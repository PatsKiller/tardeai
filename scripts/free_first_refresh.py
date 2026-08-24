#!/usr/bin/env python3
"""FREE_FIRST_ONLY classifier. Never calls a paid provider.

  PYTHONPATH=. python scripts/free_first_refresh.py --root .
  PYTHONPATH=. python scripts/free_first_refresh.py --root . --json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.lib.free_first_refresh import run_free_first  # noqa: E402

AUTHORITY = "READ_ONLY_ADVISORY"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--max-searx", type=int, default=0, help="0 = do not hit SearXNG")
    args = ap.parse_args()
    report = run_free_first(args.root, max_searx=int(args.max_searx))
    report.pop("rows", None)  # keep stdout small; full rows optional via --dump
    if args.json:
        print(json.dumps(report, indent=2, default=str))
        return 0
    print(f"FREE_FIRST_ONLY authority={AUTHORITY} paid_attempted={report['paid_calls_attempted']}")
    print(f"total={report['total_symbols']} no_new_info={report['no_new_info']}")
    print(f"Hermes_reuse={report['existing_Hermes_reuse']} structured={report['structured_resolved']} "
          f"unresolved={report['unresolved_after_free']} Flash_eligible={report['Flash_eligible_count']}")
    print(f"Flash_symbols={report['Flash_symbols'][:20]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
