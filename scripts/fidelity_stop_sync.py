#!/usr/bin/env python3
"""fidelity_stop_sync.py — record Fidelity GTC sell stops for Stop Management (read-only).

SnapTrade syncs Fidelity positions and activities but returns zero open/pending orders — GTC stops
placed in Fidelity Active Trader must be recorded here. Dry-run by default.

  python3 scripts/fidelity_stop_sync.py                    # dry-run known rollover stops
  python3 scripts/fidelity_stop_sync.py --apply          # persist to manual_broker_stops
  python3 scripts/fidelity_stop_sync.py --apply --json stops.json
  python3 scripts/fidelity_stop_sync.py --apply --trading-days-only   # cron (skip weekends/holidays)
"""
from __future__ import annotations

import sys as _f09_sys

if __name__ == "__main__" and "--dry-run" in _f09_sys.argv[1:]:
    # n8n onboarding F09 (operator N8N Cutover Decision 2026-10-15; staged under AGENTS.md §23.14 until 12.0.0 is
    # ratified): --dry-run is OFFLINE and wins over every live flag. It returns here, before any .env load, DB,
    # broker, LLM, network or sender import and before any file write, and it makes NO broker call, not even a read.
    # It prints the plan and one LaneOutput@v1 line on stderr: produced 0, empty_reason dry_run
    # (offline plan; the live work's inputs are not read). Proof: tests/test_onboard_f09_b2_20261015.py.
    import os as _f09_os

    _f09_sys.path.insert(0, _f09_os.path.dirname(_f09_os.path.abspath(__file__)))
    from lib.lane_output import emit as _f09_emit, output_block as _f09_block

    _f09_lane = "fidelity-stop-sync"
    _f09_would = (
        "record the known Fidelity GTC sell stops for Stop Management from local config (no broker read) and, "
        "with --apply, persist them"
    )
    print(f"DRY-RUN {_f09_lane}: would {_f09_would}; argv={_f09_sys.argv[1:]!r}; dry-run wins over live flags; "
          "offline plan only; "
          "nothing read from env/DB/broker/network, no model call, no send, no file write")
    _f09_emit(_f09_lane, "dry_run", _f09_block(produced=0, attempted=0, empty_reason="dry_run",
                                               unit="Fidelity GTC stops recorded"))
    raise SystemExit(0)

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from lib.fidelity_stop_sync import (  # noqa: E402
    configured_stops_account,
    default_fidelity_rollover_stops,
    sync_stops,
)


def main() -> int:
    ap = argparse.ArgumentParser(description="Sync Fidelity GTC stops into manual_broker_stops")
    ap.add_argument("--apply", action="store_true", help="Write to DB (default: dry-run)")
    ap.add_argument("--json", help="JSON file: list of {symbol, stop_price, qty, account?, placed_date?}")
    ap.add_argument("--no-retire", action="store_true", help="Do not deactivate stops absent from input")
    ap.add_argument("--trading-days-only", action="store_true",
                    help="Exit 0 without syncing on weekends/US market holidays (for cron)")
    args = ap.parse_args()

    if args.trading_days_only:
        from market_session import is_trading_day
        if not is_trading_day():
            print(json.dumps({"ok": True, "skipped": "not_trading_day", "applied": False}))
            return 0

    if args.json:
        rows = json.loads(Path(args.json).read_text())
        if isinstance(rows, dict):
            rows = rows.get("stops") or rows.get("rows") or []
        retire_account = None
    else:
        rows = default_fidelity_rollover_stops()
        retire_account = configured_stops_account()

    report = sync_stops(rows, retire_absent=not args.no_retire, apply=args.apply,
                        retire_account=retire_account)
    print(json.dumps(report, indent=2, default=str))
    return 0 if not report.get("errors") else 1


if __name__ == "__main__":
    raise SystemExit(main())