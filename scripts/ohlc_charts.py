#!/usr/bin/env python3
"""ohlc_charts.py — free OHLCV + indicators for per-trade replay charts (TradingView Lightweight Charts).

Source: Alpaca free historical bars (data.alpaca.markets, IEX feed) — OHLCV + VWAP, daily + intraday. Indicators
(VWAP/MACD/RSI) computed from the bars. No metered API; uses the existing paper Alpaca keys. Read-only.
"""
import os, json, urllib.request, urllib.error, datetime as dt

ALPACA_DATA = "https://data.alpaca.markets/v2/stocks/{sym}/bars"


def _keys():
    return (os.environ.get("ALPACA_API_KEY") or os.environ.get("APCA_API_KEY_ID"),
            os.environ.get("ALPACA_SECRET_KEY") or os.environ.get("APCA_API_SECRET_KEY"))


def _fetch(symbol, start, end, timeframe):
    key, sec = _keys()
    if not key or not sec:
        return [], "no Alpaca keys"
    bars, token = [], None
    for _ in range(6):  # page
        q = (f"?timeframe={timeframe}&start={start}&end={end}&limit=10000&feed=iex&adjustment=split"
             + (f"&page_token={token}" if token else ""))
        req = urllib.request.Request(ALPACA_DATA.format(sym=symbol) + q,
                                     headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": sec})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                d = json.load(r)
        except urllib.error.HTTPError as e:
            return [], f"alpaca {e.code}"
        except Exception as e:
            return [], str(e)[:80]
        bars += d.get("bars") or []
        token = d.get("next_page_token")
        if not token:
            break
    return bars, None


def _schwab_bars(symbol, start, end, timeframe):
    """TIER 2 (best-effort): Schwab price history via schwab_transport (read-only). Returns Alpaca-shaped
    bars or [] if not wired/unavailable — so the caller falls through to the Finviz image."""
    try:
        import sys, os as _os
        sys.path.insert(0, _os.path.dirname(__file__))
        import schwab_transport as st
        if not hasattr(st, "get_price_history"):
            return []
        raw = st.get_price_history(symbol, start, end, timeframe)  # boundary owns the schwab-py call
        out = []
        for c in (raw or []):
            if not isinstance(c, dict) or "close" not in c:
                continue
            out.append({"o": c.get("open"), "h": c.get("high"), "l": c.get("low"), "c": c.get("close"),
                        "v": c.get("volume", 0), "vw": c.get("vwap"),
                        "t": c.get("datetime") or c.get("t")})
        return out
    except Exception:
        return []


def _ema(vals, p):
    k = 2.0 / (p + 1); out = []; e = None
    for v in vals:
        e = v if e is None else v * k + e * (1 - k)
        out.append(e)
    return out


def _macd(closes):
    if len(closes) < 26:
        return [None] * len(closes)
    e12, e26 = _ema(closes, 12), _ema(closes, 26)
    line = [a - b for a, b in zip(e12, e26)]
    sig = _ema(line, 9)
    return [{"macd": round(a, 4), "signal": round(b, 4), "hist": round(a - b, 4)} for a, b in zip(line, sig)]


def _rsi(closes, p=14):
    out = [None] * len(closes)
    if len(closes) <= p:
        return out
    g = l = 0.0
    for i in range(1, p + 1):
        ch = closes[i] - closes[i - 1]; g += max(ch, 0); l += max(-ch, 0)
    ag, al = g / p, l / p
    out[p] = 100 - 100 / (1 + (ag / al if al else 1e9))
    for i in range(p + 1, len(closes)):
        ch = closes[i] - closes[i - 1]
        ag = (ag * (p - 1) + max(ch, 0)) / p
        al = (al * (p - 1) + max(-ch, 0)) / p
        out[i] = 100 - 100 / (1 + (ag / al if al else 1e9))
    return [round(x, 2) if x is not None else None for x in out]


def trade_chart(symbol, entry_date, exit_date, entry_price=None, exit_price=None,
                entry_time=None, exit_time=None):
    """Return OHLCV + VWAP/MACD/RSI + entry/exit markers for a trade window.

    Same-day trade → 1-min intraday bars (scalp replay); multi-day → daily bars with padding."""
    symbol = (symbol or "").upper().strip()
    try:
        ed = dt.date.fromisoformat(str(entry_date)[:10])
        xd = dt.date.fromisoformat(str(exit_date)[:10]) if exit_date else ed
    except Exception:
        return {"error": "bad dates", "symbol": symbol}

    same_day = ed == xd
    if same_day:
        timeframe = "1Min"
        start = f"{ed.isoformat()}T00:00:00Z"
        end = (xd + dt.timedelta(days=1)).isoformat() + "T00:00:00Z"
    else:
        timeframe = "1Day"
        pad = max(5, (xd - ed).days // 5)
        start = (ed - dt.timedelta(days=pad)).isoformat()
        end = (xd + dt.timedelta(days=pad)).isoformat()

    bars, err = _fetch(symbol, start, end, timeframe)
    source = "alpaca"
    if not bars:
        # TIER 2: Schwab price history (free, authoritative, read-only behind the fence; best-effort).
        sbars = _schwab_bars(symbol, start, end, timeframe)
        if sbars:
            bars, err, source = sbars, None, "schwab"
    if err or not bars:
        # TIER 3 FALLBACK: static Finviz Elite chart image
        # (served via the /api/v2/finviz-chart proxy which attaches the Elite cookie).
        return {"symbol": symbol, "timeframe": timeframe, "bars": [], "fallback": "finviz",
                "fallback_image": f"/api/v2/finviz-chart?symbol={symbol}&p={'i5' if same_day else 'd'}",
                "reason": err or "no Alpaca bars for this symbol/window"}

    closes = [b["c"] for b in bars]
    macd, rsi = _macd(closes), _rsi(closes)
    out_bars, vol, vwap = [], [], []
    for i, b in enumerate(bars):
        t = b["t"]
        # Lightweight Charts: daily uses 'YYYY-MM-DD'; intraday uses unix seconds
        if timeframe == "1Day":
            tkey = t[:10]
        else:
            tkey = int(dt.datetime.fromisoformat(t.replace("Z", "+00:00")).timestamp())
        out_bars.append({"time": tkey, "open": b["o"], "high": b["h"], "low": b["l"], "close": b["c"]})
        vol.append({"time": tkey, "value": b.get("v", 0),
                    "color": "rgba(34,197,94,.5)" if b["c"] >= b["o"] else "rgba(239,68,68,.5)"})
        if b.get("vw"):
            vwap.append({"time": tkey, "value": round(b["vw"], 4)})

    def _markseries(ind):
        return [{"time": out_bars[i]["time"], **ind[i]} for i in range(len(ind)) if ind[i] is not None]

    def _bar_at(target_date, default_idx):
        """closest bar time to a YYYY-MM-DD (daily) — so the marker lands on the real entry/exit bar."""
        try:
            td = str(target_date)[:10]
            if timeframe == "1Day":
                cands = [b["time"] for b in out_bars if b["time"] <= td]
                return cands[-1] if cands else out_bars[default_idx]["time"]
        except Exception:
            pass
        return out_bars[default_idx]["time"]

    markers = []
    if entry_price:
        markers.append({"time": _bar_at(entry_date, 0), "price": float(entry_price), "type": "entry",
                        "label": f"BUY {entry_price}"})
    if exit_price:
        markers.append({"time": _bar_at(exit_date, -1), "price": float(exit_price), "type": "exit",
                        "label": f"SELL {exit_price}"})

    return {"symbol": symbol, "timeframe": timeframe, "source": source, "bars": out_bars, "volume": vol, "vwap": vwap,
            "macd": [{"time": out_bars[i]["time"], **macd[i]} for i in range(len(macd)) if macd[i] is not None],
            "rsi": [{"time": out_bars[i]["time"], "value": rsi[i]} for i in range(len(rsi)) if rsi[i] is not None],
            "markers": markers, "bar_count": len(out_bars)}


if __name__ == "__main__":
    import sys
    print(json.dumps(trade_chart(*sys.argv[1:]), indent=2)[:1200])
