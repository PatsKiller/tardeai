"""
CIO Mutation Publisher — File-backed event publication helpers.

Provides utilities for publishing CIOEventBus events immediately after
file-backed mutations (e.g., writing stops.json).  These events are
NOT transactional — they are published post-write as a best-effort
notification that a mutation occurred.

Gate-C component.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from scripts.lib.cio_semantic_event_key import (
    compute_semantic_event_key,
    generate_idempotency_key,
)


def publish_stop_triggered(
    symbol: str,
    account_id: str,
    stop_id: str,
    previous_state: str,
    new_state: str,
    trigger_price: Optional[float] = None,
    extra_meta: Optional[dict[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    """Publish a risk.stop_triggered event on the CIOEventBus.

    Designed to be called immediately after a stop mutation is persisted to
    stops.json.  Includes semantic_event_key for cross-publisher deduplication
    so the heartbeat backstop does not double-report the same transition.

    Returns the event dict that was published, or None if the bus is unavailable.
    """
    try:
        from scripts.lib.cio_event_bus import CIOEventBus

        bus = CIOEventBus()

        aggregate = {
            "account_id": account_id,
            "symbol": symbol,
            "stop_id": stop_id,
            "previous_state": previous_state,
            "new_state": new_state,
        }
        semantic_key = compute_semantic_event_key("risk.stop_triggered", aggregate)
        timestamp = datetime.now(timezone.utc).isoformat()
        source_event_id = f"mut-{uuid.uuid4().hex[:12]}"
        idem_key = generate_idempotency_key("stop", symbol, timestamp)

        payload = {
            "symbol": symbol,
            "account_id": account_id,
            "stop_id": stop_id,
            "previous_state": previous_state,
            "new_state": new_state,
            "idempotency_key": idem_key,
        }
        if trigger_price is not None:
            payload["trigger_price"] = trigger_price
        if extra_meta:
            payload.update(extra_meta)

        evt = bus.emit(
            "risk.stop_triggered",
            payload,
            source="mutation_publisher",
            priority="HIGH",
            source_event_id=source_event_id,
            semantic_event_key=semantic_key,
        )
        return evt.to_dict()
    except Exception:
        return None


def publish_stop_updated(
    symbol: str,
    account_id: str,
    old_stop_price: float,
    new_stop_price: float,
    notes: str = "",
) -> Optional[dict[str, Any]]:
    """Publish a risk.stop_triggered event for a stop-update mutation.

    An updated stop is a business transition: the old stop level is being
    replaced.  This is published as stop_triggered with new_state="updated"
    rather than "triggered" so consumers can distinguish the transition type.
    """
    stop_id = f"stop-{symbol.lower()}"
    extra_meta = {
        "old_stop_price": old_stop_price,
        "new_stop_price": new_stop_price,
        "transition_notes": notes,
    }
    return publish_stop_triggered(
        symbol=symbol,
        account_id=account_id,
        stop_id=stop_id,
        previous_state="active",
        new_state="updated",
        trigger_price=new_stop_price,
        extra_meta=extra_meta,
    )


def publish_stop_removed(
    symbol: str,
    account_id: str,
) -> Optional[dict[str, Any]]:
    """Publish a risk.stop_triggered event when a stop is removed."""
    stop_id = f"stop-{symbol.lower()}"
    return publish_stop_triggered(
        symbol=symbol,
        account_id=account_id,
        stop_id=stop_id,
        previous_state="active",
        new_state="removed",
    )
