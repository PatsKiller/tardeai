"""brave_search.py — compatibility shim over the canonical Brave router.

This module used to be a second, independent Brave client: its own key read,
its own HTTP call, its own in-process cache, its own daily/monthly counters and
its own guessed plan ceiling (``MONTHLY_BUDGET = 850``, commented "out of
1000"). ``phase2b_analyst`` held a *third* set of assumptions ("2000/mo free
tier"). Measured live 2026-09-03 the plan publishes:

    x-ratelimit-policy: 50;w=1, 0;w=2592000

50 requests per **second**, and no metered monthly window at all. Both
hardcoded tiers were fiction, and they disagreed with each other.

Architecture rule 10 says one semantic question has one canonical service
contract and compatibility endpoints delegate rather than independently
recompute. So everything here now delegates to
``scripts.lib.brave_research_router``: one ledger, one durable cache, one
coalescing lock, one set of gates.

Prefer the router directly in new code — it returns an ``Outcome`` that says
*why* there are no results. These functions keep returning bare lists for the
callers that already expect them.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

MAX_RESULTS = 5

#: Retained for callers that import them. These are **local cost policy**, not
#: the provider's plan: see the module docstring.
DAILY_BUDGET = 25
MONTHLY_BUDGET = 850


def _router():
    try:
        from scripts.lib import brave_research_router as R

        return R
    except ImportError:  # pragma: no cover
        try:
            from lib import brave_research_router as R  # type: ignore

            return R
        except ImportError:
            return None


def _as_dicts(outcome) -> list[dict[str, Any]]:
    return [
        {
            "title": r.title,
            "url": r.url,
            "description": r.description,
            "age": r.age,
            "source": r.source_domain,
            "attribution": r.attribution,
            "is_primary_source": r.is_primary_source,
        }
        for r in outcome.results
    ]


def search(query, count=MAX_RESULTS, freshness=None, project_root=".", caller="default") -> list[dict[str, Any]]:
    """Routed web search. Returns ``[]`` on any denial or failure.

    ``[]`` is lossy — it cannot distinguish "nothing published" from "budget
    denied". Use :func:`search_outcome` (or the router) when that matters.
    """
    return _as_dicts(search_outcome(query, count=count, freshness=freshness, project_root=project_root, caller=caller))


def search_outcome(
    query, count=MAX_RESULTS, freshness=None, project_root=".", caller="default", purpose=None, priority=None
):
    """Routed web search preserving the reason for an empty result."""
    R = _router()
    if R is None:
        raise RuntimeError("brave_research_router unavailable — refusing to fall back to an unbudgeted client")
    return R.search(
        query,
        purpose=purpose or R.Purpose.EVIDENCE_GAP,
        priority=priority or R.Priority.WATCHLIST,
        caller=caller,
        count=count,
        freshness=freshness,
        endpoint="web",
        project_root=Path(project_root) if project_root else None,
    )


def search_news(query, count=MAX_RESULTS, freshness="pd", project_root=".", caller="default") -> list[dict[str, Any]]:
    R = _router()
    if R is None:
        raise RuntimeError("brave_research_router unavailable — refusing to fall back to an unbudgeted client")
    out = R.search(
        query,
        purpose=R.Purpose.CATALYST_CORROBORATION,
        priority=R.Priority.WATCHLIST,
        caller=caller,
        count=count,
        freshness=freshness,
        endpoint="news",
        project_root=Path(project_root) if project_root else None,
    )
    return _as_dicts(out)


def search_ticker(symbol, context="news catalyst", freshness="pd", project_root=".", caller="search_ticker"):
    return search_news(f"{symbol} stock {context}", freshness=freshness, project_root=project_root, caller=caller)


def format_results_for_prompt(results, max_chars=800):
    """Render discovery artifacts for an LLM prompt.

    The ``SEARCH_DISCOVERY`` banner is deliberate: a model handed bare snippets
    will otherwise treat them as established fact.
    """
    if not results:
        return "No web search results available."
    lines, total = ["(SEARCH_DISCOVERY — snippets are leads, not verified facts)"], 0
    for i, r in enumerate(results[:5], 1):
        line = f"{i}. [{r.get('age', '?')}] {str(r.get('title', ''))[:100]} — {str(r.get('description', ''))[:150]}"
        if total + len(line) > max_chars:
            break
        lines.append(line)
        total += len(line)
    return "\n".join(lines)


def inject_search_context(base_prompt, query, search_type="news", project_root=".", caller="inject_search_context"):
    results = (
        search_news(query, project_root=project_root, caller=caller)
        if search_type == "news"
        else search(query, project_root=project_root, caller=caller)
    )
    if not results:
        return base_prompt
    return f"RECENT WEB SEARCH RESULTS for '{query}':\n{format_results_for_prompt(results)}\n\n{base_prompt}"


def get_budget_status(root: Optional[Path] = None) -> dict[str, Any]:
    """Budget/effectiveness status for monitoring and alerting.

    Keys ``monthly_pct`` / ``monthly_alert`` are preserved for
    ``alert_dispatcher_unified.check_brave_budget``. ``plan`` is new and carries
    the *measured* provider allowance so an alarm can stop reporting a
    percentage of a number nobody verified.
    """
    R = _router()
    if R is None:
        return {"error": "router_unavailable", "monthly_pct": 0, "monthly_alert": "unknown"}
    rep = R.effectiveness_report(root=root)
    budget = rep.get("budget") or {}
    return {
        "date": rep.get("period"),
        "calls_today": budget.get("daily_used"),
        "daily_limit": budget.get("daily_limit"),
        "daily_remaining": (budget.get("daily_limit", 0) - budget.get("daily_used", 0))
        if budget.get("daily_limit") is not None
        else None,
        "monthly_total": budget.get("monthly_used"),
        "monthly_limit": budget.get("monthly_limit"),
        "monthly_pct": budget.get("monthly_pct", 0),
        "monthly_alert": budget.get("alert", "ok"),
        "denied_today": budget.get("denied_today"),
        "cache_hits": rep.get("cache_hits"),
        "adopted": rep.get("adopted"),
        "adoption_rate_pct": rep.get("adoption_rate_pct"),
        "plan": rep.get("allowance_reconciliation"),
        "ledger_path": budget.get("ledger_path"),
    }


def test_connection(project_root=".") -> bool:
    """Report configuration and budget state **without** spending a credit.

    The previous implementation printed ``budget['limit']`` and
    ``budget['remaining']`` against a dict that only ever had ``daily_limit``
    and ``daily_remaining`` — so this function raised ``KeyError`` on every
    invocation — and then issued a live search to "test" the key, spending a
    real credit on a diagnostic.
    """
    R = _router()
    if R is None:
        print("  [brave-search] router unavailable")
        return False
    key = R._api_key(Path(project_root) if project_root else None)
    if not key:
        print("  [brave-search] No API key — add BRAVE_SEARCH_API_KEY to .env")
        return False
    b = get_budget_status()
    print(
        f"  [brave-search] today {b['calls_today']}/{b['daily_limit']}, "
        f"month {b['monthly_total']}/{b['monthly_limit']} "
        f"({b['monthly_alert']})"
    )
    plan = b.get("plan") or {}
    print(f"  [brave-search] plan: {plan.get('note', 'unmeasured')}")
    return True


if __name__ == "__main__":
    import sys

    if "--budget" in sys.argv:
        print(json.dumps(get_budget_status(), indent=2, default=str))
    else:
        test_connection(".")
