#!/usr/bin/env python3
"""D2 — attach the pilot predicate to one live goal. Dry-run by default.

Measured 2026-09-17: `GOAL_PREDICATE_SET` = 0 against 34,912 wakes. Nothing in
the codebase calls `CIOGoalStore.set_predicate`, so no goal has ever carried a
predicate — and a goal without one can never close, which is why
`GOAL_STATUS_CHANGED` has been 0 for 37 days. The machinery shipped; nothing
drove it.

Setting a predicate changes what the live dispatcher serves, so `--apply` is
operator-gated (AGENTS.md §17) and the default is a dry run that writes nothing.
The dry run prints the exact event that WOULD be appended.

No new identity: the predicate reuses `goal_pilot_material_change.build_predicate`
terms, so identity stays `(goal_id, predicate_version, predicate_hash)` rooted in
the goal's own id.

Authority: READ_ONLY_ADVISORY unless --apply. MBI_BEHAVIOR = 0.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

AUTHORITY = "READ_ONLY_ADVISORY"
SCHEDULED_ENTRYPOINT = (
    "PROPOSAL ONLY — not installed, and deliberately not schedulable. Attaching a "
    "predicate to a live goal is an operator decision (AGENTS.md §17), not a cron."
)


def _store():
    from scripts.lib.canonical_store_registry import production_state_root
    from scripts.lib.cio_goals import CIOGoalStore

    root = Path(production_state_root()) / "data" / "cio"
    return CIOGoalStore(
        event_path=root / "cio_goals.jsonl",
        projection_path=root / "cio_goals_projection.json",
        cursor_path=root / "cio_goals_cursor.json",
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--goal-id", default=None,
                    help="target goal; default = the oldest open goal")
    ap.add_argument("--apply", action="store_true",
                    help="append GOAL_PREDICATE_SET (operator-gated, §17)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    from scripts.lib.goal_pilot_material_change import (
        PILOT_EVALUATOR, PILOT_TERMS, build_predicate,
    )

    try:
        store = _store()
    except Exception as exc:  # noqa: BLE001 — cannot-run is exit 2, never a green 0
        print(f"ERROR: cannot open goal store: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    # `list_open_goals` is the real accessor. An earlier draft guarded
    # `hasattr(store, "list_goals")` — a name that does not exist — so the guard
    # silently yielded [] and the script reported "no open goal", which reads
    # like a finding about the store instead of a typo in the caller. A missing
    # API must raise here, not degrade into a false measurement.
    if not hasattr(store, "list_open_goals"):
        print("ERROR: CIOGoalStore has no list_open_goals; refusing to guess",
              file=sys.stderr)
        return 2
    open_goals = list(store.list_open_goals())
    if not open_goals:
        print("ERROR: no open goal to attach a predicate to", file=sys.stderr)
        return 2

    if args.goal_id:
        target = next((g for g in open_goals if g.get("goal_id") == args.goal_id), None)
        if target is None:
            print(f"ERROR: {args.goal_id} is not an open goal", file=sys.stderr)
            return 2
    else:
        target = sorted(open_goals, key=lambda g: str(g.get("created_ts") or ""))[0]

    goal_id = str(target.get("goal_id"))
    already = (target.get("predicate") or {}).get("predicate_hash")
    preview = build_predicate(goal_id=goal_id)

    report = {
        "schema": "SetGoalPredicate@v1",
        "authority": "OPERATOR_WRITE" if args.apply else AUTHORITY,
        "applied": False,
        "goal_id": goal_id,
        "goal_status": target.get("status"),
        "already_has_predicate": bool(already),
        "evaluator": PILOT_EVALUATOR,
        "terms": list(PILOT_TERMS),
        "would_set_predicate_hash": preview["predicate_hash"],
        "would_set_identity": preview["predicate_identity"],
    }

    if already:
        report["note"] = "goal already carries a predicate; re-setting mints a new version"

    if args.apply:
        try:
            payload = store.set_predicate(
                goal_id,
                evaluator=PILOT_EVALUATOR,
                terms=list(PILOT_TERMS),
                actor_id="set_goal_predicate",
            )
            report["applied"] = True
            report["predicate_version"] = payload.get("predicate_version")
            report["predicate_hash"] = payload.get("predicate_hash")
            report["predicate_identity"] = payload.get("predicate_identity")
        except Exception as exc:  # noqa: BLE001
            report["error"] = f"{type(exc).__name__}: {exc}"
            print(json.dumps(report, indent=2, default=str), file=sys.stderr)
            return 1
    else:
        report["note_dry_run"] = (
            "DRY RUN — nothing written. Re-run with --apply to append "
            "GOAL_PREDICATE_SET. This changes what the live dispatcher serves."
        )

    print(json.dumps(report, indent=2, default=str) if args.json
          else "\n".join(f"  {k:28s}: {v}" for k, v in report.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
