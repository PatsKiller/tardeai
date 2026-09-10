"""Governed commitment — canonical durable contract + scheduled outcome evaluator.

Phase 4 (Grok-closure). Negative controls asserted directly.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.lib.governed_commitment import (
    CommitmentError,
    assert_not_mutated,
    build_governed_commitment,
    durable_outcome_ledger_append,
    evaluate_outcome,
)


def _base(**kw):
    base = dict(
        claim="V will hold its 50-day moving average over the next week",
        confidence=0.7,
        horizon="7d",
        due_at=datetime(2026, 9, 17, 0, 0, tzinfo=timezone.utc),
        falsifier="V closes below the 50-day MA for two consecutive sessions",
        evidence_refs=["research:46057", "material_change:mc-1"],
        source_identity="brave_router+research_scheduler",
        source_sha="abc123",
        served_sha="87e7325d2",
        subject_guid="b60bb80f-62f5-58b7-b3aa-3ed4ca29bede",
        trigger_provenance={"producer": "governed_commitment", "trigger": "schedule_slot"},
        created_at=datetime(2026, 9, 10, 1, 0, tzinfo=timezone.utc),
        frozen_at=datetime(2026, 9, 10, 1, 0, tzinfo=timezone.utc),
    )
    base.update(kw)
    return base


def test_build_valid_commitment():
    c = build_governed_commitment(**_base())
    assert c["commitment_id"].startswith("gcmt_")
    assert c["lifecycle_state"] == "FROZEN"
    assert c["frozen_at"] < c["due_at"]


def test_missing_falsifier_refused():
    with pytest.raises(CommitmentError) as ei:
        build_governed_commitment(**_base(falsifier=""))
    assert "missing_falsifier" in str(ei.value)


def test_missing_evidence_refused():
    with pytest.raises(CommitmentError) as ei:
        build_governed_commitment(**_base(evidence_refs=[]))
    assert "missing_evidence" in str(ei.value)


def test_freeze_after_window_start_refused():
    due = datetime(2026, 9, 10, 0, 0, tzinfo=timezone.utc)
    frozen = datetime(2026, 9, 11, 0, 0, tzinfo=timezone.utc)
    with pytest.raises(CommitmentError) as ei:
        build_governed_commitment(**_base(due_at=due, frozen_at=frozen))
    assert "freeze_after_window_start" in str(ei.value)


def test_wrong_source_sha_detected_as_mutation():
    c = build_governed_commitment(**_base())
    mutated = dict(c, source_sha="WRONG")
    changed = assert_not_mutated(c, mutated)
    assert "source_sha" in changed


def test_mutation_after_freeze_detected():
    c = build_governed_commitment(**_base())
    mutated = dict(c, claim="a different claim entirely")
    assert assert_not_mutated(c, mutated) == ["claim"]


def test_manual_provenance_refused():
    with pytest.raises(CommitmentError) as ei:
        build_governed_commitment(**_base(trigger_provenance={"producer": "manual"}))
    assert "prohibited_manual_or_backfill_provenance" in str(ei.value)


def test_backfill_provenance_refused():
    with pytest.raises(CommitmentError) as ei:
        build_governed_commitment(**_base(trigger_provenance={"producer": "backfill"}))
    assert "prohibited_manual_or_backfill_provenance" in str(ei.value)


def test_duplicate_commitment_same_id():
    c1 = build_governed_commitment(**_base())
    c2 = build_governed_commitment(**_base())
    assert c1["commitment_id"] == c2["commitment_id"]


def test_outcome_confirmed_and_refuted():
    c = build_governed_commitment(**_base())
    conf = evaluate_outcome(c, observation={"confirmed": True})
    ref = evaluate_outcome(c, observation={"refuted": True})
    assert conf["outcome"] == "CONFIRMED"
    assert ref["outcome"] == "REFUTED"
    assert conf["commitment_id"] == c["commitment_id"]


def test_outcome_expired_after_due():
    c = build_governed_commitment(**_base())
    after = datetime(2026, 9, 20, 0, 0, tzinfo=timezone.utc)
    o = evaluate_outcome(c, now=after)
    assert o["outcome"] == "EXPIRED"


def test_prohibited_self_evaluation():
    c = build_governed_commitment(**_base(trigger_provenance={"producer": "alice"}))
    o = evaluate_outcome(c, observation={"confirmed": True}, evaluator_identity="alice")
    assert o["outcome"] == "INSUFFICIENT_EVIDENCE"
    assert "prohibited_self_evaluation" in o["errors"]


def test_refuted_outcome_preserved_in_ledger():
    c = build_governed_commitment(**_base())
    ledger = durable_outcome_ledger_append([], evaluate_outcome(c, observation={"refuted": True}))
    assert len(ledger) == 1 and ledger[0]["outcome"] == "REFUTED"
    # Append-only: re-evaluating the same commitment+observation is a no-op.
    again = durable_outcome_ledger_append(ledger, evaluate_outcome(c, observation={"refuted": True}))
    assert len(again) == 1


def test_evaluate_malformed_commitment_insufficient_evidence():
    o = evaluate_outcome({"commitment_id": "x"})
    assert o["outcome"] == "INSUFFICIENT_EVIDENCE" and o["errors"]
