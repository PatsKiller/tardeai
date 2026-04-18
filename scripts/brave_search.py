"""
brave_search.py — Brave Search API integration for Ollama web search
"""
from __future__ import annotations
import json, os, time
from pathlib import Path
from typing import Any, Dict, List, Optional
import urllib.request, urllib.parse, urllib.error

BRAVE_API_URL = "https://api.search.brave.com/res/v1/web/search"
BRAVE_NEWS_URL = "https://api.search.brave.com/res/v1/news/search"
MAX_RESULTS = 5
REQUEST_TIMEOUT = 10
_search_cache: Dict[str, Any] = {}
_cache_ttl = 300

def _get_api_key(project_root: str = ".") -> Optional[str]:
    key = os.getenv("BRAVE_SEARCH_API_KEY", "")
    if key: return key
    env_path = Path(project_root) / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith("BRAVE_SEARCH_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"')
    return None

def _cached(k):
    if k in _search_cache:
        e = _search_cache[k]
        if time.time() - e["ts"] < _cache_ttl: return e["data"]
    return None

def _cache_set(k, data): _search_cache[k] = {"ts": time.time(), "data": data}

def search(query, count=MAX_RESULTS, freshness=None, project_root="."):
    ck = f"web:{query}:{freshness}"
    cached = _cached(ck)
    if cached is not None: return cached
    api_key = _get_api_key(project_root)
    if not api_key: return []
    params = {"q": query, "count": min(count,20), "text_decorations": "false", "search_lang": "en", "country": "US"}
    if freshness: params["freshness"] = freshness
    url = f"{BRAVE_API_URL}?{urllib.parse.urlencode(params)}"
    headers = {"Accept": "application/json", "Accept-Encoding": "gzip", "X-Subscription-Token": api_key}
    try:
        req = urllib.request.Request(url, headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            raw = resp.read()
            import gzip
            try: raw = gzip.decompress(raw)
            except Exception: pass
            data = json.loads(raw)
        results = [{"title": i.get("title",""), "url": i.get("url",""), "description": i.get("description",""), "age": i.get("age","")} for i in data.get("web",{}).get("results",[])]
        _cache_set(ck, results)
        return results
    except Exception as e:
        print(f"  [brave-search] Error: {e}")
        return []

def search_news(query, count=MAX_RESULTS, freshness="pd", project_root="."):
    ck = f"news:{query}:{freshness}"
    cached = _cached(ck)
    if cached is not None: return cached
    api_key = _get_api_key(project_root)
    if not api_key: return []
    params = {"q": query, "count": min(count,20), "search_lang": "en", "country": "US", "freshness": freshness}
    url = f"{BRAVE_NEWS_URL}?{urllib.parse.urlencode(params)}"
    headers = {"Accept": "application/json", "Accept-Encoding": "gzip", "X-Subscription-Token": api_key}
    try:
        req = urllib.request.Request(url, headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            raw = resp.read()
            import gzip
            try: raw = gzip.decompress(raw)
            except Exception: pass
            data = json.loads(raw)
        results = [{"title": i.get("title",""), "url": i.get("url",""), "description": i.get("description",""), "age": i.get("age",""), "source": i.get("meta_url",{}).get("hostname","")} for i in data.get("results",[])]
        _cache_set(ck, results)
        return results
    except Exception as e:
        print(f"  [brave-search] News error: {e}")
        return []

def search_ticker(symbol, context="news catalyst", freshness="pd", project_root="."):
    return search_news(f"{symbol} stock {context}", freshness=freshness, project_root=project_root)

def format_results_for_prompt(results, max_chars=800):
    if not results: return "No web search results available."
    lines, total = [], 0
    for i, r in enumerate(results[:5], 1):
        line = f"{i}. [{r.get('age','?')}] {r.get('title','')[:100]} — {r.get('description','')[:150]}"
        if total + len(line) > max_chars: break
        lines.append(line); total += len(line)
    return "\n".join(lines)

def inject_search_context(base_prompt, query, search_type="news", project_root="."):
    results = search_news(query, project_root=project_root) if search_type == "news" else search(query, project_root=project_root)
    if not results: return base_prompt
    return f"RECENT WEB SEARCH RESULTS for '{query}':\n{format_results_for_prompt(results)}\n\n{base_prompt}"

def test_connection(project_root="."):
    api_key = _get_api_key(project_root)
    if not api_key:
        print("  [brave-search] No API key — add BRAVE_SEARCH_API_KEY to .env")
        return False
    results = search("test", count=1, project_root=project_root)
    if results: print("  [brave-search] OK"); return True
    print("  [brave-search] Failed"); return False

if __name__ == "__main__":
    import sys
    test_connection(".")
    sym = sys.argv[1] if len(sys.argv) > 1 else "MAMO"
    results = search_ticker(sym)
    for r in results:
        print(f"  [{r.get('age','?')}] {r['title'][:80]}")
