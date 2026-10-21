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

# P10 (2026-09-16): this entrypoint exists, is tested, and is invoked by no cron
# line and no systemd unit, so `sweep_due_commitments` has never run unattended
# -- 224 durable commitments carry zero outcomes. Declared rather than installed:
# a new cron or systemd entry is operator-only (AGENTS.md §17).
SCHEDULED_ENTRYPOINT = (
    "cron: 20 18 * * * -- daily, --apply --state-root ~/trade-ai-state/persistent_wake/state "
    "(lane commitment-outcome-sweep; installed 2026-09-24 under an operator cron grant)"
)

DEFAULT_STATE_ROOT = Path("/home/johnclaw/trade-ai-state/persistent_wake/state")
COMMITMENTS = "commitments.jsonl"
OUTCOME_LEDGER = "commitment_outcomes.jsonl"
LESSON_LEDGER = "lesson_candidates.jsonl"


def _run(args) -> int:
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

    # 2026-09-24 (tranche 1, 3b): the default provider returned {} and settled
    # everything EXPIRED. Prices come from the resolver's own ticker_prices
    # lookup; when the DB is unreachable the factory yields a None-lookup and the
    # provider answers {} — INSUFFICIENT_EVIDENCE, never an invented result.
    from scripts.lib.commitment_price_observation import make_price_observation_provider
    from scripts.resolve_due_checkpoints import _price_lookup_factory

    # #1633 (2026-10-09): --as-of simulates the sweep at another instant (report only).
    when = getattr(args, "when", None) or datetime.now(timezone.utc)
    provider = make_price_observation_provider(price_lookup=_price_lookup_factory(), now=when)
    res = sweep_due_commitments(commitments, ledger=ledger, now=when,
                                observation_provider=provider)
    report = res.to_dict()
    if getattr(args, "when", None) is not None:
        # Only on an --as-of simulation: the live report stays byte-identical (frozen entrypoint, shard 05).
        report["as_of"] = when.isoformat()
    report["state_root"] = str(root)
    report["applied"] = bool(args.apply)
    report["commitments_path"] = str(root / COMMITMENTS)

    if args.apply and res.outcomes:
        report["outcomes_appended"] = append_jsonl(root / OUTCOME_LEDGER, res.outcomes)
    if args.apply and res.lessons:
        report["lessons_appended"] = append_jsonl(root / LESSON_LEDGER, res.lessons)

    global LAST_SUMMARY
    LAST_SUMMARY = {"outcomes": len(res.outcomes), "lessons": len(res.lessons), "due": getattr(res, "due", None),
                    "already_settled": getattr(res, "already_settled", None)}
    print(json.dumps(report, indent=2, default=str))
    return 0


LAST_SUMMARY = {}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    ap.add_argument("--state-root", default=str(DEFAULT_STATE_ROOT))
    ap.add_argument("--apply", action="store_true", help="append outcomes and lesson candidates")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="offline plan; wins over --apply")
    ap.add_argument(
        "--as-of",
        default=None,
        help="simulate the sweep at this ISO instant (report only; refused with --apply)",
    )
    args = ap.parse_args(argv)
    if args.dry_run:
        print(f"DRY-RUN commitment-outcome-sweep: would score due commitments under {args.state_root} "
              "and append outcomes/PROPOSED lessons plus a lane receipt; inputs NOT_MEASURED")
        return 0
    args.when = None
    if args.as_of:
        if args.apply:
            # A backdated or future-dated evaluated_at must never reach the ledger.
            print(json.dumps({"ok": False, "outcome": "AS_OF_REFUSED_WITH_APPLY"}, indent=2))
            return 2
        try:
            when = datetime.fromisoformat(str(args.as_of).replace("Z", "+00:00"))
        except ValueError:
            print(json.dumps({"ok": False, "outcome": "AS_OF_UNPARSEABLE", "as_of": args.as_of}, indent=2))
            return 2
        args.when = when if when.tzinfo else when.replace(tzinfo=timezone.utc)
    from scripts.lib.lane_last_receipt import now_iso, write_lane_receipt
    started = now_iso()
    LAST_SUMMARY.clear()
    try:
        rc = _run(args)
    except Exception as exc:
        if args.apply:
            write_lane_receipt("commitment-outcome-sweep", ok=False, exit_code=1, started_at=started,
                               script="sweep_commitment_outcomes.py", error=type(exc).__name__,
                               output={"produced_count": 0, "attempted_count": 0, "skipped_reasons": {"dependency_unavailable": 1}})
        raise
    if args.apply:
        write_lane_receipt("commitment-outcome-sweep", ok=rc == 0, exit_code=rc, started_at=started,
                           script="sweep_commitment_outcomes.py", summary=LAST_SUMMARY,
                           output=lane_output(LAST_SUMMARY, rc))
    return rc


def lane_output(summary: dict, rc: int) -> dict:
    """LaneRunReceipt@v2 output fields (n8n expected_output, unit: evaluated outcomes appended to
    commitment_outcomes.jsonl). attempted = commitments due; none due = ``nothing_due``; no commitment store at all
    (exit 2) = ``no_input_unexpected``."""
    outcomes, due = int(summary.get("outcomes") or 0), int(summary.get("due") or 0)
    skipped = {"already_settled": int(summary.get("already_settled") or 0)}
    if rc == 2:
        skipped["no_input_unexpected"] = 1
    return {"produced_count": outcomes, "attempted_count": max(due, outcomes), "skipped_reasons": skipped,
            "empty_reason": "nothing_due" if outcomes == 0 and rc == 0 else None}


if __name__ == "__main__":
    raise SystemExit(main())
