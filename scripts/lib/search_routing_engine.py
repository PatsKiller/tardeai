"""search_routing_engine.py — import alias for the search routing engine (``scripts/lib/search_router.py``).

Agent Q's scalp hot tier (branch n8nmat/scalp-hot-tier) imports ``lib.search_routing_engine.route_search``.
One engine, one module: this file re-exports, it holds no logic. AUTHORITY: READ_ONLY_ADVISORY.
"""
from __future__ import annotations

try:
    from scripts.lib.search_router import (  # noqa: F401
        SearchRequest, RoutedResponse, engine_enabled, route, route_query, route_search,
    )
except ImportError:  # pragma: no cover - dual-import shape
    from lib.search_router import (  # type: ignore  # noqa: F401
        SearchRequest, RoutedResponse, engine_enabled, route, route_query, route_search,
    )

__all__ = ["SearchRequest", "RoutedResponse", "engine_enabled", "route", "route_query", "route_search"]
