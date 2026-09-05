"""
brave_search.py — Brave Search API integration for Ollama web search

Daily budget cap: 25/day, 850/month — a LOCAL cost policy, not a provider plan.

This docstring previously asserted a Brave free-tier monthly quota. No Brave
response observed by this system has ever stated one: that figure was an
assumption written as a provider fact, and the ceiling below then read as a
reservation carved out of it. Provider capacity is now parsed from the
X-RateLimit-* headers on every response and reported separately — see
lib/research_provider_truth.py. The ceilings below are unchanged in value.
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
DAILY_BUDGET = 25
# LOCAL cost policy, owned by the operator — NOT a provider limit. Named and
# justified in lib/research_provider_truth.BRAVE_LOCAL_COST_POLICY, which is the
# single place these numbers are explained. Unchanged in value.
MONTHLY_BUDGET = 850
SKIP_WEEKENDS = True
# Callers that answer a question someone is waiting for. These are rate-limited
# and budgeted like everything else; they are simply not silenced on a weekend.
ON_DEMAND_CALLERS = frozenset({"web_research", "intel_query", "manual"})
CALLER_CAPS = {
    "portfolio_news": 10,
    "catalyst_intelligence": 10,
    "topic_ingestion": 5,
    "web_news_fetcher": 5,
    "default": 25,
}
MONTHLY_WARN_PCT = 70
MONTHLY_CRITICAL_PCT = 90
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


def _check_budget(caller: str = "default") -> bool:
    """Return True if we can make a Brave API call today.

    Delegates to the shared per-provider budget, which DENIES when it cannot
    establish state. The local ledger below is kept as a secondary per-caller
    cap; it is no longer the only thing standing between a bulk caller and the
    monthly allowance, because three other modules used to bypass it entirely.
    """
    # Shared per-provider ledger is mandatory. Falling through to the local
    # release-relative counter when the shared module cannot be imported was
    # fail-open: concurrent cron jobs under different releases each saw their
    # own near-empty file and spent. WAVE F3: DENY when the shared budget is
    # unavailable — never fail open.
    try:
        from scripts.lib.search_budget import check as _shared_check
    except ImportError:                                  # pragma: no cover
        try:
            from lib.search_budget import check as _shared_check  # type: ignore
        except ImportError:
            print("  [brave-search] shared budget unavailable — DENY (never fail open)")
            return False
    verdict = _shared_check("brave")
    if not verdict["allowed"]:
        print(f"  [brave-search] denied by shared budget: {verdict['reason']}")
        return False

    today = datetime.now().strftime("%Y-%m-%d")
    month = datetime.now().strftime("%Y-%m")
    is_weekend = datetime.now().weekday() >= 5

    # The weekend skip is a spend heuristic for SCHEDULED bulk jobs, whose
    # subject matter does not move when the market is closed. It must not apply
    # to on-demand research: re-pointing web_research through this client made
    # every interactive lookup return [] on a Saturday, which is precisely the
    # silent-empty failure this budget work exists to remove.
    if SKIP_WEEKENDS and is_weekend and caller not in ON_DEMAND_CALLERS:
        return False

    budget = _load_budget()
    if budget.get("date") != today:
        # Preserve monthly counter, reset daily
        monthly = budget.get("monthly_calls", {})
        budget = {"date": today, "calls": 0, "skipped_weekend": 0, "skipped_budget": 0,
                  "caller_calls": {}, "monthly_calls": monthly}

    # Monthly budget check
    month_total = budget.get("monthly_calls", {}).get(month, 0)
    if month_total >= MONTHLY_BUDGET:
        budget["skipped_budget"] = budget.get("skipped_budget", 0) + 1
        _save_budget(budget)
        return False

    # Daily budget check
    if budget["calls"] >= DAILY_BUDGET:
        budget["skipped_budget"] = budget.get("skipped_budget", 0) + 1
        _save_budget(budget)
        return False

    # Per-caller cap check
    caller_key = caller.split("/")[-1].replace(".py", "")
    cap = CALLER_CAPS.get(caller_key, CALLER_CAPS["default"])
    caller_today = budget.get("caller_calls", {}).get(caller_key, 0)
    if caller_today >= cap:
        return False

    return True


def _record_shared(provider: str, caller: str) -> None:
    """Count the call in the shared per-provider ledger. Best effort."""
    try:
        from scripts.lib.search_budget import record
    except ImportError:                                  # pragma: no cover
        try:
            from lib.search_budget import record  # type: ignore
        except ImportError:
            return
    try:
        record(provider, allowed=True, caller=caller)
    except Exception:
        pass


def _record_call(caller: str = "default"):
    """Record a successful Brave API call against today's budget."""
    today = datetime.now().strftime("%Y-%m-%d")
    month = datetime.now().strftime("%Y-%m")
    budget = _load_budget()
    if budget.get("date") != today:
        monthly = budget.get("monthly_calls", {})
        budget = {"date": today, "calls": 0, "skipped_weekend": 0, "skipped_budget": 0,
                  "caller_calls": {}, "monthly_calls": monthly}
    budget["calls"] = budget.get("calls", 0) + 1
    budget["last_call"] = datetime.now().isoformat()
    # Track per-caller
    caller_key = caller.split("/")[-1].replace(".py", "")
    cc = budget.setdefault("caller_calls", {})
    cc[caller_key] = cc.get(caller_key, 0) + 1
    # Track monthly
    mc = budget.setdefault("monthly_calls", {})
    mc[month] = mc.get(month, 0) + 1
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

def search(query, count=MAX_RESULTS, freshness=None, project_root=".", caller="default"):
    ck = f"web:{query}:{freshness}"
    cached = _cached(ck, _cache_ttl_web)
    if cached is not None: return cached
    if not _check_budget(caller):
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
            _observe_capacity(resp, project_root)
            raw = resp.read()
            import gzip
            try: raw = gzip.decompress(raw)
            except Exception: pass
            data = json.loads(raw)
        results = [{"title": i.get("title",""), "url": i.get("url",""), "description": i.get("description",""), "age": i.get("age","")} for i in data.get("web",{}).get("results",[])]
        _record_shared("brave", caller)
        _record_call(caller)
        _cache_set(ck, results)
        return results
    except Exception as e:
        print(f"  [brave-search] Error: {e}")
        return []


# ── provider capacity observation ────────────────────────────────────────────
# Every Brave response carries X-RateLimit-Limit / -Remaining / -Reset. This
# module used to read only resp.read() and drop them, so the one authority that
# could state Brave's real capacity was received and discarded on every call.
_CAPACITY_PATH = "data/portfolios/state/brave_provider_capacity.json"


def _observe_capacity(resp, project_root: str = ".") -> None:
    """Record what the provider said about its own limits. Never fails a search."""
    try:
        from lib.research_provider_truth import parse_provider_capacity
    except Exception:
        try:
            from scripts.lib.research_provider_truth import parse_provider_capacity  # type: ignore
        except Exception:
            return
    try:
        cap = parse_provider_capacity("brave", dict(getattr(resp, "headers", {}) or {}))
        if not cap.observed:
            return
        path = Path(project_root) / _CAPACITY_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(cap.to_dict(), indent=2) + "\n")
        os.replace(tmp, path)
    except Exception:
        # Observation is advisory. A failure here must never break a search or
        # cause a caller to retry and spend budget twice.
        pass


def observed_capacity(project_root: str = ".") -> dict:
    """Last observed provider capacity, or an explicit unobserved record."""
    try:
        from lib.research_provider_truth import ProviderCapacity
    except Exception:
        from scripts.lib.research_provider_truth import ProviderCapacity  # type: ignore
    try:
        return json.loads((Path(project_root) / _CAPACITY_PATH).read_text())
    except Exception:
        return ProviderCapacity(provider="brave").to_dict()


def search_news(query, count=MAX_RESULTS, freshness="pd", project_root=".", caller="default"):
    ck = f"news:{query}:{freshness}"
    cached = _cached(ck, _cache_ttl_news)
    if cached is not None: return cached
    if not _check_budget(caller):
        return []
    api_key = _get_api_key(project_root)
    if not api_key: return []
    params = {"q": query, "count": min(count,20), "search_lang": "en", "country": "US", "freshness": freshness}
    url = f"{BRAVE_NEWS_URL}?{urllib.parse.urlencode(params)}"
    headers = {"Accept": "application/json", "Accept-Encoding": "gzip", "X-Subscription-Token": api_key}
    try:
        req = urllib.request.Request(url, headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            _observe_capacity(resp, project_root)
            raw = resp.read()
            import gzip
            try: raw = gzip.decompress(raw)
            except Exception: pass
            data = json.loads(raw)
        results = [{"title": i.get("title",""), "url": i.get("url",""), "description": i.get("description",""), "age": i.get("age",""), "source": i.get("meta_url",{}).get("hostname","")} for i in data.get("results",[])]
        _record_shared("brave", caller)
        _record_call(caller)
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
    month = datetime.now().strftime("%Y-%m")
    if budget.get("date") != today:
        monthly = budget.get("monthly_calls", {})
        budget = {"date": today, "calls": 0, "caller_calls": {}, "monthly_calls": monthly}
    month_total = budget.get("monthly_calls", {}).get(month, 0)
    month_pct = round(month_total / MONTHLY_BUDGET * 100, 1) if MONTHLY_BUDGET else 0
    alert_level = "ok"
    if month_pct >= MONTHLY_CRITICAL_PCT:
        alert_level = "critical"
    elif month_pct >= MONTHLY_WARN_PCT:
        alert_level = "warning"
    return {
        "date": budget.get("date"), "calls_today": budget.get("calls", 0),
        "daily_limit": DAILY_BUDGET, "daily_remaining": max(0, DAILY_BUDGET - budget.get("calls", 0)),
        "monthly_total": month_total, "monthly_limit": MONTHLY_BUDGET,
        "monthly_pct": month_pct, "monthly_alert": alert_level,
        "caller_caps": CALLER_CAPS,
        "caller_today": budget.get("caller_calls", {}),
        "skipped_budget": budget.get("skipped_budget", 0),
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
