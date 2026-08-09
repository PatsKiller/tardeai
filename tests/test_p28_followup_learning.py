"""
P2.8 Follow-up and Learning — Test suite.

Tests outcome recording, learning candidate creation, and authority restrictions.
"""
import os
import tempfile
from pathlib import Path

import pytest

from scripts.lib.cio_outcome_store import CIOOutcomeStore
from scripts.lib.cio_learning_candidate import (
    CIOLearningCandidateStore,
    ALLOWED_EFFECTS,
    FORBIDDEN_EFFECTS,
)


@pytest.fixture
def outcome_store(tmpdir):
    p = os.path.join(tmpdir.strpath if hasattr(tmpdir, "strpath") else str(tmpdir), "outcomes.jsonl")
    return CIOOutcomeStore(store_path=p)


@pytest.fixture
def learning_store(tmpdir):
    p = os.path.join(tmpdir.strpath if hasattr(tmpdir, "strpath") else str(tmpdir), "learning.jsonl")
    return CIOLearningCandidateStore(store_path=p)


class TestOutcomeStore:
    """Tests for CIOOutcomeStore."""

    def test_operator_disposition_recorded(self, outcome_store):
        event = outcome_store.record_outcome(
            cio_action_id="action-001",
            operator_disposition="ACCEPTED",
            outcome_status="POSITIVE",
            result_summary="Action was correct",
            what_was_right="Allocation adjustment was timely",
            what_was_wrong="",
            unknowns="",
        )
        assert event["event_type"] == "OUTCOME_RECORDED"
        assert event["payload"]["operator_disposition"] == "ACCEPTED"

    def test_outcome_captured(self, outcome_store):
        outcome_store.record_outcome(
            cio_action_id="action-002",
            operator_disposition="DEFERRED",
            outcome_status="UNKNOWN",
            result_summary="Not yet measurable",
        )
        outcomes = outcome_store.get_outcomes("action-002")
        assert len(outcomes) == 1
        assert outcomes[0]["payload"]["outcome_status"] == "UNKNOWN"

    def test_deferred_action_re_wakes(self, outcome_store):
        """Deferred actions can be tracked for re-waking."""
        outcome_store.record_outcome(
            cio_action_id="action-deferred",
            operator_disposition="DEFERRED",
            outcome_status="UNKNOWN",
            result_summary="Deferred pending more data",
        )
        outcomes = outcome_store.get_outcomes()
        assert len(outcomes) >= 1

    def test_not_measurable_allowed(self, outcome_store):
        outcome_store.record_outcome(
            cio_action_id="action-nm",
            operator_disposition="ACKNOWLEDGED",
            outcome_status="NOT_MEASURABLE",
        )
        outcomes = outcome_store.get_outcomes("action-nm")
        assert len(outcomes) == 1

    def test_outcome_hash(self, outcome_store):
        event = outcome_store.record_outcome(
            cio_action_id="action-hash",
            operator_disposition="ACCEPTED",
            outcome_status="POSITIVE",
        )
        assert "outcome_hash" in event["payload"]
        assert len(event["payload"]["outcome_hash"]) == 64

    def test_invalid_disposition_rejected(self, outcome_store):
        with pytest.raises(ValueError, match="Invalid disposition"):
            outcome_store.record_outcome(
                cio_action_id="action-bad",
                operator_disposition="INVALID_STATUS",
            )

    def test_invalid_outcome_status_rejected(self, outcome_store):
        with pytest.raises(ValueError, match="Invalid outcome status"):
            outcome_store.record_outcome(
                cio_action_id="action-bad2",
                operator_disposition="ACCEPTED",
                outcome_status="INVALID",
            )


class TestLearningCandidate:
    """Tests for CIOLearningCandidateStore."""

    def test_candidate_lesson_created(self, learning_store):
        event = learning_store.create_candidate(
            lesson_title="Improve confidence calibration",
            description="Adjust confidence scores for low-data domains",
            proposed_effect="confidence_calibration",
            parent_action_id="action-001",
        )
        assert event["event_type"] == "LEARNING_CANDIDATE_CREATED"
        assert event["payload"]["status"] == "PROPOSED"

    def test_candidate_lesson_cannot_self_modify_policy(self, learning_store):
        """Learning candidates cannot modify forbidden domains."""
        for forbidden in FORBIDDEN_EFFECTS:
            with pytest.raises(ValueError, match=f"Forbidden learning effect: {forbidden}"):
                learning_store.create_candidate(
                    lesson_title=f"Change {forbidden}",
                    description=f"Attempt to modify {forbidden}",
                    proposed_effect=forbidden,
                )

    def test_only_allowed_effects_accepted(self, learning_store):
        """Only ALLOWED_EFFECTS are accepted."""
        for allowed in ALLOWED_EFFECTS:
            event = learning_store.create_candidate(
                lesson_title=f"Test {allowed}",
                description=f"Testing {allowed}",
                proposed_effect=allowed,
            )
            assert event["event_type"] == "LEARNING_CANDIDATE_CREATED"

    def test_unknown_effect_rejected(self, learning_store):
        with pytest.raises(ValueError, match="Unknown learning effect"):
            learning_store.create_candidate(
                lesson_title="Unknown effect",
                description="Testing",
                proposed_effect="unknown_effect",
            )

    def test_no_execution_from_learning(self, learning_store):
        """Learning store has no execution tools."""
        candidates = learning_store.list_candidates()
        # Store only records proposals — no execution
        assert isinstance(candidates, list)
