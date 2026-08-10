"""
CIO Legacy Event Adapter — One-way normalization from legacy event_detector.

Transforms specific legacy event types into CIOEventBus events.
No reverse adapter. No event ping-pong. No duplicate authority.

Gate-C component.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Optional

from scripts.lib.cio_semantic_event_key import compute_semantic_event_key


# Events that are adapted from legacy -> CIOEventBus
LEGACY_TO_CIO_EVENT_MAP = {
    "STOP_TRIGGERED": "risk.stop_triggered",
    "MARKET_REGIME_CHANGE": "market.regime_change",
}

# Events that remain legacy-only (not adapted)
LEGACY_ONLY_EVENTS = frozenset({
    "SEC_INSIDER_BUY",
    "RSI_EXTREME",
    "FRED_RATE_CHANGE",
    "DIVIDEND_CUT",
    "EARNINGS_BEAT",
    "IRMAA_THRESHOLD",
    "INCOME_FLOOR_RISK",
    "PORTFOLIO_FRESH_NEEDED",
})


def adapt_legacy_event(
    legacy_event_type: str,
    legacy_payload: dict[str, Any],
    source_event_id: str,
) -> Optional[dict[str, Any]]:
    """Adapt a legacy event to CIOEventBus format. Returns None if not adapted.

    The source_event_id preserves provenance.
    The semantic_event_key enables cross-publisher deduplication.
    """
    if legacy_event_type not in LEGACY_TO_CIO_EVENT_MAP:
        return None  # Legacy-only event, not adapted

    cio_event_type = LEGACY_TO_CIO_EVENT_MAP[legacy_event_type]

    if legacy_event_type == "STOP_TRIGGERED":
        symbol = legacy_payload.get("symbol", "")
        aggregate = {
            "symbol": symbol,
            "stop_id": legacy_payload.get("stop_id", ""),
            "previous_state": legacy_payload.get("previous_state", "active"),
            "new_state": "triggered",
        }
        semantic_key = compute_semantic_event_key(cio_event_type, aggregate)

        return {
            "event_type": cio_event_type,
            "payload": {
                "symbol": symbol,
                "stop_id": legacy_payload.get("stop_id"),
                "trigger_price": legacy_payload.get("trigger_price"),
                "previous_state": legacy_payload.get("previous_state"),
            },
            "source_event_id": source_event_id,
            "semantic_event_key": semantic_key,
            "legacy_source": "event_detector",
        }

    if legacy_event_type == "MARKET_REGIME_CHANGE":
        regime = legacy_payload.get("regime", "")
        aggregate = {
            "regime": regime,
            "previous_regime": legacy_payload.get("previous_regime", ""),
        }
        semantic_key = compute_semantic_event_key(cio_event_type, aggregate)

        return {
            "event_type": cio_event_type,
            "payload": {
                "regime": regime,
                "previous_regime": legacy_payload.get("previous_regime"),
                "confidence": legacy_payload.get("confidence"),
            },
            "source_event_id": source_event_id,
            "semantic_event_key": semantic_key,
            "legacy_source": "event_detector",
        }

    return None


def is_adapted_event(legacy_event_type: str) -> bool:
    """Check if a legacy event type is adapted to CIOEventBus."""
    return legacy_event_type in LEGACY_TO_CIO_EVENT_MAP


def is_legacy_only(legacy_event_type: str) -> bool:
    """Check if a legacy event type remains legacy-only."""
    return legacy_event_type in LEGACY_ONLY_EVENTS
