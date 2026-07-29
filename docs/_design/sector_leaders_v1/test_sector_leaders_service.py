"""
test_sector_leaders_service.py  -  REFERENCE TESTS v1

Covers the pure computation layer only. No DB, no network, no fixtures beyond
literals. These tests must pass unchanged after adaptation - if adapting the
service requires changing an assertion here, the adaptation changed a design
decision and needs sign-off, not a test edit.

Run:  pytest -q test_sector_leaders_service.py
"""

import pytest

from sector_leaders_service import (
    relative_strength_vs_industry,
    compute_dispersion,
    exposure_gap_pp,
    account_eligibility,
)


# ---------------------------------------------------------------- RS vs industry

def test_rs_vs_industry_isolates_name_selection_from_sector_beta():
    # Name +14%, its industry +8% -> the name contributed +6 of its own.
    assert relative_strength_vs_industry(14.0, 8.0) == 6.0


def test_rs_vs_industry_goes_negative_for_a_passenger_in_a_leading_group():
    # This is the OXY case: strong sector, weak name. Must be catchable.
    assert relative_strength_vs_industry(3.0, 8.0) == -5.0


@pytest.mark.parametrize("a,b", [(None, 8.0), (14.0, None), (None, None)])
def test_rs_vs_industry_returns_none_never_zero_when_unsourced(a, b):
    # Returning 0.0 here would render as a confident "flat" reading.
    assert relative_strength_vs_industry(a, b) is None


# -------------------------------------------------------------------- dispersion

def test_dispersion_requires_at_least_eight_priced_names():
    d = compute_dispersion([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0], 2.0)
    assert d["spread_pp"] is None
    assert d["top_quartile_excess_pp"] is None
    assert d["n"] == 7


def test_dispersion_measures_spread_and_top_quartile_excess():
    returns = [-4.0, -1.0, 0.0, 2.0, 3.0, 5.0, 8.0, 11.0, 14.0, 19.0]
    d = compute_dispersion(returns, etf_return_pct=4.0)
    assert d["n"] == 10
    assert d["spread_pp"] is not None and d["spread_pp"] > 0
    # Top quartile clearly beats the ETF here.
    assert d["top_quartile_excess_pp"] > 0


def test_dispersion_ignores_nulls_rather_than_treating_them_as_zero():
    with_nulls = [1.0, None, 2.0, None, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]
    d = compute_dispersion(with_nulls, 3.0)
    assert d["n"] == 8


def test_dispersion_excess_is_none_when_etf_return_unsourced():
    returns = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0]
    d = compute_dispersion(returns, etf_return_pct=None)
    assert d["spread_pp"] is not None
    assert d["top_quartile_excess_pp"] is None


# ------------------------------------------------------------------ exposure gap

def test_exposure_gap_flags_underweight_the_leading_sector():
    # The live 2026-07-29 case: Energy ranked #1, held at 3.9%.
    gap = exposure_gap_pp(3.9, (9.0, 12.0))
    assert gap["state"] == "underweight"
    assert gap["pp"] == pytest.approx(-5.1)


def test_exposure_gap_flags_overweight():
    gap = exposure_gap_pp(25.2, (10.0, 15.0))
    assert gap["state"] == "overweight"
    assert gap["pp"] == pytest.approx(10.2)


def test_exposure_gap_in_band_is_zero_not_none():
    gap = exposure_gap_pp(10.5, (9.0, 12.0))
    assert gap["state"] == "in band"
    assert gap["pp"] == 0.0


def test_exposure_gap_is_none_without_a_sizing_policy():
    # No invented band. The UI must render "unknown", not a fabricated gap.
    assert exposure_gap_pp(3.9, None) is None


def test_exposure_gap_is_none_without_a_book_weight():
    assert exposure_gap_pp(None, (9.0, 12.0)) is None


# ------------------------------------------------------------ account eligibility

TAXABLE = {"label": "Taxable", "can_short": True, "read_only": False}
ROLLOVER = {"label": "Rollover IRA", "can_short": False, "read_only": False}
ROTH = {"label": "Roth IRA", "can_short": False, "read_only": False}
ALPACA_LIVE = {"label": "Alpaca Live", "can_short": True, "read_only": True}

ALL_ACCOUNTS = [TAXABLE, ROLLOVER, ROTH, ALPACA_LIVE]


def test_long_trade_blocks_only_read_only_accounts():
    blocked, reason = account_eligibility({}, "long", ALL_ACCOUNTS)
    assert blocked == ["Alpaca Live"]
    assert "read-only" in reason


def test_short_trade_blocks_both_iras():
    blocked, _ = account_eligibility({}, "short", ALL_ACCOUNTS)
    assert "Rollover IRA" in blocked
    assert "Roth IRA" in blocked
    assert "Taxable" not in blocked


def test_short_trade_never_permits_a_read_only_account():
    blocked, _ = account_eligibility({}, "short", [ALPACA_LIVE])
    assert blocked == ["Alpaca Live"]


def test_long_trade_permits_iras():
    blocked, _ = account_eligibility({}, "long", [ROLLOVER, ROTH])
    assert blocked == []


# ============================================================================
# SL-S2 additions (2026-07-29). Everything above this line is the original
# reference contract and is UNCHANGED, byte for byte.
#
# Note on the dispersion correction: the four dispersion tests above still hold
# and were deliberately NOT rewritten. compute_dispersion() always took "a pool
# of returns plus an ETF return" and always measured spread within whatever pool
# it was given — the function was correct. The defect was the CALL SITE passing
# a sector-wide pool. So the level contract needed new tests, not edits to
# passing ones.
# ============================================================================

from sector_leaders_service import (           # noqa: E402
    dispersion_verdict,
    DISPERSION_MIN_NAMES,
    DISPERSION_NAMES_SPREAD_PP,
    DISPERSION_NAMES_EXCESS_PP,
    DISPERSION_ETF_SPREAD_PP,
    HORIZONS,
    CONFIRMING_STATES,
    _sector_aliases,
)


# ------------------------------------------------------ dispersion LEVEL contract

def test_dispersion_thresholds_unchanged_by_the_level_correction():
    # The 2026-07-29 correction moved the level, not the cut points. Changing
    # both at once would leave neither testable against outcome data.
    assert (DISPERSION_NAMES_SPREAD_PP, DISPERSION_NAMES_EXCESS_PP,
            DISPERSION_ETF_SPREAD_PP) == (12.0, 4.0, 6.0)
    assert DISPERSION_MIN_NAMES == 8


def test_excess_is_measured_against_the_etf_not_the_group_mean():
    # Measuring excess against the pool's own mean is near-tautological: the top
    # quartile always beats it. Against the ETF the number can be negative, and
    # that is the whole point.
    returns = [-9.0, -8.0, -7.0, -6.0, -5.0, -4.0, -3.0, -2.0, -1.0, 0.0]
    d = compute_dispersion(returns, etf_return_pct=5.0)
    assert d["top_quartile_excess_pp"] < 0


def test_wide_spread_alone_does_not_buy_names_without_etf_excess():
    # The inter-industry pooling bug produced exactly this shape: spread huge,
    # excess irrelevant. Both halves must be load-bearing.
    wide_but_trailing = {"spread_pp": 40.0, "top_quartile_excess_pp": 1.0, "n": 30}
    assert dispersion_verdict(wide_but_trailing) == "mixed"


def test_verdict_requires_both_spread_and_excess_to_buy_names():
    assert dispersion_verdict(
        {"spread_pp": 20.0, "top_quartile_excess_pp": 8.0, "n": 20}) == "buy names"


def test_tight_group_buys_the_etf():
    assert dispersion_verdict(
        {"spread_pp": 4.0, "top_quartile_excess_pp": 9.0, "n": 20}) == "buy the ETF"


def test_verdict_omitted_when_the_industry_is_too_thin():
    # Below the floor the verdict is OMITTED, never pooled upward to rescue it.
    thin = compute_dispersion([1.0] * (DISPERSION_MIN_NAMES - 1), 0.0)
    assert thin["spread_pp"] is None
    assert dispersion_verdict(thin) is None


def test_verdict_is_none_when_excess_unsourced_even_with_wide_spread():
    d = compute_dispersion([float(i) for i in range(10)], etf_return_pct=None)
    assert d["spread_pp"] is not None
    assert d["top_quartile_excess_pp"] is None
    assert dispersion_verdict(d) in (None, "mixed", "buy the ETF")
    assert dispersion_verdict(d) != "buy names"


# ------------------------------------------------------------- horizon contract

def test_both_sides_of_rs_use_the_same_finviz_window():
    # rs_vs_industry subtracts an industry composite from a name return. If the
    # two ever index different windows the metric is silently meaningless.
    for h, spec in HORIZONS.items():
        assert spec["industry_col"].replace("perf_", "") == \
               spec["name_key"].replace("perf_", "").replace("_pct", ""), h
