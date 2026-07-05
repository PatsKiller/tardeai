#!/usr/bin/env python3
"""hermes_threshold_evaluator.py — Do-no-harm evaluation cycle (read-only).

Alias for hermes_threshold_learner.py --evaluate with do-no-harm regression output.

  python3 scripts/hermes_threshold_evaluator.py
  python3 scripts/hermes_threshold_evaluator.py --json
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
    ap = argparse.ArgumentParser(description="Hermes Threshold Evaluator (do-no-harm)")
    ap.add_argument("--json", action="store_true", help="Print JSON (default)")
    ap.add_argument("--lookback-days", type=int, default=None)
    args = ap.parse_args()

    if KILL_SWITCH.exists():
        out = {"ok": False, "reason": "HERMES_DISABLED kill switch present"}
        print(json.dumps(out, indent=2))
        return 1

    from lib.hermes_thresholds.evaluation_engine import run_evaluation_cycle
    from lib.hermes_thresholds.do_no_harm import load_do_no_harm_report

    out = run_evaluation_cycle(lookback_days=args.lookback_days)
    out["do_no_harm_report"] = load_do_no_harm_report().get("latest") or load_do_no_harm_report()
    out["advisory_only"] = True
    print(json.dumps(out, indent=2, default=str))
    return 0 if out.get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())