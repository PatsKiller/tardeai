#!/usr/bin/env python3
"""market_quote_provider.py — Multi-provider quote adapter for execution readiness.

Provider hierarchy:
    1. Alpaca paper market data (real-time bid/ask if configured)
    2. Schwab Trader API batch quotes (real-time; extended-hours when linked)
    3. Polygon latest quote/trade (real-time with paid plan)
    4. Finnhub quote
    5. FMP quote
    6. yfinance delayed quote (display only, not execution eligible)
    7. Finviz cache (display only, never execution eligible)

After-hours / swing: check_fresh_quote() relaxes to 24h outside regular session
but requires a real-time broker quote (schwab/alpaca/polygon) — not delayed caches.

Usage:
    .venv/bin/python scripts/market_quote_provider.py --symbol EVC --dry-run
    .venv/bin/python scripts/market_quote_provider.py --pending-proposals --apply
    .venv/bin/python scripts/market_quote_provider.py --symbols EVC,BLMN,NNE --apply
"""
import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from session13_db import get_conn

log = logging.getLogger("quote_provider")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")

FINVIZ_CACHE_PATH = PROJECT_ROOT / "data" / "portfolios" / "state" / "finviz_quote_cache.json"

# Real-time providers acceptable for after-hours proposal validation
REALTIME_PROVIDERS = frozenset({"schwab", "alpaca", "polygon"})
INTRADAY_MAX_AGE_MINUTES = 15.0
SWING_EXTENDED_MAX_AGE_MINUTES = 1440.0  # 24h — matches proposal_execution_readiness


def _parse_schwab_timestamp(ts) -> datetime | None:
    """Parse Schwab quoteTime/tradeTime (ms epoch, s epoch, or ISO)."""
    if ts is None:
        return None
    try:
        if isinstance(ts, (int, float)):
            val = float(ts)
            if val > 1e12:
                val /= 1000.0
            return datetime.fromtimestamp(val, tz=timezone.utc)
        if isinstance(ts, str):
            if ts.isdigit():
                val = float(ts)
                if val > 1e12:
                    val /= 1000.0
                return datetime.fromtimestamp(val, tz=timezone.utc)
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if hasattr(ts, "timestamp"):
            dt = ts if getattr(ts, "tzinfo", None) else ts.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
    except Exception:
        return None
    return None


def resolve_quote_max_age_minutes(strategy_id=None, *, session=None) -> float:
    """Session-aware quote freshness ceiling for proposal generation."""
    from market_session import current_market_session

    sess = session or current_market_session()
    is_intraday = False
    if strategy_id:
        try:
            from proposal_lifecycle import get_timeframe_class
            is_intraday = get_timeframe_class(strategy_id) == "intraday"
        except Exception:
            is_intraday = strategy_id in ("momentum_scalp", "gap_and_go", "intraday_scalp")

    if is_intraday:
        return INTRADAY_MAX_AGE_MINUTES
    if sess in ("premarket", "afterhours", "closed", "weekend", "holiday"):
        return SWING_EXTENDED_MAX_AGE_MINUTES
    return INTRADAY_MAX_AGE_MINUTES


def _make_result(provider, priority, last_price, bid=None, ask=None,
                 bid_size=None, ask_size=None, day_volume=None, vwap=None,
                 quote_timestamp=None, is_delayed=False, raw_payload=None):
    spread = None
    spread_pct = None
    if bid is not None and ask is not None and bid > 0:
        spread = round(ask - bid, 4)
        spread_pct = round(spread / bid * 100, 4) if bid > 0 else None

    is_exec = (bid is not None and ask is not None and
               provider in REALTIME_PROVIDERS and not is_delayed)

    return {
        "provider": provider,
        "provider_priority": priority,
        "last_price": last_price,
        "bid": bid,
        "ask": ask,
        "bid_size": bid_size,
        "ask_size": ask_size,
        "spread": spread,
        "spread_pct": spread_pct,
        "day_volume": day_volume,
        "vwap": vwap,
        "quote_timestamp": quote_timestamp,
        "is_delayed": is_delayed,
        "is_execution_eligible": is_exec,
        "raw_payload": raw_payload or {},
    }


# ── Provider 1: Alpaca ─────────────────────────────────────────────────────

def fetch_alpaca_quote(symbol: str) -> dict:
    api_key = os.getenv("ALPACA_API_KEY", "")
    secret_key = os.getenv("ALPACA_SECRET_KEY", "")
    if not api_key or not secret_key:
        return None
    try:
        import requests
        # Alpaca data API for latest quote
        data_url = "https://data.alpaca.markets"
        headers = {
            "APCA-API-KEY-ID": api_key,
            "APCA-API-SECRET-KEY": secret_key,
        }
        resp = requests.get(
            f"{data_url}/v2/stocks/{symbol}/quotes/latest",
            headers=headers, timeout=10)
        if resp.status_code != 200:
            log.debug(f"Alpaca quote {symbol}: HTTP {resp.status_code}")
            return None
        data = resp.json()
        q = data.get("quote", {})
        if not q:
            return None
        ts = q.get("t")
        qt = datetime.fromisoformat(ts.replace("Z", "+00:00")) if ts else None
        return _make_result(
            provider="alpaca", priority=1,
            last_price=None,  # quote endpoint gives bid/ask, not last
            bid=float(q["bp"]) if q.get("bp") else None,
            ask=float(q["ap"]) if q.get("ap") else None,
            bid_size=int(q.get("bs", 0)),
            ask_size=int(q.get("as", 0)),
            quote_timestamp=qt.isoformat() if qt else None,
            raw_payload=q,
        )
    except Exception as e:
        log.debug(f"Alpaca quote {symbol} failed: {e}")
        return None


def fetch_alpaca_trade(symbol: str) -> dict:
    """Fetch latest trade from Alpaca for last price + volume."""
    api_key = os.getenv("ALPACA_API_KEY", "")
    secret_key = os.getenv("ALPACA_SECRET_KEY", "")
    if not api_key or not secret_key:
        return None
    try:
        import requests
        data_url = "https://data.alpaca.markets"
        headers = {
            "APCA-API-KEY-ID": api_key,
            "APCA-API-SECRET-KEY": secret_key,
        }
        resp = requests.get(
            f"{data_url}/v2/stocks/{symbol}/trades/latest",
            headers=headers, timeout=10)
        if resp.status_code != 200:
            return None
        data = resp.json()
        t = data.get("trade", {})
        if not t:
            return None
        return {
            "last_price": float(t["p"]) if t.get("p") else None,
            "size": int(t.get("s", 0)),
            "timestamp": t.get("t"),
        }
    except Exception:
        return None


def fetch_alpaca_snapshot(symbol: str) -> dict:
    """Fetch Alpaca snapshot (combines quote + trade + volume)."""
    api_key = os.getenv("ALPACA_API_KEY", "")
    secret_key = os.getenv("ALPACA_SECRET_KEY", "")
    if not api_key or not secret_key:
        return None
    try:
        import requests
        data_url = "https://data.alpaca.markets"
        headers = {
            "APCA-API-KEY-ID": api_key,
            "APCA-API-SECRET-KEY": secret_key,
        }
        # feed=iex: the free Alpaca tier blocks the default SIP feed, so without this the snapshot
        # returns nothing and get_best_quote falls through to the day-stale finviz cache (the
        # "quote is 1022min old" approval block). IEX is the same free feed the intraday cron uses.
        resp = requests.get(
            f"{data_url}/v2/stocks/{symbol}/snapshot",
            headers=headers, params={"feed": "iex"}, timeout=10)
        if resp.status_code != 200:
            log.debug(f"Alpaca snapshot {symbol}: HTTP {resp.status_code}")
            return None
        data = resp.json()
        q = data.get("latestQuote", {})
        t = data.get("latestTrade", {})
        bar = data.get("dailyBar", {})
        ts = q.get("t") or t.get("t")
        qt = datetime.fromisoformat(ts.replace("Z", "+00:00")) if ts else None

        return _make_result(
            provider="alpaca", priority=1,
            last_price=float(t["p"]) if t.get("p") else None,
            bid=float(q["bp"]) if q.get("bp") else None,
            ask=float(q["ap"]) if q.get("ap") else None,
            bid_size=int(q.get("bs", 0)),
            ask_size=int(q.get("as", 0)),
            day_volume=int(bar.get("v", 0)) if bar.get("v") else None,
            vwap=float(bar.get("vw")) if bar.get("vw") else None,
            quote_timestamp=qt.isoformat() if qt else None,
            raw_payload=data,
        )
    except Exception as e:
        log.debug(f"Alpaca snapshot {symbol} failed: {e}")
        return None


# ── Provider 2: Schwab Trader API ──────────────────────────────────────────

def fetch_schwab_quote(symbol: str) -> dict:
    """READ-ONLY Schwab batch quote — extended-hours when account is linked."""
    sym = (symbol or "").upper()
    if not sym:
        return None
    try:
        import schwab_transport
        result = schwab_transport.get_quotes([sym])
        if not result or result.get("status") != "ok":
            return None
        quotes = result.get("quotes") or {}
        q = quotes.get(sym) or quotes.get(symbol)
        if not q:
            return None

        last = q.get("last")
        bid = q.get("bid")
        ask = q.get("ask")
        if last is None and bid is not None and ask is not None:
            last = round((float(bid) + float(ask)) / 2, 4)
        elif last is None and bid is not None:
            last = float(bid)
        if last is None or float(last) <= 0:
            return None

        qt = _parse_schwab_timestamp(q.get("updated"))
        return _make_result(
            provider="schwab", priority=2,
            last_price=float(last),
            bid=float(bid) if bid is not None else None,
            ask=float(ask) if ask is not None else None,
            day_volume=int(q["volume"]) if q.get("volume") else None,
            quote_timestamp=qt.isoformat() if qt else None,
            is_delayed=False,
            raw_payload=q,
        )
    except Exception as e:
        log.debug(f"Schwab quote {symbol} failed: {e}")
        return None


# ── Provider 3: Polygon ────────────────────────────────────────────────────

def fetch_polygon_quote(symbol: str) -> dict:
    api_key = os.getenv("POLYGON_API_KEY", "")
    if not api_key:
        return None
    try:
        import requests
        resp = requests.get(
            f"https://api.polygon.io/v2/snapshot/locale/us/markets/stocks/tickers/{symbol}",
            params={"apiKey": api_key}, timeout=10)
        if resp.status_code != 200:
            return None
        data = resp.json()
        ticker = data.get("ticker", {})
        if not ticker:
            return None
        lq = ticker.get("lastQuote", {})
        lt = ticker.get("lastTrade", {})
        day = ticker.get("day", {})
        ts = lq.get("t") or lt.get("t")
        qt = None
        if ts:
            # Polygon timestamps are nanoseconds
            try:
                qt = datetime.fromtimestamp(ts / 1e9, tz=timezone.utc)
            except Exception:
                pass

        return _make_result(
            provider="polygon", priority=2,
            last_price=float(lt["p"]) if lt.get("p") else float(day.get("c", 0)) or None,
            bid=float(lq["p"]) if lq.get("p") else None,
            ask=float(lq.get("P")) if lq.get("P") else None,
            bid_size=int(lq.get("s", 0)) if lq.get("s") else None,
            ask_size=int(lq.get("S", 0)) if lq.get("S") else None,
            day_volume=int(day.get("v", 0)) if day.get("v") else None,
            vwap=float(day.get("vw")) if day.get("vw") else None,
            quote_timestamp=qt.isoformat() if qt else None,
            raw_payload=ticker,
        )
    except Exception as e:
        log.debug(f"Polygon quote {symbol} failed: {e}")
        return None


# ── Provider 4: Finnhub ────────────────────────────────────────────────────

def fetch_finnhub_quote(symbol: str) -> dict:
    api_key = os.getenv("FINNHUB_API_KEY", "")
    if not api_key:
        return None
    try:
        import requests
        resp = requests.get(
            "https://finnhub.io/api/v1/quote",
            params={"symbol": symbol, "token": api_key}, timeout=10)
        if resp.status_code != 200:
            return None
        data = resp.json()
        if not data.get("c"):
            return None
        ts = data.get("t")
        qt = datetime.fromtimestamp(ts, tz=timezone.utc) if ts else None
        return _make_result(
            provider="finnhub", priority=3,
            last_price=float(data["c"]),
            day_volume=None,  # Finnhub quote doesn't include volume
            quote_timestamp=qt.isoformat() if qt else None,
            is_delayed=True,  # Finnhub free tier is 15-min delayed
            raw_payload=data,
        )
    except Exception as e:
        log.debug(f"Finnhub quote {symbol} failed: {e}")
        return None


# ── Provider 5: FMP ────────────────────────────────────────────────────────

def fetch_fmp_quote(symbol: str) -> dict:
    api_key = os.getenv("FMP_API_KEY", "")
    if not api_key:
        return None
    try:
        import requests
        resp = requests.get(
            f"https://financialmodelingprep.com/api/v3/quote-short/{symbol}",
            params={"apikey": api_key}, timeout=10)
        if resp.status_code != 200:
            return None
        data = resp.json()
        if not data or not isinstance(data, list) or not data[0].get("price"):
            return None
        q = data[0]
        return _make_result(
            provider="fmp", priority=4,
            last_price=float(q["price"]),
            day_volume=int(q.get("volume", 0)) if q.get("volume") else None,
            is_delayed=True,
            raw_payload=q,
        )
    except Exception as e:
        log.debug(f"FMP quote {symbol} failed: {e}")
        return None


# ── Provider 6: yfinance ───────────────────────────────────────────────────

def fetch_yfinance_quote(symbol: str) -> dict:
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        info = ticker.fast_info
        last_price = float(info.get("lastPrice", 0) or info.get("last_price", 0))
        if not last_price:
            return None
        day_volume = int(info.get("lastVolume", 0) or 0)
        return _make_result(
            provider="yfinance", priority=5,
            last_price=last_price,
            day_volume=day_volume if day_volume > 0 else None,
            quote_timestamp=datetime.now(timezone.utc).isoformat(),
            is_delayed=True,
            raw_payload={"last_price": last_price, "volume": day_volume},
        )
    except Exception as e:
        log.debug(f"yfinance quote {symbol} failed: {e}")
        return None


# ── Provider 7: Finviz cache (display-only) ────────────────────────────────

def fetch_finviz_cache(symbol: str) -> dict:
    if not FINVIZ_CACHE_PATH.exists():
        return None
    try:
        cache = json.loads(FINVIZ_CACHE_PATH.read_text())
        q = cache.get(symbol)
        if not q or not q.get("price"):
            return None
        return _make_result(
            provider="finviz_cache", priority=6,
            last_price=float(q["price"]),
            day_volume=int(q.get("volume", 0)) if q.get("volume") else None,
            quote_timestamp=q.get("last_updated"),
            is_delayed=True,
            raw_payload=q,
        )
    except Exception:
        return None


# ── Orchestrator ───────────────────────────────────────────────────────────

PROVIDER_CHAIN = [
    ("alpaca", fetch_alpaca_snapshot),
    ("schwab", fetch_schwab_quote),
    ("polygon", fetch_polygon_quote),
    ("finnhub", fetch_finnhub_quote),
    ("fmp", fetch_fmp_quote),
    ("yfinance", fetch_yfinance_quote),
    ("finviz_cache", fetch_finviz_cache),
]


def quote_age_minutes(quote: dict) -> float | None:
    """Age of quote in minutes from quote_timestamp. None if unknown."""
    ts = (quote or {}).get("quote_timestamp")
    if ts is None:
        return None
    try:
        if isinstance(ts, (int, float)):
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        elif hasattr(ts, "timestamp"):
            dt = ts if getattr(ts, "tzinfo", None) else ts.replace(tzinfo=timezone.utc)
        else:
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 60.0)
    except Exception:
        return None


def check_fresh_quote(symbol: str, *, max_age_minutes: float | None = None,
                      strategy_id: str | None = None) -> dict:
    """Verify a live quote exists and is current (after-hours OK if fresh).

    When strategy_id is set, max_age relaxes to 24h for swing/position outside
    regular session — but only if the quote came from a real-time broker feed
    (Schwab/Alpaca/Polygon). Intraday strategies always require ≤15 min.

    Returns {ok, reason, quote, age_minutes, last_price, max_age_minutes, provider}.
    """
    sym = (symbol or "").upper()
    from market_session import current_market_session
    session = current_market_session()
    if max_age_minutes is None:
        max_age_minutes = resolve_quote_max_age_minutes(strategy_id, session=session)

    try:
        q = get_best_quote(sym) or {}
    except Exception as exc:
        return {"ok": False, "reason": f"quote_error: {exc}", "quote": {}, "age_minutes": None,
                "last_price": None, "max_age_minutes": max_age_minutes, "provider": None,
                "market_session": session}

    provider = q.get("provider") or ""
    last = q.get("last_price")
    if last is None or float(last) <= 0:
        return {"ok": False, "reason": "no_valid_price", "quote": q, "age_minutes": None,
                "last_price": None, "max_age_minutes": max_age_minutes, "provider": provider,
                "market_session": session}

    # Outside RTH with relaxed ceiling: delayed caches must not pass
    if max_age_minutes > INTRADAY_MAX_AGE_MINUTES and session != "regular":
        if provider not in REALTIME_PROVIDERS:
            return {
                "ok": False,
                "reason": f"afterhours_requires_realtime_provider (got {provider})",
                "quote": q, "age_minutes": quote_age_minutes(q), "last_price": last,
                "max_age_minutes": max_age_minutes, "provider": provider,
                "market_session": session,
            }

    age = quote_age_minutes(q)
    if age is None:
        # Provider returned price but no timestamp — accept if from real-time providers only
        if provider in REALTIME_PROVIDERS:
            return {"ok": True, "reason": "ok_no_timestamp", "quote": q, "age_minutes": None,
                    "last_price": last, "max_age_minutes": max_age_minutes, "provider": provider,
                    "market_session": session}
        return {"ok": False, "reason": "quote_timestamp_missing", "quote": q, "age_minutes": None,
                "last_price": last, "max_age_minutes": max_age_minutes, "provider": provider,
                "market_session": session}

    if age > max_age_minutes:
        return {
            "ok": False,
            "reason": f"quote_stale_{age:.0f}min",
            "quote": q,
            "age_minutes": age,
            "last_price": last,
            "max_age_minutes": max_age_minutes,
            "provider": provider,
            "market_session": session,
        }

    return {"ok": True, "reason": "ok", "quote": q, "age_minutes": age, "last_price": last,
            "max_age_minutes": max_age_minutes, "provider": provider, "market_session": session}


def _normalize_provider_result(result: dict, name: str) -> dict | None:
    """Ensure result has last_price; return None if unusable."""
    if not result:
        return None
    if result.get("last_price") is None and result.get("bid") is not None:
        if result.get("ask"):
            result["last_price"] = round((result["bid"] + result["ask"]) / 2, 4)
        else:
            result["last_price"] = result["bid"]
    if result.get("last_price") is None:
        return None
    result.setdefault("provider", name)
    return result


def _quote_sort_key(quote: dict) -> tuple:
    """Prefer real-time providers, then freshest timestamp, then priority."""
    provider = quote.get("provider") or ""
    is_rt = provider in REALTIME_PROVIDERS
    age = quote_age_minutes(quote)
    age_key = age if age is not None else 999999.0
    priority = quote.get("provider_priority") or 99
    return (0 if is_rt else 1, age_key, priority)


def get_best_quote(symbol: str) -> dict:
    """Try each provider; return freshest real-time quote (Schwab beats stale Alpaca after hours)."""
    tried = []
    candidates = []
    for name, fetcher in PROVIDER_CHAIN:
        try:
            result = _normalize_provider_result(fetcher(symbol), name)
            if result:
                candidates.append(result)
            else:
                tried.append(name)
        except Exception as e:
            tried.append(f"{name}:error")
            log.debug(f"Provider {name} failed for {symbol}: {e}")

    if candidates:
        best = min(candidates, key=_quote_sort_key)
        best["providers_tried"] = tried + [best.get("provider", "?")]
        if len(candidates) > 1:
            best["providers_considered"] = [c.get("provider") for c in candidates]
        return best

    return {
        "provider": "none",
        "provider_priority": 99,
        "last_price": None,
        "bid": None, "ask": None,
        "spread": None, "spread_pct": None,
        "day_volume": None,
        "quote_timestamp": None,
        "is_delayed": True,
        "is_execution_eligible": False,
        "providers_tried": tried,
        "raw_payload": {},
    }


def store_quote(conn, symbol: str, quote: dict) -> int:
    """Store quote snapshot in market_quote_snapshots. Returns snapshot id."""
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO market_quote_snapshots
            (symbol, provider, provider_priority, quote_timestamp,
             last_price, bid, ask, bid_size, ask_size,
             spread, spread_pct, day_volume, minute_volume, vwap,
             is_delayed, is_execution_eligible, raw_payload)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
    """, [
        symbol, quote.get("provider"), quote.get("provider_priority"),
        quote.get("quote_timestamp"),
        quote.get("last_price"), quote.get("bid"), quote.get("ask"),
        quote.get("bid_size"), quote.get("ask_size"),
        quote.get("spread"), quote.get("spread_pct"),
        quote.get("day_volume"), quote.get("minute_volume"),
        quote.get("vwap"),
        quote.get("is_delayed", True),
        quote.get("is_execution_eligible", False),
        json.dumps(quote.get("raw_payload", {}), default=str),
    ])
    snapshot_id = cur.fetchone()[0]
    conn.commit()
    return snapshot_id


def get_pending_symbols(conn) -> list:
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT symbol FROM paper_trade_proposals WHERE status='PENDING' ORDER BY symbol")
    return [r[0] for r in cur.fetchall()]


def main():
    parser = argparse.ArgumentParser(description="Market quote provider")
    parser.add_argument("--symbol", type=str)
    parser.add_argument("--symbols", type=str, help="Comma-separated symbols")
    parser.add_argument("--pending-proposals", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    conn = get_conn()
    try:
        if args.pending_proposals:
            symbols = get_pending_symbols(conn)
        elif args.symbols:
            symbols = [s.strip().upper() for s in args.symbols.split(",")]
        elif args.symbol:
            symbols = [args.symbol.upper()]
        else:
            print("Usage: --symbol TICK or --pending-proposals or --symbols A,B,C")
            return

        log.info(f"Fetching quotes for {len(symbols)} symbols: {symbols}")
        results = []
        for sym in symbols:
            q = get_best_quote(sym)
            if args.apply and q.get("provider") != "none":
                sid = store_quote(conn, sym, q)
                q["snapshot_id"] = sid
            log.info(f"  {sym}: provider={q.get('provider')} price={q.get('last_price')} "
                     f"bid={q.get('bid')} ask={q.get('ask')} exec={q.get('is_execution_eligible')} "
                     f"vol={q.get('day_volume')}")
            results.append({"symbol": sym, **q})

        print(json.dumps({"symbols": len(results), "results": results}, indent=2, default=str))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
