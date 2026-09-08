"""CampaignInterfaces@v1 — the single frozen identifier contract.

INTEGRATION-OWNED. Authored at INTEGRATION_ORDER.md step 5 for campaign
m2-canary-20260907. Supersedes the three per-lane vendored copies, which are now
thin shims re-exporting from here.

Why this file exists
--------------------
The lanes were told (INTERFACE_CONTRACTS.md §1) to vendor a test-local copy until
this module landed. Two derivations resulted:

    lane A, lane B : ns = uuid5(NAMESPACE_URL, "tradeai:campaign:<name>")
    lane C         : ns = hardcoded literal UUIDs

They disagree. For identical inputs at integration time:

    lane A mint_wake_id -> fe429b4e-9de8-5458-9e85-b584d91fe8cc
    lane C mint_wake_id -> 332a991a-00fe-5eef-8205-c9132801f641

That would have broken integrated trace #1 silently: lane C research receipts
would carry wake ids lane A never minted, and the join would simply return
nothing. Nothing would have errored.

The DERIVED scheme is canonical: two of three lanes use it, it is
self-documenting, and it matches §1's requirement that identifiers be UUIDv5 over
a named spine namespace rather than magic constants. Lane C's ids change as a
result. That is safe: lane C declared write_attribution method=no_write_path with
attributable_total=0, so it persisted no identifier anywhere.
"""
from __future__ import annotations

import datetime as _dt
import uuid

INTERFACE_VERSION = "CampaignInterfaces@v1"
NAMESPACE_URL_PREFIX = "tradeai:campaign:"


def _ns(name: str) -> uuid.UUID:
    """Canonical namespace derivation. The one source of truth."""
    return uuid.uuid5(uuid.NAMESPACE_URL, f"{NAMESPACE_URL_PREFIX}{name}")


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

# Schema names (INTERFACE_CONTRACTS.md §4-§7)
WAKE_SCHEMA = "WakeRecord@v2"
RECEIPT_SCHEMA = "AgentConsumptionReceipt@v2"
COMMITMENT_SCHEMA = "CommitmentRecord@v2"
VIEW_SCHEMA = "AgentView@v2"
SCHEDULE_SCHEMA = "PersistentWakeScheduleContract@v1"
COMM_EVENT_SCHEMA = "CommunicationEvent@v2"
CURATION_PROVENANCE_SCHEMA = "CurationProvenance@v1"

# SFR-A-FOLLOWUP3-002: material_change added 2026-09-08. The wake selector
# legitimately selects subjects on MaterialChange@v1, so a receipt must be able
# to name one as its source. Extending Python ALONE would violate the DDL CHECK
# constraint the moment a receipt reached the database — the migration and
# INTERFACE_CONTRACTS.md §6 are extended in the same commit.
SOURCE_KINDS = frozenset({"comm_event", "research_object", "memory_fact",
                         "operator_turn", "material_change"})
EFFECT_KINDS = frozenset({"none", "changed_question", "changed_priority",
                          "changed_view", "changed_commitment"})
PARENT_KINDS = frozenset({"wake", "comm_event", "research_object", "commitment", "outcome"})
RETENTION_CLASSES = frozenset({"operational_90d", "evidence_2y", "permanent"})
PROVIDER_SETTLEMENT_STATES = frozenset({"UNSETTLED", "SETTLED", "FAILED", "UNKNOWN_LEGACY"})
DELIVERY_OWNERS = frozenset({"gateway", "legacy"})
GATEWAY_MODES = frozenset({"OFF", "SHADOW", "CANARY", "ACTIVE"})
CURATION_KINDS = frozenset({"deterministic", "llm_curated"})
WAKE_LIFECYCLE = ("SCHEDULED", "CLAIMED", "LOADED", "ACTED", "SETTLED",
                  "ABANDONED", "STALE", "MEMORY_UNAVAILABLE", "MEMORY_MALFORMED")
# Lane A's schedule/health states, preserved verbatim. An earlier integration
# draft invented ("DEFINED","ARMED","DISARMED") here, which broke
# assert_schedule_states_complete() and with it the production-schedule safety
# test. The canonical module must ADOPT lane definitions, not replace them.
SCHEDULE_STATES = (
    "never_scheduled", "due", "running", "completed", "partial", "failed",
    "replay_suppressed", "stale_dependency", "no_relevant_memory",
)


def _u(ns: uuid.UUID, *parts: str) -> str:
    return str(uuid.uuid5(ns, "|".join("" if p is None else str(p) for p in parts)))


def mint_wake_id(agent_id, wake_reason, schedule_slot_utc, subject_guid) -> str:
    return _u(ns_wake, agent_id, wake_reason, schedule_slot_utc, subject_guid)


def mint_commitment_id(wake_id, subject_guid, commitment_kind, normalized_claim) -> str:
    return _u(ns_commit, wake_id, subject_guid, commitment_kind, normalized_claim)


def mint_receipt_id(agent_id, source_kind, source_id, purpose) -> str:
    """ConsumptionReceiptId, prefixed ``acr_``.

    Third cross-lane divergence found at step 5: lane B minted ``acr_<uuid5>``,
    lanes A and C minted a bare ``<uuid5>``. Same namespace, same key, different
    string — a receipt written by B could not be found by A.

    ``acr_`` wins because it is the DEPLOYED convention: every pre-existing
    @v1 row in communication_agent_consumption_receipts carries it
    (acr_01a06fc9-…), and tests/test_comms_agent_contracts.py asserts it.
    Lanes A and C persisted nothing (no_write_path), so re-shaping their ids is
    safe; changing the deployed shape would not be.
    """
    return f"acr_{_u(ns_receipt, agent_id, source_kind, source_id, purpose)}"


# lane C spelled this one differently; keep both names bound to one implementation
mint_consumption_receipt_id = mint_receipt_id


def mint_communication_event_id(channel, provider_thread, provider_msg_id, occurred_at) -> str:
    return _u(ns_comm, channel, provider_thread, provider_msg_id, occurred_at)


def mint_thread_id(subject_guid, channel, root_event_id) -> str:
    return _u(ns_thread, subject_guid, channel, root_event_id)


def mint_research_object_id(source_url_canonical, published_at, subject_guid) -> str:
    return _u(ns_research, source_url_canonical, published_at, subject_guid)


def mint_outcome_id(commitment_id, observation_window_end) -> str:
    return _u(ns_outcome, commitment_id, observation_window_end)


def mint_belief_proposal_id(outcome_id, belief_key, proposal_revision) -> str:
    return _u(ns_belief, outcome_id, belief_key, proposal_revision)


def mint_view_id(agent_id, subject_guid, as_of) -> str:
    return _u(ns_view, agent_id, subject_guid, as_of)


def envelope(*, schema_version, source_sha, correlation_id, idempotency_key,
             parent_id=None, parent_kind=None,
             retention_class="operational_90d", lifecycle_state=None,
             provenance=None, produced_at=None) -> dict:
    """The §2 mandatory envelope carried by every campaign object."""
    if retention_class not in RETENTION_CLASSES:
        raise ValueError(f"retention_class {retention_class!r} not in {sorted(RETENTION_CLASSES)}")
    if parent_kind is not None and parent_kind not in PARENT_KINDS:
        raise ValueError(f"parent_kind {parent_kind!r} not in {sorted(PARENT_KINDS)}")
    return {
        "schema_version": schema_version,
        "source_sha": source_sha,
        "produced_at": produced_at or _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "correlation_id": correlation_id,
        "idempotency_key": idempotency_key,
        "parent_id": parent_id,
        "parent_kind": parent_kind,
        "retention_class": retention_class,
        "lifecycle_state": lifecycle_state,
        "provenance": provenance or {},
        "interface_version": INTERFACE_VERSION,
    }


def canonical_url(url: str) -> str:
    """Normalize a source URL for identity. Strip fragment and trailing slash.

    Lane C's implementation, preserved verbatim. An earlier integration draft also
    stripped the scheme and host prefix, which broke research_object.py's
    ``source_url must be http(s)`` validation — the scheme is load-bearing
    downstream, not noise.
    """
    u = (url or "").strip()
    if not u:
        raise ValueError("source_url required")
    if "#" in u:
        u = u.split("#", 1)[0]
    if u.endswith("/") and u.count("/") > 2:
        u = u.rstrip("/")
    return u


# ─────────────────────────────────────────────────────────────────────────────
# What counts as consumption evidence (INTEGRATION_ORDER.md step 11, defect 15).
#
# Defect 15 is that maturity reporting conflates receipt types. Two ways to
# overstate consumption, both live in this system right now:
#
#   1. TOMBSTONED rows. All five receipts in production on 2026-09-07 were
#      orphans referencing events that never existed; four of them were the
#      audited "consumption receipts = 4" M1 baseline. They are tombstoned in
#      place, not deleted, so a naive count(*) still returns 5.
#   2. effect_kind='none'. A receipt saying "I read this and it changed nothing"
#      is honest and legal — and is NOT evidence that consumption matured.
#
# Any surface reporting consumption MUST use these. A bare count(*) is wrong.
# ─────────────────────────────────────────────────────────────────────────────

TOMBSTONE_PREFIX = "TOMBSTONED"

USABLE_RECEIPT_SQL = """
    COALESCE(policy_decision, '') NOT LIKE 'TOMBSTONED%'
AND effect_kind IS NOT NULL
AND effect_kind <> 'none'
AND effect_ref IS NOT NULL
""".strip()


def is_usable_consumption_receipt(row: dict) -> bool:
    """True only when this receipt evidences that consumption changed something.

    Mirrors USABLE_RECEIPT_SQL. Keep the two in step.
    """
    if str(row.get("policy_decision") or "").startswith(TOMBSTONE_PREFIX):
        return False
    effect = row.get("effect_kind")
    if not effect or effect == "none":
        return False
    if effect not in EFFECT_KINDS:
        raise ValueError(f"effect_kind {effect!r} not in {sorted(EFFECT_KINDS)}")
    return row.get("effect_ref") is not None
