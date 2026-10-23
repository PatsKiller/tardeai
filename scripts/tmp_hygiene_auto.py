#!/usr/bin/env python3
"""tmp_hygiene_auto.py — the /tmp hygiene that actually deletes: plan + apply on a HOST timer, alert by inode band.

Operator, 2026-10-22 (verbatim), after /tmp (tmpfs, 1,048,576 inodes) hit 99% inodes while the daily n8n lane
``tmp-hygiene`` ran plan-only (22 candidates, 59,088 files reclaimable, nothing removed): "It needs to be able to
delete it. Just looking at it won't do anything."

WHERE IT RUNS — the host, never n8n
    linux_launchers/systemd/tradeai-tmp-hygiene-apply.timer     hourly                  -> this script
    linux_launchers/systemd/tradeai-tmp-hygiene-pressure.timer  every 5 min             -> this script --pressure-only
  AGENTS.md §24.12 (15.0.0) admits exactly one n8n deletion lane, ``disk-hygiene`` running scripts/disk_hygiene.py,
  and the allowlist ``never`` list keeps "destructive retention stages" off the n8n executor (§23.14). So deletion
  here runs on host timers (as disk-hygiene-enforcer / disk-pressure-guard do), and n8n keeps the daily --plan lane
  and the inode-band monitor (disk-usage-monitor) — scheduling evidence and alerts, never the rm. Under the n8n
  executor (TRADEAI_RUN_ID set) this script refuses.

WHAT IT DOES (one run)
  1. Refuses unless ``tmp.auto_apply.enabled`` (the kill switch) and ``tmp.auto_apply.standing_approval`` carries the
     operator, the date and the verbatim quote. That approval replaces TRADEAI_DISK_HYGIENE_GRANT on THIS path only;
     a manual ``tmp_hygiene.py --apply`` still needs the grant. The root must be /tmp.
  2. ``--pressure-only``: below ``pressure_trigger_pct`` inode use it stops (receipt only); above it, it acts unless
     an auto run finished within ``pressure_min_interval_minutes``.
  3. One non-blocking lock (state root, never /tmp: /tmp may have no inode left for a lock file).
  4. A FRESH plan of every tmp rule (scripts/tmp_hygiene.py: S, P, B, E, G, never-touch), then tmp_hygiene.apply on
     that manifest in the same run: per-item re-validation (rule, fingerprint, cwd, open fd, never-touch), item /
     byte / file caps.
  5. Writes: the plan manifest (``manifest_latest_name``), the run report (``report_latest_name``), one JSONL line per
     removed item (path, rule, bytes, files, age_days, how) in the monthly deletions ledger, and a LaneRunReceipt@v2
     (lane ``tmp-hygiene-apply``, or ``tmp-hygiene-pressure`` for a below-trigger check).
  6. Inode use after the run: >= alert_p1_pct -> P1, >= alert_p2_pct -> P2, through the existing host notifier
     (telegram_alert.send_telegram, deduped by lib/alert_condition_state like disk_pressure_guard); recovery is said
     once. ``--dry-run`` prints the plan and what an apply would remove; it writes, deletes and sends nothing.

Exit: 0 = done (including below-trigger, lock busy, kill switch off); 1 = refused (approval missing, wrong root,
n8n executor), rules unreadable or a write failed; 2 = usage. MBI_BEHAVIOR = 0. No broker, no DB.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import disk_hygiene as DH  # noqa: E402
from scripts import tmp_hygiene as TH  # noqa: E402
from scripts.lib import lane_last_receipt as R  # noqa: E402

LANE_ID = TH.APPLY_LANE_ID  # "tmp-hygiene-apply"
PRESSURE_LANE_ID = "tmp-hygiene-pressure"
SCRIPT = "scripts/tmp_hygiene_auto.py"
RUN_ID_ENV = "TRADEAI_RUN_ID"
CONDITION_KEY = "system_health:tmp_inodes"
REPORT_SCHEMA = "TmpHygieneAutoRun@v1"
DELETION_SCHEMA = "TmpHygieneDeletion@v1"
APPROVAL_FIELDS = ("id", "operator", "date", "quote")


class Refused(Exception):
    pass


def auto_cfg(t: Mapping[str, Any]) -> dict[str, Any]:
    aa = t.get("auto_apply")
    if not isinstance(aa, dict):
        raise DH.RulesError("rules_missing:tmp.auto_apply")
    for key in ("enabled", "standing_approval", "pressure_trigger_pct", "pressure_min_interval_minutes",
                "alert_p2_pct", "alert_p1_pct", "realert_minutes", "manifest_latest_name", "report_latest_name",
                "deletions_ledger_pattern"):
        if key not in aa:
            raise DH.RulesError(f"rules_missing:tmp.auto_apply.{key}")
    if not float(aa["pressure_trigger_pct"]) < float(aa["alert_p2_pct"]) < float(aa["alert_p1_pct"]) <= 100.0:
        raise DH.RulesError("rules_bad:tmp.auto_apply thresholds must be trigger < p2 < p1 <= 100")
    return aa


def approval_id(aa: Mapping[str, Any]) -> str:
    """The standing operator approval's id; raises Refused when any provenance field is empty."""
    ap = aa.get("standing_approval")
    if not isinstance(ap, dict) or any(not str(ap.get(k) or "").strip() for k in APPROVAL_FIELDS):
        raise Refused("standing_approval_incomplete")
    return str(ap["id"])


def band_of(pct: Optional[float], aa: Mapping[str, Any]) -> str:
    if pct is None:
        return "unknown"
    if pct >= float(aa["alert_p1_pct"]):
        return "P1"
    if pct >= float(aa["alert_p2_pct"]):
        return "P2"
    return "ok"


def default_notify(text: str, priority: str) -> str:
    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        from telegram_alert import send_telegram  # noqa: PLC0415 (host-only lane; never an n8n closure)

        ok = send_telegram(text, message_class="operator_alert", priority=priority, producer="tmp_hygiene_auto")
        return "accepted" if ok else "send_returned_false"
    except Exception as exc:  # noqa: BLE001 - alerting never raises past the reclaim
        return f"error:{type(exc).__name__}"


def alert(
    pct: Optional[float],
    aa: Mapping[str, Any],
    run: Mapping[str, Any],
    *,
    notify: Callable[[str, str], str],
    state_path: Optional[Path],
) -> dict[str, Any]:
    band = band_of(pct, aa)
    if band == "unknown":
        return {"band": band, "notify": False}
    try:
        from scripts.lib.alert_condition_state import observe

        obs = observe(CONDITION_KEY, band, alertable=band != "ok", path=state_path,
                      min_realert_minutes=int(aa["realert_minutes"]), extra={"inodes_used_pct": pct})
    except Exception as exc:  # noqa: BLE001
        return {"band": band, "notify": False, "error": f"{type(exc).__name__}"}
    out: dict[str, Any] = {"band": band, "action": obs.get("action"), "notify": bool(obs.get("notify"))}
    if out["notify"]:
        removed = run.get("removed_count", 0)
        files = run.get("reclaimed_files", 0)
        if band == "ok":
            text = f"/tmp inodes recovered: {pct:.1f}% used (tmp-hygiene removed {removed} items, {files} files)"
            priority = "P2"
        else:
            level = aa["alert_p1_pct"] if band == "P1" else aa["alert_p2_pct"]
            text = (f"/tmp inodes {pct:.1f}% used ({band}: >= {level}%)"
                    f"; tmp-hygiene removed {removed} items / {files} files this run;"
                    f" {run.get('remaining_candidates', 0)} candidates left; manifest {run.get('manifest')}")
            priority = band
        out["priority"] = priority
        out["sent"] = notify(text, priority)
    return out


def _last_finished(path: Path) -> Optional[datetime]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        return datetime.fromisoformat(doc["finished_at"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def append_deletions(ledger: Path, rows: list[dict[str, Any]], run_id: str, approval: str) -> None:
    if not rows:
        return
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with ledger.open("a", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps({"schema": DELETION_SCHEMA, "run": run_id, "approval": approval, **r},
                                separators=(",", ":")) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def run(
    *,
    rules: Mapping[str, Any],
    t: Mapping[str, Any],
    now: datetime,
    state_root: Optional[Path],
    pressure_only: bool,
    dry_run: bool,
    allow_test_root: bool = False,
    notify: Callable[[str, str], str] = default_notify,
    alert_state_path: Optional[Path] = None,
    wall_start: Optional[datetime] = None,
) -> int:
    wall_start = wall_start or datetime.now(timezone.utc)
    aa = auto_cfg(t)
    if os.environ.get(RUN_ID_ENV):
        raise Refused("n8n_executor_never_applies")
    if os.path.realpath(t["_root"]) != TH.REQUIRED_TMP_ROOT and not allow_test_root:
        raise Refused(f"tmp_root_must_be_{TH.REQUIRED_TMP_ROOT}")
    if not aa["enabled"]:
        print(json.dumps({"mode": "auto", "skipped": "auto_apply_disabled (kill switch: tmp.auto_apply.enabled)"}))
        return 0
    approval = approval_id(aa)
    mdir = DH.manifest_dir(rules, state_root)
    fs = TH.statvfs_inodes(t["_root"])
    pct = fs["inodes_used_pct"] if fs else None
    report_path = mdir / aa["report_latest_name"]
    if pressure_only:
        trigger = float(aa["pressure_trigger_pct"])
        last = _last_finished(report_path)
        recent = last is not None and (now - last).total_seconds() < 60 * float(aa["pressure_min_interval_minutes"])
        if pct is None or pct < trigger or recent:
            why = "below_trigger" if (pct is None or pct < trigger) else "auto_run_recent"
            print(json.dumps({"mode": "pressure", "inodes_used_pct": pct, "trigger_pct": trigger, "skipped": why}))
            if not dry_run:
                R.write_lane_receipt(
                    PRESSURE_LANE_ID, ok=True, exit_code=0, started_at=wall_start, script=SCRIPT,
                    summary={"inodes_used_pct": pct, "trigger_pct": trigger, "acted": False, "why": why},
                    path=R.receipt_path(PRESSURE_LANE_ID, state_root),
                    output={"produced_count": 0, "attempted_count": 0, "skipped_reasons": {why: 1},
                            "empty_reason": why},
                )
            return 0

    m = TH.plan(rules, t, now)
    if dry_run:
        rows = [{"path": r["path"], "rule": r["rule"], "files": r.get("file_count"),
                 "age_days": (r.get("evidence") or {}).get("idle_days")} for r in m["items"]]
        print(json.dumps({"dry_run": True, "inodes_used_pct": pct, "would_remove": len(rows),
                          "would_reclaim_files": m["totals"]["reclaimable_files"], "approval": approval}))
        print(TH.human_summary(m, int(rules["manifest"].get("top_n") or 20)))
        return 0

    from scripts.lib.atomic_json_store import atomic_write_json

    mdir.mkdir(parents=True, exist_ok=True)
    lock_fh = open(mdir / "tmp_hygiene_auto.lock", "a+")  # noqa: SIM115 - held for the run
    try:
        fcntl.flock(lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print(json.dumps({"mode": "auto", "skipped": "lock_busy"}))
        lock_fh.close()
        return 0
    try:
        m["mode"] = "auto_plan"
        m["authority"] = {"standing_approval": aa["standing_approval"]}
        mpath = mdir / aa["manifest_latest_name"]
        atomic_write_json(mpath, m, indent=1)
        rep = TH.apply(mpath, rules, t, now, grant=f"standing:{approval}", run_id=None)
        after = TH.statvfs_inodes(t["_root"])
        pct_after = after["inodes_used_pct"] if after else None
        run_id = now.strftime("%Y%m%dT%H%M%SZ")
        ledger = mdir / aa["deletions_ledger_pattern"].replace("{yyyymm}", now.strftime("%Y%m"))
        append_deletions(ledger, rep["removed"], run_id, approval)
        doc = {
            "schema": REPORT_SCHEMA,
            "run": run_id,
            "trigger": "pressure" if pressure_only else "hourly",
            "authority": aa["standing_approval"],
            "manifest": str(mpath),
            "deletions_ledger": str(ledger),
            "inodes_used_pct_before": pct,
            "inodes_used_pct_after": pct_after,
            "candidates": m["totals"]["candidates"],
            "removed_count": len(rep["removed"]),
            "reclaimed_files": rep.get("reclaimed_files", 0),
            "reclaimed_bytes": rep.get("reclaimed_bytes", 0),
            "refused": rep.get("refused"),
            "removed": rep["removed"],
            "skipped": rep["skipped"],
            # the logical clock when injected (tests), else the wall clock: the pressure interval compares to `now`
            "finished_at": max(now, datetime.now(timezone.utc)).isoformat(),
        }
        doc["remaining_candidates"] = doc["candidates"] - doc["removed_count"]
        doc["alert"] = alert(pct_after, aa, doc, notify=notify, state_path=alert_state_path)
        atomic_write_json(report_path, doc, indent=1)
        ok = not rep.get("refused")
        R.write_lane_receipt(
            LANE_ID, ok=ok, exit_code=0 if ok else 1, started_at=wall_start, script=SCRIPT,
            summary={k: doc[k] for k in ("trigger", "candidates", "removed_count", "reclaimed_files",
                                          "reclaimed_bytes", "inodes_used_pct_before", "inodes_used_pct_after",
                                          "refused")} | {"report": str(report_path), "approval": approval},
            error=rep.get("refused"),
            path=R.receipt_path(LANE_ID, state_root),
            output={"produced_count": 1, "attempted_count": 1, "skipped_reasons": {}, "empty_reason": None,
                    "output_evidence": [{"kind": "file", "ref": str(report_path),
                                         "removed": doc["removed_count"], "reclaimed_files": doc["reclaimed_files"]}]},
        )
        if pressure_only:  # the pressure lane's own heartbeat also advances when it acted
            R.write_lane_receipt(
                PRESSURE_LANE_ID, ok=ok, exit_code=0 if ok else 1, started_at=wall_start, script=SCRIPT,
                summary={"inodes_used_pct": pct, "trigger_pct": float(aa["pressure_trigger_pct"]), "acted": True,
                         "removed_count": doc["removed_count"], "report": str(report_path)},
                path=R.receipt_path(PRESSURE_LANE_ID, state_root),
                output={"produced_count": 1, "attempted_count": 1, "skipped_reasons": {}, "empty_reason": None,
                        "output_evidence": [{"kind": "file", "ref": str(report_path)}]},
            )
        print(json.dumps({k: doc[k] for k in ("trigger", "candidates", "removed_count", "reclaimed_files",
                                              "inodes_used_pct_before", "inodes_used_pct_after", "refused")}
                         | {"alert": doc["alert"].get("band")}))
        return 0 if ok else 1
    finally:
        fcntl.flock(lock_fh, fcntl.LOCK_UN)
        lock_fh.close()


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--pressure-only", action="store_true", help="act only at >= pressure_trigger_pct inode use")
    ap.add_argument("--dry-run", action="store_true", help="plan and print what would be removed; writes nothing")
    ap.add_argument("--rules", help="rules file (default config/disk_hygiene_rules.json)")
    ap.add_argument("--state-root", help="persistent-state root (default TRADEAI_STATE_ROOT / resolver)")
    ap.add_argument("--home", help=argparse.SUPPRESS)  # tests
    ap.add_argument("--now", help=argparse.SUPPRESS)  # tests: aware ISO 8601
    ap.add_argument("--allow-test-root", action="store_true", help=argparse.SUPPRESS)  # tests: a fake /tmp
    ap.add_argument("--alert-state", help=argparse.SUPPRESS)  # tests
    try:
        a = ap.parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code else 0
    wall_start = datetime.now(timezone.utc)
    now = DH._parse_now(a.now)
    if now is None:
        print("--now must be an aware ISO 8601 timestamp", file=sys.stderr)
        return 2
    try:
        rules = DH.load_rules(Path(a.rules) if a.rules else None, home=Path(a.home) if a.home else None)
        t = TH.tmp_rules(rules)
        return run(rules=rules, t=t, now=now, state_root=Path(a.state_root) if a.state_root else None,
                   pressure_only=a.pressure_only, dry_run=a.dry_run, allow_test_root=a.allow_test_root,
                   alert_state_path=Path(a.alert_state) if a.alert_state else None, wall_start=wall_start)
    except Refused as exc:
        print(json.dumps({"ok": False, "refused": str(exc)}))
        return 1
    except (DH.RulesError, KeyError, TypeError, ValueError, OSError) as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"[:300]}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
