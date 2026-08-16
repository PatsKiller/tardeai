"""Phase 7 — decision field parity across surfaces."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from scripts.lib.cio_decision_semantics import (  # noqa: E402
    REQUIRED_DECISION_FIELDS,
    decision_field_parity,
    ensure_decision_fields,
    make_decision_id,
)


def test_required_fields_list():
    assert "decision_id" in REQUIRED_DECISION_FIELDS
    assert "recommended_delta_usd" in REQUIRED_DECISION_FIELDS


def test_parity_matching_surfaces():
    did = make_decision_id("SCHD", "TRIM", -14800.0, "concentration fire")
    plan = [{
        "decision_id": did,
        "symbol": "SCHD",
        "stance_code": "TRIM",
        "recommended_delta_usd": -14800.0,
        "why_now": "concentration fire",
        "current_value_usd": 226000.0,
        "current_weight_pct": 17.6,
        "sizing_method": "clear_fire_staged",
    }]
    cards = [{
        "decision_id": did,
        "symbol": "SCHD",
        "stance_code": "TRIM",
        "recommended_delta_usd": -14800.0,
        "why_now": "concentration fire",
        "current_value_usd": 226000.0,
        "current_weight_pct": 17.6,
        "sizing_method": "clear_fire_staged",
    }]
    r = decision_field_parity(plan, cards)
    assert r["ok"] is True
    assert r["decision_count"] == 1
    assert r["field_mismatches"] == []


def test_parity_detects_delta_mismatch():
    did = make_decision_id("AAA", "TRIM", -1000.0, "x")
    a = [{
        "decision_id": did, "symbol": "AAA", "stance_code": "TRIM",
        "recommended_delta_usd": -1000.0, "why_now": "x",
        "current_value_usd": 10000, "current_weight_pct": 1.0,
        "sizing_method": "scenario_only",
    }]
    b = [{
        "decision_id": did, "symbol": "AAA", "stance_code": "TRIM",
        "recommended_delta_usd": -500.0, "why_now": "x",  # mismatch
        "current_value_usd": 10000, "current_weight_pct": 1.0,
        "sizing_method": "scenario_only",
    }]
    r = decision_field_parity(a, b)
    assert r["ok"] is False
    assert any(m["field"] == "recommended_delta_usd" for m in r["field_mismatches"])


def test_ensure_decision_fields_fills_id():
    row = ensure_decision_fields({
        "symbol": "XYZ",
        "cio_stance": "HOLD",
        "recommended_delta_usd": 0,
        "why_now": "no new desk signal; hold",
    })
    assert row["decision_id"].startswith("dec_")
    assert row["stance_code"] == "HOLD"
    assert row["stance"] == "Hold"


# ─────────────────────────────────────────────────────────────────────────────
# G8 — multi-surface helper (cio_decision_parity)
# ─────────────────────────────────────────────────────────────────────────────

def _g8_row(**overrides):
    row = {
        "decision_id": "dec_schd_trim",
        "decision_input_digest": "in_aaa",
        "decision_evidence_digest": "ev_aaa",
        "symbol": "SCHD",
        "action": "TRIM",
        "stance_code": "TRIM",
        "recommended_delta_usd": -14800.0,
        "why_now": "concentration fire",
    }
    row.update(overrides)
    return row


def test_g8_parity_matching_surfaces():
    from scripts.lib.cio_decision_parity import compare_decision_surfaces
    row = _g8_row()
    r = compare_decision_surfaces(
        plan={"position_decisions": [row]},
        cio_home={"cio_now": {"decisions": [dict(row)]}},
        report={"part_a": {"decisions_now": [dict(row)]}},
        telegram_payload={"decisions": [dict(row)]},
    )
    assert r["ok"] is True
    assert r["missing_from_surface"] == []
    assert r["extra_on_surface"] == []
    assert r["field_mismatch"] == []
    assert r["digest_mismatch"] == []


def test_g8_material_mismatch_not_ok():
    from scripts.lib.cio_decision_parity import compare_decision_surfaces
    plan_row = _g8_row()
    home_row = _g8_row(recommended_delta_usd=-500.0)
    r = compare_decision_surfaces(
        plan={"position_decisions": [plan_row]},
        cio_home={"cio_now": {"decisions": [home_row]}},
        report={"part_a": {"decisions_now": [plan_row]}},
        telegram_payload=plan_row,
    )
    assert r["ok"] is False
    assert any(m["field"] == "recommended_delta_usd" for m in r["field_mismatch"])


def test_g8_missing_and_digest_mismatch():
    from scripts.lib.cio_decision_parity import compare_decision_surfaces
    plan_row = _g8_row()
    report_row = _g8_row(decision_evidence_digest="ev_OTHER")
    r = compare_decision_surfaces(
        plan={"position_decisions": [plan_row, _g8_row(
            decision_id="dec_v_exit", symbol="V", action="EXIT",
            stance_code="EXIT", recommended_delta_usd=-40000.0,
            decision_input_digest="in_v", decision_evidence_digest="ev_v",
        )]},
        cio_home={"cio_now": {"decisions": [plan_row]}},
        report={"part_a": {"decisions_now": [report_row]}},
        telegram_payload={"decisions": [plan_row]},
    )
    assert r["ok"] is False
    assert any(m["decision_id"] == "dec_v_exit" for m in r["missing_from_surface"])
    assert any(m["field"] == "decision_evidence_digest" for m in r["digest_mismatch"])
