#!/usr/bin/env python3
"""hermes_loft_law_discovery.py — NYC Loft Law domain-pack discovery CLI (spec Part G).

Scans news_articles + hermes_research_intelligence for the loft-law term list
(config/research_domains/nyc_loft_law.yaml) and files matches as Discovery
Inbox candidates in the NON-trading nyc_loft_law workspace:

  court/case-citation wording   -> CASE_LAW_CANDIDATE
  statute/rule-change wording   -> STATUTE_UPDATE_CANDIDATE
  explainer-worthy cluster      -> WEBSITE_CONTENT_CANDIDATE
  recurring topic               -> LEGAL_TOPIC_CANDIDATE

Source policy enforced (primary/secondary/blocked; blocked skipped, primary
ranked first). Every candidate carries the forced labels ("Research summary
only." / "Not legal advice." / "Consult a qualified NY attorney." / "Cite
primary sources where possible."), OPERATOR_REVIEW_REQUIRED, and
content_stage=candidate — NEVER auto-published, never a trading input.

Usage:
  python3 scripts/hermes_loft_law_discovery.py --run [--dry-run] [--json]
                                               [--limit N] [--window-hours H]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from lib.hermes_discovery import loft_law  # noqa: E402


def _print_human(report: dict) -> None:
    emitted = report["would_upsert"] if report["dry_run"] else report["upserted"]
    print(f"[loft-law] dry_run={report['dry_run']} pack={report['pack']} "
          f"domain={report['domain']} workspace={report['workspace']}")
    print(f"  scanned_rows={report['scanned_rows']} payloads={report['payloads']} "
          f"emitted={emitted} window_hours={report['window_hours']}")
    print(f"  by_type:         {report['by_type']}")
    print(f"  by_source_class: {report['by_source_class']}")
    print(f"  skipped:         {report['skipped_reasons']}")
    for note in report["notes"]:
        print(f"  note: {note}")
    for c in report["candidates"][:15]:
        print(f"  - {c['candidate_type']:26s} [{c['source_policy_class']:9s}] "
              f"{c['label']} (terms: {', '.join(c['matched_terms'])})")
    if report["scanned_rows"] == 0:
        print("  (honest zero: no loft-law term matches in the current corpus)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", action="store_true", help="run loft-law discovery")
    ap.add_argument("--dry-run", action="store_true",
                    help="scan + report only; write nothing")
    ap.add_argument("--json", action="store_true", help="JSON report output")
    ap.add_argument("--limit", type=int, default=25,
                    help="max candidates this run (default 25)")
    ap.add_argument("--window-hours", type=int, default=loft_law.WINDOW_HOURS,
                    help=f"scan window in hours (default {loft_law.WINDOW_HOURS})")
    args = ap.parse_args()

    if not args.run:
        ap.print_help()
        return 2

    report = loft_law.run_discovery(dry_run=args.dry_run,
                                    limit=max(1, args.limit),
                                    window_hours=max(1, args.window_hours))
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        _print_human(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
