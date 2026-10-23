"""Data Broker HTTP surface (catalog + Watch Intelligence).

Index / catalog (advertise all projections):
  GET /api/v3/data-broker
  GET /api/v3/data-broker/catalog

Watch Intelligence (composes existing broker domains):
  GET /api/v3/data-broker/watch-intelligence
  GET /api/v3/data-broker/watch-intelligence/{symbol}
  GET /api/v3/data-broker/watch-filters
  GET /api/v3/data-broker/watch-lists
  GET /api/v3/data-broker/watch-curation   (My Watchlist + System Suggests, operator 2026-10-23)
  GET /api/v3/data-broker/watch-universe   (Full universe on Watch: curator rank + position facts + filters)
  GET /api/v3/data-broker/watch-reviews/{symbol}
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def get_catalog() -> dict[str, Any]:
    """Advertise the full Data Broker surface (existing + Watch Intelligence)."""
    from lib.data_broker.catalog import broker_catalog
    return broker_catalog()


def get_list(query: dict | None = None) -> dict[str, Any]:
    from lib.data_broker.watch_intelligence import list_watch_intelligence
    out = list_watch_intelligence(query or {})
    # Advertise composition so clients know this is the broker package, not a side API
    out.setdefault("data_broker", {
        "package": "scripts/lib/data_broker",
        "projection": "watch_intelligence",
        "contract_version": out.get("data_contract_version") or out.get("contract_version"),
        "catalog": "/api/v3/data-broker",
        "composes": [
            "watch_canonical_quote",
            "symbol_profile",
            "analyst_rollup",
            "yahoo_analyst_targets",
            "catalyst_events",
            "decision_packets",
            "review_artifacts",
            "operator_starred_symbols",
            "holdings",
            "screener_find_pins",
        ],
        "provider_calls": 0,
        "read_only": True,
    })
    return out


def get_detail(symbol: str) -> dict[str, Any]:
    from lib.data_broker.watch_intelligence import detail_watch_intelligence
    out = detail_watch_intelligence(symbol)
    out.setdefault("data_broker", {
        "package": "scripts/lib/data_broker",
        "projection": "watch_intelligence",
        "contract_version": out.get("data_contract_version") or out.get("contract_version"),
        "catalog": "/api/v3/data-broker",
        "provider_calls": 0,
        "read_only": True,
    })
    return out


def get_prospects(query: dict | None = None) -> dict[str, Any]:
    """GET /api/v3/data-broker/watch-prospects — the Watch page's prospect lanes (interim adapter until the
    cio_prospect projection is live; lib/data_broker/watch_prospects.py)."""
    from lib.data_broker.watch_prospects import list_watch_prospects
    return list_watch_prospects(query or {})


def get_curation(query: dict | None = None) -> dict[str, Any]:
    """GET /api/v3/data-broker/watch-curation — My Watchlist (every operator name, starred first, never capped) and
    System Suggests (top N of the Full universe ranking, rotating with reasons); lib/data_broker/watch_curation.py."""
    from lib.data_broker.watch_curation import list_watch_curation
    return list_watch_curation(query or {})


def get_symbol_search(query: dict | None = None) -> dict[str, Any]:
    """GET /api/v3/data-broker/watch-symbol-search?q= — ticker / company typeahead for the Add-symbol box."""
    from lib.data_broker.watch_curation import list_symbol_search
    return list_symbol_search(query or {})


def get_universe(query: dict | None = None) -> dict[str, Any]:
    """GET /api/v3/data-broker/watch-universe — the curator's ranked list with held / formerly held / never held,
    the last round trip and re-entry advice per row, and the position filters (lib/data_broker/watch_universe.py)."""
    from lib.data_broker.watch_universe import list_watch_universe
    return list_watch_universe(query or {})


def get_filters() -> dict[str, Any]:
    from lib.data_broker.watch_intelligence import watch_filters
    out = watch_filters()
    out.setdefault("data_broker", {"projection": "watch_filters", "catalog": "/api/v3/data-broker"})
    return out


def get_lists() -> dict[str, Any]:
    from lib.data_broker.watch_intelligence import watch_lists
    out = watch_lists()
    out.setdefault("data_broker", {"projection": "watch_lists", "catalog": "/api/v3/data-broker"})
    return out


def get_reviews(symbol: str) -> dict[str, Any]:
    from lib.data_broker.watch_intelligence import watch_reviews
    out = watch_reviews(symbol)
    out.setdefault("data_broker", {"projection": "watch_reviews", "catalog": "/api/v3/data-broker"})
    return out
