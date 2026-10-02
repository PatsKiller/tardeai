"""Contract tests for the direct CIODecisionLineage@v1 projection."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.cio_decision_lineage_projection import (  # noqa: E402
    direct_match,
    project_decision_lineage,
)


def _stage(lineage: dict, name: str) -> dict:
    return lineage["stages"][name]


def test_same_symbol_historical_decisions_remain_exactly_distinct():
    workflows = [
        {
            "decision_id": "dec_same_symbol_1",
            "workflow_id": "wf_1",
            "subject_guid": "security-guid-1",
            "event_id": "wake-1",
            "stage_status": {"specialist": "UNWIRED"},
            "producer": "cio-cycle-1",
        },
        {
            "decision_id": "dec_same_symbol_2",
            "workflow_id": "wf_2",
            "subject_guid": "security-guid-2",
            "event_id": "wake-2",
            "stage_status": {"specialist": "PENDING"},
            "producer": "cio-cycle-2",
        },
    ]
    first = project_decision_lineage("dec_same_symbol_1", workflow_records=workflows)
    second = project_decision_lineage("dec_same_symbol_2", workflow_records=workflows)

    assert _stage(first, "security_identity")["value"] == "security-guid-1"
    assert _stage(second, "security_identity")["value"] == "security-guid-2"
    assert _stage(first, "wake_event")["value"] == "wake-1"
    assert _stage(second, "wake_event")["value"] == "wake-2"
    assert _stage(first, "specialist_delegation")["state"] == "UNWIRED"
    assert _stage(second, "specialist_delegation")["state"] == "PENDING"
    assert first["matched_sources"]["workflow_records"] == 1
    assert second["matched_sources"]["workflow_records"] == 1


def test_missing_stage_is_unknown_unless_backend_declares_a_state():
    missing = project_decision_lineage("dec_missing", decision={"decision_id": "dec_missing"})
    assert _stage(missing, "specialist_disagreement")["state"] == "UNKNOWN"
    assert _stage(missing, "canon_frameworks")["state"] == "UNKNOWN"

    declared = project_decision_lineage(
        "dec_declared",
        workflow_records=[
            {
                "decision_id": "dec_declared",
                "record_type": "envelope",
                "stage_status": {
                    "specialist": "UNWIRED",
                    "notification": "PENDING",
                    "checkpoint": "NOT_RUN",
                },
            }
        ],
    )
    assert _stage(declared, "specialist_delegation")["state"] == "UNWIRED"
    assert _stage(declared, "notification")["state"] == "PENDING"
    assert _stage(declared, "checkpoint")["state"] == "NOT_RUN"


def test_checkpoint_without_settled_outcome_is_pending_and_not_fabricated():
    lineage = project_decision_lineage(
        "dec_pending",
        decision={"decision_id": "dec_pending"},
        checkpoint_records=[
            {
                "decision_id": "dec_pending",
                "checkpoint_id": "checkpoint-1",
                "status": "OPEN",
                "recorded_at": "2026-10-01T12:00:00Z",
            }
        ],
        composition_as_of="2026-10-01T12:01:00Z",
    )
    assert _stage(lineage, "outcome")["state"] == "PENDING"
    assert _stage(lineage, "outcome")["value"] is None
    assert lineage["stages"]["checkpoint"]["value"] == "checkpoint-1"
    assert lineage["source_as_of"] == "2026-10-01T12:00:00Z"
    assert lineage["composition_as_of"] == "2026-10-01T12:01:00Z"


def test_projection_is_read_only_and_has_no_execution_authority():
    lineage = project_decision_lineage("dec_authority", decision={"decision_id": "dec_authority"})
    assert lineage["authority"] == "READ_ONLY_ADVISORY"
    assert lineage["financial_action"] is False
    assert lineage["mutation"] is False
    assert lineage["memory_behavior_influence"] == 0


def test_direct_match_never_falls_back_to_symbol_or_neighboring_decision():
    rows = [
        {"decision_id": "dec_exact", "symbol": "SCHD"},
        {"decision_id": "dec_other", "symbol": "SCHD"},
    ]
    assert direct_match("dec_exact", rows) == [rows[0]]
    assert direct_match("dec_absent", rows) == []


def test_frontend_uses_direct_route_and_does_not_infer_backend_state():
    hub = (ROOT / "apps" / "command-center-v3" / "src" / "pages" / "CioHub.tsx").read_text()
    panel = (ROOT / "apps" / "command-center-v3" / "src" / "components" / "cio" / "CioDecisionLineagePanel.tsx").read_text()
    helper = (ROOT / "apps" / "command-center-v3" / "src" / "lib" / "cioDecisionLineage.ts").read_text()

    assert "decisionLineageHref" in hub
    assert "to={`/v3/cio" not in hub
    assert "/api/v3/intelligence/lineages" not in panel
    assert "/api/v3/cio/decision/" in panel
    assert "stage?.state" in panel
    assert "missing specialist" not in panel.lower()
    assert "specialist_artifacts" not in panel
    assert "framework_refs" not in panel
    # Outcome identifiers may be rendered as exact backend links; the panel
    # must not derive an outcome state from their absence.
    assert "missing outcome" not in panel.lower()
    assert "`/cio?tab=evidence-comms" in helper


def test_source_refs_normalize_string_and_list_without_fake_freshness():
    one = project_decision_lineage(
        "dec_ref_1",
        workflow_records=[{"decision_id": "dec_ref_1", "source_ref": "workflow://one", "updated_at": "2026-10-01T01:00:00Z"}],
        composition_as_of="2026-10-01T02:00:00Z",
    )
    many = project_decision_lineage(
        "dec_ref_2",
        workflow_records=[{"decision_id": "dec_ref_2", "source_refs": ["workflow://two", "hermes://two"], "updated_at": "2026-10-01T01:00:00Z"}],
        composition_as_of="2026-10-01T03:00:00Z",
    )
    assert one["source_refs"] == ["workflow://one"]
    assert many["source_refs"] == ["hermes://two", "workflow://two"]
    assert one["source_as_of"] != one["composition_as_of"]


def test_json_contract_has_all_required_stage_keys():
    lineage = project_decision_lineage("dec_schema", decision={"decision_id": "dec_schema"})
    assert set(lineage["stages"]) == {
        "wake_event", "security_identity", "office_truth", "institutional_cognition",
        "canon_frameworks", "research_retrieved", "research_used", "research_rejected",
        "research_gap", "specialist_delegation", "specialist_disagreement", "model_route",
        "judgment", "counter_thesis", "confidence", "falsifier", "notification",
        "operator_disposition", "checkpoint", "outcome", "belief_calibration_lesson",
    }
    json.dumps(lineage)


def test_api_projection_resolves_by_exact_decision_id(tmp_path, monkeypatch):
    import scripts.api_v3_cio as api
    import scripts.api_v2 as api_v2

    cio_root = tmp_path / "cio"
    cio_root.mkdir()
    (cio_root / "cio_workflow_lineage.jsonl").write_text(
        json.dumps({
            "decision_id": "dec_api_exact",
            "workflow_id": "workflow-api",
            "record_type": "envelope",
            "subject_guid": "security-api",
            "event_id": "wake-api",
            "stage_status": {"specialist": "UNWIRED"},
        }) + "\n"
    )
    monkeypatch.setenv("TRADEAI_CIO_DIR", str(cio_root))
    monkeypatch.setattr(api, "load_known_decision_catalog", lambda: {})

    result = api.get_cio_decision_lineage("dec_api_exact")
    assert result["ok"] is True
    assert result["lineage"]["decision_id"] == "dec_api_exact"
    assert result["lineage"]["stages"]["security_identity"]["value"] == "security-api"
    assert result["lineage"]["stages"]["specialist_delegation"]["state"] == "UNWIRED"

    absent = api.get_cio_decision_lineage("dec_api_absent")
    assert absent["ok"] is False
    assert absent["error"] == "decision_lineage_not_found"

    monkeypatch.setattr(api, "get_cio_decision_lineage", lambda decision_id: {
        "ok": True,
        "lineage": {"schema": "CIODecisionLineage@v1", "decision_id": decision_id},
        "authority": "READ_ONLY_ADVISORY",
    })
    status, payload = api_v2.handle("/api/v3/cio/decision/dec_api_exact/lineage")
    assert status == 200
    assert payload["lineage"]["decision_id"] == "dec_api_exact"


def test_lineage_exposes_additive_research_provenance_without_execution_authority():
    research = {
        "schema": "CIOResearchProvenance@v1",
        "decision_id": "dec_research",
        "counts": {"retrieved": 1, "used_in_judgment": 1, "rejected": 0, "unknown": 0},
        "artifacts": [{"artifact_id": "res-1", "status": "USED_IN_JUDGMENT", "decision_id": "dec_research"}],
    }
    lineage = project_decision_lineage("dec_research", decision={"decision_id": "dec_research"}, research_provenance=research)
    assert lineage["research_provenance"]["schema"] == "CIOResearchProvenance@v1"
    assert lineage["research_provenance"]["artifacts"][0]["decision_id"] == "dec_research"
    assert lineage["authority"] == "READ_ONLY_ADVISORY"
    assert lineage["financial_action"] is False
    assert lineage["mutation"] is False


def test_exact_decision_lineage_carries_only_exact_cognition_and_learning_rows(tmp_path, monkeypatch):
    import scripts.api_v3_cio as api

    cio_root = tmp_path / "cio"
    cio_root.mkdir()
    (cio_root / "cio_workflow_lineage.jsonl").write_text(json.dumps({"decision_id": "dec-context", "record_type": "envelope"}) + "\n")
    (cio_root / "memory_contexts.jsonl").write_text(
        json.dumps({"context_id": "ctx-exact", "decision_id": "dec-context", "memory_ids": ["m1"]}) + "\n"
        + json.dumps({"context_id": "ctx-other", "decision_id": "dec-other", "memory_ids": ["m2"]}) + "\n"
    )
    (cio_root / "advisory_outcomes_v1.jsonl").write_text(
        json.dumps({"outcome_id": "out-exact", "decision_id": "dec-context", "status": "PENDING"}) + "\n"
        + json.dumps({"outcome_id": "out-other", "decision_id": "dec-other", "status": "SETTLED"}) + "\n"
    )
    monkeypatch.setenv("TRADEAI_CIO_DIR", str(cio_root))
    monkeypatch.setattr(api, "load_known_decision_catalog", lambda: {})
    result = api.get_cio_decision_lineage("dec-context")
    assert result["ok"] is True
    assert [item["id"] for item in result["lineage"]["institutional_cognition"]["items"]] == ["ctx-exact"]
    assert [row["outcome_id"] for row in result["lineage"]["learning"]["pending_outcomes"]] == ["out-exact"]
    assert result["lineage"]["learning"]["settled_outcomes"] == []


def test_exact_lookup_uses_bounded_tail_and_omits_unrelated_capability_scan(tmp_path, monkeypatch):
    import scripts.api_v3_cio as api
    import scripts.lib.cio_operator_evidence as evidence

    path = tmp_path / "large.jsonl"
    path.write_text("{\"decision_id\": \"other\", \"payload\": \"x\"}\n" * 20 + "{\"decision_id\": \"exact\"}\n")
    monkeypatch.setattr(evidence, "_DECISION_LOOKUP_TAIL_BYTES", 32)
    assert evidence._rows(path, decision_id="exact") == [{"decision_id": "exact"}]

    cio_root = tmp_path / "cio"
    cio_root.mkdir()
    (cio_root / "cio_workflow_lineage.jsonl").write_text(json.dumps({"decision_id": "exact", "record_type": "envelope"}) + "\n")
    monkeypatch.setenv("TRADEAI_CIO_DIR", str(cio_root))
    monkeypatch.setattr(api, "load_known_decision_catalog", lambda: {})
    calls = {}

    def fake_operator_evidence(*, now, decision_id, include_coverage):
        calls.update({"decision_id": decision_id, "include_coverage": include_coverage})
        return {"blocks": {"research": {}, "institutional_cognition": {"items": []}, "learning": {}}}

    monkeypatch.setattr(evidence, "build_operator_evidence", fake_operator_evidence)
    result = api.get_cio_decision_lineage("exact")
    assert result["ok"] is True
    assert calls == {"decision_id": "exact", "include_coverage": False}


def test_frontend_research_provenance_has_required_operator_groups_and_links():
    panel = (ROOT / "apps" / "command-center-v3" / "src" / "components" / "cio" / "CioOperatorEvidencePanel.tsx").read_text()
    lineage_panel = (ROOT / "apps" / "command-center-v3" / "src" / "components" / "cio" / "CioDecisionLineagePanel.tsx").read_text()
    assert "/api/v3/cio/research-provenance" in panel
    assert "Evidence actually used" in panel
    assert "Retrieved but not proven used" in panel
    assert "Rejected with reason" in panel
    assert "Open CIO decision" in panel
    assert "Open security/thesis" in panel
    assert "research-unknown-group" in panel
    assert "decision_id=${encodeURIComponent(decisionId)}" in panel
    assert "Open artifact" in lineage_panel
    assert "Open thesis" in panel
    assert "related_decisions" in panel
    assert "cio-lineage-research-provenance" in lineage_panel
