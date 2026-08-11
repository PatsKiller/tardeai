#!/usr/bin/env python3
"""Score advisory desk verdicts at 30/60/90d horizons (deterministic).

Usage:
  .venv/bin/python scripts/advisory_outcome_scorer.py --once
  .venv/bin/python scripts/advisory_outcome_scorer.py --once --max 100
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from lib.advisory.advisory_memory import score_pending_outcomes  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--once", action="store_true", help="Run one sweep (default)")
    ap.add_argument("--max", type=int, default=200, help="Max new outcome rows")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    result = score_pending_outcomes(max_new=args.max)
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        cal = result.get("calibration") or {}
        g = cal.get("global") or {}
        print(
            f"advisory outcomes: written={result.get('written')} "
            f"scored_total={g.get('n')} hit_rate={g.get('hit_rate')}"
        )
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
