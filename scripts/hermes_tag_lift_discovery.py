#!/usr/bin/env python3
"""hermes_tag_lift_discovery.py — tag-lift discovery CLI (spec Part F).

Folds OUTCOME evidence back into discovery: per-tag/source lift_ratio
(current outcome_bus.json vs the prior history snapshot) plus useful/false
outcome counts (hermes_discovery_outcome_feed.json + hermes_discovery_feedback)
become (a) bounded score-weight deltas on existing candidates via
feedback.apply_weight_delta (per-run ±0.1, cumulative hard bound ±0.3) and
(b) new TREND/TOPIC candidates ONLY when useful_outcome_count >=
tag_lift_min_outcomes (config, default 5).

Advisory-only: candidates + weight tilts, never promotion, never trading
thresholds/execution. Every input is read defensively — missing files/tables
are skipped with a note, never an exception.

Usage:
  python3 scripts/hermes_tag_lift_discovery.py --run [--dry-run] [--json]
      [--bus-path P] [--history-dir D] [--feed-path P]

Lane hermes-tag-lift-discovery (cron L684, `--run --json` behind the DeepSeek off-peak wrapper).
--dry-run never reaches feedback.apply_weight_delta or inbox.upsert_candidate (tag_lift.run_discovery gates both
on `not dry_run` before the call), runs its SELECTs in a READ ONLY db_adapter session, prints a DRY-RUN report
(stderr when --json) and writes no receipt. A real --run writes
<state_root>/data/runtime/hermes-tag-lift-discovery_last.json (LaneRunReceipt@v1; ok_at only on success).
Exit codes: 0 = ran (zero tags / zero candidates is a finding); 1 = crash (failed receipt, re-raised) or every
item failed (weight_deltas_planned > 0, weight_deltas_applied == 0 and nothing upserted; one failed delta is a
soft failure noted in the report); 2 = usage (no --run). A PEAK_SKIP by the wrapper never starts this script, so it
leaves no receipt (the lane goes stale, not green).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from lib.hermes_discovery import tag_lift  # noqa: E402

LANE_ID = "hermes-tag-lift-discovery"


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
    print(f"[tag-lift] dry_run={report['dry_run']} tags={report['tags_analyzed']} "
          f"deltas_planned={report['weight_deltas_planned']} "
          f"deltas_applied={report['weight_deltas_applied']} "
          f"candidates_planned={report['candidates_planned']} "
          f"upserted={report['upserted']}")
    print(f"  thresholds: {report['thresholds']}")
    print(f"  inputs:     {report['inputs']}")
    print(f"  by_type:    {report['by_type']}")
    print(f"  by_domain:  {report['by_domain']}")
    print(f"  skipped:    {report['skipped_reasons']}")
    for note in report["notes"]:
        print(f"  note: {note}")
    for d in report["weight_deltas"][:10]:
        target = d.get("trend_key") or d.get("source_domain")
        print(f"  Δ {d['kind']:6s} {target}: {d['delta']:+.3f} ({d['reason']})")
    for c in report["candidates"][:10]:
        tl = c["tag_lift_json"]
        print(f"  - {c['candidate_type']:16s} [{c['domain']}] {c['label']} "
              f"(useful={tl['useful_outcome_count']} lift_ratio={tl['lift_ratio']})")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", action="store_true", help="run tag-lift discovery")
    ap.add_argument("--dry-run", action="store_true",
                    help="compute + report only; NO weight deltas, NO upserts")
    ap.add_argument("--json", action="store_true", help="JSON report output")
    ap.add_argument("--bus-path", default=None, help="override outcome_bus.json path")
    ap.add_argument("--history-dir", default=None,
                    help="override outcome_bus_history dir (prior window)")
    ap.add_argument("--feed-path", default=None,
                    help="override hermes_discovery_outcome_feed.json path")
    args = ap.parse_args()

    if not args.run:
        ap.print_help()
        return 2

    if args.dry_run:
        readonly = _readonly_db_session()
        report = tag_lift.run_discovery(dry_run=True, bus_path=args.bus_path,
                                        history_dir=args.history_dir, feed_path=args.feed_path)
    else:
        from datetime import datetime, timezone
        started = datetime.now(timezone.utc).isoformat()
        try:
            report = tag_lift.run_discovery(dry_run=False, bus_path=args.bus_path,
                                            history_dir=args.history_dir, feed_path=args.feed_path)
        except Exception as exc:
            _receipt_lib().write_lane_receipt(LANE_ID, ok=False, exit_code=1, started_at=started,
                                              script="hermes_tag_lift_discovery.py",
                                              error=f"{type(exc).__name__}: {exc}")
            raise
        # every item failed: deltas were planned, none applied, and no candidate was upserted (upsert errors raise)
        failed = (bool(report.get("weight_deltas_planned")) and not report.get("weight_deltas_applied")
                  and not report.get("upserted"))
        _receipt_lib().write_lane_receipt(
            LANE_ID, ok=not failed, exit_code=1 if failed else 0, started_at=started, script="hermes_tag_lift_discovery.py",
            summary={k: report.get(k) for k in ('tags_analyzed', 'weight_deltas_planned', 'weight_deltas_applied', 'candidates_planned', 'upserted')},
            error="all_weight_deltas_failed" if failed else None)
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        _print_human(report)
    if args.dry_run:
        _dry_report({**{k: report.get(k) for k in ('tags_analyzed', 'weight_deltas_planned', 'candidates_planned')}, "readonly_session": readonly},
                    would_write=['feedback.apply_weight_delta (score-weight deltas)', 'discovery inbox (inbox.upsert_candidate)'], json_stdout=args.json)
        return 0
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
