#!/usr/bin/env python3
"""alpaca_paper_options_executor.py — operator CLI for the Alpaca PAPER options lane.

The ONLY entry point that can submit an options order in this lane, and it is
paper-locked (see scripts/lib/options_pipeline/alpaca_paper.py invariants:
ALPACA_PAPER_BASE_URL must resolve to paper-api.alpaca.markets, LIMIT orders
only, hard 1-contract cap, buy-to-open only). The scanner/generator never
import this — an order exists only because the operator ran this CLI.

Usage:
    # inspect the queue's Alpaca lane
    .venv/bin/python scripts/alpaca_paper_options_executor.py --status

    # operator marks a pending desk row as ready for the Alpaca paper lane
    .venv/bin/python scripts/alpaca_paper_options_executor.py --mark-ready <PROPOSAL_ID>

    # build + print the exact order payload — zero HTTP, zero state change
    .venv/bin/python scripts/alpaca_paper_options_executor.py \
        --submit --proposal-id <PROPOSAL_ID> --dry-run

    # real paper submit — BOTH flags are mandatory, refused otherwise
    .venv/bin/python scripts/alpaca_paper_options_executor.py \
        --submit --proposal-id <PROPOSAL_ID> --confirm

    # poll fills/rejects/closes → outcomes (add --dry-run to list only)
    .venv/bin/python scripts/alpaca_paper_options_executor.py --reconcile

    # operator-only: OUTCOME_RECORDED → READY_FOR_LIVE_REVIEW (never automatic)
    .venv/bin/python scripts/alpaca_paper_options_executor.py --mark-live-review <PROPOSAL_ID>
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

OPERATOR_ACTOR = "operator:alpaca_paper_options_executor_cli"


def _load_env() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv(PROJECT_ROOT / ".env")
    except Exception:
        pass


def _print(obj) -> None:
    print(json.dumps(obj, indent=2, default=str))


def cmd_status(ap) -> int:
    summary = ap.status_summary()
    print("options_approval_queue by status:")
    for row in summary:
        print(f"  {row['status']:<24} {row['n']}")
    lane_rows = []
    for st in ap.ALPACA_STATES:
        lane_rows.extend(ap.list_rows_in_status(st))
    if lane_rows:
        print("\nAlpaca paper lane:")
        for r in lane_rows:
            aj = (r.get("meta") or {}).get("alpaca_json") or {}
            oid = (aj.get("response") or {}).get("id") or "-"
            print(f"  {r['proposal_id']:<64} {r['status']:<24} order={oid}")
    else:
        print("\nAlpaca paper lane: (empty)")
    return 0


def cmd_mark_ready(ap, proposal_id: str, dry_run: bool) -> int:
    if dry_run:
        row = ap.get_queue_row(proposal_id)
        if not row:
            print(f"REFUSED: proposal {proposal_id!r} not in queue")
            return 1
        ok = row["status"] in ap.LEGAL_TRANSITIONS[ap.STATE_READY]
        _print({"dry_run": True, "proposal_id": proposal_id,
                "current_status": row["status"],
                "would_transition_to": ap.STATE_READY if ok else None,
                "legal": ok})
        return 0 if ok else 1
    _print(ap.mark_ready(proposal_id, operator_actor=OPERATOR_ACTOR))
    return 0


def cmd_mark_live_review(ap, proposal_id: str, dry_run: bool) -> int:
    if dry_run:
        row = ap.get_queue_row(proposal_id)
        if not row:
            print(f"REFUSED: proposal {proposal_id!r} not in queue")
            return 1
        ok = row["status"] == ap.STATE_OUTCOME
        _print({"dry_run": True, "proposal_id": proposal_id,
                "current_status": row["status"],
                "would_transition_to": ap.STATE_LIVE_REVIEW if ok else None,
                "legal": ok})
        return 0 if ok else 1
    _print(ap.mark_live_review(proposal_id, operator_actor=OPERATOR_ACTOR))
    return 0


def cmd_submit(ap, proposal_id: str, confirm: bool, dry_run: bool) -> int:
    if not proposal_id:
        print("REFUSED: --submit requires an explicit --proposal-id "
              "(operator action — there is no batch/auto submit).")
        return 2
    if dry_run:
        res = ap.submit_ready_proposal(proposal_id, confirm=False, dry_run=True)
        _print(res)
        return 0 if res.get("ok") else 1
    if not confirm:
        print("REFUSED: --submit requires --confirm (operator action). "
              "Use --dry-run to preview the payload without HTTP.")
        return 2
    res = ap.submit_ready_proposal(proposal_id, confirm=True, dry_run=False)
    _print(res)
    return 0 if res.get("ok") else 1


def cmd_reconcile(ap, dry_run: bool) -> int:
    res = ap.reconcile_fills(dry_run=dry_run)
    _print(res)
    return 0 if res.get("ok") else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Operator CLI — Alpaca PAPER options lane (limit-only, 1 contract)")
    parser.add_argument("--status", action="store_true",
                        help="queue summary + Alpaca-lane rows")
    parser.add_argument("--mark-ready", metavar="PROPOSAL_ID",
                        help="operator mark: pending/approved -> READY_FOR_ALPACA_PAPER")
    parser.add_argument("--mark-live-review", metavar="PROPOSAL_ID",
                        help="operator mark: OUTCOME_RECORDED -> READY_FOR_LIVE_REVIEW")
    parser.add_argument("--submit", action="store_true",
                        help="submit ONE ready proposal (needs --proposal-id and --confirm)")
    parser.add_argument("--proposal-id", default="",
                        help="explicit proposal id for --submit")
    parser.add_argument("--confirm", action="store_true",
                        help="operator confirmation for a real paper submit")
    parser.add_argument("--reconcile", action="store_true",
                        help="poll fills/rejects/closes -> outcomes")
    parser.add_argument("--dry-run", action="store_true",
                        help="everywhere: show what would happen — zero HTTP, zero writes")
    args = parser.parse_args(argv)

    actions = [bool(args.status), bool(args.mark_ready),
               bool(args.mark_live_review), bool(args.submit), bool(args.reconcile)]
    if sum(actions) != 1:
        parser.print_help()
        print("\nREFUSED: pick exactly one action "
              "(--status | --mark-ready | --mark-live-review | --submit | --reconcile)")
        return 2

    _load_env()
    from lib.options_pipeline import alpaca_paper as ap

    try:
        if args.status:
            return cmd_status(ap)
        if args.mark_ready:
            return cmd_mark_ready(ap, args.mark_ready, args.dry_run)
        if args.mark_live_review:
            return cmd_mark_live_review(ap, args.mark_live_review, args.dry_run)
        if args.submit:
            return cmd_submit(ap, args.proposal_id, args.confirm, args.dry_run)
        if args.reconcile:
            return cmd_reconcile(ap, args.dry_run)
    except (ap.PaperEndpointError, ap.OrderPolicyError,
            ap.IllegalTransitionError, ap.OperatorActionRequiredError) as e:
        print(f"REFUSED: {e}")
        return 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
