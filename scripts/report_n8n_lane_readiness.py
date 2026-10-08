#!/usr/bin/env python3
"""report_n8n_lane_readiness.py — is ONE registry lane ready to hand its schedule to n8n?

The n8n scheduler-of-record program (2026-10-08) moves lanes shadow → canary → cutover. This report
answers "may this lane be cut over now" from EXISTING evidence only — it probes nothing, runs
nothing and writes only its own receipt:

  (a) the lane has a config/lane_registry.json row and it is ACTIVE;
  (b) its host scheduler is present exactly once (cron: `scheduler.match` on exactly one
      uncommented line; systemd: the timer unit is enabled — from --host-state-json or systemctl);
  (c) its output_signal is fresh within 2 × expected_cadence_hours;
  (d) when the cron line names a lock (safe_flock.sh / flock), the last 3 `completed` events
      for that component in logs/safe_flock_events.jsonl have exit_code 0;
  (e) a shadow RunReceipt (mode dry_run, exit 0) and a canary RunReceipt (mode live, exit 0)
      exist for the lane — from the run ledger `runs` table or data/runtime/n8n_runs/*.json.

Verdict: GO (every check holds), GO_WITH_NOTES (holds, with notes: no lock to judge, fewer than
3 completions on record, a lane already kind n8n), NO_GO (a blocker, named).

    python3 scripts/report_n8n_lane_readiness.py --lane <lane_id>            # table only
    python3 scripts/report_n8n_lane_readiness.py --lane <lane_id> --write    # + data/runtime/n8n_lane_readiness_last.json

AUTHORITY: READ_ONLY_ADVISORY. No crontab, systemd, DB or send.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.lib.lane_registry import (  # noqa: E402
    _parse_ts,
    load_registry,
    n8n_ledger_path,
    n8n_runs_dir,
    observe_signal,
    state_root,
)
from scripts.report_tranche_b_readiness import crontab_text  # noqa: E402

SCHEMA = "N8nLaneReadiness@v1"
NO_CONSUMER_REASON = (
    "Per-lane n8n cutover readiness receipt (2026-10-08). Read by the operator and the migration board before "
    "`cutover_lane.sh --apply`; produced on demand under the cutover grant, no scheduled lane consumes it yet."
)
AUTHORITY = "READ_ONLY_ADVISORY"
RECEIPT_REL = "data/runtime/n8n_lane_readiness_last.json"
SAFE_FLOCK_EVENTS_REL = "logs/safe_flock_events.jsonl"
COMPLETIONS_WANTED = 3
LOCK_RE = re.compile(r"(?:safe_flock\.sh|flock(?:\s+-\S+)*)\s+(\S+\.lock)\b")
SHADOW_MODE = "dry_run"
CANARY_MODE = "live"
RUN_RECEIPT_SCHEMA = "RunReceipt@v1"


def lane_row(reg: dict[str, Any], lane_id: str) -> Optional[dict[str, Any]]:
    for row in reg.get("lanes") or []:
        if str(row.get("lane_id") or "") == lane_id:
            return row
    return None


def host_scheduler(
    row: dict[str, Any], *, text: str, host_state: Optional[dict[str, Any]], timer_state_fn=None
) -> dict[str, Any]:
    sched = row.get("scheduler") or {}
    kind = str(sched.get("kind") or "none")
    match = str(sched.get("match") or sched.get("expression") or "")
    if kind == "cron" or (kind == "n8n" and not match.endswith(".timer")):
        live = [ln for ln in text.splitlines() if match and match in ln and not ln.lstrip().startswith("#")]
        commented = [ln for ln in text.splitlines() if match and match in ln and ln.lstrip().startswith("#")]
        return {
            "kind": kind,
            "match": match,
            "live_count": len(live),
            "commented_count": len(commented),
            "line": live[0] if len(live) == 1 else None,
            "present_once": len(live) == 1,
            "measured": True,
        }
    if kind == "systemd" or (kind == "n8n" and match.endswith(".timer")):
        timers = (host_state or {}).get("timers") or {}
        st = timers.get(match) if match in timers else (timer_state_fn(match) if timer_state_fn else None)
        if not st:
            return {
                "kind": kind,
                "match": match,
                "present_once": False,
                "measured": False,
                "detail": "timer state unavailable (pass --host-state-json)",
            }
        enabled = str(st.get("unit_file_state") or "").lower() in {"enabled", "enabled-runtime", "static"}
        return {
            "kind": kind,
            "match": match,
            "present_once": enabled,
            "measured": True,
            "unit_file_state": st.get("unit_file_state"),
            "sub_state": st.get("sub_state"),
        }
    return {
        "kind": kind,
        "match": match,
        "present_once": False,
        "measured": False,
        "detail": f"kind {kind!r} has no host scheduler to check",
    }


def safe_flock_completions(component: str, *, state: Path, limit: int = COMPLETIONS_WANTED) -> dict[str, Any]:
    p = state / SAFE_FLOCK_EVENTS_REL
    if not p.exists():
        return {"component": component, "path": str(p), "completions": [], "detail": "events file absent"}
    rows: list[dict[str, Any]] = []
    try:
        with p.open("rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            fh.seek(max(0, size - 2_000_000))
            chunk = fh.read().decode("utf-8", "replace")
        for ln in chunk.splitlines():
            if f'"component":"{component}"' not in ln or '"event_type":"completed"' not in ln:
                continue
            try:
                rows.append(json.loads(ln))
            except ValueError:
                continue
    except OSError as exc:
        return {"component": component, "path": str(p), "completions": [], "detail": f"unreadable: {exc}"}
    last = rows[-limit:]
    return {
        "component": component,
        "path": str(p),
        "completions": [{"ts": r.get("ts"), "exit_code": r.get("exit_code")} for r in last],
        "detail": "tail 2 MB scanned",
    }


def _runs_from_ledger(lane_id: str, path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
        try:
            conn.row_factory = sqlite3.Row
            cur = conn.execute(
                "SELECT run_id, mode, state, exit_code, finished_at FROM runs "
                "WHERE lane_id = ? AND finished_at IS NOT NULL ORDER BY finished_at DESC",
                (lane_id,),
            )
            return [dict(r) | {"source": "ledger"} for r in cur.fetchall()]
        finally:
            conn.close()
    except sqlite3.Error:
        return []


def _runs_from_receipts(lane_id: str, folder: Path) -> list[dict[str, Any]]:
    out = []
    if not folder.is_dir():
        return out
    for p in folder.glob("*.json"):
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(doc, dict) and str(doc.get("lane_id") or "") == lane_id:
            out.append(
                {
                    "run_id": doc.get("run_id") or p.stem,
                    "mode": doc.get("mode"),
                    "state": doc.get("state"),
                    "exit_code": doc.get("exit_code"),
                    "finished_at": doc.get("finished_at"),
                    "source": "receipt",
                }
            )
    out.sort(key=lambda r: str(r.get("finished_at") or ""), reverse=True)
    return out


def run_receipts(lane_id: str, *, state: Path) -> dict[str, Any]:
    runs = _runs_from_ledger(lane_id, n8n_ledger_path(state)) or _runs_from_receipts(lane_id, n8n_runs_dir(state))

    def best(mode: str) -> Optional[dict[str, Any]]:
        for r in runs:
            if str(r.get("mode") or "") == mode:
                return r
        return None

    shadow, canary = best(SHADOW_MODE), best(CANARY_MODE)

    def ok(r: Optional[dict[str, Any]]) -> bool:
        return bool(r) and str(r.get("exit_code")) == "0" and str(r.get("state") or "RUN_DONE") == "RUN_DONE"

    return {
        "schema": RUN_RECEIPT_SCHEMA,
        "count": len(runs),
        "shadow": shadow,
        "canary": canary,
        "shadow_ok": ok(shadow),
        "canary_ok": ok(canary),
    }


def assess_lane(
    lane_id: str,
    *,
    reg: dict[str, Any],
    text: str,
    state: Path,
    now: datetime,
    host_state: Optional[dict[str, Any]] = None,
    timer_state_fn=None,
) -> dict[str, Any]:
    blockers: list[str] = []
    notes: list[str] = []
    row = lane_row(reg, lane_id)
    out: dict[str, Any] = {"lane_id": lane_id, "row_present": row is not None}
    if row is None:
        blockers.append("no registry row")
        return out | {"verdict": "NO_GO", "blockers": blockers, "notes": notes}
    state_val = str(row.get("state") or "")
    out["state"] = state_val
    out["scheduler"] = row.get("scheduler")
    if state_val != "ACTIVE":
        blockers.append(f"lane state is {state_val}, not ACTIVE")
    kind = str((row.get("scheduler") or {}).get("kind") or "")
    if kind == "n8n":
        notes.append("lane is already kind n8n (cut over); host check is the double-scheduler check")

    host = host_scheduler(row, text=text, host_state=host_state, timer_state_fn=timer_state_fn)
    out["host_scheduler"] = host
    if kind == "n8n":
        if host.get("measured") and host.get("present_once"):
            blockers.append("retired host scheduler is still live beside n8n (double scheduler)")
    elif not host.get("measured"):
        blockers.append("host scheduler not measurable: " + str(host.get("detail")))
    elif not host.get("present_once"):
        blockers.append(f"host scheduler not present exactly once (live_count={host.get('live_count', 'n/a')})")

    cadence_h = float(row.get("expected_cadence_hours") or 0) or None
    obs = observe_signal(row.get("output_signal") or {}, root=state)
    last = obs.get("last_output_at")
    age_h = round((now - last).total_seconds() / 3600.0, 2) if last else None
    out["output_signal"] = {
        "last_output_at": last.isoformat() if last else None,
        "age_hours": age_h,
        "readable": obs.get("readable", True),
        "detail": obs.get("detail"),
        "limit_hours": (cadence_h * 2) if cadence_h else None,
    }
    if not obs.get("readable", True):
        blockers.append("output_signal unreadable: " + str(obs.get("detail")))
    elif last is None:
        blockers.append("output_signal absent (never produced)")
    elif cadence_h and age_h is not None and age_h > 2 * cadence_h:
        blockers.append(f"output_signal stale: {age_h}h > 2×{cadence_h}h")
    elif cadence_h is None:
        notes.append("no expected_cadence_hours; freshness not judged")

    lock_m = LOCK_RE.search(str(host.get("line") or ""))
    if lock_m:
        comp = Path(lock_m.group(1)).name[: -len(".lock")]
        fl = safe_flock_completions(comp, state=state)
        out["safe_flock"] = fl
        comps = fl["completions"]
        if any(str(c.get("exit_code")) != "0" for c in comps):
            blockers.append(f"safe_flock {comp}: a recent completion exited non-zero")
        if len(comps) < COMPLETIONS_WANTED:
            notes.append(f"safe_flock {comp}: only {len(comps)} completion(s) on record (want {COMPLETIONS_WANTED})")
    else:
        out["safe_flock"] = None
        notes.append("no lock named on the host line; safe_flock history not judged")

    rr = run_receipts(lane_id, state=state)
    out["run_receipts"] = rr
    if not rr["shadow_ok"]:
        blockers.append("no shadow RunReceipt (mode dry_run, exit 0)")
    if not rr["canary_ok"]:
        blockers.append("no canary RunReceipt (mode live, exit 0)")

    verdict = "NO_GO" if blockers else ("GO_WITH_NOTES" if notes else "GO")
    return out | {"verdict": verdict, "blockers": blockers, "notes": notes}


def render(r: dict[str, Any]) -> str:
    lines = [f"lane {r['lane_id']}: {r['verdict']}"]
    for b in r.get("blockers") or []:
        lines.append(f"  BLOCKER: {b}")
    for n in r.get("notes") or []:
        lines.append(f"  note: {n}")
    hs = r.get("host_scheduler") or {}
    if hs:
        lines.append(
            f"  host scheduler: {hs.get('kind')} match={hs.get('match')!r} present_once={hs.get('present_once')}"
        )
    sig = r.get("output_signal") or {}
    if sig:
        lines.append(
            f"  output_signal: age={sig.get('age_hours')}h limit={sig.get('limit_hours')}h {sig.get('detail')}"
        )
    rr = r.get("run_receipts") or {}
    if rr:
        lines.append(
            f"  run receipts: {rr.get('count')} shadow_ok={rr.get('shadow_ok')} canary_ok={rr.get('canary_ok')}"
        )
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--lane", required=True, help="lane_id from config/lane_registry.json")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true", help="print only, write nothing (default)")
    g.add_argument("--write", action="store_true", help=f"also write {RECEIPT_REL} under the state root")
    ap.add_argument("--crontab-file", type=Path, default=None, help="read this file instead of `crontab -l` (tests)")
    ap.add_argument(
        "--host-state-json",
        type=Path,
        default=None,
        help='captured {"timers": {unit: {unit_file_state, sub_state, ...}}} for systemd lanes (tests/CI)',
    )
    ap.add_argument("--state-root", type=Path, default=None)
    ap.add_argument("--code-root", type=Path, default=None)
    ap.add_argument("--now", default=None, help="ISO timestamp override (tests)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    now = datetime.fromisoformat(args.now).astimezone(timezone.utc) if args.now else datetime.now(timezone.utc)
    state = args.state_root or Path(os.environ.get("TRADEAI_STATE_ROOT") or state_root())
    code_root = args.code_root or ROOT
    reg = load_registry(code_root / "config" / "lane_registry.json")
    text = crontab_text(file=args.crontab_file)
    host_state = json.loads(args.host_state_json.read_text(encoding="utf-8")) if args.host_state_json else None
    timer_fn = None
    if host_state is None:
        from scripts.lib.lane_state_drift import timer_state

        timer_fn = timer_state
    r = assess_lane(args.lane, reg=reg, text=text, state=state, now=now, host_state=host_state, timer_state_fn=timer_fn)
    doc = {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "as_of": now.isoformat(),
        "mode": "write" if args.write else "dry-run",
        "state_root": str(state),
        "lane": r,
        "verdict": r["verdict"],
    }
    if args.json:
        print(json.dumps(doc, indent=1, default=str))
    else:
        print(render(r))
    if args.write:
        p = state / RECEIPT_REL
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(doc, indent=1, default=str) + "\n", encoding="utf-8")
        print("wrote", p, file=sys.stderr if args.json else sys.stdout)
    else:
        print("dry-run: nothing written", file=sys.stderr if args.json else sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
