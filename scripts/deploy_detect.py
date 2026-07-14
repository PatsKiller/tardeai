#!/usr/bin/env python3
"""deploy_detect.py — detect recent sells → deploy_events (live sync).

Run after Schwab/SnapTrade sync or via cron (~10:10 ET trading days).

  python3 scripts/deploy_detect.py              # dry-run last 14 days
  python3 scripts/deploy_detect.py --apply      # persist
  python3 scripts/deploy_detect.py --apply --days 30
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from lib.sale_event_detector import sync_deploy_events  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Detect recent sells into deploy_events")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--trading-days-only", action="store_true",
                    help="Exit 0 without syncing on weekends/holidays")
    args = ap.parse_args()
    if args.trading_days_only:
        from market_session import is_trading_day
        if not is_trading_day():
            print(json.dumps({"ok": True, "skipped": "not_trading_day", "applied": False}))
            return 0
    report = sync_deploy_events(apply=args.apply, days=args.days, source="live_detect")
    print(json.dumps(report, indent=2, default=str))
    return 0 if not report.get("errors") else 1


if __name__ == "__main__":
    raise SystemExit(main())