"""Derived stage states for CIODecisionLineage@v1 (review gaps 1, 2 and 5).

A stage is LIVE only when a matched durable row for THIS decision carries a
parseable source_as_of and a source_ref; False/0/"" are never evidence; and
provenance fields are null unless a row matched.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.cio_decision_lineage_projection import (  # noqa: E402
    STAGE_KEYS,
    UNWIRED_STAGES,
    VALID_STATES,
    project_decision_lineage,
)

NOW = "2026-10-02T12:00:00+00:00"


def _stages(**kwargs) -> dict:
    return project_decision_lineage(kwargs.pop("decision_id", "dec_s"), composition_as_of=NOW, **kwargs)["stages"]


def test_every_stage_has_vocab_state_and_reason():
    stages = _stages(decision={"decision_id": "dec_s"})
    assert set(stages) == set(STAGE_KEYS)
    for name, stage in stages.items():
        assert stage["state"] in VALID_STATES, name
        assert stage["state_reason"], name


def test_false_zero_and_empty_are_never_evidence():
    stages = _stages(decision={
        "decision_id": "dec_s", "as_of": NOW, "source_ref": "cio_decisions:dec_s",
        "confidence": 0, "judgment": "", "counter_thesis": False, "falsifier": [], "model_route": "None",
    })
    for name in ("confidence", "judgment", "counter_thesis", "falsifier", "model_route"):
        assert stages[name]["state"] == "UNKNOWN", name
        assert stages[name]["value"] is None


def test_live_requires_source_ref_and_parseable_source_as_of():
    live = _stages(decision={"decision_id": "dec_s", "action": "HOLD", "as_of": NOW, "source_ref": "cio_decisions:dec_s"})
    assert live["judgment"]["state"] == "LIVE"
    assert live["judgment"]["source_ref"] == "cio_decisions:dec_s"
    assert live["judgment"]["source_as_of"] == NOW

    no_clock = _stages(decision={"decision_id": "dec_s", "action": "HOLD", "as_of": "yesterday-ish"})
    assert no_clock["judgment"]["state"] == "PARTIAL"
    assert "source_as_of" in no_clock["judgment"]["state_reason"]
    assert no_clock["judgment"]["source_as_of"] is None


def test_unmatched_stage_has_null_provenance_not_a_hardcoded_store():
    stages = _stages(decision={"decision_id": "dec_s"})
    for name, stage in stages.items():
        if stage["state"] in {"UNKNOWN", "UNWIRED", "UNAVAILABLE"}:
            for field in ("source_ref", "run_id", "trace_id", "source_as_of"):
                assert stage[field] is None, (name, field)
    assert stages["wake_event"]["source_ref"] is None


def test_matched_row_ref_falls_back_to_store_and_row_identity():
    stages = _stages(workflow_records=[{
        "decision_id": "dec_s", "record_type": "envelope", "semantic_key": "env_1",
        "event_id": "evt_1", "workflow_id": "wf_1", "updated_at": NOW,
    }])
    assert stages["wake_event"]["state"] == "LIVE"
    assert stages["wake_event"]["source_ref"] == "cio_workflow_lineage:env_1"
    assert stages["wake_event"]["run_id"] == "wf_1"


def test_unwired_is_declared_per_stage_with_reason_and_only_without_a_match():
    assert set(UNWIRED_STAGES) <= set(STAGE_KEYS)
    assert all(reason for reason in UNWIRED_STAGES.values())
    stages = _stages(decision={"decision_id": "dec_s", "framework_refs": ["canon:1"], "as_of": NOW, "source_ref": "x"})
    assert stages["canon_frameworks"]["state"] == "LIVE"
    unwired = [n for n, s in _stages(decision={"decision_id": "dec_s"}).items() if s["state"] == "UNWIRED"]
    assert sorted(unwired) == sorted(UNWIRED_STAGES)


def test_not_run_only_from_explicit_producer_record():
    env = {"decision_id": "dec_s", "record_type": "envelope", "semantic_key": "env_1", "updated_at": NOW,
           "stage_status": {"notification": "NOT_YET_CREATED", "specialist": "NOT_REQUIRED"}}
    stages = _stages(workflow_records=[env])
    assert stages["notification"]["state"] == "NOT_RUN"
    assert "NOT_YET_CREATED" in stages["notification"]["state_reason"]
    assert stages["specialist_delegation"]["state"] == "NOT_APPLICABLE"
    # A stage without a producer record is never NOT_RUN.
    assert stages["model_route"]["state"] == "UNKNOWN"

    skipped = _stages(decision={"decision_id": "dec_s", "as_of": NOW, "cognition_refs": {"skipped": "non_security_symbol"}})
    assert skipped["institutional_cognition"]["state"] == "NOT_RUN"
    assert "non_security_symbol" in skipped["institutional_cognition"]["state_reason"]


def test_unreadable_store_is_unavailable_not_unknown():
    stages = _stages(
        decision={"decision_id": "dec_s"},
        source_availability={"decision_dispositions": False, "outcome_checkpoints": False, "cio_workflow_lineage": True},
    )
    assert stages["operator_disposition"]["state"] == "UNAVAILABLE"
    assert stages["checkpoint"]["state"] == "UNAVAILABLE"
    assert stages["outcome"]["state"] == "UNAVAILABLE"
    assert stages["model_route"]["state"] == "UNKNOWN"


def test_outcome_pending_until_horizon_matures_then_partial():
    base = {"decision_id": "dec_s", "checkpoint_id": "cp1", "status": "SCHEDULED", "created_at": NOW}
    future = _stages(checkpoint_records=[{**base, "due_at": "2026-10-09T12:00:00+00:00"}])
    assert future["checkpoint"]["state"] == "LIVE"
    assert future["checkpoint"]["source_ref"] == "outcome_checkpoints:cp1"
    assert future["outcome"]["state"] == "PENDING"
    matured = _stages(checkpoint_records=[{**base, "due_at": "2026-09-01T12:00:00+00:00"}])
    assert matured["outcome"]["state"] == "PARTIAL"
    settled = _stages(checkpoint_records=[{**base, "status": "RESOLVED", "outcome_id": "out1",
                                           "resolved_at": "2026-10-01T12:00:00+00:00"}])
    assert settled["outcome"]["state"] == "LIVE"
    assert settled["outcome"]["value"] == "out1"
    not_priceable = _stages(checkpoint_records=[{**base, "status": "NOT_PRICE_RESOLVABLE",
                                                 "resolution_reason": "cash_decision"}])
    assert not_priceable["outcome"]["state"] == "NOT_APPLICABLE"


def test_research_stages_come_from_exact_decision_artifacts():
    research = {
        "sources": [{"source": "hermes_research_results.jsonl", "evidence_class": "DURABLE_RUNTIME_ARTIFACT"}],
        "artifacts": [
            {"artifact_id": "r1", "status": "USED_IN_JUDGMENT", "decision_id": "dec_s",
             "source_ref": "hermes_research_results.jsonl", "source_as_of": NOW},
            {"artifact_id": "r2", "status": "USED_IN_JUDGMENT", "decision_id": "dec_other",
             "source_ref": "hermes_research_results.jsonl", "source_as_of": NOW},
        ],
    }
    stages = _stages(decision={"decision_id": "dec_s"}, research_provenance=research)
    assert stages["research_used"]["state"] == "LIVE"
    assert stages["research_used"]["value"] == ["r1"]
    assert stages["research_retrieved"]["state"] == "LIVE"
    assert stages["research_rejected"]["state"] == "UNKNOWN"
    missing = _stages(decision={"decision_id": "dec_s"}, research_provenance={
        "sources": [{"source": "hermes_research_results.jsonl", "evidence_class": "UNAVAILABLE"}], "artifacts": []})
    assert missing["research_used"]["state"] == "UNAVAILABLE"


def test_request_without_result_is_partial_not_live():
    stages = _stages(workflow_records=[{"decision_id": "dec_s", "record_type": "envelope", "semantic_key": "e",
                                        "research_request_id": "res_1", "updated_at": NOW}])
    assert stages["research_retrieved"]["state"] == "PARTIAL"


def _write(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


def test_api_same_symbol_decisions_resolve_distinct_stages_and_research(tmp_path, monkeypatch):
    import scripts.api_v3_cio as api

    cio_root = tmp_path / "cio"
    cio_root.mkdir()
    _write(cio_root / "cio_workflow_lineage.jsonl", [
        {"decision_id": "dec_schd_a", "workflow_id": "wf_a", "record_type": "envelope", "semantic_key": "env_a",
         "symbol": "SCHD", "subject_guid": "guid-schd", "event_id": "evt_a", "updated_at": "2026-10-01T10:00:00+00:00",
         "stage_status": {"notification": "NOT_YET_CREATED"}},
        {"decision_id": "dec_schd_b", "workflow_id": "wf_b", "record_type": "envelope", "semantic_key": "env_b",
         "symbol": "SCHD", "subject_guid": "guid-schd", "event_id": "evt_b", "updated_at": "2026-10-02T10:00:00+00:00",
         "notification_id": "ntf_b"},
    ])
    _write(cio_root / "intelligence_lineages.jsonl", [])
    _write(cio_root / "outcome_checkpoints.jsonl", [
        {"decision_id": "dec_schd_a", "checkpoint_id": "cp_a", "status": "SCHEDULED", "created_at": NOW,
         "due_at": "2099-01-01T00:00:00+00:00"},
    ])
    _write(cio_root / "decision_dispositions.jsonl", [])
    _write(cio_root / "hermes_research_results.jsonl", [
        {"result_id": "res_a", "decision_id": "dec_schd_a", "symbol": "SCHD", "status": "USED_IN_JUDGMENT",
         "retrieved_at": "2026-10-01T09:00:00+00:00"},
        {"result_id": "res_b", "decision_id": "dec_schd_b", "symbol": "SCHD",
         "retrieved_at": "2026-10-02T09:00:00+00:00"},
    ])
    monkeypatch.setenv("TRADEAI_CIO_DIR", str(cio_root))
    monkeypatch.setattr(api, "load_known_decision_catalog", lambda: {})

    a = api.get_cio_decision_lineage("dec_schd_a")
    b = api.get_cio_decision_lineage("dec_schd_b")
    assert a["ok"] is True and b["ok"] is True
    sa, sb = a["lineage"]["stages"], b["lineage"]["stages"]
    assert sa["wake_event"]["value"] == "evt_a" and sb["wake_event"]["value"] == "evt_b"
    assert sa["wake_event"]["source_ref"] == "cio_workflow_lineage:env_a"
    assert sb["wake_event"]["source_ref"] == "cio_workflow_lineage:env_b"
    assert sa["notification"]["state"] == "NOT_RUN" and sb["notification"]["state"] == "LIVE"
    assert sa["checkpoint"]["state"] == "LIVE" and sa["outcome"]["state"] == "PENDING"
    assert sb["checkpoint"]["state"] == "UNKNOWN" and sb["checkpoint"]["source_ref"] is None
    assert sa["research_used"]["state"] == "LIVE" and sa["research_used"]["value"] == ["res_a"]
    assert sb["research_used"]["state"] == "UNKNOWN"
    assert sb["research_retrieved"]["value"] == ["res_b"]
    ids_a = [x["artifact_id"] for x in a["lineage"]["research_provenance"]["artifacts"]]
    ids_b = [x["artifact_id"] for x in b["lineage"]["research_provenance"]["artifacts"]]
    assert ids_a == ["res_a"] and ids_b == ["res_b"]
    assert a["lineage"]["source_availability"]["decision_dispositions"] is True


def test_api_missing_store_marks_its_stages_unavailable(tmp_path, monkeypatch):
    import scripts.api_v3_cio as api

    cio_root = tmp_path / "cio"
    cio_root.mkdir()
    _write(cio_root / "cio_workflow_lineage.jsonl", [
        {"decision_id": "dec_nostore", "record_type": "envelope", "semantic_key": "env_n", "updated_at": NOW},
    ])
    monkeypatch.setenv("TRADEAI_CIO_DIR", str(cio_root))
    monkeypatch.setattr(api, "load_known_decision_catalog", lambda: {})
    result = api.get_cio_decision_lineage("dec_nostore")
    stages = result["lineage"]["stages"]
    assert stages["checkpoint"]["state"] == "UNAVAILABLE"
    assert stages["operator_disposition"]["state"] == "UNAVAILABLE"
    assert result["lineage"]["source_availability"]["outcome_checkpoints"] is False
