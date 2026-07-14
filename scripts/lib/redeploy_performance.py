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

ENGINE_VERSION = "performance_1.1.0"


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


def _stress_pct(prof: dict[str, Any], key: str) -> float | None:
    for w in (prof.get("stress") or []):
        if w.get("key") == key and w.get("history_available"):
            return w.get("pct")
    return None


def _tech_weight(facts: dict[str, Any]) -> float | None:
    """Look-through technology weight 0..1; None (never 0) when unknown."""
    sw = facts.get("sector_weights")
    if isinstance(sw, dict) and sw:
        for k, v in sw.items():
            if "tech" in str(k).lower():
                try:
                    x = float(v)
                    return x / 100.0 if x > 1.5 else x
                except (TypeError, ValueError):
                    return None
        return 0.0  # weights known, technology genuinely absent
    cat = str(facts.get("category") or "").lower()
    if "technology" in cat:
        return 1.0
    return None


def plan_scenarios(cur, plan_legs: list[dict[str, Any]], leg_profiles: dict[str, dict[str, Any]],
                   facts_map: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Plan-level scenario matrix — every row states its kind and coverage; no fabrication.

    kinds: FORECAST (vol-derived band) · DETERMINISTIC_MODEL (stated shock × measured
    sensitivity) · HISTORICAL_OBSERVATION (realized window return) · each with the % of
    plan dollars its number actually covers. Cash reserve counts as 0% nominal for
    market-shock rows (noted where that is itself an assumption, e.g. inflation)."""
    regime = None
    try:
        cur.execute("SELECT regime_label FROM market_regime_snapshots ORDER BY created_at DESC LIMIT 1")
        row = cur.fetchone()
        regime = str(row[0]) if row else None
    except Exception:
        pass

    total = sum(_as_float(l.get("target_dollars")) for l in plan_legs)
    if total <= 0:
        return []

    def leg_value(leg, kind_fn):
        """(pct, covered_dollars) for one leg under one scenario; (None, 0) when unknowable."""
        dollars = _as_float(leg.get("target_dollars"))
        if leg.get("is_reserve"):
            return 0.0, dollars  # nominal cash
        prof = leg_profiles.get(str(leg.get("ticker") or "").upper()) or {}
        facts = facts_map.get(str(leg.get("ticker") or "").upper()) or {}
        pct_val = kind_fn(prof, facts)
        return (pct_val, dollars) if pct_val is not None else (None, 0.0)

    def beta_of(prof, facts):
        b = prof.get("beta_1y_vs_spy")
        return b if b is not None else facts.get("beta_3y")

    rows = [
        {"key": "bull_1y", "kind": "FORECAST",
         "label": "Bull case (1Y) — +1σ realized volatility, zero drift, distributions excluded",
         "fn": lambda p, f: p.get("volatility_1y_pct")},
        {"key": "base_1y", "kind": "FORECAST",
         "label": "Base case (1Y) — zero drift; realized-vol band midpoint, distributions excluded",
         "fn": lambda p, f: 0.0 if p.get("volatility_1y_pct") is not None else None},
        {"key": "bear_1y", "kind": "FORECAST",
         "label": "Bear case (1Y) — −1σ realized volatility, zero drift, distributions excluded",
         "fn": lambda p, f: -p["volatility_1y_pct"] if p.get("volatility_1y_pct") is not None else None},
        {"key": "equity_drawdown_20", "kind": "DETERMINISTIC_MODEL",
         "label": "Equity drawdown −20% — measured 1Y beta × −20% market shock",
         "fn": lambda p, f: round(-20.0 * beta_of(p, f), 2) if beta_of(p, f) is not None else None},
        {"key": "tech_selloff_25", "kind": "DETERMINISTIC_MODEL",
         "label": "Technology selloff −25% — look-through technology weight × −25%; other sectors flat",
         "fn": lambda p, f: (round(-25.0 * _tech_weight(f), 2) if _tech_weight(f) is not None else None)},
        {"key": "rate_shock_2022", "kind": "HISTORICAL_OBSERVATION",
         "label": "Rate shock — realized 2022-01-03 → 2022-10-12 (Fed +300bp cycle)",
         "fn": lambda p, f: _stress_pct(p, "rate_shock_2022")},
        {"key": "inflation_shock_2022", "kind": "HISTORICAL_OBSERVATION",
         "label": "Inflation shock — realized 2022 window (CPI 9.1% peak); note: 2022 combined the "
                  "rate and inflation shocks — separate attribution is unavailable, not fabricated",
         "fn": lambda p, f: _stress_pct(p, "rate_shock_2022")},
        {"key": "recession_2020", "kind": "HISTORICAL_OBSERVATION",
         "label": "Recession — realized COVID crash 2020-02-19 → 2020-03-23",
         "fn": lambda p, f: _stress_pct(p, "covid_2020")},
        {"key": "geopolitical_2022", "kind": "HISTORICAL_OBSERVATION",
         "label": "Geopolitical escalation — realized Russia-Ukraine invasion window 2022-02-18 → 2022-03-14",
         "fn": lambda p, f: _stress_pct(p, "geopolitical_2022")},
        {"key": "regime_transition", "kind": "DETERMINISTIC_MODEL",
         "label": f"Regime transition — measured 1Y beta × −10% regime-break shock (current regime: {regime or 'unknown'})",
         "fn": lambda p, f: round(-10.0 * beta_of(p, f), 2) if beta_of(p, f) is not None else None},
    ]

    out = []
    for r in rows:
        acc, covered = 0.0, 0.0
        for leg in plan_legs:
            pct_val, dollars = leg_value(leg, r["fn"])
            if pct_val is not None and dollars > 0:
                acc += dollars * pct_val
                covered += dollars
        out.append({
            "key": r["key"], "kind": r["kind"], "label": r["label"],
            "plan_pct": round(acc / covered, 2) if covered > 0 else None,
            "coverage_pct_of_plan": round(covered / total * 100.0, 1),
            "unavailable": covered == 0,
            "note": None if covered > 0 else "no leg has the data this scenario needs — reported unavailable, never zero",
        })
    return out


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

    leg_syms = [str(l.get("ticker") or "").upper() for l in plan_legs if not l.get("is_reserve")]
    facts_map = get_instrument_facts(cur, leg_syms) if leg_syms else {}
    profiles = {p.get("symbol"): p for p in legs_out if p.get("symbol")}
    scenarios = plan_scenarios(cur, plan_legs, profiles, facts_map)

    plan_yield = round(weighted_yield / yield_cov, 2) if yield_cov > 0 else None
    return {
        "ok": True,
        "advisory_only": True,
        "engine_version": ENGINE_VERSION,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "benchmark": bench_symbol,
        "scenarios": scenarios,
        "scenario_kinds_note": ("FORECAST = vol-derived band; DETERMINISTIC_MODEL = stated shock × "
                                "measured sensitivity; HISTORICAL_OBSERVATION = realized window return. "
                                "Every row reports the % of plan dollars it covers; missing data is "
                                "'unavailable', never zero."),
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
