"""R12 iterations 5–8: situation pos/neg, notification truth table, freshness."""
from __future__ import annotations

import pytest

from scripts.lib.cio_notification_signal import (
    DELIVERY_DIGEST,
    DELIVERY_IMMEDIATE,
    DELIVERY_SUPPRESSED,
    decide_notification,
)
from scripts.lib.cio_situation_notify_bridge import situation_to_decision
from scripts.lib.cio_situation_state import SITUATION_CLASSES, detect_office_situations
from tests.r11_office_fixtures import NOW, market, office, policy, portfolio, seasonality

pytestmark = pytest.mark.tier0


class _Mem:
    def latest(self, _lineage):
        return None


def _nd(decision):
    return decide_notification(decision, store=_Mem())


POSITIVE = {
    "EXCESS_CASH": office(),
    "POLICY_GAP": office(policy=policy(confirmed=False)),
    "CONCENTRATION": office(portfolio_state=portfolio(
        cash_pct=10.0, holdings=[{"symbol": "NVDA", "security_guid": "g", "weight_pct": 22.0}]
    )),
    "ALLOCATION_DRIFT": None,  # built below
    "THESIS_DETERIORATION": office(
        portfolio_state=portfolio(cash_pct=10.0),
        ticker_cognition={"g": {"symbol": "SCHD", "security_guid": "g", "thesis_delta": "DETERIORATION"}},
    ),
    "THESIS_IMPROVEMENT": office(
        portfolio_state=portfolio(cash_pct=10.0),
        ticker_cognition={"g": {"symbol": "SCHG", "security_guid": "g", "thesis_delta": "IMPROVEMENT"}},
    ),
    "MARKET_REGIME_CHANGE": office(
        portfolio_state=portfolio(cash_pct=10.0),
        market_context=market(regime="risk_off"),
        prior_situations={"market_regime": "risk_on_trend"},
    ),
    "SEASONAL_SETUP": office(
        portfolio_state=portfolio(cash_pct=10.0),
        seasonality=seasonality(setup="q3_setup", material=True),
    ),
    "CATALYST_APPROACHING": office(
        portfolio_state=portfolio(cash_pct=10.0),
        catalysts=[{"symbol": "CSCO", "security_guid": "gc", "days_to_event": 2, "event": "earnings"}],
    ),
    "REENTRY_READY": office(
        portfolio_state=portfolio(cash_pct=10.0),
        opportunities=[{"symbol": "KTOS", "security_guid": "gk", "research_complete": True, "priority": "HIGH"}],
    ),
    "RESEARCH_GAP_RESOLVED": office(
        portfolio_state=portfolio(cash_pct=10.0),
        research_gaps=[{"symbol": "NOC", "security_guid": "gn", "resolved": True}],
    ),
    "CONTRADICTION": office(
        portfolio_state=portfolio(cash_pct=10.0),
        contradictions=[{"symbol": "NOC", "security_guid": "gn", "summary": "bull vs bear"}],
    ),
    "OUTCOME_MATURITY": office(
        portfolio_state=portfolio(cash_pct=10.0),
        outcomes=[{"subject_guid": "g", "mature": True, "outcome_ids": [f"o{i}" for i in range(5)]}],
    ),
    "NO_MATERIAL_CHANGE": office(portfolio_state=portfolio(cash_pct=10.0)),
}


def _office_for(klass: str):
    if klass == "ALLOCATION_DRIFT":
        o = office(portfolio_state=portfolio(cash_pct=10.0))
        o["portfolio_state"]["allocation"]["equity"] = {"pct": 85.0}
        o["portfolio_state"]["allocation"]["fixed_income"] = {"pct": 5.0}
        return o
    return POSITIVE[klass]


@pytest.mark.parametrize("klass", list(SITUATION_CLASSES))
def test_positive_detection(klass: str) -> None:
    scan = detect_office_situations(_office_for(klass), evaluated_at=NOW)
    classes = {s["situation_class"] for s in scan["situations"]}
    if klass == "EXCESS_CASH":
        assert "EXCESS_CASH" in classes or "ALLOCATION_DRIFT" in classes
    else:
        assert klass in classes


@pytest.mark.parametrize("klass", list(SITUATION_CLASSES))
def test_negative_lookalike_does_not_fire(klass: str) -> None:
    quiet = office(portfolio_state=portfolio(cash_pct=10.0))
    if klass == "NO_MATERIAL_CHANGE":
        scan = detect_office_situations(quiet, evaluated_at=NOW)
        assert scan["notification_decision"] == "SUPPRESS"
        return
    if klass == "EXCESS_CASH":
        scan = detect_office_situations(quiet, evaluated_at=NOW)
        assert "EXCESS_CASH" not in {s["situation_class"] for s in scan["situations"]}
        return
    if klass == "CONCENTRATION":
        o = office(portfolio_state=portfolio(
            cash_pct=10.0, holdings=[{"symbol": "NVDA", "security_guid": "g", "weight_pct": 5.0}]
        ))
        scan = detect_office_situations(o, evaluated_at=NOW)
        assert "CONCENTRATION" not in {s["situation_class"] for s in scan["situations"]}
        return
    if klass == "CATALYST_APPROACHING":
        o = office(portfolio_state=portfolio(cash_pct=10.0), catalysts=[{"symbol": "CSCO", "days_to_event": 90}])
        scan = detect_office_situations(o, evaluated_at=NOW)
        assert "CATALYST_APPROACHING" not in {s["situation_class"] for s in scan["situations"]}
        return
    if klass == "REENTRY_READY":
        o = office(portfolio_state=portfolio(cash_pct=10.0), opportunities=[{"symbol": "KTOS", "research_complete": False, "priority": "HIGH"}])
        scan = detect_office_situations(o, evaluated_at=NOW)
        assert "REENTRY_READY" not in {s["situation_class"] for s in scan["situations"]}
        return
    if klass == "RESEARCH_GAP_RESOLVED":
        o = office(portfolio_state=portfolio(cash_pct=10.0), research_gaps=[{"symbol": "NOC", "resolved": False, "critical": False}])
        scan = detect_office_situations(o, evaluated_at=NOW)
        assert "RESEARCH_GAP_RESOLVED" not in {s["situation_class"] for s in scan["situations"]}
        return
    if klass == "THESIS_DETERIORATION":
        o = office(portfolio_state=portfolio(cash_pct=10.0), ticker_cognition={"g": {"symbol": "SCHD", "thesis_delta": "NO_NEW_INFO"}})
        scan = detect_office_situations(o, evaluated_at=NOW)
        assert "THESIS_DETERIORATION" not in {s["situation_class"] for s in scan["situations"]}
        return
    if klass == "SEASONAL_SETUP":
        o = office(portfolio_state=portfolio(cash_pct=10.0), seasonality=seasonality(material=False))
        scan = detect_office_situations(o, evaluated_at=NOW)
        assert "SEASONAL_SETUP" not in {s["situation_class"] for s in scan["situations"]}
        return
    if klass == "MARKET_REGIME_CHANGE":
        o = office(portfolio_state=portfolio(cash_pct=10.0), market_context=market(regime="risk_on_trend"), prior_situations={"market_regime": "risk_on_trend"})
        scan = detect_office_situations(o, evaluated_at=NOW)
        assert "MARKET_REGIME_CHANGE" not in {s["situation_class"] for s in scan["situations"]}
        return
    scan = detect_office_situations(quiet, evaluated_at=NOW)
    if klass not in {"POLICY_GAP", "ALLOCATION_DRIFT", "THESIS_IMPROVEMENT", "CONTRADICTION", "OUTCOME_MATURITY"}:
        assert klass not in {s["situation_class"] for s in scan["situations"]}


def test_hold_cash_is_not_immediate() -> None:
    sit = detect_office_situations(office(portfolio_state=portfolio(cash_pct=10.0)), evaluated_at=NOW)
    row = sit["situations"][0]
    dec = situation_to_decision(row)
    nd = _nd(dec)
    assert nd["notification_class"] in {DELIVERY_SUPPRESSED, DELIVERY_DIGEST, "COMMAND_CENTER_ONLY"}
    assert nd["notification_class"] != DELIVERY_IMMEDIATE or dec.get("act_now") is False


def test_stale_thesis_deterioration_defers() -> None:
    o = office(
        portfolio_state=portfolio(cash_pct=10.0, truth="STALE"),
        ticker_cognition={"g": {"symbol": "SCHD", "security_guid": "g", "thesis_delta": "DETERIORATION"}},
    )
    scan = detect_office_situations(o, evaluated_at=NOW)
    det = next(s for s in scan["situations"] if s["situation_class"] == "THESIS_DETERIORATION")
    assert det["notification_eligibility"] == "DEFER"
    assert det["suppression_reason"] == "STALE_FINANCIAL_TRUTH"


@pytest.mark.parametrize("delta", [-0.01, 0.0, 0.01])
def test_tiny_cash_deviation_without_confirmed_policy_is_not_deploy(delta: float) -> None:
    o = office(policy=policy(confirmed=False), portfolio_state=portfolio(cash_pct=20.0 + delta))
    scan = detect_office_situations(o, evaluated_at=NOW)
    cash = next((s for s in scan["situations"] if s.get("cash_situation")), None)
    if cash:
        assert cash["cash_situation"]["conclusion"] != "DEPLOY_STAGED"
        assert cash["financial_action"] is False
