#!/usr/bin/env python3
"""Score governed commitments whose horizon has closed.

The scheduled pass that did not exist. `evaluate_outcome` had a single caller
which ran it on the same line that minted the commitment, so a seven-day
prediction was scored at freeze time and nothing ever revisited it: 224 durable
commitments, zero carrying any outcome.

Defaults to a dry run. `--apply` is required to append to the durable ledger,
and even then nothing mutates a commitment and nothing changes production
behaviour -- lessons are emitted as PROPOSED candidates for a separate
ratification this tool cannot perform.

    python3 scripts/sweep_commitment_outcomes.py                  # report
    python3 scripts/sweep_commitment_outcomes.py --apply          # durable
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.lib.commitment_outcome_sweep import (  # noqa: E402
    append_jsonl,
    read_jsonl,
    sweep_due_commitments,
)

DEFAULT_STATE_ROOT = Path("/home/johnclaw/trade-ai-state/persistent_wake/state")
COMMITMENTS = "commitments.jsonl"
OUTCOME_LEDGER = "commitment_outcomes.jsonl"
LESSON_LEDGER = "lesson_candidates.jsonl"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--state-root", default=str(DEFAULT_STATE_ROOT))
    ap.add_argument(
        "--apply",
        action="store_true",
        help="append outcomes and lesson candidates to the durable ledgers",
    )
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    root = Path(args.state_root)
    commitments = read_jsonl(root / COMMITMENTS)
    ledger = read_jsonl(root / OUTCOME_LEDGER)
    if not commitments:
        # An absent store is not "nothing was due". Say which it is.
        print(
            json.dumps(
                {
                    "ok": False,
                    "outcome": "NO_COMMITMENT_STORE",
                    "path": str(root / COMMITMENTS),
                },
                indent=2,
            )
        )
        return 2

    res = sweep_due_commitments(commitments, ledger=ledger, now=datetime.now(timezone.utc))
    report = res.to_dict()
    report["state_root"] = str(root)
    report["applied"] = bool(args.apply)
    report["commitments_path"] = str(root / COMMITMENTS)

    if args.apply and res.outcomes:
        report["outcomes_appended"] = append_jsonl(root / OUTCOME_LEDGER, res.outcomes)
    if args.apply and res.lessons:
        report["lessons_appended"] = append_jsonl(root / LESSON_LEDGER, res.lessons)

    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
