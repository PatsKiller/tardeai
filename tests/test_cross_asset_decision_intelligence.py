"""Phase 1 contract tests for cross-asset decision intelligence."""
from __future__ import annotations

import json

import pytest

from scripts.lib.cross_asset_decision import (
    AppendOnlyDecisionStore,
    build_decision_object,
    build_event,
    candidate_expressions,
    coverage_row,
    validate_decision_object,
)


def _decision(signal="BUY", *, held=False, shares=0):
    event = build_event(symbol="ABC", signal=signal, source="test", payload={"price": 10})
    return build_decision_object(
        event=event,
        identity={"symbol": "ABC", "security_guid": "sec-abc", "identity_status": "CONFIRMED"},
        position={"held": held, "shares": shares},
    )


def test_signal_matrix_routes_buy_and_hold_without_live_action():
    buy = _decision("BUY")
    hold = _decision("HOLD", held=True, shares=150)
    assert [x["structure"] for x in buy["expression_comparison"]["candidates"]] == [
        "shares", "cash_secured_put", "long_call", "bull_call_spread"
    ]
    assert [x["structure"] for x in hold["expression_comparison"]["candidates"]] == [
        "shares", "covered_call", "protective_put", "collar"
    ]
    assert buy["financial_action"] is False
    assert buy["expression_comparison"]["decision"] == "SHADOW_ONLY"


def test_covered_call_requires_held_position_and_100_shares():
    assert "covered_call" not in candidate_expressions("HOLD", held=False, shares=0)
    assert "covered_call" not in candidate_expressions("HOLD", held=True, shares=99)
    assert "covered_call" in candidate_expressions("HOLD", held=True, shares=100)


def test_unknown_signal_and_identity_mismatch_fail_closed():
    with pytest.raises(ValueError, match="unsupported_signal"):
        build_event(symbol="ABC", signal="BUY_MORE", source="test")
    event = build_event(symbol="ABC", signal="BUY", source="test")
    with pytest.raises(ValueError, match="identity_symbol_mismatch"):
        build_decision_object(event=event, identity={"symbol": "XYZ"})


def test_validation_rejects_authority_or_schema_mutation():
    obj = _decision()
    obj["financial_action"] = True
    errors = validate_decision_object(obj)
    assert "financial_action_must_be_false" in errors


def test_append_only_store_is_idempotent_and_preserves_rows(tmp_path):
    path = tmp_path / "shadow.jsonl"
    store = AppendOnlyDecisionStore(path)
    obj = _decision()
    assert store.append(obj) == "APPENDED"
    assert store.append(obj) == "DUPLICATE_IGNORED"
    rows = store.read()
    assert len(rows) == 1
    assert json.loads(path.read_text(encoding="utf-8"))["evaluation_id"] == obj["evaluation_id"]


def test_coverage_row_proves_comparison_denominator():
    row = coverage_row(_decision("REENTRY"))
    assert row["expected_count"] == 3
    assert row["generated_count"] == 3
    assert row["state"] == "COVERED"
