"""Lineage reads the production-case ledger for outcomes and dispositions.

cio_production_cases.jsonl is keyed by decision_id and was never read by the
lineage view. Measured 2026-10-03: 3,030 OUTCOME_OBSERVED events, every one
EXPIRED / horizon_elapsed_no_market_outcome. An expired horizon is a recorded
verdict that no market result was measured; it must never read as a result.
RETRIEVAL_RECORDED is ephemeral and DARWIN_SCORED is a formula, so neither may
witness any stage.
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

AS_OF = "2026-08-15T14:23:21+00:00"
DID = "dec_reentry_26e4e818e03d3419"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_IDENTITY_REGISTRY", str(tmp_path / "registry.json"))
    stub = types.ModuleType("api_v2")
    stub._db_query = lambda sql, params, fetch=None: None
    monkeypatch.setitem(sys.modules, "api_v2", stub)


def _event(event_type: str, payload: dict, **extra) -> dict:
    return {"case_id": "case_abc", "decision_id": DID, "event_type": event_type, "occurred_at": AS_OF,
            "payload": payload, "source": "closed_loop_p0_observer", "authority": "READ_ONLY_ADVISORY", **extra}


def _root(tmp_path: Path, cases: list[dict], dispositions: list[dict] | None = None) -> Path:
    root = tmp_path / "cio"
    root.mkdir(parents=True)
    for name in ("cio_workflow_lineage.jsonl", "intelligence_lineages.jsonl", "outcome_checkpoints.jsonl"):
        (root / name).write_text("", encoding="utf-8")
    (root / "decision_dispositions.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in dispositions or []), encoding="utf-8")
    (root / "cio_production_cases.jsonl").write_text("".join(json.dumps(r) + "\n" for r in cases), encoding="utf-8")
    trace = {"agent": "alex", "role": "material_scan", "trace_id": "tr_1", "wake_id": "wake_1",
             "started_at": AS_OF, "ended_at": AS_OF, "status": "completed",
             "decision": {"decision_id": DID, "as_of": AS_OF, "current_action": "WAIT", "inputs_digest": "ctx",
                          "wake_id": "wake_1", "trace_id": "tr_1", "symbol": "DATA_UNAVAILABLE"}}
    (root / "agent_run_traces.jsonl").write_text(json.dumps(trace) + "\n", encoding="utf-8")
    return root


def _stages(monkeypatch, root: Path) -> dict:
    import scripts.api_v3_cio as api

    monkeypatch.setenv("TRADEAI_CIO_DIR", str(root))
    monkeypatch.setattr(api, "load_known_decision_catalog", lambda: {})
    result = api.get_cio_decision_lineage(DID)
    assert result["ok"] is True, result
    return result["lineage"]["stages"]


EXPIRED = {"evaluation_horizon": "7d", "maturity_at": "2026-08-22T22:34:10+00:00",
           "outcome_status": "EXPIRED", "reason": "horizon_elapsed_no_market_outcome"}


def test_expired_outcome_is_recorded_but_never_a_market_result(tmp_path, monkeypatch):
    stage = _stages(monkeypatch, _root(tmp_path, [_event("OUTCOME_OBSERVED", EXPIRED)]))["outcome"]
    assert stage["state"] == "NOT_APPLICABLE"
    assert stage["value"] == "EXPIRED"
    assert "horizon_elapsed_no_market_outcome" in stage["state_reason"]
    assert "no market result was measured" in stage["state_reason"]
    assert stage["source_ref"] == "cio_production_cases:case_abc#OUTCOME_OBSERVED"
    assert stage["source_as_of"].startswith("2026-08-22")


def test_a_measured_outcome_status_reads_live(tmp_path, monkeypatch):
    measured = {**EXPIRED, "outcome_status": "TARGET_HIT", "reason": "price crossed target"}
    stage = _stages(monkeypatch, _root(tmp_path, [_event("OUTCOME_OBSERVED", measured)]))["outcome"]
    assert stage["state"] == "LIVE" and stage["value"] == "TARGET_HIT"


def test_retrieval_and_darwin_events_witness_no_stage(tmp_path, monkeypatch):
    cases = [
        _event("RETRIEVAL_RECORDED", {"decision_use_audit": {"durable": False, "note": "ephemeral"},
                                      "research_result_id": "res_1", "used_research_ids": ["res_1"]}),
        _event("DARWIN_SCORED", {"darwin_status": "SCORED", "formula": "base50+disp+outcome+audit",
                                 "lesson_id": "les_1", "score_id": "sc_1", "outcome_status": "EXPIRED"}),
    ]
    stages = _stages(monkeypatch, _root(tmp_path, cases))
    for name, stage in stages.items():
        assert "cio_production_cases" not in str(stage["source_ref"] or ""), name
    assert stages["outcome"]["state"] == "UNKNOWN"
    assert stages["belief_calibration_lesson"]["state"] != "LIVE"
    assert stages["research_used"]["state"] != "LIVE"


def test_case_disposition_fills_only_when_the_disposition_store_has_none(tmp_path, monkeypatch):
    legacy = {"case_id": "case_d", "decision_id": DID, "status": "DISPOSITION", "recorded_at": AS_OF,
              "operator_disposition": {"disposition": "ack", "source": "signed_action_link"}}
    stage = _stages(monkeypatch, _root(tmp_path / "a", [legacy]))["operator_disposition"]
    assert stage["state"] == "LIVE"
    assert stage["value"]["disposition"] == "ack"
    assert stage["source_ref"] == "cio_production_cases:case_d#DISPOSITION"

    store_row = {"decision_id": DID, "disposition": "reject", "occurred_at": AS_OF, "source_ref": "decision_dispositions:x"}
    stage = _stages(monkeypatch, _root(tmp_path / "b", [legacy], [store_row]))["operator_disposition"]
    assert stage["source_ref"] == "decision_dispositions:x"
