#!/usr/bin/env python3
"""n8n_migration_board.py — where every lane of the n8n scheduler-of-record program stands.

Stream G of the 2026-10-08 program (plan `streamed-humming-wolf`, 71 lanes in tranches N1–N6).
Reads, never changes: the tranche list (`config/n8n_migration_tranches.json`), the lane registry
(scheduler of record), the coordination ledger `runs` table through the read-only projection, the
`RunReceipt@v1` files under `data/runtime/n8n_runs/`, the `CutoverReceipt@v1` files under
`data/runtime/n8n_cutover/`, the readiness verdicts (`n8n_lane_readiness_last.json`) and the lane's
own output signal (lane_registry.observe_signal, read-only). Every input may be absent: the board
then says NOT_STARTED / NO_REGISTRY_ROW / UNVERIFIABLE instead of guessing.

    python3 scripts/n8n_migration_board.py                 # JSON to stdout, nothing written
    python3 scripts/n8n_migration_board.py --markdown      # operator table
    python3 scripts/n8n_migration_board.py --write         # data/runtime/n8n_migration_board_last.json

Phase per lane: NOT_STARTED | SHADOW (a dry_run RunReceipt exists) | CANARY (a live RunReceipt
while the registry still says cron/systemd) | CUT_OVER (registry scheduler.kind == n8n) |
ROLLED_BACK (the last cutover receipt is a rollback). Served by GET /api/v2/coordination/migration-board.

AUTHORITY: READ_ONLY_ADVISORY. No cutover, no rollback, no send, no write except its own receipt.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.lib import lane_registry as LR  # noqa: E402
from scripts.lib.n8n_coordination_projection import RUNS_RECEIPT_DIR, ledger_path, project_runs  # noqa: E402
from scripts.lib.n8n_pilot_observations import served_sha, state_root  # noqa: E402

SCHEMA = "N8nMigrationBoard@v1"
TRANCHES_SCHEMA = "N8nMigrationTranches@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
NO_CONSUMER_REASON = (
    "Operator-run board for the n8n scheduler-of-record program; its receipt is served by "
    "GET /api/v2/coordination/migration-board (scripts/api_v2.py reads the file, not this module). "
    "No cron line until the operator installs one."
)
TRANCHES_PATH = ROOT / "config" / "n8n_migration_tranches.json"
BOARD_REL = "data/runtime/n8n_migration_board_last.json"
CUTOVER_DIR_REL = "data/runtime/n8n_cutover"
READINESS_REL = "data/runtime/n8n_lane_readiness_last.json"
# Source of truth: scripts/n8n_run_executor.py LAST_REL (the heartbeat sits beside, not inside, n8n_runs/).
# Kept as a literal so this reader does not import the executor entrypoint; the drift test
# tests/test_n8n_migration_board_20261008.py asserts executor, board and fan-in agree.
EXECUTOR_LAST_REL = "data/runtime/n8n_run_executor_last.json"
PHASES = ("NOT_STARTED", "SHADOW", "CANARY", "CUT_OVER", "ROLLED_BACK")
RUN_FAILURE_STATES = {"RUN_FAILED", "RUN_TIMEOUT"}
STALE_FACTOR = 2.0          # output signal older than 2x cadence = rollback trigger (plan §Rollback triggers)
FLAG_RUN_FAILED_AFTER_CUTOVER = "RUN_FAILED_AFTER_CUTOVER"
FLAG_OUTPUT_SIGNAL_STALE = "OUTPUT_SIGNAL_STALE"
FLAG_DOUBLE_SCHEDULER = "DOUBLE_SCHEDULER"
FLAG_NO_REGISTRY_ROW = "NO_REGISTRY_ROW"
FLAG_RUN_REFUSED = "RUN_REFUSED"
FLAG_EXECUTOR_STALLED = "EXECUTOR_STALLED"


def _load_json(p: Path) -> Optional[dict]:
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else None
    except (OSError, ValueError):
        return None


def _ts(v: Any) -> Optional[datetime]:
    return LR._parse_ts(v)


def _hours_since(v: Any, now: datetime) -> Optional[float]:
    d = _ts(v)
    return None if d is None else round((now - d).total_seconds() / 3600.0, 2)


def load_tranches(path: Optional[Path] = None) -> dict[str, Any]:
    doc = json.loads((path or TRANCHES_PATH).read_text(encoding="utf-8"))
    if doc.get("schema") != TRANCHES_SCHEMA:
        raise ValueError(f"unexpected tranche schema {doc.get('schema')!r}")
    return doc


def _run_rows(root: Path, ledger: Optional[Path]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Union of ledger `runs` rows and RunReceipt files, keyed by run_id (receipt wins on detail)."""
    by_id: dict[str, dict[str, Any]] = {}
    proj = project_runs(ledger, limit=500)
    for it in proj.get("items") or []:
        if it.get("run_id"):
            by_id[str(it["run_id"])] = dict(it)
    rdir = root / RUNS_RECEIPT_DIR
    n_files = 0
    if rdir.is_dir():
        for p in sorted(rdir.glob("*.json")):
            if p.name == "n8n_run_executor_last.json":
                continue
            doc = _load_json(p)
            if not doc or not doc.get("run_id"):
                continue
            n_files += 1
            rid = str(doc["run_id"])
            row = by_id.get(rid, {})
            row.update({k: doc.get(k, row.get(k)) for k in
                        ("run_id", "lane_id", "mode", "state", "exit_code", "duration_s", "started_at", "finished_at",
                         "lock_skipped", "timed_out", "output_signal_mtime_after", "code_sha")})
            row.setdefault("receipt_ref", f"{RUNS_RECEIPT_DIR}/{p.name}")
            by_id[rid] = row
    src = {"ledger_status": proj.get("status"), "ledger": proj.get("ledger"), "ledger_rows": proj.get("count", 0),
           "receipt_files": n_files}
    return list(by_id.values()), src


def _latest(rows: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    def key(r: dict[str, Any]) -> str:
        return str(r.get("finished_at") or r.get("started_at") or r.get("requested_at") or "")
    return max(rows, key=key) if rows else None


def _cutover_receipts(root: Path) -> dict[str, dict[str, Any]]:
    """Latest CutoverReceipt@v1 per lane (by `at`, then file name)."""
    out: dict[str, dict[str, Any]] = {}
    cdir = root / CUTOVER_DIR_REL
    if not cdir.is_dir():
        return out
    for p in sorted(cdir.glob("*.json")):
        if p.name == "n8n_cutover_last.json":
            continue
        doc = _load_json(p)
        lane = doc.get("lane_id") if doc else None
        if not lane:
            continue
        doc = dict(doc)
        doc["_ref"] = f"{CUTOVER_DIR_REL}/{p.name}"
        prev = out.get(lane)
        if prev is None or str(doc.get("at") or "") >= str(prev.get("at") or ""):
            out[lane] = doc
    return out


def _readiness(root: Path) -> dict[str, dict[str, Any]]:
    doc = _load_json(root / READINESS_REL)
    if not doc:
        return {}
    lanes = doc.get("lanes")
    out: dict[str, dict[str, Any]] = {}
    if isinstance(lanes, dict):
        for k, v in lanes.items():
            out[str(k)] = v if isinstance(v, dict) else {"verdict": v}
    elif isinstance(lanes, list):
        for v in lanes:
            if isinstance(v, dict) and v.get("lane_id"):
                out[str(v["lane_id"])] = v
    return out


def _cron_present(match: Optional[str], cron_text: Optional[str]) -> Optional[bool]:
    if cron_text is None or not match:
        return None
    for line in cron_text.splitlines():
        s = line.strip()
        if s and not s.startswith("#") and match in s:
            return True
    return False


def lane_row(spec: dict[str, Any], tranche: str, *, reg_row: Optional[dict[str, Any]], runs: list[dict[str, Any]],
             cutover: Optional[dict[str, Any]], readiness: Optional[dict[str, Any]], now: datetime, root: Path,
             cron_text: Optional[str], units: Optional[list[str]], executor_stalled: bool) -> dict[str, Any]:
    lane_id = spec["lane_id"]
    flags: list[str] = []
    sched = (reg_row or {}).get("scheduler") or {}
    kind = str(sched.get("kind") or "") if reg_row else ""
    scheduler_of_record = kind if kind in ("cron", "systemd", "n8n") else (kind or "unregistered")
    if reg_row is None:
        flags.append(FLAG_NO_REGISTRY_ROW)
    last = _latest(runs)
    has_live = any(str(r.get("mode") or "") == "live" for r in runs)
    has_dry = any(str(r.get("mode") or "") == "dry_run" for r in runs)
    if cutover and str(cutover.get("action") or "") == "rollback" and cutover.get("applied") is not False:
        phase = "ROLLED_BACK"
    elif kind == "n8n":
        phase = "CUT_OVER"
    elif has_live:
        phase = "CANARY"
    elif has_dry:
        phase = "SHADOW"
    else:
        phase = "NOT_STARTED"
    last_run = None
    if last:
        last_run = {k: last.get(k) for k in ("run_id", "mode", "state", "exit_code", "duration_s", "finished_at")}
        if phase == "CUT_OVER" and str(last.get("state") or "") in RUN_FAILURE_STATES:
            flags.append(FLAG_RUN_FAILED_AFTER_CUTOVER)
        if str(last.get("state") or "") == "RUN_REFUSED":
            flags.append(FLAG_RUN_REFUSED)
    cadence = (reg_row or {}).get("expected_cadence_hours")
    signal_age_h: Optional[float] = None
    signal_detail: Optional[str] = None
    if reg_row is not None and reg_row.get("output_signal"):
        obs = LR.observe_signal(reg_row["output_signal"], root=root)
        signal_detail = obs.get("detail")
        if obs.get("last_output_at"):
            signal_age_h = _hours_since(obs["last_output_at"], now)
        elif not obs.get("readable", True):
            signal_detail = f"UNVERIFIABLE: {obs.get('detail')}"
    try:
        cad = float(cadence) if cadence is not None else None
    except (TypeError, ValueError):
        cad = None
    if signal_age_h is not None and cad and signal_age_h > STALE_FACTOR * cad:
        flags.append(FLAG_OUTPUT_SIGNAL_STALE)
    match = sched.get("match") or spec.get("match")
    double = None
    if kind == "n8n":
        cron_hit = _cron_present(match, cron_text)
        timer_hit = None
        if units is not None:
            expr = str(sched.get("expression") or "")
            retired = str(sched.get("retired_unit") or sched.get("timer") or "")
            timer_hit = bool(retired) and retired in units or (expr.endswith(".timer") and expr in units)
        double = bool(cron_hit) or bool(timer_hit)
        if double:
            flags.append(FLAG_DOUBLE_SCHEDULER)
    if kind == "n8n" and executor_stalled:
        flags.append(FLAG_EXECUTOR_STALLED)
    rollback_ready = bool(cutover and cutover.get("crontab_backup"))
    verdict = None
    reasons: list[str] = []
    if readiness:
        verdict = readiness.get("verdict")
        reasons = [str(r) for r in (readiness.get("reasons") or [])][:6]
    return {
        "lane_id": lane_id, "tranche": tranche, "registry_row": reg_row is not None,
        "registry_state": (reg_row or {}).get("state"), "scheduler_of_record": scheduler_of_record,
        "scheduler_expression": sched.get("expression"), "phase": phase, "run_count": len(runs),
        "last_run": last_run, "expected_cadence_hours": cadence, "output_signal_age_h": signal_age_h,
        "output_signal_detail": signal_detail, "rollback_ready": rollback_ready,
        "cutover": None if not cutover else {k: cutover.get(k) for k in ("action", "scheduler_before", "scheduler_after", "applied", "at", "_ref")},
        "readiness": verdict, "readiness_reasons": reasons, "risk_flags": flags, "double_scheduler": double,
        "note": spec.get("note"),
    }


def build_board(*, root: Optional[Path] = None, registry: Optional[dict[str, Any]] = None,
                tranches: Optional[dict[str, Any]] = None, now: Optional[datetime] = None,
                ledger: Optional[Path] = None, cron_text: Optional[str] = None,
                units: Optional[list[str]] = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    root = Path(root) if root else state_root()
    tr = tranches or load_tranches()
    reg = registry if registry is not None else LR.load_registry()
    by_lane = {str(r.get("lane_id")): r for r in (reg.get("lanes") or [])}
    runs, run_src = _run_rows(root, ledger or ledger_path())
    runs_by_lane: dict[str, list[dict[str, Any]]] = {}
    for r in runs:
        runs_by_lane.setdefault(str(r.get("lane_id")), []).append(r)
    cutovers = _cutover_receipts(root)
    ready = _readiness(root)
    n8n_cadences = [float(r.get("expected_cadence_hours")) for r in by_lane.values()
                    if ((r.get("scheduler") or {}).get("kind") == "n8n") and r.get("expected_cadence_hours")]
    exec_doc = _load_json(root / EXECUTOR_LAST_REL)
    exec_age_h = _hours_since((exec_doc or {}).get("finished_at") or (exec_doc or {}).get("as_of") or (exec_doc or {}).get("at"), now)
    executor_stalled = bool(n8n_cadences and exec_age_h is not None and exec_age_h > STALE_FACTOR * min(n8n_cadences))
    lanes: list[dict[str, Any]] = []
    for tname, tdoc in (tr.get("tranches") or {}).items():
        for spec in tdoc.get("lanes") or []:
            lid = spec["lane_id"]
            lanes.append(lane_row(spec, tname, reg_row=by_lane.get(lid), runs=runs_by_lane.get(lid, []),
                                  cutover=cutovers.get(lid), readiness=ready.get(lid), now=now, root=root,
                                  cron_text=cron_text, units=units, executor_stalled=executor_stalled))
    per_tranche: dict[str, dict[str, Any]] = {}
    for row in lanes:
        t = per_tranche.setdefault(row["tranche"], {"lanes": 0, "by_phase": {p: 0 for p in PHASES}, "risks": 0, "no_registry_row": 0})
        t["lanes"] += 1
        t["by_phase"][row["phase"]] += 1
        t["risks"] += len([f for f in row["risk_flags"] if f != FLAG_NO_REGISTRY_ROW])
        t["no_registry_row"] += int(not row["registry_row"])
    open_risks = [{"lane_id": r["lane_id"], "tranche": r["tranche"], "flag": f, "phase": r["phase"]}
                  for r in lanes for f in r["risk_flags"] if f != FLAG_NO_REGISTRY_ROW]
    totals = {p: sum(t["by_phase"][p] for t in per_tranche.values()) for p in PHASES}
    return {
        "schema": SCHEMA, "authority": AUTHORITY, "as_of": now.isoformat(), "served_sha": served_sha() or None,
        "state_root": str(root), "status": "OK", "lane_count": len(lanes),
        "sources": {"tranches": str(TRANCHES_PATH.relative_to(ROOT)), "registry_lanes": len(by_lane), **run_src,
                    "cutover_receipts": len(cutovers), "readiness_lanes": len(ready),
                    "executor_last_age_h": exec_age_h, "executor_stalled": executor_stalled,
                    "crontab_read": cron_text is not None, "systemd_read": units is not None},
        "summary": {"per_tranche": per_tranche, "by_phase": totals, "open_risks": open_risks,
                    "open_risk_count": len(open_risks), "no_registry_row": sum(1 for r in lanes if not r["registry_row"])},
        "lanes": lanes,
    }


def render_markdown(board: dict[str, Any]) -> str:
    s = board.get("summary") or {}
    out = [f"# n8n migration board — {board.get('as_of')}", "",
           f"lanes {board.get('lane_count')} · phases " + " · ".join(f"{k} {v}" for k, v in (s.get('by_phase') or {}).items())
           + f" · open risks {s.get('open_risk_count', 0)} · no registry row {s.get('no_registry_row', 0)}", "",
           "| tranche | lane | scheduler | phase | last run | signal age h | ready | rollback | risk |", "|---|---|---|---|---|---|---|---|---|"]
    for r in board.get("lanes") or []:
        lr = r.get("last_run") or {}
        last = f"{lr.get('mode')} {lr.get('state')} exit={lr.get('exit_code')} {lr.get('finished_at') or ''}".strip() if lr else "—"
        age = "—" if r.get("output_signal_age_h") is None else f"{r['output_signal_age_h']:.1f}"
        out.append(f"| {r['tranche']} | {r['lane_id']} | {r['scheduler_of_record']} | {r['phase']} | {last} | {age} | "
                   f"{r.get('readiness') or '—'} | {'yes' if r.get('rollback_ready') else 'no'} | {', '.join(r.get('risk_flags') or []) or '—'} |")
    return "\n".join(out) + "\n"


def _host_probe() -> tuple[Optional[str], Optional[list[str]]]:
    """crontab -l and the timer names, both fail-soft (CI runners have neither)."""
    import subprocess
    cron_text = None
    try:
        r = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=30)
        cron_text = r.stdout if r.returncode == 0 else None
    except Exception:  # noqa: BLE001
        cron_text = None
    try:
        units = [str(u.get("expression") or "") for u in LR.discover_systemd()]
    except Exception:  # noqa: BLE001
        units = None
    return cron_text, units


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--write", action="store_true", help="write the receipt under the state root")
    ap.add_argument("--markdown", action="store_true", help="print the operator table instead of JSON")
    ap.add_argument("--receipt", default=None, help="receipt path override (default state_root/" + BOARD_REL + ")")
    ap.add_argument("--ledger", default=None, help="coordination ledger path override")
    ap.add_argument("--no-host", action="store_true", help="skip crontab/systemd probes (double-scheduler flag unverifiable)")
    args = ap.parse_args(argv)
    root = state_root()
    cron_text, units = (None, None) if args.no_host else _host_probe()
    board = build_board(root=root, ledger=Path(args.ledger) if args.ledger else None, cron_text=cron_text, units=units)
    if args.write:
        out = Path(args.receipt) if args.receipt else root / BOARD_REL
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(board, indent=1, default=str) + "\n", encoding="utf-8")
        os.replace(tmp, out)
        board["written"] = str(out)
    if args.markdown:
        sys.stdout.write(render_markdown(board))
    else:
        s = board["summary"]
        print(json.dumps({"schema": SCHEMA, "as_of": board["as_of"], "lanes": board["lane_count"], "by_phase": s["by_phase"],
                          "open_risks": s["open_risk_count"], "no_registry_row": s["no_registry_row"],
                          "written": board.get("written")}, default=str) if args.write else json.dumps(board, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
