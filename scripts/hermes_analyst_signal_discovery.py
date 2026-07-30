#!/usr/bin/env python3
"""hermes_analyst_signal_discovery.py — analyst-signal discovery CLI.

Turns current analyst ratings into Discovery Inbox candidates: per-symbol
rating changes, price-target moves and new-coverage initiations become
TICKER_CANDIDATE rows, and a per-sector roll-up of same-direction moves becomes
a TREND_CANDIDATE — so analyst activity drives sector/theme discovery, not just
per-name scoring.

Source: yahoo_analyst_targets_history (latest vs prior snapshot per symbol).
Thresholds: config/hermes_discovery_schedule.json. Candidates only —
OPERATOR_REVIEW_REQUIRED, never promoted, never auto-added to a watchlist, no
broker/execution imports. Shadow-first: with analyst_signal_enabled=false the
pass computes + reports but writes nothing.

Usage:
  python3 scripts/hermes_analyst_signal_discovery.py --run [--dry-run] [--json]
                                                     [--limit N]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from lib.hermes_discovery import analyst_signals  # noqa: E402


def _print_human(report: dict) -> None:
    print(f"[analyst-signals] dry_run={report['dry_run']} "
          f"effective_dry={report['effective_dry_run']} "
          f"enabled={report['enabled_in_schedule']} "
          f"scanned={report['scanned_symbols']} signals={report['signals_detected']} "
          f"emitted={report['would_upsert'] if report['effective_dry_run'] else report['upserted']}")
    print(f"  thresholds: {report['thresholds']}")
    print(f"  by_type:    {report['by_type']}")
    print(f"  by_domain:  {report['by_domain']}")
    print(f"  skipped:    {report['skipped_reasons']}")
    for note in report["notes"]:
        print(f"  note: {note}")
    for c in report["candidates"][:15]:
        print(f"  - {c['candidate_type']:16s} [{c['domain']}] {c['label']} "
              f"({c.get('direction')})")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", action="store_true", help="run analyst-signal discovery")
    ap.add_argument("--dry-run", action="store_true",
                    help="detect + report only; write nothing")
    ap.add_argument("--json", action="store_true", help="JSON report output")
    ap.add_argument("--limit", type=int, default=None,
                    help="max candidates this run (default: schedule config cap)")
    args = ap.parse_args()

    if not args.run:
        ap.print_help()
        return 2

    report = analyst_signals.run_discovery(dry_run=args.dry_run, limit=args.limit)
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        _print_human(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
