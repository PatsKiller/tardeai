#!/usr/bin/env python3
"""Emit the whole-site truth evidence bundle. READ-ONLY.

Runs every read-only contract this campaign added and writes deterministic
artifacts under ``evidence/whole_site/``. A validator reproduces the campaign by
running this file, not by trusting the handoff.

  python3 scripts/emit_whole_site_evidence.py [--out evidence/whole_site]

Touches no broker, order, provider, scheduler, credential or production path. The
control-plane probes read state roots; nothing is written outside ``--out``.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib import effective_truth as et  # noqa: E402
from lib import operator_control_contract as occ  # noqa: E402
from lib import state_root_divergence as srd  # noqa: E402
from lib import whole_site_truth as wst  # noqa: E402


def _write_json(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, default=str) + "\n")


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("")
        return
    cols: list[str] = []
    for r in rows:
        for k in r:
            if k not in cols:
                cols.append(k)
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


SERVER_MODULES = ("scripts/api_v2.py", "scripts/portfolio_server.py", "scripts/portfolio_api.py")


def _store_writers(name: str) -> list[str]:
    """In-repo files that mention this store by name. Used to tell a fossil apart
    from a fork: a store only the running service writes is intentionally separate."""
    import subprocess

    try:
        out = subprocess.run(
            ["git", "grep", "-l", "-F", name, "--", "scripts/", "tools/", "bin/"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        ).stdout
    except Exception:  # noqa: BLE001
        return []
    return sorted({p for p in out.splitlines() if p.strip()})


def state_root_disposition(scan: dict) -> tuple[list[dict], dict]:
    """Disposition every audited store. Detection existing is not resolution.

    converged / intentionally-separate / producer-ahead / served-ahead /
    unreadable / unknown, and every unresolved fork carries a deferral reason.
    AGENTS.md rule 5 forbids auto-merging divergent authoritative copies, so a
    fork is reported and escalated here, never reconciled.
    """
    rows: list[dict] = []
    tally: dict[str, int] = {}
    for st in scan.get("stores", []):
        name = st["store"]
        verdict, direction = st.get("verdict"), st.get("direction")
        p_ok = (st.get("producer") or {}).get("exists")
        s_ok = (st.get("served") or {}).get("exists")
        writers = _store_writers(name)
        server_only = bool(writers) and all(w in SERVER_MODULES for w in writers)

        if verdict in ("IDENTICAL", "SAME_INODE"):
            disp, why = "converged", f"{verdict}: producer and served copies agree"
        elif not p_ok or not s_ok:
            disp, why = "unknown", f"{verdict}: one side absent (producer={p_ok} served={s_ok})"
        elif verdict == "DIVERGENT" and direction == "SERVED_AHEAD" and server_only:
            disp, why = (
                "intentionally-separate",
                f"served copy is newer and the only in-repo writers are server-process modules "
                f"({', '.join(writers)}); the running service is the sole writer and the checkout "
                f"copy is a fossil",
            )
        elif verdict == "DIVERGENT" and direction == "SERVED_AHEAD":
            disp, why = (
                "served-ahead",
                f"served copy newer by {abs(st.get('skew_seconds') or 0) / 3600:.1f}h; "
                f"writers: {', '.join(writers) or 'none in-repo'}",
            )
        elif verdict == "DIVERGENT" and direction == "PRODUCER_AHEAD":
            disp, why = (
                "producer-ahead",
                f"producer copy newer by {abs(st.get('skew_seconds') or 0) / 86400:.1f}d; the served "
                f"surface renders stale truth; writers: {', '.join(writers) or 'none in-repo'}",
            )
        else:
            disp, why = "unknown", f"verdict={verdict} direction={direction}"

        deferred = disp in ("producer-ahead", "served-ahead")
        rows.append(
            {
                "store": name,
                "verdict": verdict,
                "direction": direction,
                "byte_identical": st.get("byte_identical"),
                "skew_seconds": st.get("skew_seconds"),
                "producer_mtime_utc": (st.get("producer") or {}).get("mtime_utc"),
                "served_mtime_utc": (st.get("served") or {}).get("mtime_utc"),
                "in_repo_writers": ";".join(writers),
                "disposition": disp,
                "deferred": deferred,
                "deferred_reason": (
                    "repair is outside this campaign's authority: AGENTS.md rule 5 / WAVE G1 forbid "
                    "auto-merging divergent authoritative copies; this lane reports and escalates"
                    if deferred
                    else ""
                ),
                "evidence": why,
            }
        )
        tally[disp] = tally.get(disp, 0) + 1

    summary = {
        "schema": "StateRootDispositionLedger@v1",
        "as_of": scan.get("as_of"),
        "producer_root": scan.get("producer_root"),
        "served_root": scan.get("served_root"),
        "audited_store_count": len(rows),
        "disposition_counts": dict(sorted(tally.items())),
        "deferred_count": sum(1 for r in rows if r["deferred"]),
        "auto_remediate": False,
        "note": (
            "Detection is complete and served; RESOLUTION IS NOT. Every producer-ahead and "
            "served-ahead fork remains open and is listed store-by-store. This campaign does not "
            "claim the root-divergence problem is closed."
        ),
    }
    return rows, summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=str(ROOT / "evidence" / "whole_site"))
    args = ap.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    # ── 1. control-plane surface authority ──────────────────────────────────
    cpa = wst.control_plane_surface_authority(ROOT)
    _write_json(out / "CONTROL_PLANE_SURFACE_AUTHORITY.json", cpa)
    _write_csv(
        out / "CONTROL_PLANE_SURFACE_AUTHORITY.csv",
        [
            {
                "route": s["route"],
                "tranche": s["tranche"],
                "data_mode": s["data_mode"],
                "banner_required": s["banner_required"],
                "banner_dismissible": s["banner_dismissible"],
                "live_domain": s["live_domain"],
                "served_data_quality": (s["live"] or {}).get("data_quality"),
                "checkout_data_quality": ((s["live"] or {}).get("checkout") or {}).get("data_quality"),
                "roots_disagree": (s["live"] or {}).get("roots_disagree"),
                "bundled_fixture": (s["bundled_fixture"] or {}).get("path"),
                "reason": s["reason"],
            }
            for s in cpa["surfaces"]
        ],
    )

    # ── 2. operator identity / authorization boundary ───────────────────────
    _write_json(out / "OPERATOR_IDENTITY_BOUNDARY.json", wst.operator_identity_boundary(ROOT))

    # ── 3. /v3-next lineage ─────────────────────────────────────────────────
    _write_json(out / "V3_NEXT_LINEAGE.json", wst.v3_next_lineage(root=ROOT))

    # ── 4. route disposition ────────────────────────────────────────────────
    rd = wst.route_disposition(ROOT)
    _write_json(out / "ROUTE_DISPOSITION.json", rd)
    _write_csv(out / "ROUTE_DISPOSITION.csv", rd["routes"])

    # ── 5. operator control ledger ──────────────────────────────────────────
    occ_rep = occ.contract()
    _write_json(
        out / "OPERATOR_CONTROL_CONTRACT.json",
        {k: v for k, v in occ_rep.items() if k != "controls"},
    )
    _write_csv(out / "OPERATOR_CONTROL_CONTRACT.csv", occ.to_csv_rows(occ_rep))

    # ── 6. declared vs effective: flags, schedulers, Finviz store ───────────
    flags = et.feature_flag_truth(ROOT)
    _write_json(out / "FEATURE_FLAG_TRUTH.json", flags)
    if flags.get("flags"):
        _write_csv(out / "FEATURE_FLAG_TRUTH.csv", flags["flags"])

    sched = et.scheduler_truth()
    _write_json(out / "SCHEDULER_TRUTH.json", {k: v for k, v in sched.items() if k != "timers"})
    _write_csv(out / "SCHEDULER_TRUTH.csv", sched.get("timers", []))

    finviz = et.finviz_store_health()
    _write_json(out / "FINVIZ_STORE_HEALTH.json", finviz)

    # ── 7. state-root divergence, every audited store ───────────────────────
    scan = srd.scan(with_hashes=True)
    _write_json(
        out / "STATE_ROOT_SCAN.json",
        {k: v for k, v in scan.items() if k != "stores"},
    )
    disp_rows, disp_summary = state_root_disposition(scan)
    _write_csv(out / "STATE_ROOT_DISPOSITION.csv", disp_rows)
    _write_json(out / "STATE_ROOT_DISPOSITION.json", disp_summary)

    summary = {
        "schema": "WholeSiteEvidence@v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "authority": "READ_ONLY_ADVISORY",
        "control_plane_surface_modes": cpa["mode_counts"],
        "route_disposition_counts": rd["disposition_counts"],
        "operator_controls": occ_rep["control_count"],
        "operator_control_provability": occ_rep["provability_counts"],
        "operator_controls_with_wrong_method": occ_rep["wrong_method_count"],
        "operator_controls_unresolved_by_static_analysis": occ_rep["unregistered_count"],
        "state_root_stores": scan["store_count"],
        "state_root_status": scan["status"],
        "state_root_diverged": scan["diverged_count"],
        "state_root_disposition": disp_summary["disposition_counts"],
        "state_root_deferred": disp_summary["deferred_count"],
        "v3_next_lineage": wst.v3_next_lineage(root=ROOT)["lineage"],
        "write_gate_effective_in_this_process": wst.operator_identity_boundary(ROOT)["write_gate_effective"],
        "feature_flag_deltas": flags.get("delta_count", flags.get("status")),
        "scheduler": {
            "timer_unit_files": sched["timer_unit_files"],
            "disabled": len(sched["disabled_timers"]),
            "failed_last_run": len(sched["timers_with_failed_last_run"]),
            "never_triggered": len(sched["enabled_timers_never_triggered"]),
            "cron_active_entries": sched["cron_active_entries"],
            "cron_commented_out_jobs": sched["cron_commented_out_jobs"],
        },
        "finviz_store_state": finviz["state"],
    }
    _write_json(out / "WHOLE_SITE_EVIDENCE_SUMMARY.json", summary)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
