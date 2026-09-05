"""CommunicationEvent@v2 contract."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from scripts.lib.comms.identity import (
    content_hash_for,
    idempotency_key_for,
    new_event_id,
    protected_facts_hash_for,
)

SCHEMA_VERSION = "CommunicationEvent@v2"

# Message classes that must carry non-empty protected_facts (fail closed).
PROTECTED_FACT_REQUIRED_CLASSES = frozenset(
    {
        "approval",
        "protection_incident",
        "broker_fact",
        "order_state",
        "risk_limit",
        "account_fact",
    }
)

REQUIRED_ALWAYS = (
    "direction",
    "event_type",
    "message_class",
    "producer",
    "subject_key",
    "retention_class",
)


@dataclass
class CommunicationEvent:
    """Canonical communication ledger row (logical message)."""

    direction: str
    event_type: str
    message_class: str
    producer: str
    subject_key: str
    retention_class: str
    event_id: str | None = None
    schema_version: str = SCHEMA_VERSION
    severity: str = "info"
    audience: str = "operator"
    producer_version: str | None = None
    producer_event_id: str | None = None
    idempotency_key: str | None = None
    thread_id: str | None = None
    correlation_id: str | None = None
    causation_id: str | None = None
    parent_event_id: str | None = None
    reply_to_event_id: str | None = None
    incident_id: str | None = None
    supersedes_event_id: str | None = None
    version: int = 1
    entity_refs: dict[str, Any] = field(default_factory=dict)
    protected_facts: dict[str, Any] = field(default_factory=dict)
    protected_facts_hash: str | None = None
    authoritative_sources: list[dict[str, Any]] = field(default_factory=list)
    command_center_url: str | None = None
    external_links: list[dict[str, Any]] = field(default_factory=list)
    content_classification: str = "operational"
    expires_at: datetime | None = None
    legal_hold: bool = False
    redaction_policy: str | None = None
    curation_mode: str = "DETERMINISTIC"
    content_hash: str | None = None
    sanitized_body: str | None = None
    short_summary: str | None = None
    raw_body_ref: str | None = None
    provider_coordinates: dict[str, Any] = field(default_factory=dict)
    delivery_policy: dict[str, Any] = field(default_factory=dict)
    knowledge_eligibility: str = "ineligible"
    knowledge_status: str = "none"
    build_sha: str | None = None
    release_id: str | None = None
    run_id: str | None = None
    source_system: str | None = None
    source_agent: str | None = None
    source_job: str | None = None
    observed_at: datetime | None = None
    created_at: datetime | None = None
    intended_action: str = "notify"
    observation_version: str = "1"
    channels: list[str] = field(default_factory=lambda: ["telegram"])
    payload: dict[str, Any] = field(default_factory=dict)

    def mint_identity(self) -> "CommunicationEvent":
        """Assign event_id / idempotency / hashes if missing. Never overwrites event_id."""
        if not self.event_id:
            self.event_id = new_event_id()
        if not self.idempotency_key:
            self.idempotency_key = idempotency_key_for(
                producer=self.producer,
                event_type=self.event_type,
                subject_key=self.subject_key,
                intended_action=self.intended_action,
                entity_refs=self.entity_refs,
                observation_version=self.observation_version,
            )
        if not self.protected_facts_hash:
            self.protected_facts_hash = protected_facts_hash_for(self.protected_facts)
        if not self.content_hash:
            self.content_hash = content_hash_for(
                sanitized_body=self.sanitized_body,
                protected_facts=self.protected_facts,
                short_summary=self.short_summary,
            )
        if self.created_at is None:
            self.created_at = datetime.now(timezone.utc)
        if self.thread_id is None:
            self.thread_id = f"thr_{self.subject_key}"
        if self.correlation_id is None:
            self.correlation_id = self.thread_id
        return self

    def to_row(self) -> dict[str, Any]:
        self.mint_identity()
        d = asdict(self)
        # Not persisted as columns
        d.pop("intended_action", None)
        d.pop("observation_version", None)
        d.pop("channels", None)
        return d


def required_missing(event: CommunicationEvent) -> list[str]:
    """Return missing/invalid required fields. Empty list => pass fail-closed gate."""
    missing: list[str] = []
    for name in REQUIRED_ALWAYS:
        val = getattr(event, name, None)
        if val is None or (isinstance(val, str) and not val.strip()):
            missing.append(name)
    if event.direction not in ("INBOUND", "OUTBOUND"):
        missing.append("direction_invalid")
    if event.message_class in PROTECTED_FACT_REQUIRED_CLASSES and not event.protected_facts:
        missing.append("protected_facts")
    if event.message_class in PROTECTED_FACT_REQUIRED_CLASSES and not event.authoritative_sources:
        missing.append("authoritative_sources")
    # Retention always required non-empty (already in REQUIRED_ALWAYS).
    # Recipient/delivery policy required when outbound with channels.
    if event.direction == "OUTBOUND":
        if not event.channels and not (event.delivery_policy or {}).get("channels"):
            missing.append("delivery_channels")
        if event.audience is None or str(event.audience).strip() == "":
            missing.append("audience")
    return missing
