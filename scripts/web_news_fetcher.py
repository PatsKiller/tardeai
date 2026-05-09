"""web_news_fetcher.py — Fetch live news for tickers via Brave Search API.

Provides fresh web search results to supplement DB-stored news.
Used by incubator_llm_screener.py and portfolio_ai_analyst.py.

Usage:
    from web_news_fetcher import fetch_web_news
    news = fetch_web_news("AAPL")
    # Returns list of {"title", "url", "snippet", "age"} dicts
"""
import json
import os
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import List, Dict, Optional

# Cache to avoid hammering the API for the same ticker within a session
_cache: Dict[str, tuple] = {}  # symbol -> (timestamp, results)
_CACHE_TTL = 600  # 10 min cache per symbol

# Load API key from env or .env
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


def fetch_web_news(symbol: str, query_extra: str = "", max_results: int = 5) -> List[Dict]:
    """Search Brave for recent news about a stock ticker.

    Returns list of dicts with: title, url, snippet, age
    Falls back gracefully if API key missing or search fails.
    """
    # Check cache
    cached = _cache.get(symbol)
    if cached and (time.time() - cached[0]) < _CACHE_TTL:
        return cached[1]

    key = _get_brave_key()
    if not key:
        return []

    query = f"{symbol} stock news {query_extra}".strip()
    try:
        url = f"https://api.search.brave.com/res/v1/web/search?q={urllib.request.quote(query)}&count={max_results}&freshness=pw"
        req = urllib.request.Request(url, headers={
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
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
            })

        _cache[symbol] = (time.time(), results)
        return results

    except Exception as e:
        print(f"  [web-news] Search failed for {symbol}: {e}")
        return []


def fetch_web_news_batch(symbols: List[str], max_per_symbol: int = 3) -> Dict[str, List[Dict]]:
    """Fetch news for multiple symbols. Returns {symbol: [results]}."""
    all_results = {}
    for sym in symbols:
        results = fetch_web_news(sym, max_results=max_per_symbol)
        if results:
            all_results[sym] = results
        time.sleep(0.3)  # rate limit courtesy
    return all_results


def format_news_for_prompt(news_by_symbol: Dict[str, List[Dict]], max_chars: int = 500) -> str:
    """Format web news results into compact text for LLM prompt injection."""
    if not news_by_symbol:
        return ""
    lines = ["LIVE WEB NEWS:"]
    chars = 15
    for sym, articles in news_by_symbol.items():
        for a in articles[:2]:
            line = f"  {sym}: {a['title'][:60]} ({a.get('age', '?')})"
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
        print(f"Web news for {symbol}:")
        for r in results:
            print(f"  [{r.get('age', '?')}] {r['title']}")
            print(f"    {r['snippet']}")
    else:
        print(f"No web news found for {symbol} (check BRAVE_API_KEY in .env)")
