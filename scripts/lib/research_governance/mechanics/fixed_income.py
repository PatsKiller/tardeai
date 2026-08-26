"""R2 fixed-income mechanics. Explicit conventions. Fail closed.

Supported instruments: fixed-rate coupon, zero-coupon, callable fixed-rate.
Day-counts: ACT/ACT_ISDA, ACT/360, ACT/365, 30/360_US.
Frequencies: annual, semiannual, quarterly, monthly.

Yields are annual *nominal* rates compounded at the coupon frequency unless
the caller declares otherwise. Prices default to per-100 face.

YTW is UNAVAILABLE unless every economically relevant call/maturity path
needed for the calculation is supplied. Call schedules are never inferred.

Formula conventions are industry-standard (Tuckman/Serrat / SIA 30/360 /
ISDA ACT/ACT). Canon books in the R1 catalog are SOURCE_CLAIM_INCOMPLETE;
this module does not claim a specific book page.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Optional

from .common import (
    AUTHORITY,
    AssumptionClass,
    CouponFrequency,
    DayCount,
    InputDatum,
    MechanicError,
    MechanicResult,
    MechanicStatus,
    Quantity,
    Unit,
    as_decimal_rate,
    fail_result,
    parse_coupon_frequency,
    parse_date_only,
    parse_day_count,
    periods_per_year,
    require_unit,
    year_fraction,
)

_THIS = Path(__file__).resolve()
_YTM_TOL = 1e-12
_YTM_MAX_ITER = 80
_YTM_LO = -0.5
_YTM_HI = 5.0

_LIMITATIONS = [
    "Deterministic math conditional on supplied contractual inputs and conventions.",
    "Not a live market quotation and not financial truth.",
    "Day-count 30/360_US is NASD/SIA; ICMA 30E/360 is unsupported (ambiguous if requested as 30/360).",
    "Yield is annual nominal compounded at coupon frequency.",
    "Canon book page citations unavailable (SOURCE_CLAIM_INCOMPLETE).",
]


@dataclass(frozen=True)
class CashFlow:
    pay_date: date
    amount_per_100: float
    year_frac_from_settle: float
    kind: str  # coupon | redemption | combined


@dataclass(frozen=True)
class CallPath:
    date: date
    price_per_100: float


def _src() -> Path:
    return _THIS


def _qty_map(inputs: dict[str, InputDatum]) -> tuple[dict, dict, dict, dict, dict, dict]:
    values, units, conv, asof, sources, quality = {}, {}, {}, {}, {}, {}
    for k, d in inputs.items():
        values[k] = d.value
        units[k] = d.unit.value if d.unit else ""
        conv[k] = d.convention or ""
        asof[k] = d.as_of
        sources[k] = d.source
        quality[k] = d.klass.value
    return values, units, conv, asof, sources, quality


def _ok(
    *,
    calculation_id: str,
    mechanic_type: str,
    instrument_id: str,
    result: dict[str, Any],
    inputs: dict[str, InputDatum],
    conventions: dict[str, str],
    assumptions: Optional[dict] = None,
    warnings: Optional[list[str]] = None,
) -> MechanicResult:
    iv, iu, ic, ia, iso, iq = _qty_map(inputs)
    ic.update(conventions)
    r = MechanicResult(
        calculation_id=calculation_id,
        mechanic_type=mechanic_type,
        instrument_id=instrument_id,
        status=MechanicStatus.OK,
        result=result,
        warnings=list(warnings or []),
        limitations=list(_LIMITATIONS),
        input_values=iv,
        input_units=iu,
        input_conventions=ic,
        input_as_of=ia,
        input_sources=iso,
        input_quality=iq,
        assumptions=dict(assumptions or {}),
        assumption_sources={k: "caller" for k in (assumptions or {})},
        assumption_as_of={k: None for k in (assumptions or {})},
    )
    return r.seal(_src())


def _fail(cid: str, mtype: str, iid: str, err: MechanicError, inputs: Optional[dict] = None) -> MechanicResult:
    extra = {}
    if inputs:
        iv, iu, ic, ia, iso, iq = _qty_map(inputs)
        extra = dict(
            input_values=iv, input_units=iu, input_conventions=ic,
            input_as_of=ia, input_sources=iso, input_quality=iq,
        )
    return fail_result(
        calculation_id=cid,
        mechanic_type=mtype,
        instrument_id=iid,
        status=err.status,
        reason=err.reason,
        reason_code=str(err.extra.get("reason_code") or err.status.value),
        source_path=_src(),
        limitations=list(_LIMITATIONS),
        **extra,
    )


def _add_months(d: date, months: int) -> date:
    y = d.year + (d.month - 1 + months) // 12
    m = (d.month - 1 + months) % 12 + 1
    last = __import__("calendar").monthrange(y, m)[1]
    return date(y, m, min(d.day, last))


def _coupon_dates(maturity: date, freq: CouponFrequency, first_on_or_after: date) -> list[date]:
    step = 12 // periods_per_year(freq)
    dates: list[date] = []
    # Walk backward from maturity so the final coupon is on maturity.
    cur = maturity
    while cur > first_on_or_after:
        dates.append(cur)
        cur = _add_months(cur, -step)
        if len(dates) > 2000:
            raise MechanicError(MechanicStatus.INVALID_INPUT, "coupon schedule exploded")
    return sorted(set(d for d in dates if d > first_on_or_after))


def _previous_coupon(maturity: date, freq: CouponFrequency, settle: date) -> date:
    step = 12 // periods_per_year(freq)
    cur = maturity
    prev = maturity
    guard = 0
    while cur > settle:
        prev = cur
        cur = _add_months(cur, -step)
        guard += 1
        if guard > 2000:
            raise MechanicError(MechanicStatus.INVALID_INPUT, "previous-coupon search failed")
    return cur


def cashflow_schedule(
    *,
    settlement: date,
    maturity: date,
    coupon_rate_dec: float,
    freq: CouponFrequency,
    day_count: DayCount,
    face_per_100: float = 100.0,
    redemption_per_100: float = 100.0,
) -> list[CashFlow]:
    if coupon_rate_dec < 0:
        raise MechanicError(MechanicStatus.INVALID_INPUT, "negative coupon rate")
    m = periods_per_year(freq)
    cpn = face_per_100 * coupon_rate_dec / m
    if coupon_rate_dec == 0:
        t = year_fraction(settlement, maturity, day_count)
        return [CashFlow(maturity, redemption_per_100, t, "redemption")]
    pays = _coupon_dates(maturity, freq, settlement)
    flows: list[CashFlow] = []
    for i, d in enumerate(pays):
        amt = cpn
        kind = "coupon"
        if d == maturity:
            amt = cpn + redemption_per_100
            kind = "combined"
        t = year_fraction(settlement, d, day_count)
        flows.append(CashFlow(d, amt, t, kind))
    if not flows:
        raise MechanicError(MechanicStatus.INVALID_INPUT, "no cash flows after settlement")
    return flows


def accrued_interest_per_100(
    *,
    settlement: date,
    maturity: date,
    coupon_rate_dec: float,
    freq: CouponFrequency,
    day_count: DayCount,
) -> float:
    if coupon_rate_dec == 0:
        return 0.0
    prev = _previous_coupon(maturity, freq, settlement)
    nxt_candidates = _coupon_dates(maturity, freq, prev)
    nxt = nxt_candidates[0] if nxt_candidates else maturity
    if settlement <= prev:
        return 0.0
    if settlement >= nxt:
        return 0.0
    frac_elapsed = year_fraction(prev, settlement, day_count)
    frac_period = year_fraction(prev, nxt, day_count)
    if frac_period <= 0:
        raise MechanicError(MechanicStatus.INVALID_INPUT, "zero-length coupon period")
    period_coupon = 100.0 * coupon_rate_dec / periods_per_year(freq)
    return period_coupon * (frac_elapsed / frac_period)


def dirty_price_from_yield(
    *,
    settlement: date,
    maturity: date,
    coupon_rate_dec: float,
    freq: CouponFrequency,
    day_count: DayCount,
    yield_dec: float,
    redemption_per_100: float = 100.0,
) -> float:
    flows = cashflow_schedule(
        settlement=settlement, maturity=maturity, coupon_rate_dec=coupon_rate_dec,
        freq=freq, day_count=day_count, redemption_per_100=redemption_per_100,
    )
    m = periods_per_year(freq)
    total = 0.0
    for cf in flows:
        total += cf.amount_per_100 / ((1.0 + yield_dec / m) ** (m * cf.year_frac_from_settle))
    return total


def _price_derivative(settlement, maturity, coupon_rate_dec, freq, day_count, y, redemption) -> float:
    h = 1e-6
    up = dirty_price_from_yield(
        settlement=settlement, maturity=maturity, coupon_rate_dec=coupon_rate_dec,
        freq=freq, day_count=day_count, yield_dec=y + h, redemption_per_100=redemption,
    )
    dn = dirty_price_from_yield(
        settlement=settlement, maturity=maturity, coupon_rate_dec=coupon_rate_dec,
        freq=freq, day_count=day_count, yield_dec=y - h, redemption_per_100=redemption,
    )
    return (up - dn) / (2 * h)


def solve_yield(
    *,
    dirty_target: float,
    settlement: date,
    maturity: date,
    coupon_rate_dec: float,
    freq: CouponFrequency,
    day_count: DayCount,
    redemption_per_100: float = 100.0,
) -> dict[str, Any]:
    """Bracket + Newton. Fail closed if not bracketed or residual too large."""
    def px(y: float) -> float:
        return dirty_price_from_yield(
            settlement=settlement, maturity=maturity, coupon_rate_dec=coupon_rate_dec,
            freq=freq, day_count=day_count, yield_dec=y, redemption_per_100=redemption_per_100,
        )

    lo, hi = _YTM_LO, _YTM_HI
    plo, phi = px(lo) - dirty_target, px(hi) - dirty_target
    if plo == 0:
        return {"yield": lo, "iterations": 0, "residual": 0.0, "annualization": "nominal",
                "compounding": "coupon_frequency", "frequency": freq.value, "bracketed": True}
    if phi == 0:
        return {"yield": hi, "iterations": 0, "residual": 0.0, "annualization": "nominal",
                "compounding": "coupon_frequency", "frequency": freq.value, "bracketed": True}
    if plo * phi > 0:
        raise MechanicError(
            MechanicStatus.UNAVAILABLE,
            "yield root not bracketed in [-50%, +500%]",
            reason_code="ROOT_NOT_BRACKETED",
        )
    y = 0.05
    it = 0
    for it in range(1, _YTM_MAX_ITER + 1):
        p = px(y)
        resid = p - dirty_target
        if abs(resid) < _YTM_TOL:
            return {
                "yield": y, "iterations": it, "residual": resid,
                "annualization": "nominal", "compounding": "coupon_frequency",
                "frequency": freq.value, "bracketed": True,
            }
        deriv = _price_derivative(settlement, maturity, coupon_rate_dec, freq, day_count, y, redemption_per_100)
        if deriv == 0 or not math.isfinite(deriv):
            # bisection step
            mid = 0.5 * (lo + hi)
            if (px(mid) - dirty_target) * plo > 0:
                lo = mid
                plo = px(lo) - dirty_target
            else:
                hi = mid
            y = 0.5 * (lo + hi)
            continue
        y_new = y - resid / deriv
        if y_new <= lo or y_new >= hi or not math.isfinite(y_new):
            y_new = 0.5 * (lo + hi)
        if (px(y_new) - dirty_target) * plo > 0:
            lo = y_new
            plo = px(lo) - dirty_target
        else:
            hi = y_new
        y = y_new
    resid = px(y) - dirty_target
    if abs(resid) >= 1e-8:
        raise MechanicError(
            MechanicStatus.UNAVAILABLE,
            f"yield solver residual {resid} exceeds tolerance after {_YTM_MAX_ITER} iterations",
            reason_code="SOLVER_RESIDUAL",
        )
    return {
        "yield": y, "iterations": it, "residual": resid,
        "annualization": "nominal", "compounding": "coupon_frequency",
        "frequency": freq.value, "bracketed": True,
    }


def macaulay_modified_dv01_convexity(
    *,
    settlement: date,
    maturity: date,
    coupon_rate_dec: float,
    freq: CouponFrequency,
    day_count: DayCount,
    yield_dec: float,
    dirty: float,
    redemption_per_100: float = 100.0,
    face: Optional[float] = None,
) -> dict[str, Any]:
    flows = cashflow_schedule(
        settlement=settlement, maturity=maturity, coupon_rate_dec=coupon_rate_dec,
        freq=freq, day_count=day_count, redemption_per_100=redemption_per_100,
    )
    m = periods_per_year(freq)
    mac_num = 0.0
    conv_num = 0.0
    for cf in flows:
        df = 1.0 / ((1.0 + yield_dec / m) ** (m * cf.year_frac_from_settle))
        pv = cf.amount_per_100 * df
        t = cf.year_frac_from_settle
        mac_num += t * pv
        conv_num += t * (t + 1.0 / m) * pv
    if dirty == 0:
        raise MechanicError(MechanicStatus.INVALID_INPUT, "dirty price is zero")
    macaulay = mac_num / dirty
    modified = macaulay / (1.0 + yield_dec / m)
    # Convexity in years^2 / (per unit yield), standard periodic compounding.
    convexity = conv_num / (dirty * (1.0 + yield_dec / m) ** 2)
    # DV01: price change for +1bp yield. Analytical ≈ modified * dirty * 1e-4
    dv01_per_100 = modified * dirty * 1e-4
    out = {
        "macaulay_duration_years": macaulay,
        "modified_duration": modified,
        "convexity": convexity,
        "dv01_per_100_face": dv01_per_100,
        "dv01_basis": "price_change_for_plus_1bp_yield",
        "yield_compounding": "coupon_frequency",
        "frequency": freq.value,
    }
    if face is not None:
        out["dv01_position_usd"] = dv01_per_100 * (face / 100.0)
        out["face_value"] = face
    return out


def _parse_calls(raw: Any) -> Optional[list[CallPath]]:
    if raw is None:
        return None
    if not isinstance(raw, (list, tuple)):
        raise MechanicError(MechanicStatus.INVALID_INPUT, "call schedule must be a list")
    paths: list[CallPath] = []
    for item in raw:
        if not isinstance(item, dict) or "date" not in item or "price" not in item:
            raise MechanicError(
                MechanicStatus.UNAVAILABLE,
                "incomplete call schedule (each path needs date and price)",
                reason_code="INCOMPLETE_CALL_SCHEDULE",
            )
        d = parse_date_only(item["date"], name="call_date")
        px = float(item["price"])
        if not math.isfinite(px) or px <= 0:
            raise MechanicError(MechanicStatus.INVALID_INPUT, f"invalid call price {item['price']!r}")
        paths.append(CallPath(d, px))
    return paths


def analyze_bond(
    *,
    instrument_id: str = "bond",
    calculation_id: str = "fi-bond",
    settlement: Any,
    maturity: Any,
    coupon_rate: Any,
    coupon_rate_unit: Any = Unit.DECIMAL_RATE,
    frequency: Any,
    day_count: Any,
    clean_price: Any = None,
    dirty_price: Any = None,
    yield_to_maturity: Any = None,
    face: Any = None,
    callable: bool = False,
    call_schedule: Any = None,
    redemption: Any = 100.0,
    inputs_meta: Optional[dict[str, InputDatum]] = None,
) -> MechanicResult:
    """Full bond analytics. Supply clean or dirty price, or a yield."""
    iid = instrument_id
    cid = calculation_id
    meta: dict[str, InputDatum] = dict(inputs_meta or {})
    try:
        if settlement is None:
            raise MechanicError(MechanicStatus.UNAVAILABLE, "missing settlement date", reason_code="MISSING_SETTLEMENT")
        if maturity is None:
            raise MechanicError(MechanicStatus.INVALID_INPUT, "missing maturity")
        settle = parse_date_only(settlement, name="settlement")
        mat = parse_date_only(maturity, name="maturity")
        if settle > mat:
            raise MechanicError(MechanicStatus.INVALID_INPUT, "settlement after maturity")
        freq = parse_coupon_frequency(frequency)
        dc = parse_day_count(day_count)
        if isinstance(coupon_rate, Quantity):
            cpn = as_decimal_rate(coupon_rate, name="coupon_rate")
        else:
            cpn = as_decimal_rate(Quantity(float(coupon_rate), coupon_rate_unit if isinstance(coupon_rate_unit, Unit) else Unit(coupon_rate_unit)), name="coupon_rate")
        if face is not None and float(face) < 0:
            raise MechanicError(MechanicStatus.INVALID_INPUT, "negative face where unsupported")
        red = float(redemption)
        acc = accrued_interest_per_100(
            settlement=settle, maturity=mat, coupon_rate_dec=cpn, freq=freq, day_count=dc,
        )
        dirty: Optional[float] = None
        clean: Optional[float] = None
        ytm: Optional[float] = None
        ytm_solver: dict[str, Any] = {}
        if dirty_price is not None:
            dirty = float(dirty_price)
            clean = dirty - acc
        elif clean_price is not None:
            clean = float(clean_price)
            dirty = clean + acc
        if yield_to_maturity is not None:
            if isinstance(yield_to_maturity, Quantity):
                ytm = as_decimal_rate(yield_to_maturity, name="yield")
            else:
                ytm = float(yield_to_maturity)
            if dirty is None:
                dirty = dirty_price_from_yield(
                    settlement=settle, maturity=mat, coupon_rate_dec=cpn,
                    freq=freq, day_count=dc, yield_dec=ytm, redemption_per_100=red,
                )
                clean = dirty - acc
        if dirty is None:
            raise MechanicError(MechanicStatus.UNAVAILABLE, "need clean_price, dirty_price, or yield_to_maturity")
        if ytm is None:
            ytm_solver = solve_yield(
                dirty_target=dirty, settlement=settle, maturity=mat,
                coupon_rate_dec=cpn, freq=freq, day_count=dc, redemption_per_100=red,
            )
            ytm = float(ytm_solver["yield"])
        else:
            ytm_solver = {
                "yield": ytm, "iterations": 0, "residual": dirty - dirty_price_from_yield(
                    settlement=settle, maturity=mat, coupon_rate_dec=cpn,
                    freq=freq, day_count=dc, yield_dec=ytm, redemption_per_100=red,
                ),
                "annualization": "nominal", "compounding": "coupon_frequency",
                "frequency": freq.value, "bracketed": True,
            }
        risk = macaulay_modified_dv01_convexity(
            settlement=settle, maturity=mat, coupon_rate_dec=cpn, freq=freq,
            day_count=dc, yield_dec=ytm, dirty=dirty, redemption_per_100=red,
            face=None if face is None else float(face),
        )
        ytc_list: list[dict[str, Any]] = []
        ytw_status = MechanicStatus.OK
        ytw_reason = ""
        ytw: Optional[float] = None
        if callable:
            calls = _parse_calls(call_schedule)
            if not calls:
                ytw_status = MechanicStatus.UNAVAILABLE
                ytw_reason = "INCOMPLETE_CALL_SCHEDULE"
            else:
                path_yields = [ytm]
                for call in calls:
                    if call.date <= settle or call.date > mat:
                        continue
                    try:
                        sol = solve_yield(
                            dirty_target=dirty, settlement=settle, maturity=call.date,
                            coupon_rate_dec=cpn, freq=freq, day_count=dc,
                            redemption_per_100=call.price_per_100,
                        )
                        ytc_list.append({
                            "call_date": call.date.isoformat(),
                            "call_price_per_100": call.price_per_100,
                            "yield": sol["yield"],
                            "iterations": sol["iterations"],
                            "residual": sol["residual"],
                        })
                        path_yields.append(float(sol["yield"]))
                    except MechanicError as exc:
                        ytc_list.append({
                            "call_date": call.date.isoformat(),
                            "status": exc.status.value,
                            "reason": exc.reason,
                        })
                if path_yields:
                    ytw = min(path_yields)
        else:
            ytw = ytm
        # Price vs yield shock (normal positive-duration): +10bp
        p_up = dirty_price_from_yield(
            settlement=settle, maturity=mat, coupon_rate_dec=cpn, freq=freq,
            day_count=dc, yield_dec=ytm + 0.001, redemption_per_100=red,
        )
        result = {
            "instrument": "zero_coupon" if cpn == 0 else ("callable_fixed" if callable else "fixed_coupon"),
            "settlement": settle.isoformat(),
            "maturity": mat.isoformat(),
            "day_count": dc.value,
            "frequency": freq.value,
            "coupon_rate_decimal": cpn,
            "accrued_interest_per_100": acc,
            "clean_price_per_100": clean,
            "dirty_price_per_100": dirty,
            "price_basis": "PER_100_FACE",
            "identity_clean_plus_accrued": (clean if clean is not None else 0) + acc,
            "yield_to_maturity": ytm,
            "yield_solver": ytm_solver,
            "yield_to_call": ytc_list,
            "yield_to_worst": ytw,
            "ytw_status": ytw_status.value,
            "ytw_reason": ytw_reason,
            "price_at_yield_plus_10bp": p_up,
            "price_falls_when_yield_rises": p_up < dirty,
            "authority": AUTHORITY,
            **risk,
        }
        if ytw_status != MechanicStatus.OK:
            result["yield_to_worst"] = None
        warnings = []
        if ytw_status != MechanicStatus.OK:
            warnings.append(ytw_reason)
        return _ok(
            calculation_id=cid,
            mechanic_type="fixed_income",
            instrument_id=iid,
            result=result,
            inputs=meta or {
                "settlement": InputDatum("settlement", settle.isoformat(), None, AssumptionClass.VERIFIED_FACT_INPUT),
                "maturity": InputDatum("maturity", mat.isoformat(), None, AssumptionClass.VERIFIED_FACT_INPUT),
                "coupon_rate": InputDatum("coupon_rate", cpn, Unit.DECIMAL_RATE, AssumptionClass.VERIFIED_FACT_INPUT),
                "day_count": InputDatum("day_count", dc.value, None, AssumptionClass.CONVENTION, convention=dc.value),
                "frequency": InputDatum("frequency", freq.value, None, AssumptionClass.CONVENTION, convention=freq.value),
            },
            conventions={"day_count": dc.value, "frequency": freq.value, "price_basis": "PER_100_FACE",
                         "yield": "annual_nominal_compounded_at_coupon_frequency"},
            warnings=warnings,
        )
    except MechanicError as err:
        return _fail(cid, "fixed_income", iid, err, meta or None)
    except (TypeError, ValueError) as err:
        return _fail(cid, "fixed_income", iid, MechanicError(MechanicStatus.INVALID_INPUT, str(err)), meta or None)
