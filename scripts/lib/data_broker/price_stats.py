"""Price Stats — Data Broker read model for 52-week range, period changes, moving averages and volume.

Investment Command Center (operator 2026-10-08). Quotes cover ~5,400 symbols but avg volume and the 52-week range
were filled for ~60 and weekly/monthly change went stale on 2026-09-29; SMA200 is absent from the confluence cache.
All of it is derivable from stores we already hold, so nothing new is fetched:
  * ticker_prices (registry domain ``technicals``, ~254 daily closes per symbol) → 52-week high/low (closes),
    week (5 sessions) / month (21 sessions) change, SMA 20/50/200;
  * market_ohlcv_bars timeframe 'daily' (~1,210 symbols) → true 52-week high/low, 30-session average volume and
    relative volume (latest bar ÷ average).
Zero provider calls. Read-only. Each symbol carries ``as_of`` and the source of each block.
"""
from __future__ import annotations

from typing import Any

from lib.data_broker.envelope import envelope

DOMAIN = "technicals"
CLOSES_SQL = """SELECT upper(symbol) AS s, price_date, close_price FROM ticker_prices
                 WHERE upper(symbol) = ANY(%s) AND price_date > CURRENT_DATE - 380
                 ORDER BY upper(symbol), price_date"""
BARS_SQL = """SELECT upper(symbol) AS s, bar_time, high, low, close, volume FROM market_ohlcv_bars
               WHERE upper(symbol) = ANY(%s) AND timeframe = 'daily' AND bar_time > now() - interval '380 days'
               ORDER BY upper(symbol), bar_time"""


def _f(v: Any) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _sma(xs: list[float], n: int) -> float | None:
    return round(sum(xs[-n:]) / n, 4) if len(xs) >= n else None


def _chg(xs: list[float], back: int) -> float | None:
    if len(xs) <= back or not xs[-1 - back]:
        return None
    return round((xs[-1] - xs[-1 - back]) / xs[-1 - back] * 100, 2)


def compute(closes: list[float], bars: list[dict[str, Any]]) -> dict[str, Any]:
    """Pure: stats from an ascending close series and ascending daily bars."""
    out: dict[str, Any] = {}
    year = closes[-252:]
    if year:
        out.update(high_52w=max(year), low_52w=min(year), range_source="ticker_prices.close")
    hb = [b for b in bars[-252:] if _f(b.get("high")) is not None and _f(b.get("low")) is not None]
    if len(hb) >= 120:  # a true intraday range only when the bar history covers most of the year
        out.update(high_52w=max(_f(b["high"]) for b in hb), low_52w=min(_f(b["low"]) for b in hb),
                   range_source="market_ohlcv_bars.daily")
    out.update(change_1w_pct=_chg(closes, 5), change_1m_pct=_chg(closes, 21),
               sma_20=_sma(closes, 20), sma_50=_sma(closes, 50), sma_200=_sma(closes, 200))
    vols = [_f(b.get("volume")) for b in bars if _f(b.get("volume"))]
    if len(vols) >= 10:
        avg = sum(vols[-31:-1]) / len(vols[-31:-1]) if len(vols) > 1 else None
        out["avg_volume_30d"] = round(avg) if avg else None
        out["relative_volume"] = round(vols[-1] / avg, 2) if avg else None
        out["volume_source"] = "market_ohlcv_bars.daily"
    last = closes[-1] if closes else None
    if last and out.get("sma_20") and out.get("sma_50") and out.get("sma_200"):
        s20, s50, s200 = out["sma_20"], out["sma_50"], out["sma_200"]
        out["ma_alignment"] = ("bullish" if last > s20 > s50 > s200 else
                               "bearish" if last < s20 < s50 < s200 else "mixed")
    out["closes_n"] = len(closes)
    return out


def get_price_stats(db_query, symbols: list[str], *, now=None, registry=None) -> dict[str, dict[str, Any]]:
    """{SYMBOL: {high_52w, low_52w, change_1w_pct, change_1m_pct, sma_20/50/200, ma_alignment, avg_volume_30d,
    relative_volume, as_of, ...}} for a batch. Missing inputs leave the field absent (never a fake value)."""
    syms = sorted({str(s).upper().strip() for s in symbols if s and str(s).strip()})
    if not syms:
        return {}
    closes: dict[str, list[float]] = {}
    as_of: dict[str, Any] = {}
    for r in db_query(CLOSES_SQL, (syms,)) or []:
        c = _f(r.get("close_price"))
        if c:
            closes.setdefault(r["s"], []).append(c)
            as_of[r["s"]] = r.get("price_date")
    bars: dict[str, list[dict[str, Any]]] = {}
    for r in db_query(BARS_SQL, (syms,)) or []:
        bars.setdefault(r["s"], []).append(r)
    out: dict[str, dict[str, Any]] = {}
    for s in syms:
        if s not in closes and s not in bars:
            continue
        st = compute(closes.get(s) or [], bars.get(s) or [])
        st.update(envelope(DOMAIN, as_of.get(s), now=now, registry=registry,
                           source={"table": "ticker_prices+market_ohlcv_bars"}))
        out[s] = st
    return out
