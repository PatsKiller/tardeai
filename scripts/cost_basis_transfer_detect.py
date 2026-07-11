#!/usr/bin/env python3
"""Detect cross-account transfers and carry forward cost basis history.

Compares a prior holdings snapshot against the current holdings.json (or two explicit files).
High-confidence matches auto-write to cost_basis_overrides.json; others land in
candidate_mappings_needing_confirmation.

  python3 scripts/cost_basis_transfer_detect.py                    # prior=.bak vs current
  python3 scripts/cost_basis_transfer_detect.py --dry-run         # detect only
  python3 scripts/cost_basis_transfer_detect.py --prior PATH --current PATH
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from lib.cost_basis_transfer import process_holdings_change  # noqa: E402

HOLDINGS = PROJECT_ROOT / "data" / "portfolios" / "state" / "holdings.json"


def main() -> int:
    ap = argparse.ArgumentParser(description="Detect IRA/broker transfers and tag cost basis history.")
    ap.add_argument("--prior", type=Path, help="Prior holdings JSON (default: holdings.json.bak_costbasis or .bak)")
    ap.add_argument("--current", type=Path, default=HOLDINGS, help="Current holdings JSON")
    ap.add_argument("--dry-run", action="store_true", help="Detect only — do not write overrides/events")
    ap.add_argument("--apply-tags", action="store_true",
                    help="Write transfer tags + basis back into --current holdings file")
    args = ap.parse_args()

    current_path = args.current
    if not current_path.exists():
        print(f"ERROR: current holdings not found: {current_path}", file=sys.stderr)
        return 1

    prior_path = args.prior
    if not prior_path:
        for candidate in (
            current_path.with_suffix(current_path.suffix + ".bak_costbasis"),
            current_path.with_suffix(current_path.suffix + ".bak"),
        ):
            if candidate.exists():
                prior_path = candidate
                break
    if not prior_path or not prior_path.exists():
        print("ERROR: no prior snapshot — pass --prior or ensure holdings.json.bak exists", file=sys.stderr)
        return 1

    prior_doc = json.loads(prior_path.read_text())
    current_doc = json.loads(current_path.read_text())
    out = process_holdings_change(prior_doc, current_doc, sync_source="manual_detect", apply=not args.dry_run)

    print(out.get("summary", "done"))
    for ev in out.get("transfer_events") or []:
        ps = ev.get("per_share_basis")
        ps_s = f"${ps:.4f}/sh" if ps else "basis unknown"
        print(f"  {ev.get('symbol')}: {ev.get('from_account')} → {ev.get('to_account')} "
              f"{ev.get('shares')} sh @ {ps_s} [{ev.get('confidence')}] {ev.get('status')}")

    if args.apply_tags and out.get("holdings_doc") and not args.dry_run:
        from holdings_guard import protected_holdings_write
        res = protected_holdings_write(
            out["holdings_doc"],
            source="cost_basis_transfer",
            account_key="transfer_tag",
            protect_basis=False,
            skip_transfer_detect=True,
        )
        print(f"holdings tags write: {res.get('status')}")

    print(json.dumps({k: v for k, v in out.items() if k != "holdings_doc"}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())