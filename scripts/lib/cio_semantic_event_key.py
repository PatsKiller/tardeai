"""
CIO Semantic Event Key — Deduplication across publishers.

Produces deterministic hash from business transition, not wall-clock timestamp.
All publishers (primary writer, legacy adapter, heartbeat) derive the same key
for the same underlying business event.

Gate-C component.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any


def canonicalize_transition(data: dict[str, Any]) -> str:
    """Canonical JSON representation for hashing."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"))


def compute_semantic_event_key(event_type: str, aggregate: dict[str, Any]) -> str:
    """Produce a deterministic hash from event type + business aggregate.

    Example for risk.stop_triggered:
        aggregate = {
            "account_id": "...",
            "symbol": "AAPL",
            "stop_id": "stop-123",
            "previous_state": "active",
            "new_state": "triggered",
        }

    All publishers observing the same transition produce the same key.
    """
    event_canonical = canonicalize_transition({
        "event_type": event_type,
        "aggregate": aggregate,
    })
    return hashlib.sha256(event_canonical.encode("utf-8")).hexdigest()


def generate_idempotency_key(prefix: str, symbol: str, timestamp: str | None = None) -> str:
    """Generate a unique idempotency key for event deduplication.

    Combines a domain prefix, symbol, and timestamp to create a stable
    deduplication key.  When timestamp is omitted, UTC now is used.

    Pattern: {prefix}:{symbol}:{iso_timestamp}
    """
    ts = timestamp or datetime.now(timezone.utc).isoformat()
    raw = f"{prefix}:{symbol}:{ts}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


class SemanticEventDeduplicator:
    """Tracks seen semantic event keys to prevent duplicate publication."""

    def __init__(self, max_size: int = 10000):
        self._seen: set[str] = set()
        self._max_size = max_size

    def is_duplicate(self, semantic_key: str) -> bool:
        return semantic_key in self._seen

    def mark_seen(self, semantic_key: str) -> None:
        if len(self._seen) >= self._max_size:
            # Simple FIFO eviction: clear oldest half
            self._seen = set(list(self._seen)[self._max_size // 2:])
        self._seen.add(semantic_key)

    def check_and_mark(self, semantic_key: str) -> bool:
        """Returns True if this is a new (non-duplicate) key, and marks it seen."""
        if self.is_duplicate(semantic_key):
            return False
        self.mark_seen(semantic_key)
        return True
