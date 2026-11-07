#!/usr/bin/env python3
"""Read-only report: commitment outcome ledger rows vs effective outcomes, and the cleanup PLAN.

Never writes. LQ-20261107-54. Usage: commitment_outcome_ledger_plan.py [--state-root DIR] [--items]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.lib.commitment_outcome_sweep import (  # noqa: E402
    outcome_summary,
    plan_ledger_cleanup,
    read_jsonl,
)


def default_root() -> Path:
    env = os.environ.get("TRADEAI_STATE_ROOT")
    return Path(env) if env else Path.home() / "trade-ai-state" / "persistent_wake" / "state"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--state-root", default=str(default_root()))
    ap.add_argument("--items", action="store_true", help="include every superseded row")
    a = ap.parse_args(argv)
    root = Path(a.state_root)
    commitments = read_jsonl(root / "commitments.jsonl")
    ledger = read_jsonl(root / "commitment_outcomes.jsonl")
    plan = plan_ledger_cleanup(ledger)
    if not a.items:
        plan = {k: v for k, v in plan.items() if k != "items"}
    print(json.dumps({"summary": outcome_summary(commitments, ledger), "cleanup_plan": plan}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
