#!/usr/bin/env python3
"""Remove phase_e test-fixture entries from the Hermes outcome bus JSON.

Companion to redeploy_fixture_cleanup_2026_07_13.sql (P0 audit 2026-07-13).
The DB cleanup is transactional; this file is not — hence a separate,
dry-run-by-default script. Requires --apply to write.

Targets in state/hermes/outcome_bus.json:
  - by_symbol.JEPQ.redeploy_events: 3 entries, event_id=144, $1082.16,
    recorded 2026-07-14T03:19/03:22/03:23 UTC, sold_symbol null
  - feedback_to_governor: 3 matching entries, source=redeploy_monitor,
    note 'Manual redeploy fill stage 1 for None sale'
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

FIXTURE_EVENT_ID = 144
FIXTURE_TIMES = ("2026-07-14T03:19", "2026-07-14T03:22", "2026-07-14T03:23")


def _is_fixture_redeploy_event(entry: dict) -> bool:
    at = str(entry.get("recorded_at") or "")
    return (
        entry.get("event_id") == FIXTURE_EVENT_ID
        and entry.get("sold_symbol") is None
        and any(at.startswith(t) for t in FIXTURE_TIMES)
    )


def _is_fixture_governor_feedback(entry: dict) -> bool:
    at = str(entry.get("at") or "")
    return (
        entry.get("source") == "redeploy_monitor"
        and entry.get("symbol") == "JEPQ"
        and "for None sale" in str(entry.get("note") or "")
        and any(at.startswith(t) for t in FIXTURE_TIMES)
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    args = ap.parse_args()

    from lib.hermes_outcome_bus.bus import load_outcome_bus, write_outcome_bus

    bus = load_outcome_bus()
    removed = {"redeploy_events": 0, "feedback_to_governor": 0}

    jepq = (bus.get("by_symbol") or {}).get("JEPQ") or {}
    events = jepq.get("redeploy_events") or []
    keep_events = [e for e in events if not _is_fixture_redeploy_event(e)]
    removed["redeploy_events"] = len(events) - len(keep_events)
    if "redeploy_events" in jepq:
        jepq["redeploy_events"] = keep_events

    feedback = bus.get("feedback_to_governor") or []
    keep_feedback = [e for e in feedback if not _is_fixture_governor_feedback(e)]
    removed["feedback_to_governor"] = len(feedback) - len(keep_feedback)
    if "feedback_to_governor" in bus:
        bus["feedback_to_governor"] = keep_feedback

    print(json.dumps({
        "mode": "apply" if args.apply else "dry_run",
        "removed": removed,
        "jepq_redeploy_events_remaining": len(keep_events),
        "governor_feedback_remaining": len(keep_feedback),
    }, indent=2))

    if args.apply:
        write_outcome_bus(bus, apply=True)
        print("outcome bus written")
    else:
        print("dry run — no changes written (use --apply after operator approval)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
