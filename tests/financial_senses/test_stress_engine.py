"""Deterministic portfolio stress engine tests (shock-unit contract)."""
from __future__ import annotations

import pytest

from financial_senses.stress_engine import (
    InvalidShock,
    TIER_CASH,
    TIER_SENSITIVITY,
    TIER_SECTOR,
    TIER_UNAVAILABLE,
    PortfolioStressProvider,
    get_scenario,
    normalize_bps,
    normalize_return,
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
    assert r["cash_buffer_effect"] is None


def test_sector_shock_applies_directly():
    port = {"positions": [_pos("AAPL", 100000, sector="technology")]}
    sc = get_scenario("broad_equity_minus_10").to_dict()
    sc["shocks"] = {"sector_shocks": {"technology": -0.15}}
    r = stress_portfolio(port, sc)
    assert r["positions"][0]["tier"] == TIER_SECTOR
    assert r["positions"][0]["pnl"] == pytest.approx(-15000.0)
    assert r["estimated_pnl"] == pytest.approx(-15000.0)


def test_sector_20_percent_is_not_minus_2000_pct():
    # -20 PERCENT must model -20%, never -2000%.
    port = {"positions": [_pos("AAPL", 100000, sector="technology")]}
    sc = {"scenario_id": "x", "shocks": {"sector_shocks": {"technology": {"value": -20, "unit": "PERCENT"}}}}
    r = stress_portfolio(port, sc)
    assert r["positions"][0]["return"] == pytest.approx(-0.20)
    assert r["positions"][0]["pnl"] == pytest.approx(-20000.0)


def test_sourced_beta_sensitivity_used():
    port = {
        "positions": [
            _pos("AAPL", 100000, sensitivity={"equity_market_beta": {"value": 1.5, "source": "approved_vendor"}})
        ]
    }
    r = stress_portfolio(port, get_scenario("broad_equity_minus_10").to_dict())
    assert r["positions"][0]["tier"] == TIER_SENSITIVITY
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
    modeled_sum = sum(p["pnl"] for p in r["positions"] if p["pnl"] is not None)
    assert r["estimated_pnl"] == pytest.approx(modeled_sum)
    assert r["estimated_pnl"] == pytest.approx(-5000.0)
    assert r["gross_exposure"] == pytest.approx(200000.0)
    assert r["net_exposure"] == pytest.approx(200000.0)
    assert r["modeled_value"] == pytest.approx(100000.0)


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
        "shocks": {"sector_shocks": {"technology": -0.15}, "equity_market_pct": -0.10},
    }
    r = stress_portfolio(port, sc)
    assert r["positions"][0]["tier"] == TIER_SECTOR
    assert r["positions"][0]["pnl"] == pytest.approx(-15000.0)


def test_negative_position_short_supported():
    port = {"positions": [_pos("AAPL", -100000, sector="technology")]}
    sc = {"scenario_id": "x", "shocks": {"sector_shocks": {"technology": -0.10}}}
    r = stress_portfolio(port, sc)
    assert r["positions"][0]["pnl"] == pytest.approx(10000.0)


def test_short_exposure_estimated_pct_unavailable_without_nav():
    port = {"positions": [_pos("AAPL", -100000, sector="technology")]}
    sc = {"scenario_id": "x", "shocks": {"sector_shocks": {"technology": -0.10}}}
    r = stress_portfolio(port, sc)
    assert r["portfolio_nav"] is None
    assert r["estimated_pct"] is None


def test_short_exposure_estimated_pct_with_explicit_nav():
    port = {"portfolio_nav": 50000, "positions": [_pos("AAPL", -100000, sector="technology")]}
    sc = {"scenario_id": "x", "shocks": {"sector_shocks": {"technology": -0.10}}}
    r = stress_portfolio(port, sc)
    assert r["portfolio_nav"] == 50000.0
    assert r["estimated_pct"] == pytest.approx(10000.0 / 50000.0 * 100.0)


def test_duration_rates_sensitivity():
    port = {
        "positions": [
            _pos("BND", 100000, sensitivity={"duration": {"value": 6.0, "source": "duration_credit_characteristics"}})
        ]
    }
    r = stress_portfolio(port, get_scenario("rates_plus_100bp").to_dict())
    assert r["positions"][0]["pnl"] == pytest.approx(-6000.0)


def test_factor_shock_decimal_return():
    port = {
        "positions": [
            _pos("ETF", 100000, factors={"value": {"loading": 2.0, "source": "approved_vendor"}})
        ]
    }
    sc = {"scenario_id": "x", "shocks": {"factor_shocks": {"value": -0.10}}}
    r = stress_portfolio(port, sc)
    assert r["positions"][0]["pnl"] == pytest.approx(-20000.0)


def test_normalize_return_units_consistent():
    assert normalize_return({"value": -20, "unit": "PERCENT"}) == pytest.approx(-0.20)
    assert normalize_return({"value": -0.20, "unit": "DECIMAL_RETURN"}) == pytest.approx(-0.20)
    assert normalize_return(-0.20) == pytest.approx(-0.20)


def test_normalize_bps_units():
    assert normalize_bps(100) == 100.0
    assert normalize_bps({"value": 1.0, "unit": "PERCENT"}) == pytest.approx(100.0)
    assert normalize_bps({"value": 0.01, "unit": "DECIMAL_RETURN"}) == pytest.approx(100.0)


def test_invalid_unit_raises():
    with pytest.raises(InvalidShock):
        normalize_return({"value": -20, "unit": "FOO"})


def test_plain_minus_20_out_of_range_raises():
    with pytest.raises(InvalidShock):
        normalize_return(-20.0)


def test_provider_query_ok():
    p = PortfolioStressProvider()
    r = p.query(
        "risk.stress_portfolio",
        {"portfolio": {"positions": [_pos("CASH", 100, cash_like=True)]}, "scenario": "broad_equity_minus_10"},
    )
    assert r.status == "OK"
    assert r.data["estimated_pnl"] == 0.0


def test_provider_invalid_unit_invalid_request():
    p = PortfolioStressProvider()
    r = p.query(
        "risk.stress_portfolio",
        {
            "portfolio": {"positions": [_pos("AAPL", 100000, sector="technology")]},
            "scenario": {"scenario_id": "x", "shocks": {"sector_shocks": {"technology": {"value": -20, "unit": "FOO"}}}},
        },
    )
    assert r.status == "INVALID_REQUEST"


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


def test_unmodeled_short_completeness_partial():
    # An unmodeled short: signed unmodeled net is negative, gross is positive.
    p = PortfolioStressProvider()
    r = p.query(
        "risk.stress_portfolio",
        {"portfolio": {"positions": [_pos("AAPL", -100000)]},
         "scenario": {"scenario_id": "x", "shocks": {"sector_shocks": {"technology": -0.10}}}},
    )
    assert r.data["unmodeled_gross_exposure"] == pytest.approx(100000.0)
    assert r.data["unmodeled_net_exposure"] == pytest.approx(-100000.0)
    assert r.data["coverage_pct"] == pytest.approx(0.0)
    assert r.quality.completeness == "PARTIAL"


def test_offsetting_unmodeled_long_short_completeness_partial():
    # +100k long and -100k short, both unmodeled: signed net is 0, gross is 200k.
    port = {"positions": [_pos("LONG", 100000), _pos("SHORT", -100000)]}
    sc = {"scenario_id": "x", "shocks": {"sector_shocks": {"technology": -0.10}}}
    res = stress_portfolio(port, sc)
    assert res["unmodeled_net_exposure"] == pytest.approx(0.0)
    assert res["unmodeled_gross_exposure"] == pytest.approx(200000.0)
    assert res["coverage_pct"] == pytest.approx(0.0)

    p = PortfolioStressProvider()
    r = p.query("risk.stress_portfolio", {"portfolio": port, "scenario": sc})
    assert r.quality.completeness == "PARTIAL"


def test_fully_modeled_long_short_completeness_complete():
    port = {
        "positions": [
            _pos("LONG", 100000, sector="technology"),
            _pos("SHORT", -100000, sector="technology"),
        ]
    }
    sc = {"scenario_id": "x", "shocks": {"sector_shocks": {"technology": -0.10}}}
    p = PortfolioStressProvider()
    r = p.query("risk.stress_portfolio", {"portfolio": port, "scenario": sc})
    assert r.data["unmodeled_gross_exposure"] == 0.0
    assert r.data["coverage_pct"] == pytest.approx(100.0)
    assert r.quality.completeness == "COMPLETE"


def test_exposure_fields_separate():
    port = {
        "positions": [
            _pos("CASH", 50000, cash_like=True),
            _pos("AAPL", 50000, sector="technology"),
            _pos("UNKNOWN", 100000),
        ]
    }
    sc = {"scenario_id": "x", "shocks": {"sector_shocks": {"technology": -0.10}}}
    r = stress_portfolio(port, sc)
    assert r["modeled_net_exposure"] == pytest.approx(100000.0)
    assert r["modeled_gross_exposure"] == pytest.approx(100000.0)
    assert r["unmodeled_net_exposure"] == pytest.approx(100000.0)
    assert r["unmodeled_gross_exposure"] == pytest.approx(100000.0)
    assert r["net_exposure"] == pytest.approx(200000.0)
    assert r["gross_exposure"] == pytest.approx(200000.0)


def test_stress_estimate_is_model_estimate_not_fact():
    p = PortfolioStressProvider()
    r = p.query(
        "risk.stress_portfolio",
        {"portfolio": {"positions": [_pos("AAPL", 100000, sector="technology")]},
         "scenario": {"scenario_id": "x", "shocks": {"sector_shocks": {"technology": -0.10}}}},
    )
    assert len(r.estimates) == 1
    assert r.estimates[0].key == "stress_estimated_pnl"
    assert r.estimates[0].source_type == "MODEL_INFERENCE"
    assert all(f.source_type != "MODEL_INFERENCE" for f in r.facts)
    assert r.validate() == []
