"""Phase 1 — DecisionPayload@v1 capture (flag-gated, fail-soft)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.agent_decision_payload import (  # noqa: E402
    PAYLOAD_SCHEMA,
    build_decision_payload,
    count_decision_payloads,
    decision_payload_enabled,
    emit_decision_payload,
    emit_payloads_for_decisions,
    infer_decision_origin,
    payload_from_material_decision,
    payload_from_symbol_intelligence,
)
from scripts.lib.agent_feature_flags import DEFAULT_FLAGS, load_feature_flags  # noqa: E402
from scripts.lib.agent_runtime_instrumentation import instrument_material_wake  # noqa: E402


def _flags(**kw):
    base = load_feature_flags({})
    base.update(kw)
    return base


def test_flag_defaults_off():
    assert DEFAULT_FLAGS.get("AGENT_DECISION_PAYLOAD") == 0
    assert load_feature_flags({})["AGENT_DECISION_PAYLOAD"] == 0
    assert decision_payload_enabled(_flags()) is False


def test_flag_off_emit_is_noop(tmp_path):
    tp = tmp_path / "traces.jsonl"
    pl = build_decision_payload(
        decision_id="dec_x",
        wake_id="wake_x",
        symbol="UBER",
        surface="material_scan",
        current_action="WAIT",
    )
    res = emit_decision_payload(pl, flags=_flags(AGENT_DECISION_PAYLOAD=0), path=tp)
    assert res["emitted"] is False
    assert not tp.exists()


def test_flag_off_parity_instrumentation_unchanged(tmp_path):
    """Decision-payload flag alone must not flip instrument_material_wake ON path."""
    res = instrument_material_wake(
        {"wake_id": "w1"},
        flags=_flags(AGENT_CONTEXT_ENVELOPE=0, AGENT_RUN_TRACE=0, AGENT_DECISION_PAYLOAD=1),
        trace_path=tmp_path / "t.jsonl",
    )
    # instrumentation still off (those flags are separate)
    assert res["instrumented"] is False
    assert res["trace_appended"] is False


def test_build_payload_schema_and_origin():
    pl = build_decision_payload(
        decision_id="dec_1",
        wake_id="wake_1",
        symbol="uber",
        surface="reentry",
        current_action="NEAR",
        decision_origin="DETERMINISTIC_RANK",
        confidence=6.5,
    )
    assert pl["schema"] == PAYLOAD_SCHEMA
    assert pl["symbol"] == "UBER"
    assert pl["current_action"] == "NEAR"
    assert pl["authority"] == "READ_ONLY_ADVISORY"
    assert pl["financial_action"] is False
    assert pl["confidence"] == 6.5
    assert infer_decision_origin(trigger="RESEARCH_COMPLETED") == "FRESH_RESEARCH"
    assert infer_decision_origin(trigger="GOAL_DUE") == "DETERMINISTIC_RANK"
    assert infer_decision_origin(synthesized=True) == "SYNTHESIZED"


def test_emit_on_appends_completed_trace(tmp_path):
    tp = tmp_path / "traces.jsonl"
    pl = build_decision_payload(
        decision_id="dec_uber_1",
        wake_id="wake_scan_1",
        symbol="UBER",
        surface="material_scan",
        current_action="WAIT",
        decision_origin="DETERMINISTIC_RANK",
    )
    res = emit_decision_payload(pl, flags=_flags(AGENT_DECISION_PAYLOAD=1), path=tp)
    assert res["emitted"] is True
    assert tp.exists()
    rows = [json.loads(l) for l in tp.read_text().splitlines() if l.strip()]
    assert len(rows) == 1
    assert rows[0]["status"] == "completed"
    assert rows[0]["decision"]["schema"] == PAYLOAD_SCHEMA
    assert rows[0]["decision"]["decision_id"] == "dec_uber_1"
    assert "chain_of_thought" not in json.dumps(rows[0])


def test_emit_payloads_for_decisions_batch(tmp_path):
    tp = tmp_path / "traces.jsonl"
    decisions = [
        {"decision_id": "dec_a", "symbol": "AAA", "standing_recommendation": "HOLD"},
        {"decision_id": "dec_b", "symbol": "BBB", "action": "TRIM"},
    ]
    out = emit_payloads_for_decisions(
        decisions,
        wake_id="wake_batch",
        surface="material_scan",
        flags=_flags(AGENT_DECISION_PAYLOAD=1),
        path=tp,
    )
    assert out["enabled"] is True
    assert out["attempted"] == 2
    assert out["emitted"] == 2
    cov = count_decision_payloads(tp)
    assert cov["with_decision_payload_v1"] == 2


def test_emit_fail_soft_bad_path(tmp_path):
    # Unwritable path → emitted False, no raise
    bad = tmp_path / "no_such_dir" / "nested" / "t.jsonl"
    # Make parent a file so mkdir fails
    blocker = tmp_path / "no_such_dir"
    blocker.write_text("notadir")
    pl = build_decision_payload(decision_id="dec_z", wake_id="w", symbol="Z", current_action="WAIT")
    res = emit_decision_payload(pl, flags=_flags(AGENT_DECISION_PAYLOAD=1), path=bad)
    assert res["emitted"] is False
    assert res.get("error")


def test_payload_from_symbol_intelligence():
    card = {
        "symbol": "UBER",
        "object_id": "sio_UBER_reentry_added_NEAR",
        "change": {"kind": "reentry_added", "to": "NEAR"},
        "technical": {"status": "NEAR"},
        "provenance": {"decision_origin": "FRESH_RESEARCH", "trigger": "RESEARCH_COMPLETED"},
        "thesis": {"confidence_0_10": 5.0},
    }
    pl = payload_from_symbol_intelligence(card, wake_id="wake_prod_1")
    assert pl["surface"] == "reentry"
    assert pl["current_action"] == "NEAR"
    assert pl["decision_origin"] == "FRESH_RESEARCH"


def test_payload_from_material_decision():
    d = {
        "decision_id": "dec_cash_1",
        "symbol": "CASH",
        "standing_recommendation": "HOLD",
        "trigger": "GOAL_DUE",
    }
    pl = payload_from_material_decision(d, wake_id="wake_x")
    assert pl["decision_id"] == "dec_cash_1"
    assert pl["decision_origin"] == "DETERMINISTIC_RANK"
    assert pl["current_action"] == "HOLD"


def test_redact_strips_forbidden_extras(tmp_path):
    tp = tmp_path / "t.jsonl"
    pl = build_decision_payload(
        decision_id="dec_r",
        wake_id="w",
        symbol="X",
        current_action="WAIT",
        extra={"chain_of_thought": "secret thoughts", "note": "ok"},
    )
    assert "chain_of_thought" not in pl
    assert pl.get("note") == "ok"
    emit_decision_payload(pl, flags=_flags(AGENT_DECISION_PAYLOAD=1), path=tp)
    text = tp.read_text()
    assert "secret thoughts" not in text
