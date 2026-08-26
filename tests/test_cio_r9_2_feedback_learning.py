from __future__ import annotations

from pathlib import Path

import pytest

from scripts.lib.cio_feedback_learning_v1 import (
    append_linked_feedback,
    build_preference_candidates,
    build_weekly_learning_review,
    reconcile_weekly_learning_review,
)


def _feedback(index: int, *, reason: str = "VALUATION", decision_id: str | None = None) -> dict:
    return {
        "schema": "OperatorFeedback@v2",
        "feedback_id": f"f{index}",
        "status": "ACTIVE",
        "intent": "DISAGREE",
        "reason_class": reason,
        "decision_id": decision_id or f"d{index}",
    }


def test_linked_feedback_requires_operator_and_context(tmp_path: Path) -> None:
    store = tmp_path / "feedback.jsonl"
    with pytest.raises(PermissionError, match="operator identity"):
        append_linked_feedback({"intent": "AGREE", "decision_id": "d1"}, store_path=store)
    with pytest.raises(ValueError, match="at least one"):
        append_linked_feedback({"intent": "AGREE", "operator_identity_class": "OPERATOR"}, store_path=store)
    row = append_linked_feedback({
        "intent": "NEED_DATA",
        "reason_class": "EVIDENCE",
        "operator_identity_class": "OPERATOR",
        "portfolio_thesis_id": "cio_portfolio",
        "portfolio_thesis_version": "cio_portfolio@v2",
        "capital_plan_id": "capital_plan",
        "capital_plan_version": "capital_plan@v3",
        "reason": "Need current valuation evidence.",
    }, store_path=store)
    assert row["schema"] == "OperatorFeedback@v2"
    assert row["behavior_authority"] is False
    assert row["policy_update"] is None
    assert row["memory_behavior_influence"] == 0
    assert row["financial_action"] is False


def test_preference_candidate_requires_repetition_across_distinct_decisions() -> None:
    repeated_same = [_feedback(index, decision_id="same") for index in range(3)]
    assert build_preference_candidates(repeated_same) == []
    candidates = build_preference_candidates([_feedback(index) for index in range(3)])
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["schema"] == "PreferenceCandidate@v1"
    assert candidate["status"] == "CANDIDATE"
    assert candidate["requires_operator_confirmation"] is True
    assert candidate["policy_update"] is None
    assert candidate["behavior_influence"] == 0


def test_weekly_review_marks_short_outcome_history_unmeasured() -> None:
    review = build_weekly_learning_review(
        week_ending="2026-08-23",
        decision_rows=[{"decision_id": "d1"}],
        feedback_rows=[_feedback(index) for index in range(3)],
        outcome_rows=[{"status": "OUTCOME_EVALUATED", "record_id": "o1", "thesis_result": "SUPPORTED", "benchmark_relative_return_pct": 1.2}],
        thesis_deltas=[{"classification": "NO_NEW_INFO"}],
        research_receipts=[{"research_id": "r1", "usefulness": "NO_NEW_INFO"}],
    )
    assert review["schema"] == "CIOWeeklyLearningReview@v1"
    assert review["observation_window_state"] == "UNMEASURED_OBSERVATION_WINDOW"
    assert review["matured_outcomes"] == {"count": 1, "benchmarked_count": 1}
    assert review["no_chain_of_thought"] is True
    assert review["automatic_policy_promotion"] is False
    assert review["memory_behavior_influence"] == 0


def test_weekly_review_requires_five_actual_evaluated_outcomes_for_measured() -> None:
    outcomes = [
        {"status": "OUTCOME_EVALUATED", "record_id": f"o{i}", "thesis_result": "SUPPORTED", "benchmark_relative_return_pct": i}
        for i in range(5)
    ]
    review = build_weekly_learning_review(
        week_ending="2026-08-23",
        decision_rows=[],
        feedback_rows=[],
        outcome_rows=outcomes,
    )
    assert review["observation_window_state"] == "MEASURED"


def test_weekly_review_replay_is_idempotent(tmp_path: Path) -> None:
    review = build_weekly_learning_review(
        week_ending="2026-08-23",
        decision_rows=[],
        feedback_rows=[],
        outcome_rows=[],
    )
    store = tmp_path / "weekly.jsonl"
    first = reconcile_weekly_learning_review(review, store_path=store)
    second = reconcile_weekly_learning_review(review, store_path=store)
    assert first["published"] is True
    assert second["published"] is False
    assert second["reason"] == "NO_NEW_INFO"
    assert len(store.read_text(encoding="utf-8").splitlines()) == 1


def test_learning_sources_have_no_financial_mutation_surface() -> None:
    root = Path(__file__).resolve().parents[1]
    for relative in (
        "scripts/lib/cio_feedback_learning_v1.py",
        "scripts/materialize_cio_weekly_learning.py",
    ):
        source = (root / relative).read_text(encoding="utf-8").lower()
        for forbidden in ("place_order", "cancel_order", "modify_stop", "broker_client", "two_factor"):
            assert forbidden not in source
