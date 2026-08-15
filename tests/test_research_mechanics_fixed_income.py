"""R2 fixed-income golden + convention tests.

Independent derivations are hand-computable closed forms (par, zero, 30/360 US).
"""
from __future__ import annotations

import math
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.research_governance.mechanics.common import (  # noqa: E402
    DayCount,
    MechanicError,
    MechanicStatus,
    Quantity,
    Unit,
    parse_day_count,
    year_fraction,
)
from scripts.lib.research_governance.mechanics.fixed_income import (  # noqa: E402
    analyze_bond,
    dirty_price_from_yield,
)


def test_day_count_act_360():
    # Independent: 31 calendar days / 360
    yf = year_fraction(date(2020, 1, 1), date(2020, 2, 1), DayCount.ACT_360)
    assert abs(yf - 31 / 360.0) < 1e-15


def test_day_count_act_365():
    yf = year_fraction(date(2019, 1, 1), date(2020, 1, 1), DayCount.ACT_365)
    assert abs(yf - 365 / 365.0) < 1e-15


def test_day_count_30_360_us():
    # 2020-01-15 to 2020-03-15: 30/360 US = 60 days
    yf = year_fraction(date(2020, 1, 15), date(2020, 3, 15), DayCount.THIRTY_360_US)
    assert abs(yf - 60 / 360.0) < 1e-15


def test_day_count_act_act_isda_leap():
    # 2020-01-01 to 2021-01-01 crosses leap year: 366/366 = 1
    yf = year_fraction(date(2020, 1, 1), date(2021, 1, 1), DayCount.ACT_ACT_ISDA)
    assert abs(yf - 1.0) < 1e-15


def test_ambiguous_30_360_rejected():
    try:
        parse_day_count("30/360")
        raise AssertionError("should have failed")
    except MechanicError as exc:
        assert exc.status == MechanicStatus.AMBIGUOUS_CONVENTION


def test_clean_plus_accrued_equals_dirty():
    # Independent: 6% SA, 30/360 US, 30 days after coupon → accrued = 0.50
    r = analyze_bond(
        instrument_id="cpn",
        settlement="2020-02-15",
        maturity="2022-01-15",
        coupon_rate=0.06,
        frequency="semiannual",
        day_count="30/360_US",
        yield_to_maturity=0.06,
    )
    assert r.status.value == "OK", r.reason
    acc = r.result["accrued_interest_per_100"]
    assert abs(acc - 0.50) < 1e-8
    assert abs(r.result["dirty_price_per_100"] - r.result["clean_price_per_100"] - acc) < 1e-10
    assert abs(r.result["identity_clean_plus_accrued"] - r.result["dirty_price_per_100"]) < 1e-10


def test_zero_coupon_pv_golden():
    # Independent: T=1 ACT/365 (2019-01-01→2020-01-01=365d), y=5% annual
    # P = 100 / 1.05
    r = analyze_bond(
        instrument_id="zero", settlement="2019-01-01", maturity="2020-01-01",
        coupon_rate=0.0, frequency="annual", day_count="ACT/365",
        yield_to_maturity=0.05,
    )
    assert r.status.value == "OK", r.reason
    assert abs(r.result["dirty_price_per_100"] - 100.0 / 1.05) < 1e-10
    assert r.result["accrued_interest_per_100"] == 0.0


def test_zero_coupon_ytm_golden():
    price = 100.0 / 1.05
    r = analyze_bond(
        instrument_id="zero", settlement="2019-01-01", maturity="2020-01-01",
        coupon_rate=0.0, frequency="annual", day_count="ACT/365",
        dirty_price=price,
    )
    assert r.status.value == "OK", r.reason
    assert abs(r.result["yield_to_maturity"] - 0.05) < 1e-9
    assert r.result["yield_solver"]["bracketed"] is True


def test_fixed_coupon_ytm_golden():
    # 30/360 US 2-year 6% annual at par → y=6%
    r = analyze_bond(
        instrument_id="par", settlement="2020-01-01", maturity="2022-01-01",
        coupon_rate=0.06, frequency="annual", day_count="30/360_US",
        dirty_price=100.0,
    )
    assert r.status.value == "OK", r.reason
    assert abs(r.result["yield_to_maturity"] - 0.06) < 1e-9


def test_invalid_frequency():
    r = analyze_bond(
        instrument_id="x", settlement="2020-01-01", maturity="2022-01-01",
        coupon_rate=0.05, frequency="biweekly", day_count="ACT/365",
        yield_to_maturity=0.05,
    )
    assert r.status.value == "INVALID_INPUT"


def test_missing_settlement():
    r = analyze_bond(
        instrument_id="x", settlement=None, maturity="2022-01-01",
        coupon_rate=0.05, frequency="annual", day_count="ACT/365",
        yield_to_maturity=0.05,
    )
    assert r.status.value == "UNAVAILABLE"


def test_missing_maturity():
    r = analyze_bond(
        instrument_id="x", settlement="2020-01-01", maturity=None,
        coupon_rate=0.05, frequency="annual", day_count="ACT/365",
        yield_to_maturity=0.05,
    )
    assert r.status.value == "INVALID_INPUT"


def test_settlement_after_maturity():
    r = analyze_bond(
        instrument_id="x", settlement="2023-01-01", maturity="2022-01-01",
        coupon_rate=0.05, frequency="annual", day_count="ACT/365",
        yield_to_maturity=0.05,
    )
    assert r.status.value == "INVALID_INPUT"


def test_negative_face():
    r = analyze_bond(
        instrument_id="x", settlement="2020-01-01", maturity="2022-01-01",
        coupon_rate=0.05, frequency="annual", day_count="ACT/365",
        yield_to_maturity=0.05, face=-1,
    )
    assert r.status.value == "INVALID_INPUT"


def test_incomplete_call_schedule_ytw_unavailable():
    r = analyze_bond(
        instrument_id="c", settlement="2020-01-01", maturity="2025-01-01",
        coupon_rate=0.05, frequency="annual", day_count="30/360_US",
        yield_to_maturity=0.05, callable=True, call_schedule=None,
    )
    assert r.result["ytw_status"] == "UNAVAILABLE"
    assert r.result["ytw_reason"] == "INCOMPLETE_CALL_SCHEDULE"
    assert r.result["yield_to_worst"] is None


def test_ytw_selects_minimum_path():
    r = analyze_bond(
        instrument_id="c", settlement="2020-01-01", maturity="2025-01-01",
        coupon_rate=0.08, frequency="annual", day_count="30/360_US",
        dirty_price=110.0, callable=True,
        call_schedule=[{"date": "2022-01-01", "price": 101.0}],
    )
    assert r.status.value == "OK", r.reason
    assert r.result["yield_to_call"]
    assert r.result["yield_to_worst"] <= r.result["yield_to_maturity"] + 1e-12


def test_macaulay_duration_golden():
    # Independent: 2-year 6% annual par, 30/360 US.
    # Mac = [1*6/1.06 + 2*106/1.06^2] / 100
    r = analyze_bond(
        instrument_id="par", settlement="2020-01-01", maturity="2022-01-01",
        coupon_rate=0.06, frequency="annual", day_count="30/360_US",
        yield_to_maturity=0.06,
    )
    assert r.status.value == "OK", r.reason
    expected = (1 * 6 / 1.06 + 2 * 106 / 1.06 ** 2) / 100.0
    assert abs(r.result["macaulay_duration_years"] - expected) < 1e-8


def test_modified_duration_identity():
    r = analyze_bond(
        instrument_id="par", settlement="2020-01-01", maturity="2022-01-01",
        coupon_rate=0.06, frequency="annual", day_count="30/360_US",
        yield_to_maturity=0.06,
    )
    mac = r.result["macaulay_duration_years"]
    mod = r.result["modified_duration"]
    assert abs(mod - mac / 1.06) < 1e-10


def test_dv01_finite_difference():
    r = analyze_bond(
        instrument_id="par", settlement="2020-01-01", maturity="2022-01-01",
        coupon_rate=0.06, frequency="annual", day_count="30/360_US",
        yield_to_maturity=0.06,
    )
    y = 0.06
    p0 = r.result["dirty_price_per_100"]
    from scripts.lib.research_governance.mechanics.common import CouponFrequency
    pup = dirty_price_from_yield(
        settlement=date(2020, 1, 1), maturity=date(2022, 1, 1),
        coupon_rate_dec=0.06, freq=CouponFrequency.ANNUAL,
        day_count=DayCount.THIRTY_360_US, yield_dec=y + 1e-4,
    )
    fd = p0 - pup  # price drop for +1bp
    assert abs(r.result["dv01_per_100_face"] - fd) / fd < 0.05


def test_convexity_finite_difference():
    from scripts.lib.research_governance.mechanics.common import CouponFrequency
    settle, mat = date(2020, 1, 1), date(2022, 1, 1)
    y = 0.06
    h = 1e-4
    p0 = dirty_price_from_yield(
        settlement=settle, maturity=mat, coupon_rate_dec=0.06,
        freq=CouponFrequency.ANNUAL, day_count=DayCount.THIRTY_360_US, yield_dec=y,
    )
    pup = dirty_price_from_yield(
        settlement=settle, maturity=mat, coupon_rate_dec=0.06,
        freq=CouponFrequency.ANNUAL, day_count=DayCount.THIRTY_360_US, yield_dec=y + h,
    )
    pdn = dirty_price_from_yield(
        settlement=settle, maturity=mat, coupon_rate_dec=0.06,
        freq=CouponFrequency.ANNUAL, day_count=DayCount.THIRTY_360_US, yield_dec=y - h,
    )
    fd_conv = (pup + pdn - 2 * p0) / (p0 * h * h)
    r = analyze_bond(
        instrument_id="par", settlement="2020-01-01", maturity="2022-01-01",
        coupon_rate=0.06, frequency="annual", day_count="30/360_US",
        yield_to_maturity=0.06,
    )
    # Same order of magnitude / relative close (formula vs FD)
    assert abs(r.result["convexity"] - fd_conv) / abs(fd_conv) < 0.15


def test_price_falls_when_yield_rises():
    r = analyze_bond(
        instrument_id="par", settlement="2020-01-01", maturity="2022-01-01",
        coupon_rate=0.06, frequency="annual", day_count="30/360_US",
        yield_to_maturity=0.06,
    )
    assert r.result["price_falls_when_yield_rises"] is True


def test_percent_coupon_unit():
    r = analyze_bond(
        instrument_id="par", settlement="2020-01-01", maturity="2022-01-01",
        coupon_rate=Quantity(6.0, Unit.PERCENT), frequency="annual",
        day_count="30/360_US", yield_to_maturity=0.06,
    )
    assert r.status.value == "OK", r.reason
    assert abs(r.result["dirty_price_per_100"] - 100.0) < 1e-8


def test_authority_label():
    r = analyze_bond(
        instrument_id="z", settlement="2019-01-01", maturity="2020-01-01",
        coupon_rate=0.0, frequency="annual", day_count="ACT/365",
        yield_to_maturity=0.05,
    )
    assert r.authority == "READ_ONLY_ADVISORY"
    assert r.result["authority"] == "READ_ONLY_ADVISORY"
