#!/usr/bin/env python3
"""Watch Desk v4 (E1): persist sector-ETF vs SPY relative strength daily.

The Sectors tab only had day-% snapshots — no history, so no trend. This job writes
one row per sector ETF per trading day into sector_rs_daily (close, spy_close,
rs = close/spy_close). The tab renders 20d/60d RS sparklines from it.

  python scripts/sector_rs_daily.py              # upsert today from latest quotes
  python scripts/sector_rs_daily.py --backfill   # rebuild from market_quotes history (~since 05-05)

Cron: 17:20 weekdays (after close, before the 17:40 Gain Guardian run).
Read-only against quotes; never deletes (upsert by (rs_date, symbol)).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except Exception:
    pass

SECTOR_ETFS = ["XLK", "XLV", "XLF", "XLY", "XLP", "XLE", "XLI", "XLB", "XLRE", "XLU", "XLC"]
BENCH = "SPY"


def _ensure(ex):
    ex("""CREATE TABLE IF NOT EXISTS sector_rs_daily (
            rs_date date NOT NULL,
            symbol text NOT NULL,
            close numeric,
            spy_close numeric,
            rs numeric,
            PRIMARY KEY (rs_date, symbol))""", fetch=None)


def backfill(ex) -> int:
    """Daily last-quote per symbol from market_quotes history → rs rows."""
    n = ex("""
        WITH daily AS (
            SELECT DISTINCT ON (upper(symbol), fetched_at::date)
                   upper(symbol) AS symbol, fetched_at::date AS d, price
            FROM market_quotes
            WHERE upper(symbol) = ANY(%s) AND price IS NOT NULL AND price > 0
            ORDER BY upper(symbol), fetched_at::date, fetched_at DESC
        ), spy AS (
            SELECT d, price AS spy_price FROM daily WHERE symbol = %s
        )
        INSERT INTO sector_rs_daily (rs_date, symbol, close, spy_close, rs)
        SELECT dd.d, dd.symbol, dd.price, s.spy_price,
               round((dd.price / s.spy_price)::numeric, 6)
        FROM daily dd JOIN spy s USING (d)
        WHERE dd.symbol <> %s
        ON CONFLICT (rs_date, symbol) DO UPDATE
            SET close = EXCLUDED.close, spy_close = EXCLUDED.spy_close, rs = EXCLUDED.rs
        RETURNING 1""", (SECTOR_ETFS + [BENCH], BENCH, BENCH), fetch="all")
    return len(n or [])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", action="store_true")
    args = ap.parse_args()
    from db_adapter import _execute as ex
    _ensure(ex)
    # today's pass and backfill share one idempotent upsert — today is just the tail
    rows = backfill(ex)
    scope = "backfill" if args.backfill else "daily"
    print(f"[sector-rs] {scope}: {rows} (rs_date,symbol) rows upserted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
