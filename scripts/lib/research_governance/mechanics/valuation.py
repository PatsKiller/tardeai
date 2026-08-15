"""R2 valuation / reverse-DCF. CONDITIONAL MODEL OUTPUT, not financial truth.

Gordon TV requires WACC > g. Missing debt/cash/shares never default to zero.
One unknown is solved at a time. Multiple roots in-domain → UNAVAILABLE.
"""
from __future__ import annotations

import math
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
    as_decimal_rate,
    convert_quantity,
    fail_result,
)

_THIS = Path(__file__).resolve()
_SOLVER_TOL = 1e-10
_SOLVER_MAX = 80

_LIMITATIONS = [
    "CONDITIONAL MODEL OUTPUT — not financial truth.",
    "Reverse DCF does not say what growth will occur; it says what growth/margin "
    "is implied by the supplied price under the supplied model and assumptions.",
    "Damodaran / Expectations Investing full text is SOURCE_CLAIM_INCOMPLETE; "
    "formulas are labeled industry-standard Gordon / explicit-period DCF.",
    "Missing debt or cash is UNAVAILABLE (never assumed zero).",
]


def _ok(cid, iid, result, inputs, conventions, warnings=None, assumptions=None) -> MechanicResult:
    iv, iu, ic, ia, iso, iq = {}, {}, {}, {}, {}, {}
    for k, d in inputs.items():
        iv[k] = d.value
        iu[k] = d.unit.value if d.unit else ""
        ic[k] = d.convention or ""
        ia[k] = d.as_of
        iso[k] = d.source
        iq[k] = d.klass.value
    ic.update(conventions)
    asum = dict(assumptions or {})
    r = MechanicResult(
        calculation_id=cid, mechanic_type="valuation_model", instrument_id=iid,
        status=MechanicStatus.OK, result=result, warnings=list(warnings or []),
        limitations=list(_LIMITATIONS), input_values=iv, input_units=iu,
        input_conventions=ic, input_as_of=ia, input_sources=iso, input_quality=iq,
        assumptions=asum,
        assumption_sources={k: (inputs.get(k).source if k in inputs else "caller") for k in asum},
        assumption_as_of={k: (inputs.get(k).as_of if k in inputs else None) for k in asum},
    )
    return r.seal(_THIS)


def _fail(cid, iid, err: MechanicError) -> MechanicResult:
    return fail_result(
        calculation_id=cid, mechanic_type="valuation_model", instrument_id=iid,
        status=err.status, reason=err.reason,
        reason_code=str(err.extra.get("reason_code") or err.status.value),
        source_path=_THIS, limitations=list(_LIMITATIONS),
    )


def _rate(value: Any, unit: Any, name: str) -> float:
    if isinstance(value, Quantity):
        return as_decimal_rate(value, name=name)
    u = unit if isinstance(unit, Unit) else Unit(str(unit or "DECIMAL_RATE"))
    return as_decimal_rate(Quantity(float(value), u), name=name)


def _usd(value: Any, unit: Any, name: str, *, required: bool) -> Optional[float]:
    if value is None:
        if required:
            raise MechanicError(MechanicStatus.UNAVAILABLE, f"missing {name}", reason_code=f"MISSING_{name.upper()}")
        return None
    if isinstance(value, Quantity):
        if value.unit not in (Unit.USD, Unit.USD_MILLIONS):
            raise MechanicError(MechanicStatus.AMBIGUOUS_CONVENTION, f"{name} unit must be USD or USD_MILLIONS")
        return convert_quantity(value, Unit.USD).value
    u = unit if isinstance(unit, Unit) else Unit(str(unit or "USD"))
    if u == Unit.USD_MILLIONS:
        return float(value) * 1_000_000.0
    if u != Unit.USD:
        raise MechanicError(MechanicStatus.AMBIGUOUS_CONVENTION, f"{name} ambiguous units (USD vs USD_MILLIONS)", reason_code="UNIT_MISMATCH")
    return float(value)


def present_value_fcfs(fcfs: Sequence[float], wacc: float) -> float:
    total = 0.0
    for i, cf in enumerate(fcfs, start=1):
        total += float(cf) / ((1.0 + wacc) ** i)
    return total


def gordon_tv(fcf_n: float, wacc: float, g: float) -> float:
    if wacc <= g:
        raise MechanicError(MechanicStatus.INVALID_INPUT, "WACC <= terminal growth", reason_code="WACC_LE_G")
    return float(fcf_n) * (1.0 + g) / (wacc - g)


def enterprise_to_equity(
    *,
    enterprise_value: float,
    debt: Optional[float],
    cash: Optional[float],
    other_claims: float = 0.0,
) -> float:
    if debt is None:
        raise MechanicError(MechanicStatus.UNAVAILABLE, "missing debt", reason_code="MISSING_DEBT")
    if cash is None:
        raise MechanicError(MechanicStatus.UNAVAILABLE, "missing cash", reason_code="MISSING_CASH")
    return float(enterprise_value) - float(debt) + float(cash) + float(other_claims)


def dcf_value(
    *,
    instrument_id: str,
    fcfs: Sequence[float],
    wacc: Any,
    terminal_growth: Any,
    debt: Any,
    cash: Any,
    shares: Any = None,
    other_claims: float = 0.0,
    market_price: Any = None,
    market_price_as_of: Optional[str] = None,
    market_price_source: str = "",
    wacc_unit: Any = Unit.DECIMAL_RATE,
    g_unit: Any = Unit.DECIMAL_RATE,
    money_unit: Any = Unit.USD,
    calculation_id: str = "val-dcf",
    wacc_source: str = "",
    wacc_as_of: Optional[str] = None,
    g_source: str = "",
    g_as_of: Optional[str] = None,
) -> MechanicResult:
    cid, iid = calculation_id, instrument_id
    try:
        flows = [float(x) for x in fcfs]
        if not flows:
            raise MechanicError(MechanicStatus.INVALID_INPUT, "empty explicit FCF forecast")
        w = _rate(wacc, wacc_unit, "wacc")
        g = _rate(terminal_growth, g_unit, "terminal_growth")
        dbt = _usd(debt, money_unit, "debt", required=True)
        csh = _usd(cash, money_unit, "cash", required=True)
        tv = gordon_tv(flows[-1], w, g)
        pv_fcf = present_value_fcfs(flows, w)
        pv_tv = tv / ((1.0 + w) ** len(flows))
        ev = pv_fcf + pv_tv
        eq = enterprise_to_equity(enterprise_value=ev, debt=dbt, cash=csh, other_claims=other_claims)
        per_share = None
        if shares is None:
            # per-share UNAVAILABLE; EV/equity still OK
            pass
        else:
            sh = float(shares)
            if sh < 0:
                raise MechanicError(MechanicStatus.INVALID_INPUT, "negative shares")
            if sh == 0:
                raise MechanicError(MechanicStatus.UNAVAILABLE, "missing share count", reason_code="MISSING_SHARES")
            per_share = eq / sh
        warnings = []
        if shares is None:
            warnings.append("per-share UNAVAILABLE (share count not supplied)")
        if market_price is not None and per_share is not None:
            mp = float(market_price)
            # flag inconsistent market-cap vs price if both shares and price given
            implied_eq = mp * float(shares)
            if abs(implied_eq - eq) / max(abs(eq), 1.0) > 0.25:
                warnings.append("market cap implied by price×shares differs from model equity by >25%")
        inputs = {
            "wacc": InputDatum("wacc", w, Unit.DECIMAL_RATE, AssumptionClass.ASSUMPTION_INPUT, source=wacc_source, as_of=wacc_as_of),
            "terminal_growth": InputDatum("terminal_growth", g, Unit.DECIMAL_RATE, AssumptionClass.ASSUMPTION_INPUT, source=g_source, as_of=g_as_of),
            "debt": InputDatum("debt", dbt, Unit.USD, AssumptionClass.VERIFIED_FACT_INPUT),
            "cash": InputDatum("cash", csh, Unit.USD, AssumptionClass.VERIFIED_FACT_INPUT),
        }
        result = {
            "label": "CONDITIONAL_MODEL_OUTPUT",
            "not": "FINANCIAL_TRUTH",
            "explicit_fcf_pv": pv_fcf,
            "terminal_value": tv,
            "terminal_value_pv": pv_tv,
            "enterprise_value": ev,
            "equity_value": eq,
            "per_share_value": per_share,
            "horizon_years": len(flows),
            "wacc": w,
            "terminal_growth": g,
            "market_price": None if market_price is None else float(market_price),
            "market_price_as_of": market_price_as_of,
            "market_price_source": market_price_source,
            "authority": AUTHORITY,
        }
        return _ok(cid, iid, result, inputs, {
            "terminal": "gordon_growth",
            "wacc_gt_g": True,
            "discounting": "end_of_year",
        }, warnings=warnings, assumptions={"wacc": w, "terminal_growth": g, "horizon": len(flows)})
    except MechanicError as err:
        return _fail(cid, iid, err)


def reverse_dcf(
    *,
    instrument_id: str,
    solved_variable: str,
    target_equity_value: float,
    fcfs: Optional[Sequence[float]] = None,
    starting_fcf: Optional[float] = None,
    horizon: int = 5,
    wacc: Any = None,
    terminal_growth: Any = None,
    fcf_growth: Any = None,
    debt: Any = None,
    cash: Any = None,
    other_claims: float = 0.0,
    wacc_unit: Any = Unit.DECIMAL_RATE,
    g_unit: Any = Unit.DECIMAL_RATE,
    money_unit: Any = Unit.USD,
    domain: tuple[float, float] = (-0.2, 0.3),
    calculation_id: str = "val-rdcf",
    market_price: Any = None,
    market_price_as_of: Optional[str] = None,
    market_price_source: str = "",
) -> MechanicResult:
    """Solve one unknown: implied_fcf_cagr | implied_terminal_growth | implied_fcf_level."""
    cid, iid = calculation_id, instrument_id
    try:
        var = str(solved_variable).strip().lower()
        w = _rate(wacc, wacc_unit, "wacc") if wacc is not None else None
        g = _rate(terminal_growth, g_unit, "terminal_growth") if terminal_growth is not None else None
        dbt = _usd(debt, money_unit, "debt", required=True)
        csh = _usd(cash, money_unit, "cash", required=True)
        target = float(target_equity_value)
        lo, hi = domain

        def equity_from_flows(flows: list[float], ww: float, gg: float) -> float:
            tv = gordon_tv(flows[-1], ww, gg)
            ev = present_value_fcfs(flows, ww) + tv / ((1.0 + ww) ** len(flows))
            return enterprise_to_equity(enterprise_value=ev, debt=dbt, cash=csh, other_claims=other_claims)

        def build_flows(level: float, cagr: float) -> list[float]:
            return [float(level) * ((1.0 + cagr) ** t) for t in range(1, int(horizon) + 1)]

        def f_of(x: float) -> float:
            if var in ("implied_fcf_cagr", "implied_revenue_cagr"):
                if starting_fcf is None:
                    raise MechanicError(MechanicStatus.UNAVAILABLE, "starting_fcf required to solve growth")
                if w is None or g is None:
                    raise MechanicError(MechanicStatus.UNAVAILABLE, "wacc and terminal_growth must be fixed")
                return equity_from_flows(build_flows(float(starting_fcf), x), w, g) - target
            if var == "implied_terminal_growth":
                if w is None:
                    raise MechanicError(MechanicStatus.UNAVAILABLE, "wacc must be fixed")
                flows = [float(v) for v in (fcfs or [])]
                if not flows:
                    if starting_fcf is None or fcf_growth is None:
                        raise MechanicError(MechanicStatus.UNAVAILABLE, "fcfs or starting_fcf+fcf_growth required")
                    cg = _rate(fcf_growth, g_unit, "fcf_growth")
                    flows = build_flows(float(starting_fcf), cg)
                return equity_from_flows(flows, w, x) - target
            if var in ("implied_fcf_level", "implied_steady_state_fcf"):
                if w is None or g is None:
                    raise MechanicError(MechanicStatus.UNAVAILABLE, "wacc and terminal_growth must be fixed")
                cg = 0.0 if fcf_growth is None else _rate(fcf_growth, g_unit, "fcf_growth")
                return equity_from_flows(build_flows(x, cg), w, g) - target
            raise MechanicError(MechanicStatus.UNSUPPORTED, f"unknown solved_variable {solved_variable!r}")

        # Root count in domain (sample grid + sign changes)
        grid = [lo + (hi - lo) * i / 40.0 for i in range(41)]
        vals = []
        for x in grid:
            try:
                vals.append((x, f_of(x)))
            except MechanicError:
                vals.append((x, math.nan))
        sign_changes = 0
        for (x0, y0), (x1, y1) in zip(vals, vals[1:]):
            if math.isfinite(y0) and math.isfinite(y1) and y0 == 0:
                sign_changes += 1
            elif math.isfinite(y0) and math.isfinite(y1) and y0 * y1 < 0:
                sign_changes += 1
        if sign_changes == 0:
            raise MechanicError(MechanicStatus.UNAVAILABLE, "reverse DCF no root in declared domain")
        if sign_changes > 1:
            raise MechanicError(MechanicStatus.UNAVAILABLE, "multiple roots in domain")
        # Bisect the unique bracket
        a = b = None
        for (x0, y0), (x1, y1) in zip(vals, vals[1:]):
            if math.isfinite(y0) and math.isfinite(y1) and y0 * y1 <= 0:
                a, b = x0, x1
                break
        if a is None:
            raise MechanicError(MechanicStatus.UNAVAILABLE, "reverse DCF no root in declared domain")
        fa, fb = f_of(a), f_of(b)
        mid = a
        it = 0
        for it in range(1, _SOLVER_MAX + 1):
            mid = 0.5 * (a + b)
            fm = f_of(mid)
            if abs(fm) < _SOLVER_TOL or abs(b - a) < _SOLVER_TOL:
                break
            if fa * fm <= 0:
                b, fb = mid, fm
            else:
                a, fa = mid, fm
        residual = f_of(mid)
        if abs(residual) > 1e-6:
            raise MechanicError(MechanicStatus.UNAVAILABLE, f"solver residual too large: {residual}")
        inputs = {
            "wacc": InputDatum("wacc", w, Unit.DECIMAL_RATE, AssumptionClass.ASSUMPTION_INPUT) if w is not None else InputDatum("wacc", None, None, AssumptionClass.ASSUMPTION_INPUT),
            "target_equity_value": InputDatum("target_equity_value", target, Unit.USD, AssumptionClass.VERIFIED_FACT_INPUT, as_of=market_price_as_of, source=market_price_source),
        }
        fixed = {"wacc": w, "terminal_growth": g, "horizon": horizon, "debt": dbt, "cash": csh}
        return _ok(cid, iid, {
            "label": "CONDITIONAL_MODEL_OUTPUT",
            "not": "FINANCIAL_TRUTH",
            "solved_variable": var,
            "solution": mid,
            "root_residual": residual,
            "solver_tolerance": _SOLVER_TOL,
            "iterations": it,
            "assumptions_fixed": fixed,
            "domain": [lo, hi],
            "market_price": None if market_price is None else float(market_price),
            "market_price_as_of": market_price_as_of,
            "market_price_source": market_price_source,
            "authority": AUTHORITY,
        }, inputs, {"model": "explicit_period_gordon"}, assumptions=fixed)
    except MechanicError as err:
        return _fail(cid, iid, err)


def sensitivity_matrix(
    *,
    instrument_id: str,
    fcfs: Sequence[float],
    wacc_grid: Sequence[float],
    g_grid: Sequence[float],
    debt: Any,
    cash: Any,
    other_claims: float = 0.0,
    money_unit: Any = Unit.USD,
    calculation_id: str = "val-sens",
) -> MechanicResult:
    cid, iid = calculation_id, instrument_id
    try:
        flows = [float(x) for x in fcfs]
        dbt = _usd(debt, money_unit, "debt", required=True)
        csh = _usd(cash, money_unit, "cash", required=True)
        rows = []
        prev_row = None
        for w in wacc_grid:
            row = []
            for g in g_grid:
                if float(w) <= float(g):
                    row.append({"wacc": float(w), "g": float(g), "status": "INVALID_INPUT", "equity_value": None})
                    continue
                tv = gordon_tv(flows[-1], float(w), float(g))
                ev = present_value_fcfs(flows, float(w)) + tv / ((1.0 + float(w)) ** len(flows))
                eq = enterprise_to_equity(enterprise_value=ev, debt=dbt, cash=csh, other_claims=other_claims)
                row.append({"wacc": float(w), "g": float(g), "status": "OK", "equity_value": eq})
            rows.append(row)
            prev_row = row
        # Monotonicity: higher WACC (same g) → lower equity when both OK
        mono = True
        for col in range(len(g_grid)):
            last = None
            for r in rows:
                cell = r[col]
                if cell["status"] != "OK":
                    continue
                if last is not None and cell["equity_value"] > last + 1e-6:
                    mono = False
                last = cell["equity_value"]
        inputs = {
            "debt": InputDatum("debt", dbt, Unit.USD, AssumptionClass.VERIFIED_FACT_INPUT),
            "cash": InputDatum("cash", csh, Unit.USD, AssumptionClass.VERIFIED_FACT_INPUT),
        }
        return _ok(cid, iid, {
            "label": "CONDITIONAL_MODEL_OUTPUT",
            "axes": {"wacc": [float(x) for x in wacc_grid], "terminal_growth": [float(x) for x in g_grid]},
            "cells": rows,
            "higher_wacc_lowers_equity": mono,
            "authority": AUTHORITY,
        }, inputs, {"pair": "discount_rate_x_terminal_growth"}, assumptions={"model": "same_as_dcf"})
    except MechanicError as err:
        return _fail(cid, iid, err)
