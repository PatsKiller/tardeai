"""Communications Gateway — canonical CommunicationEvent client (Phase 1–11).

Public API:
  - CommunicationEvent / publish_communication
  - ChannelDelivery / reserve_delivery / settle_delivery / record_chunk
  - channel adapters: send_via_gateway (email/slack/whatsapp; deliver=False default)
  - subject memory: subject_key_for, upsert_subject, attach_event_to_subject,
    retrieve_subject_history
  - curation: select_curation_mode, curate_deterministic,
    apply_llm_curation_result, CurationReceipt, …
  - librarian: classify_retention, apply_retention_decision,
    execute_expiry_pass, propose_knowledge_candidate, …
  - agent contracts: register_subscription, emit_consumption_receipt,
    acknowledge_consumption, declare_influence, AgentConsumptionReceipt, …
  - SHADOW compare: compare_legacy_vs_gateway, record_shadow_observation,
    shadow_report
  - new_event_id / idempotency_key_for
  - get_gateway_mode / MODE_*

Does NOT own provider delivery by default. Modes default to OFF. Phase 3 records
ChannelDelivery@v1 stubs (RESERVED) without sending.
Phase 4 attaches events to subject threads after publish.
Phase 5 curation never calls real LLM APIs.
Phase 6 librarian classifies retention; never auto-promotes chat to knowledge.
Phase 8 agent consumption receipts never self-certify truth.
Phase 10 channel adapters send only when deliver=True and mode is CANARY/ACTIVE.
Phase 11 SHADOW compare never claims delivery ownership or flips ACTIVE.
"""
from __future__ import annotations

from scripts.lib.comms.agent_contracts import (
    KNOWN_AGENTS,
    SCHEMA_VERSION as AGENT_CONSUMPTION_SCHEMA_VERSION,
    SELF_CERTIFYING_STATUSES,
    AgentConsumptionReceipt,
    AgentContractError,
    acknowledge_consumption,
    assert_not_self_certifying_truth,
    declare_influence,
    eligible_events_for_agent,
    emit_consumption_receipt,
    get_consumption_receipt,
    list_subscriptions,
    register_subscription,
)
from scripts.lib.comms.channel_adapters import (
    ADAPTER_VERSIONS,
    SUPPORTED_CHANNELS,
    send_via_gateway,
)
from scripts.lib.comms.client import PublishResult, publish_communication
from scripts.lib.comms.curation import (
    DETERMINISTIC,
    HUMAN_EDIT,
    LLM_CHALLENGE,
    LLM_SUMMARY,
    PROTECTED_FACT_KEYS,
    TEMPLATE,
    CurationReceipt,
    apply_llm_curation_result,
    curate_deterministic,
    get_curation_receipt,
    preserve_protected_facts,
    select_curation_mode,
    store_curation_receipt,
)
from scripts.lib.comms.delivery import (
    ChannelDelivery,
    DeliveryGateError,
    attach_delivery_reservation,
    record_chunk,
    reserve_delivery,
    settle_delivery,
)
from scripts.lib.comms.subject_memory import (
    attach_event_to_subject,
    get_subject,
    retrieve_subject_history,
    subject_key_for,
    upsert_subject,
)
from scripts.lib.comms.enforcement import (
    MissingCommunicationEventId,
    assert_delivery_not_owned_in_off_or_shadow,
    require_event_id,
)
from scripts.lib.comms.event import CommunicationEvent, required_missing
from scripts.lib.comms.identity import idempotency_key_for, new_event_id
from scripts.lib.comms.librarian import (
    ACCEPTED,
    CANDIDATE,
    COMPACT,
    DELETE_ALL_ALLOWED,
    DELETE_CONTENT_KEEP_TOMBSTONE,
    DISPUTED,
    HOLD,
    KEEP,
    KNOWLEDGE_STATUSES,
    REDACT,
    REJECTED,
    RETENTION_ACTIONS,
    RETRACTED,
    SUPERSEDED,
    RetentionDecision,
    apply_retention_decision,
    classify_retention,
    decide_knowledge_candidate,
    execute_expiry_pass,
    propose_knowledge_candidate,
    reset_librarian_memory,
)
from scripts.lib.comms.mode import (
    MODE_ACTIVE,
    MODE_CANARY,
    MODE_OFF,
    MODE_SHADOW,
    VALID_MODES,
    get_gateway_mode,
    mode_diagnostics,
)
from scripts.lib.comms.shadow_compare import (
    compare_legacy_vs_gateway,
    extract_route_intent,
    record_shadow_observation,
    reset_shadow_observations,
    shadow_report,
)

__all__ = [
    "CommunicationEvent",
    "PublishResult",
    "publish_communication",
    "ChannelDelivery",
    "DeliveryGateError",
    "reserve_delivery",
    "settle_delivery",
    "record_chunk",
    "attach_delivery_reservation",
    "send_via_gateway",
    "SUPPORTED_CHANNELS",
    "ADAPTER_VERSIONS",
    "new_event_id",
    "idempotency_key_for",
    "required_missing",
    "require_event_id",
    "MissingCommunicationEventId",
    "assert_delivery_not_owned_in_off_or_shadow",
    "MODE_OFF",
    "MODE_SHADOW",
    "MODE_CANARY",
    "MODE_ACTIVE",
    "VALID_MODES",
    "get_gateway_mode",
    "mode_diagnostics",
    "DETERMINISTIC",
    "TEMPLATE",
    "LLM_SUMMARY",
    "LLM_CHALLENGE",
    "HUMAN_EDIT",
    "PROTECTED_FACT_KEYS",
    "CurationReceipt",
    "select_curation_mode",
    "curate_deterministic",
    "preserve_protected_facts",
    "apply_llm_curation_result",
    "store_curation_receipt",
    "get_curation_receipt",
    "subject_key_for",
    "upsert_subject",
    "attach_event_to_subject",
    "retrieve_subject_history",
    "get_subject",
    "KEEP",
    "COMPACT",
    "REDACT",
    "DELETE_CONTENT_KEEP_TOMBSTONE",
    "DELETE_ALL_ALLOWED",
    "HOLD",
    "RETENTION_ACTIONS",
    "CANDIDATE",
    "ACCEPTED",
    "DISPUTED",
    "SUPERSEDED",
    "RETRACTED",
    "REJECTED",
    "KNOWLEDGE_STATUSES",
    "RetentionDecision",
    "classify_retention",
    "apply_retention_decision",
    "execute_expiry_pass",
    "propose_knowledge_candidate",
    "decide_knowledge_candidate",
    "reset_librarian_memory",
    "KNOWN_AGENTS",
    "SELF_CERTIFYING_STATUSES",
    "AGENT_CONSUMPTION_SCHEMA_VERSION",
    "AgentConsumptionReceipt",
    "AgentContractError",
    "register_subscription",
    "list_subscriptions",
    "eligible_events_for_agent",
    "emit_consumption_receipt",
    "get_consumption_receipt",
    "acknowledge_consumption",
    "declare_influence",
    "assert_not_self_certifying_truth",
    "compare_legacy_vs_gateway",
    "extract_route_intent",
    "record_shadow_observation",
    "shadow_report",
    "reset_shadow_observations",
]
