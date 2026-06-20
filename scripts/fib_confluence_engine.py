#!/usr/bin/env python3
"""fib_confluence_engine.py — MULTI-TIMEFRAME swing structure + Fibonacci retracement/extension +
cross-timeframe confluence, for one symbol. Analyzes several charts (daily / weekly / monthly) instead
of a single active chart, surfaces the swing highs/lows, Fib levels, trend/structure and S/R per
timeframe, then clusters levels that align ACROSS timeframes into ranked confluence zones.

Transparent by design: every level carries its originating timeframe + source so the analysis can be
verified. Advisory only — never places a trade. Source: yfinance OHLC (on-demand, cached by the API).

  .venv/bin/python scripts/fib_confluence_engine.py --symbol NVDA
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# (name, yfinance period, interval) — short / mid / long structure
TIMEFRAMES = [("daily", "6mo", "1d"), ("weekly", "2y", "1wk"), ("monthly", "6y", "1mo")]
FIB_RETR = [0.236, 0.382, 0.5, 0.618, 0.786]
FIB_EXT = [1.272, 1.618, 2.618]
CONFLUENCE_TOL_PCT = 1.5   # levels within this % of each other cluster into one zone


def _fetch_bars(symbol, period, interval):
    import yfinance as yf
    h = yf.Ticker(symbol).history(period=period, interval=interval, auto_adjust=False)
    if h is None or len(h) < 8:
        return []
    return [{"t": str(idx.date()), "o": float(r["Open"]), "h": float(r["High"]), "l": float(r["Low"]), "c": float(r["Close"])}
            for idx, r in h.iterrows() if r["High"] == r["High"] and r["Low"] == r["Low"]]


def _pivots(bars, span=3):
    """Fractal swing pivots: a swing high (low) is a bar whose high (low) is the extreme within ±span bars."""
    highs, lows = [], []
    for i in range(span, len(bars) - span):
        win = bars[i - span:i + span + 1]
        if bars[i]["h"] == max(b["h"] for b in win):
            highs.append((i, bars[i]["h"], bars[i]["t"]))
        if bars[i]["l"] == min(b["l"] for b in win):
            lows.append((i, bars[i]["l"], bars[i]["t"]))
    return highs, lows


def _structure(highs, lows):
    """Trend from the last two swing highs + lows: HH+HL=uptrend, LH+LL=downtrend, else range."""
    if len(highs) >= 2 and len(lows) >= 2:
        hh = highs[-1][1] > highs[-2][1]
        hl = lows[-1][1] > lows[-2][1]
        if hh and hl:
            return "uptrend", "higher highs + higher lows"
        if not hh and not hl:
            return "downtrend", "lower highs + lower lows"
    return "range", "no clean HH/HL or LH/LL sequence"


def _analyze_tf(symbol, name, period, interval):
    bars = _fetch_bars(symbol, period, interval)
    if len(bars) < 12:
        return {"timeframe": name, "available": False, "reason": "insufficient bars"}
    span = 2 if name == "monthly" else 3
    highs, lows = _pivots(bars, span)
    if not highs or not lows:
        return {"timeframe": name, "available": False, "reason": "no swing pivots"}
    direction, structure = _structure(highs, lows)
    # dominant swing = the most significant recent leg: the highest swing high and the lowest swing low
    sh = max(highs, key=lambda x: x[1])
    sl = min(lows, key=lambda x: x[1])
    swing_high, sh_date = sh[1], sh[2]
    swing_low, sl_date = sl[1], sl[2]
    rng = swing_high - swing_low
    cur = bars[-1]["c"]
    # retracement: levels inside the swing; extension: beyond it (in the trend direction)
    up = direction != "downtrend"   # default measure low→high (retrace down) unless a clean downtrend
    retr = []
    for r in FIB_RETR:
        px = swing_high - rng * r if up else swing_low + rng * r
        retr.append({"ratio": r, "label": f"{r*100:.1f}%", "price": round(px, 2)})
    ext = []
    for e in FIB_EXT:
        px = swing_high + rng * (e - 1) if up else swing_low - rng * (e - 1)
        ext.append({"ratio": e, "label": f"{e*100:.1f}%", "price": round(px, 2)})
    # S/R = the most recent few swing highs/lows
    sr_res = sorted({round(h[1], 2) for h in highs[-3:]}, reverse=True)
    sr_sup = sorted({round(l[1], 2) for l in lows[-3:]})
    return {"timeframe": name, "available": True, "bars": len(bars), "current_price": round(cur, 2),
            "trend": direction, "structure": structure,
            "swing_high": round(swing_high, 2), "swing_high_date": sh_date,
            "swing_low": round(swing_low, 2), "swing_low_date": sl_date,
            "range_pct": round(rng / swing_low * 100, 1) if swing_low else None,
            "measured": "low→high (retrace down)" if up else "high→low (retrace up)",
            "retracements": retr, "extensions": ext,
            "resistance": sr_res, "support": sr_sup}


def _confluence(tfs, current_price):
    """Cluster every level (fib retr/ext + swing high/low + S/R) across timeframes; rank by overlap."""
    pts = []   # (price, timeframe, kind, label)
    for tf in tfs:
        if not tf.get("available"):
            continue
        n = tf["timeframe"]
        for r in tf["retracements"]:
            pts.append((r["price"], n, "fib_retr", f"{n} {r['label']} retr"))
        for e in tf["extensions"]:
            pts.append((e["price"], n, "fib_ext", f"{n} {e['label']} ext"))
        pts.append((tf["swing_high"], n, "swing_high", f"{n} swing high"))
        pts.append((tf["swing_low"], n, "swing_low", f"{n} swing low"))
        for s in tf["support"]:
            pts.append((s, n, "support", f"{n} support"))
        for s in tf["resistance"]:
            pts.append((s, n, "resistance", f"{n} resistance"))
    pts = [p for p in pts if p[0] and p[0] > 0]
    pts.sort(key=lambda x: x[0])
    zones, used = [], [False] * len(pts)
    for i, p in enumerate(pts):
        if used[i]:
            continue
        cluster = [p]
        used[i] = True
        for j in range(i + 1, len(pts)):
            if used[j]:
                continue
            if abs(pts[j][0] - p[0]) / p[0] * 100 <= CONFLUENCE_TOL_PCT:
                cluster.append(pts[j]); used[j] = True
        prices = [c[0] for c in cluster]
        tfset = sorted({c[1] for c in cluster})
        kinds = sorted({c[2] for c in cluster})
        if len(cluster) < 2:
            continue   # a single level is not confluence
        lo, hi = min(prices), max(prices)
        mid = sum(prices) / len(prices)
        # strength = # overlapping signals + bonus for timeframe diversity + bonus for mixed signal kinds
        strength = len(cluster) + (len(tfset) - 1) * 1.5 + (len(kinds) - 1) * 0.5
        zones.append({
            "price_low": round(lo, 2), "price_high": round(hi, 2), "price_mid": round(mid, 2),
            "dist_pct": round((mid - current_price) / current_price * 100, 1) if current_price else None,
            "signal_count": len(cluster), "timeframes": tfset, "signal_kinds": kinds,
            "levels": [c[3] for c in cluster], "strength": round(strength, 1),
            "zone": "above" if mid > current_price else "below"})
    zones.sort(key=lambda z: z["strength"], reverse=True)
    for i, z in enumerate(zones):
        z["confidence"] = "high" if z["strength"] >= 5 else "medium" if z["strength"] >= 3.5 else "low"
    return zones


def analyze(symbol: str) -> dict:
    symbol = (symbol or "").upper().strip()
    if not symbol:
        return {"ok": False, "error": "symbol required"}
    try:
        tfs = [_analyze_tf(symbol, n, p, i) for (n, p, i) in TIMEFRAMES]
        cur = next((t["current_price"] for t in tfs if t.get("available")), None)
        zones = _confluence(tfs, cur) if cur else []
        # OHLC bars for the on-click charts (drawn with the Fib levels as price lines, no extra fetch):
        # daily (~6mo) + monthly (~6yr) so details show both short- and long-term structure.
        chart_bars = _fetch_bars(symbol, "6mo", "1d")[-140:]
        chart_bars_monthly = _fetch_bars(symbol, "6y", "1mo")[-84:]
        return {"ok": True, "advisory_only": True, "symbol": symbol, "current_price": cur,
                "timeframes": tfs, "confluence_zones": zones,
                "chart_bars": chart_bars, "chart_bars_monthly": chart_bars_monthly,
                "note": "Multi-timeframe swing + Fibonacci + cross-timeframe confluence. Advisory only — "
                        "verify against your own charts; never an order."}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200], "symbol": symbol}


def main():
    import argparse, json
    from dotenv import load_dotenv
    load_dotenv(str(Path(__file__).resolve().parent.parent / ".env"))
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", required=True)
    a = ap.parse_args()
    print(json.dumps(analyze(a.symbol), indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
