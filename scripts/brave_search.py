"""
brave_search.py — Brave Search API integration for Ollama web search

Daily budget cap: 30 requests/day (900/month with buffer for 1,000/month free tier).
Weekend skip: No Brave calls Sat/Sun (use DDG/RSS fallback).
Cache TTL: 60 min for news, 5 min for web (was 5 min for both).
Budget tracked in: data/portfolios/state/brave_search_budget.json
"""
from __future__ import annotations
import json, os, time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
import urllib.request, urllib.parse, urllib.error

BRAVE_API_URL = "https://api.search.brave.com/res/v1/web/search"
BRAVE_NEWS_URL = "https://api.search.brave.com/res/v1/news/search"
MAX_RESULTS = 5
REQUEST_TIMEOUT = 10
DAILY_BUDGET = 30
SKIP_WEEKENDS = True
_search_cache: Dict[str, Any] = {}
_cache_ttl_web = 300       # 5 min for web search
_cache_ttl_news = 3600     # 60 min for news search

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_BUDGET_FILE = _PROJECT_ROOT / "data" / "portfolios" / "state" / "brave_search_budget.json"


def _load_budget() -> dict:
    try:
        if _BUDGET_FILE.exists():
            return json.loads(_BUDGET_FILE.read_text())
    except Exception:
        pass
    return {}


def _save_budget(data: dict):
    try:
        _BUDGET_FILE.parent.mkdir(parents=True, exist_ok=True)
        _BUDGET_FILE.write_text(json.dumps(data, indent=2))
    except Exception:
        pass


def _check_budget() -> bool:
    """Return True if we can make a Brave API call today."""
    today = datetime.now().strftime("%Y-%m-%d")
    is_weekend = datetime.now().weekday() >= 5

    if SKIP_WEEKENDS and is_weekend:
        return False

    budget = _load_budget()
    if budget.get("date") != today:
        budget = {"date": today, "calls": 0, "skipped_weekend": 0, "skipped_budget": 0}

    if budget["calls"] >= DAILY_BUDGET:
        budget["skipped_budget"] = budget.get("skipped_budget", 0) + 1
        _save_budget(budget)
        return False

    return True


def _record_call():
    """Record a successful Brave API call against today's budget."""
    today = datetime.now().strftime("%Y-%m-%d")
    budget = _load_budget()
    if budget.get("date") != today:
        budget = {"date": today, "calls": 0, "skipped_weekend": 0, "skipped_budget": 0}
    budget["calls"] = budget.get("calls", 0) + 1
    budget["last_call"] = datetime.now().isoformat()
    _save_budget(budget)

def _get_api_key(project_root: str = ".") -> Optional[str]:
    key = os.getenv("BRAVE_SEARCH_API_KEY", "")
    if key: return key
    env_path = Path(project_root) / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith("BRAVE_SEARCH_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"')
    return None

def _cached(k, ttl=None):
    if k in _search_cache:
        e = _search_cache[k]
        _ttl = ttl or _cache_ttl_web
        if time.time() - e["ts"] < _ttl: return e["data"]
    return None

def _cache_set(k, data): _search_cache[k] = {"ts": time.time(), "data": data}

def search(query, count=MAX_RESULTS, freshness=None, project_root="."):
    ck = f"web:{query}:{freshness}"
    cached = _cached(ck, _cache_ttl_web)
    if cached is not None: return cached
    if not _check_budget():
        return []
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
        _record_call()
        _cache_set(ck, results)
        return results
    except Exception as e:
        print(f"  [brave-search] Error: {e}")
        return []

def search_news(query, count=MAX_RESULTS, freshness="pd", project_root="."):
    ck = f"news:{query}:{freshness}"
    cached = _cached(ck, _cache_ttl_news)
    if cached is not None: return cached
    if not _check_budget():
        return []
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
        _record_call()
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

def get_budget_status() -> dict:
    """Return current budget status for monitoring/alerting."""
    budget = _load_budget()
    today = datetime.now().strftime("%Y-%m-%d")
    if budget.get("date") != today:
        return {"date": today, "calls": 0, "limit": DAILY_BUDGET, "remaining": DAILY_BUDGET,
                "is_weekend": datetime.now().weekday() >= 5, "skip_weekends": SKIP_WEEKENDS}
    return {
        "date": budget.get("date"), "calls": budget.get("calls", 0),
        "limit": DAILY_BUDGET, "remaining": max(0, DAILY_BUDGET - budget.get("calls", 0)),
        "skipped_budget": budget.get("skipped_budget", 0),
        "skipped_weekend": budget.get("skipped_weekend", 0),
        "last_call": budget.get("last_call"),
        "is_weekend": datetime.now().weekday() >= 5,
        "skip_weekends": SKIP_WEEKENDS,
    }


def test_connection(project_root="."):
    api_key = _get_api_key(project_root)
    if not api_key:
        print("  [brave-search] No API key — add BRAVE_SEARCH_API_KEY to .env")
        return False
    budget = get_budget_status()
    print(f"  [brave-search] Budget: {budget['calls']}/{budget['limit']} today, {budget['remaining']} remaining")
    if budget.get("is_weekend") and SKIP_WEEKENDS:
        print("  [brave-search] Weekend — calls skipped (using fallback sources)")
        return True
    if budget["remaining"] <= 0:
        print("  [brave-search] Daily budget exhausted — calls skipped")
        return True
    results = search("test", count=1, project_root=project_root)
    if results: print("  [brave-search] OK"); return True
    print("  [brave-search] Failed"); return False


if __name__ == "__main__":
    import sys
    if "--budget" in sys.argv:
        b = get_budget_status()
        print(json.dumps(b, indent=2))
    else:
        test_connection(".")
        sym = sys.argv[1] if len(sys.argv) > 1 else "MAMO"
        results = search_ticker(sym)
        for r in results:
            print(f"  [{r.get('age','?')}] {r['title'][:80]}")
