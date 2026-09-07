# VENDORED: replaced by campaign_interfaces at integration
"""Lane-B local copy of CampaignInterfaces@v1 identifier minting.

Integration step 5 replaces imports of this module with
`scripts.lib.campaign_interfaces`. Other lanes must not import this file.

Namespaces follow INTERFACE_CONTRACTS §1:
  uuid5(NAMESPACE_URL, "tradeai:campaign:<name>") then uuid5(that, key).

SubjectGuid is NOT redefined here — use scripts.lib.cio_subject_guid /
security_identity spine (integration-owned).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

INTERFACE_VERSION = "CampaignInterfaces@v1"
COMM_EVENT_SCHEMA = "CommunicationEvent@v2"
RECEIPT_SCHEMA = "AgentConsumptionReceipt@v2"
CURATION_PROVENANCE_SCHEMA = "CurationProvenance@v1"


def _ns(name: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"tradeai:campaign:{name}")


ns_comm = _ns("comm")
ns_thread = _ns("thread")
ns_receipt = _ns("receipt")

# Documented fallback if security_identity spine is unavailable at import time.
# Do not redefine SubjectGuid; consumers resolve via cio_subject_guid.
NAMESPACE_URL_PREFIX = "tradeai:campaign:"

SOURCE_KINDS = frozenset(
    {"comm_event", "research_object", "memory_fact", "operator_turn"}
)
EFFECT_KINDS = frozenset(
    {
        "none",
        "changed_question",
        "changed_priority",
        "changed_view",
        "changed_commitment",
    }
)
PROVIDER_SETTLEMENT_STATES = frozenset(
    {"UNSETTLED", "SETTLED", "FAILED", "UNKNOWN_LEGACY"}
)
DELIVERY_OWNERS = frozenset({"gateway", "legacy"})
GATEWAY_MODES = frozenset({"OFF", "SHADOW", "CANARY", "ACTIVE"})
CURATION_KINDS = frozenset({"deterministic", "llm_curated"})
PARENT_KINDS = frozenset(
    {"wake", "comm_event", "research_object", "commitment", "outcome"}
)
RETENTION_CLASSES = frozenset(
    {"operational_90d", "evidence_2y", "permanent"}
)


def mint_communication_event_id(
    channel: str,
    provider_thread: str,
    provider_msg_id: str,
    occurred_at: str,
) -> str:
    """CommunicationEventId = uuid5(ns_comm, channel + provider_thread + provider_msg_id + occurred_at)."""
    key = f"{channel}|{provider_thread}|{provider_msg_id}|{occurred_at}"
    return str(uuid.uuid5(ns_comm, key))


def mint_thread_id(subject_guid: str, channel: str, root_event_id: str) -> str:
    """ThreadId = uuid5(ns_thread, subject_guid + channel + root_event_id)."""
    key = f"{subject_guid}|{channel}|{root_event_id}"
    return str(uuid.uuid5(ns_thread, key))


def mint_receipt_id(
    agent_id: str, source_kind: str, source_id: str, purpose: str
) -> str:
    """ConsumptionReceiptId = uuid5(ns_receipt, agent_id + source_kind + source_id + purpose).

    Prefixed ``acr_`` for continuity with AgentConsumptionReceipt@v1 identity shape;
    the uuid5 body remains the deterministic campaign identifier.
    """
    key = f"{agent_id}|{source_kind}|{source_id}|{purpose}"
    return f"acr_{uuid.uuid5(ns_receipt, key)}"


def envelope(
    *,
    schema_version: str,
    source_sha: str,
    produced_at: str | None = None,
    correlation_id: str,
    idempotency_key: str,
    lifecycle_state: str,
    provenance: dict[str, Any] | None = None,
    parent_id: str | None = None,
    parent_kind: str | None = None,
    retention_class: str = "operational_90d",
) -> dict[str, Any]:
    """Mandatory §2 envelope fields on every campaign object."""
    if produced_at is None:
        produced_at = datetime.now(timezone.utc).isoformat()
    return {
        "schema_version": schema_version,
        "source_sha": source_sha,
        "produced_at": produced_at,
        "correlation_id": correlation_id,
        "idempotency_key": idempotency_key,
        "parent_id": parent_id,
        "parent_kind": parent_kind,
        "retention_class": retention_class,
        "lifecycle_state": lifecycle_state,
        "provenance": provenance
        if provenance is not None
        else {"producer": "unknown", "inputs": [], "policy_decisions": [], "llm": None},
    }


def map_curation_mode_to_kind(curation_mode: str | None) -> str:
    """Map internal curation_mode → §5/§7 curation_kind."""
    mode = (curation_mode or "").strip().upper()
    if mode in ("LLM_SUMMARY", "LLM_CHALLENGE"):
        return "llm_curated"
    return "deterministic"


def try_import_security_identity_ns() -> str:
    """Return documented spine prefix; never redefine SubjectGuid."""
    try:
        from scripts.lib import security_identity  # noqa: F401

        return "tradeai:"  # security_identity._uuid uses tradeai:{namespace}:{value}
    except Exception:
        return NAMESPACE_URL_PREFIX
