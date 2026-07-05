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
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from lib.hermes_discovery import tag_lift  # noqa: E402


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

    report = tag_lift.run_discovery(dry_run=args.dry_run,
                                    bus_path=args.bus_path,
                                    history_dir=args.history_dir,
                                    feed_path=args.feed_path)
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        _print_human(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
