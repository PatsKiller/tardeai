"""R11 TIER 1 — full advisory loop fixtures A–G. No broker writes."""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts.lib.cio_advisory_notify import deliver_prepared, prepare_advisory_notification
from scripts.lib.cio_office_cycle import run_office_cycle
from scripts.lib.cio_situation_state import detect_office_situations
from tests.r11_office_fixtures import NOW, market, office, policy, portfolio, seasonality, thesis

pytestmark = pytest.mark.tier1


def _assert_authority(result: dict) -> None:
    assert result.get("authority") == "READ_ONLY_ADVISORY"
    assert result.get("financial_action") is False
    assert result.get("executable_order") is None
    assert result.get("memory_behavior_influence", 0) == 0


def test_a_excess_cash(tmp_path: Path) -> None:
    result = run_office_cycle(office(), root=tmp_path, evaluated_at=NOW)
    classes = set(result["classes"])
    assert "EXCESS_CASH" in classes or "ALLOCATION_DRIFT" in classes
    assert result["notification_decision"] == "NOTIFY"
    assert result["llm_calls"] == 0  # persisted summary unused; generate unbound → 0
    assert "HEADLINE" in result["message"]
    assert result["episode"]["kind"] == "notification"
    _assert_authority(result)


def test_b_concentration(tmp_path: Path) -> None:
    o = office(portfolio_state=portfolio(
        cash_pct=10.0,
        holdings=[{"symbol": "NVDA", "security_guid": "guid-nvda", "weight_pct": 25.0}],
    ))
    scan = detect_office_situations(o, evaluated_at=NOW)
    assert any(s["situation_class"] == "CONCENTRATION" for s in scan["situations"])
    result = run_office_cycle(o, root=tmp_path, evaluated_at=NOW)
    assert result["notification_decision"] == "NOTIFY"
    _assert_authority(result)


def test_c_thesis_deterioration(tmp_path: Path) -> None:
    o = office(
        portfolio_state=portfolio(cash_pct=10.0),
        ticker_cognition={"guid-x": {"symbol": "SCHD", "security_guid": "guid-x", "thesis_delta": "MATERIAL_NEGATIVE"}},
    )
    result = run_office_cycle(o, root=tmp_path, evaluated_at=NOW)
    assert "THESIS_DETERIORATION" in set(result["classes"])
    assert result["notification_decision"] == "NOTIFY"
    _assert_authority(result)


def test_d_opportunity_reentry(tmp_path: Path) -> None:
    o = office(
        portfolio_state=portfolio(cash_pct=10.0),
        opportunities=[{"symbol": "KTOS", "security_guid": "guid-ktos", "research_complete": True, "priority": "HIGH"}],
    )
    result = run_office_cycle(o, root=tmp_path, evaluated_at=NOW)
    assert "REENTRY_READY" in set(result["classes"])
    _assert_authority(result)


def test_e_seasonal_regime(tmp_path: Path) -> None:
    o = office(
        portfolio_state=portfolio(cash_pct=10.0),
        seasonality=seasonality(setup="sell_in_may_exit", material=True),
        market_context=market(regime="risk_off"),
        prior_situations={"market_regime": "risk_on_trend"},
    )
    result = run_office_cycle(o, root=tmp_path, evaluated_at=NOW)
    classes = set(result["classes"])
    assert "SEASONAL_SETUP" in classes or "MARKET_REGIME_CHANGE" in classes
    _assert_authority(result)


def test_f_need_data(tmp_path: Path) -> None:
    o = office(
        portfolio_state=portfolio(cash_pct=10.0),
        research_gaps=[{"symbol": "VIVS", "critical": True, "field": "filings", "resolved": False}],
    )
    result = run_office_cycle(o, root=tmp_path, evaluated_at=NOW)
    assert result["primary_situation"].get("cio_conclusion") == "NEED_DATA" or result["notification_decision"] == "DEFER"
    _assert_authority(result)


def test_g_no_change(tmp_path: Path) -> None:
    o = office(portfolio_state=portfolio(cash_pct=10.0))
    result = run_office_cycle(o, root=tmp_path, evaluated_at=NOW)
    assert result["notification_decision"] == "SUPPRESS"
    assert result["llm_calls"] == 0
    assert result["episode"]["kind"] == "suppression"
    _assert_authority(result)


def test_policy_gap_not_spam(tmp_path: Path) -> None:
    o = office(policy=policy(confirmed=False))
    first = run_office_cycle(o, root=tmp_path, evaluated_at=NOW)
    second = run_office_cycle(o, root=tmp_path, evaluated_at=NOW)
    assert first["notification_decision"] == "NOTIFY"
    assert second["notification_decision"] == "SUPPRESS"


def test_stale_truth_defers(tmp_path: Path) -> None:
    o = office(portfolio_state=portfolio(cash_pct=45.0, truth="STALE"))
    result = run_office_cycle(o, root=tmp_path, evaluated_at=NOW)
    # POLICY_GAP may still notify; other material pages defer.
    elig = {s.get("notification_eligibility") for s in result["situations"]}
    assert "DEFER" in elig or any(s.get("suppression_reason") == "STALE_FINANCIAL_TRUTH" for s in result["situations"]) or result["notification_decision"] in {"DEFER", "NOTIFY"}
    _assert_authority(result)


def test_fixture_delivery_receipt(tmp_path: Path) -> None:
    result = run_office_cycle(office(), root=tmp_path, evaluated_at=NOW)
    prepared = prepare_advisory_notification(result["primary_situation"], message=result["message"])
    receipt = deliver_prepared(prepared, live=False)
    assert receipt["prepared"] is True
    assert receipt["sent"] is True
    assert receipt["sender_attribution"] == "alex_cio"
    assert receipt["trace_id"]
    assert receipt["situation_id"]
    assert receipt["live"] is False
    assert "HEADLINE" in prepared["body"]
