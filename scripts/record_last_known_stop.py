#!/usr/bin/env python3
"""Record a stop level the operator set (or saw) at Schwab, so stop_health keeps warning while Schwab is blind.

ZETA/DT 2026-10-15: resting Schwab stops filled with no near-trigger warning because the Schwab app is
deactivated and nothing local held the levels. This writes ONE row to the local stop_last_known table
(origin='operator'). It never calls Schwab or any broker; it does not place, cancel or modify an order.

  # list what stop_health is watching right now (read-only)
  python3 scripts/record_last_known_stop.py --list
  # record a level (dry run prints the row; --apply writes it)
  python3 scripts/record_last_known_stop.py --account schwab_rollover_ira --symbol NFLX --stop 69.14 --qty 400 --apply
  # retire a level (the stop filled or you cancelled it at Schwab)
  python3 scripts/record_last_known_stop.py --account schwab_rollover_ira --symbol ZETA --status filled --apply

An operator-entered level supersedes every older observation of that position's stops; a later complete
Schwab read (when Schwab is re-enabled) supersedes the operator rows.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from lib import last_known_stops as lks  # noqa: E402

_STATUSES = ("open", "filled", "cancelled")


def _list() -> int:
    from schwab_position_sync import _HOLDINGS_ACCT
    cfg = lks.load_config()
    stops = lks.load_last_known(brokers=cfg.get("brokers") or ["schwab"],
                                lookback_days=float(cfg.get("lookback_days") or 10))
    quotes = lks.holdings_quotes()
    for s in stops:
        q = quotes.get((_HOLDINGS_ACCT.get(s["account"], s["account"]), s["symbol"])) or {}
        px = q.get("price")
        dist = f"{(px - s['stop_price']) / px * 100:+.2f}%" if px else "n/a"
        print(f"{s['account']:<22} {s['symbol']:<6} stop ${s['stop_price']:<9.2f} price {px or 'n/a':<9} "
              f"dist {dist:<8} held {q.get('shares')} · {s['source']} {s['captured_at']}")
    print(f"{len(stops)} last-known stop level(s)")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--list", action="store_true", help="show the last-known stops stop_health is watching")
    ap.add_argument("--account", help="e.g. schwab_rollover_ira, schwab_taxable, schwab_roth_ira")
    ap.add_argument("--symbol")
    ap.add_argument("--stop", type=float, help="stop trigger price")
    ap.add_argument("--qty", type=float)
    ap.add_argument("--order-id", help="Schwab order number, if known")
    ap.add_argument("--status", choices=_STATUSES, default="open")
    ap.add_argument("--note")
    ap.add_argument("--apply", action="store_true", help="write the row (default: dry run)")
    a = ap.parse_args(argv)
    if a.list:
        return _list()
    if not a.account or not a.symbol:
        ap.error("--account and --symbol are required (or --list)")
    if a.status == "open" and (a.stop is None or a.stop <= 0):
        ap.error("--stop is required for an open stop")
    if not a.apply:
        print("DRY RUN (no write) — would record:", json.dumps({
            "account": a.account, "symbol": a.symbol.upper(), "stop_price": a.stop, "qty": a.qty,
            "order_id": a.order_id or f"operator-{a.symbol.upper()}-{a.account}", "status": a.status,
            "origin": "operator"}))
        return 0
    row = lks.record_operator_stop(account=a.account, symbol=a.symbol, stop_price=a.stop, qty=a.qty,
                                   order_id=a.order_id, status=a.status, note=a.note)
    print("recorded:", json.dumps(row))
    return 0


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv(str(PROJECT_ROOT / ".env"))
    sys.exit(main())
