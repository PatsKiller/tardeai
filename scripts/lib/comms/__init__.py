"""Communications Gateway — canonical CommunicationEvent client (Phase 1–5).

Public API:
  - CommunicationEvent / publish_communication
  - ChannelDelivery / reserve_delivery / settle_delivery / record_chunk
  - subject memory: subject_key_for, upsert_subject, attach_event_to_subject,
    retrieve_subject_history
  - curation: select_curation_mode, curate_deterministic,
    apply_llm_curation_result, CurationReceipt, …
  - new_event_id / idempotency_key_for
  - get_gateway_mode / MODE_*

Does NOT own provider delivery. Modes default to OFF. Phase 3 records
ChannelDelivery@v1 stubs (RESERVED) without sending.
Phase 4 attaches events to subject threads after publish.
Phase 5 curation never calls real LLM APIs.
"""
from __future__ import annotations

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
from scripts.lib.comms.mode import (
    MODE_ACTIVE,
    MODE_CANARY,
    MODE_OFF,
    MODE_SHADOW,
    VALID_MODES,
    get_gateway_mode,
    mode_diagnostics,
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
]
