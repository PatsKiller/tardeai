"""
catalyst_news_sources.py — Trade AI v12
Unified catalyst news dispatcher — live sources in priority order.

Round-robin source priority:
  1. Finviz News    (FINVIZ_API_TOKEN — news_export.ashx)
  2. Yahoo Finance  (no key needed — public RSS/JSON)

Finnhub, NewsAPI, Polygon and FMP were retired 2026-09-13 — see
config/data_source_authority.json. Backups beyond these two are the governed
search chain (Brave → SearXNG), declared there, not here.

Search backup (Phase 5, 2026-09-13): when EVERY live slot returns zero fresh
articles, fetch_catalyst_news performs ONE governed headline pull through
scripts/lib/brave_router.search (kind="news", caller="catalyst_intelligence",
no_spill=False — so a Brave denial spills to SearXNG under its own budget).
Those rows carry source="search:<provider>" and is_fresh computed as usual from
the result's age. The receipt (pass ``receipt={}``) names which slot answered.
Never a search call when a live slot answered; the answer is then finviz/yahoo.

Usage in catalyst_enrichment.py — replace your existing news fetch call with:

    from scripts.catalyst_news_sources import fetch_catalyst_news
    articles = fetch_catalyst_news(ticker, lookback_hours=72)

fetch_catalyst_news() returns the first source that yields ≥1 fresh article,
then stops; only when both live slots are empty does the search backup run.

For bulk enrichment use fetch_catalyst_news_bulk() which respects max_tickers.
"""

from __future__ import annotations

import logging
import os
import re
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
# Source 1: Finviz News
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
# Source 2: Yahoo Finance
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
    ("finviz_news",  _fetch_finviz_news),   # slot 1
    ("yahoo",        _fetch_yahoo),         # slot 2
]


# ─────────────────────────────────────────────────────────────────────────────
# Backup: ONE governed headline pull through the search chain
# ─────────────────────────────────────────────────────────────────────────────

#: Budget caller key — search_budget.CALLER_DAILY_CAPS["catalyst_intelligence"] = 10/day.
SEARCH_CALLER = "catalyst_intelligence"
SEARCH_PURPOSE = "catalyst_backup"
SEARCH_RESULT_COUNT = 10

_AGE_RE = re.compile(
    r"^(\d+)\s*(minutes?|mins?|months?|mo|m|hours?|hrs?|h|days?|d|weeks?|wks?|w|years?|yrs?|y)\b"
)
_AGE_UNIT_SECONDS = {"mo": 2_592_000, "m": 60, "h": 3600, "d": 86400, "w": 604800, "y": 31_536_000}


def _age_to_ts(age, now_ts: Optional[int] = None) -> int:
    """A search result's age ("2 hours ago", "1d", ISO date) → epoch seconds.

    0 means unknown, and unknown is NOT fresh: ``_is_fresh(0, …)`` is False, so
    a headline whose date the engine did not report is carried but never counted
    as a fresh catalyst. SearXNG rarely reports one; Brave usually does.
    """
    s = str(age or "").strip().lower()
    if not s:
        return 0
    now_ts = now_ts if now_ts is not None else _now_ts()
    if s.startswith("just") or s in {"now", "today"}:
        return now_ts
    if s == "yesterday":
        return now_ts - 86400
    m = _AGE_RE.match(s)
    if m:
        unit = m.group(2)
        key = "mo" if unit.startswith("mo") else unit[0]
        return now_ts - int(m.group(1)) * _AGE_UNIT_SECONDS[key]
    try:
        dt = datetime.fromisoformat(str(age).strip().replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except Exception:
        return 0


def _governed_search(query: str, count: int = SEARCH_RESULT_COUNT):
    """The ONLY network path for the backup: brave_router.search, budget-checked,
    spilling to the registry's backup chain on a Brave denial (no_spill=False)."""
    try:
        from scripts.lib import brave_router
    except ImportError:
        from lib import brave_router  # type: ignore
    return brave_router.search(
        query, kind="news", count=count, caller=SEARCH_CALLER,
        purpose=SEARCH_PURPOSE, no_spill=False,
    )


def _search_backup(ticker: str, lookback_hours: int) -> tuple[list[dict], dict]:
    """One governed pull. Returns (rows, info); info.answered_by is "search:<provider>" or None."""
    query = f"{ticker} stock news"
    info: dict = {"query": query, "answered_by": None, "reason": None, "receipt": None}
    try:
        resp = _governed_search(query)
    except Exception as exc:
        info["reason"] = f"SEARCH_ERROR:{type(exc).__name__}:{exc}"
        return [], info
    info["reason"] = str(getattr(resp, "reason", "") or "")
    info["receipt"] = getattr(resp, "receipt", None)
    if not getattr(resp, "ok", False):
        return [], info
    default_provider = str(getattr(resp, "provider", "") or "brave")
    rows: list[dict] = []
    answered: Optional[str] = None
    for r in getattr(resp, "results", None) or []:
        if not isinstance(r, dict):
            continue
        headline, url = str(r.get("title") or "").strip(), str(r.get("url") or "").strip()
        if not headline or not url:
            continue
        provider = str(r.get("provider") or default_provider)
        answered = answered or f"search:{provider}"
        rows.append(_standardize(headline, url, _age_to_ts(r.get("age")),
                                 f"search:{provider}", ticker, lookback_hours))
    info["answered_by"] = answered or f"search:{default_provider}"
    return rows, info


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def fetch_catalyst_news(
    ticker: str,
    lookback_hours: int = DEFAULT_LOOKBACK_HOURS,
    require_fresh: bool = True,
    receipt: Optional[dict] = None,
) -> list[dict]:
    """
    Fetch catalyst news for `ticker` using the live-source round-robin.

    Tries each source in priority order and returns the first that yields
    ≥1 article (or ≥1 fresh article if require_fresh=True). Only when every
    live slot yields nothing usable does ONE governed search pull run
    (brave→searxng via brave_router); those rows are source="search:<provider>".

    ``receipt`` (a dict, filled in place) records per-slot counts and which slot
    answered — "finviz_news", "yahoo", "search:brave", "search:searxng" or None.

    Returns [] only if ALL sources, including the search backup, yield nothing.
    """
    ticker = ticker.upper().strip()
    source_results: dict[str, int] = {}
    if receipt is not None:
        receipt.update({"ticker": ticker, "live": source_results, "answered_by": None, "search": None})

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
            if receipt is not None:
                receipt["answered_by"] = source_name
            return used

        except Exception as exc:
            log.warning("[catalyst] %s/%s error: %s", ticker, source_name, exc)
            source_results[source_name] = 0

    # Every live slot came back empty (or stale). ONE governed pull through the
    # search chain — never reached when a live slot answered above.
    rows, info = _search_backup(ticker, lookback_hours)
    if receipt is not None:
        receipt["search"] = info
    fresh = [a for a in rows if a.get("is_fresh")]
    used = fresh if (require_fresh and fresh) else ([] if require_fresh else rows)
    if used:
        if receipt is not None:
            receipt["answered_by"] = info.get("answered_by")
        log.info(
            "[catalyst] %s — source: %-12s | %d articles | %d fresh (live slots: %s)",
            ticker, info.get("answered_by"), len(rows), len(fresh),
            " | ".join(f"{k}:{v}" for k, v in source_results.items()),
        )
        return used

    log.warning(
        "[catalyst] %s — ALL sources exhausted. Live: %s | search: %s",
        ticker,
        " | ".join(f"{k}:{v}" for k, v in source_results.items()),
        info.get("reason"),
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
