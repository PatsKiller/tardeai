"""Cross-lane integrated traces — INTEGRATION_ORDER.md step 12.

Each lane proved its own segment in isolation. Nothing proved the JOINS between
them, and that gap is not theoretical: at step 5 lanes A and C were found minting
different WakeIds for identical inputs (fe429b4e… vs 332a991a…). Every per-lane
test still passed. The join would simply have returned nothing.

These tests assert the identifiers actually meet across lane boundaries.
Isolated environments only — no DB, no network, no provider spend.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.lib import campaign_interfaces as CI  # noqa: E402
from scripts.lib import campaign_interfaces_b as B  # noqa: E402
from scripts.lib import campaign_interfaces_c as C  # noqa: E402
from scripts.lib import persistent_wake_interfaces as A  # noqa: E402

SUBJ = "sg-noc-001"
SLOT = "2026-09-08T06:00:00Z"


# ── trace 1: research → identity → wake → receipt ───────────────────────────
def test_trace_research_to_wake_receipt_ids_join_across_lanes():
    """Lane C mints the research object; lane A wakes on it; the receipt binds
    both. If the lanes disagree on a namespace this returns two unrelated ids
    and the join is silently empty."""
    rid = C.mint_research_object_id("reuters.com/x", "2026-09-07", SUBJ)
    assert rid == CI.mint_research_object_id("reuters.com/x", "2026-09-07", SUBJ)

    wake_a = A.mint_wake_id("cio", "scheduled", SLOT, SUBJ)
    wake_c = C.mint_wake_id("cio", "scheduled", SLOT, SUBJ)
    assert wake_a == wake_c, "lane A and lane C must mint the same WakeId"

    r_a = A.mint_receipt_id("cio", "research_object", rid, "intake")
    r_c = C.mint_consumption_receipt_id("cio", "research_object", rid, "intake")
    assert r_a == r_c, "receipt id must not depend on which lane minted it"
    assert r_a.startswith("acr_"), "deployed @v1 identity shape must be preserved"


# ── trace 2: comms event → thread → receipt ─────────────────────────────────
def test_trace_communication_event_to_agent_receipt_ids_join():
    ev_b = B.mint_communication_event_id("telegram", "thr1", "msg1", "2026-09-07T12:00:00Z")
    ev_i = CI.mint_communication_event_id("telegram", "thr1", "msg1", "2026-09-07T12:00:00Z")
    assert ev_b == ev_i

    th_b = B.mint_thread_id(SUBJ, "telegram", ev_b)
    assert th_b == CI.mint_thread_id(SUBJ, "telegram", ev_b)

    r_b = B.mint_receipt_id("cio", "comm_event", ev_b, "intake")
    r_a = A.mint_receipt_id("cio", "comm_event", ev_b, "intake")
    assert r_b == r_a, "lane B and lane A must agree on a comm_event receipt id"


# ── trace 3: wake → commitment → outcome → belief proposal ──────────────────
def test_trace_persistent_loop_ids_chain():
    wake = CI.mint_wake_id("cio", "scheduled", SLOT, SUBJ)
    commit = A.mint_commitment_id(wake, SUBJ, "expectation", "noc holds above 500")
    assert commit == CI.mint_commitment_id(wake, SUBJ, "expectation", "noc holds above 500")

    outcome = CI.mint_outcome_id(commit, "2026-09-15T00:00:00Z")
    belief = CI.mint_belief_proposal_id(outcome, "noc_momentum", 1)
    assert len({wake, commit, outcome, belief}) == 4, "each hop must be distinct"
    # the chain must be reconstructible: same inputs, same ids, no randomness
    assert outcome == CI.mint_outcome_id(commit, "2026-09-15T00:00:00Z")
    assert belief == CI.mint_belief_proposal_id(outcome, "noc_momentum", 1)


# ── trace 4: replay produces no duplicate identity ──────────────────────────
@pytest.mark.parametrize("mint,args", [
    (CI.mint_wake_id, ("cio", "scheduled", SLOT, SUBJ)),
    (CI.mint_research_object_id, ("reuters.com/x", "2026-09-07", SUBJ)),
    (CI.mint_communication_event_id, ("telegram", "thr1", "msg1", "2026-09-07T12:00:00Z")),
    (CI.mint_receipt_id, ("cio", "comm_event", "evt-1", "intake")),
    (CI.mint_outcome_id, ("commit-1", "2026-09-15T00:00:00Z")),
    (CI.mint_belief_proposal_id, ("outcome-1", "k", 1)),
])
def test_replay_collides_rather_than_duplicating(mint, args):
    assert mint(*args) == mint(*args)


def test_distinct_inputs_do_not_collide():
    a = CI.mint_wake_id("cio", "scheduled", SLOT, SUBJ)
    b = CI.mint_wake_id("cio", "scheduled", SLOT, "sg-other")
    assert a != b, "different subjects must not share a wake id"


# ── failure containment ────────────────────────────────────────────────────
def test_envelope_rejects_unknown_retention_class():
    with pytest.raises(ValueError):
        CI.envelope(schema_version="X@v1", source_sha="abc", correlation_id="c",
                    idempotency_key="k", retention_class="forever_and_ever")


def test_envelope_rejects_unknown_parent_kind():
    with pytest.raises(ValueError):
        CI.envelope(schema_version="X@v1", source_sha="abc", correlation_id="c",
                    idempotency_key="k", parent_kind="not_a_kind")


def test_envelope_carries_every_mandatory_field():
    e = CI.envelope(schema_version="WakeRecord@v2", source_sha="deadbeef",
                    correlation_id="corr-1", idempotency_key="idem-1",
                    parent_id="w1", parent_kind="wake", lifecycle_state="LOADED")
    for k in ("schema_version", "source_sha", "produced_at", "correlation_id",
              "idempotency_key", "parent_id", "parent_kind", "retention_class",
              "lifecycle_state", "provenance", "interface_version"):
        assert k in e, f"envelope missing mandatory field {k}"
    assert e["interface_version"] == "CampaignInterfaces@v1"


def test_canonical_url_preserves_scheme():
    """An integration draft stripped the scheme here and broke research_object's
    http(s) validation. The scheme is load-bearing, not noise."""
    assert CI.canonical_url("https://reuters.com/x/").startswith("https://")
