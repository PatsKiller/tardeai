"""Closing the completion loop, without manufacturing completions.

`is_complete_to_checkpoint` was false for 97 of 97 workflows and had never once
been true. Both arcs succeeded; each did half the job and neither said so:

    arc A (research)  checkpoint COMPLETED + checkpoint_id, notification never decided
    arc B (CIO)       notification settled, no checkpoint ever written

The repair is to make each arc finish its own record. What must NOT happen is
the predicate getting looser, or a workflow being marked complete because a
field was filled in with a placeholder.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.lib.cio_lineage import (
    load_envelope,
    persist_canonical_checkpoint,
    record_cio_generation,
    record_hermes_completion,
    record_hermes_request,
    record_notification,
)
from scripts.lib.cio_workflow_envelope import is_complete_to_checkpoint


@pytest.fixture(autouse=True)
def _isolated_registry(tmp_path, monkeypatch):
    """Envelope writes resolve identity; never read the production registry."""
    monkeypatch.setenv("TRADEAI_IDENTITY_REGISTRY", str(tmp_path / "registry.json"))


def test_research_completion_settles_its_notification_and_completes(tmp_path):
    """Arc A had a real checkpoint and a real checkpoint_id for 30 workflows.

    It never completed because nothing ever decided about notification, so the
    stage sat at NOT_YET_CREATED and the workflow could not end in either
    direction.
    """
    lineage = tmp_path / "lineage.jsonl"
    request = {"plan_id": "p1", "research_id": "r1", "symbol": "NVDA"}
    workflow = record_hermes_request(request, path=lineage)
    record_hermes_completion(
        request, {"research_id": "r1", "result_id": "res1"}, path=lineage, root=tmp_path)

    env = load_envelope(workflow, lineage)
    assert env["checkpoint_id"]
    assert env["stage_status"]["notification"] == "NOT_REQUIRED"
    assert env["complete_to_checkpoint"] is True


def test_the_notification_decision_records_why(tmp_path):
    """NOT_REQUIRED must be auditable, not a silent flag flip.

    Research produces an observational checkpoint and delivers nothing to the
    operator; the CIO arc owns delivery. A reader has to be able to see that
    reasoning rather than infer it.
    """
    lineage = tmp_path / "lineage.jsonl"
    request = {"plan_id": "p1", "research_id": "r1", "symbol": "NVDA"}
    workflow = record_hermes_request(request, path=lineage)
    record_hermes_completion(
        request, {"research_id": "r1", "result_id": "res1"}, path=lineage, root=tmp_path)

    env = load_envelope(workflow, lineage)
    assert env["suppression_reason"] == "RESEARCH_OBSERVATIONAL_NO_OPERATOR_DELIVERY"
    assert env["notification_classification"] == "NOT_REQUIRED"
    assert env.get("notification_id") in (None, "")  # nothing was delivered


def test_a_cio_run_completes_once_it_records_its_outcome(tmp_path):
    """Arc B synthesised, notified, and wrote no checkpoint on any envelope.

    A run that produced a decision is exactly what OutcomeCheckpoint@v1 exists to
    make reviewable; without one the learning loop has nothing to review.
    """
    lineage = tmp_path / "lineage.jsonl"
    run_id = "47ffdf30-84a3-4eb3-88db-61c42de31126"

    record_cio_generation(run_id, generation_id="gen-1", path=lineage,
                          identity={"subject_id": "wake_goal_goal_7_14", "entity_type": "GOAL"})
    record_notification(run_id, notification_id="ntf-1", classification="IMMEDIATE", path=lineage)
    assert load_envelope(run_id, lineage)["complete_to_checkpoint"] is False

    persist_canonical_checkpoint(
        tmp_path, run_id,
        {"decision_id": run_id, "subject_id": "wake_goal_goal_7_14", "entity_type": "GOAL",
         "recommendation": "OBSERVE", "producer_id": "cio_run_worker",
         "material_generation": "gen-1", "notification_id": "ntf-1"},
        "cio_run", path=lineage)

    env = load_envelope(run_id, lineage)
    assert env["checkpoint_id"]
    assert env["complete_to_checkpoint"] is True


def test_a_goal_wake_is_not_given_a_security_identity(tmp_path):
    """A portfolio goal wake is not about a security.

    Filling `subject_guid` to make it look joinable would produce a confident
    wrong join between a portfolio-level run and an arbitrary security.
    """
    lineage = tmp_path / "lineage.jsonl"
    run_id = "3b741161-e016-4777-90d7-7025c4ea89a3"

    record_cio_generation(run_id, generation_id="gen-2", path=lineage,
                          identity={"subject_id": "wake_goal_goal_9_11", "entity_type": "GOAL"})
    record_notification(run_id, notification_id="ntf-2", classification="IMMEDIATE", path=lineage)
    persist_canonical_checkpoint(
        tmp_path, run_id,
        {"decision_id": run_id, "subject_id": "wake_goal_goal_9_11", "entity_type": "GOAL",
         "recommendation": "OBSERVE", "producer_id": "cio_run_worker"},
        "cio_run", path=lineage)

    env = load_envelope(run_id, lineage)
    assert env["entity_type"] == "GOAL"
    assert env["subject_guid"] is None, "a goal wake has no security identity"
    assert env["complete_to_checkpoint"] is True


def test_a_checkpoint_without_a_notification_decision_still_does_not_complete(tmp_path):
    """The guard. The predicate must not have become permissive.

    A workflow that has a checkpoint but has never decided about notification is
    still ambiguous and must still be incomplete — otherwise this work traded a
    real signal for a cosmetic one.
    """
    lineage = tmp_path / "lineage.jsonl"
    run_id = "ambiguous-run"

    record_cio_generation(run_id, generation_id="gen-3", path=lineage)
    persist_canonical_checkpoint(
        tmp_path, run_id,
        {"decision_id": run_id, "recommendation": "OBSERVE", "producer_id": "test"},
        "sha", path=lineage)

    env = load_envelope(run_id, lineage)
    assert env["checkpoint_id"], "checkpoint really was written"
    assert env["stage_status"]["notification"] == "NOT_YET_CREATED"
    assert env["complete_to_checkpoint"] is False
    assert is_complete_to_checkpoint(env) is False


def test_a_notification_without_a_checkpoint_still_does_not_complete(tmp_path):
    """The other half of the guard: a real checkpoint is still required."""
    lineage = tmp_path / "lineage.jsonl"
    run_id = "no-checkpoint-run"

    record_cio_generation(run_id, generation_id="gen-4", path=lineage)
    record_notification(run_id, notification_id="ntf-4", classification="IMMEDIATE", path=lineage)

    env = load_envelope(run_id, lineage)
    assert env["complete_to_checkpoint"] is False
