"""Flight recorder: specialist_disagreement stage wiring (Phase A).

specialist_disagreement was UNWIRED: no producer persisted specialist_disagreement/
disagreement_receipt to cio_workflow_lineage.jsonl, leaving the stage UNKNOWN
instead of LIVE during decision lineage projection.

This test verifies that record_specialist_disagreement() writes envelope records
with the required fields so the projection can match by decision_id and derive LIVE.
"""
from pathlib import Path

import pytest

from scripts.lib.cio_decision_lineage_projection import project_decision_lineage
from scripts.lib.cio_lineage import (
    iter_lineage_records,
    load_envelope,
    record_specialist_disagreement,
)


@pytest.fixture(autouse=True)
def _isolated_identity_registry(tmp_path_factory, monkeypatch):
    """Pin registry away from production for test isolation."""
    monkeypatch.setenv(
        "TRADEAI_IDENTITY_REGISTRY",
        str(tmp_path_factory.mktemp("identity") / "registry.json"),
    )


def test_record_specialist_disagreement_persists_fields(tmp_path: Path):
    """specialist_disagreement fields persist to lineage and envelope can be loaded."""
    path = tmp_path / "lineage.jsonl"
    workflow_id = "wf_test_disagreement_1"
    decision_id = "decision_disagreement_1"

    result = record_specialist_disagreement(
        workflow_id,
        decision_id=decision_id,
        specialist_disagreement="CONSENSUS",
        disagreement_receipt="receipt_consensus_1",
        path=path,
    )

    env = load_envelope(workflow_id, path)
    assert env is not None
    assert env.get("specialist_disagreement") == "CONSENSUS"
    assert env.get("disagreement_receipt") == "receipt_consensus_1"
    assert env.get("decision_id") == decision_id


def test_record_specialist_disagreement_includes_source_ref(tmp_path: Path):
    """source_ref and source_as_of fields enable projection to mark stage LIVE."""
    path = tmp_path / "lineage.jsonl"
    workflow_id = "wf_test_disagreement_2"
    decision_id = "decision_disagreement_2"

    record_specialist_disagreement(
        workflow_id,
        decision_id=decision_id,
        specialist_disagreement="DIVERGENT",
        path=path,
    )

    env = load_envelope(workflow_id, path)
    assert env is not None
    assert env.get("source_ref") == "cio_specialist_disagreement"
    assert env.get("source_as_of") is not None


def test_specialist_disagreement_projects_as_live(tmp_path: Path):
    """Decision lineage projection derives specialist_disagreement stage as LIVE."""
    path = tmp_path / "lineage.jsonl"
    workflow_id = "wf_test_disagreement_3"
    decision_id = "decision_disagreement_3"

    record_specialist_disagreement(
        workflow_id,
        decision_id=decision_id,
        specialist_disagreement="CONSENSUS",
        path=path,
    )

    rows = iter_lineage_records(path)
    projection = project_decision_lineage(
        decision_id,
        workflow_records=rows,
    )

    assert projection.get("stages") is not None
    disagreement_stage = projection["stages"].get("specialist_disagreement")
    assert disagreement_stage is not None
    assert disagreement_stage.get("state") == "LIVE", f"Expected LIVE but got {disagreement_stage.get('state')}: {disagreement_stage.get('state_reason')}"
    assert disagreement_stage.get("value") == "CONSENSUS"


def test_record_specialist_disagreement_idempotent(tmp_path: Path):
    """Duplicate specialist_disagreement records result in same envelope fields."""
    path = tmp_path / "lineage.jsonl"
    workflow_id = "wf_test_disagreement_4"
    decision_id = "decision_disagreement_4"

    record_specialist_disagreement(
        workflow_id,
        decision_id=decision_id,
        specialist_disagreement="CONSENSUS",
        path=path,
    )
    env1 = load_envelope(workflow_id, path)

    record_specialist_disagreement(
        workflow_id,
        decision_id=decision_id,
        specialist_disagreement="CONSENSUS",
        path=path,
    )
    env2 = load_envelope(workflow_id, path)

    # Envelopes should have the same stage fields (semantic_key avoids true duplicates)
    assert env1.get("specialist_disagreement") == env2.get("specialist_disagreement")
    assert env1.get("decision_id") == env2.get("decision_id")


def test_specialist_disagreement_with_only_receipt(tmp_path: Path):
    """specialist_disagreement can be persisted with just disagreement_receipt."""
    path = tmp_path / "lineage.jsonl"
    workflow_id = "wf_test_disagreement_5"
    decision_id = "decision_disagreement_5"

    record_specialist_disagreement(
        workflow_id,
        decision_id=decision_id,
        disagreement_receipt="receipt_123",
        path=path,
    )

    env = load_envelope(workflow_id, path)
    assert env is not None
    assert env.get("disagreement_receipt") == "receipt_123"
    assert env.get("decision_id") == decision_id
