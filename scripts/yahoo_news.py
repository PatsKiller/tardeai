"""
yahoo_news.py — Trade AI v12
Yahoo Finance news headlines — 5th fallback in the catalyst round-robin.

No API key required. Uses the public Yahoo Finance search/quote JSON endpoint.
Falls back gracefully on any network or parse error.

Public API:
    fetch_yahoo_news(ticker, lookback_hours=72) → list[dict]

Each dict:
    headline    str
    source      str   ("yahoo_finance")
    url         str
    datetime    int   (Unix timestamp — providerPublishTime)
    ticker      str
    is_fresh    bool
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
YAHOO_NEWS_ENABLED: bool = os.getenv("YAHOO_NEWS_ENABLED", "true").lower() == "true"

# Public Yahoo Finance endpoints (no key needed)
YAHOO_SEARCH_URL = "https://query1.finance.yahoo.com/v1/finance/search"
YAHOO_QUOTE_URL = "https://query2.finance.yahoo.com/v10/finance/quoteSummary/{ticker}"

REQUEST_TIMEOUT = 10
REQUEST_DELAY = 0.3

# Rotate between query1 and query2 hosts to reduce rate-limit risk
_HOSTS = [
    "https://query1.finance.yahoo.com",
    "https://query2.finance.yahoo.com",
]
_host_idx = 0

# Internal cache
_cache: dict[str, tuple[float, list[dict]]] = {}
CACHE_TTL = 900  # 15 minutes


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _next_host() -> str:
    global _host_idx
    host = _HOSTS[_host_idx % len(_HOSTS)]
    _host_idx += 1
    return host


def _now_ts() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def _is_fresh(pub_ts: int, lookback_hours: int) -> bool:
    cutoff = _now_ts() - (lookback_hours * 3600)
    return pub_ts >= cutoff


def _build_headers() -> dict:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://finance.yahoo.com/",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Fetch strategies
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_via_search(ticker: str, lookback_hours: int) -> list[dict]:
    """
    Strategy A: /v1/finance/search — fast, returns up to ~8 headlines.
    """
    host = _next_host()
    url = f"{host}/v1/finance/search"
    params = {
        "q": ticker,
        "newsCount": 10,
        "quotesCount": 0,
        "enableFuzzyQuery": False,
        "enableCb": False,
    }

    try:
        r = requests.get(url, params=params, headers=_build_headers(), timeout=REQUEST_TIMEOUT)
        if r.status_code != 200:
            log.debug("[yahoo_news] search endpoint HTTP %d for %s", r.status_code, ticker)
            return []

        data = r.json()
        raw_news = data.get("news", [])
        return _parse_news_items(raw_news, ticker, lookback_hours, "yahoo_search")

    except Exception as exc:
        log.debug("[yahoo_news] search strategy failed for %s: %s", ticker, exc)
        return []


def _fetch_via_quote_summary(ticker: str, lookback_hours: int) -> list[dict]:
    """
    Strategy B: /v10/finance/quoteSummary — broader coverage, up to ~20 headlines.
    """
    host = _next_host()
    url = f"{host}/v10/finance/quoteSummary/{ticker}"
    params = {"modules": "topHoldings,assetProfile,upgradeDowngradeHistory,recommendationTrend"}

    # Use a separate news-focused module
    url_news = f"{host}/v10/finance/quoteSummary/{ticker}"
    params_news = {"modules": "summaryProfile"}  # pivot: try topHoldings

    # Actually use the simpler v11 endpoint
    url_v11 = f"{host}/v11/finance/quoteSummary/{ticker}"
    params_v11 = {"modules": "topHoldings"}

    # Best public endpoint for news is actually the search API
    # Fall back to RSS as last resort
    rss_url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US"

    try:
        r = requests.get(rss_url, headers=_build_headers(), timeout=REQUEST_TIMEOUT)
        if r.status_code != 200:
            return []

        # Parse RSS XML
        import xml.etree.ElementTree as ET
        root = ET.fromstring(r.content)
        ns = {"media": "http://search.yahoo.com/mrss/"}
        items = root.findall(".//item")

        articles = []
        for item in items[:20]:
            title_el = item.find("title")
            link_el = item.find("link")
            pubdate_el = item.find("pubDate")

            headline = title_el.text.strip() if title_el is not None and title_el.text else ""
            link = link_el.text.strip() if link_el is not None and link_el.text else ""
            pub_str = pubdate_el.text.strip() if pubdate_el is not None and pubdate_el.text else ""

            if not headline:
                continue

            pub_ts = 0
            try:
                from email.utils import parsedate_to_datetime
                pub_ts = int(parsedate_to_datetime(pub_str).timestamp())
            except Exception:
                pass

            articles.append({
                "headline": headline,
                "source": "yahoo_finance",
                "url": link,
                "datetime": pub_ts,
                "ticker": ticker,
                "is_fresh": _is_fresh(pub_ts, lookback_hours) if pub_ts else False,
            })

        return articles

    except Exception as exc:
        log.debug("[yahoo_news] RSS strategy failed for %s: %s", ticker, exc)
        return []


def _parse_news_items(
    raw_news: list,
    ticker: str,
    lookback_hours: int,
    source_tag: str,
) -> list[dict]:
    """Convert Yahoo API news items to standard article dicts."""
    articles = []
    for item in raw_news:
        if not isinstance(item, dict):
            continue
        headline = item.get("title", "").strip()
        url = item.get("link", "").strip()
        pub_ts = item.get("providerPublishTime", 0)

        if not headline:
            continue

        articles.append({
            "headline": headline,
            "source": "yahoo_finance",
            "url": url,
            "datetime": pub_ts,
            "ticker": ticker,
            "is_fresh": _is_fresh(pub_ts, lookback_hours),
        })
    return articles


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def fetch_yahoo_news(
    ticker: str,
    lookback_hours: int = 72,
    use_cache: bool = True,
) -> list[dict]:
    """
    Fetch news headlines for `ticker` from Yahoo Finance.
    No API key needed.

    Tries two strategies:
      1. /v1/finance/search  (fast, JSON)
      2. RSS feed            (fallback, broader history)

    Returns a deduplicated list, newest first.
    """
    if not YAHOO_NEWS_ENABLED:
        return []

    ticker = ticker.upper().strip()
    cache_key = f"yahoo:{ticker}:{lookback_hours}"

    # ── Cache check ───────────────────────────────────────────────────────────
    if use_cache and cache_key in _cache:
        cached_ts, cached_articles = _cache[cache_key]
        if time.time() - cached_ts < CACHE_TTL:
            log.debug("[yahoo_news] %s — cache hit", ticker)
            return cached_articles

    # ── Strategy A: search API ────────────────────────────────────────────────
    articles = _fetch_via_search(ticker, lookback_hours)
    time.sleep(REQUEST_DELAY)

    # ── Strategy B: RSS if search returned nothing ────────────────────────────
    if not articles:
        articles = _fetch_via_quote_summary(ticker, lookback_hours)
        time.sleep(REQUEST_DELAY)

    # Deduplicate by headline
    seen: set[str] = set()
    unique = []
    for a in articles:
        key = a["headline"].lower()[:80]
        if key not in seen:
            seen.add(key)
            unique.append(a)

    # Sort newest first
    unique.sort(key=lambda x: x["datetime"], reverse=True)

    # Cache result
    _cache[cache_key] = (time.time(), unique)

    fresh_count = sum(1 for a in unique if a["is_fresh"])
    if unique:
        log.info(
            "[yahoo_news] %s — %d articles | %d fresh",
            ticker, len(unique), fresh_count,
        )
    else:
        log.debug("[yahoo_news] %s — no articles returned", ticker)

    return unique


def fetch_yahoo_news_batch(
    tickers: list[str],
    lookback_hours: int = 72,
    max_tickers: int = 50,
) -> dict[str, list[dict]]:
    """Fetch Yahoo news for a list of tickers."""
    results: dict[str, list[dict]] = {}
    for ticker in tickers[:max_tickers]:
        results[ticker] = fetch_yahoo_news(ticker, lookback_hours=lookback_hours)
    return results


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

    ticker = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    print(f"\n=== Yahoo Finance News Test — {ticker} ===\n")
    articles = fetch_yahoo_news(ticker, lookback_hours=72)

    if not articles:
        print("No articles returned.")
    else:
        for a in articles[:10]:
            ts = datetime.fromtimestamp(a["datetime"]).strftime("%m/%d %H:%M") if a["datetime"] else "?"
            fresh = "✅" if a["is_fresh"] else "  "
            print(f"  {fresh} [{ts}] {a['headline'][:80]}")
        print(f"\n  Total: {len(articles)} articles")
