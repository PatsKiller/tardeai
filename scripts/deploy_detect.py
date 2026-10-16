#!/usr/bin/env python3
"""deploy_detect.py — detect recent sells → deploy_events (live sync).

Run after Schwab/SnapTrade sync or via cron (~10:10 ET trading days).

  python3 scripts/deploy_detect.py              # dry-run last 14 days
  python3 scripts/deploy_detect.py --apply      # persist
  python3 scripts/deploy_detect.py --apply --days 30
"""
from __future__ import annotations

import sys as _dr_sys

if __name__ == "__main__" and "--dry-run" in _dr_sys.argv[1:]:
    # n8n onboarding (lane disposition 2026-10-15, MIGRATE_N8N): --dry-run is an OFFLINE plan and wins over every
    # live flag (--apply). It returns here, before the .env load, any DB/LLM/network/sender import and any file
    # write; it prints the plan and one LaneOutput@v1 line on stderr (produced 0, empty_reason dry_run).
    import os as _dr_os

    _dr_sys.path.insert(0, _dr_os.path.join(_dr_os.path.dirname(_dr_os.path.abspath(__file__))))
    from lib.lane_output import emit as _dr_emit, output_block as _dr_block

    _dr_lane = "deploy-detect"
    _dr_would = (
        "skip on a non-trading day (--trading-days-only), detect sells of the last --days (default 14) from "
        "the synced holdings history and, with --apply, upsert them into deploy_events (source live_detect)"
    )
    print(f"DRY-RUN {_dr_lane}: would {_dr_would}; argv={_dr_sys.argv[1:]!r}; dry-run wins over live flags; "
          "nothing read from env/DB/network, no model call, no send, no file write")
    _dr_emit(_dr_lane, "dry_run", _dr_block(produced=0, attempted=0, empty_reason="dry_run", unit="sell_event"))
    raise SystemExit(0)

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