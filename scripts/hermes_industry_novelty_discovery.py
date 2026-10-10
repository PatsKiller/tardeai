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

Lane hermes-industry-novelty-discovery (cron L686, `--run --json` behind the DeepSeek off-peak wrapper).
--dry-run never reaches inbox.upsert_candidate (industry_novelty.run_discovery gates it on the effective dry run before
the call), runs its SELECTs in a READ ONLY db_adapter session, prints a DRY-RUN report (stderr when --json) and
writes no receipt. A real --run writes <state_root>/data/runtime/hermes-industry-novelty-discovery_last.json (LaneRunReceipt@v1; ok_at only
on success) -- including a schedule-disabled (effective dry) pass, which is a successful run that wrote nothing.
Exit codes: 0 = ran (zero candidates is a finding); 1 = crash (an upsert error propagates: failed receipt,
re-raised); 2 = usage (no --run).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from lib.hermes_discovery import industry_novelty  # noqa: E402

LANE_ID = "hermes-industry-novelty-discovery"


def _receipt_lib():
    from lib import lane_last_receipt as lr
    return lr


def _readonly_db_session() -> bool:
    """Dry run: put the db_adapter session the lib reads through in READ ONLY at the server (AGENTS.md §6).

    Defence in depth only: the lib's dry-run branch already returns before every write."""
    try:
        from db_adapter import _get_conn
        conn = _get_conn()
        if conn is None:
            return False
        _receipt_lib().enforce_readonly(conn)
        return True
    except Exception as exc:
        print(f"[{LANE_ID}] READ ONLY session not established: {type(exc).__name__}", file=sys.stderr)
        return False


def _dry_report(summary, *, would_write, json_stdout=False):
    """lane_last_receipt.dry_run_report, sent to stderr when stdout carries the script's JSON report."""
    import contextlib
    with contextlib.redirect_stdout(sys.stderr) if json_stdout else contextlib.nullcontext():
        return _receipt_lib().dry_run_report(LANE_ID, summary, would_write=would_write)


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

    if args.dry_run:
        readonly = _readonly_db_session()
        report = industry_novelty.run_discovery(dry_run=True, limit=args.limit)
    else:
        from datetime import datetime, timezone
        started = datetime.now(timezone.utc).isoformat()
        try:
            report = industry_novelty.run_discovery(dry_run=False, limit=args.limit)
        except Exception as exc:
            _receipt_lib().write_lane_receipt(LANE_ID, ok=False, exit_code=1, started_at=started,
                                              script="hermes_industry_novelty_discovery.py",
                                              error=f"{type(exc).__name__}: {exc}")
            raise
        _receipt_lib().write_lane_receipt(
            LANE_ID, ok=True, exit_code=0, started_at=started, script="hermes_industry_novelty_discovery.py",
            summary={k: report.get(k) for k in ('scanned_sectors', 'novel_detected', 'upserted', 'effective_dry_run', 'enabled_in_schedule')})
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        _print_human(report)
    if args.dry_run:
        _dry_report({**{k: report.get(k) for k in ('scanned_sectors', 'novel_detected', 'would_upsert', 'enabled_in_schedule')}, "readonly_session": readonly},
                    would_write=['discovery inbox GAP_CANDIDATE (inbox.upsert_candidate)'], json_stdout=args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
