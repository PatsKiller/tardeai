"""Flight recorder: canon_frameworks stage wiring (Phase A).

canon_frameworks was UNWIRED: no producer persisted framework_refs/canon_refs/
methodology_ref to cio_workflow_lineage.jsonl, leaving the stage UNKNOWN instead
of LIVE during decision lineage projection.

This test verifies that record_canon_frameworks() writes envelope records with
the required fields so the projection can match by decision_id and derive LIVE.
"""
from pathlib import Path

import pytest

from scripts.lib.cio_decision_lineage_projection import project_decision_lineage
from scripts.lib.cio_lineage import (
    LineageStore,
    iter_lineage_records,
    load_envelope,
    record_canon_frameworks,
)


@pytest.fixture(autouse=True)
def _isolated_identity_registry(tmp_path_factory, monkeypatch):
    """Pin registry away from production for test isolation."""
    monkeypatch.setenv(
        "TRADEAI_IDENTITY_REGISTRY",
        str(tmp_path_factory.mktemp("identity") / "registry.json"),
    )


def test_record_canon_frameworks_persists_framework_refs(tmp_path: Path):
    """canon_frameworks fields persist to lineage and envelope can be loaded."""
    path = tmp_path / "lineage.jsonl"
    workflow_id = "wf_test_canon_1"
    decision_id = "decision_canon_1"

    result = record_canon_frameworks(
        workflow_id,
        decision_id=decision_id,
        framework_refs=["framework_a", "framework_b"],
        canon_refs=["canon_x", "canon_y"],
        methodology_ref="methodology_v1",
        path=path,
    )

    env = load_envelope(workflow_id, path)
    assert env is not None
    assert env.get("framework_refs") == ["framework_a", "framework_b"]
    assert env.get("canon_refs") == ["canon_x", "canon_y"]
    assert env.get("methodology_ref") == "methodology_v1"
    assert env.get("decision_id") == decision_id


def test_record_canon_frameworks_includes_source_ref_for_live_evidence(tmp_path: Path):
    """source_ref and source_as_of fields enable projection to mark stage LIVE."""
    path = tmp_path / "lineage.jsonl"
    workflow_id = "wf_test_canon_2"
    decision_id = "decision_canon_2"

    record_canon_frameworks(
        workflow_id,
        decision_id=decision_id,
        framework_refs=["framework_x"],
        path=path,
    )

    env = load_envelope(workflow_id, path)
    assert env is not None
    assert env.get("source_ref") == "cio_canon_frameworks"
    assert env.get("source_as_of") is not None


def test_canon_frameworks_projects_as_live(tmp_path: Path):
    """Decision lineage projection derives canon_frameworks stage as LIVE when fields present."""
    path = tmp_path / "lineage.jsonl"
    workflow_id = "wf_test_canon_3"
    decision_id = "decision_canon_3"

    record_canon_frameworks(
        workflow_id,
        decision_id=decision_id,
        framework_refs=["f1"],
        canon_refs=["c1"],
        path=path,
    )

    rows = iter_lineage_records(path)
    projection = project_decision_lineage(
        decision_id,
        workflow_records=rows,
    )

    assert projection.get("stages") is not None
    canon_stage = projection["stages"].get("canon_frameworks")
    assert canon_stage is not None
    assert canon_stage.get("state") == "LIVE", f"Expected LIVE but got {canon_stage.get('state')}: {canon_stage.get('state_reason')}"
    assert canon_stage.get("value") == ["f1"]


def test_record_canon_frameworks_idempotent(tmp_path: Path):
    """Duplicate canon_frameworks records result in same envelope fields."""
    path = tmp_path / "lineage.jsonl"
    workflow_id = "wf_test_canon_4"
    decision_id = "decision_canon_4"

    record_canon_frameworks(
        workflow_id,
        decision_id=decision_id,
        framework_refs=["f1"],
        path=path,
    )
    env1 = load_envelope(workflow_id, path)

    record_canon_frameworks(
        workflow_id,
        decision_id=decision_id,
        framework_refs=["f1"],
        path=path,
    )
    env2 = load_envelope(workflow_id, path)

    # Envelopes should have the same stage fields (semantic_key avoids true duplicates)
    assert env1.get("framework_refs") == env2.get("framework_refs")
    assert env1.get("decision_id") == env2.get("decision_id")
