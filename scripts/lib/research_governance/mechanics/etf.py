"""R2 ETF mechanics. Official NAV, indicative NAV, proxy, and market price are distinct.

PROXY may never be used as OFFICIAL_NAV. Indicative NAV cannot masquerade as official.
Premium/discount is valid only with compatible instrument, currency, and timestamps.
"""
from __future__ import annotations

import math
import statistics
from enum import Enum
from pathlib import Path
from typing import Any, Optional, Sequence

from .common import (
    AUTHORITY,
    AssumptionClass,
    InputDatum,
    MechanicError,
    MechanicResult,
    MechanicStatus,
    Quantity,
    Unit,
    convert_quantity,
    fail_result,
    parse_timestamp,
    require_unit,
    time_gap_seconds,
)

_THIS = Path(__file__).resolve()

DEFAULT_STALE_SECONDS = 18 * 3600  # same-session vs prior official NAV typically < 18h


class NavKind(str, Enum):
    OFFICIAL_NAV = "OFFICIAL_NAV"
    INDICATIVE_NAV = "INDICATIVE_NAV"
    MARKET_PRICE = "MARKET_PRICE"
    PROXY = "PROXY"


class ReturnBasis(str, Enum):
    PRICE = "price"
    TOTAL_RETURN = "total_return"
    NAV_TOTAL_RETURN = "nav_total_return"


class TeStdev(str, Enum):
    SAMPLE = "sample"
    POPULATION = "population"


_ANNUALIZATION = {
    "daily": 252,
    "weekly": 52,
    "monthly": 12,
    "quarterly": 4,
    "annual": 1,
}

_LIMITATIONS = [
    "Deterministic ETF identity math. Not a live AP basket or official fund accounting statement.",
    "Official NAV is accepted only when the caller labels it OFFICIAL_NAV.",
    "Creation-unit notional is shares × basis price; AP basket economics are not inferred.",
    "Canon ETF book (Ferri) is SOURCE_CLAIM_INCOMPLETE; no page citation is claimed.",
]


def _ok(cid, mtype, iid, result, inputs, conventions, warnings=None, assumptions=None) -> MechanicResult:
    iv, iu, ic, ia, iso, iq = {}, {}, {}, {}, {}, {}
    for k, d in inputs.items():
        iv[k] = d.value
        iu[k] = d.unit.value if d.unit else ""
        ic[k] = d.convention or ""
        ia[k] = d.as_of
        iso[k] = d.source
        iq[k] = d.klass.value
    ic.update(conventions)
    r = MechanicResult(
        calculation_id=cid, mechanic_type=mtype, instrument_id=iid,
        status=MechanicStatus.OK, result=result, warnings=list(warnings or []),
        limitations=list(_LIMITATIONS), input_values=iv, input_units=iu,
        input_conventions=ic, input_as_of=ia, input_sources=iso, input_quality=iq,
        assumptions=dict(assumptions or {}),
        assumption_sources={k: "caller" for k in (assumptions or {})},
        assumption_as_of={k: None for k in (assumptions or {})},
    )
    return r.seal(_THIS)


def _fail(cid, mtype, iid, err: MechanicError) -> MechanicResult:
    return fail_result(
        calculation_id=cid, mechanic_type=mtype, instrument_id=iid,
        status=err.status, reason=err.reason,
        reason_code=str(err.extra.get("reason_code") or err.status.value),
        source_path=_THIS, limitations=list(_LIMITATIONS),
    )


def _parse_kind(raw: Any) -> NavKind:
    if isinstance(raw, NavKind):
        return raw
    try:
        return NavKind(str(raw).strip().upper())
    except ValueError as exc:
        raise MechanicError(MechanicStatus.INVALID_INPUT, f"unknown NAV/price kind: {raw!r}") from exc


def _money(value: Any, unit: Any, name: str) -> tuple[float, Unit]:
    if isinstance(value, Quantity):
        q = convert_quantity(value, Unit.USD) if value.unit == Unit.USD_MILLIONS else value
        if q.unit != Unit.USD:
            raise MechanicError(MechanicStatus.INVALID_INPUT, f"{name} must be USD (or USD_MILLIONS)", reason_code="UNIT_MISMATCH")
        return q.value, Unit.USD
    u = unit if isinstance(unit, Unit) else Unit(str(unit))
    if u == Unit.USD_MILLIONS:
        return float(value) * 1_000_000.0, Unit.USD
    if u != Unit.USD:
        raise MechanicError(MechanicStatus.INVALID_INPUT, f"{name} must be USD, got {u.value}", reason_code="UNIT_MISMATCH")
    return float(value), Unit.USD


def premium_discount(
    *,
    instrument_id: str,
    market_price: Any,
    market_price_as_of: Any,
    market_currency: str,
    nav: Any,
    nav_as_of: Any,
    nav_currency: str,
    nav_kind: Any,
    requested_nav_role: Any = NavKind.OFFICIAL_NAV,
    share_class_id: str = "",
    nav_share_class_id: str = "",
    fx_rate: Any = None,
    stale_tolerance_seconds: float = DEFAULT_STALE_SECONDS,
    calculation_id: str = "etf-prem",
    price_unit: Any = Unit.USD,
    nav_unit: Any = Unit.USD,
) -> MechanicResult:
    cid, iid, mtype = calculation_id, instrument_id, "etf_premium_discount"
    try:
        kind = _parse_kind(nav_kind)
        role = _parse_kind(requested_nav_role)
        if kind == NavKind.PROXY:
            raise MechanicError(
                MechanicStatus.INVALID_INPUT,
                "PROXY may never be used as OFFICIAL_NAV",
                reason_code="PROXY_AS_OFFICIAL_NAV",
            )
        if role == NavKind.OFFICIAL_NAV and kind == NavKind.INDICATIVE_NAV:
            raise MechanicError(
                MechanicStatus.INVALID_INPUT,
                "indicative NAV cannot masquerade as official NAV",
                reason_code="INDICATIVE_AS_OFFICIAL",
            )
        if role == NavKind.OFFICIAL_NAV and kind != NavKind.OFFICIAL_NAV:
            raise MechanicError(
                MechanicStatus.INVALID_INPUT,
                f"requested OFFICIAL_NAV but caller labeled {kind.value}",
                reason_code="NAV_KIND_MISMATCH",
            )
        px, _ = _money(market_price, price_unit, "market_price")
        nv, _ = _money(nav, nav_unit, "nav")
        if px <= 0 or nv <= 0:
            raise MechanicError(MechanicStatus.INVALID_INPUT, "market price and NAV must be positive")
        px_ts = parse_timestamp(market_price_as_of, name="market_price_as_of")
        nv_ts = parse_timestamp(nav_as_of, name="nav_as_of")
        gap = time_gap_seconds(px_ts, nv_ts)
        if gap > float(stale_tolerance_seconds):
            raise MechanicError(
                MechanicStatus.STALE_INPUT,
                f"market price and NAV timestamps differ by {gap:.0f}s (tolerance {stale_tolerance_seconds:.0f}s)",
                reason_code="STALE_NAV_PRICE",
            )
        mc, nc = str(market_currency).upper(), str(nav_currency).upper()
        if mc != nc:
            if fx_rate is None:
                raise MechanicError(
                    MechanicStatus.UNAVAILABLE,
                    f"currency mismatch {mc} vs {nc} and no FX supplied",
                    reason_code="CURRENCY_MISMATCH",
                )
            nv = nv * float(fx_rate)
        if share_class_id and nav_share_class_id and share_class_id != nav_share_class_id:
            raise MechanicError(MechanicStatus.UNAVAILABLE, "share-class mismatch between price and NAV")
        prem = px / nv - 1.0
        inputs = {
            "market_price": InputDatum("market_price", px, Unit.USD, AssumptionClass.VERIFIED_FACT_INPUT, as_of=px_ts.isoformat()),
            "nav": InputDatum("nav", nv, Unit.USD, AssumptionClass.VERIFIED_FACT_INPUT, as_of=nv_ts.isoformat()),
            "nav_kind": InputDatum("nav_kind", kind.value, None, AssumptionClass.CONVENTION, convention=kind.value),
        }
        return _ok(cid, mtype, iid, {
            "market_price": px,
            "market_price_as_of": px_ts.isoformat(),
            "nav": nv,
            "nav_as_of": nv_ts.isoformat(),
            "nav_kind": kind.value,
            "time_gap_seconds": gap,
            "premium_discount_pct": prem * 100.0,
            "premium_discount_decimal": prem,
            "currency": mc,
            "authority": AUTHORITY,
        }, inputs, {"nav_kind": kind.value, "formula": "market_price/nav - 1"})
    except MechanicError as err:
        return _fail(cid, mtype, iid, err)


def tracking_difference(
    *,
    instrument_id: str,
    fund_return: float,
    benchmark_return: float,
    return_basis: Any,
    fund_unit: Any = Unit.DECIMAL_RATE,
    bench_unit: Any = Unit.DECIMAL_RATE,
    calculation_id: str = "etf-td",
) -> MechanicResult:
    cid, iid, mtype = calculation_id, instrument_id, "etf_tracking_difference"
    try:
        try:
            basis = ReturnBasis(str(return_basis).strip().lower())
        except ValueError as exc:
            raise MechanicError(MechanicStatus.AMBIGUOUS_CONVENTION, f"return basis missing/unknown: {return_basis!r}") from exc
        fu = fund_unit if isinstance(fund_unit, Unit) else Unit(str(fund_unit))
        bu = bench_unit if isinstance(bench_unit, Unit) else Unit(str(bench_unit))
        if fu != bu:
            raise MechanicError(MechanicStatus.INVALID_INPUT, "fund/benchmark return units differ", reason_code="UNIT_MISMATCH")
        fr = Quantity(float(fund_return), fu)
        br = Quantity(float(benchmark_return), bu)
        if fu == Unit.PERCENT:
            fd, bd = fr.value / 100.0, br.value / 100.0
        elif fu == Unit.DECIMAL_RATE:
            fd, bd = fr.value, br.value
        else:
            raise MechanicError(MechanicStatus.INVALID_INPUT, "returns must be PERCENT or DECIMAL_RATE")
        td = fd - bd
        inputs = {
            "fund_return": InputDatum("fund_return", fund_return, fu, AssumptionClass.VERIFIED_FACT_INPUT),
            "benchmark_return": InputDatum("benchmark_return", benchmark_return, bu, AssumptionClass.VERIFIED_FACT_INPUT),
            "return_basis": InputDatum("return_basis", basis.value, None, AssumptionClass.CONVENTION, convention=basis.value),
        }
        return _ok(cid, mtype, iid, {
            "tracking_difference_decimal": td,
            "tracking_difference_pct": td * 100.0,
            "return_basis": basis.value,
            "formula": "fund_return - benchmark_return",
            "authority": AUTHORITY,
        }, inputs, {"return_basis": basis.value})
    except MechanicError as err:
        return _fail(cid, mtype, iid, err)


def tracking_error(
    *,
    instrument_id: str,
    tracking_differences: Sequence[float],
    return_frequency: Any,
    stdev: Any = TeStdev.SAMPLE,
    annualization_factor: Optional[int] = None,
    difference_unit: Any = Unit.DECIMAL_RATE,
    calculation_id: str = "etf-te",
) -> MechanicResult:
    cid, iid, mtype = calculation_id, instrument_id, "etf_tracking_error"
    try:
        if return_frequency is None or str(return_frequency).strip() == "":
            raise MechanicError(MechanicStatus.AMBIGUOUS_CONVENTION, "frequency missing for annualized TE")
        freq = str(return_frequency).strip().lower()
        if annualization_factor is None:
            if freq not in _ANNUALIZATION:
                raise MechanicError(MechanicStatus.AMBIGUOUS_CONVENTION, f"unknown return frequency: {return_frequency!r}")
            ann = _ANNUALIZATION[freq]
        else:
            ann = int(annualization_factor)
            if ann <= 0:
                raise MechanicError(MechanicStatus.INVALID_INPUT, "annualization_factor must be positive")
        series = [float(x) for x in tracking_differences]
        if len(series) < 2:
            raise MechanicError(MechanicStatus.UNAVAILABLE, "single-observation TE is undefined")
        kind = TeStdev(str(stdev).strip().lower()) if not isinstance(stdev, TeStdev) else stdev
        if kind == TeStdev.SAMPLE:
            sd = statistics.stdev(series)
        else:
            sd = statistics.pstdev(series)
        te = sd * math.sqrt(ann)
        u = difference_unit if isinstance(difference_unit, Unit) else Unit(str(difference_unit))
        inputs = {
            "n": InputDatum("n", len(series), None, AssumptionClass.DERIVED_INPUT),
            "return_frequency": InputDatum("return_frequency", freq, None, AssumptionClass.CONVENTION, convention=freq),
        }
        return _ok(cid, mtype, iid, {
            "n": len(series),
            "periodic_stdev": sd,
            "tracking_error_annualized": te,
            "return_frequency": freq,
            "annualization_factor": ann,
            "stdev": kind.value,
            "difference_unit": u.value,
            "authority": AUTHORITY,
        }, inputs, {"return_frequency": freq, "stdev": kind.value})
    except MechanicError as err:
        return _fail(cid, mtype, iid, err)
    except statistics.StatisticsError as err:
        return _fail(cid, mtype, iid, MechanicError(MechanicStatus.UNAVAILABLE, str(err)))


def spread_bps(
    *,
    instrument_id: str,
    bid: float,
    ask: float,
    calculation_id: str = "etf-spread",
) -> MechanicResult:
    cid, iid, mtype = calculation_id, instrument_id, "etf_spread"
    try:
        b, a = float(bid), float(ask)
        if b <= 0 or a <= 0:
            raise MechanicError(MechanicStatus.INVALID_INPUT, "zero/negative bid/ask")
        if a < b:
            raise MechanicError(MechanicStatus.INVALID_INPUT, "ask < bid")
        mid = (a + b) / 2.0
        bps = (a - b) / mid * 10_000.0
        inputs = {
            "bid": InputDatum("bid", b, Unit.USD, AssumptionClass.VERIFIED_FACT_INPUT),
            "ask": InputDatum("ask", a, Unit.USD, AssumptionClass.VERIFIED_FACT_INPUT),
        }
        return _ok(cid, mtype, iid, {
            "quoted_spread": a - b,
            "mid": mid,
            "spread_bps": bps,
            "authority": AUTHORITY,
        }, inputs, {"formula": "(ask-bid)/mid * 10000"})
    except MechanicError as err:
        return _fail(cid, mtype, iid, err)


def creation_unit_notional(
    *,
    instrument_id: str,
    creation_unit_shares: Any,
    basis_price: float,
    basis: str,
    calculation_id: str = "etf-cu",
) -> MechanicResult:
    cid, iid, mtype = calculation_id, instrument_id, "etf_creation_unit"
    try:
        if creation_unit_shares is None:
            raise MechanicError(MechanicStatus.UNAVAILABLE, "creation unit missing share count")
        shares = float(creation_unit_shares)
        if shares <= 0:
            raise MechanicError(MechanicStatus.INVALID_INPUT, "creation_unit_shares must be positive")
        px = float(basis_price)
        if px <= 0:
            raise MechanicError(MechanicStatus.INVALID_INPUT, "basis_price must be positive")
        b = str(basis).strip().lower()
        if b not in ("nav", "market_price"):
            raise MechanicError(MechanicStatus.AMBIGUOUS_CONVENTION, "creation-unit basis must be nav or market_price")
        notional = shares * px
        inputs = {
            "creation_unit_shares": InputDatum("creation_unit_shares", shares, Unit.SHARES, AssumptionClass.VERIFIED_FACT_INPUT),
            "basis_price": InputDatum("basis_price", px, Unit.USD, AssumptionClass.VERIFIED_FACT_INPUT),
        }
        return _ok(cid, mtype, iid, {
            "creation_notional": notional,
            "basis": b,
            "creation_unit_shares": shares,
            "basis_price": px,
            "note": "AP basket economics are not inferred; this is shares × basis only.",
            "authority": AUTHORITY,
        }, inputs, {"basis": b})
    except MechanicError as err:
        return _fail(cid, mtype, iid, err)


def position_values(
    *,
    instrument_id: str,
    shares: float,
    nav: float,
    market_price: float,
    calculation_id: str = "etf-pos",
) -> MechanicResult:
    cid, iid, mtype = calculation_id, instrument_id, "etf_position_value"
    try:
        sh, nv, px = float(shares), float(nav), float(market_price)
        if sh < 0:
            raise MechanicError(MechanicStatus.INVALID_INPUT, "negative shares")
        if nv <= 0 or px <= 0:
            raise MechanicError(MechanicStatus.INVALID_INPUT, "NAV and market price must be positive")
        inputs = {
            "shares": InputDatum("shares", sh, Unit.SHARES, AssumptionClass.VERIFIED_FACT_INPUT),
        }
        return _ok(cid, mtype, iid, {
            "nav_based_position_value": sh * nv,
            "market_price_position_value": sh * px,
            "authority": AUTHORITY,
        }, inputs, {"nav_role": "caller_supplied"})
    except MechanicError as err:
        return _fail(cid, mtype, iid, err)
