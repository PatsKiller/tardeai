#!/usr/bin/env python3
"""Watch Desk v4 (E1): persist sector-ETF vs SPY relative strength daily.

The Sectors tab only had day-% snapshots — no history, so no trend. This job writes
one row per sector ETF per trading day into sector_rs_daily (close, spy_close,
rs = close/spy_close). The tab renders 20d/60d RS sparklines from it.

  python scripts/sector_rs_daily.py              # upsert today from latest quotes
  python scripts/sector_rs_daily.py --backfill   # rebuild from market_quotes history (~since 05-05)

  python scripts/sector_rs_daily.py --dry-run    # count what would be upserted; write nothing

Cron: 17:20 weekdays (after close, before the 17:40 Gain Guardian run).
Read-only against quotes; never deletes (upsert by (rs_date, symbol)).

n8n refactor wave 1 (2026-10-10): ``--dry-run`` runs a SEPARATE read-only SELECT (the same CTE
without INSERT, no CREATE TABLE) and reports the rows that would be upserted (new vs existing).
A real run writes ``<state_root>/data/runtime/sector-rs-daily_last.json`` (LaneRunReceipt@v1; ok_at
only on success). A SQL error used to print "0 rows upserted" and exit 0 (db_adapter._execute
returns None on error); it now exits 1.
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
    ex(
        """CREATE TABLE IF NOT EXISTS sector_rs_daily (
            rs_date date NOT NULL,
            symbol text NOT NULL,
            close numeric,
            spy_close numeric,
            rs numeric,
            PRIMARY KEY (rs_date, symbol))""",
        fetch=None,
    )


_DAILY_CTE = """
        WITH daily AS (
            SELECT DISTINCT ON (upper(symbol), fetched_at::date)
                   upper(symbol) AS symbol, fetched_at::date AS d, price
            FROM market_quotes
            WHERE upper(symbol) = ANY(%s) AND price IS NOT NULL AND price > 0
            ORDER BY upper(symbol), fetched_at::date, fetched_at DESC
        ), spy AS (
            SELECT d, price AS spy_price FROM daily WHERE symbol = %s
        )"""


def preview(ex) -> dict | None:
    """Read-only twin of backfill(): what the upsert WOULD touch. Never writes, never creates."""
    reg = ex("SELECT to_regclass('sector_rs_daily') IS NOT NULL AS present", fetch="one")
    if reg is None:
        return None
    present = bool(reg.get("present") if isinstance(reg, dict) else reg[0])
    if present:
        sql = (
            _DAILY_CTE
            + """
        SELECT count(*) AS would_upsert,
               count(*) FILTER (WHERE r.rs_date IS NULL) AS would_insert,
               max(dd.d) AS latest_date
        FROM daily dd JOIN spy s USING (d)
        LEFT JOIN sector_rs_daily r ON r.rs_date = dd.d AND r.symbol = dd.symbol
        WHERE dd.symbol <> %s"""
        )
    else:
        sql = (
            _DAILY_CTE
            + """
        SELECT count(*) AS would_upsert, count(*) AS would_insert, max(dd.d) AS latest_date
        FROM daily dd JOIN spy s USING (d)
        WHERE dd.symbol <> %s"""
        )
    row = ex(sql, (SECTOR_ETFS + [BENCH], BENCH, BENCH), fetch="one")
    if row is None:
        return None
    row = dict(row) if isinstance(row, dict) else dict(zip(("would_upsert", "would_insert", "latest_date"), row))
    row["table_present"] = present
    return row


def backfill(ex) -> int | None:
    """Daily last-quote per symbol from market_quotes history → rs rows."""
    n = ex(
        """
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
        RETURNING 1""",
        (SECTOR_ETFS + [BENCH], BENCH, BENCH),
        fetch="all",
    )
    if n is None:  # db_adapter._execute returns None on a SQL error / no connection
        return None
    return len(n)


LANE_ID = "sector-rs-daily"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="read-only preview of the upsert; write nothing")
    args = ap.parse_args(argv)
    from db_adapter import _execute as ex
    from lib.lane_last_receipt import dry_run_report, now_iso, write_lane_receipt

    scope = "backfill" if args.backfill else "daily"
    if args.dry_run:
        # Returns before _ensure()/backfill() are reachable (AGENTS.md §6).
        pv = preview(ex)
        if pv is None:
            print(f"[sector-rs] DRY-RUN {scope}: preview query FAILED")
            return 1
        print(
            f"[sector-rs] DRY-RUN {scope}: would upsert {pv['would_upsert']} (rs_date,symbol) rows "
            f"({pv['would_insert']} new), latest {pv['latest_date']}"
        )
        dry_run_report(
            LANE_ID, {"scope": scope, **pv}, would_write=[f"sector_rs_daily: upsert {pv['would_upsert']} rows"]
        )
        return 0
    started = now_iso()
    _ensure(ex)
    # today's pass and backfill share one idempotent upsert — today is just the tail
    rows = backfill(ex)
    if rows is None:
        print(f"[sector-rs] {scope}: upsert FAILED (SQL error — see db_adapter line above)")
        write_lane_receipt(
            LANE_ID,
            ok=False,
            started_at=started,
            script="sector_rs_daily.py",
            exit_code=1,
            summary={"scope": scope, "error": "upsert returned no result"},
        )
        return 1
    print(f"[sector-rs] {scope}: {rows} (rs_date,symbol) rows upserted")
    write_lane_receipt(
        LANE_ID,
        ok=True,
        started_at=started,
        script="sector_rs_daily.py",
        exit_code=0,
        summary={"scope": scope, "rows_upserted": rows},
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
