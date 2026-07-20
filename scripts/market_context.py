"""market_context.py — Market-wide context snapshot for Trade AI v12.

Fetches per run:
  - SPY / QQQ / IWM (price, change%, pre-market change%, trend vs last run)
  - VIX (level, change, direction: rising / falling / flat)
  - 11 sector ETFs with color tier and intraday trend vs last run
  - Market breadth label: Bullish / Neutral / Bearish
  - Top sector leader and laggard

Data sources (round-robin with fallback):
  1. Yahoo Finance   — PRIMARY  (free, 24/7, pre-market + post-market, handles ^VIX)
  2. FMP             — SECONDARY (real-time quotes incl. pre-market, ^VIX supported)
  3. Polygon         — TERTIARY  (intraday only, does NOT support VIX)
  4. Finviz          — FALLBACK  (token auth, ETFs only, no VIX)

v12.1 fixes:
  - Yahoo re-enabled as primary: pre-market prices work 4AM–9:30AM ET
  - VIX: mapped to ^VIX for Yahoo + FMP (Polygon stock snapshot doesn't carry VIX)
  - Polygon excluded from VIX fetch to prevent 0-return
  - Pre-market / post-market price fields added to index data
  - FMP VIX: symbol passed as ^VIX (URL-encoded automatically by requests)
  - Finviz quotes: uses FINVIZ_API_TOKEN if available
"""
from __future__ import annotations
import os, time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import requests
from finviz_http import finviz_get, finviz_probe  # global Finviz throttle (2026-07-20)

# ── Constants ─────────────────────────────────────────────────────────────────

INDICES = ["SPY", "QQQ", "IWM"]

SECTOR_ETFS = [
    ("XLK", "Technology"),
    ("XLF", "Financials"),
    ("XLE", "Energy"),
    ("XLV", "Healthcare"),
    ("XLY", "Consumer Disc."),
    ("XLI", "Industrials"),
    ("XLP", "Consumer Stapl."),
    ("XLU", "Utilities"),
    ("XLRE", "Real Estate"),
    ("XLB", "Materials"),
    ("XLC", "Comm. Services"),
]

ALL_SYMBOLS = [s for s, _ in SECTOR_ETFS] + INDICES + ["VIX"]

# Symbols that are indices — Polygon stock endpoint can't fetch these
INDEX_SYMBOLS = {"VIX"}

# Yahoo Finance symbol mapping: internal name → Yahoo symbol
YAHOO_SYMBOL_MAP = {
    "VIX": "^VIX",
}

# FMP symbol mapping: internal name → FMP symbol
FMP_SYMBOL_MAP = {
    "VIX": "^VIX",
}

# Browser-realistic headers for Yahoo Finance
_YAHOO_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
}

# ── Env helpers ───────────────────────────────────────────────────────────────

def _env(k: str) -> str:
    return os.getenv(k, "").strip()


# ── Per-source fetchers ───────────────────────────────────────────────────────

def _fetch_yahoo(symbols: List[str]) -> Dict[str, Dict]:
    """
    Yahoo Finance — primary source, 24/7 operation.

    Handles:
    - Pre-market prices (4:00 AM – 9:30 AM ET): uses preMarketPrice/preMarketChangePercent
    - Regular hours: uses regularMarketPrice/regularMarketChangePercent
    - After-hours (4:00 PM – 8:00 PM ET): uses postMarketPrice/postMarketChangePercent
    - VIX: maps "VIX" → "^VIX"

    Uses v8/finance/chart endpoint which always returns the most current price.
    """
    results = {}

    for sym in symbols:
        yahoo_sym = YAHOO_SYMBOL_MAP.get(sym, sym)
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_sym}"
            resp = requests.get(
                url,
                headers=_YAHOO_HEADERS,
                params={"interval": "1d", "range": "2d"},
                timeout=10,
            )
            if resp.status_code != 200:
                # Try query2 host as backup
                url2 = url.replace("query1.", "query2.")
                resp = requests.get(url2, headers=_YAHOO_HEADERS,
                                    params={"interval": "1d", "range": "2d"}, timeout=8)
                if resp.status_code != 200:
                    continue

            data = resp.json()
            chart_result = data.get("chart", {}).get("result", [])
            if not chart_result:
                continue
            meta = chart_result[0].get("meta", {})

            # ── Price selection: pre-market → regular → post-market ──────────
            pre_price   = meta.get("preMarketPrice")   or 0.0
            post_price  = meta.get("postMarketPrice")  or 0.0
            reg_price   = meta.get("regularMarketPrice") or 0.0
            prev_close  = meta.get("chartPreviousClose") or meta.get("previousClose") or reg_price

            # Prefer the most live price available
            # During pre-market (4–9:30 AM ET): preMarketPrice is set
            # During regular hours: regularMarketPrice is live
            # After hours: postMarketPrice is set
            live_price = pre_price or reg_price or post_price or prev_close

            # ── Change % selection ───────────────────────────────────────────
            pre_chg_pct  = meta.get("preMarketChangePercent")  or 0.0
            post_chg_pct = meta.get("postMarketChangePercent") or 0.0
            reg_chg_pct  = meta.get("regularMarketChangePercent") or 0.0

            # Use pre-market change if pre_price is set, else regular, else post
            if pre_price and abs(pre_chg_pct) > 0:
                change_pct = round(pre_chg_pct * 100, 2) if abs(pre_chg_pct) < 1 else round(pre_chg_pct, 2)
            elif post_price and abs(post_chg_pct) > 0:
                change_pct = round(post_chg_pct * 100, 2) if abs(post_chg_pct) < 1 else round(post_chg_pct, 2)
            elif reg_chg_pct:
                change_pct = round(reg_chg_pct * 100, 2) if abs(reg_chg_pct) < 1 else round(reg_chg_pct, 2)
            elif prev_close and live_price:
                change_pct = round((live_price - prev_close) / prev_close * 100, 2)
            else:
                change_pct = 0.0

            results[sym] = {
                "symbol":           sym,
                "price":            round(live_price, 2),
                "change_percent":   change_pct,
                "volume":           meta.get("regularMarketVolume") or 0,
                "prev_close":       round(float(prev_close), 2),
                "pre_market_price": round(float(pre_price), 2) if pre_price else None,
                "post_market_price": round(float(post_price), 2) if post_price else None,
                "source":           "yahoo",
            }
            time.sleep(0.15)

        except Exception:
            continue

    return results


def _fetch_fmp(symbols: List[str]) -> Dict[str, Dict]:
    """
    FMP real-time quotes — secondary source.
    Includes pre-market prices when market is closed.
    Supports ^VIX via FMP_SYMBOL_MAP.
    """
    key = _env("FMP_API_KEY")
    if not key:
        return {}
    try:
        # Map symbols (e.g. VIX → ^VIX) before sending to FMP
        mapped = [FMP_SYMBOL_MAP.get(s, s) for s in symbols]
        tickers_param = ",".join(mapped)
        url = "https://financialmodelingprep.com/stable/quote"
        resp = requests.get(
            url, params={"symbol": tickers_param, "apikey": key}, timeout=10
        )
        resp.raise_for_status()
        results = {}
        for item in resp.json() or []:
            fmp_sym = item.get("symbol", "")
            # Reverse-map FMP symbol back to internal symbol
            reverse_map = {v: k for k, v in FMP_SYMBOL_MAP.items()}
            internal_sym = reverse_map.get(fmp_sym, fmp_sym)
            if internal_sym not in symbols:
                continue
            results[internal_sym] = {
                "symbol":         internal_sym,
                "price":          item.get("price", 0),
                "change_percent": item.get("changesPercentage", 0),
                "volume":         item.get("volume", 0),
                "prev_close":     item.get("previousClose", 0),
                "source":         "fmp",
            }
        return results
    except Exception:
        return {}


def _fetch_polygon(symbols: List[str]) -> Dict[str, Dict]:
    """
    Polygon stock snapshot — tertiary source.
    NOTE: Polygon stock endpoint does NOT support index symbols (VIX).
    Index symbols are automatically excluded from the request.
    """
    key = _env("POLYGON_API_KEY")
    if not key:
        return {}

    # Exclude index symbols — Polygon stock snapshot doesn't carry them
    stock_symbols = [s for s in symbols if s not in INDEX_SYMBOLS]
    if not stock_symbols:
        return {}

    try:
        url = "https://api.polygon.io/v2/snapshot/locale/us/markets/stocks/tickers"
        resp = requests.get(
            url,
            params={"tickers": ",".join(stock_symbols), "apiKey": key},
            timeout=10,
        )
        resp.raise_for_status()
        results = {}
        for item in resp.json().get("tickers", []):
            sym = item.get("ticker", "")
            day       = item.get("day", {})
            prev      = item.get("prevDay", {})
            last      = item.get("lastTrade", {})
            change_pct = item.get("todaysChangePerc", 0) or 0

            day_close  = day.get("c", 0) or 0
            prev_close = prev.get("c", 0) or 0
            last_price = last.get("p", 0) or 0

            # Pre-market: day hasn't opened yet so day.c = 0
            # Use last trade price + compute change vs prev_close
            price = day_close or last_price or prev_close
            if last_price and prev_close and not day_close:
                change_pct = round((last_price - prev_close) / prev_close * 100, 2)

            if not price:
                continue

            results[sym] = {
                "symbol":         sym,
                "price":          round(price, 2),
                "change_percent": round(change_pct, 2),
                "volume":         day.get("v", 0),
                "prev_close":     round(prev_close, 2),
                "source":         "polygon",
            }
        return results
    except Exception:
        return {}


def _fetch_finviz_quotes(symbols: List[str]) -> Dict[str, Dict]:
    """
    Finviz quote export — fallback for ETFs.
    Uses API token if available, cookie as fallback.
    Does not support index symbols (VIX).
    """
    stock_symbols = [s for s in symbols if s not in INDEX_SYMBOLS]
    if not stock_symbols:
        return {}

    token  = _env("FINVIZ_API_TOKEN")
    cookie = _env("FINVIZ_COOKIE")
    if not token and not cookie:
        return {}

    results = {}
    session = requests.Session()
    session.headers.update({
        "User-Agent": _env("FINVIZ_USER_AGENT") or (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "text/csv,*/*",
    })
    if not token and cookie:
        session.headers["Cookie"] = cookie

    for sym in stock_symbols:
        try:
            url = f"https://elite.finviz.com/export.ashx?v=152&t={sym}"
            if token:
                url += f"&auth={token}"
            resp = finviz_get(url, timeout=8, raise_on_429=False)
            if resp.status_code != 200:
                continue
            lines = resp.text.strip().split("\n")
            if len(lines) < 2:
                continue
            headers_row = lines[0].split(",")
            vals_row    = lines[1].split(",")
            row         = dict(zip(headers_row, vals_row))
            price = float(row.get("Price", 0) or 0)
            chg   = row.get("Change", "0%").rstrip("%")
            try:
                change_pct = float(chg)
            except ValueError:
                change_pct = 0.0
            if not price:
                continue
            results[sym] = {
                "symbol":         sym,
                "price":          price,
                "change_percent": change_pct,
                "volume":         0,
                "source":         "finviz",
            }
            time.sleep(0.15)
        except Exception:
            continue
    return results


# ── Round-robin fetch ─────────────────────────────────────────────────────────

def _round_robin_fetch(symbols: List[str]) -> Dict[str, Dict]:
    """
    Try each source in priority order; fill gaps from subsequent sources.

    Priority:
      1. Yahoo Finance  — primary, 24/7, pre/post-market, handles VIX
      2. FMP            — real-time, handles VIX via ^VIX
      3. Polygon        — intraday stocks only (no VIX)
      4. Finviz         — ETF fallback (no VIX)
    """
    fetched: Dict[str, Dict] = {}
    remaining = list(symbols)

    for fetcher in [_fetch_yahoo, _fetch_fmp, _fetch_polygon, _fetch_finviz_quotes]:
        if not remaining:
            break
        batch = fetcher(remaining)
        for sym, data in batch.items():
            # Only accept data that has a non-zero price
            if sym not in fetched and (data.get("price") or 0) > 0:
                fetched[sym] = data
        remaining = [s for s in remaining if s not in fetched]

    # Fill anything still missing with zeroes
    for sym in remaining:
        fetched[sym] = {
            "symbol": sym, "price": 0, "change_percent": 0,
            "volume": 0, "source": "unavailable",
        }
    return fetched


# ── Sector tier classification ─────────────────────────────────────────────────

def _color_tier(pct: float) -> str:
    if pct >= 2:    return "strong-up"
    if pct >= 0.5:  return "up"
    if pct >= -0.5: return "flat"
    if pct >= -2:   return "down"
    return "strong-down"


# ── Breadth label ─────────────────────────────────────────────────────────────

def _breadth_label(sectors: List[Dict]) -> str:
    advancing = sum(1 for s in sectors if s["change_percent"] > 0.3)
    declining = sum(1 for s in sectors if s["change_percent"] < -0.3)
    total = len(sectors)
    if advancing >= total * 0.6:
        return "Bullish"
    if declining >= total * 0.6:
        return "Bearish"
    return "Neutral"


# ── VIX direction ─────────────────────────────────────────────────────────────

def _vix_direction(vix_pct: float) -> str:
    if vix_pct > 3:    return "spiking"
    if vix_pct > 0.5:  return "rising"
    if vix_pct < -3:   return "collapsing"
    if vix_pct < -0.5: return "falling"
    return "flat"


# ── Market session detector ───────────────────────────────────────────────────

def get_market_session(now: datetime | None = None) -> dict:
    """Detect current market session and return structured session info."""
    from datetime import time as dtime
    from zoneinfo import ZoneInfo

    if now is None:
        now = datetime.now(timezone.utc)
    try:
        now_et = now.astimezone(ZoneInfo("America/New_York"))
    except Exception:
        now_et = now

    t       = now_et.time()
    weekday = now_et.weekday()  # 0=Mon, 6=Sun

    if weekday >= 5:
        return {
            "session": "closed", "session_label": "Weekend — Market Closed",
            "session_emoji": "🔴", "session_color": "#9A9AB0",
            "opens_in_min": None, "closes_in_min": None,
            "description": "Markets closed. Next open: Monday 9:30 AM ET",
        }

    pre_start = dtime(4,  0)
    mkt_start = dtime(9, 30)
    mkt_end   = dtime(16, 0)
    ah_end    = dtime(20, 0)

    def mins(a, b):
        return int(
            (datetime.combine(now_et.date(), b)
             - datetime.combine(now_et.date(), a)).total_seconds() / 60
        )

    if t < pre_start:
        return {"session": "closed", "session_label": "Overnight — Market Closed",
                "session_emoji": "🔴", "session_color": "#9A9AB0",
                "opens_in_min": mins(t, pre_start), "closes_in_min": None,
                "description": f"Pre-market opens in {mins(t, pre_start)} min (4:00 AM ET)"}
    elif t < mkt_start:
        return {"session": "pre_market", "session_label": "Pre-Market",
                "session_emoji": "🌅", "session_color": "#F4B400",
                "opens_in_min": mins(t, mkt_start), "closes_in_min": None,
                "description": f"Market opens in {mins(t, mkt_start)} min (9:30 AM ET)"}
    elif t < mkt_end:
        return {"session": "market_hours", "session_label": "Market Open",
                "session_emoji": "🟢", "session_color": "#0F9D58",
                "opens_in_min": None, "closes_in_min": mins(t, mkt_end),
                "description": f"Market closes in {mins(t, mkt_end)} min (4:00 PM ET)"}
    elif t < ah_end:
        return {"session": "after_hours", "session_label": "After Hours",
                "session_emoji": "🌙", "session_color": "#1A73E8",
                "opens_in_min": None, "closes_in_min": mins(t, ah_end),
                "description": f"After-hours trading. Closes at 8:00 PM ET"}
    else:
        return {"session": "closed", "session_label": "Market Closed",
                "session_emoji": "🔴", "session_color": "#9A9AB0",
                "opens_in_min": None, "closes_in_min": None,
                "description": "After-hours closed. Pre-market opens 4:00 AM ET"}


# ── Main snapshot builder ─────────────────────────────────────────────────────

def get_market_snapshot() -> Dict[str, Any]:
    """
    Fetch and structure the full market context snapshot.

    Works during all sessions:
      - Pre-market  (4:00–9:30 AM ET): Yahoo returns preMarketPrice
      - Market open (9:30–4:00 PM ET): all sources return live prices
      - After-hours (4:00–8:00 PM ET): Yahoo returns postMarketPrice
      - Overnight / Weekend: returns last close prices

    Returns:
      {
        timestamp        : ISO string
        indices          : {SPY: {price, change_percent, pre_market_price, source}, ...}
        vix              : {price, change_percent, direction}
        sectors          : [{symbol, name, price, change_percent, color_tier}, ...]
        sector_leader    : {symbol, name, change_percent}
        sector_laggard   : {symbol, name, change_percent}
        breadth_label    : "Bullish" | "Neutral" | "Bearish"
        spy_direction    : "up" | "down" | "flat"
        session          : {session, session_label, session_emoji, ...}
      }
    """
    raw = _round_robin_fetch(ALL_SYMBOLS)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    # Indices
    indices = {}
    for sym in INDICES:
        d = raw.get(sym, {})
        pct = d.get("change_percent", 0) or 0
        indices[sym] = {
            "symbol":           sym,
            "price":            d.get("price", 0),
            "change_percent":   round(pct, 2),
            "pre_market_price": d.get("pre_market_price"),
            "post_market_price": d.get("post_market_price"),
            "prev_close":       d.get("prev_close", 0),
            "source":           d.get("source", "unavailable"),
        }

    # VIX
    vix_data = raw.get("VIX", {})
    vix_pct  = vix_data.get("change_percent", 0) or 0
    vix = {
        "price":          round(vix_data.get("price", 0), 2),
        "change_percent": round(vix_pct, 2),
        "direction":      _vix_direction(vix_pct),
        "source":         vix_data.get("source", "unavailable"),
    }

    # Sectors
    sectors = []
    for sym, name in SECTOR_ETFS:
        d = raw.get(sym, {})
        pct = d.get("change_percent", 0) or 0
        sectors.append({
            "symbol":         sym,
            "name":           name,
            "price":          d.get("price", 0),
            "change_percent": round(pct, 2),
            "color_tier":     _color_tier(pct),
            "source":         d.get("source", "unavailable"),
            "trend_arrow":    "→",  # filled in by trend_engine
        })

    sectors_sorted = sorted(sectors, key=lambda x: x["change_percent"], reverse=True)
    leader  = sectors_sorted[0]  if sectors_sorted else {}
    laggard = sectors_sorted[-1] if sectors_sorted else {}

    spy_pct = indices.get("SPY", {}).get("change_percent", 0)
    spy_dir = "up" if spy_pct > 0.3 else ("down" if spy_pct < -0.3 else "flat")

    session = get_market_session()

    # Log source summary for debugging
    sources_used = {d.get("source", "?") for d in raw.values() if d.get("price", 0) > 0}
    zero_count   = sum(1 for d in raw.values() if not d.get("price"))
    if zero_count:
        import logging
        logging.getLogger(__name__).warning(
            "[market_context] %d symbols returned price=0 (sources: %s)",
            zero_count, sources_used,
        )

    return {
        "timestamp":      now,
        "indices":        indices,
        "vix":            vix,
        "sectors":        sectors,
        "sector_leader":  leader,
        "sector_laggard": laggard,
        "breadth_label":  _breadth_label(sectors),
        "spy_direction":  spy_dir,
        "session":        session,
    }


# ── Standalone test ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%H:%M:%S",
    )
    print("\n=== Market Context Test ===\n")
    snap = get_market_snapshot()
    session = snap["session"]
    print(f"  Session : {session['session_emoji']}  {session['session_label']}")
    print(f"  Breadth : {snap['breadth_label']}")
    print()

    # Indices
    for sym, d in snap["indices"].items():
        pm = f"  PM:{d['pre_market_price']}" if d.get("pre_market_price") else ""
        print(f"  {sym:<4}  ${d['price']:<8.2f}  {d['change_percent']:+.2f}%{pm}  [{d['source']}]")

    # VIX
    v = snap["vix"]
    print(f"  VIX   ${v['price']:<8.2f}  {v['change_percent']:+.2f}%  {v['direction']}  [{v['source']}]")
    print()

    # Top 5 sectors
    print("  Sectors (top 5):")
    for s in sorted(snap["sectors"], key=lambda x: x["change_percent"], reverse=True)[:5]:
        print(f"    {s['symbol']:<5}  {s['change_percent']:+.2f}%  {s['color_tier']}  [{s['source']}]")
