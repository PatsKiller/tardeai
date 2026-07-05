#!/usr/bin/env python3
"""hermes_white_space_discovery.py — white-space coverage-diff CLI (spec Part A).

Diffs recurring outside-world DEMAND (hermes_research_intelligence topics,
news entities via content_entity_links, recurring discovery-candidate
subjects, outcome-bus tags) against everything the system already COVERS
(holdings, watchlist, enabled topic monitors, active watch directives,
strategy registry, active research sources). Subjects with recurrence >= 2
AND cross-source >= 2 that are absent from every covered surface become
GAP_CANDIDATE rows (meta_json.gap_type ∈ MISSING_THEME / MISSING_SECTOR /
MISSING_STRATEGY / MISSING_SOURCE / MISSING_COMPANY / MISSING_LEGAL_TOPIC /
MISSING_TAX_TOPIC / MISSING_RETIREMENT_TOPIC / MISSING_PRODUCT_VERTICAL) in
the Discovery Inbox.

Candidates only — OPERATOR_REVIEW_REQUIRED, never promoted, no
broker/execution imports anywhere in this path. Importing the engine also
registers it as the worker pool's 'white_space' lane runner.

Usage:
  python3 scripts/hermes_white_space_discovery.py --run [--dry-run] [--json]
                                                  [--limit N] [--window-days D]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from lib.hermes_discovery import white_space  # noqa: E402


def _print_human(report: dict) -> None:
    if report.get("error"):
        print(f"[white-space] ERROR: {report['error']}")
        for note in report.get("notes") or []:
            print(f"  note: {note}")
        return
    emitted = report["would_upsert"] if report["dry_run"] else report["upserted"]
    print(f"[white-space] dry_run={report['dry_run']} "
          f"covered_keys={report['covered_keys']} "
          f"demand_subjects={report['demand_subjects']} "
          f"gaps={report['gaps_detected']} emitted={emitted}")
    print(f"  thresholds:    {report['thresholds']}")
    print(f"  covered_areas: {report['covered_areas']}")
    print(f"  by_gap_type:   {report['by_gap_type']}")
    print(f"  skipped:       {report['skipped_reasons']}")
    for note in report.get("notes") or []:
        print(f"  note: {note}")
    for c in report["candidates"][:15]:
        extra = f" #{c['id']} {c.get('status')}" if "id" in c else ""
        print(f"  - {c['gap_type']:26s} {c['label']} "
              f"(recurrence {c['recurrence_count']}, "
              f"{c['source_count']} sources){extra}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", action="store_true", help="run white-space discovery")
    ap.add_argument("--dry-run", action="store_true",
                    help="detect + report only; write nothing")
    ap.add_argument("--json", action="store_true", help="JSON report output")
    ap.add_argument("--limit", type=int, default=None,
                    help=f"max gap candidates this run "
                         f"(default: {white_space.DEFAULT_RUN_LIMIT})")
    ap.add_argument("--window-days", type=int, default=white_space.WINDOW_DAYS,
                    help="demand look-back window in days")
    args = ap.parse_args()

    if not args.run:
        ap.print_help()
        return 2

    report = white_space.run_discovery(dry_run=args.dry_run, limit=args.limit,
                                       window_days=max(1, args.window_days))
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        _print_human(report)
    return 1 if report.get("error") else 0


if __name__ == "__main__":
    sys.exit(main())
