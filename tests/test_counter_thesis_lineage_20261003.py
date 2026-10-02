"""Flight recorder: counter_thesis stage wiring (Phase B).

counter_thesis was DARK: producer reads the stage but doesn't write counter_thesis/
counter_case to cio_workflow_lineage.jsonl, leaving the stage UNKNOWN instead of LIVE
during decision lineage projection.

This test verifies that record_counter_thesis() writes envelope records with the required
fields so the projection can match by decision_id and derive LIVE.
"""
from pathlib import Path

import pytest

from scripts.lib.cio_decision_lineage_projection import project_decision_lineage
from scripts.lib.cio_lineage import (
    iter_lineage_records,
    load_envelope,
    record_counter_thesis,
)


@pytest.fixture(autouse=True)
def _isolated_identity_registry(tmp_path_factory, monkeypatch):
    """Pin registry away from production for test isolation."""
    monkeypatch.setenv(
        "TRADEAI_IDENTITY_REGISTRY",
        str(tmp_path_factory.mktemp("identity") / "registry.json"),
    )


def test_record_counter_thesis_persists_fields(tmp_path: Path):
    """counter_thesis fields persist to lineage and envelope can be loaded."""
    path = tmp_path / "lineage.jsonl"
    workflow_id = "wf_test_counter_1"
    decision_id = "decision_counter_1"

    record_counter_thesis(
        workflow_id,
        decision_id=decision_id,
        counter_thesis="bearish_scenario",
        counter_case="Fed rate hikes exceed consensus",
        path=path,
    )

    env = load_envelope(workflow_id, path)
    assert env is not None
    assert env.get("counter_thesis") == "bearish_scenario"
    assert env.get("counter_case") == "Fed rate hikes exceed consensus"
    assert env.get("decision_id") == decision_id


def test_record_counter_thesis_includes_source_ref(tmp_path: Path):
    """source_ref and source_as_of fields enable projection to mark stage LIVE."""
    path = tmp_path / "lineage.jsonl"
    workflow_id = "wf_test_counter_2"
    decision_id = "decision_counter_2"

    record_counter_thesis(
        workflow_id,
        decision_id=decision_id,
        counter_thesis="bullish_alternative",
        path=path,
    )

    env = load_envelope(workflow_id, path)
    assert env is not None
    assert env.get("source_ref") == "cio_counter_thesis"
    assert env.get("source_as_of") is not None


def test_counter_thesis_projects_as_live(tmp_path: Path):
    """Decision lineage projection derives counter_thesis stage as LIVE."""
    path = tmp_path / "lineage.jsonl"
    workflow_id = "wf_test_counter_3"
    decision_id = "decision_counter_3"

    record_counter_thesis(
        workflow_id,
        decision_id=decision_id,
        counter_thesis="risk_scenario",
        counter_case="Black swan event in emerging markets",
        path=path,
    )

    rows = iter_lineage_records(path)
    projection = project_decision_lineage(
        decision_id,
        workflow_records=rows,
    )

    assert projection.get("stages") is not None
    counter_stage = projection["stages"].get("counter_thesis")
    assert counter_stage is not None
    assert counter_stage.get("state") == "LIVE", f"Expected LIVE but got {counter_stage.get('state')}: {counter_stage.get('state_reason')}"
    assert counter_stage.get("value") == "risk_scenario"
