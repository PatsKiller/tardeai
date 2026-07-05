#!/usr/bin/env python3
"""hermes_entity_spike_discovery.py — entity/term spike discovery CLI (spec Part E).

Detects current-window (48h) mention spikes vs the prior-window baseline
across content_entity_links (topic/sector/ticker entities, news-source
attributed) and hermes_research_intelligence topics, then files them as
TREND_CANDIDATE / TOPIC_CANDIDATE rows in the Discovery Inbox.

Gates (config/hermes_discovery_schedule.json): recurrence >=
min_recurrence_count, cross_source_count >= entity_spike_min_sources,
lift >= 2.0, and not already covered by an active watch_directive / enabled
topic_monitor row. Candidates only — OPERATOR_REVIEW_REQUIRED, never
promoted, no broker/execution imports anywhere in this path.

Usage:
  python3 scripts/hermes_entity_spike_discovery.py --run [--dry-run] [--json]
                                                   [--limit N] [--window-hours H]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from lib.hermes_discovery import entity_spikes  # noqa: E402


def _print_human(report: dict) -> None:
    print(f"[entity-spikes] dry_run={report['dry_run']} "
          f"scanned={report['scanned_terms']} spikes={report['spikes_detected']} "
          f"emitted={report['would_upsert'] if report['dry_run'] else report['upserted']}")
    print(f"  thresholds: {report['thresholds']}")
    print(f"  by_type:    {report['by_type']}")
    print(f"  by_domain:  {report['by_domain']}")
    print(f"  skipped:    {report['skipped_reasons']}")
    for note in report["notes"]:
        print(f"  note: {note}")
    for c in report["candidates"][:15]:
        spike = c["spike"]
        print(f"  - {c['candidate_type']:16s} [{c['domain']}] {c['label']} "
              f"(lift {spike['lift']}x, {spike['current_count']} vs "
              f"{spike['prior_count']}, {spike['cross_source_count']} sources)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", action="store_true", help="run spike discovery")
    ap.add_argument("--dry-run", action="store_true",
                    help="detect + report only; write nothing")
    ap.add_argument("--json", action="store_true", help="JSON report output")
    ap.add_argument("--limit", type=int, default=None,
                    help="max candidates this run (default: schedule config cap)")
    ap.add_argument("--window-hours", type=int, default=entity_spikes.WINDOW_HOURS,
                    help="current-window size; baseline is the same-size prior window")
    args = ap.parse_args()

    if not args.run:
        ap.print_help()
        return 2

    report = entity_spikes.run_discovery(dry_run=args.dry_run, limit=args.limit,
                                         window_hours=max(1, args.window_hours))
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        _print_human(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
