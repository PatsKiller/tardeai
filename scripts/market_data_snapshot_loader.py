#!/usr/bin/env python3
"""market_data_snapshot_loader.py — Fetch and cache OHLCV bars for technical analysis.

Uses yfinance as primary source (free, reliable for daily/intraday).
Falls back to Polygon/FMP for extended hours data if available.

Usage:
    .venv/bin/python scripts/market_data_snapshot_loader.py --symbol XMTR --timeframes 1m,5m,daily --days 30 --apply
    .venv/bin/python scripts/market_data_snapshot_loader.py --pending-proposals --timeframes 1m,5m,daily --days 60 --apply
    .venv/bin/python scripts/market_data_snapshot_loader.py --pending-proposals --dry-run
"""
import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from session13_db import get_conn

log = logging.getLogger("ohlcv_loader")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")

TIMEFRAME_MAP = {
    "1m": {"yf_interval": "1m", "yf_period": "5d", "max_days": 7},
    "5m": {"yf_interval": "5m", "yf_period": "5d", "max_days": 60},
    "15m": {"yf_interval": "15m", "yf_period": "5d", "max_days": 60},
    "daily": {"yf_interval": "1d", "yf_period": None, "max_days": 365},
}


def fetch_yfinance_bars(symbol: str, timeframe: str, days: int) -> list:
    """Fetch OHLCV bars via yfinance."""
    import yfinance as yf
    cfg = TIMEFRAME_MAP.get(timeframe)
    if not cfg:
        log.warning(f"Unknown timeframe: {timeframe}")
        return []

    try:
        ticker = yf.Ticker(symbol)
        if timeframe == "daily":
            end = datetime.now()
            start = end - timedelta(days=days)
            df = ticker.history(start=start.strftime("%Y-%m-%d"),
                                end=end.strftime("%Y-%m-%d"),
                                interval="1d")
        else:
            # Intraday: yfinance limits lookback
            actual_days = min(days, cfg["max_days"])
            df = ticker.history(period=f"{actual_days}d", interval=cfg["yf_interval"])

        if df is None or df.empty:
            return []

        bars = []
        for idx, row in df.iterrows():
            bar_time = idx.to_pydatetime()
            if bar_time.tzinfo is None:
                bar_time = bar_time.replace(tzinfo=timezone.utc)
            bars.append({
                "symbol": symbol,
                "timeframe": timeframe,
                "bar_time": bar_time,
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"]),
                "volume": float(row.get("Volume", 0)),
                "source": "yfinance",
            })
        return bars
    except Exception as e:
        log.warning(f"yfinance fetch failed for {symbol} {timeframe}: {e}")
        return []


def fetch_polygon_bars(symbol: str, timeframe: str, days: int) -> list:
    """Fetch OHLCV bars via Polygon (supports extended hours)."""
    api_key = os.getenv("POLYGON_API_KEY", "")
    if not api_key:
        return []

    try:
        import requests
        multiplier = {"1m": 1, "5m": 5, "15m": 15, "daily": 1}.get(timeframe, 1)
        span = "day" if timeframe == "daily" else "minute"
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

        url = (f"https://api.polygon.io/v2/aggs/ticker/{symbol}/range/"
               f"{multiplier}/{span}/{start_date}/{end_date}"
               f"?adjusted=true&sort=asc&limit=5000&apiKey={api_key}")

        resp = requests.get(url, timeout=15)
        if resp.status_code != 200:
            return []

        data = resp.json()
        results = data.get("results", [])
        bars = []
        for r in results:
            bar_time = datetime.fromtimestamp(r["t"] / 1000, tz=timezone.utc)
            bars.append({
                "symbol": symbol,
                "timeframe": timeframe,
                "bar_time": bar_time,
                "open": float(r.get("o", 0)),
                "high": float(r.get("h", 0)),
                "low": float(r.get("l", 0)),
                "close": float(r.get("c", 0)),
                "volume": float(r.get("v", 0)),
                "source": "polygon",
            })
        return bars
    except Exception as e:
        log.warning(f"Polygon fetch failed for {symbol} {timeframe}: {e}")
        return []


def store_bars(conn, bars: list) -> int:
    """Upsert bars into market_ohlcv_bars. Returns count stored."""
    if not bars:
        return 0
    cur = conn.cursor()
    stored = 0
    for b in bars:
        try:
            cur.execute("""
                INSERT INTO market_ohlcv_bars (symbol, timeframe, bar_time, open, high, low, close, volume, source)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (symbol, timeframe, bar_time)
                DO UPDATE SET open=EXCLUDED.open, high=EXCLUDED.high, low=EXCLUDED.low,
                              close=EXCLUDED.close, volume=EXCLUDED.volume, source=EXCLUDED.source
            """, [b["symbol"], b["timeframe"], b["bar_time"],
                  b["open"], b["high"], b["low"], b["close"], b["volume"], b["source"]])
            stored += 1
        except Exception as e:
            log.warning(f"Failed to store bar {b['symbol']} {b['timeframe']} {b['bar_time']}: {e}")
            conn.rollback()
    conn.commit()
    return stored


def load_symbol(conn, symbol: str, timeframes: list, days: int, apply: bool = False) -> dict:
    """Load OHLCV data for a symbol across timeframes."""
    result = {"symbol": symbol, "timeframes": {}}

    for tf in timeframes:
        # Try yfinance first
        bars = fetch_yfinance_bars(symbol, tf, days)
        source = "yfinance"

        # Fall back to Polygon for intraday if yfinance returns nothing
        if not bars and tf != "daily":
            bars = fetch_polygon_bars(symbol, tf, days)
            source = "polygon" if bars else "none"

        # For daily, try Polygon as fallback too
        if not bars and tf == "daily":
            bars = fetch_polygon_bars(symbol, tf, days)
            source = "polygon" if bars else "none"

        stored = 0
        if bars and apply:
            stored = store_bars(conn, bars)

        status = "LOADED" if bars else "UNAVAILABLE"
        if tf in ("1m", "5m", "15m") and not bars:
            status = "INTRADAY_UNAVAILABLE"

        result["timeframes"][tf] = {
            "bars_fetched": len(bars),
            "bars_stored": stored,
            "source": source,
            "status": status,
            "date_range": {
                "first": str(bars[0]["bar_time"]) if bars else None,
                "last": str(bars[-1]["bar_time"]) if bars else None,
            }
        }
        log.info(f"  {symbol} {tf}: {len(bars)} bars from {source} ({status})")

    # Overall OHLCV status
    daily_status = result["timeframes"].get("daily", {}).get("status", "UNAVAILABLE")
    intraday_statuses = [v["status"] for k, v in result["timeframes"].items() if k != "daily"]
    has_intraday = any(s == "LOADED" for s in intraday_statuses)

    if daily_status == "LOADED" and has_intraday:
        result["ohlcv_data_status"] = "FULL"
    elif daily_status == "LOADED":
        result["ohlcv_data_status"] = "DAILY_ONLY"
    elif has_intraday:
        result["ohlcv_data_status"] = "INTRADAY_ONLY"
    else:
        result["ohlcv_data_status"] = "UNAVAILABLE"

    return result


def get_pending_symbols(conn) -> list:
    """Get symbols from pending proposals."""
    cur = conn.cursor()
    cur.execute("""
        SELECT DISTINCT symbol FROM paper_trade_proposals
        WHERE status = 'PENDING' ORDER BY symbol
    """)
    return [r[0] for r in cur.fetchall()]


def main():
    parser = argparse.ArgumentParser(description="OHLCV data loader for technical analysis")
    parser.add_argument("--symbol", type=str, help="Single symbol to load")
    parser.add_argument("--pending-proposals", action="store_true", help="Load data for all pending proposals")
    parser.add_argument("--timeframes", type=str, default="daily,5m,1m",
                        help="Comma-separated timeframes: 1m,5m,15m,daily")
    parser.add_argument("--days", type=int, default=60, help="Days of history to fetch")
    parser.add_argument("--apply", action="store_true", help="Write to database")
    parser.add_argument("--dry-run", action="store_true", help="Display only, do not write")
    args = parser.parse_args()

    timeframes = [t.strip() for t in args.timeframes.split(",")]

    conn = get_conn()
    try:
        if args.pending_proposals:
            symbols = get_pending_symbols(conn)
            log.info(f"Loading OHLCV for {len(symbols)} pending proposal symbols: {symbols}")
        elif args.symbol:
            symbols = [args.symbol.upper()]
        else:
            print("Usage: --symbol TICK or --pending-proposals")
            return

        results = []
        for sym in symbols:
            r = load_symbol(conn, sym, timeframes, args.days, apply=args.apply)
            results.append(r)

        print(json.dumps({"symbols_processed": len(results), "results": results}, indent=2, default=str))

        if args.dry_run:
            print("\n(dry-run — no DB writes performed)")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
