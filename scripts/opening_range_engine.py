#!/usr/bin/env python3
"""opening_range_engine.py — Compute opening range and premarket levels from intraday bars.

Uses 1m/5m bars from market_ohlcv_bars to compute ORB and premarket levels.

Usage:
    .venv/bin/python scripts/opening_range_engine.py --symbol XMTR --date today --dry-run
    .venv/bin/python scripts/opening_range_engine.py --pending-proposals --apply
"""
import argparse
import json
import logging
import sys
from datetime import datetime, timezone, timedelta, time as dt_time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from session13_db import get_conn

log = logging.getLogger("opening_range")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")

# Market hours in UTC (ET + 4h during EDT)
PREMARKET_START_UTC = dt_time(8, 0)   # 4:00 AM ET
MARKET_OPEN_UTC = dt_time(13, 30)     # 9:30 AM ET
MARKET_CLOSE_UTC = dt_time(20, 0)     # 4:00 PM ET

ORB_WINDOWS = [5, 15, 30]


def get_intraday_bars(conn, symbol: str, date_str: str = "today") -> list:
    """Get intraday bars (1m preferred, 5m fallback) for a date."""
    if date_str == "today":
        target_date = datetime.now(timezone.utc).date()
    else:
        target_date = datetime.strptime(date_str, "%Y-%m-%d").date()

    cur = conn.cursor()
    # Try 1m first
    cur.execute("""
        SELECT bar_time, open, high, low, close, volume, timeframe
        FROM market_ohlcv_bars
        WHERE symbol = %s AND timeframe = '1m'
        AND bar_time::date = %s
        ORDER BY bar_time ASC
    """, [symbol, target_date])
    rows = cur.fetchall()

    if not rows:
        # Fallback to 5m
        cur.execute("""
            SELECT bar_time, open, high, low, close, volume, timeframe
            FROM market_ohlcv_bars
            WHERE symbol = %s AND timeframe = '5m'
            AND bar_time::date = %s
            ORDER BY bar_time ASC
        """, [symbol, target_date])
        rows = cur.fetchall()

    cols = ["bar_time", "open", "high", "low", "close", "volume", "timeframe"]
    return [dict(zip(cols, r)) for r in rows]


def compute_premarket_levels(bars: list) -> dict:
    """Compute premarket high/low/volume from bars before market open."""
    premarket_bars = []
    for b in bars:
        bt = b["bar_time"]
        if hasattr(bt, "time"):
            t = bt.time()
        else:
            t = datetime.fromisoformat(str(bt)).time()
        if PREMARKET_START_UTC <= t < MARKET_OPEN_UTC:
            premarket_bars.append(b)

    if not premarket_bars:
        return {
            "premarket_high": None,
            "premarket_low": None,
            "premarket_volume": None,
            "premarket_status": "NO_INTRADAY_DATA",
        }

    pm_high = max(float(b["high"]) for b in premarket_bars)
    pm_low = min(float(b["low"]) for b in premarket_bars)
    pm_vol = sum(float(b.get("volume", 0)) for b in premarket_bars)

    return {
        "premarket_high": round(pm_high, 2),
        "premarket_low": round(pm_low, 2),
        "premarket_volume": int(pm_vol),
        "premarket_status": "AVAILABLE",
        "premarket_bars_count": len(premarket_bars),
    }


def compute_opening_range(bars: list, window_minutes: int) -> dict:
    """Compute opening range high/low for a given window."""
    orb_bars = []
    cutoff = None
    for b in bars:
        bt = b["bar_time"]
        if hasattr(bt, "time"):
            t = bt.time()
        else:
            t = datetime.fromisoformat(str(bt)).time()

        if t >= MARKET_OPEN_UTC:
            if cutoff is None:
                cutoff_dt = datetime.combine(datetime.today(), MARKET_OPEN_UTC).replace(tzinfo=timezone.utc)
                cutoff = (cutoff_dt + timedelta(minutes=window_minutes)).time()
            if t < cutoff:
                orb_bars.append(b)

    if not orb_bars:
        return {f"orb_{window_minutes}_high": None, f"orb_{window_minutes}_low": None}

    orb_high = max(float(b["high"]) for b in orb_bars)
    orb_low = min(float(b["low"]) for b in orb_bars)

    return {
        f"orb_{window_minutes}_high": round(orb_high, 2),
        f"orb_{window_minutes}_low": round(orb_low, 2),
        f"orb_{window_minutes}_bars": len(orb_bars),
    }


def classify_orb_status(orb_data: dict, current_price: float) -> str:
    """Classify current price relative to opening range."""
    orb_15_high = orb_data.get("orb_15_high")
    orb_15_low = orb_data.get("orb_15_low")

    if orb_15_high is None or orb_15_low is None:
        # Try 5-minute ORB
        orb_5_high = orb_data.get("orb_5_high")
        orb_5_low = orb_data.get("orb_5_low")
        if orb_5_high is None:
            return "NO_INTRADAY_DATA"
        orb_high, orb_low = orb_5_high, orb_5_low
    else:
        orb_high, orb_low = orb_15_high, orb_15_low

    if current_price > orb_high * 1.002:
        return "ORB_BREAKOUT_CONFIRMED"
    elif current_price < orb_low * 0.998:
        return "ORB_BREAKOUT_FAILED"
    else:
        return "INSIDE_OPENING_RANGE"


def classify_premarket_status(premarket_data: dict, current_price: float) -> str:
    """Classify current price relative to premarket levels."""
    pm_high = premarket_data.get("premarket_high")
    if pm_high is None:
        return "NO_INTRADAY_DATA"
    pm_low = premarket_data.get("premarket_low")

    if current_price > pm_high * 1.002:
        return "PREMARKET_HIGH_RECLAIM"
    elif current_price < pm_low * 0.998:
        return "PREMARKET_HIGH_REJECTED"
    else:
        return "INSIDE_PREMARKET_RANGE"


def process_symbol(conn, symbol: str, date_str: str = "today",
                   current_price: float = None, apply: bool = False) -> dict:
    """Run full ORB/premarket analysis for a symbol."""
    bars = get_intraday_bars(conn, symbol, date_str)

    now_utc = datetime.now(timezone.utc)
    is_market_open = (now_utc.weekday() < 5 and
                      MARKET_OPEN_UTC <= now_utc.time() <= MARKET_CLOSE_UTC)

    if not bars:
        result = {
            "symbol": symbol,
            "opening_range_status": "NO_INTRADAY_DATA",
            "premarket_status": "NO_INTRADAY_DATA",
            "market_open": is_market_open,
            "intraday_data_source": "none",
            "bars_available": 0,
        }
        if not is_market_open:
            result["opening_range_status"] = "MARKET_NOT_OPEN"
        if apply:
            _write_orb_to_snapshot(conn, symbol, result)
        return result

    # Get current price from latest bar if not provided
    if current_price is None:
        current_price = float(bars[-1]["close"])

    # Compute levels
    premarket = compute_premarket_levels(bars)
    orb_data = {}
    for window in ORB_WINDOWS:
        orb_data.update(compute_opening_range(bars, window))

    orb_status = classify_orb_status(orb_data, current_price)
    pm_status = classify_premarket_status(premarket, current_price)

    # Price vs ORB/premarket
    price_vs_orb = None
    if orb_data.get("orb_15_high") and orb_data.get("orb_15_low"):
        orb_mid = (orb_data["orb_15_high"] + orb_data["orb_15_low"]) / 2
        price_vs_orb = round((current_price - orb_mid) / orb_mid * 100, 2) if orb_mid > 0 else None

    price_vs_premarket = None
    if premarket.get("premarket_high"):
        price_vs_premarket = round((current_price - premarket["premarket_high"]) / premarket["premarket_high"] * 100, 2)

    result = {
        "symbol": symbol,
        "current_price": current_price,
        "market_open": is_market_open,
        "intraday_data_source": bars[0].get("timeframe", "unknown"),
        "bars_available": len(bars),
        **premarket,
        **orb_data,
        "current_price_vs_orb": price_vs_orb,
        "current_price_vs_premarket": price_vs_premarket,
        "opening_range_status": orb_status,
        "premarket_status": pm_status,
    }

    if apply:
        _write_orb_to_snapshot(conn, symbol, result)

    return result


def _write_orb_to_snapshot(conn, symbol: str, orb_result: dict):
    """Update proposal_technical_snapshots with ORB data."""
    cur = conn.cursor()
    try:
        cur.execute("""
            UPDATE proposal_technical_snapshots
            SET opening_range_high = %s, opening_range_low = %s,
                premarket_high = %s, premarket_low = %s,
                opening_range_minutes = 15,
                opening_range_status = %s, premarket_status = %s,
                intraday_data_source = %s, ohlcv_data_status = %s
            WHERE symbol = %s
            AND id = (SELECT id FROM proposal_technical_snapshots WHERE symbol = %s ORDER BY computed_at DESC LIMIT 1)
        """, [
            orb_result.get("orb_15_high"), orb_result.get("orb_15_low"),
            orb_result.get("premarket_high"), orb_result.get("premarket_low"),
            orb_result.get("opening_range_status"), orb_result.get("premarket_status"),
            orb_result.get("intraday_data_source"),
            "FULL" if orb_result.get("bars_available", 0) > 0 else "INTRADAY_UNAVAILABLE",
            symbol, symbol,
        ])
        conn.commit()
        log.info(f"  ORB data written for {symbol}")
    except Exception as e:
        log.warning(f"  Failed to write ORB for {symbol}: {e}")
        conn.rollback()


def main():
    parser = argparse.ArgumentParser(description="Opening range / premarket engine")
    parser.add_argument("--symbol", type=str)
    parser.add_argument("--pending-proposals", action="store_true")
    parser.add_argument("--date", type=str, default="today")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    conn = get_conn()
    try:
        if args.pending_proposals:
            cur = conn.cursor()
            cur.execute("SELECT DISTINCT symbol FROM paper_trade_proposals WHERE status='PENDING'")
            symbols = [r[0] for r in cur.fetchall()]
        elif args.symbol:
            symbols = [args.symbol.upper()]
        else:
            print("Usage: --symbol TICK or --pending-proposals")
            return

        results = []
        for sym in symbols:
            r = process_symbol(conn, sym, args.date, apply=args.apply)
            log.info(f"  {sym}: ORB={r.get('opening_range_status')} PM={r.get('premarket_status')}")
            results.append(r)

        print(json.dumps({"processed": len(results), "results": results}, indent=2, default=str))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
