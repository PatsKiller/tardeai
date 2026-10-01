"""CIO operator-evidence composition tests."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.cio_operator_evidence import build_operator_evidence  # noqa: E402


def _write(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")


def test_retrieved_used_and_rejected_are_distinct_and_receipt_driven(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_CIO_DIR", str(tmp_path))
    _write(tmp_path / "hermes_research_results.jsonl", [
        {"result_id": "res_retrieved", "symbol": "AAA", "created_at": "2026-10-01T10:00:00Z"},
        {"result_id": "res_used", "symbol": "BBB", "used_in_judgment": True, "decision_id": "dec_1", "created_at": "2026-10-01T11:00:00Z"},
        {"result_id": "res_rejected", "symbol": "CCC", "rejection_reason": "contradictory source", "created_at": "2026-10-01T12:00:00Z"},
    ])
    result = build_operator_evidence(now="2026-10-01T13:00:00Z")
    research = result["blocks"]["research"]
    assert research["counts"] == {"retrieved": 1, "used_in_judgment": 1, "rejected": 1, "unknown": 0}
    assert research["used_in_judgment"][0]["decision_id"] == "dec_1"
    assert research["rejected"][0]["reason_used_or_rejected"] == "contradictory source"


def test_missing_receipt_is_not_rejected_or_used(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_CIO_DIR", str(tmp_path))
    _write(tmp_path / "hermes_research_results.jsonl", [{"result_id": "res_unknown", "symbol": "AAA"}])
    result = build_operator_evidence(now="2026-10-01T13:00:00Z")
    artifact = result["blocks"]["research"]["artifacts"][0]
    assert artifact["status"] == "RETRIEVED"
    assert artifact.get("decision_id") is None


def test_generic_research_reason_is_not_a_rejection_receipt(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_CIO_DIR", str(tmp_path))
    _write(tmp_path / "hermes_research_results.jsonl", [{
        "result_id": "res_request_reason",
        "symbol": "AAA",
        "reason": "operator_desk_research_need",
        "created_at": "2026-10-01T10:00:00Z",
    }])
    result = build_operator_evidence(now="2026-10-01T13:00:00Z")
    artifact = result["blocks"]["research"]["artifacts"][0]
    assert artifact["status"] == "RETRIEVED"
    assert artifact["reason_used_or_rejected"] is None


def test_research_projection_preserves_metadata_and_exact_decision_filter(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_CIO_DIR", str(tmp_path))
    _write(tmp_path / "web_evidence_provenance.jsonl", [
        {
            "artifact_id": "web_used",
            "source_type": "filing",
            "publisher": "Issuer",
            "source_url": "https://example.test/filing",
            "publication_date": "2026-09-30",
            "retrieved_at": "2026-10-01T10:00:00Z",
            "source_as_of": "2026-09-30T00:00:00Z",
            "symbol": "AAA",
            "research_run_id": "run-1",
            "agent_model": "model-1",
            "used_in_judgment": True,
            "decision_id": "dec-1",
            "thesis_refs": ["thesis-aaa-v3"],
            "trace_id": "trace-1",
            "evidence_class": "PRIMARY_RESEARCH",
        },
        {"artifact_id": "web_other", "symbol": "AAA", "retrieved_at": "2026-10-01T11:00:00Z", "decision_id": "dec-2"},
    ])
    from scripts.lib.cio_operator_evidence import build_research_provenance

    block = build_research_provenance(tmp_path, decision_id="dec-1")
    assert block["schema"] == "CIOResearchProvenance@v1"
    assert [a["artifact_id"] for a in block["artifacts"]] == ["web_used"]
    assert block["artifacts"][0]["status"] == "USED_IN_JUDGMENT"
    assert block["artifacts"][0]["source_as_of"] == "2026-09-30T00:00:00Z"
    assert block["artifacts"][0]["research_run_id"] == "run-1"
    assert block["artifacts"][0]["trace_id"] == "trace-1"
    assert block["artifacts"][0]["related_decisions"] == ["dec-1"]
    assert block["artifacts"][0]["related_securities"] == ["AAA"]
    assert block["artifacts"][0]["thesis_refs"] == ["thesis-aaa-v3"]
    assert block["composition_as_of"]


def test_research_decision_refs_preserve_exact_historical_links(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_CIO_DIR", str(tmp_path))
    _write(tmp_path / "web_evidence_provenance.jsonl", [
        {"artifact_id": "shared", "symbol": "AAA", "decision_refs": ["dec-old"], "retrieved_at": "2026-09-01T10:00:00Z"},
        {"artifact_id": "shared", "symbol": "AAA", "decision_refs": ["dec-new"], "used_in_judgment": True, "retrieved_at": "2026-10-01T10:00:00Z"},
    ])
    from scripts.lib.cio_operator_evidence import build_research_provenance

    old = build_research_provenance(tmp_path, decision_id="dec-old")
    new = build_research_provenance(tmp_path, decision_id="dec-new")
    assert [item["artifact_id"] for item in old["artifacts"]] == ["shared"]
    assert [item["artifact_id"] for item in new["artifacts"]] == ["shared"]
    assert old["artifacts"][0]["related_decisions"] == ["dec-new", "dec-old"]
    assert new["artifacts"][0]["related_decisions"] == ["dec-new", "dec-old"]


def test_source_clock_does_not_advance_when_only_composition_changes(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_CIO_DIR", str(tmp_path))
    _write(tmp_path / "hermes_research_results.jsonl", [{"result_id": "res_clock", "created_at": "2026-10-01T10:00:00Z"}])
    first = build_operator_evidence(now="2026-10-01T11:00:00Z")
    second = build_operator_evidence(now="2026-10-01T12:00:00Z")
    assert first["source_as_of"] == second["source_as_of"] == "2026-10-01T10:00:00Z"
    assert first["composition_as_of"] != second["composition_as_of"]


def test_capability_state_is_backend_runtime_census_not_frontend_field_absence(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_CIO_DIR", str(tmp_path))
    _write(tmp_path / "cio_specialist_artifacts.jsonl", [{"artifact_id": "sp_1", "created_at": "2026-10-01T09:00:00Z"}])
    _write(tmp_path / "cio_workflow_lineage.jsonl", [{"source_ref": "cio_specialist_artifacts.jsonl", "created_at": "2026-10-01T10:00:00Z"}])
    result = build_operator_evidence(now="2026-10-01T13:00:00Z")
    rows = {row["capability"]: row for row in result["blocks"]["capability_coverage"]["rows"]}
    assert rows["specialist artifacts"]["current_status"] == "LIVE"
    assert rows["specialist artifacts"]["last_consumed_at"] == "2026-10-01T10:00:00Z"
    assert rows["specialist artifacts"]["evidence_class"] == "RUNTIME_ARTIFACT_CENSUS"
    assert rows["InstrumentRecord"]["current_status"] in {"PARTIAL", "DARK", "UNWIRED"}
    assert result["authority"] == "READ_ONLY_ADVISORY"
    assert result["financial_action"] is False
    assert result["mutation"] is False


def test_cio_operator_evidence_api_route_is_read_only():
    import scripts.api_v2 as api_v2

    status, payload = api_v2.handle("/api/v3/cio/operator-evidence")
    assert status == 200
    assert payload["schema"] == "CIOOperatorEvidence@v1"
    assert payload["authority"] == "READ_ONLY_ADVISORY"
    assert payload["financial_action"] is False


def test_research_provenance_api_route_is_read_only(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_CIO_DIR", str(tmp_path))
    import scripts.api_v2 as api_v2

    status, payload = api_v2.handle("/api/v3/cio/research-provenance")
    assert status == 200
    assert payload["schema"] == "CIOResearchProvenance@v1"
    assert payload["authority"] == "READ_ONLY_ADVISORY"
    assert payload["financial_action"] is False
    assert payload["mutation"] is False


def test_cognition_separates_available_retrieved_used_changed_and_contradictory(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_CIO_DIR", str(tmp_path))
    _write(tmp_path / "memory_contexts.jsonl", [
        {"context_id": "ctx-retrieved", "memory_ids": ["m-1"], "created_at": "2026-10-01T10:00:00Z"},
        {
            "context_id": "ctx-used",
            "memory_ids": ["m-2"],
            "used_in_judgment": True,
            "changed_view": True,
            "contradictory": True,
            "created_at": "2026-10-01T11:00:00Z",
        },
    ])
    cognition = build_operator_evidence(now="2026-10-01T12:00:00Z")["blocks"]["institutional_cognition"]
    by_id = {item["id"]: item for item in cognition["items"]}
    assert by_id["ctx-retrieved"]["state"] == "RETRIEVED"
    assert by_id["ctx-retrieved"]["influence"] == "NOT_PROVEN"
    assert by_id["ctx-used"]["state"] == "USED"
    assert by_id["ctx-used"]["changed_question_or_view"] is True
    assert by_id["ctx-used"]["contradictory"] is True
    assert cognition["office_truth_boundary"] == ["price", "holdings", "cash", "orders", "broker_state", "risk_limits"]
    assert cognition["memory_behavior_influence"] == 0


def test_learning_uses_real_outcomes_and_keeps_research_lessons_separate(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_CIO_DIR", str(tmp_path))
    _write(tmp_path / "advisory_outcomes_v1.jsonl", [
        {"outcome_id": "out-1", "decision_id": "dec-1", "status": "SETTLED", "result": "SUCCESS", "created_at": "2026-10-01T10:00:00Z"},
        {"outcome_id": "out-2", "decision_id": "dec-2", "status": "PENDING", "created_at": "2026-10-01T11:00:00Z"},
    ])
    _write(tmp_path / "lesson_candidates.jsonl", [
        {"lesson_id": "lesson-out", "statement": "outcome lesson", "supporting_outcome_ids": ["out-1"], "lesson_provenance": "OUTCOME_DERIVED", "status": "PROVISIONAL"},
        {"lesson_id": "lesson-research", "statement": "research lesson", "research_artifact_ids": ["res-1"], "lesson_provenance": "RESEARCH_DERIVED", "status": "PROVISIONAL"},
        {"lesson_id": "lesson-fake-ready", "statement": "unlinked", "status": "REVIEW_READY"},
    ])
    learning = build_operator_evidence(now="2026-10-01T12:00:00Z")["blocks"]["learning"]
    assert learning["sample_size"] == 1
    assert learning["successful_count"] == 1
    assert learning["success_rate"] == 1.0
    assert learning["maturity_state"] == "INSUFFICIENT_EVIDENCE"
    assert [row["lesson_id"] for row in learning["outcome_derived_lessons"]] == ["lesson-out"]
    assert [row["lesson_id"] for row in learning["research_derived_lessons"]] == ["lesson-research"]
    assert learning["review_ready"] == []
    by_lesson = {row["lesson_id"]: row for row in learning["lessons"]}
    assert by_lesson["lesson-research"]["evidence_state"] == "INSUFFICIENT_EVIDENCE"


def test_coverage_exposes_required_runtime_edge_fields_and_never_uses_ui_absence(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_CIO_DIR", str(tmp_path))
    coverage = build_operator_evidence(now="2026-10-01T12:00:00Z")["blocks"]["capability_coverage"]
    names = {row["capability"] for row in coverage["rows"]}
    required = {
        "InstrumentRecord", "identity resolution", "persistent cognition", "memory retrieval",
        "Hermes research", "external research", "specialist artifacts", "specialist disagreement",
        "CIO synthesis", "judgment", "commitment", "notification policy", "delivery/outbox",
        "operator feedback", "outcome checkpoint", "outcome settlement", "belief writer", "lesson",
        "hypothesis", "graph propagation", "canon retrieval", "historical analogue retrieval",
    }
    assert required <= names
    for row in coverage["rows"]:
        assert row["state"] in {"LIVE", "PARTIAL", "UNWIRED", "DARK", "UNKNOWN"}
        assert "contract" in row and "producer" in row and "consumer" in row
        assert "last_produced_at" in row and "last_consumed_at" in row
        assert "durable_artifact" in row and "artifact_age" in row
        assert row["evidence_class"] == "RUNTIME_ARTIFACT_CENSUS"
        assert "reason" in row and row["reason"]


def test_cio_has_first_class_cognition_learning_and_coverage_views():
    source = (ROOT / "apps" / "command-center-v3" / "src" / "pages" / "CioHub.tsx").read_text()
    assert "institutional-cognition" in source
    assert "learning-cockpit" in source
    assert "capability-coverage" in source
    assert 'section="cognition"' in source
    assert 'section="learning"' in source
    assert 'section="coverage"' in source
