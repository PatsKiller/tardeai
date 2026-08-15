"""R2 ETF mechanics goldens and guards."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.research_governance.mechanics.etf import (  # noqa: E402
    creation_unit_notional,
    position_values,
    premium_discount,
    spread_bps,
    tracking_difference,
    tracking_error,
)

TS = "2026-01-15T21:00:00+00:00"


def test_premium_discount_golden():
    r = premium_discount(
        instrument_id="SPY", market_price=102.0, market_price_as_of=TS,
        market_currency="USD", nav=100.0, nav_as_of=TS, nav_currency="USD",
        nav_kind="OFFICIAL_NAV",
    )
    assert r.status.value == "OK", r.reason
    assert abs(r.result["premium_discount_decimal"] - 0.02) < 1e-12
    assert abs(r.result["premium_discount_pct"] - 2.0) < 1e-10


def test_stale_nav_price():
    r = premium_discount(
        instrument_id="SPY", market_price=100.0,
        market_price_as_of="2026-01-16T21:00:00+00:00",
        market_currency="USD", nav=100.0, nav_as_of="2026-01-01T21:00:00+00:00",
        nav_currency="USD", nav_kind="OFFICIAL_NAV",
    )
    assert r.status.value == "STALE_INPUT"


def test_currency_mismatch_without_fx():
    r = premium_discount(
        instrument_id="EU", market_price=100.0, market_price_as_of=TS,
        market_currency="USD", nav=100.0, nav_as_of=TS, nav_currency="EUR",
        nav_kind="OFFICIAL_NAV",
    )
    assert r.status.value == "UNAVAILABLE"


def test_proxy_cannot_be_official():
    r = premium_discount(
        instrument_id="SPY", market_price=100.0, market_price_as_of=TS,
        market_currency="USD", nav=100.0, nav_as_of=TS, nav_currency="USD",
        nav_kind="PROXY",
    )
    assert r.status.value == "INVALID_INPUT"
    assert "PROXY" in r.reason


def test_indicative_cannot_masquerade():
    r = premium_discount(
        instrument_id="SPY", market_price=100.0, market_price_as_of=TS,
        market_currency="USD", nav=100.0, nav_as_of=TS, nav_currency="USD",
        nav_kind="INDICATIVE_NAV", requested_nav_role="OFFICIAL_NAV",
    )
    assert r.status.value == "INVALID_INPUT"


def test_spread_bps_golden():
    r = spread_bps(instrument_id="SPY", bid=100.0, ask=100.20)
    assert r.status.value == "OK"
    # mid=100.10, spread=0.20, bps = 0.20/100.10*10000
    expected = 0.20 / 100.10 * 10_000
    assert abs(r.result["spread_bps"] - expected) < 1e-10


def test_ask_lt_bid():
    assert spread_bps(instrument_id="X", bid=101, ask=100).status.value == "INVALID_INPUT"


def test_zero_bid():
    assert spread_bps(instrument_id="X", bid=0, ask=1).status.value == "INVALID_INPUT"


def test_tracking_difference_golden():
    r = tracking_difference(
        instrument_id="SPY", fund_return=0.10, benchmark_return=0.09,
        return_basis="nav_total_return",
    )
    assert r.status.value == "OK"
    assert abs(r.result["tracking_difference_decimal"] - 0.01) < 1e-15


def test_tracking_error_golden():
    series = [0.01, -0.01]
    r = tracking_error(
        instrument_id="SPY", tracking_differences=series, return_frequency="annual",
        stdev="sample",
    )
    assert r.status.value == "OK"
    # sample stdev of [0.01,-0.01] = sqrt(2*0.01^2 / 1) = 0.014142...
    import statistics
    expected = statistics.stdev(series) * 1.0
    assert abs(r.result["tracking_error_annualized"] - expected) < 1e-12


def test_tracking_error_single_obs():
    r = tracking_error(instrument_id="SPY", tracking_differences=[0.01], return_frequency="monthly")
    assert r.status.value == "UNAVAILABLE"


def test_tracking_error_missing_frequency():
    r = tracking_error(instrument_id="SPY", tracking_differences=[0.01, 0.02], return_frequency=None)
    assert r.status.value == "AMBIGUOUS_CONVENTION"


def test_creation_unit_missing_shares():
    r = creation_unit_notional(instrument_id="SPY", creation_unit_shares=None, basis_price=100, basis="nav")
    assert r.status.value == "UNAVAILABLE"


def test_creation_unit_notional():
    r = creation_unit_notional(
        instrument_id="SPY", creation_unit_shares=50_000, basis_price=400.0, basis="nav",
    )
    assert r.status.value == "OK"
    assert r.result["creation_notional"] == 20_000_000.0
    assert r.result["basis"] == "nav"


def test_position_values():
    r = position_values(instrument_id="SPY", shares=10, nav=400, market_price=402)
    assert r.status.value == "OK"
    assert r.result["nav_based_position_value"] == 4000
    assert r.result["market_price_position_value"] == 4020
