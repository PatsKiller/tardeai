"""Phase 7 — agent_learning_linkage unit/adversarial tests.

No broker, no network. Deterministic only. Asserts the CRITICAL
feedback-vs-outcome invariant and that the learning loop never mutates a store
or strategy on its own.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import pytest  # noqa: E402

from scripts.lib.agent_learning_linkage import (  # noqa: E402
    AUTHORITY_READ_ONLY_ADVISORY,
    FEEDBACK_NOT_OUTCOME,
    LINEAGE_STEPS,
    MEMORY_STATUS_CANDIDATE,
    admit_memory_candidate,
    build_lineage,
    classify_feedback_vs_outcome,
    is_measured_outcome,
    lineage_digest,
    link_memory_refs,
    propose_memory_write,
)
from scripts.lib.agent_memory_governance import (  # noqa: E402
    STATUS_ACTIVE,
    STATUS_CANDIDATE,
    STATUS_REJECT,
)


class _RecordingProvider:
    """A store-like object that would record any write/promote it received."""

    def __init__(self):
        self.writes = []
        self.promotes = []

    def write(self, *args, **kwargs):
        self.writes.append((args, kwargs))

    def promote(self, *args, **kwargs):
        self.promotes.append((args, kwargs))


# ── Feedback vs outcome invariant (CRITICAL) ───────────────────────────────


def test_reject_is_feedback_not_loss():
    assert classify_feedback_vs_outcome("REJECT") == "FEEDBACK"
    assert classify_feedback_vs_outcome("reject") == "FEEDBACK"
    assert classify_feedback_vs_outcome("REJECT") != "MEASURED_INVESTMENT_OUTCOME"
    # A REJECT disposition is never a measured outcome even with flags.
    assert not is_measured_outcome({"disposition": "REJECT", "measured": True, "matured": True})


def test_ack_is_feedback_not_win():
    assert classify_feedback_vs_outcome("ACK") == "FEEDBACK"
    assert classify_feedback_vs_outcome("ACK") != "MEASURED_INVESTMENT_OUTCOME"
    assert not is_measured_outcome({"disposition": "ACK", "measured": True, "matured": True})


def test_done_and_rate_are_feedback():
    assert classify_feedback_vs_outcome("DONE") == "FEEDBACK"
    assert classify_feedback_vs_outcome("RATE") == "FEEDBACK"
    assert classify_feedback_vs_outcome("DEFER") == "FEEDBACK"
    assert classify_feedback_vs_outcome("NOTE") == "FEEDBACK"


def test_feedback_not_outcome_frozenset_contains_core():
    for disp in ("REJECT", "ACK", "DONE", "RATE"):
        assert disp in FEEDBACK_NOT_OUTCOME


def test_matured_measured_outcome_is_outcome():
    assert (
        classify_feedback_vs_outcome("MEASURED_INVESTMENT_OUTCOME")
        == "MEASURED_INVESTMENT_OUTCOME"
    )
    assert is_measured_outcome({
        "disposition": "MEASURED_INVESTMENT_OUTCOME",
        "measured": True,
        "matured": True,
    })


def test_measured_but_not_matured_is_not_outcome():
    # Measured alone is not enough — the outcome must have matured.
    assert not is_measured_outcome({
        "disposition": "MEASURED_INVESTMENT_OUTCOME",
        "measured": True,
        "matured": False,
    })


def test_unclassified_disposition_is_not_an_outcome():
    assert classify_feedback_vs_outcome("SOMETHING_ELSE") == "UNCLASSIFIED"
    assert not is_measured_outcome({"disposition": "SOMETHING_ELSE", "measured": True, "matured": True})


# ── Lineage ────────────────────────────────────────────────────────────────


def test_build_lineage_ordered_and_none_for_missing():
    lin = build_lineage(wake_id="w1", decision_id="dec_1")
    assert list(lin.keys()) == list(LINEAGE_STEPS)
    assert lin["wake_id"] == "w1"
    assert lin["decision_id"] == "dec_1"
    assert lin["trace_id"] is None
    assert lin["lesson_candidate"] is None


def test_lineage_digest_deterministic():
    a = build_lineage(wake_id="w1", trace_id="tr_1", decision_id="dec_1")
    b = build_lineage(wake_id="w1", trace_id="tr_1", decision_id="dec_1")
    assert lineage_digest(a) == lineage_digest(b)


def test_lineage_digest_changes_on_material_change():
    a = build_lineage(wake_id="w1", decision_id="dec_1")
    b = build_lineage(wake_id="w1", decision_id="dec_2")
    assert lineage_digest(a) != lineage_digest(b)


# ── propose_memory_write (candidate only, no store mutation) ───────────────


def test_propose_memory_write_returns_candidate_with_provenance():
    provider = _RecordingProvider()
    cand = propose_memory_write(
        "reflect: operator rejected SCHD trim",
        memory_type="lesson",
        content="SCHD is an income anchor; do not auto-trim",
        source_event_ids=["evt_1", "evt_2"],
        source_refs=["ref_1"],
        wake_id="w1",
        trace_id="tr_w1",
        decision_id="dec_schd",
    )
    assert cand["status"] == MEMORY_STATUS_CANDIDATE
    assert cand["admit_status"] == STATUS_CANDIDATE
    assert cand["memory_type"] == "lesson"
    assert "provenance" in cand
    assert cand["provenance"]["authority"] == AUTHORITY_READ_ONLY_ADVISORY
    assert cand["authority"] == AUTHORITY_READ_ONLY_ADVISORY
    assert cand["memory_id"].startswith("mem_")
    assert cand["lineage"]["wake_id"] == "w1"
    # No store/provider was touched.
    assert provider.writes == []
    assert provider.promotes == []


def test_propose_memory_write_does_not_mutate_provider():
    provider = _RecordingProvider()
    propose_memory_write(
        "reflect",
        memory_type="lesson",
        content="content",
        source_event_ids=["e1"],
    )
    # The candidate path has no provider coupling: nothing written or promoted.
    assert provider.writes == []
    assert provider.promotes == []


def test_no_automatic_strategy_mutation():
    cand = propose_memory_write(
        "reflect",
        memory_type="lesson",
        content="content",
        source_event_ids=["e1"],
    )
    # A candidate is CANDIDATE — it never self-promotes or self-writes.
    assert cand["status"] == "CANDIDATE"
    assert cand["admit_status"] == "CANDIDATE"
    assert cand["provenance"]["write_attempted"] is False
    assert cand["provenance"]["promote_attempted"] is False
    assert cand.get("written") is None
    assert cand.get("promoted") is None
    # No authority escalation.
    assert cand["authority"] == "READ_ONLY_ADVISORY"


# ── link_memory_refs ───────────────────────────────────────────────────────


def test_link_memory_refs_attaches_lineage():
    record = {"memory_id": "mem_x", "content": "op prefers SCHD"}
    out = link_memory_refs(
        record,
        wake_id="w1",
        trace_id="tr_w1",
        decision_id="dec_1",
        case_id="case_1",
    )
    assert out["lineage"]["wake_id"] == "w1"
    assert out["lineage"]["trace_id"] == "tr_w1"
    assert out["lineage"]["decision_id"] == "dec_1"
    assert out["lineage"]["case_id"] == "case_1"
    assert out["lineage_digest"] == lineage_digest(out["lineage"])
    assert out["memory_id"] == "mem_x"


def test_link_memory_refs_is_non_mutating():
    record = {"memory_id": "mem_x", "content": "op prefers SCHD"}
    original = dict(record)
    link_memory_refs(record, wake_id="w1", decision_id="dec_1")
    assert record == original


# ── Provenance / admission closure (remediation) ──────────────────────────


def test_propose_memory_write_no_provenance_is_rejected():
    cand = propose_memory_write(
        "reflect",
        memory_type="lesson",
        content="content",
        source_event_ids=[],
        source_refs=[],
    )
    assert cand["status"] == STATUS_REJECT
    assert cand["admit_status"] == STATUS_REJECT
    assert cand["retrievable"] is False
    assert "reject_reason" in cand


def test_propose_memory_write_forbidden_subject_is_rejected():
    cand = propose_memory_write(
        "reflect",
        memory_type="lesson",
        content="cash is $1,000,000",
        subject="cash",
        source_event_ids=["evt_1"],
    )
    assert cand["status"] == STATUS_REJECT
    assert cand["retrievable"] is False


def test_propose_memory_write_valid_is_candidate_retrievable():
    cand = propose_memory_write(
        "reflect",
        memory_type="lesson",
        content="content",
        source_event_ids=["evt_1"],
    )
    assert cand["status"] == STATUS_CANDIDATE
    assert cand["retrievable"] is True


def test_admit_memory_candidate_reuses_governance_vocabulary():
    cand = propose_memory_write(
        "reflect",
        memory_type="OPERATOR_EXPLICIT_PREFERENCE",
        content="operator prefers SCHD",
        source_event_ids=["evt_1"],
        subject="income anchor",
    )
    admitted = admit_memory_candidate(cand, admit=True)
    # Explicit operator statement admits ACTIVE (governance vocabulary), not a
    # second "ADMITTED" status.
    assert admitted["status"] == STATUS_ACTIVE
    assert admitted["admit_status"] == STATUS_ACTIVE
    assert admitted["retrievable"] is True


def test_admit_memory_candidate_inferred_stays_candidate():
    cand = propose_memory_write(
        "reflect",
        memory_type="OPERATOR_INFERRED_PREFERENCE",
        content="seems to like SCHD",
        source_event_ids=["evt_1"],
    )
    admitted = admit_memory_candidate(cand, admit=True)
    assert admitted["status"] == STATUS_CANDIDATE


def test_admit_memory_candidate_no_provenance_rejected_even_on_admit():
    cand = propose_memory_write(
        "reflect",
        memory_type="OPERATOR_EXPLICIT_PREFERENCE",
        content="operator prefers SCHD",
        source_event_ids=[],
        source_refs=[],
    )
    admitted = admit_memory_candidate(cand, admit=True)
    assert admitted["status"] == STATUS_REJECT
    assert admitted["retrievable"] is False


def test_admit_memory_candidate_forbidden_subject_rejected():
    cand = propose_memory_write(
        "reflect",
        memory_type="OPERATOR_EXPLICIT_PREFERENCE",
        content="cash is $1,000,000",
        source_event_ids=["evt_1"],
        subject="cash",
    )
    # Even a valid provenance + explicit admit cannot admit a forbidden subject.
    admitted = admit_memory_candidate(
        {
            "memory_type": "OPERATOR_EXPLICIT_PREFERENCE",
            "subject": "cash",
            "content": "cash is $1,000,000",
            "source_event_ids": ["evt_1"],
        },
        admit=True,
    )
    assert admitted["status"] == STATUS_REJECT


def test_admit_memory_candidate_explicit_reject_is_reject():
    cand = propose_memory_write(
        "reflect",
        memory_type="OPERATOR_EXPLICIT_PREFERENCE",
        content="operator prefers SCHD",
        source_event_ids=["evt_1"],
    )
    rejected = admit_memory_candidate(cand, admit=False, reason="operator changed mind")
    assert rejected["status"] == STATUS_REJECT
    assert rejected["retrievable"] is False

