"""L4: a frozen prediction must be revisited after its horizon.

Measured on the live store 2026-09-12:

    durable commitments                                        224
    carrying any outcome / score / resolution field               0
    past due                                                     0  (earliest 2026-09-19)
    frozen_at == created_at                                    224
    cron entries running an outcome evaluator over commitments    0
    systemd units doing so                                        0

The contract was never the problem. GovernedCommitmentOutcome@v1, the
CONFIRMED/REFUTED/EXPIRED vocabulary, the self-evaluation prohibition and the
append-only ledger all existed. `evaluate_outcome` simply had one caller,
cortex_shadow_pipeline, which invokes it on the same line that mints the
commitment -- so a seven-day prediction was scored at freeze time and nothing
ever looked again.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from scripts.lib.commitment_outcome_sweep import (
    build_lesson_candidate,
    claim_is_falsifiable,
    is_prediction,
    no_observation_provider,
    sweep_due_commitments,
)

NOW = datetime(2026, 9, 12, 1, 0, tzinfo=timezone.utc)


def _commitment(
    cid="gcmt_test01",
    *,
    due_days=-1,
    claim="ADBE margin expansion persists through the next print.",
    falsifier="Next 10-Q shows gross margin below the prior quarter.",
    confidence=0.7,
    producer="cortex_shadow_pipeline",
):
    created = NOW - timedelta(days=8)
    return {
        "schema_version": "GovernedCommitment@v1",
        "commitment_id": cid,
        "subject_guid": "0bc81168-8536-51ef-9bc8-44cb160bcc60",
        "claim": claim,
        "confidence": confidence,
        "horizon": "7d",
        "due_at": (NOW + timedelta(days=due_days)).isoformat(),
        "falsifier": falsifier,
        "evidence_refs": ["wake:abc"],
        "source_identity": producer,
        "source_sha": "eb648174a",
        "served_sha": "eb648174a",
        "trigger_provenance": {"producer": producer, "trigger": "agent_view_v1"},
        "created_at": created.isoformat(),
        "frozen_at": created.isoformat(),
        "lifecycle_state": "FROZEN",
    }


def test_a_commitment_that_is_not_yet_due_is_left_alone():
    res = sweep_due_commitments([_commitment(due_days=+7)], now=NOW)
    assert res.scanned == 1
    assert res.due == 0
    assert res.outcomes == []


def test_a_due_commitment_with_no_observation_expires_rather_than_confirming():
    """The default provider knows nothing. Reporting CONFIRMED there would be
    manufactured evidence; EXPIRED is the truthful 'horizon closed unobserved'."""
    res = sweep_due_commitments([_commitment()], now=NOW)
    assert res.due == 1
    assert res.by_outcome == {"EXPIRED": 1}
    assert res.scored == 1
    assert no_observation_provider(_commitment()) == {}


def test_a_refuted_prediction_is_preserved_and_proposes_a_lesson():
    res = sweep_due_commitments(
        [_commitment()], observation_provider=lambda _c: {"refuted": True}, now=NOW
    )
    assert res.by_outcome == {"REFUTED": 1}
    assert len(res.lessons) == 1
    lesson = res.lessons[0]
    assert lesson["status"] == "PROPOSED"
    assert lesson["changes_production_behaviour"] is False
    assert lesson["ratified_by"] is None


def test_a_confirmed_prediction_also_proposes_a_lesson():
    res = sweep_due_commitments(
        [_commitment()], observation_provider=lambda _c: {"confirmed": True}, now=NOW
    )
    assert res.by_outcome == {"CONFIRMED": 1}
    assert len(res.lessons) == 1


def test_the_commitment_itself_is_never_mutated():
    """A frozen prediction stays exactly as written, refuted included."""
    c = _commitment()
    before = dict(c)
    sweep_due_commitments([c], observation_provider=lambda _x: {"refuted": True}, now=NOW)
    assert c == before


def test_rescoring_the_same_commitment_is_idempotent():
    ledger: list[dict] = []
    first = sweep_due_commitments(
        [_commitment()], ledger=ledger, observation_provider=lambda _c: {"refuted": True}, now=NOW
    )
    second = sweep_due_commitments(
        [_commitment()],
        ledger=first.ledger,
        observation_provider=lambda _c: {"refuted": True},
        now=NOW,
    )
    assert len(first.ledger) == 1
    assert second.already_settled == 1
    assert second.outcomes == []
    assert len(second.ledger) == 1


def test_an_unfalsifiable_claim_is_reported_not_scored_as_a_success():
    """96 of 224 live commitments are this exact template. Scoring them
    CONFIRMED would manufacture a success rate out of boilerplate."""
    c = _commitment(
        claim="Scheduled persistent wake reviewed subject "
        "4b54769d-c407-5732-81c3-cf67575dd759; advisory observation only.",
        falsifier="observation contradicts claim within horizon",
    )
    ok, reason = claim_is_falsifiable(c)
    assert ok is False
    assert reason == "claim_asserts_only_that_a_review_occurred"

    res = sweep_due_commitments([c], observation_provider=lambda _x: {"confirmed": True}, now=NOW)
    assert res.unfalsifiable == 1
    assert res.scored == 0
    assert res.by_outcome == {"INSUFFICIENT_EVIDENCE": 1}
    assert res.lessons == []
    assert "claim_not_falsifiable" in res.outcomes[0]["errors"][0]


def test_a_vacuous_falsifier_alone_is_enough_to_refuse_scoring():
    c = _commitment(
        claim="ADBE will outperform its sector over the horizon.",
        falsifier="observation contradicts claim within horizon",
    )
    ok, reason = claim_is_falsifiable(c)
    assert ok is False
    assert reason == "falsifier_names_no_observable"


def test_an_agent_cannot_score_its_own_commitment():
    """Constitutional: an agent cannot validate or score its own artifact."""
    res = sweep_due_commitments(
        [_commitment(producer="cortex_shadow_pipeline")],
        observation_provider=lambda _c: {"confirmed": True},
        now=NOW,
        evaluator_identity="cortex_shadow_pipeline",
    )
    assert res.by_outcome == {"INSUFFICIENT_EVIDENCE": 1}
    assert "prohibited_self_evaluation" in res.outcomes[0]["errors"]
    assert res.scored == 0


def test_a_neutral_evaluator_may_score_it():
    res = sweep_due_commitments(
        [_commitment(producer="cortex_shadow_pipeline")],
        observation_provider=lambda _c: {"confirmed": True},
        now=NOW,
        evaluator_identity="deterministic_neutral",
    )
    assert res.by_outcome == {"CONFIRMED": 1}


def test_a_lesson_is_a_candidate_and_cannot_ratify_itself():
    lesson = build_lesson_candidate(
        _commitment(), {"outcome": "REFUTED"}, now=NOW
    )
    assert lesson["status"] == "PROPOSED"
    assert lesson["ratified_by"] is None and lesson["ratified_at"] is None
    assert lesson["rejected_by"] is None and lesson["rejected_at"] is None
    assert lesson["mbi_behavior"] == 0
    assert lesson["authority"] == "READ_ONLY_ADVISORY"


def test_mixed_batch_counts_every_category_separately():
    batch = [
        _commitment(cid="a", due_days=+7),
        _commitment(cid="b"),
        _commitment(
            cid="c",
            claim="Scheduled persistent wake reviewed subject 1111-2222; advisory observation only.",
            falsifier="observation contradicts claim within horizon",
        ),
    ]
    res = sweep_due_commitments(batch, now=NOW)
    assert (res.scanned, res.due, res.unfalsifiable) == (3, 2, 1)
    assert res.by_outcome == {"EXPIRED": 1, "INSUFFICIENT_EVIDENCE": 1}


# ---------------------------------------------------------------------------
# commitments.jsonl holds two record shapes and only one of them predicts.
# ---------------------------------------------------------------------------

WAKE_OBSERVATION = {
    "agent_id": "cio",
    "authority": "READ_ONLY_ADVISORY",
    "claim": "selection:material_change:d4c2d622-2aec-5675-b84f-a660dc68800c warrants review",
    "commitment_id": "7ae3e043-75c6-56ad-8fdf-e84d3cdd327a",
    "commitment_kind": "SELECTION_OBSERVATION",
    "lifecycle_state": "OPEN",
    "normalized_claim": "selection:material_change:d4c2d622 warrants review",
    "produced_at": "2026-09-10T06:00:01.799895Z",
    "schema_version": "AgentCommitment@v1",
}


def test_a_wake_observation_is_not_treated_as_a_failed_prediction():
    """125 of the 224 live records are this shape: no due_at, no horizon, no
    confidence, no falsifier. Counting them as predictions missing a falsifier
    would invent 125 failures out of records that never claimed anything about
    the future."""
    assert is_prediction(WAKE_OBSERVATION) is False
    ok, reason = claim_is_falsifiable(WAKE_OBSERVATION)
    assert (ok, reason) == (False, "not_a_prediction")


def test_a_governed_commitment_is_a_prediction():
    assert is_prediction(_commitment()) is True


def test_observations_are_skipped_by_the_sweep_entirely():
    """They have no due_at, so they are never due and never scored -- they must
    not land in the unfalsifiable count either."""
    res = sweep_due_commitments([WAKE_OBSERVATION, _commitment()], now=NOW)
    assert res.scanned == 2
    assert res.due == 1
    assert res.unfalsifiable == 0
    assert res.by_outcome == {"EXPIRED": 1}


def test_a_prediction_needs_both_a_due_date_and_a_horizon():
    assert is_prediction({"due_at": "2026-09-19T00:00:00Z"}) is False
    assert is_prediction({"horizon": "7d"}) is False
    assert is_prediction({"due_at": "2026-09-19T00:00:00Z", "horizon": "7d"}) is True
