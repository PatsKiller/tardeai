"""
catalyst_news_sources.py — Trade AI v12
Unified catalyst news dispatcher — all 6 sources in priority order.

Round-robin source priority:
  1. Finnhub       (FINNHUB_API_KEY)
  2. NewsAPI        (NEWSAPI_KEY)
  3. Polygon        (POLYGON_API_KEY)
  4. FMP            (FMP_API_KEY)
  5. Finviz News    (FINVIZ_API_TOKEN — news_export.ashx)  ← NEW
  6. Yahoo Finance  (no key needed — public RSS/JSON)       ← NEW

Usage in catalyst_enrichment.py — replace your existing news fetch call with:

    from scripts.catalyst_news_sources import fetch_catalyst_news
    articles = fetch_catalyst_news(ticker, lookback_hours=72)

fetch_catalyst_news() returns the first source that yields ≥1 fresh article,
then stops (same logic as before, now with 2 extra fallbacks).

For bulk enrichment use fetch_catalyst_news_bulk() which respects max_tickers.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Callable, Optional

import requests
from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger(__name__)

# ── API Keys ──────────────────────────────────────────────────────────────────
FINNHUB_KEY: str = os.getenv("FINNHUB_API_KEY", "").strip()
NEWSAPI_KEY: str = os.getenv("NEWSAPI_KEY", "").strip()
POLYGON_KEY: str = os.getenv("POLYGON_API_KEY", "").strip()
FMP_KEY: str = os.getenv("FMP_API_KEY", "").strip()
FINVIZ_TOKEN: str = os.getenv("FINVIZ_API_TOKEN", "").strip()
YAHOO_ENABLED: bool = os.getenv("YAHOO_NEWS_ENABLED", "true").lower() == "true"
FINVIZ_NEWS_ENABLED: bool = os.getenv("FINVIZ_NEWS_ENABLED", "true").lower() == "true"

# Lookback
DEFAULT_LOOKBACK_HOURS: int = 72
REQUEST_TIMEOUT: int = 10


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _now_ts() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def _is_fresh(pub_ts: int, lookback_hours: int) -> bool:
    return pub_ts >= (_now_ts() - lookback_hours * 3600)


def _get_json(url: str, params: dict = None, headers: dict = None) -> Optional[dict | list]:
    try:
        r = requests.get(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT)
        if r.status_code == 200:
            return r.json()
        log.debug("HTTP %d from %s", r.status_code, url)
    except Exception as exc:
        log.debug("Request error %s: %s", url, exc)
    return None


def _standardize(
    headline: str,
    url: str,
    pub_ts: int,
    source: str,
    ticker: str,
    lookback_hours: int,
) -> dict:
    return {
        "headline": headline,
        "source": source,
        "url": url,
        "datetime": pub_ts,
        "ticker": ticker,
        "is_fresh": _is_fresh(pub_ts, lookback_hours),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Source 1: Finnhub
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_finnhub(ticker: str, lookback_hours: int) -> list[dict]:
    if not FINNHUB_KEY:
        return []
    from_ts = _now_ts() - lookback_hours * 3600
    to_ts = _now_ts()
    data = _get_json(
        "https://finnhub.io/api/v1/company-news",
        params={
            "symbol": ticker,
            "from": datetime.fromtimestamp(from_ts).strftime("%Y-%m-%d"),
            "to": datetime.fromtimestamp(to_ts).strftime("%Y-%m-%d"),
            "token": FINNHUB_KEY,
        },
    )
    if not isinstance(data, list):
        return []
    articles = []
    for item in data:
        headline = item.get("headline", "").strip()
        if not headline:
            continue
        articles.append(_standardize(
            headline=headline,
            url=item.get("url", ""),
            pub_ts=item.get("datetime", 0),
            source="finnhub",
            ticker=ticker,
            lookback_hours=lookback_hours,
        ))
    return articles


# ─────────────────────────────────────────────────────────────────────────────
# Source 2: NewsAPI
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_newsapi(ticker: str, lookback_hours: int) -> list[dict]:
    if not NEWSAPI_KEY:
        return []
    from_dt = datetime.fromtimestamp(_now_ts() - lookback_hours * 3600, tz=timezone.utc)
    data = _get_json(
        "https://newsapi.org/v2/everything",
        params={
            "q": ticker,
            "from": from_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "sortBy": "publishedAt",
            "language": "en",
            "pageSize": 10,
            "apiKey": NEWSAPI_KEY,
        },
    )
    try:
        from lib.data_source_report import report_source
        report_source("newsapi", isinstance(data, dict),
                      error=None if isinstance(data, dict) else "no/invalid response")
    except Exception:
        pass
    if not isinstance(data, dict):
        return []
    articles = []
    for item in data.get("articles", []):
        headline = item.get("title", "").strip()
        if not headline or headline == "[Removed]":
            continue
        pub_str = item.get("publishedAt", "")
        try:
            pub_ts = int(datetime.strptime(pub_str, "%Y-%m-%dT%H:%M:%SZ")
                        .replace(tzinfo=timezone.utc).timestamp())
        except Exception:
            pub_ts = 0
        articles.append(_standardize(
            headline=headline,
            url=item.get("url", ""),
            pub_ts=pub_ts,
            source="newsapi",
            ticker=ticker,
            lookback_hours=lookback_hours,
        ))
    return articles


# ─────────────────────────────────────────────────────────────────────────────
# Source 3: Polygon
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_polygon(ticker: str, lookback_hours: int) -> list[dict]:
    if not POLYGON_KEY:
        return []
    from_dt = datetime.fromtimestamp(_now_ts() - lookback_hours * 3600, tz=timezone.utc)
    data = _get_json(
        f"https://api.polygon.io/v2/reference/news",
        params={
            "ticker": ticker,
            "published_utc.gte": from_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "order": "desc",
            "limit": 10,
            "apiKey": POLYGON_KEY,
        },
    )
    if not isinstance(data, dict):
        return []
    articles = []
    for item in data.get("results", []):
        headline = item.get("title", "").strip()
        if not headline:
            continue
        pub_str = item.get("published_utc", "")
        try:
            pub_ts = int(datetime.strptime(pub_str[:19], "%Y-%m-%dT%H:%M:%S")
                        .replace(tzinfo=timezone.utc).timestamp())
        except Exception:
            pub_ts = 0
        articles.append(_standardize(
            headline=headline,
            url=item.get("article_url", ""),
            pub_ts=pub_ts,
            source="polygon",
            ticker=ticker,
            lookback_hours=lookback_hours,
        ))
    return articles


# ─────────────────────────────────────────────────────────────────────────────
# Source 4: FMP
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_fmp(ticker: str, lookback_hours: int) -> list[dict]:
    if not FMP_KEY:
        return []
    data = _get_json(
        f"https://financialmodelingprep.com/api/v3/stock_news",
        params={
            "tickers": ticker,
            "limit": 10,
            "apikey": FMP_KEY,
        },
    )
    if not isinstance(data, list):
        return []
    articles = []
    for item in data:
        headline = item.get("title", "").strip()
        if not headline:
            continue
        pub_str = item.get("publishedDate", "")
        try:
            pub_ts = int(datetime.strptime(pub_str[:19], "%Y-%m-%d %H:%M:%S")
                        .replace(tzinfo=timezone.utc).timestamp())
        except Exception:
            pub_ts = 0
        if not _is_fresh(pub_ts, lookback_hours):
            continue
        articles.append(_standardize(
            headline=headline,
            url=item.get("url", ""),
            pub_ts=pub_ts,
            source="fmp",
            ticker=ticker,
            lookback_hours=lookback_hours,
        ))
    return articles


# ─────────────────────────────────────────────────────────────────────────────
# Source 5: Finviz News (NEW)
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_finviz_news(ticker: str, lookback_hours: int) -> list[dict]:
    if not FINVIZ_NEWS_ENABLED or not FINVIZ_TOKEN:
        return []
    try:
        from scripts.finviz_news import fetch_finviz_news
        return fetch_finviz_news(ticker, lookback_hours=lookback_hours)
    except ImportError:
        log.warning("[catalyst] finviz_news module not found")
        return []


# ─────────────────────────────────────────────────────────────────────────────
# Source 6: Yahoo Finance (NEW)
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_yahoo(ticker: str, lookback_hours: int) -> list[dict]:
    if not YAHOO_ENABLED:
        return []
    try:
        from scripts.yahoo_news import fetch_yahoo_news
        return fetch_yahoo_news(ticker, lookback_hours=lookback_hours)
    except ImportError:
        log.warning("[catalyst] yahoo_news module not found")
        return []


# ─────────────────────────────────────────────────────────────────────────────
# Source registry — order = priority
# ─────────────────────────────────────────────────────────────────────────────

_SOURCES: list[tuple[str, Callable]] = [
    ("finnhub",      _fetch_finnhub),
    ("newsapi",      _fetch_newsapi),
    ("polygon",      _fetch_polygon),
    ("fmp",          _fetch_fmp),
    ("finviz_news",  _fetch_finviz_news),   # NEW — slot 5
    ("yahoo",        _fetch_yahoo),         # NEW — slot 6
]


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def fetch_catalyst_news(
    ticker: str,
    lookback_hours: int = DEFAULT_LOOKBACK_HOURS,
    require_fresh: bool = True,
) -> list[dict]:
    """
    Fetch catalyst news for `ticker` using the 6-source round-robin.

    Tries each source in priority order and returns the first that yields
    ≥1 article (or ≥1 fresh article if require_fresh=True).

    Returns [] only if ALL sources fail / return nothing.
    """
    ticker = ticker.upper().strip()
    source_results: dict[str, int] = {}

    for source_name, fetch_fn in _SOURCES:
        try:
            articles = fetch_fn(ticker, lookback_hours)
            source_results[source_name] = len(articles)

            if not articles:
                continue

            fresh = [a for a in articles if a.get("is_fresh")]

            if require_fresh and not fresh:
                log.debug("[catalyst] %s/%s — %d articles, 0 fresh → trying next source",
                          ticker, source_name, len(articles))
                continue

            used = fresh if (require_fresh and fresh) else articles
            log.info(
                "[catalyst] %s — source: %-12s | %d articles | %d fresh",
                ticker, source_name, len(articles), len(fresh),
            )
            return used

        except Exception as exc:
            log.warning("[catalyst] %s/%s error: %s", ticker, source_name, exc)
            source_results[source_name] = 0

    log.warning(
        "[catalyst] %s — ALL sources exhausted. Results: %s",
        ticker,
        " | ".join(f"{k}:{v}" for k, v in source_results.items()),
    )
    return []


def fetch_catalyst_news_bulk(
    tickers: list[str],
    lookback_hours: int = DEFAULT_LOOKBACK_HOURS,
    max_tickers: int = 100,
    delay_between: float = 0.2,
) -> dict[str, list[dict]]:
    """
    Fetch catalyst news for a list of tickers (up to max_tickers).

    Returns dict of ticker → articles list.
    """
    results: dict[str, list[dict]] = {}
    batch = tickers[:max_tickers]
    log.info("[catalyst] bulk fetch — %d tickers", len(batch))

    for i, ticker in enumerate(batch):
        results[ticker] = fetch_catalyst_news(ticker, lookback_hours=lookback_hours)
        if delay_between > 0 and i < len(batch) - 1:
            time.sleep(delay_between)

    total_articles = sum(len(v) for v in results.values())
    total_fresh = sum(
        sum(1 for a in v if a.get("is_fresh"))
        for v in results.values()
    )
    log.info(
        "[catalyst] bulk complete — %d tickers | %d articles total | %d fresh",
        len(results), total_articles, total_fresh,
    )
    return results


def get_source_summary(results: dict[str, list[dict]]) -> str:
    """Return a one-line summary of which sources contributed data."""
    source_counts: dict[str, int] = {}
    for articles in results.values():
        for a in articles:
            src = a.get("source", "unknown")
            source_counts[src] = source_counts.get(src, 0) + 1
    return " | ".join(f"{k}:{v}" for k, v in sorted(source_counts.items()))


# ─────────────────────────────────────────────────────────────────────────────
# Standalone test
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%H:%M:%S",
    )

    tickers = sys.argv[1:] if len(sys.argv) > 1 else ["NVDA", "AAPL", "TSLA"]
    print(f"\n=== Catalyst News Sources Test — {tickers} ===\n")
    print(f"  Sources configured:")
    for name, fn in _SOURCES:
        print(f"    {'✅' if True else '❌'}  {name}")
    print()

    for ticker in tickers:
        print(f"── {ticker} ─────────────────")
        articles = fetch_catalyst_news(ticker, lookback_hours=72)
        if articles:
            for a in articles[:3]:
                ts = datetime.fromtimestamp(a["datetime"]).strftime("%m/%d %H:%M") if a["datetime"] else "?"
                print(f"  [{a['source']:15s}] [{ts}] {a['headline'][:70]}")
        else:
            print("  (no articles)")
        print()
