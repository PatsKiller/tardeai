#!/usr/bin/env python3
"""deploy_backfill.py — 24-month post-sale redeploy event backfill (advisory only).

  python3 scripts/deploy_backfill.py                    # dry-run
  python3 scripts/deploy_backfill.py --apply            # persist deploy_events
  python3 scripts/deploy_backfill.py --apply --months 24

Policy (approved): sells older than 90 days → status=dismissed (historical_backfill_over_90d).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from lib.sale_event_detector import sync_deploy_events  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Backfill deploy_events from trade_transactions sells")
    ap.add_argument("--apply", action="store_true", help="Write to DB (default: dry-run)")
    ap.add_argument("--months", type=int, default=24, help="Lookback window (default 24)")
    ap.add_argument("--dismiss-after-days", type=int, default=90,
                    help="Auto-dismiss backfill events older than N days (default 90)")
    args = ap.parse_args()
    since = date.today() - timedelta(days=max(1, args.months) * 30)
    report = sync_deploy_events(
        apply=args.apply,
        since=since,
        source="backfill",
        dismiss_after_days=args.dismiss_after_days,
    )
    print(json.dumps(report, indent=2, default=str))
    return 0 if not report.get("errors") else 1


if __name__ == "__main__":
    raise SystemExit(main())