#!/usr/bin/env python3
"""Repair goals whose `due_ts` precedes their `created_ts`, by APPENDING.

    python scripts/repair_goal_due_ts.py              # dry run (default)
    python scripts/repair_goal_due_ts.py --json
    python scripts/repair_goal_due_ts.py --apply      # append GOAL_UPDATED events

Measured 2026-09-16 on the live store: all three goals carry a `due_ts` ten
minutes BEFORE their `created_ts`.

    goal_695a5dbe2401  created 2026-08-11T14:21:40Z  due 2026-08-11T14:11:40Z
    goal_f2664540d8c1  created 2026-08-11T14:21:40Z  due 2026-08-11T14:11:40Z
    goal_f1d5c0a993d0  created 2026-08-11T14:21:40Z  due 2026-08-11T14:11:40Z

A goal that is due before it exists is due on every tick forever, which is how
34,347 wakes were served against three goals that never closed.

The log is NEVER rewritten. The repair is a `GOAL_UPDATED` event appended to
the end of the event log, exactly like any other update; replaying the log from
the beginning still yields every historical state, and the correction is itself
an auditable event with an actor and a timestamp.

Dry run is the default and touches nothing: the projection and cursor are
redirected to a scratch directory so that even the rebuildable snapshot of the
live store is left alone.

AUTHORITY: READ_ONLY_ADVISORY. MBI_BEHAVIOR=0. No broker, order, or risk write.
"""
from __future__ import annotations

NO_CONSUMER_REASON = (
    "operator repair tool, run by hand with --apply after review. It is "
    "deliberately on no timer: a data repair that runs itself unattended is "
    "how a bad correction becomes 34,000 rows of bad correction."
)

import argparse
import json
import sys
import tempfile
from datetime import timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib.cio_goals import (  # noqa: E402
    DEFAULT_EVENT_CURSOR_PATH,
    DEFAULT_GOALS_PATH,
    DEFAULT_PROJECTION_PATH,
    CIOGoalStore,
    _parse_ts,
)

AUTHORITY = "READ_ONLY_ADVISORY"


def inverted_goals(store: CIOGoalStore) -> list[dict[str, Any]]:
    """Goals whose due_ts is strictly before their created_ts."""
    out = []
    for goal in store._goals.values():
        due = _parse_ts(goal.get("due_ts"))
        created = _parse_ts(goal.get("created_ts"))
        if due is None or created is None:
            continue
        if due < created:
            out.append(goal)
    return sorted(out, key=lambda g: str(g.get("goal_id")))


def repaired_due(goal: dict[str, Any], *, due_in_hours: float, now) -> str:
    """The corrected due_ts.

    Anchored to the LATER of the goal's creation and now, so the result is both
    after `created_ts` (the invariant) and in the future (which is what stops
    the goal being re-served on every tick).
    """
    created = _parse_ts(goal.get("created_ts"))
    anchor = max(created, now) if created else now
    return (anchor + timedelta(hours=due_in_hours)).isoformat()


def run(
    *,
    apply: bool = False,
    due_in_hours: float = 24.0,
    event_path: Path | str = DEFAULT_GOALS_PATH,
    projection_path: Path | str | None = None,
    cursor_path: Path | str | None = None,
    actor_id: str = "repair_goal_due_ts",
) -> dict[str, Any]:
    from datetime import datetime, timezone

    scratch = None
    if not apply and projection_path is None:
        # A dry run must not even rewrite the rebuildable projection.
        scratch = Path(tempfile.mkdtemp(prefix="goal_due_repair_dry_"))
        projection_path = scratch / "projection.json"
        cursor_path = scratch / "cursors.json"

    store = CIOGoalStore(
        event_path=event_path,
        projection_path=projection_path or DEFAULT_PROJECTION_PATH,
        cursor_path=cursor_path or DEFAULT_EVENT_CURSOR_PATH,
    )
    now = datetime.now(timezone.utc)
    found = inverted_goals(store)

    events_before = sum(1 for _ in open(store.event_path)) if store.event_path.is_file() else 0
    repairs: list[dict[str, Any]] = []
    for goal in found:
        new_due = repaired_due(goal, due_in_hours=due_in_hours, now=now)
        row = {
            "goal_id": goal.get("goal_id"),
            "owner_agent": goal.get("owner_agent"),
            "title": goal.get("title"),
            "created_ts": goal.get("created_ts"),
            "due_ts_before": goal.get("due_ts"),
            "due_ts_after": new_due,
            "applied": False,
        }
        if apply:
            store.update_goal(goal["goal_id"], due_ts=new_due, actor_id=actor_id)
            row["applied"] = True
        repairs.append(row)

    events_after = sum(1 for _ in open(store.event_path)) if store.event_path.is_file() else 0
    return {
        "schema": "GoalDueTsRepair@v1",
        "authority": AUTHORITY,
        "memory_behavior_influence": 0,
        "financial_action": False,
        "applied": bool(apply),
        "event_path": str(store.event_path),
        "goals_scanned": len(store._goals),
        "inverted_found": len(found),
        "repaired": sum(1 for r in repairs if r["applied"]),
        "events_before": events_before,
        "events_after": events_after,
        "appended_only": events_after >= events_before,
        "repairs": repairs,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="append GOAL_UPDATED events (default: dry run)")
    ap.add_argument("--json", action="store_true", help="emit the receipt as JSON")
    ap.add_argument("--due-in-hours", type=float, default=24.0,
                    help="how far ahead of max(created_ts, now) the repaired due_ts sits")
    ap.add_argument("--event-path", default=str(DEFAULT_GOALS_PATH))
    ap.add_argument("--projection-path", default=None)
    ap.add_argument("--cursor-path", default=None)
    args = ap.parse_args()

    result = run(
        apply=args.apply,
        due_in_hours=args.due_in_hours,
        event_path=args.event_path,
        projection_path=args.projection_path,
        cursor_path=args.cursor_path,
    )
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0

    mode = "APPLY" if result["applied"] else "DRY RUN"
    print(f"── goal due_ts repair ({mode}) ──")
    print(f"  store            : {result['event_path']}")
    print(f"  goals scanned    : {result['goals_scanned']}")
    print(f"  born overdue     : {result['inverted_found']}")
    print(f"  repaired         : {result['repaired']}")
    print(f"  events {result['events_before']} -> {result['events_after']} (append-only: {result['appended_only']})")
    for r in result["repairs"]:
        flag = "applied" if r["applied"] else "would append"
        print(f"    {r['goal_id']} {r['owner_agent']:<8} {flag}")
        print(f"      created  {r['created_ts']}")
        print(f"      due      {r['due_ts_before']}  ->  {r['due_ts_after']}")
    if not result["applied"] and result["inverted_found"]:
        print("\n  Nothing was written. Re-run with --apply to append the GOAL_UPDATED events.")
    print(f"  {AUTHORITY}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
