"""Deterministic portfolio stress engine tests."""
from __future__ import annotations

import pytest

from financial_senses.stress_engine import (
    TIER_CASH,
    TIER_SENSITIVITY,
    TIER_SECTOR,
    TIER_UNAVAILABLE,
    PortfolioStressProvider,
    get_scenario,
    stress_portfolio,
)


def _pos(symbol, mv, **kw):
    d = {"symbol": symbol, "market_value": mv}
    d.update(kw)
    return d


def test_all_cash_portfolio_zero_pnl():
    port = {"positions": [_pos("CASH", 100000, cash_like=True)]}
    r = stress_portfolio(port, get_scenario("broad_equity_minus_10").to_dict())
    assert r["estimated_pnl"] == 0.0
    assert r["unmodeled_value"] == 0.0
    assert r["coverage_pct"] == 100.0
    assert r["cash_buffer_effect"] == 0.0


def test_sector_shock_applies_directly():
    port = {"positions": [_pos("AAPL", 100000, sector="technology")]}
    sc = get_scenario("broad_equity_minus_10").to_dict()
    sc["shocks"] = {"sector_shocks": {"technology": -0.15}}
    r = stress_portfolio(port, sc)
    assert r["positions"][0]["tier"] == TIER_SECTOR
    assert r["positions"][0]["pnl"] == pytest.approx(-15000.0)
    assert r["estimated_pnl"] == pytest.approx(-15000.0)


def test_sourced_beta_sensitivity_used():
    port = {
        "positions": [
            _pos("AAPL", 100000, sensitivity={"equity_market_beta": {"value": 1.5, "source": "approved_vendor"}})
        ]
    }
    r = stress_portfolio(port, get_scenario("broad_equity_minus_10").to_dict())
    assert r["positions"][0]["tier"] == TIER_SENSITIVITY
    # 1.5 * -10% = -15%
    assert r["positions"][0]["pnl"] == pytest.approx(-15000.0)


def test_unsourced_beta_is_unmodeled_not_fabricated():
    port = {
        "positions": [
            _pos("AAPL", 100000, sensitivity={"equity_market_beta": {"value": 1.5}})
        ]
    }
    r = stress_portfolio(port, get_scenario("broad_equity_minus_10").to_dict())
    assert r["positions"][0]["tier"] == TIER_UNAVAILABLE
    assert r["positions"][0]["pnl"] is None
    assert r["unmodeled_value"] == pytest.approx(100000.0)


def test_no_sensitivity_means_unmodeled():
    port = {"positions": [_pos("AAPL", 100000)]}
    r = stress_portfolio(port, get_scenario("broad_equity_minus_10").to_dict())
    assert r["positions"][0]["tier"] == TIER_UNAVAILABLE
    assert r["coverage_pct"] == 0.0


def test_partial_coverage_and_invariants():
    port = {
        "positions": [
            _pos("CASH", 50000, cash_like=True),
            _pos("AAPL", 50000, sector="technology"),
            _pos("UNKNOWN", 100000),
        ]
    }
    sc = {"scenario_id": "x", "shocks": {"sector_shocks": {"technology": -0.10}}}
    r = stress_portfolio(port, sc)
    assert r["unmodeled_value"] == pytest.approx(100000.0)
    assert r["coverage_pct"] == pytest.approx(50.0)
    # sum of modeled PnL == modeled portfolio PnL
    modeled_sum = sum(p["pnl"] for p in r["positions"] if p["pnl"] is not None)
    assert r["estimated_pnl"] == pytest.approx(modeled_sum)
    assert r["estimated_pnl"] == pytest.approx(-5000.0)


def test_no_double_counting_sector_beats_beta():
    port = {
        "positions": [
            _pos(
                "AAPL",
                100000,
                sector="technology",
                sensitivity={"equity_market_beta": {"value": 1.5, "source": "approved_vendor"}},
            )
        ]
    }
    sc = {
        "scenario_id": "x",
        "shocks": {"sector_shocks": {"technology": -0.15}, "equity_market_pct": -10.0},
    }
    r = stress_portfolio(port, sc)
    assert r["positions"][0]["tier"] == TIER_SECTOR
    assert r["positions"][0]["pnl"] == pytest.approx(-15000.0)


def test_negative_position_short_supported():
    port = {"positions": [_pos("AAPL", -100000, sector="technology")]}
    sc = {"scenario_id": "x", "shocks": {"sector_shocks": {"technology": -0.10}}}
    r = stress_portfolio(port, sc)
    # short position gains when sector falls
    assert r["positions"][0]["pnl"] == pytest.approx(10000.0)


def test_duration_rates_sensitivity():
    port = {
        "positions": [
            _pos("BND", 100000, sensitivity={"duration": {"value": 6.0, "source": "duration_credit_characteristics"}})
        ]
    }
    r = stress_portfolio(port, get_scenario("rates_plus_100bp").to_dict())
    # -6.0 * 100bp/10000 = -6%
    assert r["positions"][0]["pnl"] == pytest.approx(-6000.0)


def test_provider_query_ok():
    p = PortfolioStressProvider()
    r = p.query(
        "risk.stress_portfolio",
        {"portfolio": {"positions": [_pos("CASH", 100, cash_like=True)]}, "scenario": "broad_equity_minus_10"},
    )
    assert r.status == "OK"
    assert r.data["estimated_pnl"] == 0.0


def test_provider_unknown_scenario_invalid():
    p = PortfolioStressProvider()
    r = p.query(
        "risk.stress_portfolio",
        {"portfolio": {"positions": [_pos("CASH", 100, cash_like=True)]}, "scenario": "does_not_exist"},
    )
    assert r.status == "INVALID_REQUEST"


def test_provider_requires_positions():
    p = PortfolioStressProvider()
    r = p.query("risk.stress_portfolio", {"portfolio": {"positions": []}, "scenario": "broad_equity_minus_10"})
    assert r.status == "INVALID_REQUEST"
