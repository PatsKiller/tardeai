from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.lib.cio_cash_capital_v1 import (
    build_capital_deployment_plan,
    build_cash_deployment_situation,
    reconcile_capital_plan,
)


NOW = datetime(2026, 8, 23, 15, 0, tzinfo=timezone.utc)


def _policy(confirmed: bool = False) -> dict:
    return {
        "status": "CONFIRMED" if confirmed else "POLICY_REQUIRED",
        "version": "policy_v1",
        "fields": {
            "cash_target_range_pct": {"value": {"min": 5.0, "max": 15.0}, "operator_confirmed": confirmed},
            "minimum_liquidity_reserve_usd": {"value": 25_000.0, "operator_confirmed": confirmed},
        },
    }


def _portfolio(verified: bool = False) -> dict:
    reserved = 25_000.0 if verified else None
    return {
        "version": "portfolio_v1",
        "truth_quality": "VERIFIED" if verified else "UNVERIFIED_INVESTABLE",
        "total_portfolio_value_usd": 1_283_600.72,
        "observed_cash_usd": 578_111.14,
        "investable_cash_usd": 500_000.0 if verified else None,
        "allocation": {"cash": {"pct": 45.0382}},
        "cash_accounts": {
            "ira": {"reserved_cash_usd": reserved},
        },
    }


def _market(verified: bool = False) -> dict:
    return {
        "version": "market_v1",
        "truth_quality": "VERIFIED" if verified else "PARTIAL",
        "fields": {
            "regime": {"value": "risk_on_trend"},
            "fed_funds_rate_pct": {"value": 3.63},
            "ten_two_spread_pct": {"value": 0.5},
            "breadth": {"value": "broad"},
            "vix_close": {"value": 16.01},
            "valuation": {"value": None},
            "macro_calendar": {"value": None},
            "portfolio_earnings_calendar": {"value": None},
        },
    }


def _thesis(current: bool = False) -> dict:
    return {
        "thesis_version": "cio_portfolio@v1",
        "state": "CURRENT" if current else "INSUFFICIENT_DATA",
        "underweight_sleeves": ["equity", "fixed_income"] if current else [],
    }


def _situation(*, confirmed: bool = False, verified: bool = False, thesis_current: bool = False):
    return build_cash_deployment_situation(
        policy=_policy(confirmed),
        portfolio_state=_portfolio(verified),
        market_context=_market(verified),
        seasonality={"version": "season_v1", "truth_quality": "UNAVAILABLE"},
        portfolio_thesis=_thesis(thesis_current),
        evaluated_at=NOW,
    )


def test_actual_shape_blocks_amounts_when_investable_cash_and_policy_are_unverified() -> None:
    situation = _situation()
    plan = build_capital_deployment_plan(situation=situation, portfolio_thesis=_thesis(), evaluated_at=NOW)
    assert situation["observed_cash_usd"] == 578_111.14
    assert situation["cash_pct"] == 45.0382
    assert situation["investable_cash_usd"] is None
    assert situation["deployable_excess_usd"] is None
    assert situation["conclusion"] == "RESEARCH_FIRST"
    assert set(situation["blockers"]) >= {"POLICY_REQUIRED", "INVESTABLE_CASH_UNVERIFIED"}
    # R11: independently material cash with missing policy is a POLICY_GAP operator
    # question — not a deployment recommendation and not silent suppression.
    assert situation["notification"]["class"] == "POLICY_GAP"
    assert situation["notification"]["eligible"] is True
    assert situation["notification"]["operator_question"] is True
    assert situation["deployable_excess_usd"] is None
    assert situation["financial_action"] is False
    assert plan["available_capital_usd"] is None
    assert plan["do_now"] == []
    assert plan["state"] == "BLOCKED"
    assert plan["executable_order"] is None


def test_verified_policy_excess_allows_only_bounded_advisory_sleeve_range() -> None:
    situation = _situation(confirmed=True, verified=True, thesis_current=True)
    plan = build_capital_deployment_plan(
        situation=situation,
        portfolio_thesis=_thesis(current=True),
        methodology_refs=["canon_claim_1"],
        evaluated_at=NOW,
    )
    assert situation["state"] == "CURRENT"
    assert situation["deviation_state"] == "ABOVE_RANGE"
    assert situation["deployable_excess_usd"] == 307_459.89
    assert situation["conclusion"] == "DEPLOY_STAGED"
    assert situation["notification"]["eligible"] is True
    assert len(plan["do_now"]) == 1
    assert plan["do_now"][0]["advisory_allocation_range"]["max_usd"] == 307_459.89
    assert plan["financial_action"] is False
    assert plan["executable_order"] is None


def test_in_range_cash_holds_cash_without_forcing_deployment() -> None:
    portfolio = _portfolio(verified=True)
    portfolio["observed_cash_usd"] = 128_360.07
    portfolio["investable_cash_usd"] = 103_360.07
    portfolio["allocation"]["cash"]["pct"] = 10.0
    situation = build_cash_deployment_situation(
        policy=_policy(True),
        portfolio_state=portfolio,
        market_context=_market(True),
        seasonality={"version": "season_v1", "truth_quality": "VERIFIED"},
        portfolio_thesis=_thesis(True),
        evaluated_at=NOW,
    )
    plan = build_capital_deployment_plan(situation=situation, portfolio_thesis=_thesis(True), evaluated_at=NOW)
    assert situation["conclusion"] == "HOLD_CASH"
    assert situation["material"] is False
    assert situation["notification"]["suppression_reason"] == "CASH_WITHIN_POLICY"
    assert plan["do_now"] == []
    assert plan["keep_cash_short_duration"][0]["role"] == "POLICY_ALIGNED_LIQUIDITY"


def test_identical_plan_replay_is_not_published_twice(tmp_path: Path) -> None:
    store = tmp_path / "capital.jsonl"
    situation = _situation()
    plan = build_capital_deployment_plan(situation=situation, portfolio_thesis=_thesis(), evaluated_at=NOW)
    first = reconcile_capital_plan(situation, plan, store_path=str(store))
    second = reconcile_capital_plan(situation, plan, store_path=str(store))
    assert first["published"] is True
    assert first["plan"]["plan_version"] == "capital_plan@v1"
    assert second["published"] is False
    assert second["reason"] == "NO_NEW_INFO"
    assert len(store.read_text(encoding="utf-8").splitlines()) == 1


def test_tampered_capital_plan_is_rejected(tmp_path: Path) -> None:
    situation = _situation()
    plan = build_capital_deployment_plan(situation=situation, portfolio_thesis=_thesis(), evaluated_at=NOW)
    plan["available_capital_usd"] = 999_999.0
    with pytest.raises(ValueError, match="capital plan content_hash mismatch"):
        reconcile_capital_plan(situation, plan, store_path=str(tmp_path / "capital.jsonl"))


def test_sources_are_advisory_only() -> None:
    source = (Path(__file__).resolve().parents[1] / "scripts/lib/cio_cash_capital_v1.py").read_text(encoding="utf-8").lower()
    for forbidden in ("place_order", "cancel_order", "modify_stop", "broker_client", "two_factor"):
        assert forbidden not in source
