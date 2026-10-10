"""Scalp research search — the hot tier's only door to web search: the search routing engine.

Coordination ruling 2026-10-10 (operator: Brave at $20/month max, priority for scalps about to fire): the hot tier
**never calls Brave or SearXNG directly and adds no caps of its own**. It asks the rule-based routing engine that
Agent V builds on ``n8nmat/search-routing-engine`` (``config/search_routing_policy.json`` + a router chokepoint over
``scripts/lib/brave_router.py``: free lane first — cache, SearXNG, broker — then Brave only for a priority scalp or
insufficient free results, inside a dollar budget).

Interface this module needs from the engine (``REQUIRED_INTERFACE``), any one of the module paths in
``ENGINE_MODULES``::

    route_search(query, *, request_class, caller, subject, intent,
                 time_range="day", categories="news", limit=3,
                 cache_ttl_s=1200, dry_run=False) -> {
        "ok": bool, "results": [{title, url, content, engine, published}], "provider": str | None,
        "cache_hit": bool, "as_of": iso, "decision": str, "denied_reason": str | None}

``request_class`` is ``scalp_priority`` (a name about to fire: on the list with a GO-pending / awaiting-catalyst
route) or ``scalp_research`` (any other scalp name). ``cache_ttl_s`` is the shared 20-minute (subject, intent)
window: L708 and L379 ask the same intent (``premarket catalyst``) for the same subject, so within 20 minutes the
second asker is a cache hit. The cache lives in the engine; this module keeps none.

Until the engine is importable :func:`engine_available` is False and the hot-tier research path stays off (the
researcher keeps its legacy behaviour). That is a precondition of the flag flip, recorded in the packet.

READ_ONLY_ADVISORY: research context only; never a trade signal.
"""

from __future__ import annotations

import importlib
from typing import Any, Callable

ENGINE_MODULES = ("lib.search_routing_engine", "lib.search_routing", "lib.search_router")
ENGINE_FUNCTION = "route_search"
REQUEST_CLASS_PRIORITY = "scalp_priority"
REQUEST_CLASS_RESEARCH = "scalp_research"
CACHE_TTL_S = 20 * 60
REQUIRED_INTERFACE = (
    "route_search(query, *, request_class, caller, subject, intent, time_range='day', categories='news', "
    "limit=3, cache_ttl_s=1200, dry_run=False) -> {ok, results, provider, cache_hit, as_of, decision, denied_reason}"
)

_override: dict[str, Any] = {"fn": None}


def set_engine_for_tests(fn: Callable[..., dict] | None) -> None:
    """Inject a stand-in engine (tests only); ``None`` restores discovery."""
    _override["fn"] = fn


def _engine() -> Callable[..., dict] | None:
    if _override["fn"] is not None:
        return _override["fn"]
    for name in ENGINE_MODULES:
        try:
            mod = importlib.import_module(name)
        except Exception:
            continue
        fn = getattr(mod, ENGINE_FUNCTION, None)
        if callable(fn):
            return fn
    return None


def engine_available() -> bool:
    return _engine() is not None


def route(
    symbol: str,
    intent: str,
    *,
    caller: str,
    priority: bool = False,
    time_range: str = "day",
    limit: int = 3,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Ask the routing engine for ``{symbol} stock {intent}``. Never raises; never calls a provider itself.

    Microcaps often return nothing for ``time_range=day``; on an ok-but-empty day answer the engine is asked once
    more with ``week`` (plan §C.2.3). A dry run passes ``dry_run=True`` through: the engine reports what it would do.
    """
    fn = _engine()
    sym = str(symbol or "").upper().strip()
    base = {"symbol": sym, "intent": intent, "caller": caller, "dry_run": dry_run}
    if fn is None:
        return {
            **base,
            "ok": False,
            "results": [],
            "decision": "ROUTING_ENGINE_UNAVAILABLE",
            "denied_reason": "search routing engine not importable",
            "provider": None,
            "cache_hit": False,
        }
    rc = REQUEST_CLASS_PRIORITY if priority else REQUEST_CLASS_RESEARCH
    query = f"{sym} stock {intent}"
    attempts = []
    out: dict[str, Any] = {}
    for tr in (time_range, "week") if time_range == "day" else (time_range,):
        try:
            out = dict(
                fn(
                    query,
                    request_class=rc,
                    caller=caller,
                    subject=sym,
                    intent=intent,
                    time_range=tr,
                    categories="news",
                    limit=limit,
                    cache_ttl_s=CACHE_TTL_S,
                    dry_run=dry_run,
                )
                or {}
            )
        except Exception as exc:  # the engine failing is a typed answer, not a crash of the lane
            out = {
                "ok": False,
                "results": [],
                "decision": "ROUTING_ENGINE_ERROR",
                "denied_reason": f"{type(exc).__name__}: {exc}"[:200],
            }
        attempts.append({"time_range": tr, "decision": out.get("decision"), "n": len(out.get("results") or [])})
        if not out.get("ok") or out.get("results") or dry_run:
            break
    return {
        **base,
        "request_class": rc,
        "attempts": attempts,
        "results": list(out.get("results") or []),
        "ok": bool(out.get("ok")),
        "decision": out.get("decision"),
        "denied_reason": out.get("denied_reason"),
        "provider": out.get("provider"),
        "cache_hit": bool(out.get("cache_hit")),
        "as_of": out.get("as_of"),
    }
