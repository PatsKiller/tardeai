"""Data Broker: registry, read models, and canonical data helpers.

See docs/DATA_ARCHITECTURE_AUDIT_2026_07_31.md (if present) and
docs/design/watchlist-intelligence-v3/DATA_BROKER_WATCH_CONSUMERS.md.

Core modules (existing):
  market_quote, quote_batch, symbol_profile, analyst_rollup, analyst_detail,
  catalyst_record, indicator_snapshot, portfolio_snapshot, entry_plan,
  reentry_decision_desk, sector_momentum, ...

Watch Intelligence (enhanced / advertised):
  watch_intelligence — primary /v3/watch projection
  catalog — GET /api/v3/data-broker index of all projections

HTTP:
  GET /api/v3/data-broker
  GET /api/v3/data-broker/catalog
  GET /api/v3/data-broker/watch-intelligence
  GET /api/v3/data-broker/watch-intelligence/{symbol}
  GET /api/v3/data-broker/watch-filters
  GET /api/v3/data-broker/watch-lists
  GET /api/v3/data-broker/watch-reviews/{symbol}
"""
from __future__ import annotations

from lib.data_broker.catalog import PROJECTIONS, broker_catalog

__all__ = [
    "PROJECTIONS",
    "broker_catalog",
]
