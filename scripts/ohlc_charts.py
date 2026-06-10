#!/usr/bin/env python3
"""ohlc_charts.py — free OHLCV + indicators for per-trade replay charts (TradingView Lightweight Charts).

Source: Alpaca free historical bars (data.alpaca.markets, IEX feed) — OHLCV + VWAP, daily + intraday. Indicators
(VWAP/MACD/RSI) computed from the bars. No metered API; uses the existing paper Alpaca keys. Read-only.
"""
import os, json, urllib.request, urllib.error, datetime as dt

ALPACA_DATA = "https://data.alpaca.markets/v2/stocks/{sym}/bars"

try:
    from zoneinfo import ZoneInfo
    _ET = ZoneInfo("America/New_York")
except Exception:
    _ET = None


def _et_ts(iso):
    """UTC ISO -> a unix timestamp whose UTC wall-clock equals US/Eastern wall-clock (DST-aware), so
    Lightweight Charts (renders in UTC) shows ET market time. e.g. 12:08Z -> displays 08:08 (EDT)."""
    d = dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    if _ET is not None:
        d = d.astimezone(_ET)
    else:  # fallback: rough EDT(Mar-Nov)/EST offset
        d = d - dt.timedelta(hours=4 if 3 <= d.month <= 11 else 5)
    return int(d.replace(tzinfo=dt.timezone.utc).timestamp())


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


def _parse_ts(s):
    """Parse a date or full timestamp -> aware UTC datetime (normalizes space + short '-04' offset)."""
    import re as _re
    if not s:
        return None
    x = str(s).strip().replace(" ", "T").replace("Z", "+00:00")
    if "T" in x:                                 # only normalize a tz offset on a timestamp, NOT a bare date
        x = _re.sub(r"(T.*[+-]\d{2})$", r"\1:00", x)   # ...-04 -> ...-04:00
    try:
        d = dt.datetime.fromisoformat(x)
        return (d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)).astimezone(dt.timezone.utc)
    except Exception:
        try:
            return dt.datetime.fromisoformat(x[:10]).replace(tzinfo=dt.timezone.utc)
        except Exception:
            return None


def trade_chart(symbol, entry_date, exit_date, entry_price=None, exit_price=None,
                entry_time=None, exit_time=None):
    """OHLCV + VWAP/MACD/RSI + entry/exit markers. Same-day -> 1-min bars in a TIGHT window around the
    actual fill times (NOT the whole session); multi-day -> daily. Times shown in US/Eastern."""
    symbol = (symbol or "").upper().strip()
    ent = _parse_ts(entry_time or entry_date)
    ext = _parse_ts(exit_time or exit_date) or ent
    if not ent:
        return {"error": "bad dates", "symbol": symbol}
    if ext < ent:
        ext = ent
    ed, xd = ent.date(), ext.date()
    same_day = ed == xd
    has_time = bool(ent.hour or ent.minute or ext.hour or ext.minute)
    win = None

    def _session_open(d):
        """09:30 ET of date d as aware UTC — for true session VWAP + indicator context."""
        if _ET:
            return dt.datetime.combine(d, dt.time(9, 30), tzinfo=_ET).astimezone(dt.timezone.utc)
        return dt.datetime.combine(d, dt.time(13, 30), tzinfo=dt.timezone.utc)

    sess_open = None
    if same_day and has_time:
        timeframe = "1Min"
        sess_open = _session_open(ed)
        # DISPLAY window: pad each side by max(10 min, the hold), capped 60 min.
        hold = ext - ent
        pad = max(dt.timedelta(minutes=10), min(hold, dt.timedelta(minutes=60)))
        s_dt, e_dt = ent - pad, ext + pad
        # morning trade (entry within 90 min of the open) -> show ~30 min PREMARKET + the open for context
        if ent <= sess_open + dt.timedelta(minutes=90):
            s_dt = min(s_dt, sess_open - dt.timedelta(minutes=30))
        win = (s_dt, e_dt)
        # FETCH from premarket open (4:00 ET) so premarket bars exist + VWAP/indicators have context.
        start, end = min(_session_open(ed) - dt.timedelta(hours=5, minutes=30), s_dt).isoformat(), e_dt.isoformat()
    elif same_day:
        timeframe = "1Min"   # same-day, no fill time -> premarket + regular session
        sess_open = _session_open(ed)
        s_dt = sess_open - dt.timedelta(minutes=30)
        e_dt = sess_open + dt.timedelta(hours=6, minutes=30)
        start, end, win = (sess_open - dt.timedelta(hours=5, minutes=30)).isoformat(), e_dt.isoformat(), (s_dt, e_dt)
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

    # Indicators + VWAP accumulate over the FULL fetch (intraday: from the 9:30 session open) so VWAP is a
    # true session VWAP reset at the open and MACD/RSI have context; we then RENDER only the display window.
    closes = [b["c"] for b in bars]
    macd, rsi = _macd(closes), _rsi(closes)
    out_bars, vol, vwap, out_macd, out_rsi = [], [], [], [], []
    cum_pv = cum_v = 0.0
    s_dt, e_dt = win if win else (None, None)
    session_open_time = None
    for i, b in enumerate(bars):
        bt = dt.datetime.fromisoformat(b["t"].replace("Z", "+00:00"))
        in_session = sess_open is None or bt >= sess_open    # session VWAP excludes premarket (standard)
        if in_session:
            tp = (b["h"] + b["l"] + b["c"]) / 3.0
            cum_pv += tp * (b.get("v") or 0); cum_v += (b.get("v") or 0)
        if win is not None and not (s_dt <= bt <= e_dt):     # only DISPLAY bars inside the window
            continue
        tkey = b["t"][:10] if timeframe == "1Day" else _et_ts(b["t"])
        if (sess_open is not None and session_open_time is None and bt >= sess_open
                and (bt - sess_open) < dt.timedelta(minutes=2)):   # only the actual 9:30 bar (not a midday first-bar)
            session_open_time = tkey
        out_bars.append({"time": tkey, "open": b["o"], "high": b["h"], "low": b["l"], "close": b["c"]})
        vol.append({"time": tkey, "value": b.get("v", 0),
                    "color": "rgba(34,197,94,.5)" if b["c"] >= b["o"] else "rgba(239,68,68,.5)"})
        if in_session:                                        # premarket bars show price/volume but no VWAP
            vwap.append({"time": tkey, "value": round(cum_pv / cum_v if cum_v else b["c"], 4)})
        if macd[i] is not None:
            out_macd.append({"time": tkey, **macd[i]})
        if rsi[i] is not None:
            out_rsi.append({"time": tkey, "value": rsi[i]})
    if not out_bars:
        return {"symbol": symbol, "timeframe": timeframe, "bars": [], "fallback": "finviz",
                "fallback_image": f"/api/v2/finviz-chart?symbol={symbol}&p={'i5' if same_day else 'd'}",
                "reason": "no bars in trade window"}

    def _mark_time(ts, default_idx):
        """bar 'time' nearest the real fill timestamp (daily: by date; intraday: nearest ET-bar)."""
        if timeframe == "1Day":
            td = ts.date().isoformat()
            cands = [b["time"] for b in out_bars if b["time"] <= td]
            return cands[-1] if cands else out_bars[default_idx]["time"]
        tgt = _et_ts(ts.astimezone(dt.timezone.utc).isoformat())
        return min(out_bars, key=lambda b: abs(b["time"] - tgt))["time"]

    markers = []
    if entry_price:
        markers.append({"time": _mark_time(ent, 0), "price": float(entry_price), "type": "entry", "label": f"BUY {entry_price}"})
    if exit_price:
        markers.append({"time": _mark_time(ext, -1), "price": float(exit_price), "type": "exit", "label": f"SELL {exit_price}"})

    et = lambda d: (d.astimezone(_ET).strftime("%H:%M:%S ET") if _ET else d.strftime("%H:%M UTC"))
    return {"symbol": symbol, "timeframe": timeframe, "source": source, "tz": "America/New_York",
            "entry_et": et(ent), "exit_et": et(ext), "bars": out_bars, "volume": vol, "vwap": vwap,
            "macd": out_macd, "rsi": out_rsi, "markers": markers, "bar_count": len(out_bars),
            "session_open_time": session_open_time}


if __name__ == "__main__":
    import sys
    print(json.dumps(trade_chart(*sys.argv[1:]), indent=2)[:1200])
