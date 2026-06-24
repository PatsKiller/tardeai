"""Tests for report_synthesis — v2 actionable holding report sections."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from report_synthesis import (  # noqa: E402
    HOLDING_REPORT_SECTIONS,
    aggregate_holdings,
    build_action_steps,
    compose_symbol_sections,
    entry_quality,
    evaluate_agents,
    news_impact,
    thesis_status,
)


def _mock_holdings_loader():
    return [
        {
            "symbol": "LDOS",
            "account": "ira_trad",
            "shares": 5.2,
            "cost_basis": 934.23,
            "gain_loss": -382.81,
            "gain_loss_pct": -40.94,
            "market_value": 551.42,
            "portfolio_pct": 0.04,
            "current_price": 106.04,
            "name": "Leidos Holdings",
            "cost_basis_source": "broker",
        },
    ]


def test_holding_report_sections_order():
    assert HOLDING_REPORT_SECTIONS[0] == "header_context"
    assert "action_plan" in HOLDING_REPORT_SECTIONS
    assert "intelligence_view" in HOLDING_REPORT_SECTIONS
    assert HOLDING_REPORT_SECTIONS.index("action_plan") > HOLDING_REPORT_SECTIONS.index("intelligence_view")


def test_aggregate_holdings_merges_accounts():
    agg = aggregate_holdings("LDOS", _mock_holdings_loader)
    assert agg["entry_price"] == pytest.approx(934.23 / 5.2, rel=1e-3)
    assert agg["unrealized_pnl_pct"] == pytest.approx(-40.94, rel=1e-2)
    assert "ira trad" in agg["accounts"][0].lower()


def test_entry_quality_drawdown():
    assert "Poor" in entry_quality(-40.9, None)
    assert "Strong" in entry_quality(20, None)


def test_news_impact_keywords():
    assert news_impact("Jefferies downgrade", "") == "Negative"
    assert news_impact("Contract award", "") == "Positive"
    assert news_impact("Quarterly update", "") == "Neutral"


def test_evaluate_agents_scores_relevance():
    agents = [
        {"agent": "risk_agent", "recommendation": "HOLD", "confidence": 0.7, "summary": "x" * 30},
        {"agent": "steph", "recommendation": "BUY", "confidence": 0.8, "summary": "y" * 30},
    ]
    synthesis = {"recommendation": "ADD"}
    evaluated, para = evaluate_agents(agents, synthesis, None)
    assert len(evaluated) == 2
    assert any("Relevant" in e["relevance"] or "Mixed" in e["relevance"] for e in evaluated)
    assert "Agent panel" in para


def test_build_action_steps_underwater():
    steps = build_action_steps(
        "ADD",
        price=106.0,
        personal={"portfolio_pct": 0.04, "unrealized_pnl_pct": -40.9},
        proposal=None,
        enrich={},
        pro={"target_mean_price": 178.27},
        thesis="At risk",
    )
    assert any("P&L" in s for s in steps)
    assert any("thesis" in s.lower() for s in steps)


def test_thesis_status_from_proposal():
    assert thesis_status(None, {"thesis_validity": {"zone_status": "invalid"}}, {}) == "Broken"
    assert thesis_status({"conflicts_detected": True}, None, {}) == "At risk"


def test_compose_symbol_sections_ldos_shape():
    personal = aggregate_holdings("LDOS", _mock_holdings_loader)
    enrich = {
        "price": 106.04,
        "company": "Leidos Holdings",
        "sector": "Industrials",
        "day_change_pct": -1.2,
        "rsi": 45,
        "sma20_pct": -2,
        "sma50_pct": -5,
        "pe": 18,
        "forward_pe": 16,
    }
    sections = compose_symbol_sections(
        symbol="LDOS",
        enrich=enrich,
        holding=personal.get("primary"),
        personal=personal,
        wl=None,
        synthesis={"recommendation": "ADD", "decision_safety": "safe"},
        agents=[{"agent": "risk_agent", "recommendation": "HOLD", "summary": "a" * 40}],
        ensemble={"final_decision": "block", "final_score": 4.2, "final_confidence": 0.55, "lanes_used": ["grok"]},
        news=[{"title": "Defense budget update", "source": "Reuters", "date": "2026-06-01"}],
        proposal={"thesis_validity": {"zone_status": "ok", "drift_pct": -3}},
        sections=list(HOLDING_REPORT_SECTIONS),
        report_type="symbol_holding",
        exec_metrics={"recommendation": "ADD", "confidence": 72, "confidence_label": "Medium"},
    )
    ids = [s["id"] for s in sections]
    assert "report_continuity" in ids
    assert ids.index("report_continuity") > ids.index("personal_performance")
    pp = next(s for s in sections if s["id"] == "personal_performance")
    assert "unrealized" in pp["content"].lower() or "entry" in pp["content"].lower()
    ap = next(s for s in sections if s["id"] == "action_plan")
    assert ap.get("bullets")
    intel = next(s for s in sections if s["id"] == "intelligence_view")
    assert intel.get("agents")
    assert "Across" in intel.get("content", "") or "agent" in intel.get("content", "").lower()
    assert not any(len(str(b)) > 200 for b in (intel.get("bullets") or []))


def test_ldos_builder_v3_integration():
    from analyst_report_builder import build_symbol_report

    report = build_symbol_report("LDOS", report_type="symbol_holding")
    assert report["meta"]["version"] == "3.0"
    ids = {s["id"] for s in report["sections"]}
    assert "personal_performance" in ids
    assert "action_plan" in ids
    assert "intelligence_view" in ids
    assert "agent_synthesis" not in ids
    intel = next(s for s in report["sections"] if s["id"] == "intelligence_view")
    assert intel.get("agents") is not None
    exec_sec = next(s for s in report["sections"] if s["id"] == "executive_summary")
    assert exec_sec.get("callouts")
    assert report["meta"]["kpis"].get("entry_price") is not None