"""Flight recorder: model_route stage wiring (Phase B).

model_route was DARK: producer reads the stage but doesn't write model_route/model_used/
provider/model_provider to cio_workflow_lineage.jsonl, leaving the stage UNKNOWN
instead of LIVE during decision lineage projection.

This test verifies that record_model_route() writes envelope records with the required
fields so the projection can match by decision_id and derive LIVE.
"""
from pathlib import Path

import pytest

from scripts.lib.cio_decision_lineage_projection import project_decision_lineage
from scripts.lib.cio_lineage import (
    iter_lineage_records,
    load_envelope,
    record_model_route,
)


@pytest.fixture(autouse=True)
def _isolated_identity_registry(tmp_path_factory, monkeypatch):
    """Pin registry away from production for test isolation."""
    monkeypatch.setenv(
        "TRADEAI_IDENTITY_REGISTRY",
        str(tmp_path_factory.mktemp("identity") / "registry.json"),
    )


def test_record_model_route_persists_fields(tmp_path: Path):
    """model_route fields persist to lineage and envelope can be loaded."""
    path = tmp_path / "lineage.jsonl"
    workflow_id = "wf_test_model_1"
    decision_id = "decision_model_1"

    result = record_model_route(
        workflow_id,
        decision_id=decision_id,
        model_route="primary_claude",
        model_used="claude-opus-5-5",
        provider="anthropic",
        model_provider="Anthropic",
        path=path,
    )

    env = load_envelope(workflow_id, path)
    assert env is not None
    assert env.get("model_route") == "primary_claude"
    assert env.get("model_used") == "claude-opus-5-5"
    assert env.get("provider") == "anthropic"
    assert env.get("model_provider") == "Anthropic"
    assert env.get("decision_id") == decision_id


def test_record_model_route_includes_source_ref(tmp_path: Path):
    """source_ref and source_as_of fields enable projection to mark stage LIVE."""
    path = tmp_path / "lineage.jsonl"
    workflow_id = "wf_test_model_2"
    decision_id = "decision_model_2"

    record_model_route(
        workflow_id,
        decision_id=decision_id,
        model_used="gpt-4",
        path=path,
    )

    env = load_envelope(workflow_id, path)
    assert env is not None
    assert env.get("source_ref") == "cio_model_route"
    assert env.get("source_as_of") is not None


def test_model_route_projects_as_live(tmp_path: Path):
    """Decision lineage projection derives model_route stage as LIVE when fields present."""
    path = tmp_path / "lineage.jsonl"
    workflow_id = "wf_test_model_3"
    decision_id = "decision_model_3"

    record_model_route(
        workflow_id,
        decision_id=decision_id,
        model_route="fast_path",
        model_used="gpt-4-turbo",
        path=path,
    )

    rows = iter_lineage_records(path)
    projection = project_decision_lineage(
        decision_id,
        workflow_records=rows,
    )

    assert projection.get("stages") is not None
    model_stage = projection["stages"].get("model_route")
    assert model_stage is not None
    assert model_stage.get("state") == "LIVE", f"Expected LIVE but got {model_stage.get('state')}: {model_stage.get('state_reason')}"
    assert model_stage.get("value") == "fast_path"
