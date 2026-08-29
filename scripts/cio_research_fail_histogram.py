#!/usr/bin/env python3
"""Hermes research failure histogram (Wave 2 slice 19). Read-only. No requeue.

  python scripts/cio_research_fail_histogram.py                 # last 7d on CURRENT
  python scripts/cio_research_fail_histogram.py --days 30 --json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIVE = Path("/home/johnclaw/trade-ai-releases/portfolio-server/CURRENT")


def main() -> int:
    ap = argparse.ArgumentParser(description="Hermes research failure histogram")
    ap.add_argument("--root", default=str(LIVE))
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    sys.path.insert(0, str(ROOT))
    from scripts.lib.cio_research_fail_policy import load_fail_histogram

    hist = load_fail_histogram(root=a.root, window_days=a.days)
    text = json.dumps(hist, indent=2, default=str)
    if a.out:
        Path(a.out).write_text(text + "\n", encoding="utf-8")
    if a.json:
        print(text)
        return 0

    print(f"Hermes research failures — last {hist['window_days']}d "
          f"({hist['failures_in_window']} of {hist['failures_total_all_time']} all time)")
    print(f"{'class':<20}{'n':>6}{'retryable':>12}{'worker_bug':>12}{'plans':>8}")
    for cls, row in hist["by_class_policy"].items():
        print(f"{cls:<20}{row['n']:>6}{str(row['retryable']):>12}"
              f"{str(row['is_worker_bug']):>12}{row['distinct_plans']:>8}")
    print(f"\nretryable={hist['retryable_n']}  non_retryable={hist['non_retryable_n']}  "
          f"worker_bug={hist['worker_bug_n']}")
    print(f"\n{hist['note']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
