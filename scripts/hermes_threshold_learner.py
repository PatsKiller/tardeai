#!/usr/bin/env python3
"""hermes_threshold_learner.py — Adaptive threshold learning (Phase 2).

Analyzes outcome bus history and proposes conservative threshold adjustments.
All changes require explicit human approval in v1 — review mode is default.

  python3 scripts/hermes_threshold_learner.py --status
  python3 scripts/hermes_threshold_learner.py --learn
  python3 scripts/hermes_threshold_learner.py --learn --apply
  python3 scripts/hermes_threshold_learner.py --approve tp_abc123
  python3 scripts/hermes_threshold_learner.py --reject tp_abc123 --reason "too aggressive"
  python3 scripts/hermes_threshold_learner.py --rollback
  python3 scripts/hermes_threshold_learner.py --evaluate
  python3 scripts/hermes_threshold_learner.py --evaluate-status

See docs/hermes/HERMES_ADAPTIVE_THRESHOLD_LEARNING.md
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
    ap = argparse.ArgumentParser(description="Hermes Adaptive Threshold Learner")
    ap.add_argument("--status", action="store_true", help="Show active vs static thresholds")
    ap.add_argument("--learn", action="store_true", help="Run learning cycle (proposals only)")
    ap.add_argument("--apply", action="store_true", help="Persist proposals from --learn")
    ap.add_argument("--approve", type=str, default=None, metavar="PROPOSAL_ID")
    ap.add_argument("--reject", type=str, default=None, metavar="PROPOSAL_ID")
    ap.add_argument("--reason", type=str, default="operator_rejected")
    ap.add_argument("--rollback", action="store_true", help="Revert to static yaml defaults")
    ap.add_argument("--evaluate", action="store_true", help="Run before/after evaluation (read-only)")
    ap.add_argument("--evaluate-status", action="store_true", help="Show stored evaluation results")
    ap.add_argument("--lookback-days", type=int, default=None, help="Evaluation lookback window")
    ap.add_argument("--by", type=str, default="operator", help="Approver identity for audit")
    args = ap.parse_args()

    if KILL_SWITCH.exists():
        out = {"ok": False, "reason": "HERMES_DISABLED kill switch present"}
        print(json.dumps(out, indent=2))
        return 1

    from lib.hermes_thresholds.evaluation_engine import evaluation_status, run_evaluation_cycle
    from lib.hermes_thresholds.threshold_learner import run_learning_cycle
    from lib.hermes_thresholds.workflow import (
        approve_proposal,
        reject_proposal,
        rollback_thresholds,
        threshold_status,
    )

    if args.status:
        out = threshold_status()
    elif args.evaluate:
        out = run_evaluation_cycle(lookback_days=args.lookback_days)
    elif args.evaluate_status:
        out = evaluation_status()
    elif args.learn:
        out = run_learning_cycle(apply_proposals=args.apply)
    elif args.approve:
        out = approve_proposal(args.approve, approved_by=args.by, force_apply=True)
    elif args.reject:
        out = reject_proposal(args.reject, reason=args.reason)
    elif args.rollback:
        out = rollback_thresholds(approved_by=args.by)
    else:
        ap.print_help()
        return 0

    print(json.dumps(out, indent=2, default=str))
    return 0 if out.get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())