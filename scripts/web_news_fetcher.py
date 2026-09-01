"""web_news_fetcher.py — Fetch live news for tickers via Finviz/Yahoo (not search API).

F2 (2026-08-31): Brave Search API is reserved for residual-web. This module
feeds incubator_llm_screener.py and portfolio_ai_analyst.py — bulk news — so
it uses Finviz export + Yahoo RSS, with DuckDuckGo HTML scrape as last resort.

Usage:
    from web_news_fetcher import fetch_web_news
    news = fetch_web_news("AAPL")
    # Returns list of {"title", "url", "snippet", "age", "source"} dicts
"""
import json
import os
import re
import time
import urllib.request
import urllib.error
import urllib.parse
from html import unescape
from pathlib import Path
from typing import List, Dict

# Cache to avoid hammering APIs for the same ticker within a session
_cache: Dict[str, tuple] = {}  # symbol -> (timestamp, results)
_CACHE_TTL = 600  # 10 min cache per symbol


def _finviz_yahoo_news(symbol: str, max_results: int = 5) -> List[Dict]:
    """F2 primary path: Finviz Elite news export, then Yahoo RSS/search."""
    sym = (symbol or "").upper().strip()
    if not sym:
        return []
    out: List[Dict] = []
    try:
        from finviz_news import fetch_finviz_news
        for a in fetch_finviz_news(sym, lookback_hours=72)[:max_results]:
            out.append({
                "title": a.get("headline") or a.get("title") or "",
                "url": a.get("url") or "",
                "snippet": str(a.get("original_source") or a.get("source") or "")[:150],
                "age": "",
                "source": "finviz_news",
            })
    except Exception as e:
        print(f"  [web-news] Finviz failed: {e}")
    if len(out) >= max_results:
        return out[:max_results]
    try:
        from yahoo_news import fetch_yahoo_news
        for a in fetch_yahoo_news(sym, lookback_hours=72)[: max(0, max_results - len(out))]:
            out.append({
                "title": a.get("headline") or a.get("title") or "",
                "url": a.get("url") or "",
                "snippet": str(a.get("source") or "yahoo")[:150],
                "age": "",
                "source": "yahoo_news",
            })
    except Exception as e:
        print(f"  [web-news] Yahoo failed: {e}")
    return out[:max_results]


def _brave_search(query: str, max_results: int = 5) -> List[Dict]:
    """Retired for bulk news (F2). Kept as named stub so imports do not fail open."""
    return []


def _ddg_search(query: str, max_results: int = 5) -> List[Dict]:
    """Search via DuckDuckGo Lite (no API key needed, lighter rate limits)."""
    try:
        # Use lite endpoint — simpler HTML, less likely to trigger bot detection
        data = urllib.parse.urlencode({"q": query}).encode()
        req = urllib.request.Request("https://lite.duckduckgo.com/lite/", data=data, headers={
            "User-Agent": "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0",
            "Content-Type": "application/x-www-form-urlencoded",
        }, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="replace")

        results = []
        # Lite format: <a href="https://...">Title</a> (external links only)
        links = re.findall(
            r'<a[^>]*href="(https?://[^"]+)"[^>]*>(.*?)</a>',
            html
        )
        for href, title_html in links[:max_results * 2]:
            # Skip DDG internal links
            if "duckduckgo.com" in href or "duck.co" in href:
                continue
            title = re.sub(r'<[^>]+>', '', unescape(title_html)).strip()
            if title and len(title) > 10:
                results.append({
                    "title": title[:120],
                    "url": href,
                    "snippet": "",
                    "age": "",
                    "source": "ddg",
                })
            if len(results) >= max_results:
                break
        return results
    except Exception as e:
        print(f"  [web-news] DuckDuckGo failed: {e}")
        return []


def fetch_web_news(symbol: str, query_extra: str = "", max_results: int = 5) -> List[Dict]:
    """Fetch recent news about a stock ticker without the paid search API.

    Order: Finviz → Yahoo → DuckDuckGo HTML scrape. Brave is not called.
    Returns list of dicts with: title, url, snippet, age, source
    """
    # Check cache
    cached = _cache.get(symbol)
    if cached and (time.time() - cached[0]) < _CACHE_TTL:
        return cached[1]

    query = f"{symbol} stock news {query_extra}".strip()

    results = _finviz_yahoo_news(symbol, max_results)

    # Last-resort scrape (not a search API credit)
    if not results:
        results = _ddg_search(query, max_results)

    if results:
        _cache[symbol] = (time.time(), results)

    return results


def fetch_web_news_batch(symbols: List[str], max_per_symbol: int = 3) -> Dict[str, List[Dict]]:
    """Fetch news for multiple symbols. Returns {symbol: [results]}."""
    all_results = {}
    for sym in symbols:
        results = fetch_web_news(sym, max_results=max_per_symbol)
        if results:
            all_results[sym] = results
        time.sleep(1.5)  # rate limit courtesy — DDG needs spacing
    return all_results


def format_news_for_prompt(news_by_symbol: Dict[str, List[Dict]], max_chars: int = 500) -> str:
    """Format web news results into compact text for LLM prompt injection."""
    if not news_by_symbol:
        return ""
    lines = ["LIVE WEB NEWS:"]
    chars = 15
    for sym, articles in news_by_symbol.items():
        for a in articles[:2]:
            age = f" ({a['age']})" if a.get('age') else ""
            line = f"  {sym}: {a['title'][:60]}{age}"
            if chars + len(line) > max_chars:
                break
            lines.append(line)
            chars += len(line)
        if chars >= max_chars:
            break
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    symbol = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    results = fetch_web_news(symbol)
    if results:
        print(f"Web news for {symbol} (via {results[0].get('source', '?')}):")
        for r in results:
            print(f"  {r['title']}")
            if r['snippet']:
                print(f"    {r['snippet']}")
    else:
        print(f"No web news found for {symbol}")
