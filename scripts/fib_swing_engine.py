#!/usr/bin/env python3
"""fib_swing_engine.py — Compute Fibonacci retracement/extension levels from real swing data.

Uses daily OHLCV bars from market_ohlcv_bars to find swing high/low,
then computes actionable Fib levels.

Usage:
    .venv/bin/python scripts/fib_swing_engine.py --symbol XMTR --days 60 --dry-run
    .venv/bin/python scripts/fib_swing_engine.py --pending-proposals --apply
"""
import argparse
import json
import logging
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from session13_db import get_conn

log = logging.getLogger("fib_swing")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")

FIB_LEVELS = [0.236, 0.382, 0.500, 0.618, 0.786]
FIB_EXTENSIONS = [1.272, 1.618]
MIN_SWING_RANGE_PCT = 8.0


def get_daily_bars(conn, symbol: str, days: int = 60) -> list:
    """Get daily OHLCV bars from cache."""
    cur = conn.cursor()
    cur.execute("""
        SELECT bar_time, open, high, low, close, volume
        FROM market_ohlcv_bars
        WHERE symbol = %s AND timeframe = 'daily'
        AND bar_time >= NOW() - INTERVAL '%s days'
        ORDER BY bar_time ASC
    """, [symbol, days])
    cols = ["bar_time", "open", "high", "low", "close", "volume"]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def compute_atr(bars: list, period: int = 14) -> float:
    """Compute ATR from bars."""
    if len(bars) < period + 1:
        return 0
    trs = []
    for i in range(1, len(bars)):
        h = float(bars[i]["high"])
        l = float(bars[i]["low"])
        pc = float(bars[i - 1]["close"])
        tr = max(h - l, abs(h - pc), abs(l - pc))
        trs.append(tr)
    if len(trs) < period:
        return sum(trs) / len(trs) if trs else 0
    # Simple ATR: average of last `period` true ranges
    return sum(trs[-period:]) / period


def find_swing_points(bars: list, atr: float) -> dict:
    """Find swing high and swing low from daily bars.

    For bullish setups: swing_low is the lowest low before the recent impulse,
    swing_high is the highest high after swing_low.
    """
    if len(bars) < 10:
        return {"available": False, "summary": "Insufficient daily bars for swing detection"}

    highs = [float(b["high"]) for b in bars]
    lows = [float(b["low"]) for b in bars]
    closes = [float(b["close"]) for b in bars]

    # Find the overall low and high
    overall_low = min(lows)
    overall_low_idx = lows.index(overall_low)
    overall_high = max(highs)
    overall_high_idx = highs.index(overall_high)

    # Determine trend direction: if high came after low, bullish impulse
    if overall_high_idx > overall_low_idx:
        swing_low = overall_low
        swing_low_idx = overall_low_idx
        # Swing high is the max high after the swing low
        swing_high = max(highs[swing_low_idx:])
        swing_high_idx = swing_low_idx + highs[swing_low_idx:].index(swing_high)
        trend = "bullish_impulse"
    else:
        # Bearish: high came before low
        swing_high = overall_high
        swing_high_idx = overall_high_idx
        swing_low = min(lows[swing_high_idx:])
        swing_low_idx = swing_high_idx + lows[swing_high_idx:].index(swing_low)
        trend = "bearish_impulse"

    swing_range = swing_high - swing_low
    swing_range_pct = (swing_range / swing_low * 100) if swing_low > 0 else 0
    min_range = max(2 * atr, swing_low * MIN_SWING_RANGE_PCT / 100) if atr > 0 else swing_low * MIN_SWING_RANGE_PCT / 100

    if swing_range < min_range and swing_range_pct < MIN_SWING_RANGE_PCT:
        return {
            "available": False,
            "summary": f"Swing range {swing_range_pct:.1f}% too small (min {MIN_SWING_RANGE_PCT}% or 2x ATR)",
            "swing_high": round(swing_high, 2),
            "swing_low": round(swing_low, 2),
            "swing_range_pct": round(swing_range_pct, 1),
        }

    return {
        "available": True,
        "trend": trend,
        "swing_high": round(swing_high, 2),
        "swing_low": round(swing_low, 2),
        "swing_high_date": str(bars[swing_high_idx]["bar_time"]),
        "swing_low_date": str(bars[swing_low_idx]["bar_time"]),
        "swing_range": round(swing_range, 2),
        "swing_range_pct": round(swing_range_pct, 1),
    }


def compute_fib_levels(swing_data: dict, current_price: float) -> dict:
    """Compute Fibonacci retracement and extension levels."""
    if not swing_data.get("available"):
        return swing_data

    sh = swing_data["swing_high"]
    sl = swing_data["swing_low"]
    swing_range = sh - sl

    levels = {}
    # Retracement levels (measured from high)
    for fib in FIB_LEVELS:
        key = f"fib_{str(fib).replace('0.', '')}"
        levels[key] = round(sh - swing_range * fib, 2)

    # Extension levels (measured from low)
    for ext in FIB_EXTENSIONS:
        key = f"ext_{str(ext).replace('.', '')}"
        levels[key] = round(sl + swing_range * ext, 2)

    # Find nearest level to current price
    nearest_level = None
    nearest_distance = float("inf")
    nearest_key = None
    for key, val in levels.items():
        dist = abs(current_price - val)
        if dist < nearest_distance:
            nearest_distance = dist
            nearest_level = val
            nearest_key = key

    distance_pct = (nearest_distance / current_price * 100) if current_price > 0 else 0

    # Interpretation
    if nearest_key and "fib_" in nearest_key:
        fib_val = nearest_key.replace("fib_", "")
        if distance_pct < 2:
            interpretation = f"Entry is near {fib_val[0]}.{fib_val[1:]}% retracement support."
        elif current_price > sh:
            interpretation = f"Price above swing high — possible extension territory."
        else:
            interpretation = f"Price {distance_pct:.1f}% from nearest Fib {nearest_key}."
    elif nearest_key:
        interpretation = f"Price near Fib extension {nearest_key} — potential target zone."
    else:
        interpretation = "Fib context computed but no clear proximity."

    result = {
        **swing_data,
        "levels": levels,
        "nearest": nearest_key,
        "nearest_level": nearest_level,
        "distance_pct": round(distance_pct, 2),
        "interpretation": interpretation,
        "current_price": current_price,
    }
    return result


def process_symbol(conn, symbol: str, days: int = 60, current_price: float = None, apply: bool = False) -> dict:
    """Run full Fib analysis for a symbol."""
    bars = get_daily_bars(conn, symbol, days)
    if not bars:
        return {
            "symbol": symbol,
            "available": False,
            "summary": f"No daily bars in market_ohlcv_bars for {symbol}",
        }

    atr = compute_atr(bars)
    if current_price is None:
        current_price = float(bars[-1]["close"])

    swing_data = find_swing_points(bars, atr)
    result = compute_fib_levels(swing_data, current_price)
    result["symbol"] = symbol
    result["bars_used"] = len(bars)
    result["atr"] = round(atr, 4) if atr else None

    if apply and result.get("available"):
        _write_fib_to_snapshot(conn, symbol, result)

    return result


def _write_fib_to_snapshot(conn, symbol: str, fib_result: dict):
    """Update proposal_technical_snapshots with Fib data."""
    cur = conn.cursor()
    levels = fib_result.get("levels", {})
    try:
        cur.execute("""
            UPDATE proposal_technical_snapshots
            SET swing_high = %s, swing_low = %s,
                swing_high_date = %s, swing_low_date = %s,
                fib_236 = %s, fib_382 = %s, fib_500 = %s,
                fib_618 = %s, fib_786 = %s,
                fib_1272 = %s, fib_1618 = %s,
                nearest_fib_level = %s, nearest_fib_distance_pct = %s,
                fib_context = %s
            WHERE symbol = %s
            AND id = (SELECT id FROM proposal_technical_snapshots WHERE symbol = %s ORDER BY computed_at DESC LIMIT 1)
        """, [
            fib_result.get("swing_high"), fib_result.get("swing_low"),
            fib_result.get("swing_high_date"), fib_result.get("swing_low_date"),
            levels.get("fib_236"), levels.get("fib_382"), levels.get("fib_500"),
            levels.get("fib_618"), levels.get("fib_786"),
            levels.get("ext_1272"), levels.get("ext_1618"),
            fib_result.get("nearest"), fib_result.get("distance_pct"),
            json.dumps(fib_result, default=str),
            symbol, symbol,
        ])
        conn.commit()
        log.info(f"  Fib data written to snapshot for {symbol}")
    except Exception as e:
        log.warning(f"  Failed to write Fib for {symbol}: {e}")
        conn.rollback()


def main():
    parser = argparse.ArgumentParser(description="Fibonacci swing engine")
    parser.add_argument("--symbol", type=str)
    parser.add_argument("--pending-proposals", action="store_true")
    parser.add_argument("--days", type=int, default=60)
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
            r = process_symbol(conn, sym, args.days, apply=args.apply)
            status = "available" if r.get("available") else "unavailable"
            log.info(f"  {sym}: {status} — {r.get('summary', r.get('interpretation', ''))}")
            results.append(r)

        print(json.dumps({"processed": len(results), "results": results}, indent=2, default=str))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
