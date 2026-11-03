#!/usr/bin/env python3
"""One hourly self-heal status block for the hourly operator email.

Read-only: no network, no model, no writes, no schedule. It reads the live incident store
(data/coordination/incidents/{index,supervisor_last,watchers_last,supervisor_calls}.json),
the fixer state (data/runtime/self_heal_fixer_state.json) and the reviewed runbook config
(config/incident_runbook_actions.json) and prints four lines the lead pastes as-is:

    SELF-HEAL · 17:07 UTC
    detected 5 (last hour) · dispatched 0 · fixed 4 (last hour) · still blocked 27 · unresolved 10
    supervisor 2026-11-03T17:02:00Z: considered 5, actions 0, dispatched 0, skipped 5 (5 on daily model-call cap); model calls today 40/40
    watchers 2026-11-03T17:05:00Z: 10/10 without a gap; findings lane_health 16, health_tick 3, ...
    verdict: DETECT alive · DECIDE starved by the daily model-call cap · FIX not scheduled (5 requests queued) — lane NOT alive end-to-end

Definitions (stable; do not "improve" silently):
  detected      incidents with opened_at inside the last 60 minutes
  dispatched    supervisor dispatches in its last cycle (the fixer is unscheduled)
  fixed         records whose closed_at / fixed_at / resolved_at is inside the last 60 minutes
  blocked       records with status blocked; unresolved = the index summary's unresolved count
Verdict rules:
  DETECT alive       watcher receipt fresh (<= 15 min) and every watcher has no gap; else stale/gapped
  DECIDE starved     every skip in the supervisor's last cycle is "daily model-call cap"; else working
  FIX not scheduled  fix_requested jobs waiting in the fixer state (no schedule exists; 24.5 still gates the PR)
  lane alive         detect and decide are OK and no fix queue is waiting
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

STATE = Path("/home/johnclaw/trade-ai-releases/persistent-state")
INCIDENTS = STATE / "data" / "coordination" / "incidents"
RUNTIME = STATE / "data" / "runtime"
CONFIG = Path(__file__).resolve().parents[1] / "config" / "incident_runbook_actions.json"
CAP_SKIP = "daily model-call cap"
WATCHER_FRESH_MIN = 15.0


def _ts(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def build_block(*, index: dict, supervisor: dict, watchers: dict, calls: dict, policy: dict,
                fixer: dict, now: datetime) -> list[str]:
    """The four pasted lines. Pure: every input is a parsed document, no I/O."""
    records = index.get("incidents") or []
    hour = now - timedelta(hours=1)
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    detected = [r for r in records if (_ts(r.get("opened_at")) or epoch) > hour]
    fixed = [r for r in records
             if any((_ts(r.get(k)) or epoch) > hour for k in ("closed_at", "fixed_at", "resolved_at"))]
    summary = index.get("summary") or {}
    counts = summary.get("counts") or {}
    blocked = counts.get("blocked", sum(1 for r in records if r.get("status") == "blocked"))
    unresolved = summary.get("unresolved", sum(1 for r in records if r.get("status") == "open"))

    watcher_rows = watchers.get("watchers") or {}
    gaps = [name for name, row in watcher_rows.items() if row.get("gap")]
    findings = {name: row.get("findings", 0) for name, row in watcher_rows.items() if row.get("findings")}
    watcher_at = _ts(watchers.get("as_of"))
    watcher_age = (now - watcher_at).total_seconds() / 60 if watcher_at else None
    detect_ok = bool(watcher_rows) and not gaps and watcher_age is not None and watcher_age <= WATCHER_FRESH_MIN

    skipped = supervisor.get("skipped") or []
    cap_skips = sum(1 for s in skipped if s.get("why") == CAP_SKIP)
    decide_ok = bool(supervisor) and not (skipped and cap_skips == len(skipped))

    queued = sum(1 for job in (fixer.get("jobs") or {}).values() if job.get("state") == "fix_requested")
    day_cap = int((policy.get("policy") or {}).get("max_model_calls_per_day") or 40)

    verdict = " · ".join([
        "DETECT alive" if detect_ok else "DETECT stale/gapped",
        "DECIDE working" if decide_ok else f"DECIDE starved by the {CAP_SKIP}",
        f"FIX not scheduled ({queued} requests queued)" if queued else "FIX no queue",
    ]) + (" — lane alive end-to-end" if detect_ok and decide_ok and not queued else " — lane NOT alive end-to-end")

    findings_text = ", ".join(f"{k} {v}" for k, v in sorted(findings.items(), key=lambda kv: -kv[1])) or "none"
    return [
        f"SELF-HEAL · {now:%H:%M} UTC",
        f"detected {len(detected)} (last hour) · dispatched {len(supervisor.get('dispatched') or [])} · "
        f"fixed {len(fixed)} (last hour) · still blocked {blocked} · unresolved {unresolved}",
        f"supervisor {supervisor.get('as_of', '?')}: considered {len(supervisor.get('considered') or [])}, "
        f"actions {len(supervisor.get('actions') or [])}, dispatched {len(supervisor.get('dispatched') or [])}, "
        f"skipped {len(skipped)} ({cap_skips} on {CAP_SKIP}); model calls today {calls.get('count', '?')}/{day_cap}",
        f"watchers {watchers.get('as_of', '?')}: {len(watcher_rows) - len(gaps)}/{len(watcher_rows)} without a gap; "
        f"findings {findings_text}",
        f"verdict: {verdict}",
    ]


def main(argv=None) -> int:
    now = datetime.now(timezone.utc)
    block = build_block(
        index=_load(INCIDENTS / "index.json", {}),
        supervisor=_load(INCIDENTS / "supervisor_last.json", {}),
        watchers=_load(INCIDENTS / "watchers_last.json", {}),
        calls=_load(INCIDENTS / "supervisor_calls.json", {}),
        policy=_load(CONFIG, {}),
        fixer=_load(RUNTIME / "self_heal_fixer_state.json", {}),
        now=now,
    )
    print("\n".join(block))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
