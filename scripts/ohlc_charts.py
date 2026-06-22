#!/usr/bin/env python3
"""ohlc_charts.py — free OHLCV + indicators for per-trade replay charts (TradingView Lightweight Charts).

Source: Alpaca free historical bars (data.alpaca.markets, IEX feed) — OHLCV + VWAP, daily + intraday. Indicators
(VWAP/MACD/RSI) computed from the bars. No metered API; uses the existing paper Alpaca keys. Read-only.
"""
import os, sys, json, urllib.request, urllib.error, datetime as dt

ALPACA_DATA = "https://data.alpaca.markets/v2/stocks/{sym}/bars"
# Data feed: 'sip' = full consolidated tape (covers OTC/microcaps; historical SIP is free since 2024),
# 'iex' = IEX-only (free, but misses many OTC names). Configurable, never hardcoded credentials.
ALPACA_FEED = os.environ.get("ALPACA_DATA_FEED", "sip")

# GLOBAL Alpaca rate limiter (cross-process). This path had no throttle/retry/cache, so a large scoring
# batch (e.g. 547 candidates after a screener pool rebuild) burst-hammered the free-tier data API into
# HTTP 429 → starved scoring → 0 signals. Fail-open if the module is unavailable.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from alpaca_throttle import acquire as _alp_acquire, cooldown as _alp_cooldown
except Exception:
    def _alp_acquire(*a, **k): return 0.0
    def _alp_cooldown(*a, **k): pass

# In-process memo cache for fetched bars (one scoring run touches the same symbols/windows repeatedly across
# stages). Keyed by (symbol, start, end, timeframe, feed). Bounded; cleared per process lifetime.
_BARS_CACHE = {}
_BARS_CACHE_MAX = int(os.environ.get("OHLC_CACHE_MAX", "2000"))
# How many times a single page may be retried after a global cooldown on 429 before giving up.
_ALP_429_RETRIES = int(os.environ.get("ALPACA_429_RETRIES", "2"))

try:
    from zoneinfo import ZoneInfo
    _ET = ZoneInfo("America/New_York")
except Exception:
    _ET = None


def _sess(d, h, m):
    """h:m ET of date d as aware UTC (module-level for reuse by execution-quality analytics)."""
    if _ET:
        return dt.datetime.combine(d, dt.time(h, m), tzinfo=_ET).astimezone(dt.timezone.utc)
    return dt.datetime.combine(d, dt.time(h + 4, m), tzinfo=dt.timezone.utc)


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
    # isoformat() yields '+00:00' for UTC; in a URL query the '+' decodes to a SPACE -> Alpaca 400. Use 'Z'.
    start = str(start).replace("+00:00", "Z")
    end = str(end).replace("+00:00", "Z")
    ckey = (symbol, start, end, timeframe, ALPACA_FEED)
    if ckey in _BARS_CACHE:
        return _BARS_CACHE[ckey], None
    bars, token = [], None
    for _ in range(6):  # page
        q = (f"?timeframe={timeframe}&start={start}&end={end}&limit=10000&feed={ALPACA_FEED}&adjustment=split"
             + (f"&page_token={token}" if token else ""))
        # Throttle every request globally; on 429 record a cooldown (all consumers back off) and retry the
        # SAME page after it clears, so a transient rate-limit doesn't drop the symbol entirely.
        d = None
        for _attempt in range(_ALP_429_RETRIES + 1):
            _alp_acquire()  # blocks until a global slot is free, honoring any active cooldown
            req = urllib.request.Request(ALPACA_DATA.format(sym=symbol) + q,
                                         headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": sec})
            try:
                with urllib.request.urlopen(req, timeout=15) as r:
                    d = json.load(r)
                break
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    retry_after = None
                    try:
                        _ra = e.headers.get("Retry-After") if e.headers else None
                        retry_after = float(_ra) if _ra else None
                    except (TypeError, ValueError):
                        retry_after = None
                    _alp_cooldown(retry_after)  # default 30s — applies to ALL Alpaca data consumers
                    continue  # next acquire() will block until the cooldown clears, then retry this page
                return bars, f"alpaca {e.code}"
            except Exception as e:
                return bars, str(e)[:80]
        if d is None:
            return bars, "alpaca 429 (exhausted retries)"
        bars += d.get("bars") or []
        token = d.get("next_page_token")
        if not token:
            break
    else:
        # hit the 6-page cap with a token still pending: data truncated — say so (audit: silent truncation)
        print(f"  [ohlc] WARNING {symbol} {timeframe}: hit 6-page Alpaca cap with more data pending — bars truncated")
    if len(_BARS_CACHE) < _BARS_CACHE_MAX:
        _BARS_CACHE[ckey] = bars
    return bars, None


def _schwab_bars(symbol, start, end, timeframe):
    """TIER 2 (best-effort): Schwab price history via schwab_transport (read-only). Returns Alpaca-shaped
    bars or [] if not wired/unavailable — so the caller falls through to the Finviz image.

    Chunking (2026-06-11 audit): Schwab minute-history has window caps and no pagination — long intraday
    spans are split into <=10-day chunks and concatenated so the fallback can't silently undersize."""
    if timeframe != "1Day":
        import datetime as _dt
        try:
            _s = _dt.datetime.fromisoformat(str(start).replace("Z", "+00:00"))
            _e = _dt.datetime.fromisoformat(str(end).replace("Z", "+00:00"))
        except Exception:
            _s = _e = None
        if _s and _e and (_e - _s).days > 10:
            out, cur = [], _s
            while cur < _e:
                nxt = min(cur + _dt.timedelta(days=10), _e)
                out += _schwab_bars(symbol, cur.strftime("%Y-%m-%dT%H:%M:%SZ"),
                                    nxt.strftime("%Y-%m-%dT%H:%M:%SZ"), timeframe) or []
                cur = nxt
            seen, dedup = set(), []
            for b in out:
                if b["t"] not in seen:
                    seen.add(b["t"]); dedup.append(b)
            return dedup
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

    def _sess(d, h, m):
        """h:m ET of date d as aware UTC."""
        if _ET:
            return dt.datetime.combine(d, dt.time(h, m), tzinfo=_ET).astimezone(dt.timezone.utc)
        return dt.datetime.combine(d, dt.time(h + 4, m), tzinfo=dt.timezone.utc)

    def _session_open(d):
        return _sess(d, 9, 30)

    def _session_close(d):
        return _sess(d, 16, 0)

    sess_open = sess_close = None
    if same_day and has_time:
        timeframe = "1Min"
        sess_open, sess_close = _session_open(ed), _session_close(ed)
        # DISPLAY window: pad each side by max(10 min, the hold), capped 60 min.
        hold = ext - ent
        pad = max(dt.timedelta(minutes=10), min(hold, dt.timedelta(minutes=60)))
        s_dt, e_dt = ent - pad, ext + pad
        # morning trade (entry within 90 min of the open) -> show ~30 min PREMARKET + the open
        if ent <= sess_open + dt.timedelta(minutes=90):
            s_dt = min(s_dt, sess_open - dt.timedelta(minutes=30))
        # afternoon trade (exit within 90 min of the close) -> show the close + ~30 min AFTER-HOURS
        if ext >= sess_close - dt.timedelta(minutes=90):
            e_dt = max(e_dt, sess_close + dt.timedelta(minutes=30))
        win = (s_dt, e_dt)
        # FETCH premarket(4:00 ET) -> the window end (incl after-hours) so those bars + VWAP context exist.
        start, end = min(sess_open - dt.timedelta(hours=5, minutes=30), s_dt).isoformat(), e_dt.isoformat()
    elif same_day:
        timeframe = "1Min"   # same-day, no fill time -> premarket + regular session + a little after-hours
        sess_open, sess_close = _session_open(ed), _session_close(ed)
        s_dt = sess_open - dt.timedelta(minutes=30)
        e_dt = sess_close + dt.timedelta(minutes=30)
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
    session_open_time = session_close_time = None
    for i, b in enumerate(bars):
        bt = dt.datetime.fromisoformat(b["t"].replace("Z", "+00:00"))
        # session VWAP = REGULAR hours only (excludes premarket AND after-hours), standard convention
        in_session = sess_open is None or (bt >= sess_open and (sess_close is None or bt < sess_close))
        if in_session:
            tp = (b["h"] + b["l"] + b["c"]) / 3.0
            cum_pv += tp * (b.get("v") or 0); cum_v += (b.get("v") or 0)
        if win is not None and not (s_dt <= bt <= e_dt):     # only DISPLAY bars inside the window
            continue
        tkey = b["t"][:10] if timeframe == "1Day" else _et_ts(b["t"])
        if (sess_open is not None and session_open_time is None and bt >= sess_open
                and (bt - sess_open) < dt.timedelta(minutes=2)):   # only the actual 9:30 bar
            session_open_time = tkey
        if (sess_close is not None and session_close_time is None and bt >= sess_close
                and (bt - sess_close) < dt.timedelta(minutes=2)):  # only the actual 16:00 bar
            session_close_time = tkey
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

    # ── Replay backlog (2026-06-11): news pins + L2 pressure strip + SPY overlay ───────────────────────────
    def _bar_time_for(ts_dt):
        if timeframe == "1Day":
            td = ts_dt.date().isoformat()
            cands = [b["time"] for b in out_bars if b["time"] <= td]
            return cands[-1] if cands else None
        tgt = _et_ts(ts_dt.astimezone(dt.timezone.utc).isoformat())
        near = min(out_bars, key=lambda b: abs(b["time"] - tgt))
        return near["time"] if abs(near["time"] - tgt) <= (90 if timeframe != "1Day" else 0) * 60 else None

    news_events = []
    try:
        from db_adapter import _get_conn as _gc2
        _c = _gc2(); _cu = _c.cursor()
        _pad = dt.timedelta(hours=4) if same_day else dt.timedelta(days=2)
        _cu.execute("""SELECT published_at, title, source FROM news_articles
                       WHERE symbol=%s AND published_at BETWEEN %s AND %s
                       ORDER BY published_at LIMIT 12""",
                    (symbol, (ent - _pad), (ext + _pad)))
        _first_bt, _last_bt = out_bars[0]["time"], out_bars[-1]["time"]
        for _pa, _ti, _so in _cu.fetchall():
            if _pa is None:
                continue
            _pdt = _pa if _pa.tzinfo else _pa.replace(tzinfo=dt.timezone.utc)
            _bt = _bar_time_for(_pdt)
            _clamped = None
            if _bt is None:
                # clamp out-of-window catalysts to the chart edge instead of dropping them — an 08:00
                # offering pricing IS the story of an 11:00 trade (found via ATOS 2026-06-11)
                _clamped = "pre" if _pdt <= ent else "post"
                _bt = _first_bt if _clamped == "pre" else _last_bt
            news_events.append({"time": _bt, "title": (_ti or "")[:110], "source": _so, "clamped": _clamped,
                                "at_et": (_pa.astimezone(_ET).strftime("%m-%d %H:%M") if _ET else str(_pa)[:16])})
        _c.close()
    except Exception:
        pass

    l2_strip = []
    try:
        from db_adapter import _get_conn as _gc3
        _c = _gc3(); _cu = _c.cursor()
        _cu.execute("""SELECT captured_at, imbalance FROM schwab_stream_book
                       WHERE symbol=%s AND captured_at BETWEEN %s AND %s AND imbalance IS NOT NULL
                       ORDER BY captured_at""", (symbol, ent - dt.timedelta(minutes=30), ext + dt.timedelta(minutes=30)))
        _seen_t = set()
        for _ca, _imb in _cu.fetchall():
            _bt = _bar_time_for(_ca if _ca.tzinfo else _ca.replace(tzinfo=dt.timezone.utc))
            if _bt is not None and _bt not in _seen_t:
                _seen_t.add(_bt)
                l2_strip.append({"time": _bt, "value": float(_imb)})
        _c.close()
    except Exception:
        pass

    spy_overlay = []
    try:
        sbars, _serr = _fetch("SPY", start, end, timeframe)
        if not sbars:
            sbars = _schwab_bars("SPY", start, end, timeframe)
        if sbars and out_bars:
            _smap = {}
            for b in sbars:
                k = b["t"][:10] if timeframe == "1Day" else _et_ts(b["t"])
                _smap[k] = b["c"]
            _base_sym = out_bars[0]["close"]
            _base_spy = next((_smap[b["time"]] for b in out_bars if b["time"] in _smap), None)
            if _base_spy:
                for b in out_bars:
                    if b["time"] in _smap:
                        # SPY rebased to the symbol's first close: same-$ overlay shows relative strength
                        spy_overlay.append({"time": b["time"],
                                            "value": round(_base_sym * (_smap[b["time"]] / _base_spy), 4)})
    except Exception:
        pass

    et = lambda d: (d.astimezone(_ET).strftime("%H:%M:%S ET") if _ET else d.strftime("%H:%M UTC"))
    return {"symbol": symbol, "timeframe": timeframe, "source": source, "tz": "America/New_York",
            "entry_et": et(ent), "exit_et": et(ext), "bars": out_bars, "volume": vol, "vwap": vwap,
            "macd": out_macd, "rsi": out_rsi, "markers": markers, "bar_count": len(out_bars),
            "session_open_time": session_open_time, "session_close_time": session_close_time,
            "news_events": news_events, "l2_strip": l2_strip, "spy_overlay": spy_overlay}


if __name__ == "__main__":
    import sys
    print(json.dumps(trade_chart(*sys.argv[1:]), indent=2)[:1200])
