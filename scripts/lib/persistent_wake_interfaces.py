"""VENDORED SHIM — superseded by scripts/lib/campaign_interfaces.py.

Replaced at INTEGRATION_ORDER.md step 5 (campaign m2-canary-20260907). The lane
vendored this while the canonical module did not yet exist, per
INTERFACE_CONTRACTS.md §1. It now re-exports from the single source of truth so
the three lanes cannot drift apart again.

Kept rather than deleted so lane imports keep resolving and lane history stays
readable (AGENTS.md §0.6).
"""
from __future__ import annotations

from scripts.lib.campaign_interfaces import *  # noqa: F401,F403
from scripts.lib.campaign_interfaces import (  # noqa: F401
    _ns,
    envelope,
    mint_wake_id,
    mint_commitment_id,
    mint_receipt_id,
    mint_consumption_receipt_id,
    mint_communication_event_id,
    mint_thread_id,
    mint_research_object_id,
    mint_outcome_id,
    mint_belief_proposal_id,
    mint_view_id,
    canonical_url,
    INTERFACE_VERSION,
)

from scripts.lib.campaign_interfaces import (  # noqa: F401
    ns_wake, ns_commit, ns_receipt, ns_comm, ns_thread, ns_research,
    ns_outcome, ns_belief, ns_memory_fact, ns_operator_turn, ns_view,
    ns_schedule_slot, WAKE_SCHEMA, RECEIPT_SCHEMA, COMMITMENT_SCHEMA,
    VIEW_SCHEMA, SCHEDULE_SCHEMA, SOURCE_KINDS, EFFECT_KINDS,
    WAKE_LIFECYCLE, SCHEDULE_STATES,
)
