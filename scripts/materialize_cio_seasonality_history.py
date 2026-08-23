#!/usr/bin/env python3
"""Backfill adjusted daily benchmark/sector prices for SeasonalityState@v1.

This is advisory data acquisition only. It writes market_ohlcv_bars and has no
financial execution or protection imports.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from typing import Any

from scripts.lib.cio_market_context_state import connect_trade_ai_readonly


DEFAULT_SYMBOLS = ("SPY", "XLB", "XLC", "XLE", "XLF", "XLI", "XLK", "XLP", "XLRE", "XLU", "XLV", "XLY")


def fetch_adjusted_daily(symbols: list[str], start: str) -> list[dict[str, Any]]:
    import yfinance as yf

    frame = yf.download(
        symbols,
        start=start,
        interval="1d",
        auto_adjust=True,
        actions=False,
        group_by="ticker",
        progress=False,
        threads=False,
    )
    rows: list[dict[str, Any]] = []
    for symbol in symbols:
        try:
            series = frame[symbol] if len(symbols) > 1 else frame
        except (KeyError, TypeError):
            continue
        for index, values in series.iterrows():
            close = values.get("Close")
            if close is None or str(close) == "nan":
                continue
            when = index.to_pydatetime() if hasattr(index, "to_pydatetime") else index
            if not getattr(when, "tzinfo", None):
                when = when.replace(tzinfo=timezone.utc)
            rows.append({
                "symbol": symbol,
                "bar_time": when,
                "open": float(values.get("Open")) if str(values.get("Open")) != "nan" else None,
                "high": float(values.get("High")) if str(values.get("High")) != "nan" else None,
                "low": float(values.get("Low")) if str(values.get("Low")) != "nan" else None,
                "close": float(close),
                "volume": float(values.get("Volume")) if str(values.get("Volume")) != "nan" else None,
            })
    return rows


def connect_trade_ai_writer():
    """Use the existing DB environment, but do not inherit the read-only session."""
    import os
    import psycopg2

    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5432")),
        dbname=os.getenv("DB_NAME", "trade_ai"),
        user=os.getenv("DB_USER", "trade_ai"),
        password=os.getenv("DB_PASSWORD", ""),
        connect_timeout=10,
    )


def existing_coverage(symbols: list[str]) -> dict[str, int]:
    conn = connect_trade_ai_readonly()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT symbol, count(*) FROM market_ohlcv_bars
            WHERE timeframe='daily' AND symbol = ANY(%s)
            GROUP BY symbol
        """, (symbols,))
        return {str(symbol): int(count) for symbol, count in cur.fetchall()}
    finally:
        conn.close()


def persist_rows(rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    conn = connect_trade_ai_writer()
    inserted = 0
    try:
        cur = conn.cursor()
        for row in rows:
            cur.execute("""
                INSERT INTO market_ohlcv_bars
                    (symbol, timeframe, bar_time, open, high, low, close, volume, source, created_at)
                VALUES (%s, 'daily', %s, %s, %s, %s, %s, %s,
                        'yfinance_adjusted_cio_seasonality', NOW())
                ON CONFLICT (symbol, timeframe, bar_time) DO NOTHING
            """, (
                row["symbol"], row["bar_time"], row.get("open"), row.get("high"),
                row.get("low"), row["close"], row.get("volume"),
            ))
            inserted += cur.rowcount
        conn.commit()
        return inserted
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    parser.add_argument("--start", default="2000-01-01")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    symbols = sorted({value.strip().upper() for value in args.symbols.split(",") if value.strip()})
    before = existing_coverage(symbols)
    rows = fetch_adjusted_daily(symbols, args.start)
    inserted = 0 if args.dry_run else persist_rows(rows)
    print({
        "schema": "CIOSeasonalityHistoryMaterialization@v1",
        "authority": "READ_ONLY_ADVISORY",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "symbols": symbols,
        "fetched_rows": len(rows),
        "inserted_rows": inserted,
        "coverage_before": before,
        "dry_run": bool(args.dry_run),
        "financial_action": False,
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
