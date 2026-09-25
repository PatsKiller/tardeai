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
    # CampaignInterfaces@v1 §5 — forward-only settlement / ownership / curation
    provider_message_id: str | None = None
    provider_settled_at: datetime | None = None
    provider_settlement_state: str = "UNSETTLED"
    delivery_owner: str | None = None  # gateway|legacy
    gateway_mode_at_dispatch: str | None = None  # OFF|SHADOW|CANARY|ACTIVE
    curation_kind: str | None = None  # deterministic|llm_curated
    curation_provenance: dict[str, Any] = field(default_factory=dict)
    subject_guid: str | None = None  # read-only from identity spine; never minted here
    # §2 envelope extras (optional; filled by producers that emit campaign envelopes)
    source_sha: str | None = None
    produced_at: datetime | None = None
    parent_id: str | None = None
    parent_kind: str | None = None
    lifecycle_state: str | None = None
    provenance: dict[str, Any] = field(default_factory=dict)

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
        self._default_lineage()
        if not self.curation_kind:
            from scripts.lib.campaign_interfaces_b import map_curation_mode_to_kind

            self.curation_kind = map_curation_mode_to_kind(self.curation_mode)
        # Historic/legacy rows keep UNKNOWN_LEGACY; never invent identity for them.
        state = (self.provider_settlement_state or "").strip().upper()
        if state not in ("UNSETTLED", "SETTLED", "FAILED", "UNKNOWN_LEGACY"):
            self.provider_settlement_state = "UNSETTLED"
        if not (self.source_sha or "").strip():
            from scripts.lib.runtime_identity import resolve_source_sha

            self.source_sha = resolve_source_sha()
        return self

    def _default_lineage(self) -> None:
        """Default ``causation_id`` / ``parent_event_id`` — the Phase 4 memory join.

        Measured 2026-09-22: both columns were NULL on all 54,928 ledger rows.
        They have existed since the 2026-09-05 ledger migration; nothing ever
        wrote them, so no event could be traced to the one that caused it.

        Precedence runs strongest real link first. A producer-supplied value is
        NEVER overwritten, and a link is never fabricated from a non-event
        identifier — ``run_id``, ``incident_id`` and ``wake_id`` are not event
        ids and must not be laundered into an event-id column.

        ``parent_event_id`` — the event this one is a direct CHILD of:
            reply_to_event_id -> parent_id (only when parent_kind names a comm
            event) -> supersedes_event_id -> NULL.

          The NULL tail is deliberate and load-bearing. A root event has no
          parent; writing its own id here would be a false statement AND would
          make any recursive walk of the lineage tree loop forever. So this
          column stays sparse until real reply/supersede lineage exists. That
          is an honest measurement of the lineage the system actually has, not
          a column we failed to fill.

        ``causation_id`` — the event that CAUSED this one:
            reply_to_event_id -> parent_event_id -> supersedes_event_id
            -> own event_id.

          The self-referencing tail is the standard event-sourcing encoding for
          a ROOT message, and it is a marker rather than an invented ancestor:
          a cron-scheduled alert is caused by a schedule, not by another ledger
          event. ``causation_id = event_id`` means exactly "nothing in this
          ledger caused this", and ``causation_id <> event_id`` is the precise
          predicate for "has an upstream cause" (see ``is_root_event``).
          Leaving it NULL would instead keep the column unjoinable and
          indistinguishable from the 54,928 unwired rows this change fixes.
        """
        parent_kind = (self.parent_kind or "").strip().lower()
        # An open lineage scope (scripts/lib/event_lineage.py) names the event
        # this send answers -- e.g. the operator's inbound message, or the turn
        # a Hermes completion was requested from. It applies only when the
        # event itself names no reply/parent/supersede link, and it never
        # overrides a producer-supplied value.
        if (self.parent_event_id is None and self.causation_id is None
                and str(getattr(self, "direction", "") or "").upper() != "INBOUND"
                and not self.reply_to_event_id and not self.supersedes_event_id
                and not (self.parent_id and parent_kind == "comm_event")):
            try:
                from scripts.lib.event_lineage import current as _current_lineage

                _lin = _current_lineage()
            except Exception:  # noqa: BLE001 — lineage never breaks a write
                _lin = None
            if _lin and _lin.parent_event_id != self.event_id:
                self.parent_event_id = _lin.parent_event_id
                if _lin.causation_id and _lin.causation_id != self.event_id:
                    self.causation_id = _lin.causation_id
        if self.parent_event_id is None:
            self.parent_event_id = (
                self.reply_to_event_id
                or (self.parent_id if parent_kind == "comm_event" else None)
                or self.supersedes_event_id
                or None
            )
        if self.causation_id is None:
            self.causation_id = (
                self.reply_to_event_id
                or self.parent_event_id
                or self.supersedes_event_id
                or self.event_id
            )

    def to_row(self) -> dict[str, Any]:
        self.mint_identity()
        d = asdict(self)
        # Not persisted as columns
        d.pop("intended_action", None)
        d.pop("observation_version", None)
        d.pop("channels", None)
        return d

    def apply_provider_settlement(
        self,
        *,
        provider_message_id: str | None,
        status: str,
        settled_at: datetime | None = None,
        delivery_owner: str | None = None,
        gateway_mode: str | None = None,
        failure_reason: str | None = None,
    ) -> "CommunicationEvent":
        """Forward-only settlement identity on the event (defect 6)."""
        now = settled_at or datetime.now(timezone.utc)
        st = (status or "").strip().upper()
        if st in ("SENT", "DELIVERED", "ACKNOWLEDGED") and provider_message_id:
            self.provider_message_id = provider_message_id
            self.provider_settled_at = now
            self.provider_settlement_state = "SETTLED"
        elif st in ("FAILED", "BOUNCED"):
            self.provider_settled_at = now
            self.provider_settlement_state = "FAILED"
            if failure_reason:
                coords = dict(self.provider_coordinates or {})
                coords["failure_reason"] = failure_reason
                self.provider_coordinates = coords
        elif st == "LEGACY_DELIVERED":
            # Legacy path: do not invent provider identity.
            self.provider_settlement_state = "UNKNOWN_LEGACY"
            self.provider_settled_at = now
        if delivery_owner:
            self.delivery_owner = delivery_owner
        if gateway_mode:
            self.gateway_mode_at_dispatch = gateway_mode
        return self


def is_root_event(event: CommunicationEvent) -> bool:
    """True when nothing in this ledger caused the event.

    The exact predicate behind the ``causation_id`` default: a root event
    points at itself, a caused event points at its cause. Consumers must use
    this rather than testing for NULL, which now means "never minted".
    """
    return bool(event.event_id) and event.causation_id == event.event_id


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
