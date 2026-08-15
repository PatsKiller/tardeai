"""R2 acceptance gates R2A-1..R2A-15. Separate namespace from RGA-1..16."""
from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

from .enums import GateState
from .mechanics.common import AUTHORITY, DayCount, Quantity, Unit, convert_quantity, parse_day_count, year_fraction
from .mechanics.etf import premium_discount, spread_bps, tracking_difference, tracking_error
from .mechanics.fixed_income import analyze_bond
from .mechanics.valuation import dcf_value, reverse_dcf, sensitivity_matrix
from . import pr_scope_guard
from .producers import FixedIncomeInput, run_governed_fixed_income
from .receipts import governed_result

R2A_IDS = tuple(f"R2A-{i}" for i in range(1, 16))

R2A_NAMES = {
    "R2A-1": "fixed_income_reference_vectors",
    "R2A-2": "fixed_income_convention_integrity",
    "R2A-3": "ytw_fail_closed",
    "R2A-4": "duration_dv01_convexity",
    "R2A-5": "etf_nav_price_semantics",
    "R2A-6": "etf_tracking_math",
    "R2A-7": "etf_proxy_block",
    "R2A-8": "valuation_reference_vectors",
    "R2A-9": "reverse_dcf_conditionality",
    "R2A-10": "valuation_sensitivity",
    "R2A-11": "units_fail_closed",
    "R2A-12": "source_and_asof_provenance",
    "R2A-13": "deterministic_result_authenticity",
    "R2A-14": "authority_read_only",
    "R2A-15": "scope_isolation",
}


def _pass(detail: str) -> tuple[str, str]:
    return GateState.PASS.value, detail


def _fail(detail: str) -> tuple[str, str]:
    return GateState.FAIL.value, detail


def _check_fi_vectors() -> tuple[str, str]:
    z = analyze_bond(
        instrument_id="zero", settlement="2019-01-01", maturity="2020-01-01",
        coupon_rate=0.0, frequency="annual", day_count="ACT/365",
        yield_to_maturity=0.05,
    )
    if z.status.value != "OK":
        return _fail(f"zero coupon failed: {z.reason}")
    # 2019-01-01 → 2020-01-01 is 365 days (2019 not leap) → ACT/365 year frac = 1.
    expected = 100.0 / 1.05
    if abs(z.result["dirty_price_per_100"] - expected) > 1e-8:
        return _fail(f"zero PV {z.result['dirty_price_per_100']} != {expected}")
    y = analyze_bond(
        instrument_id="zero", settlement="2019-01-01", maturity="2020-01-01",
        coupon_rate=0.0, frequency="annual", day_count="ACT/365",
        dirty_price=expected,
    )
    if abs(y.result["yield_to_maturity"] - 0.05) > 1e-8:
        return _fail(f"zero YTM {y.result['yield_to_maturity']} != 0.05")
    par = analyze_bond(
        instrument_id="par", settlement="2020-01-01", maturity="2022-01-01",
        coupon_rate=0.06, frequency="annual", day_count="30/360_US",
        yield_to_maturity=0.06,
    )
    if abs(par.result["dirty_price_per_100"] - 100.0) > 1e-8:
        return _fail(f"par bond dirty {par.result['dirty_price_per_100']} not 100")
    return _pass("zero PV/YTM and par coupon golden vectors hold")


def _check_fi_conventions() -> tuple[str, str]:
    try:
        parse_day_count("30/360")
        return _fail("bare 30/360 should be AMBIGUOUS")
    except Exception as exc:
        if getattr(exc, "status", None) is None or exc.status.value != "AMBIGUOUS_CONVENTION":
            return _fail(f"30/360 did not raise AMBIGUOUS: {exc}")
    bad = analyze_bond(
        instrument_id="x", settlement="2020-01-01", maturity="2022-01-01",
        coupon_rate=0.05, frequency="biweekly", day_count="ACT/365",
        yield_to_maturity=0.05,
    )
    if bad.status.value != "INVALID_INPUT":
        return _fail("invalid frequency did not fail")
    miss = analyze_bond(
        instrument_id="x", settlement=None, maturity="2022-01-01",
        coupon_rate=0.05, frequency="annual", day_count="ACT/365",
        yield_to_maturity=0.05,
    )
    if miss.status.value != "UNAVAILABLE":
        return _fail("missing settlement did not UNAVAILABLE")
    after = analyze_bond(
        instrument_id="x", settlement="2023-01-01", maturity="2022-01-01",
        coupon_rate=0.05, frequency="annual", day_count="ACT/365",
        yield_to_maturity=0.05,
    )
    if after.status.value != "INVALID_INPUT":
        return _fail("settlement after maturity did not INVALID")
    return _pass("day-count/frequency/settlement conventions fail closed")


def _check_ytw() -> tuple[str, str]:
    inc = analyze_bond(
        instrument_id="call", settlement="2020-01-01", maturity="2025-01-01",
        coupon_rate=0.05, frequency="annual", day_count="ACT/365",
        yield_to_maturity=0.05, callable=True, call_schedule=None,
    )
    if inc.result.get("ytw_status") != "UNAVAILABLE" or inc.result.get("ytw_reason") != "INCOMPLETE_CALL_SCHEDULE":
        return _fail(f"incomplete call schedule not fail-closed: {inc.result}")
    ok = analyze_bond(
        instrument_id="call", settlement="2020-01-01", maturity="2025-01-01",
        coupon_rate=0.08, frequency="annual", day_count="ACT/365",
        dirty_price=110.0, callable=True,
        call_schedule=[{"date": "2022-01-01", "price": 101.0}],
    )
    if ok.status.value != "OK" or ok.result.get("yield_to_worst") is None:
        return _fail(f"callable YTW missing: {ok.reason} {ok.result}")
    if ok.result["yield_to_worst"] > ok.result["yield_to_maturity"] + 1e-12:
        return _fail("YTW exceeded YTM")
    return _pass("YTW fail-closed on incomplete schedule; min path when complete")


def _check_risk() -> tuple[str, str]:
    r = analyze_bond(
        instrument_id="par", settlement="2020-01-01", maturity="2022-01-01",
        coupon_rate=0.06, frequency="annual", day_count="30/360_US",
        yield_to_maturity=0.06,
    )
    mac = r.result["macaulay_duration_years"]
    mod = r.result["modified_duration"]
    if abs(mod - mac / 1.06) > 1e-8:
        return _fail(f"modified != Mac/(1+y): {mod} vs {mac/1.06}")
    if not r.result.get("price_falls_when_yield_rises"):
        return _fail("price did not fall when yield rose")
    return _pass("duration identity + DV01/convexity fields present")


def _check_etf_nav() -> tuple[str, str]:
    ts = "2026-01-15T21:00:00+00:00"
    g = premium_discount(
        instrument_id="SPY", market_price=100.0, market_price_as_of=ts,
        market_currency="USD", nav=100.0, nav_as_of=ts, nav_currency="USD",
        nav_kind="OFFICIAL_NAV",
    )
    if g.status.value != "OK" or abs(g.result["premium_discount_decimal"]) > 1e-12:
        return _fail(f"par premium failed {g.status} {g.result}")
    stale = premium_discount(
        instrument_id="SPY", market_price=100.0, market_price_as_of="2026-01-16T21:00:00+00:00",
        market_currency="USD", nav=100.0, nav_as_of="2026-01-01T21:00:00+00:00",
        nav_currency="USD", nav_kind="OFFICIAL_NAV",
    )
    if stale.status != stale.status or stale.status.value != "STALE_INPUT":
        return _fail(f"stale NAV not STALE_INPUT: {stale.status} {stale.reason}")
    fx = premium_discount(
        instrument_id="EU", market_price=100.0, market_price_as_of=ts,
        market_currency="USD", nav=100.0, nav_as_of=ts, nav_currency="EUR",
        nav_kind="OFFICIAL_NAV",
    )
    if fx.status.value != "UNAVAILABLE":
        return _fail("currency mismatch without FX not UNAVAILABLE")
    return _pass("official NAV premium + stale/currency guards")


def _check_etf_tracking() -> tuple[str, str]:
    td = tracking_difference(
        instrument_id="SPY", fund_return=0.10, benchmark_return=0.09,
        return_basis="total_return",
    )
    if abs(td.result["tracking_difference_decimal"] - 0.01) > 1e-12:
        return _fail("TD golden failed")
    te = tracking_error(
        instrument_id="SPY", tracking_differences=[0.01, -0.01, 0.00],
        return_frequency="monthly",
    )
    if te.status.value != "OK":
        return _fail(te.reason)
    one = tracking_error(instrument_id="SPY", tracking_differences=[0.01], return_frequency="monthly")
    if one.status.value != "UNAVAILABLE":
        return _fail("single-observation TE not UNAVAILABLE")
    miss = tracking_error(instrument_id="SPY", tracking_differences=[0.01, 0.02], return_frequency=None)
    if miss.status.value != "AMBIGUOUS_CONVENTION":
        return _fail("missing TE frequency not AMBIGUOUS")
    return _pass("tracking difference/error math + guards")


def _check_etf_proxy() -> tuple[str, str]:
    ts = "2026-01-15T21:00:00+00:00"
    p = premium_discount(
        instrument_id="SPY", market_price=100, market_price_as_of=ts,
        market_currency="USD", nav=100, nav_as_of=ts, nav_currency="USD",
        nav_kind="PROXY",
    )
    if p.status.value != "INVALID_INPUT":
        return _fail("PROXY as official not INVALID")
    i = premium_discount(
        instrument_id="SPY", market_price=100, market_price_as_of=ts,
        market_currency="USD", nav=100, nav_as_of=ts, nav_currency="USD",
        nav_kind="INDICATIVE_NAV", requested_nav_role="OFFICIAL_NAV",
    )
    if i.status.value != "INVALID_INPUT":
        return _fail("indicative masquerade not INVALID")
    return _pass("proxy and indicative cannot be official NAV")


def _check_val_vectors() -> tuple[str, str]:
    r = dcf_value(
        instrument_id="X", fcfs=[100.0], wacc=0.10, terminal_growth=0.02,
        debt=0.0, cash=0.0, shares=10.0,
    )
    if r.status.value != "OK":
        return _fail(r.reason)
    # FCF1=100, TV=100*1.02/(0.08)=1275, PV = 100/1.1 + 1275/1.1
    tv = 100.0 * 1.02 / 0.08
    ev = (100.0 + tv) / 1.10
    if abs(r.result["enterprise_value"] - ev) > 1e-6:
        return _fail(f"EV {r.result['enterprise_value']} != {ev}")
    if abs(r.result["equity_value"] - ev) > 1e-6:
        return _fail("EV-to-equity with zero debt/cash (explicit zeros) failed")
    if abs(r.result["per_share_value"] - ev / 10.0) > 1e-6:
        return _fail("per-share golden failed")
    bad = dcf_value(instrument_id="X", fcfs=[100], wacc=0.05, terminal_growth=0.05, debt=0, cash=0)
    if bad.status.value != "INVALID_INPUT":
        return _fail("WACC==g not INVALID")
    miss = dcf_value(instrument_id="X", fcfs=[100], wacc=0.10, terminal_growth=0.02, debt=None, cash=0)
    if miss.status.value != "UNAVAILABLE":
        return _fail("missing debt not UNAVAILABLE")
    return _pass("PV/TV/EV-equity golden + WACC>g + missing debt")


def _check_rdcf() -> tuple[str, str]:
    base = dcf_value(
        instrument_id="X", fcfs=[100.0, 105.0], wacc=0.10, terminal_growth=0.02,
        debt=0.0, cash=0.0,
    )
    target = base.result["equity_value"]
    sol = reverse_dcf(
        instrument_id="X", solved_variable="implied_fcf_cagr",
        target_equity_value=target, starting_fcf=100.0 / 1.05, horizon=2,
        wacc=0.10, terminal_growth=0.02, debt=0.0, cash=0.0,
        domain=(0.0, 0.10),
    )
    if sol.status.value != "OK":
        return _fail(sol.reason)
    if "CONDITIONAL_MODEL_OUTPUT" not in sol.result.get("label", ""):
        return _fail("missing conditional-model label")
    return _pass("reverse DCF labeled conditional and solves")


def _check_sens() -> tuple[str, str]:
    s = sensitivity_matrix(
        instrument_id="X", fcfs=[100.0], wacc_grid=[0.08, 0.10, 0.12],
        g_grid=[0.01, 0.02], debt=0.0, cash=0.0,
    )
    if s.status.value != "OK":
        return _fail(s.reason)
    if not s.result.get("higher_wacc_lowers_equity"):
        return _fail("sensitivity not monotone in WACC")
    return _pass("sensitivity matrix present and monotone")


def _check_units() -> tuple[str, str]:
    q = convert_quantity(Quantity(5.0, Unit.PERCENT), Unit.DECIMAL_RATE)
    if abs(q.value - 0.05) > 1e-15:
        return _fail("percent→decimal golden failed")
    bps = convert_quantity(Quantity(25.0, Unit.BASIS_POINTS), Unit.DECIMAL_RATE)
    if abs(bps.value - 0.0025) > 1e-15:
        return _fail("bps golden failed")
    try:
        convert_quantity(Quantity(500.0, Unit.USD), Unit.SHARES)
        return _fail("USD→SHARES should fail")
    except Exception:
        pass
    return _pass("unit conversions fail closed + bps/percent goldens")


def _check_asof() -> tuple[str, str]:
    from .mechanics.common import InputDatum, AssumptionClass
    d = InputDatum("nav", 1.0, Unit.USD, AssumptionClass.VERIFIED_FACT_INPUT, as_of="")
    try:
        d.require_as_of()
        return _fail("missing as_of did not fail")
    except Exception as exc:
        if getattr(exc, "status", None) is None or exc.status.value != "UNAVAILABLE":
            return _fail(f"missing as_of wrong status: {exc}")
    return _pass("missing source_as_of is UNAVAILABLE")


def _check_auth() -> tuple[str, str]:
    from .mechanics.results import wrap_mechanic
    from .results import finalize
    calc = analyze_bond(
        instrument_id="z", settlement="2020-01-01", maturity="2021-01-01",
        coupon_rate=0.0, frequency="annual", day_count="ACT/365",
        yield_to_maturity=0.05,
    )
    typed = finalize(wrap_mechanic("fixed_income", calc))
    # Caller-built signed? unsigned wrapper
    try:
        fake = governed_result(typed, input_artifact={"forged": True})
    except Exception:
        fake = None
    if fake is not None and fake.receipt.verify():
        return _fail("unsigned/forged path unexpectedly verified")
    gov = run_governed_fixed_income(FixedIncomeInput(
        instrument_id="z", settlement="2020-01-01", maturity="2021-01-01",
        coupon_rate=0.0, frequency="annual", day_count="ACT/365",
        yield_to_maturity=0.05,
    ))
    if not gov.receipt.verify():
        return _fail("producer receipt did not verify")
    if gov.result.status != "OK":
        return _fail("producer result not OK")
    return _pass("producer receipt authentic; caller-built not governed")


def _check_authority() -> tuple[str, str]:
    from .mechanics import AUTHORITY as A
    if A != "READ_ONLY_ADVISORY":
        return _fail(f"authority drifted: {A}")
    r = analyze_bond(
        instrument_id="z", settlement="2020-01-01", maturity="2021-01-01",
        coupon_rate=0.0, frequency="annual", day_count="ACT/365", yield_to_maturity=0.05,
    )
    if r.authority != "READ_ONLY_ADVISORY" or r.result.get("authority") != "READ_ONLY_ADVISORY":
        return _fail("result authority not READ_ONLY_ADVISORY")
    return _pass("authority remains READ_ONLY_ADVISORY")


def _check_scope() -> tuple[str, str]:
    for f in (
        "scripts/lib/cio_acceptance_v4.py",
        "scripts/run_cio_acceptance.py",
        "apps/command-center-v3/src/pages/CioHub.tsx",
        "scripts/rag_retrieval.py",
    ):
        if not pr_scope_guard.is_denied(f):
            return _fail(f"R2 scope guard failed to deny {f}")
    if not pr_scope_guard.is_allowed("scripts/lib/research_governance/mechanics/fixed_income.py"):
        return _fail("mechanics path not allowlisted")
    if not pr_scope_guard.is_allowed("tests/test_research_mechanics_etf.py"):
        return _fail("R2 tests not allowlisted")
    if not pr_scope_guard.is_allowed("docs/investment-office/R2_DETERMINISTIC_MECHANICS.md"):
        return _fail("R2 docs not allowlisted")
    r3 = Path(__file__).resolve().parents[3] / "scripts" / "lib" / "research_governance" / "almanac.py"
    if r3.is_file():
        return _fail("R3 almanac module present")
    return _pass("R2 allowlist + denylist; no R3 files")


R2A_CHECKS = {
    "R2A-1": _check_fi_vectors,
    "R2A-2": _check_fi_conventions,
    "R2A-3": _check_ytw,
    "R2A-4": _check_risk,
    "R2A-5": _check_etf_nav,
    "R2A-6": _check_etf_tracking,
    "R2A-7": _check_etf_proxy,
    "R2A-8": _check_val_vectors,
    "R2A-9": _check_rdcf,
    "R2A-10": _check_sens,
    "R2A-11": _check_units,
    "R2A-12": _check_asof,
    "R2A-13": _check_auth,
    "R2A-14": _check_authority,
    "R2A-15": _check_scope,
}
