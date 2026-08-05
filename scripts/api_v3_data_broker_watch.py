"""Data Broker HTTP surface (catalog + Watch Intelligence).

Index / catalog (advertise all projections):
  GET /api/v3/data-broker
  GET /api/v3/data-broker/catalog

Watch Intelligence (composes existing broker domains):
  GET /api/v3/data-broker/watch-intelligence
  GET /api/v3/data-broker/watch-intelligence/{symbol}
  GET /api/v3/data-broker/watch-filters
  GET /api/v3/data-broker/watch-lists
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
