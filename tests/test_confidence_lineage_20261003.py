"""Flight recorder: confidence stage wiring (Phase B).

confidence was DARK: producer reads the stage but doesn't write confidence/
confidence_raw/confidence_score to cio_workflow_lineage.jsonl, leaving the stage
UNKNOWN instead of LIVE during decision lineage projection.

This test verifies that record_confidence() writes envelope records with the required
fields so the projection can match by decision_id and derive LIVE.
"""
from pathlib import Path

import pytest

from scripts.lib.cio_decision_lineage_projection import project_decision_lineage
from scripts.lib.cio_lineage import (
    iter_lineage_records,
    load_envelope,
    record_confidence,
)


@pytest.fixture(autouse=True)
def _isolated_identity_registry(tmp_path_factory, monkeypatch):
    """Pin registry away from production for test isolation."""
    monkeypatch.setenv(
        "TRADEAI_IDENTITY_REGISTRY",
        str(tmp_path_factory.mktemp("identity") / "registry.json"),
    )


def test_record_confidence_persists_fields(tmp_path: Path):
    """confidence fields persist to lineage and envelope can be loaded."""
    path = tmp_path / "lineage.jsonl"
    workflow_id = "wf_test_confidence_1"
    decision_id = "decision_confidence_1"

    record_confidence(
        workflow_id,
        decision_id=decision_id,
        confidence="HIGH",
        confidence_raw="0.92",
        confidence_score=92,
        path=path,
    )

    env = load_envelope(workflow_id, path)
    assert env is not None
    assert env.get("confidence") == "HIGH"
    assert env.get("confidence_raw") == "0.92"
    assert env.get("confidence_score") == 92
    assert env.get("decision_id") == decision_id


def test_record_confidence_with_numeric_score(tmp_path: Path):
    """confidence can be persisted with numeric confidence_score."""
    path = tmp_path / "lineage.jsonl"
    workflow_id = "wf_test_confidence_2"
    decision_id = "decision_confidence_2"

    record_confidence(
        workflow_id,
        decision_id=decision_id,
        confidence_score=85.5,
        path=path,
    )

    env = load_envelope(workflow_id, path)
    assert env is not None
    assert env.get("confidence_score") == 85.5


def test_record_confidence_includes_source_ref(tmp_path: Path):
    """source_ref and source_as_of fields enable projection to mark stage LIVE."""
    path = tmp_path / "lineage.jsonl"
    workflow_id = "wf_test_confidence_3"
    decision_id = "decision_confidence_3"

    record_confidence(
        workflow_id,
        decision_id=decision_id,
        confidence="MEDIUM",
        path=path,
    )

    env = load_envelope(workflow_id, path)
    assert env is not None
    assert env.get("source_ref") == "cio_confidence"
    assert env.get("source_as_of") is not None


def test_confidence_projects_as_live(tmp_path: Path):
    """Decision lineage projection derives confidence stage as LIVE."""
    path = tmp_path / "lineage.jsonl"
    workflow_id = "wf_test_confidence_4"
    decision_id = "decision_confidence_4"

    record_confidence(
        workflow_id,
        decision_id=decision_id,
        confidence="HIGH",
        confidence_score=90,
        path=path,
    )

    rows = iter_lineage_records(path)
    projection = project_decision_lineage(
        decision_id,
        workflow_records=rows,
    )

    assert projection.get("stages") is not None
    confidence_stage = projection["stages"].get("confidence")
    assert confidence_stage is not None
    assert confidence_stage.get("state") == "LIVE", f"Expected LIVE but got {confidence_stage.get('state')}: {confidence_stage.get('state_reason')}"
    assert confidence_stage.get("value") == "HIGH"
