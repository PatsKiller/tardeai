#!/usr/bin/env python3
"""hermes_industry_novelty_discovery.py — industry/sector novelty discovery CLI.

Surfaces sectors/themes prominent in current news but absent from our covered
universe (symbol_profiles sectors, watch directives, topic monitors) as
GAP_CANDIDATE rows (meta.gap_type=MISSING_SECTOR) in the Discovery Inbox —
distinct from entity_spikes, which flags attention spikes in sectors we already
track.

Thresholds: config/hermes_discovery_schedule.json. Candidates only —
OPERATOR_REVIEW_REQUIRED, never promoted, never auto-added to a watchlist.
Shadow-first: with industry_novelty_enabled=false the pass computes + reports
but writes nothing.

Usage:
  python3 scripts/hermes_industry_novelty_discovery.py --run [--dry-run] [--json]
                                                       [--limit N]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from lib.hermes_discovery import industry_novelty  # noqa: E402


def _print_human(report: dict) -> None:
    print(f"[industry-novelty] dry_run={report['dry_run']} "
          f"effective_dry={report['effective_dry_run']} "
          f"enabled={report['enabled_in_schedule']} "
          f"scanned={report['scanned_sectors']} novel={report['novel_detected']} "
          f"emitted={report['would_upsert'] if report['effective_dry_run'] else report['upserted']}")
    print(f"  thresholds: {report['thresholds']}")
    print(f"  by_domain:  {report['by_domain']}")
    print(f"  skipped:    {report['skipped_reasons']}")
    for note in report["notes"]:
        print(f"  note: {note}")
    for c in report["candidates"][:15]:
        print(f"  - {c['candidate_type']:14s} [{c['domain']}] {c['label']} "
              f"({c['mentions']} mentions)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", action="store_true", help="run novelty discovery")
    ap.add_argument("--dry-run", action="store_true",
                    help="detect + report only; write nothing")
    ap.add_argument("--json", action="store_true", help="JSON report output")
    ap.add_argument("--limit", type=int, default=None,
                    help="max candidates this run (default: config max_per_day)")
    args = ap.parse_args()

    if not args.run:
        ap.print_help()
        return 2

    report = industry_novelty.run_discovery(dry_run=args.dry_run, limit=args.limit)
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        _print_human(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
