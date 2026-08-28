#!/usr/bin/env python3
"""Report lanes that have stopped producing. Read-only; writes nothing.

    python scripts/pipeline_liveness_report.py                  # human summary
    python scripts/pipeline_liveness_report.py --json           # machine readable
    python scripts/pipeline_liveness_report.py --fail-on-finding  # exit 1 to gate cron/CI

The CIO evidence gate blocked 54 of 55 runs for 17 continuous days and nothing
raised an alarm. Every block was recorded; no monitor watched the record. This
measures absence of throughput rather than parsing error logs, because a broken
lane and an idle lane both emit nothing -- the difference is whether work was
attempted.

STARVED means work entered the lane and nothing came out. That is the shape of
the 17-day outage and the only status that should wake anyone.

AUTHORITY: READ_ONLY_ADVISORY.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib.pipeline_liveness import (  # noqa: E402
    LIVE,
    NO_ELIGIBLE_INPUT,
    QUIET,
    STARVED,
    UNKNOWN,
    default_lanes,
    evaluate,
)

_MARK = {LIVE: "ok  ", STARVED: "STARVED", QUIET: "quiet", UNKNOWN: "UNKNOWN",
         NO_ELIGIBLE_INPUT: "NO-INPUT"}


def main() -> int:
    ap = argparse.ArgumentParser(description="Pipeline liveness — detect lanes that stopped producing")
    ap.add_argument("--json", action="store_true", help="emit JSON")
    ap.add_argument("--fail-on-finding", action="store_true",
                    help="exit 1 on any finding (STARVED, NO_ELIGIBLE_INPUT or UNKNOWN), for cron/CI gating")
    ap.add_argument("--window-hours", type=float, default=None,
                    help="override every lane's window (default: per-lane)")
    args = ap.parse_args()

    lanes = default_lanes()
    if args.window_hours:
        for lane in lanes:
            lane.window_hours = args.window_hours

    report = evaluate(lanes)
    result = report.to_dict()

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        for lane in result["lanes"]:
            mark = _MARK.get(lane["status"], lane["status"])
            produced = lane.get("produced", "?")
            attempted = lane.get("attempted", "?")
            print(f"{mark:8} {lane['lane']:34} "
                  f"produced {produced}/{attempted} attempted "
                  f"in {lane['window_hours']:g}h — {lane['describe']}")
        if result["findings"]:
            print()
            for finding in result["findings"]:
                if finding["status"] == STARVED:
                    print(f"FINDING  {finding['lane']}: {finding.get('attempted')} attempted, "
                          f"{finding.get('produced')} produced. Work is entering this lane "
                          f"and nothing is coming out.")
                elif finding["status"] == NO_ELIGIBLE_INPUT:
                    print(f"FINDING  {finding['lane']}: {finding.get('attempted')} attempted, "
                          f"0 of them eligible to produce this output. Nothing is blocked — "
                          f"no producer is emitting input this lane can promote.")
                else:
                    print(f"FINDING  {finding['lane']}: {finding.get('detail', 'source unreadable')}")

    if args.fail_on_finding and result["findings"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
