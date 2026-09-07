# VENDORED: replaced by campaign_interfaces at integration
"""Lane-A local copy of CampaignInterfaces@v1 identifier minting.

Integration step 5 replaces imports of this module with
`scripts.lib.campaign_interfaces`. Do not let other lanes import this file.
"""
from __future__ import annotations

import uuid
from typing import Iterable

# Spine-aligned namespace: uuid5(NAMESPACE_URL, "tradeai:<ns>") then uuid5(that, key)
def _ns(name: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"tradeai:campaign:{name}")


ns_wake = _ns("wake")
ns_commit = _ns("commit")
ns_receipt = _ns("receipt")
ns_comm = _ns("comm")
ns_thread = _ns("thread")
ns_research = _ns("research")
ns_outcome = _ns("outcome")
ns_belief = _ns("belief")
ns_memory_fact = _ns("memory_fact")
ns_operator_turn = _ns("operator_turn")
ns_view = _ns("view")
ns_schedule_slot = _ns("schedule_slot")

INTERFACE_VERSION = "CampaignInterfaces@v1"
WAKE_SCHEMA = "WakeRecord@v2"
RECEIPT_SCHEMA = "AgentConsumptionReceipt@v2"
COMMITMENT_SCHEMA = "CommitmentRecord@v2"
VIEW_SCHEMA = "AgentView@v2"
SCHEDULE_SCHEMA = "PersistentWakeScheduleContract@v1"


def mint_wake_id(agent_id: str, wake_reason: str, schedule_slot_utc: str, subject_guid: str) -> str:
    key = f"{agent_id}|{wake_reason}|{schedule_slot_utc}|{subject_guid}"
    return str(uuid.uuid5(ns_wake, key))


def mint_commitment_id(
    wake_id: str, subject_guid: str, commitment_kind: str, normalized_claim: str
) -> str:
    key = f"{wake_id}|{subject_guid}|{commitment_kind}|{normalized_claim}"
    return str(uuid.uuid5(ns_commit, key))


def mint_receipt_id(agent_id: str, source_kind: str, source_id: str, purpose: str) -> str:
    key = f"{agent_id}|{source_kind}|{source_id}|{purpose}"
    return str(uuid.uuid5(ns_receipt, key))


def mint_view_id(agent_id: str, subject_guid: str, wake_id: str) -> str:
    key = f"{agent_id}|{subject_guid}|{wake_id}"
    return str(uuid.uuid5(ns_view, key))


def envelope(
    *,
    schema_version: str,
    source_sha: str,
    produced_at: str,
    correlation_id: str,
    idempotency_key: str,
    lifecycle_state: str,
    provenance: dict,
    parent_id: str | None = None,
    parent_kind: str | None = None,
    retention_class: str = "operational_90d",
) -> dict:
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
        "provenance": provenance,
    }


SOURCE_KINDS = frozenset({"comm_event", "research_object", "memory_fact", "operator_turn"})
EFFECT_KINDS = frozenset({
    "none", "changed_question", "changed_priority", "changed_view", "changed_commitment"
})
WAKE_LIFECYCLE = (
    "SCHEDULED", "CLAIMED", "LOADED", "ACTED", "SETTLED", "ABANDONED", "STALE",
    "MEMORY_UNAVAILABLE", "MEMORY_MALFORMED",
)
# Explicit schedule/health states required by Lane A prompt
SCHEDULE_STATES = (
    "never_scheduled",
    "due",
    "running",
    "completed",
    "partial",
    "failed",
    "replay_suppressed",
    "stale_dependency",
    "no_relevant_memory",
)
