#!/usr/bin/env python3
"""market_data_snapshot_loader.py — Fetch and cache OHLCV bars for technical analysis.

DAILY is a price series: it comes from Alpaca, the provider ``config/data_source_authority.json`` grants
``bars`` to (:func:`fetch_alpaca_daily_bars`). It never comes from yfinance — the operator price rule of
2026-11-07 and SPEC_MARKET_EVENT_REENTRY_20261107 §2 ("never yfinance") — and Polygon was retired
2026-09-13, so no retired stub is kept here. Intraday bars still use yfinance (display-only technicals,
never a price source).

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
from datetime import datetime, time, timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
DAILY_SOURCE = "alpaca"  # the granted `bars` supply; never yfinance (see the module docstring)

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
}  # intraday only: 'daily' is Alpaca's (fetch_alpaca_daily_bars), so it has no yfinance window here

SIP_DELAY_CONFIG = PROJECT_ROOT / "config" / "market_quotes_extended.json"


def _sip_delay_minutes(default: float = 16.0) -> float:
    """The free plan's SIP delay (config/market_quotes_extended.json ``sip_delay_minutes``, measured 2026-10-31).

    Measure again 2026-11-07: a request whose ``end`` is inside the delay is refused with HTTP 403
    "subscription does not permit querying recent SIP data" — the whole window fails, not just the last bar.
    """
    try:
        cfg = json.loads(SIP_DELAY_CONFIG.read_text(encoding="utf-8"))
        return float(cfg.get("sip_delay_minutes") or default)
    except (OSError, ValueError, TypeError):
        return default


def fetch_yfinance_bars(symbol: str, timeframe: str, days: int) -> list:
    """Intraday OHLCV bars via yfinance (display-only technicals).

    DAILY is refused here on purpose. Until 2026-11-07 this function served daily bars, and every daily row in
    ``market_ohlcv_bars`` still carries ``source='yfinance'`` because of it: SPY stopped on 2026-10-09 the last
    time an on-demand lookup ran, QQQ and SMH never had one. Daily bars are a price series; the operator price
    rule (2026-11-07) and the market-event spec forbid yfinance for it. Use :func:`fetch_alpaca_daily_bars`.
    """
    if timeframe == "daily":
        log.warning(f"{symbol}: daily bars are not a yfinance series — use fetch_alpaca_daily_bars")
        return []
    import yfinance as yf
    cfg = TIMEFRAME_MAP.get(timeframe)
    if not cfg:
        log.warning(f"Unknown timeframe: {timeframe}")
        return []

    try:
        ticker = yf.Ticker(symbol)
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


def fetch_alpaca_daily_bars(symbol: str, days: int) -> list:
    """Daily OHLCV through Alpaca — the provider ``config/data_source_authority.json`` grants ``bars`` to.

    ``bar_time`` is midnight America/New_York of the SESSION, not the UTC instant Alpaca stamps (00:00 ET as
    04:00Z/05:00Z). That is the key the 2025-2026 yfinance rows already carry, so a refresh UPDATES the stored
    session (``ON CONFLICT (symbol, timeframe, bar_time)`` in :func:`store_bars`) instead of inserting a second
    row for the same day — a UTC-sliced key would silently double every session.

    A symbol Alpaca knows nothing about is ``[]``; an error is ``[]`` and logged (the lane names the symbol
    rather than storing a hole). Read-only market data: no account, no order route.

    The window ENDS ``sip_delay_minutes`` before now, not at now: the free plan refuses a request that reaches
    into its SIP delay with HTTP 403 for the whole window (see :func:`_sip_delay_minutes`).
    """
    sym = str(symbol or "").upper().strip()
    if not sym:
        return []
    end = datetime.now(timezone.utc) - timedelta(minutes=_sip_delay_minutes())
    start = end - timedelta(days=max(1, int(days)))
    try:
        import ohlc_charts as oc
        raw, err = oc.alpaca_daily_bars(sym, start.isoformat(), end.isoformat())
    except Exception as e:  # noqa: BLE001 - reported to the lane as an empty symbol
        log.warning(f"alpaca daily-bar fetch failed for {sym}: {type(e).__name__}")
        return []
    if err:
        log.warning(f"alpaca daily bars {sym}: {err}")
    out = []
    for b in raw or []:
        try:
            ts = datetime.fromisoformat(str(b["t"]).replace("Z", "+00:00"))
            session = ts.astimezone(ET).date()
            out.append({
                "symbol": sym,
                "timeframe": "daily",
                "bar_time": datetime.combine(session, time(0, 0), tzinfo=ET),
                "open": float(b["o"]),
                "high": float(b["h"]),
                "low": float(b["l"]),
                "close": float(b["c"]),
                "volume": float(b.get("v") or 0),
                "source": DAILY_SOURCE,
            })
        except (KeyError, TypeError, ValueError) as e:
            log.warning(f"alpaca daily bar {sym} unusable ({type(e).__name__}): {b!r}")
    return out


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
        if tf == "daily":
            # Daily is a price series: the granted Alpaca `bars` supply, never yfinance.
            bars, source = fetch_alpaca_daily_bars(symbol, days), DAILY_SOURCE
        else:
            bars, source = fetch_yfinance_bars(symbol, tf, days), "yfinance"
            if not bars:
                source = "none"

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
