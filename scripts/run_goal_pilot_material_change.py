#!/usr/bin/env python3
"""P8 SHADOW pilot runner — material-change corroboration (operator-armed).

Writes an append-only receipt. No broker path. Tier-2 remains env-gated.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

AUTHORITY = "READ_ONLY_ADVISORY"
SCHEDULED_ENTRYPOINT = (
    "INSTALLED, active — crontab `40 * * * *`, hourly at :40, from the rebuild "
    "tree with /run/user/$UID/tradeai/env loaded. Armed 2026-09-16 under operator "
    "APPROVE E4 (full package). Lane: goal-pilot-material-change."
)


def _execute() -> int:
    from scripts.lib.canonical_store_registry import production_state_root

    root = Path(production_state_root())
    out_dir = root / "data" / "cio"
    out_dir.mkdir(parents=True, exist_ok=True)
    receipt_path = out_dir / "goal_pilot_material_change.jsonl"

    # Import late so --help-ish failures stay cheap.
    try:
        from scripts.lib import goal_pilot_material_change as pilot
    except Exception as exc:  # noqa: BLE001
        row = {
            "schema": "GoalPilotMaterialChangeRun@v1",
            "authority": AUTHORITY,
            "ran_at": datetime.now(timezone.utc).isoformat(),
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "scheduled_entrypoint": SCHEDULED_ENTRYPOINT,
        }
        with receipt_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")
        print(json.dumps(row, indent=2))
        return 1

    payload: dict
    try:
        if hasattr(pilot, "run_shadow"):
            payload = pilot.run_shadow()
        elif hasattr(pilot, "evaluate_live_goals"):
            payload = pilot.evaluate_live_goals()
        else:
            # Minimal honest receipt: library present, no runner API yet.
            payload = {
                "schema": getattr(pilot, "SCHEMA", "GoalPilotMaterialChange@v1"),
                "authority": getattr(pilot, "AUTHORITY", AUTHORITY),
                "status": "library_loaded",
                "note": "No run_shadow/evaluate_live_goals API; armed schedule proves invocation only until a runner API is added.",
                "paid_calls": 0,
                "tier2_flag": os.environ.get("TRADEAI_TIER2_PAID_JUDGE", ""),
            }
    except Exception as exc:  # noqa: BLE001
        payload = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    completed = payload.get("ok") is not False and payload.get("status") not in {"unavailable", "library_loaded"}
    row = {
        "schema": "GoalPilotMaterialChangeRun@v1",
        "authority": AUTHORITY,
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "ok": completed,
        "scheduled_entrypoint": SCHEDULED_ENTRYPOINT,
        "result": payload,
    }
    with receipt_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, default=str) + "\n")
    print(json.dumps(row, indent=2, default=str)[:2000])
    return 0 if completed else 1


def main(argv=None) -> int:
    """Strict offline inspection before the legacy business execution path."""
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--dry-run", action="store_true", help="offline source plan")
    args = parser.parse_args(argv)
    lane = "goal-pilot-material-change"
    if args.dry_run:
        print(f"DRY-RUN {lane}: would evaluate shadow material-change pilot under existing tier gates; no paid/model, state or writes; options={vars(args)}; inputs NOT_MEASURED")
        return 0
    try:
        from scripts.lib.lane_last_receipt import now_iso, write_lane_receipt
    except ImportError:
        from lib.lane_last_receipt import now_iso, write_lane_receipt
    started = now_iso()
    previous = sys.argv
    sys.argv = [previous[0], *argv]
    try:
        result = _execute()
        rc = int(result) if isinstance(result, int) else 0
    except SystemExit as exc:
        rc = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
        write_lane_receipt(lane, ok=rc == 0, exit_code=rc, started_at=started, script="run_goal_pilot_material_change.py", summary={"completed": rc == 0})
        raise
    except Exception as exc:
        write_lane_receipt(lane, ok=False, exit_code=1, started_at=started, script="run_goal_pilot_material_change.py", error=type(exc).__name__)
        raise
    finally:
        sys.argv = previous
    write_lane_receipt(lane, ok=rc == 0, exit_code=rc, started_at=started, script="run_goal_pilot_material_change.py", summary={"completed": rc == 0})
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
