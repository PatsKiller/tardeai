"""
CIO Event Outbox — Transactional outbox pattern for DB-backed mutations.

Defines the schema for the domain_event_outbox table and provides helpers
for outbox row creation and idempotent publishing.

The outbox row is created in the same DB transaction as the business mutation.
A separate publisher (poll or NOTIFY-driven) reads unpublished rows and
writes normalized events to CIOEventBus.

Gate-C component. Schema definition only — no DB migration in this gate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


# Event types that support transactional outbox publication
OUTBOX_EVENT_TYPES = frozenset({
    "risk.stop_triggered",
    "reconciliation.drift",
    "cost_basis.material_change",
    "holding.material_exposure_change",
    "model_portfolio.ips_deviation",
})

# File-backed mutation events (not transactional, post-write publish)
FILE_EVENT_TYPES = frozenset({
    "watch.lifecycle_change",
    "catalyst.materiality_assessed",
    "analyst.action_material",
    "operator.request_received",
})

# External ingestion events
EXTERNAL_EVENT_TYPES = frozenset({})


@dataclass
class OutboxRow:
    """Schema for a domain_event_outbox row."""
    event_id: str
    event_type: str
    aggregate_id: str
    payload: dict[str, Any] = field(default_factory=dict)
    semantic_event_key: Optional[str] = None
    source_event_id: Optional[str] = None
    occurred_at: Optional[str] = None
    published: bool = False

    def __post_init__(self):
        if self.occurred_at is None:
            self.occurred_at = datetime.now(timezone.utc).isoformat()

    @property
    def mutation_backend(self) -> str:
        if self.event_type in OUTBOX_EVENT_TYPES:
            return "DB"
        if self.event_type in FILE_EVENT_TYPES:
            return "FILE"
        if self.event_type in EXTERNAL_EVENT_TYPES:
            return "EXTERNAL"
        return "FILE"

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "aggregate_id": self.aggregate_id,
            "payload": self.payload,
            "semantic_event_key": self.semantic_event_key,
            "source_event_id": self.source_event_id,
            "occurred_at": self.occurred_at,
            "published": self.published,
        }


def classify_mutation_backend(event_type: str) -> str:
    """Classify an event's mutation backend: DB, FILE, or EXTERNAL."""
    if event_type in OUTBOX_EVENT_TYPES:
        return "DB"
    if event_type in FILE_EVENT_TYPES:
        return "FILE"
    if event_type in EXTERNAL_EVENT_TYPES:
        return "EXTERNAL"
    return "FILE"
