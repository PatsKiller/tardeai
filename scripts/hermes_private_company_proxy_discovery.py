#!/usr/bin/env python3
"""hermes_private_company_proxy_discovery.py — private-company / public-proxy
discovery CLI (White-Space spec Part C).

Detects notable PRIVATE companies in the existing corpus (news_articles +
hermes_research_intelligence): entities that recur across sources, look like
proper nouns, and FAIL symbol validation (not directly listed). For each, the
corpus itself is scanned for ownership/acquisition phrases linking the private
name to a listed company; evidenced links become proxy_underlyings, no
evidence means nulls + recommended_action=research_only — ownership is never
invented. Emits PRIVATE_COMPANY_PROXY_CANDIDATE rows (candidates only,
OPERATOR_REVIEW_REQUIRED) through the Discovery Inbox.

Usage:
  python3 scripts/hermes_private_company_proxy_discovery.py --run [--dry-run]
          [--json] [--limit N] [--window-days D]
  python3 scripts/hermes_private_company_proxy_discovery.py --company NAME
          [--company NAME2 ...] [--json] [--window-days D]

--company is a targeted, ALWAYS report-only analysis of one name (repeatable):
it reports honest verdicts (no_evidence → validate-first, directly_listed,
listed_company_name, below_thresholds, candidate) and never writes.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from lib.hermes_discovery import private_proxy  # noqa: E402


def _print_run(report: dict) -> None:
    emitted = report["would_upsert"] if report["dry_run"] else report["upserted"]
    print(f"[private-proxy] dry_run={report['dry_run']} "
          f"scanned_rows={report['scanned_rows']} detected={report['detected']} "
          f"emitted={emitted}")
    print(f"  thresholds: {report['thresholds']}")
    print(f"  skipped:    {report['skipped_reasons']}")
    for note in report["notes"]:
        print(f"  note: {note}")
    for c in report["candidates"]:
        ppj = c["private_proxy_json"]
        proxies = ", ".join(f"{p['ticker']}({p['relationship']},"
                            f"{p['confidence']})"
                            for p in ppj["proxy_underlyings"]) or "none"
        extra = f" #{c['id']} {c.get('status')}" if "id" in c else ""
        print(f"  - {c['label']}{extra} [{c['research_domain']}] "
              f"action={ppj['recommended_action']} proxies={proxies}")


def _print_company(report: dict) -> None:
    print(f"[private-proxy --company {report['company']!r}] "
          f"status={report['status']}")
    print(f"  corpus_rows={report['corpus_rows']} mentions={report['mentions']} "
          f"sources={report['cross_source_count']} {report['sources']}")
    if report.get("ticker_validation"):
        v = report["ticker_validation"]
        print(f"  ticker_validation: {v['verdict']} ({v['reason']})")
    if report.get("listed_name_symbols"):
        print(f"  listed_name_symbols: {report['listed_name_symbols']}")
    for p in report["proxies"]:
        print(f"  proxy: {p['ticker']} {p['relationship']} "
              f"conf={p['confidence']} status={p['acquisition_status']}")
        print(f"         evidence: {p['evidence'][:140]}")
    print(f"  {report['message']}")
    print(f"  writes: {report['writes']}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", action="store_true",
                    help="run corpus-wide private-company discovery")
    ap.add_argument("--dry-run", action="store_true",
                    help="detect + report only; write nothing")
    ap.add_argument("--json", action="store_true", help="JSON report output")
    ap.add_argument("--limit", type=int, default=None,
                    help=f"max candidates this run (default "
                         f"{private_proxy.MAX_CANDIDATES_PER_RUN})")
    ap.add_argument("--window-days", type=int, default=private_proxy.WINDOW_DAYS,
                    help="corpus lookback window in days")
    ap.add_argument("--company", action="append", default=None, metavar="NAME",
                    help="targeted analysis of one private-company name "
                         "(repeatable; ALWAYS report-only, never writes)")
    args = ap.parse_args()

    if args.company:
        reports = [private_proxy.analyze_company(
            name, window_days=max(1, args.window_days))
            for name in args.company]
        if args.json:
            print(json.dumps(reports if len(reports) > 1 else reports[0],
                             indent=2, default=str))
        else:
            for r in reports:
                _print_company(r)
        return 0

    if not args.run:
        ap.print_help()
        return 2

    report = private_proxy.run_discovery(dry_run=args.dry_run, limit=args.limit,
                                         window_days=max(1, args.window_days))
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        _print_run(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
