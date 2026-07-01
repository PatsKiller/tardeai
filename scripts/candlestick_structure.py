#!/usr/bin/env python3
"""candlestick_structure.py — price-structure-aware stop level + `structure_type` tag.

Implements the candlestick/structure enhancement of MOMENTUM_SCALP_STOP_AND_TRAIL_POLICY §3 Layer-1:
place the initial stop just beyond the most recent SIGNIFICANT structure — swing low (longs) / swing
high (shorts), the low/high of a bullish/bearish engulfing candle, an inside-bar mother low/high, or the
previous-bar low/high — plus an ATR buffer, and pick whichever is TIGHTER between structure and pure ATR.
Fully SYMMETRIC for longs and shorts. Advisory/read-only — computes + tags, never places an order.

Tags produced (policy §5): `structure_type` ∈ {swing_low|swing_high, engulfing_low|engulfing_high,
inside_bar_low|inside_bar_high, previous_bar_low|previous_bar_high, atr_only}.

  python3 scripts/candlestick_structure.py --symbol RKLB --direction long [--entry 104.50]
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


# ── candlestick primitives (symmetric) ───────────────────────────────────────
def _is_bullish(b):  return float(b["close"]) > float(b["open"])
def _is_bearish(b):  return float(b["close"]) < float(b["open"])


def _bullish_engulfing(prev, cur):
    """cur is a bullish candle whose real body engulfs prev's bearish body."""
    return (_is_bearish(prev) and _is_bullish(cur)
            and float(cur["open"]) <= float(prev["close"]) and float(cur["close"]) >= float(prev["open"]))


def _bearish_engulfing(prev, cur):
    return (_is_bullish(prev) and _is_bearish(cur)
            and float(cur["open"]) >= float(prev["close"]) and float(cur["close"]) <= float(prev["open"]))


def _inside_bar(prev, cur):
    return float(cur["high"]) <= float(prev["high"]) and float(cur["low"]) >= float(prev["low"])


def _cfg_layer1():
    """ATR multiplier + buffer from the strategy YAML (no hardcoded values)."""
    try:
        import yaml
        c = yaml.safe_load((PROJECT_ROOT / "config/strategies/momentum_scalp.yaml").read_text())
        l1 = (((c.get("exit_rules") or {}).get("layered_stop") or {}).get("layer1_initial") or {})
        l4 = (((c.get("exit_rules") or {}).get("layered_stop") or {}).get("layer4_dynamic") or {})
        return {"atr_mult": float(l1.get("max_atr_mult", 1.5)),
                "buffer_atr": float(l1.get("structure_buffer_atr", l4.get("structure_buffer_atr", 0.15)))}
    except Exception:
        return {"atr_mult": 1.5, "buffer_atr": 0.15}


def _load_bars(symbol, timeframe, limit):
    """Last `limit` OHLC bars for symbol/timeframe from market_ohlcv_bars, oldest→newest. Rollback-safe.
    Uses a direct LIMIT query (not fib's NOW()-Nd INTERVAL filter, which drops stale/backtest data)."""
    from db_adapter import _execute
    rows = _execute("""SELECT bar_time, open, high, low, close, volume FROM market_ohlcv_bars
                       WHERE symbol=%s AND timeframe=%s ORDER BY bar_time DESC LIMIT %s""",
                    (symbol, timeframe, int(limit)), fetch="all") or []
    return list(reversed([{"bar_time": r["bar_time"], "open": r["open"], "high": r["high"],
                           "low": r["low"], "close": r["close"], "volume": r["volume"]} for r in rows]))


def analyze(symbol, *, direction="long", entry_price=None, timeframe="auto", atr_mult=None, buffer_atr=None):
    """Return the structure-aware stop + `structure_type` for a long or short. Read-only.

    timeframe: '5m' | 'daily' | '1m' | 'auto' (tries 5m→daily→1m — momentum scalps live on intraday
    structure, so 5m is preferred; daily is the swing/position fallback).

    { available, symbol, direction, timeframe, entry, atr, structure_type, structure_level, structure_stop,
      atr_stop, recommended_stop, recommended_source, note }"""
    import fib_swing_engine as fib
    cfg = _cfg_layer1()
    am = float(atr_mult if atr_mult is not None else cfg["atr_mult"])
    bf = float(buffer_atr if buffer_atr is not None else cfg["buffer_atr"])
    direction = "short" if str(direction).lower().startswith("s") else "long"

    order = [timeframe] if timeframe != "auto" else ["5m", "daily", "1m"]
    bars, tf_used = [], None
    for tf in order:
        lim = 120 if tf in ("5m", "1m") else 60
        try:
            b = _load_bars(symbol, tf, lim)
        except Exception as e:
            return {"available": False, "symbol": symbol, "error": f"bars_unavailable:{str(e)[:80]}"}
        if b and len(b) >= 10:
            bars, tf_used = b, tf
            break
    if not bars:
        return {"available": False, "symbol": symbol,
                "note": f"no OHLC bars (tried {order}) — structure tagging needs the market_ohlcv_bars feed"}

    atr = fib.compute_atr(bars, 14)
    entry = float(entry_price) if entry_price is not None else float(bars[-1]["close"])
    if not atr or atr <= 0:
        return {"available": False, "symbol": symbol, "entry": entry, "note": "ATR unavailable"}

    swings = fib.find_swing_points(bars, atr) or {}
    prev, cur = bars[-2], bars[-1]

    # Candidate structure levels. LONG → protective lows BELOW entry (pick the highest = tightest).
    # SHORT → protective highs ABOVE entry (pick the lowest = tightest). Symmetric throughout.
    cands = []  # (structure_type, level)
    if direction == "long":
        if swings.get("swing_low") is not None:
            cands.append(("swing_low", float(swings["swing_low"])))
        if _bullish_engulfing(prev, cur):
            cands.append(("engulfing_low", min(float(cur["low"]), float(prev["low"]))))
        if _inside_bar(prev, cur):
            cands.append(("inside_bar_low", float(prev["low"])))     # mother-bar low
        cands.append(("previous_bar_low", float(cur["low"])))
        valid = [(t, lv) for (t, lv) in cands if lv < entry]         # must be a real stop (below price)
        struct_type, level = (max(valid, key=lambda x: x[1]) if valid else (None, None))  # highest = tightest
        struct_stop = round(level - bf * atr, 2) if level is not None else None
        atr_stop = round(entry - am * atr, 2)
        # "whichever is tighter" (§3 L1): tighter long stop = the HIGHER price.
        if struct_stop is not None and struct_stop > atr_stop:
            rec, src, stype = struct_stop, "structure", struct_type
        else:
            rec, src, stype = atr_stop, "atr", (struct_type or "atr_only")
    else:  # short
        if swings.get("swing_high") is not None:
            cands.append(("swing_high", float(swings["swing_high"])))
        if _bearish_engulfing(prev, cur):
            cands.append(("engulfing_high", max(float(cur["high"]), float(prev["high"]))))
        if _inside_bar(prev, cur):
            cands.append(("inside_bar_high", float(prev["high"])))
        cands.append(("previous_bar_high", float(cur["high"])))
        valid = [(t, lv) for (t, lv) in cands if lv > entry]         # must be above price
        struct_type, level = (min(valid, key=lambda x: x[1]) if valid else (None, None))  # lowest = tightest
        struct_stop = round(level + bf * atr, 2) if level is not None else None
        atr_stop = round(entry + am * atr, 2)
        # tighter short stop = the LOWER price.
        if struct_stop is not None and struct_stop < atr_stop:
            rec, src, stype = struct_stop, "structure", struct_type
        else:
            rec, src, stype = atr_stop, "atr", (struct_type or "atr_only")

    risk_atr = round(abs(entry - rec) / atr, 2) if atr else None
    if src == "structure":
        note = (f"{stype.replace('_', ' ')} ${level:.2f} gives a tighter stop than {am}× ATR "
                f"(${atr_stop:.2f}) — structure respected (+{bf}× ATR buffer).")
    else:
        tight_note = (f"structure {struct_type.replace('_', ' ')} ${level:.2f} is LOOSER than ATR — using ATR"
                      if struct_type and level is not None else "no significant structure below/above — pure ATR")
        note = f"{am}× ATR stop ${atr_stop:.2f} ({tight_note})."

    return {"available": True, "symbol": symbol, "direction": direction, "timeframe": tf_used, "entry": round(entry, 2),
            "atr": round(atr, 4), "structure_type": stype, "structure_level": (round(level, 2) if level is not None else None),
            "structure_stop": struct_stop, "atr_stop": atr_stop,
            "recommended_stop": rec, "recommended_source": src, "recommended_risk_atr": risk_atr,
            "candidates": [{"structure_type": t, "level": round(lv, 2)} for (t, lv) in cands],
            "note": note}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", required=True)
    ap.add_argument("--direction", default="long")
    ap.add_argument("--entry", type=float)
    args = ap.parse_args()
    print(json.dumps(analyze(args.symbol, direction=args.direction, entry_price=args.entry), indent=2, default=str))


if __name__ == "__main__":
    main()
