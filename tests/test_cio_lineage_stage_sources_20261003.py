"""Lineage stages read the fields real producers already record.

Measured on prod 2026-10-03: holdings AgentRunTrace decisions record the LLM as
``decision.model`` (grok-3-mini on 305 of 306) and options_cio_review stores its
model, confidence and evidence_against inside ``cio_decisions.metadata`` (46 rows).
The projection matched neither, so model_route / confidence / counter_thesis read
UNKNOWN for decisions that had the evidence. These tests drive the real endpoint
function on rows shaped like those producers write.
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.cio_decision_lineage_projection import review_metadata_fields  # noqa: E402

AS_OF = "2026-10-02T11:20:33.015077+00:00"


def _write(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def _cio_root(tmp_path: Path, traces: list[dict]) -> Path:
    root = tmp_path / "cio"
    root.mkdir(parents=True)
    for name in ("cio_workflow_lineage.jsonl", "intelligence_lineages.jsonl",
                 "outcome_checkpoints.jsonl", "decision_dispositions.jsonl"):
        _write(root / name, [])
    _write(root / "agent_run_traces.jsonl", traces)
    return root


def _stub_db(monkeypatch, row: dict | None) -> None:
    stub = types.ModuleType("api_v2")
    stub._db_query = lambda sql, params, fetch=None: row
    monkeypatch.setitem(sys.modules, "api_v2", stub)


def _lineage(monkeypatch, root: Path, did: str) -> dict:
    import scripts.api_v3_cio as api

    monkeypatch.setenv("TRADEAI_CIO_DIR", str(root))
    monkeypatch.setattr(api, "load_known_decision_catalog", lambda: {})
    result = api.get_cio_decision_lineage(did)
    assert result["ok"] is True, result
    return result["lineage"]["stages"]


def _holdings_trace(did: str, model: str | None) -> dict:
    decision = {
        "schema": "DecisionPayload@v1", "decision_id": did, "surface": "holdings",
        "current_action": "HOLD", "confidence": 55.0, "decision_origin": "DETERMINISTIC_RANK",
        "inputs_digest": "ctx_x", "as_of": AS_OF, "health": "STABLE",
        "wake_id": "wake_h", "trace_id": "tr_h", "authority": "READ_ONLY_ADVISORY",
    }
    if model is not None:
        decision["model"] = model
    return {"agent": "alex", "role": "holdings", "trace_id": "tr_h", "wake_id": "wake_h",
            "started_at": AS_OF, "ended_at": AS_OF, "status": "completed", "decision": decision}


def test_holdings_trace_model_reads_as_live_model_route(tmp_path, monkeypatch):
    _stub_db(monkeypatch, None)
    root = _cio_root(tmp_path, [_holdings_trace("dec_holdings_SCHG_HOLD", "grok-3-mini")])
    stage = _lineage(monkeypatch, root, "dec_holdings_SCHG_HOLD")["model_route"]
    assert stage["state"] == "LIVE"
    assert stage["value"] == "grok-3-mini"
    assert stage["source_ref"].endswith("agent_run_traces.jsonl#tr_h")
    assert stage["source_as_of"]


def test_trace_without_a_model_stays_unknown(tmp_path, monkeypatch):
    _stub_db(monkeypatch, None)
    root = _cio_root(tmp_path, [_holdings_trace("dec_holdings_SCHG_HOLD", None)])
    stages = _lineage(monkeypatch, root, "dec_holdings_SCHG_HOLD")
    assert stages["model_route"]["state"] == "UNKNOWN"
    assert stages["model_route"]["value"] is None


def _options_review_row(metadata_as_text: bool) -> dict:
    meta = {
        "schema": "OptionsCIOReview@v1",
        "position_guid": "pos_1",
        "model": {"model_used": "deepseek-chat", "provider": "deepseek", "cost_estimate": 0.001},
        "review": {
            "outcome": "MONITOR_ONLY", "confidence": "MEDIUM", "reasoning": "r",
            "evidence_for": ["a"], "evidence_against": ["IV rank 12 makes premium thin"],
            "exit_plan_view": "adequate", "unknowns": [],
        },
    }
    return {
        "decision_id": "dec_9f0c", "symbol": "DELL", "action": "MONITOR_ONLY",
        "action_class": "options_thesis_review", "status": "proposed",
        "created_at": AS_OF, "metadata": json.dumps(meta) if metadata_as_text else meta,
    }


def test_options_review_metadata_lights_model_confidence_and_counter_case(tmp_path, monkeypatch):
    for as_text in (True, False):
        _stub_db(monkeypatch, _options_review_row(as_text))
        stages = _lineage(monkeypatch, _cio_root(tmp_path / str(as_text), []), "dec_9f0c")
        assert stages["model_route"]["state"] == "LIVE"
        assert stages["model_route"]["value"] == "deepseek-chat"
        assert stages["confidence"]["state"] == "LIVE"
        assert stages["confidence"]["value"] == "MEDIUM"
        assert stages["counter_thesis"]["state"] == "LIVE"
        assert stages["counter_thesis"]["value"] == ["IV rank 12 makes premium thin"]
        assert stages["model_route"]["source_ref"] == "cio_decisions:dec_9f0c"
        # The review has no falsifier; none is invented from exit_plan_view.
        assert stages["falsifier"]["state"] != "LIVE"
        assert stages["falsifier"]["value"] is None


def test_routine_decision_without_review_metadata_gets_nothing():
    routine = {"decision_id": "dec_r", "action_class": "routine", "metadata": {}}
    assert review_metadata_fields(routine) == {}
    assert review_metadata_fields({"metadata": "not json"}) == {}
    assert review_metadata_fields({"metadata": {"model": {}, "review": {"evidence_against": []}}}) == {}


def test_a_top_level_column_wins_over_a_lifted_review_value(tmp_path, monkeypatch):
    row = _options_review_row(False)
    row["confidence"] = 0.8
    _stub_db(monkeypatch, row)
    stages = _lineage(monkeypatch, _cio_root(tmp_path, []), "dec_9f0c")
    assert stages["confidence"]["value"] == 0.8
