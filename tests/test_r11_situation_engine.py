"""R11 TIER 0 — situation engine, cash intelligence, POLICY_GAP, authority."""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts.lib.cio_advisory_message import render_advisory_message
from scripts.lib.cio_advisory_synthesis import select_model, synthesize
from scripts.lib.cio_office_cycle import run_office_cycle
from scripts.lib.cio_situation_state import SITUATION_CLASSES, detect_office_situations
from tests.r11_office_fixtures import NOW, market, office, policy, portfolio, seasonality, thesis

pytestmark = pytest.mark.tier0


def test_situation_classes_complete() -> None:
    required = {
        "EXCESS_CASH", "ALLOCATION_DRIFT", "CONCENTRATION", "THESIS_DETERIORATION",
        "THESIS_IMPROVEMENT", "MARKET_REGIME_CHANGE", "SEASONAL_SETUP",
        "CATALYST_APPROACHING", "REENTRY_READY", "RESEARCH_GAP_RESOLVED",
        "CONTRADICTION", "POLICY_GAP", "OUTCOME_MATURITY", "NO_MATERIAL_CHANGE",
    }
    assert required <= set(SITUATION_CLASSES)


def test_excess_cash_deploy_gradually() -> None:
    scan = detect_office_situations(office(), evaluated_at=NOW)
    cash = next(s for s in scan["situations"] if s["situation_class"] in {"EXCESS_CASH", "POLICY_GAP"})
    assert cash["cash_situation"]["conclusion"] == "DEPLOY_STAGED"
    assert cash["notification_eligibility"] == "NOTIFY"
    assert cash["financial_action"] is False
    assert cash["executable_order"] is None
    text = render_advisory_message(cash)
    assert "approximately" in text.lower() or "verified cash" in text.lower()
    assert "deploy gradually" in text.lower()
    assert not text.lstrip().startswith("{")


def test_excess_cash_hold_bad_regime() -> None:
    scan = detect_office_situations(office(market_context=market(regime="risk_off")), evaluated_at=NOW)
    cash = next(s for s in scan["situations"] if s.get("cash_situation"))
    assert cash["cash_situation"]["conclusion"] == "HOLD_CASH"
    assert cash["cash_situation"]["regime_risk_off"] is True
    assert cash["notification_eligibility"] == "NOTIFY"
    text = render_advisory_message(cash)
    assert "hold" in text.lower()
    assert "order" not in text.lower() or "no orders" in text.lower()


def test_missing_policy_is_operator_question_not_silent_suppress() -> None:
    scan = detect_office_situations(office(policy=policy(confirmed=False)), evaluated_at=NOW)
    gap = next(s for s in scan["situations"] if s["situation_class"] == "POLICY_GAP")
    assert gap["notification_eligibility"] == "NOTIFY"
    text = render_advisory_message(gap)
    assert "cannot complete the recommendation" in text.lower()
    assert "cash_target_range_pct" in text
    assert "deploy gradually" not in text.lower()


def test_no_material_change_zero_llm() -> None:
    o = office(portfolio_state=portfolio(cash_pct=10.0, holdings=[]))
    scan = detect_office_situations(o, evaluated_at=NOW)
    assert scan["notification_decision"] == "SUPPRESS"
    choice = select_model(scan)
    assert choice["llm_calls"] == 0
    assert choice["why_model_required"] == "UNCHANGED_NO_MODEL"
    syn = synthesize(scan)
    assert syn["used_llm"] is False
    assert syn["local_generative"] is False


def test_concentration() -> None:
    o = office(portfolio_state=portfolio(
        cash_pct=10.0,
        holdings=[{"symbol": "NVDA", "security_guid": "guid-nvda", "weight_pct": 22.0}],
    ))
    scan = detect_office_situations(o, evaluated_at=NOW)
    hit = next(s for s in scan["situations"] if s["situation_class"] == "CONCENTRATION")
    assert "guid-nvda" in hit["affected_guids"]
    assert hit["notification_eligibility"] == "NOTIFY"


def test_thesis_deterioration_and_improvement() -> None:
    o = office(
        portfolio_state=portfolio(cash_pct=10.0),
        ticker_cognition={
            "guid-schd": {
                "symbol": "SCHD",
                "security_guid": "guid-schd",
                "thesis_delta": "DETERIORATION",
                "support": "margin compression",
            },
            "guid-schg": {
                "symbol": "SCHG",
                "security_guid": "guid-schg",
                "thesis_delta": "IMPROVEMENT",
            },
        },
    )
    scan = detect_office_situations(o, evaluated_at=NOW)
    classes = {s["situation_class"] for s in scan["situations"]}
    assert "THESIS_DETERIORATION" in classes
    assert "THESIS_IMPROVEMENT" in classes


def test_unresolved_identity_does_not_fabricate_guid() -> None:
    o = office(portfolio_state=portfolio(
        cash_pct=10.0,
        holdings=[{"symbol": "PRSO", "weight_pct": 18.0}],
    ))
    scan = detect_office_situations(o, evaluated_at=NOW)
    conc = next(s for s in scan["situations"] if s["situation_class"] in {"CONCENTRATION", "POLICY_GAP"})
    assert conc["identity_unresolved"] is True
    assert conc["affected_guids"][0].startswith("UNRESOLVED:")
    assert "fabricated" not in str(conc).lower()


def test_contradiction_suppresses_action() -> None:
    o = office(
        portfolio_state=portfolio(cash_pct=10.0),
        contradictions=[{"symbol": "NOC", "security_guid": "guid-noc", "summary": "bull vs bear notes"}],
    )
    scan = detect_office_situations(o, evaluated_at=NOW)
    hit = next(s for s in scan["situations"] if s["situation_class"] == "CONTRADICTION")
    assert hit["cio_conclusion"] == "DO_NOT_ACT_WHILE_CONFLICTED"
    assert hit["financial_action"] is False


def test_need_data_defers() -> None:
    o = office(
        portfolio_state=portfolio(cash_pct=10.0),
        research_gaps=[{"symbol": "KTOS", "critical": True, "field": "thesis", "resolved": False}],
    )
    scan = detect_office_situations(o, evaluated_at=NOW)
    assert any(s.get("cio_conclusion") == "NEED_DATA" for s in scan["situations"])
    assert scan["notification_decision"] in {"DEFER", "NOTIFY", "SUPPRESS"}
    assert any(s.get("notification_eligibility") == "DEFER" for s in scan["situations"])


def test_authority_invariants_on_every_situation() -> None:
    scan = detect_office_situations(office(), evaluated_at=NOW)
    assert scan["authority"] == "READ_ONLY_ADVISORY"
    assert scan["memory_behavior_influence"] == 0
    assert scan["financial_action"] is False
    assert scan["executable_order"] is None
    for s in scan["situations"]:
        assert s["authority"] == "READ_ONLY_ADVISORY"
        assert s["financial_action"] is False
        assert s["executable_order"] is None
        assert s["schema"] == "CIOSituationState@v1"


def test_second_cycle_uses_prior_not_raw_history(tmp_path: Path) -> None:
    o = office()
    first = run_office_cycle(o, root=tmp_path, persist=True, evaluated_at=NOW)
    second = run_office_cycle(o, root=tmp_path, persist=True, evaluated_at=NOW)
    assert first["reconstructed_from_raw_history"] is True
    assert second["prior_used"] is True
    assert second["reconstructed_from_raw_history"] is False
    assert second["notification_decision"] == "SUPPRESS"
    reasons = [s.get("suppression_reason") for s in (second.get("situations") or [])]
    assert "SEMANTIC_DEDUPE" in reasons or second["notification_decision"] == "SUPPRESS"


def test_synthesis_never_routes_local() -> None:
    scan = detect_office_situations(office(), evaluated_at=NOW)
    choice = select_model(scan, persisted_summary=None)
    assert choice["requested"] != "local"
    assert "ollama" not in str(choice).lower()
    syn = synthesize(scan, persisted_summary="prior view: excess cash")
    assert syn["used_llm"] is False
    assert syn["model"]["why_model_required"] == "EXISTING_PERSISTED_SUMMARY"
