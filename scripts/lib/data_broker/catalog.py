"""Data Broker catalog — advertise every read projection (including Watch Intelligence).

GET /api/v3/data-broker
GET /api/v3/data-broker/catalog

This is the index for operators and other apps. Watch Intelligence is one projection
in the same package as market_quote, symbol_profile, reentry_decision_desk, etc.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

# Existing + new projections. Keep paths stable; UI and other apps discover from here.
PROJECTIONS: list[dict[str, Any]] = [
    {
        "id": "market_quote",
        "module": "lib.data_broker.market_quote",
        "entrypoints": ["get_price_batch"],
        "http": [],
        "domain": "quotes",
        "description": "Batch live prices from market_quotes with get_best_quote waterfall fallback",
        "read_only": True,
        "provider_calls": "none_on_cache_hit",
    },
    {
        "id": "quote_batch",
        "module": "lib.data_broker.quote_batch",
        "entrypoints": ["quote_row_from_broker"],
        "http": [],
        "domain": "quotes",
        "description": "Canonical single-symbol quote via get_best_quote waterfall",
        "read_only": True,
    },
    {
        "id": "symbol_profile",
        "module": "lib.data_broker.symbol_profile",
        "entrypoints": ["get_symbol_profiles"],
        "http": [],
        "domain": "identity",
        "description": "Sector, industry, instrument_type, earnings from symbol_profiles",
        "read_only": True,
        "provider_calls": 0,
    },
    {
        "id": "analyst_rollup",
        "module": "lib.data_broker.analyst_rollup",
        "entrypoints": ["get_analyst_rollup"],
        "http": [],
        "domain": "street",
        "description": "Street consensus pills (pro_analyst_pills_latest.json)",
        "read_only": True,
        "provider_calls": 0,
    },
    {
        "id": "analyst_detail",
        "module": "lib.data_broker.analyst_detail",
        "entrypoints": ["get_analyst_targets"],
        "http": [],
        "domain": "street",
        "description": "Yahoo target history rollup",
        "read_only": True,
        "provider_calls": 0,
    },
    {
        "id": "catalyst_record",
        "module": "lib.data_broker.catalyst_record",
        "entrypoints": ["normalize_catalyst_row", "get_catalyst_record"],
        "http": [],
        "domain": "catalysts",
        "description": "Verified catalyst_events rows",
        "read_only": True,
        "provider_calls": 0,
    },
    {
        "id": "indicator_snapshot",
        "module": "lib.data_broker.indicator_snapshot",
        "entrypoints": ["get_indicator_snapshot"],
        "http": [],
        "domain": "technicals",
        "description": "RSI/MACD/ATR/OBV snapshot store",
        "read_only": True,
        "provider_calls": 0,
    },
    {
        "id": "portfolio_snapshot",
        "module": "lib.data_broker.portfolio_snapshot",
        "entrypoints": ["get_portfolio_snapshot"],
        "http": [],
        "domain": "portfolio",
        "description": "Book totals and holdings snapshot",
        "read_only": True,
        "provider_calls": 0,
    },
    {
        "id": "entry_plan",
        "module": "lib.data_broker.entry_plan",
        "entrypoints": ["get_entry_plans"],
        "http": [],
        "domain": "mechanics",
        "description": "Deterministic entry plan rows",
        "read_only": True,
        "provider_calls": 0,
    },
    {
        "id": "reentry_decision_desk",
        "module": "lib.data_broker.reentry_decision_desk",
        "entrypoints": ["build_decision_desk"],
        "http": ["GET /api/v2/reentry/decision-desk"],
        "domain": "reentry",
        "description": "Re-Entry READY/NEAR/BLOCK desk (broker-backed, no LLM)",
        "read_only": True,
        "provider_calls": 0,
        "consumers": ["Re-Entry", "Watch"],
    },
    {
        "id": "watch_intelligence",
        "module": "lib.data_broker.watch_intelligence",
        "entrypoints": [
            "list_watch_intelligence",
            "detail_watch_intelligence",
            "watch_filters",
            "watch_lists",
            "watch_reviews",
        ],
        "http": [
            "GET /api/v3/data-broker/watch-intelligence",
            "GET /api/v3/data-broker/watch-intelligence/{symbol}",
            "GET /api/v3/data-broker/watch-filters",
            "GET /api/v3/data-broker/watch-lists",
            "GET /api/v3/data-broker/watch-reviews/{symbol}",
        ],
        "domain": "watch",
        "description": (
            "Primary Watch Intelligence projection: identity, canonical quote, Street, "
            "Trade AI decision, CIO/Maria review artifacts, catalyst, relative performance, "
            "membership (starred/held/screener). Composes existing broker domains; zero "
            "provider calls on page load."
        ),
        "contract_version": "watch_intelligence.broker.v1",
        "read_only": True,
        "provider_calls": 0,
        "primary_ui": "/v3/watch",
        "composes": [
            "market_quote / watch_canonical_quote",
            "symbol_profile",
            "analyst_rollup / yahoo targets",
            "catalyst_record",
            "decision_packets (Trade AI)",
            "review artifacts (COMPLETE only with full provenance)",
            "operator_starred_symbols",
            "holdings.json",
            "screener_find_pins",
        ],
        "consumers": [
            "Watch Intelligence (primary /v3/watch)",
            "Portfolio",
            "Re-Entry",
            "Risk",
            "Active Trader",
            "Research Intelligence",
            "Agents",
            "Reports",
        ],
        "commands_not_broker": [
            "POST /api/v3/watch/commands/star",
            "POST /api/v3/watch/commands/list-membership",
            "POST /api/v3/watch/commands/alert",
            "POST /api/v3/watch/commands/refresh-data",
        ],
        "status": "active",
        "advertised": True,
    },
    {
        "id": "watch_decision_desk",
        "module": "lib.data_broker.watch_decision_desk",
        "entrypoints": [],
        "http": [],
        "domain": "watch",
        "description": "Legacy watch decision desk helper (prefer watch_intelligence for UI)",
        "read_only": True,
        "status": "legacy",
    },
    {
        "id": "cio_portfolio",
        "module": "lib.data_broker.cio_portfolio",
        "entrypoints": [
            "get_cio_snapshot",
            "get_cio_domain",
            "get_cio_material_changes",
        ],
        "http": [
            "GET /api/v3/data-broker/cio/snapshot",
            "GET /api/v3/data-broker/cio/domain/{domain}",
            "GET /api/v3/data-broker/cio/changes",
        ],
        "domain": "cio",
        "description": (
            "Unified CIO snapshot: portfolio, risk, watch, rotation, income, "
            "reconciliation — aggregated into one read. Composes existing broker "
            "domains; zero provider calls."
        ),
        "contract_version": "cio-snapshot-v1",
        "read_only": True,
        "provider_calls": 0,
        "composes": [
            "portfolio_snapshot",
            "risk_snapshot",
            "watch_intelligence",
            "rotation_ladders",
            "strategy_desk",
        ],
        "consumers": [
            "CIO Heartbeat",
            "Alex / CIO synthesis",
            "Command Center /v3/cio",
        ],
    },
]


def broker_catalog() -> dict[str, Any]:
    """Full Data Broker advertisement payload."""
    watch = next((p for p in PROJECTIONS if p["id"] == "watch_intelligence"), {})
    return {
        "ok": True,
        "service": "data_broker",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "package": "scripts/lib/data_broker",
        "description": (
            "Trade AI Data Broker — canonical read models. Applications must not "
            "re-select quotes, invent Street ratings, or fabricate LLM provenance."
        ),
        "index": "GET /api/v3/data-broker",
        "projection_count": len(PROJECTIONS),
        "projections": PROJECTIONS,
        "watch_intelligence": {
            "primary": True,
            "contract_version": watch.get("contract_version"),
            "http": watch.get("http"),
            "ui": watch.get("primary_ui"),
            "composes": watch.get("composes"),
            "consumers": watch.get("consumers"),
            "provider_calls_on_page_load": 0,
        },
        "rules": [
            "Broker projections are read-only",
            "Mutations use governed command endpoints, not projection POSTs",
            "Page load must not call LLM providers",
            "COMPLETE reviews require full immutable provenance",
            "Missing review → Provider NONE / Model NONE / Policy NO_CALL / Cost $0",
        ],
        "provider_calls": 0,
    }
