#!/usr/bin/env python3
"""backfill_journal_complete.py — Backfill all journal entries with tags, EQ, R:R, replay, critiques.

Usage:
    python scripts/backfill_journal_complete.py --apply
    python scripts/backfill_journal_complete.py --apply --days 365 --force-critique
    python scripts/backfill_journal_complete.py --apply --rr-only
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import journal_trade_in_view as tiv


def main():
    ap = argparse.ArgumentParser(description="Backfill journal reviews, R:R, EQ, and critiques")
    ap.add_argument("--apply", action="store_true", help="Write to DB (required)")
    ap.add_argument("--days", type=int, default=3650, help="Lookback window for closed trades")
    ap.add_argument("--account", default=None)
    ap.add_argument("--rr-only", action="store_true", help="Only backfill planned_r/realized_r")
    ap.add_argument("--no-critiques", action="store_true")
    ap.add_argument("--force-critique", action="store_true")
    ap.add_argument("--eq-limit", type=int, default=500)
    ap.add_argument("--critique-limit", type=int, default=500)
    args = ap.parse_args()

    if not args.apply:
        print(json.dumps({
            "ok": True,
            "dry_run": True,
            "note": "Pass --apply to execute backfill_journal_complete / backfill_journal_rr",
        }, indent=2))
        return 0

    if args.rr_only:
        report = tiv.backfill_journal_rr(days=args.days, account=args.account, overwrite=True)
    else:
        report = tiv.backfill_journal_complete(
            days=args.days,
            account=args.account,
            eq_limit=args.eq_limit,
            critiques=not args.no_critiques,
            critique_limit=args.critique_limit,
            force_critique=args.force_critique,
        )
    print(json.dumps(report, indent=2, default=str))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())