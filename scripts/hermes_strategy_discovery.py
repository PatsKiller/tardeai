#!/usr/bin/env python3
"""hermes_strategy_discovery.py — White-Space strategy-discovery CLI (spec Part B).

Diffs the candidate-strategy catalog (lib/hermes_discovery/strategy_discovery.py)
against the strategy registry (config/strategies/*.yaml strategy_id) and emits
the missing strategies as STRATEGY_CANDIDATE discovery-inbox candidates.

Importing this script registers the 'strategy' worker-pool lane runner
(worker_pool.register_lane_runner('strategy', ...)); --run executes that lane
through worker_pool.run_pool — the SAME lock / cadence / cap / domain-fence /
do-no-harm machinery every other lane runs under. Candidates only, ever:
promotion is structurally impossible in the pool, and every candidate is
educational_only + operator-review-required by construction.

Usage:
  python3 scripts/hermes_strategy_discovery.py --run [--dry-run] [--force] [--json]
  python3 scripts/hermes_strategy_discovery.py --catalog [--json]   # diff only, no writes
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from lib.hermes_discovery import strategy_discovery, worker_pool  # noqa: E402


def _catalog_report() -> dict:
    diff = strategy_discovery.catalog_diff()
    payloads = strategy_discovery.build_payloads()
    return {
        "catalog_size": len(strategy_discovery.STRATEGY_CATALOG),
        "registry_ids": sorted(diff["registry_ids"]),
        "missing_count": len(diff["missing"]),
        "skipped": diff["skipped"],
        "candidates": [{"label": p["label"],
                        "normalized_key": p["normalized_key"],
                        "research_domain": p["meta"]["research_domain"],
                        "family": p["meta"]["strategy_json"]["family"]}
                       for p in payloads],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", action="store_true",
                    help="run the 'strategy' lane through the worker pool")
    ap.add_argument("--dry-run", action="store_true",
                    help="list would-be candidates; writes NOTHING")
    ap.add_argument("--force", action="store_true",
                    help="ignore the lane cadence state")
    ap.add_argument("--json", action="store_true", help="JSON output")
    ap.add_argument("--catalog", action="store_true",
                    help="show the catalog↔registry diff (never writes)")
    args = ap.parse_args()

    if args.catalog:
        report = _catalog_report()
        if args.json:
            print(json.dumps(report, indent=2, default=str))
        else:
            print(f"catalog={report['catalog_size']} "
                  f"missing={report['missing_count']} "
                  f"skipped={len(report['skipped'])} "
                  f"registry_ids={len(report['registry_ids'])}")
            for c in report["candidates"]:
                print(f"  STRATEGY_CANDIDATE {c['label']!r} "
                      f"[{c['family']} → {c['research_domain']}]")
            for s in report["skipped"]:
                print(f"  skipped {s['catalog_id']}: {s['reason']} "
                      f"({s['registry_id']}={s['registry_status']})")
        return 0

    if not args.run:
        ap.print_help()
        return 2

    report = worker_pool.run_pool([strategy_discovery.LANE_ID],
                                  dry_run=args.dry_run, force=args.force)
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        lane = (report.get("lanes") or {}).get(strategy_discovery.LANE_ID, {})
        if report.get("error"):
            print(f"ERROR: {report['error']}")
        elif lane.get("error"):
            print(f"[strategy] ERROR: {lane['error']}")
        elif lane.get("skipped"):
            print(f"[strategy] skipped: {lane['skipped']}")
        else:
            print(f"[strategy] dry_run={report['dry_run']} "
                  f"scanned={lane.get('scanned')} upserted={lane.get('upserted')} "
                  f"skipped_payloads={lane.get('skipped_payloads')}")
            for c in lane.get("candidates") or []:
                extra = f" #{c['id']} {c.get('status')}" if "id" in c else ""
                print(f"    {c.get('candidate_type')} {c.get('label')!r}{extra}")
            if lane.get("skipped_reasons"):
                print(f"    skipped_reasons: {lane['skipped_reasons']}")
    return 1 if report.get("error") else 0


if __name__ == "__main__":
    raise SystemExit(main())
