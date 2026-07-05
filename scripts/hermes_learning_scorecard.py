#!/usr/bin/env python3
"""hermes_learning_scorecard.py — Daily Hermes Learning Scorecard.

  python3 scripts/hermes_learning_scorecard.py
  python3 scripts/hermes_learning_scorecard.py --json
  python3 scripts/hermes_learning_scorecard.py --lookback-hours 48

Output: data/runtime/hermes_learning_scorecard.json
API: GET /api/v2/hermes/learning-scorecard
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "lib"))

KILL_SWITCH = PROJECT_ROOT / "data" / "runtime" / "HERMES_DISABLED"


def main() -> int:
    ap = argparse.ArgumentParser(description="Hermes Daily Learning Scorecard")
    ap.add_argument("--json", action="store_true", help="Print JSON to stdout")
    ap.add_argument("--lookback-hours", type=int, default=24)
    ap.add_argument("--no-persist", action="store_true", help="Skip writing scorecard file")
    args = ap.parse_args()

    if KILL_SWITCH.exists():
        out = {"ok": False, "reason": "HERMES_DISABLED kill switch present"}
        print(json.dumps(out, indent=2))
        return 1

    from lib.hermes_outcome_bus.scorecard import build_learning_scorecard

    out = build_learning_scorecard(
        lookback_hours=args.lookback_hours,
        persist=not args.no_persist,
    )
    out["ok"] = True
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())