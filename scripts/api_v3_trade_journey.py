"""TradeInView trade journeys — HTTP surface over the read-only ``trade_journey`` projection.

  GET /api/v3/data-broker/trade-journeys[?days=30&symbol=NAVN]   open + recently closed trades (no price bars)
  GET /api/v3/data-broker/trade-journeys/{trade_id}               one journey with its daily price band

The projection (scripts/lib/data_broker/trade_journey.py) reads the CIO prospect record when its store is live and an
interim adapter over today's sources until then, labelled interim. Read-only; zero provider calls; no broker.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))


def get_list(query: dict | None = None) -> dict[str, Any]:
    from lib.data_broker.trade_journey import list_trade_journeys
    return list_trade_journeys(query or {})


def get_detail(trade_id: str, query: dict | None = None) -> dict[str, Any]:
    from lib.data_broker.trade_journey import detail_trade_journey
    return detail_trade_journey(unquote(trade_id), query or {})



def get_calendar(query: dict | None = None) -> dict[str, Any]:
    from lib.data_broker.trade_calendar import get_calendar as project
    return project(query or {})


def get_history(query: dict | None = None) -> dict[str, Any]:
    from lib.data_broker.holding_history import get_history as project
    return project(query or {})


def get_replay(query: dict | None = None) -> dict[str, Any]:
    """Explicit stored-only delegate; never imports the legacy chart provider."""
    from lib.data_broker.trade_replay import get_replay as project
    return project(query or {})
