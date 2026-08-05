"""Data Broker HTTP surface for Watch Intelligence (read-only).

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


def get_list(query: dict | None = None) -> dict[str, Any]:
    from lib.data_broker.watch_intelligence import list_watch_intelligence
    return list_watch_intelligence(query or {})


def get_detail(symbol: str) -> dict[str, Any]:
    from lib.data_broker.watch_intelligence import detail_watch_intelligence
    return detail_watch_intelligence(symbol)


def get_filters() -> dict[str, Any]:
    from lib.data_broker.watch_intelligence import watch_filters
    return watch_filters()


def get_lists() -> dict[str, Any]:
    from lib.data_broker.watch_intelligence import watch_lists
    return watch_lists()


def get_reviews(symbol: str) -> dict[str, Any]:
    from lib.data_broker.watch_intelligence import watch_reviews
    return watch_reviews(symbol)
