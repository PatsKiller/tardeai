#!/usr/bin/env python3
"""Record a non-secret compound-lane result after an owned child has finished.

Private child of agent intelligence, inference, research overnight and cost runners.
This CLI schedules nothing and stores only explicit lane/step/exit metadata.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

NO_CONSUMER_REASON = "private receipt child of the owned compound cron/timer entrypoints"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--lane", required=True)
    parser.add_argument("--step")
    parser.add_argument("--exit", type=int, required=True, dest="exit_code")
    args = parser.parse_args(argv)
    from scripts.lib.lane_last_receipt import write_lane_receipt

    lane = args.lane + ("--step-" + args.step if args.step else "")
    result = write_lane_receipt(
        lane, ok=args.exit_code == 0, exit_code=args.exit_code,
        script="completion_compound_receipt.py",
        summary={"step": args.step, "status": "RUN_SKIPPED_LOCK" if args.exit_code == 75 else
                 ("completed" if args.exit_code == 0 else "failed")},
    )
    return 0 if result else 1


if __name__ == "__main__":
    raise SystemExit(main())
