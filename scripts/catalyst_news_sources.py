"""
catalyst_news_sources.py — Trade AI v12
Unified catalyst news dispatcher — live sources in priority order.

Round-robin source priority:
  1. Finviz News    (FINVIZ_API_TOKEN — news_export.ashx)
  2. Yahoo Finance  (no key needed — public RSS/JSON)

Finnhub, NewsAPI, Polygon and FMP were retired 2026-09-13 — see
config/data_source_authority.json. Backups beyond these two are the governed
search chain (Brave → SearXNG), declared there, not here.

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

# Retired slots (finnhub, newsapi, polygon, fmp) were removed 2026-09-13: Finnhub
# had returned HTTP 401 since 07-27, NewsAPI never ran, Polygon and FMP went
# paid-only. Four dead slots sat in front of the two live ones and every
# scheduled caller fell through them. config/data_source_authority.json is the
# authority; scripts/check_data_source_authority.py fails if one comes back.
_SOURCES: list[tuple[str, Callable]] = [
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
    Fetch catalyst news for `ticker` using the live-source round-robin.

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
