"""Flight recorder: falsifier stage wiring (Phase B).

falsifier was DARK: producer reads the stage but doesn't write falsifier/invalidation/
invalidation_condition to cio_workflow_lineage.jsonl, leaving the stage UNKNOWN instead
of LIVE during decision lineage projection.

This test verifies that record_falsifier() writes envelope records with the required
fields so the projection can match by decision_id and derive LIVE.
"""
from pathlib import Path

import pytest

from scripts.lib.cio_decision_lineage_projection import project_decision_lineage
from scripts.lib.cio_lineage import (
    iter_lineage_records,
    load_envelope,
    record_falsifier,
)


@pytest.fixture(autouse=True)
def _isolated_identity_registry(tmp_path_factory, monkeypatch):
    """Pin registry away from production for test isolation."""
    monkeypatch.setenv(
        "TRADEAI_IDENTITY_REGISTRY",
        str(tmp_path_factory.mktemp("identity") / "registry.json"),
    )


def test_record_falsifier_persists_fields(tmp_path: Path):
    """falsifier fields persist to lineage and envelope can be loaded."""
    path = tmp_path / "lineage.jsonl"
    workflow_id = "wf_test_falsifier_1"
    decision_id = "decision_falsifier_1"

    record_falsifier(
        workflow_id,
        decision_id=decision_id,
        falsifier="regulatory_change",
        invalidation="SEC rule change prohibits strategy",
        invalidation_condition="IF SEC_RULE_2024_XYZ THEN ABANDON",
        path=path,
    )

    env = load_envelope(workflow_id, path)
    assert env is not None
    assert env.get("falsifier") == "regulatory_change"
    assert env.get("invalidation") == "SEC rule change prohibits strategy"
    assert env.get("invalidation_condition") == "IF SEC_RULE_2024_XYZ THEN ABANDON"
    assert env.get("decision_id") == decision_id


def test_record_falsifier_includes_source_ref(tmp_path: Path):
    """source_ref and source_as_of fields enable projection to mark stage LIVE."""
    path = tmp_path / "lineage.jsonl"
    workflow_id = "wf_test_falsifier_2"
    decision_id = "decision_falsifier_2"

    record_falsifier(
        workflow_id,
        decision_id=decision_id,
        falsifier="market_condition",
        path=path,
    )

    env = load_envelope(workflow_id, path)
    assert env is not None
    assert env.get("source_ref") == "cio_falsifier"
    assert env.get("source_as_of") is not None


def test_falsifier_projects_as_live(tmp_path: Path):
    """Decision lineage projection derives falsifier stage as LIVE."""
    path = tmp_path / "lineage.jsonl"
    workflow_id = "wf_test_falsifier_3"
    decision_id = "decision_falsifier_3"

    record_falsifier(
        workflow_id,
        decision_id=decision_id,
        falsifier="liquidity_event",
        invalidation_condition="IF price_movement > 5% THEN review",
        path=path,
    )

    rows = iter_lineage_records(path)
    projection = project_decision_lineage(
        decision_id,
        workflow_records=rows,
    )

    assert projection.get("stages") is not None
    falsifier_stage = projection["stages"].get("falsifier")
    assert falsifier_stage is not None
    assert falsifier_stage.get("state") == "LIVE", f"Expected LIVE but got {falsifier_stage.get('state')}: {falsifier_stage.get('state_reason')}"
    assert falsifier_stage.get("value") == "liquidity_event"


def test_falsifier_with_only_condition(tmp_path: Path):
    """falsifier can be persisted with just invalidation_condition."""
    path = tmp_path / "lineage.jsonl"
    workflow_id = "wf_test_falsifier_4"
    decision_id = "decision_falsifier_4"

    record_falsifier(
        workflow_id,
        decision_id=decision_id,
        invalidation_condition="stop_loss_triggered",
        path=path,
    )

    env = load_envelope(workflow_id, path)
    assert env is not None
    assert env.get("invalidation_condition") == "stop_loss_triggered"
    assert env.get("decision_id") == decision_id
