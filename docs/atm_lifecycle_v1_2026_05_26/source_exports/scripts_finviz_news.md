# Source Export: scripts/finviz_news.py

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/finviz_news.py` |
| **Git Branch** | `main` |
| **Git Commit** | `915876f` |
| **Export Timestamp** | `2026-05-26T19:48:00Z` |
| **SHA256** | `c29cf474a0b4eaee80f4309366c86dcfca050298cfc28ab24e605a1e101209f0` |
| **File Size** | 9297 bytes |

## Full Source

```py
"""
finviz_news.py — Trade AI v12
Fetch ticker-specific news headlines from Finviz Elite news_export.ashx.

Uses the same FINVIZ_API_TOKEN as screener ingestion — no extra credentials.
Acts as a high-quality, low-latency catalyst source wired into the
catalyst_news_sources round-robin before Yahoo Finance.

Public API:
    fetch_finviz_news(ticker, lookback_hours=72) → list[dict]

Each dict contains:
    headline    str
    source      str   ("finviz_news")
    url         str
    datetime    int   (Unix timestamp)
    ticker      str
    is_fresh    bool  (published within lookback_hours)
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
FINVIZ_TOKEN: str = os.getenv("FINVIZ_API_TOKEN", "").strip()
FINVIZ_UA: str = os.getenv(
    "FINVIZ_USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
)
FINVIZ_NEWS_ENABLED: bool = os.getenv("FINVIZ_NEWS_ENABLED", "true").lower() == "true"

NEWS_BASE_URL = "https://elite.finviz.com/news_export.ashx"
REQUEST_TIMEOUT = 10
REQUEST_DELAY = 0.5   # seconds between requests (be polite to the API)

# ── Internal cache (per-process, per-run) ─────────────────────────────────────
_cache: dict[str, tuple[float, list[dict]]] = {}
CACHE_TTL = 1200  # 20 minutes


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _now_ts() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def _is_fresh(pub_ts: int, lookback_hours: int) -> bool:
    cutoff = _now_ts() - (lookback_hours * 3600)
    return pub_ts >= cutoff


def _parse_finviz_news_response(data: list, ticker: str, lookback_hours: int) -> list[dict]:
    """
    Parse Finviz news_export.ashx JSON response.

    Expected format (list of dicts):
        [{"date": "Apr-01-26 09:00AM", "headline": "...", "url": "...", "source": "..."}, ...]
    """
    articles = []
    for item in data:
        if not isinstance(item, dict):
            continue

        headline = item.get("headline") or item.get("title") or ""
        url = item.get("url") or item.get("link") or ""
        source_name = item.get("source") or "finviz"
        date_str = item.get("date") or item.get("datetime") or ""

        # Parse Finviz date strings like "Apr-01-26 09:00AM"
        pub_ts = 0
        for fmt in ("%b-%d-%y %I:%M%p", "%b-%d-%Y %I:%M%p", "%Y-%m-%d %H:%M:%S"):
            try:
                dt = datetime.strptime(date_str, fmt)
                # Finviz dates are US Eastern — store as naive UTC approx
                pub_ts = int(dt.replace(tzinfo=timezone.utc).timestamp())
                break
            except ValueError:
                continue

        if not headline:
            continue

        articles.append({
            "headline": headline,
            "source": "finviz_news",
            "original_source": source_name,
            "url": url,
            "datetime": pub_ts,
            "ticker": ticker,
            "is_fresh": _is_fresh(pub_ts, lookback_hours) if pub_ts else False,
        })

    return articles


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def fetch_finviz_news(
    ticker: str,
    lookback_hours: int = 72,
    use_cache: bool = True,
) -> list[dict]:
    """
    Fetch news headlines for `ticker` from Finviz news_export.ashx.

    Returns a list of article dicts, newest first, filtered to lookback_hours.
    Returns [] if disabled, token missing, or request fails.
    """
    if not FINVIZ_NEWS_ENABLED:
        return []

    if not FINVIZ_TOKEN:
        log.warning("[finviz_news] FINVIZ_API_TOKEN not set — skipping")
        return []

    ticker = ticker.upper().strip()

    # ── Cache check ───────────────────────────────────────────────────────────
    cache_key = f"{ticker}:{lookback_hours}"
    if use_cache and cache_key in _cache:
        cached_ts, cached_articles = _cache[cache_key]
        if time.time() - cached_ts < CACHE_TTL:
            log.debug("[finviz_news] %s — cache hit (%d articles)", ticker, len(cached_articles))
            return cached_articles

    # ── Request ───────────────────────────────────────────────────────────────
    url = f"{NEWS_BASE_URL}?t={ticker}&auth={FINVIZ_TOKEN}"
    headers = {
        "User-Agent": FINVIZ_UA,
        "Accept": "application/json,text/json,*/*",
    }

    try:
        r = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        time.sleep(REQUEST_DELAY)

        if r.status_code == 404:
            # No news for this ticker — normal, not an error
            log.debug("[finviz_news] %s — 404 (no news available)", ticker)
            return []

        if r.status_code != 200:
            log.warning("[finviz_news] %s — HTTP %d", ticker, r.status_code)
            return []

        # Try JSON parse first
        try:
            data = r.json()
            if not isinstance(data, list):
                data = data.get("news", data.get("articles", []))
        except Exception:
            # Some Finviz endpoints return newline-delimited JSON
            lines = [ln.strip() for ln in r.text.splitlines() if ln.strip().startswith("{")]
            import json
            data = []
            for ln in lines:
                try:
                    data.append(json.loads(ln))
                except Exception:
                    pass

        articles = _parse_finviz_news_response(data, ticker, lookback_hours)

        # Sort newest first
        articles.sort(key=lambda x: x["datetime"], reverse=True)

        # Cache result
        _cache[cache_key] = (time.time(), articles)

        fresh_count = sum(1 for a in articles if a["is_fresh"])
        log.info(
            "[finviz_news] %s — %d articles | %d fresh (≤%dh)",
            ticker, len(articles), fresh_count, lookback_hours,
        )
        return articles

    except requests.RequestException as exc:
        log.warning("[finviz_news] %s — request error: %s", ticker, exc)
        return []


def fetch_finviz_news_batch(
    tickers: list[str],
    lookback_hours: int = 72,
    max_tickers: int = 50,
) -> dict[str, list[dict]]:
    """
    Fetch news for a list of tickers (up to max_tickers).
    Returns dict of ticker → articles.
    """
    results: dict[str, list[dict]] = {}
    for ticker in tickers[:max_tickers]:
        results[ticker] = fetch_finviz_news(ticker, lookback_hours=lookback_hours)
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

    ticker = sys.argv[1] if len(sys.argv) > 1 else "NVDA"
    print(f"\n=== Finviz News Test — {ticker} ===\n")
    articles = fetch_finviz_news(ticker, lookback_hours=72)

    if not articles:
        print("No articles returned.")
    else:
        for i, a in enumerate(articles[:10], 1):
            ts = datetime.fromtimestamp(a["datetime"]).strftime("%m/%d %H:%M") if a["datetime"] else "unknown"
            fresh = "✅" if a["is_fresh"] else "  "
            print(f"  {fresh} [{ts}] {a['headline'][:80]}")
            print(f"       src: {a['original_source']}  url: {a['url'][:60]}")
            print()
```
