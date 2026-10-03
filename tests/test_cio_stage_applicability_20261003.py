"""StageApplicability@v1: recorded deterministic origins mark model/specialist stages NOT_APPLICABLE.

Operator-approved 2026-10-03 (join design phase 2). Keyed only on the producer's
recorded decision_origin; any model evidence on the decision vetoes the contract;
a matched row, UNWIRED and a store outage all win over it.
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

from scripts.lib.agent_decision_payload import VALID_ORIGINS, payload_from_holdings_health  # noqa: E402
from scripts.lib.cio_stage_applicability import not_applicable_reason  # noqa: E402

AS_OF = "2026-10-02T11:20:33+00:00"
CONTRACT_STAGES = ("model_route", "counter_thesis", "falsifier", "specialist_delegation")


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_IDENTITY_REGISTRY", str(tmp_path / "registry.json"))
    stub = types.ModuleType("api_v2")
    stub._db_query = lambda sql, params, fetch=None: None
    monkeypatch.setitem(sys.modules, "api_v2", stub)


def _stages(monkeypatch, tmp_path: Path, decision: dict, *, drop: tuple[str, ...] = ()) -> dict:
    import scripts.api_v3_cio as api

    root = tmp_path / "cio"
    root.mkdir(parents=True)
    for name in ("cio_workflow_lineage.jsonl", "intelligence_lineages.jsonl",
                 "outcome_checkpoints.jsonl", "decision_dispositions.jsonl"):
        if name not in drop:
            (root / name).write_text("", encoding="utf-8")
    did = decision["decision_id"]
    trace = {"agent": "alex", "role": decision.get("surface", "reentry"), "trace_id": "tr_1", "wake_id": "wake_1",
             "started_at": AS_OF, "ended_at": AS_OF, "status": "completed",
             "decision": {"as_of": AS_OF, "current_action": "WAIT", "inputs_digest": "ctx",
                          "wake_id": "wake_1", "trace_id": "tr_1", **decision}}
    (root / "agent_run_traces.jsonl").write_text(json.dumps(trace) + "\n", encoding="utf-8")
    monkeypatch.setenv("TRADEAI_CIO_DIR", str(root))
    monkeypatch.setattr(api, "load_known_decision_catalog", lambda: {})
    result = api.get_cio_decision_lineage(did)
    assert result["ok"] is True, result
    return result["lineage"]["stages"]


def test_deterministic_reentry_marks_contract_stages_not_applicable(tmp_path, monkeypatch):
    stages = _stages(monkeypatch, tmp_path, {"decision_id": "dec_reentry_X", "surface": "reentry",
                                             "decision_origin": "DETERMINISTIC_RANK"})
    for name in CONTRACT_STAGES:
        assert stages[name]["state"] == "NOT_APPLICABLE", name
        assert "StageApplicability@v1" in stages[name]["state_reason"]
        assert "decision_origin=DETERMINISTIC_RANK" in stages[name]["state_reason"]
        assert stages[name]["source_ref"], name
    # Research is consumed as prior state by deterministic surfaces: never declared absent.
    for name in ("research_retrieved", "research_used", "research_rejected"):
        assert stages[name]["state"] != "NOT_APPLICABLE", name
    # UNWIRED wins over the contract.
    assert stages["specialist_disagreement"]["state"] == "UNWIRED"


def test_holdings_llm_decision_keeps_model_live_and_is_never_contracted(tmp_path, monkeypatch):
    payload = payload_from_holdings_health(
        {"symbol": "SCHG", "action": "HOLD", "confidence": 55, "health": "STABLE", "model": "grok-3-mini"},
        wake_id="wake_h")
    assert payload["decision_origin"] == "LLM_JUDGMENT"
    stages = _stages(monkeypatch, tmp_path, {**payload, "decision_id": "dec_holdings_SCHG_HOLD", "surface": "holdings"})
    assert stages["model_route"]["state"] == "LIVE" and stages["model_route"]["value"] == "grok-3-mini"
    for name in ("counter_thesis", "falsifier"):
        assert stages[name]["state"] != "NOT_APPLICABLE", name


def test_stale_deterministic_label_with_a_model_is_vetoed(tmp_path, monkeypatch):
    # Existing holdings traces carry DETERMINISTIC_RANK and a model: the model vetoes the contract.
    stages = _stages(monkeypatch, tmp_path, {"decision_id": "dec_holdings_OLD", "surface": "holdings",
                                             "decision_origin": "DETERMINISTIC_RANK", "model": "grok-3-mini"})
    assert stages["model_route"]["state"] == "LIVE"
    assert stages["counter_thesis"]["state"] == "UNKNOWN"
    assert stages["falsifier"]["state"] == "UNKNOWN"


@pytest.mark.parametrize("origin", [None, "", "OPERATOR_ASK", "SOMETHING_NEW"])
def test_missing_or_unlisted_origin_stays_unknown(tmp_path, monkeypatch, origin):
    decision = {"decision_id": "dec_x", "surface": "watch"}
    if origin is not None:
        decision["decision_origin"] = origin
    stages = _stages(monkeypatch, tmp_path, decision)
    for name in CONTRACT_STAGES:
        assert stages[name]["state"] == "UNKNOWN", (origin, name)


def test_matched_row_wins_over_contract(tmp_path, monkeypatch):
    stages = _stages(monkeypatch, tmp_path, {"decision_id": "dec_r", "surface": "reentry",
                                             "decision_origin": "DETERMINISTIC_RANK",
                                             "falsifier": "close below 41.20 before 2026-11-01"})
    assert stages["falsifier"]["state"] == "LIVE"
    assert stages["model_route"]["state"] == "NOT_APPLICABLE"


def test_store_outage_beats_contract(tmp_path, monkeypatch):
    stages = _stages(monkeypatch, tmp_path, {"decision_id": "dec_o", "surface": "reentry",
                                             "decision_origin": "DETERMINISTIC_RANK"},
                     drop=("cio_workflow_lineage.jsonl",))
    for name in CONTRACT_STAGES:
        assert stages[name]["state"] == "UNAVAILABLE", name


def test_contract_pure_rules():
    assert "LLM_JUDGMENT" in VALID_ORIGINS
    assert not_applicable_reason(None, "model_route") is None
    assert not_applicable_reason({"decision_origin": "LLM_JUDGMENT"}, "model_route") is None
    assert not_applicable_reason({"decision_origin": "deterministic_rank"}, "model_route")
    assert not_applicable_reason({"decision_origin": "DETERMINISTIC_RANK"}, "research_used") is None
    assert not_applicable_reason({"decision_origin": "DETERMINISTIC_RANK"}, "confidence") is None
