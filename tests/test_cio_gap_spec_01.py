"""G-SPEC-01 — SpecialistArtifact workflow_id bind on new writes.

READ_ONLY_ADVISORY. MBI_BEHAVIOR=0.
No DELETE/rewrite of historical jsonl. New writes must stamp workflow_id;
append refuses unbound rows with a structured result so jobs do not crash.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.lib.cio_specialist_artifact import (
    MISSING_WORKFLOW_ID,
    NEW_WRITE_REQUIRES_WORKFLOW_ID,
    SPECIALIST_ARTIFACT_SCHEMA,
    append,
    build,
    load,
    validate,
    workflow_id_bound,
)
from scripts import cio_specialist_sample_audit as sample_audit


def test_policy_flag_is_on():
    assert NEW_WRITE_REQUIRES_WORKFLOW_ID is True


@pytest.mark.parametrize("bad", [None, "", "  ", 0, False])
def test_build_raises_on_null_or_empty_workflow_id(bad):
    with pytest.raises(ValueError, match="workflow_id"):
        build(
            artifact_id="a1",
            provider="stub",
            outcome="VALID",
            workflow_id=bad,  # type: ignore[arg-type]
        )


def test_build_stamps_stripped_workflow_id():
    row = build(
        artifact_id="a1",
        provider="stub",
        outcome="VALID",
        workflow_id="  wf_bound  ",
    )
    assert row["schema"] == SPECIALIST_ARTIFACT_SCHEMA
    assert row["workflow_id"] == "wf_bound"
    assert workflow_id_bound(row["workflow_id"])
    assert validate(row) == []
    assert validate(row, new_write=True) == []


def test_append_refuses_missing_workflow_id_without_writing(tmp_path: Path):
    orphan = {
        "schema": SPECIALIST_ARTIFACT_SCHEMA,
        "artifact_id": "hist_orphan",
        "workflow_id": None,
        "plan_id": "plan_x",
        "research_id": "res_x",
        "provider": "grok_critique",
        "cost_usd": 0.0,
        "outcome": "PARTIAL",
        "source_refs": [],
        "created_at": "2026-08-30T00:00:00+00:00",
        "authority": "READ_ONLY_ADVISORY",
        "financial_action": False,
    }
    # Historical-tolerant validate still passes
    assert validate(orphan) == []
    assert MISSING_WORKFLOW_ID in validate(orphan, new_write=True)

    result = append(tmp_path, orphan)
    assert result["wrote"] is False
    assert result["refused"] is True
    assert result["reason"] == MISSING_WORKFLOW_ID
    assert MISSING_WORKFLOW_ID in result["problems"]
    assert load(tmp_path) == []


def test_append_accepts_bound_row(tmp_path: Path):
    row = build(
        artifact_id="a_bound",
        provider="stub",
        outcome="VALID",
        workflow_id="wf_ok",
        plan_id="p1",
        research_id="res_1",
    )
    result = append(tmp_path, row)
    assert result["wrote"] is True
    assert result.get("refused") is False
    rows = load(tmp_path)
    assert len(rows) == 1
    assert rows[0]["workflow_id"] == "wf_ok"


def test_historical_null_wf_row_remains_loadable(tmp_path: Path):
    """No silent rewrite: raw historical orphans stay readable."""
    cio = tmp_path / "data" / "cio"
    cio.mkdir(parents=True)
    hist = {
        "schema": SPECIALIST_ARTIFACT_SCHEMA,
        "artifact_id": "crit_spcx_legacy",
        "workflow_id": None,
        "plan_id": "plan_legacy",
        "research_id": "res_legacy",
        "provider": "grok_critique",
        "cost_usd": 0.0,
        "outcome": "PARTIAL",
        "source_refs": [],
        "created_at": "2026-08-29T00:00:00+00:00",
        "authority": "READ_ONLY_ADVISORY",
        "financial_action": False,
    }
    store = cio / "cio_specialist_artifacts.jsonl"
    store.write_text(json.dumps(hist) + "\n", encoding="utf-8")
    loaded = load(tmp_path)
    assert len(loaded) == 1
    assert loaded[0]["workflow_id"] is None
    assert validate(loaded[0]) == []  # historical-tolerant


def test_sample_audit_documents_new_write_policy(tmp_path: Path):
    cio = tmp_path / "data" / "cio"
    cio.mkdir(parents=True)
    (cio / "cio_specialist_artifacts.jsonl").write_text("", encoding="utf-8")
    (cio / "cio_workflow_lineage.jsonl").write_text("", encoding="utf-8")
    (cio / "cio_instrument_records.jsonl").write_text("", encoding="utf-8")
    (cio / "cio_plans_projection.json").write_text("{}", encoding="utf-8")
    (cio / "hermes_research_results.jsonl").write_text("", encoding="utf-8")

    doc = sample_audit.audit(tmp_path, limit=10)
    g = doc["gap_g_spec_01"]
    assert g["id"] == "G-SPEC-01"
    assert g["new_write_policy"]["requires_workflow_id"] is True
    assert "missing_workflow_id" in g["new_write_policy"]["append"]
    assert "DLQ" in g["new_write_policy"]["historical_null_wf"]
    assert "new-write" in g["finding"].lower() or "requires workflow_id" in g["finding"]


def test_grok_and_edgar_to_artifact_require_workflow_id():
    from scripts.lib.cio_grok_critique import to_artifact as grok_to_artifact
    from scripts.lib.cio_edgar_proof import to_artifact as edgar_to_artifact

    with pytest.raises(TypeError):
        grok_to_artifact(  # type: ignore[call-arg]
            {"verdict": "VALID", "cost_usd": 0.0},
            artifact_id="a1",
        )
    with pytest.raises(TypeError):
        edgar_to_artifact(  # type: ignore[call-arg]
            {"status": "PROOF", "filing": {}, "issuer": {"symbol": "X"}},
        )

    edgar = edgar_to_artifact(
        {
            "status": "PROOF",
            "filing": {"accession_number": "0001", "form": "10-K"},
            "issuer": {"symbol": "NOC", "issuer": "NOC", "cik": "1"},
        },
        workflow_id="wf_edgar",
        plan_id="p1",
    )
    assert edgar is not None
    assert edgar["workflow_id"] == "wf_edgar"
    assert edgar["provider"] == "edgar"
