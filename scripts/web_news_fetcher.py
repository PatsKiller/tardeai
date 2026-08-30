"""web_news_fetcher.py — Fetch live news for tickers via web search.

Tries Brave Search API first, falls back to DuckDuckGo HTML scrape.
Provides fresh web search results to supplement DB-stored news.
Used by incubator_llm_screener.py and portfolio_ai_analyst.py.

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


def _get_brave_key() -> str:
    key = os.getenv("BRAVE_API_KEY", "").strip() or os.getenv("BRAVE_SEARCH_API_KEY", "").strip()
    if not key:
        try:
            env_path = Path(__file__).resolve().parent.parent / ".env"
            if env_path.exists():
                for line in env_path.read_text().splitlines():
                    if line.startswith("BRAVE_API_KEY=") or line.startswith("BRAVE_SEARCH_API_KEY="):
                        key = line.split("=", 1)[1].strip().strip('"')
                        break
        except Exception:
            pass
    return key


def _brave_search(query: str, max_results: int = 5) -> List[Dict]:
    """Search via Brave Search API. Returns results or empty on failure."""
    key = _get_brave_key()
    if not key:
        return []
    # brave_search.CALLER_CAPS declared `web_news_fetcher: 5` while this module
    # held its own client — a cap that governed nothing.
    try:
        from scripts.lib.search_budget import guard as _sb_guard
    except ImportError:
        from lib.search_budget import guard as _sb_guard  # type: ignore
    if not _sb_guard("brave", "web_news_fetcher"):
        return []
    try:
        url = (f"https://api.search.brave.com/res/v1/web/search"
               f"?q={urllib.parse.quote(query)}&count={max_results}&freshness=pw")
        req = urllib.request.Request(url, headers={
            "Accept": "application/json",
            "X-Subscription-Token": key,
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        results = []
        for r in (data.get("web", {}).get("results", []))[:max_results]:
            results.append({
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "snippet": r.get("description", "")[:150],
                "age": r.get("age", ""),
                "source": "brave",
            })
        return results
    except Exception as e:
        print(f"  [web-news] Brave failed: {e}")
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
    """Search for recent news about a stock ticker.

    Tries Brave first, falls back to DuckDuckGo.
    Returns list of dicts with: title, url, snippet, age, source
    """
    # Check cache
    cached = _cache.get(symbol)
    if cached and (time.time() - cached[0]) < _CACHE_TTL:
        return cached[1]

    query = f"{symbol} stock news {query_extra}".strip()

    # Try Brave first
    results = _brave_search(query, max_results)

    # Fallback to DuckDuckGo
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
