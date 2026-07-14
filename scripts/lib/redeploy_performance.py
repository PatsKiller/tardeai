"""redeploy_performance — plan/leg performance + scenarios vs sold fund (Part E).

Everything is computed from the local 5y cache (ticker_prices/ticker_dividends/
instrument_facts). Forecast scenarios are clearly labeled forecasts derived from
realized volatility; historical stress numbers are observations. Price return
and total return are separate fields throughout. Advisory only.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from lib.redeploy_data_truth import _as_float
from lib.redeploy_price_history import (
    annualized_vol_pct,
    get_instrument_facts,
    load_closes,
    load_dividends,
    series_profile,
)

ENGINE_VERSION = "performance_1.0.0"


def trailing_yield_pct(cur, symbol: str) -> float | None:
    """Trailing-12M distributions / latest close — fallback when facts yield is absent/zero."""
    closes = load_closes(cur, symbol, days=30)
    if not closes or closes[-1][1] <= 0:
        return None
    divs = load_dividends(cur, symbol, days=370)
    if not divs:
        return None
    return round(sum(a for _, a in divs) / closes[-1][1] * 100.0, 2)


def leg_performance(cur, symbol: str, *, sold_symbol: str | None,
                    bench_symbol: str = "SPY") -> dict[str, Any]:
    prof = series_profile(cur, symbol, bench_symbol=bench_symbol)
    facts = get_instrument_facts(cur, [symbol]).get(symbol.upper(), {})
    dy = facts.get("distribution_yield_pct")
    if not dy:
        dy = trailing_yield_pct(cur, symbol)
        if dy is not None:
            prof["yield_basis"] = "trailing_12m_distributions / latest close (computed)"
    else:
        prof["yield_basis"] = "instrument_facts (yfinance)"
    prof["distribution_yield_pct"] = dy
    prof["expense_ratio_pct"] = facts.get("expense_ratio_pct")

    vol = prof.get("volatility_1y_pct")
    last_px = None
    closes = load_closes(cur, symbol, days=10)
    if closes:
        last_px = closes[-1][1]
    if vol is not None and last_px:
        # FORECAST (not history): ±1σ annual band around flat drift, from realized 1y vol.
        prof["scenarios_1y_forecast"] = {
            "basis": "±1σ from realized 1Y volatility, zero drift — a FORECAST, not history",
            "bear_pct": round(-vol, 2),
            "base_pct": 0.0,
            "bull_pct": round(vol, 2),
        }
    if sold_symbol and sold_symbol.upper() != symbol.upper():
        sold_prof = series_profile(cur, sold_symbol, bench_symbol=bench_symbol)
        cmp_rows = {}
        for win in ("1Y", "3Y", "5Y"):
            a = ((prof.get("total_return") or prof.get("price_return") or {}).get(win) or {})
            b = ((sold_prof.get("total_return") or sold_prof.get("price_return") or {}).get(win) or {})
            if a.get("pct") is not None and b.get("pct") is not None:
                cmp_rows[win] = {
                    "this_pct": a["pct"], "sold_pct": b["pct"],
                    "excess_pct_pts": round(a["pct"] - b["pct"], 2),
                }
        prof["vs_sold"] = {
            "sold_symbol": sold_symbol.upper(),
            "windows": cmp_rows or None,
            "return_basis": ("total_return where distribution history exists, "
                             "price_return otherwise — see each side's basis fields"),
        }
    return prof


def plan_performance(cur, event: dict[str, Any], plan_legs: list[dict[str, Any]],
                     *, bench_symbol: str = "SPY") -> dict[str, Any]:
    """Weighted plan-level view + per-leg detail."""
    sold = str(event.get("symbol") or "").upper() or None
    legs_out = []
    total_alloc = 0.0
    weighted = {"1Y": 0.0, "3Y": 0.0, "5Y": 0.0}
    weight_cov = {"1Y": 0.0, "3Y": 0.0, "5Y": 0.0}
    weighted_yield, yield_cov = 0.0, 0.0
    weighted_er, er_cov = 0.0, 0.0

    for leg in plan_legs:
        if leg.get("is_reserve"):
            legs_out.append({"ticker": "CASH_RESERVE",
                             "target_dollars": _as_float(leg.get("target_dollars")),
                             "note": "reserve leg — no market performance"})
            continue
        sym = str(leg.get("ticker") or "").upper()
        dollars = _as_float(leg.get("target_dollars"))
        perf = leg_performance(cur, sym, sold_symbol=sold, bench_symbol=bench_symbol)
        perf["target_dollars"] = dollars
        legs_out.append(perf)
        total_alloc += dollars
        basis = perf.get("total_return") or perf.get("price_return") or {}
        for win in ("1Y", "3Y", "5Y"):
            w = basis.get(win)
            if w and w.get("pct") is not None:
                weighted[win] += dollars * w["pct"]
                weight_cov[win] += dollars
        if perf.get("distribution_yield_pct") is not None:
            weighted_yield += dollars * perf["distribution_yield_pct"]
            yield_cov += dollars
        if perf.get("expense_ratio_pct") is not None:
            weighted_er += dollars * perf["expense_ratio_pct"]
            er_cov += dollars

    sold_perf = series_profile(cur, sold, bench_symbol=bench_symbol) if sold else None
    sold_yield = trailing_yield_pct(cur, sold) if sold else None
    sold_facts = get_instrument_facts(cur, [sold]).get(sold, {}) if sold else {}

    plan_yield = round(weighted_yield / yield_cov, 2) if yield_cov > 0 else None
    return {
        "ok": True,
        "advisory_only": True,
        "engine_version": ENGINE_VERSION,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "benchmark": bench_symbol,
        "legs": legs_out,
        "plan_weighted": {
            "return_windows": {
                win: {
                    "pct": round(weighted[win] / weight_cov[win], 2),
                    "coverage_pct_of_allocation": round(weight_cov[win] / total_alloc * 100.0, 1),
                } if weight_cov[win] > 0 else None
                for win in ("1Y", "3Y", "5Y")
            },
            "yield_pct": plan_yield,
            "expected_annual_income_usd": (
                round(total_alloc * plan_yield / 100.0, 2) if plan_yield is not None else None
            ),
            "expense_ratio_pct": round(weighted_er / er_cov, 3) if er_cov > 0 else None,
            "note": "dollar-weighted across legs with data; coverage shows how much of the allocation each number represents",
        },
        "sold_reference": {
            "symbol": sold,
            "profile": sold_perf,
            "trailing_yield_pct": sold_yield,
            "expense_ratio_pct": sold_facts.get("expense_ratio_pct"),
        } if sold else None,
    }
