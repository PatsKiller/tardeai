"""Phase 3 — Freshness & Materiality gate (pure)."""
from __future__ import annotations

import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from scripts.lib.cio_freshness_materiality_gate import (  # noqa: E402
    FRESHNESS_MATERIALITY_VERSION,
    LABEL_ACT_NOW,
    LABEL_DATA_CONFLICT,
    LABEL_REVIEW,
    LABEL_STALE_REFRESH,
    LABEL_WATCH,
    apply_to_decisions,
    attach_to_capital_plan,
    evaluate_decision_actionability,
)
from scripts.lib import cio_capital_plan as cp  # noqa: E402


NOW = datetime(2026, 8, 14, 15, 0, tzinfo=timezone.utc)  # weekday ~RTH


def _fresh_holdings():
    return {
        "updated_at": (NOW - timedelta(minutes=5)).isoformat(),
        "as_of": "2026-08-14",
        "portfolio_totals": {"total_value": 100_000.0},
        "holdings": [
            {"symbol": "CASH", "is_cash": True, "market_value": 20_000.0, "account": "ira"},
            {
                "symbol": "SCHD",
                "account": "ira",
                "shares": 100,
                "current_price": 100.0,
                "price": 100.0,
                "market_value": 10_000.0,
                "updated_at": (NOW - timedelta(minutes=3)).isoformat(),
                "price_source": "test",
            },
        ],
    }


def test_version():
    assert FRESHNESS_MATERIALITY_VERSION.startswith("freshness_materiality_")


def test_nonzero_delta_alone_not_act_now_without_freshness():
    """Core invariant: delta != 0 is insufficient for ACT NOW."""
    decision = {
        "symbol": "SCHD",
        "stance_code": "TRIM",
        "recommended_delta_usd": -1000.0,
        "why_now": "Advisory TRIM — SCHD",
        "risk": "concentration > cap",
    }
    # No timestamps, no holdings → cannot ACT NOW
    ev = evaluate_decision_actionability(decision, now=NOW)
    assert ev["act_now"] is False
    assert ev["action_label"] != LABEL_ACT_NOW
    assert abs(ev["recommended_delta_usd"]) == 1000.0


def test_stale_holdings_forces_stale_refresh():
    doc = _fresh_holdings()
    doc["updated_at"] = (NOW - timedelta(days=10)).isoformat()
    decision = {
        "symbol": "SCHD",
        "stance_code": "TRIM",
        "recommended_delta_usd": -1000.0,
        "why_now": "Advisory TRIM — SCHD",
        "risk": "concentration > cap",
        "revalidated_at": NOW.isoformat(),
    }
    pos = doc["holdings"][1]
    # even with fresh quote on row, holdings book stale fails required holdings check
    pos["updated_at"] = (NOW - timedelta(minutes=2)).isoformat()
    ft = {"overall_quality": "VERIFIED_AS_OF", "suppress_act_now_symbols": []}
    ev = evaluate_decision_actionability(
        decision, holdings_doc=doc, position_row=pos, financial_truth=ft, now=NOW,
    )
    assert ev["act_now"] is False
    assert ev["action_label"] in (LABEL_STALE_REFRESH, LABEL_REVIEW, LABEL_DATA_CONFLICT)


def test_financial_conflict_blocks_act_now():
    doc = _fresh_holdings()
    decision = {
        "symbol": "DXCM",
        "stance_code": "TRIM",
        "recommended_delta_usd": -500.0,
        "why_now": "Advisory TRIM — DXCM",
        "risk": "within single-name cap",
        "revalidated_at": NOW.isoformat(),
    }
    ft = {
        "overall_quality": "CONFLICTED",
        "suppress_act_now_symbols": ["DXCM"],
        "conflicted_symbols": ["DXCM"],
    }
    ev = evaluate_decision_actionability(
        decision,
        holdings_doc=doc,
        position_row={
            "symbol": "DXCM",
            "updated_at": (NOW - timedelta(minutes=2)).isoformat(),
            "market_value": 5000,
        },
        financial_truth=ft,
        now=NOW,
    )
    assert ev["action_label"] == LABEL_DATA_CONFLICT
    assert ev["act_now"] is False


def test_act_now_when_fresh_material_and_truth_ok():
    doc = _fresh_holdings()
    decision = {
        "symbol": "SCHD",
        "stance_code": "TRIM",
        "recommended_delta_usd": -1000.0,
        "why_now": "Advisory TRIM — SCHD",
        "risk": "concentration > cap",
        "revalidated_at": NOW.isoformat(),
    }
    pos = doc["holdings"][1]
    ft = {"overall_quality": "VERIFIED_AS_OF", "suppress_act_now_symbols": []}
    ev = evaluate_decision_actionability(
        decision, holdings_doc=doc, position_row=pos, financial_truth=ft, now=NOW,
    )
    assert ev["action_label"] == LABEL_ACT_NOW
    assert ev["act_now"] is True
    assert ev["actionable"] is True
    assert ev["evidence_source_count"] >= 2


def test_hold_is_watch_not_act_now():
    doc = _fresh_holdings()
    decision = {
        "symbol": "SCHD",
        "stance_code": "HOLD",
        "recommended_delta_usd": 0.0,
        "why_now": "no new desk signal; hold",
        "risk": "within single-name cap",
        "revalidated_at": NOW.isoformat(),
    }
    ev = evaluate_decision_actionability(
        decision,
        holdings_doc=doc,
        position_row=doc["holdings"][1],
        financial_truth={"overall_quality": "VERIFIED_AS_OF", "suppress_act_now_symbols": []},
        now=NOW,
    )
    assert ev["action_label"] == LABEL_WATCH
    assert ev["act_now"] is False


def test_apply_to_decisions_summary_counts():
    doc = _fresh_holdings()
    decisions = [
        {
            "symbol": "SCHD",
            "decision_id": "dec_schd",
            "stance_code": "TRIM",
            "recommended_delta_usd": -1000.0,
            "why_now": "Advisory TRIM — SCHD",
            "risk": "concentration > cap",
            "revalidated_at": NOW.isoformat(),
        },
        {
            "symbol": "ZZZ",
            "decision_id": "dec_zzz",
            "stance_code": "HOLD",
            "recommended_delta_usd": 0.0,
            "why_now": "no new desk signal; hold",
            "risk": "within single-name cap",
            "revalidated_at": NOW.isoformat(),
        },
    ]
    out, summary = apply_to_decisions(
        decisions,
        holdings_doc=doc,
        financial_truth={"overall_quality": "VERIFIED_AS_OF", "suppress_act_now_symbols": []},
        now=NOW,
    )
    assert len(out) == 2
    assert out[0]["action_label_display"] in (
        "ACT NOW", "REVIEW", "WATCH", "STALE — REFRESH REQUIRED", "DATA CONFLICT", "REVALIDATE",
    )
    assert "counts" in summary
    assert summary["act_now_count"] == summary["counts"].get(LABEL_ACT_NOW, 0)


def test_capital_plan_attaches_freshness_gate():
    doc = {
        "updated_at": (NOW - timedelta(minutes=5)).isoformat(),
        "portfolio_totals": {"total_value": 100_000.0},
        "config": {"accounts": {"ira": {"taxable": False}}},
        "holdings": [
            {"symbol": "CASH", "is_cash": True, "market_value": 20_000.0, "account": "ira"},
            {
                "symbol": "SCHD",
                "account": "ira",
                "shares": 100,
                "current_price": 800,
                "price": 800,
                "market_value": 80_000,
                "updated_at": (NOW - timedelta(minutes=2)).isoformat(),
            },
        ],
    }
    plan = cp.build_capital_plan_from_sources(
        holdings_doc=doc,
        queue={"items": [
            {"symbol": "SCHD", "verdict": "TRIM", "directive_label": "Advisory TRIM — SCHD", "source": "advisory"},
        ]},
        redeploy_open_events=[],
        now=NOW,
    )
    assert "freshness_materiality_gate" in plan
    assert plan["freshness_materiality_gate"].get("version", "").startswith("freshness_materiality_")
    # At least one decision annotated
    decs = plan.get("position_decisions") or []
    assert decs
    assert "action_label" in decs[0]
    assert "action_label_display" in decs[0]


def test_attach_to_capital_plan_idempotent_structure():
    plan = {
        "computed_at": NOW.isoformat(),
        "position_decisions": [
            {
                "symbol": "AAA",
                "stance_code": "HOLD",
                "recommended_delta_usd": 0,
                "why_now": "no new desk signal; hold",
                "risk": "within single-name cap",
            }
        ],
        "financial_truth_gate": {"overall_quality": "VERIFIED_AS_OF", "suppress_act_now_symbols": []},
    }
    out = attach_to_capital_plan(plan, holdings_doc=_fresh_holdings(), now=NOW)
    assert out["freshness_materiality_gate"]["act_now_count"] == 0
