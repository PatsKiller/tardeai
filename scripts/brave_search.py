"""
brave_search.py — Brave Search API integration for Ollama web search

Daily budget cap: 120/day, 1500/month — a LOCAL cost policy, not a provider plan.

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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
import urllib.request, urllib.parse, urllib.error

BRAVE_API_URL = "https://api.search.brave.com/res/v1/web/search"
BRAVE_NEWS_URL = "https://api.search.brave.com/res/v1/news/search"
MAX_RESULTS = 5
REQUEST_TIMEOUT = 10
DAILY_BUDGET = 120
# LOCAL cost policy, owned by the operator — NOT a provider limit. Named and
# justified in lib/research_provider_truth.BRAVE_LOCAL_COST_POLICY, which is the
# single place these numbers are explained.
#
# These mirror lib/search_budget.DEFAULT_LIMITS["brave"], which is the binding
# ceiling — this module's own check runs second, behind the shared one. Raised
# 2026-09-05 with the daily/monthly split described there: daily is a runaway
# breaker, monthly is the cost bound.
MONTHLY_BUDGET = 1500
SKIP_WEEKENDS = True
# Callers that answer a question someone is waiting for. These are rate-limited
# and budgeted like everything else; they are simply not silenced on a weekend.
ON_DEMAND_CALLERS = frozenset({"web_research", "intel_query", "manual"})
# CALLER_CAPS moved to lib/search_budget.CALLER_DAILY_CAPS, where it binds
# for every caller rather than only the ones importing this client.
MONTHLY_WARN_PCT = 70
MONTHLY_CRITICAL_PCT = 90
_search_cache: Dict[str, Any] = {}
_cache_ttl_web = 300       # 5 min for web search
_cache_ttl_news = 3600     # 60 min for news search

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _budget_file() -> Path:
    """The L2 per-caller ledger, at ONE canonical location for every tree.

    This was `Path(__file__).parent.parent / data/portfolios/state/...` — i.e.
    resolved relative to whichever tree happened to import this module. That
    gave every tree a PRIVATE counter, and the copies then disagreed:

        release symlink -> persistent-state/…/brave_search_budget.json
                           frozen 2026-08-10, no September at all
        dev tree        -> trade-ai-v12-rebuild/…/brave_search_budget.json
                           September = 54

    Eight copies of this basename exist on the host. The server process
    resolves the first; cron jobs running from the dev tree resolve the second.
    Neither is wrong and neither is complete, so the ceiling each enforces is
    computed from a fraction of the traffic — the same "working alarm on an
    unrepresentative sensor" failure that created lib/search_budget.py, one
    layer down.

    Resolving through the canonical state root, exactly as
    lib/search_budget.budget_path() does, makes every caller share one counter.
    The scattered copies are thereby made inert without deleting any of them:
    nothing resolves to them any more, and they remain readable as history.
    """
    try:
        from scripts.lib.search_budget import _state_root
    except ImportError:                                  # pragma: no cover
        try:
            from lib.search_budget import _state_root    # type: ignore
        except ImportError:
            # Never silently fall back to a tree-relative path — that is the
            # defect. Use the same last-resort constant search_budget uses.
            return (Path.home() / "trade-ai-releases" / "persistent-state"
                    / "data" / "portfolios" / "state" / "brave_search_budget.json")
    return _state_root() / "data" / "portfolios" / "state" / "brave_search_budget.json"


_BUDGET_FILE = _budget_file()


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


def _reserve(caller: str = "default") -> bool:
    """Atomically reserve one unit BEFORE the request. False means do not call.

    Replaces the check-then-call-then-record sequence this module used, which
    was a textbook check-to-use gap: two processes could both observe an
    under-limit counter, both call, and both record. lib/search_budget says so
    at its own `check` docstring — "prefer try_consume / guard at the call site
    so concurrent cron processes cannot both spend the last unit" — and the two
    aegis callers that bypass this client were already using guard() correctly,
    which made them more correct than the sanctioned path.

    Reserving before the request means a request that never happens has been
    counted, so every failure path must _refund.
    """
    caller_key = caller.split("/")[-1].replace(".py", "")
    try:
        from scripts.lib.search_budget import try_consume
    except ImportError:                                  # pragma: no cover
        try:
            from lib.search_budget import try_consume    # type: ignore
        except ImportError:
            print("  [brave-search] shared budget unavailable — DENY (never fail open)")
            return False
    try:
        verdict = try_consume("brave", caller=caller_key)
    except Exception as exc:                             # noqa: BLE001
        print(f"  [brave-search] budget error — DENY (never fail open): {exc}")
        return False
    if not verdict.get("allowed"):
        print(f"  [brave-search] denied by budget: {verdict.get('reason')}")
        return False
    return True


def _refund(caller: str = "default") -> None:
    """Return the unit reserved for a request that did not happen."""
    caller_key = caller.split("/")[-1].replace(".py", "")
    try:
        from scripts.lib.search_budget import refund
    except ImportError:                                  # pragma: no cover
        try:
            from lib.search_budget import refund         # type: ignore
        except ImportError:
            return
    try:
        refund("brave", caller=caller_key)
    except Exception:
        pass


def _record_call(caller: str = "default"):
    """RETIRED — the second ledger no longer counts.

    This wrote data/portfolios/state/brave_search_budget.json under an unlocked
    read-modify-write whose _save_budget swallowed every exception, so a failed
    write was invisible. That file existed as a second counter only because it
    held CALLER_CAPS, which the canonical ledger lacked; those caps now live in
    lib/search_budget.CALLER_DAILY_CAPS and bind for every caller, including the
    ones that never imported this client.

    Counting in two places is what let the two disagree: through 2026-09-04 they
    agreed exactly (52 each), and on 2026-09-05 the canonical ledger recorded 6
    calls the other never saw. The file is left in place, unwritten, as history.
    Nothing here reconciles the two numbers — that is an operator call against
    the provider's own dashboard.
    """
    return None


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
    # Reserve BEFORE the request. Every path out of here that does not make a
    # successful call must refund, or the ledger charges for work never done.
    if not _reserve(caller):
        return []
    api_key = _get_api_key(project_root)
    if not api_key:
        _refund(caller)
        return []
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
        # Already counted at reservation; nothing to record here.
        _cache_set(ck, results)
        return results
    except Exception as e:
        print(f"  [brave-search] Error: {e}")
        _refund(caller)
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
    # Reserve BEFORE the request. Every path out of here that does not make a
    # successful call must refund, or the ledger charges for work never done.
    if not _reserve(caller):
        return []
    api_key = _get_api_key(project_root)
    if not api_key:
        _refund(caller)
        return []
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
        # Already counted at reservation; nothing to record here.
        _cache_set(ck, results)
        return results
    except Exception as e:
        print(f"  [brave-search] News error: {e}")
        _refund(caller)
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
    """Budget status for monitoring/alerting, read from the BINDING ledger.

    This used to read the legacy per-tree file. That is the sensor defect
    lib/search_budget.py was written to fix, reproduced one layer up: the alarm
    was wired, scheduled and reaching a channel while reporting a percentage
    computed from a counter that saw a fraction of the traffic. On 2026-08-30 it
    reported `monthly_pct: 17.6, "ok"` from a ledger reading 150/month while the
    provider dashboard read roughly 1,000.

    An alarm on an unrepresentative sensor is worse than no alarm, because it
    answers the question that would otherwise be asked.
    """
    try:
        from scripts.lib.search_budget import status as _shared_status
    except ImportError:                                  # pragma: no cover
        from lib.search_budget import status as _shared_status  # type: ignore

    st = _shared_status("brave")
    month_total = int(st.get("monthly_used", 0))
    month_limit = int(st.get("monthly_limit", 0)) or MONTHLY_BUDGET
    month_pct = round(month_total / month_limit * 100, 1) if month_limit else 0.0
    alert_level = "ok"
    if month_pct >= MONTHLY_CRITICAL_PCT:
        alert_level = "critical"
    elif month_pct >= MONTHLY_WARN_PCT:
        alert_level = "warning"
    daily_used = int(st.get("daily_used", 0))
    daily_limit = int(st.get("daily_limit", 0)) or DAILY_BUDGET
    return {
        "source": "search_budget.json (canonical, flocked)",
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "calls_today": daily_used,
        "daily_limit": daily_limit,
        "daily_remaining": max(0, daily_limit - daily_used),
        "monthly_total": month_total,
        "monthly_limit": month_limit,
        "monthly_pct": month_pct,
        "monthly_alert": alert_level,
        "caller_caps": dict(_caller_daily_caps()),
        "last_call": st.get("last_call"),
        "is_weekend": datetime.now().weekday() >= 5,
        "skip_weekends": SKIP_WEEKENDS,
    }


def _caller_daily_caps() -> dict:
    try:
        from scripts.lib.search_budget import CALLER_DAILY_CAPS
    except ImportError:                                  # pragma: no cover
        try:
            from lib.search_budget import CALLER_DAILY_CAPS  # type: ignore
        except ImportError:
            return {}
    return CALLER_DAILY_CAPS


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
