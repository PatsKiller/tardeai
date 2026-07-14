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
from lib.redeploy_income import income_snapshot
from lib.redeploy_price_history import (
    annualized_vol_pct,
    get_instrument_facts,
    load_closes,
    load_dividends,
    series_profile,
)

ENGINE_VERSION = "performance_1.2.0"


def trailing_yield_pct(cur, symbol: str) -> float | None:
    """DEPRECATED — use lib.redeploy_income.income_snapshot (canonical income model).

    Kept only for backward compatibility of older callers.
    Trailing-12M distributions / latest close."""
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
    # Canonical income model (defect map #8/#9). Legacy fields
    # distribution_yield_pct / yield_basis are kept for backward compat.
    snap = income_snapshot(cur, [symbol]).get(symbol.upper()) or {}
    prof["income"] = snap or None
    dy = snap.get("yield_pct")
    if snap.get("yield_type") == "trailing_distribution":
        prof["yield_basis"] = "trailing_12m_distributions / latest close (computed)"
    elif snap.get("yield_type") == "indicated":
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
    """Plan-level scenario matrix — every row states its kind, methodology and
    coverage; no fabrication (defect map 2026-07-14 #10/#11).

    kinds: STATISTICAL_BAND (±1σ realized-vol shock — NOT a forecast) ·
    DETERMINISTIC_SHOCK (stated shock × measured sensitivity; legacy_kind
    DETERMINISTIC_MODEL) · HISTORICAL_OBSERVATION (realized window return) ·
    UNAVAILABLE (required data missing). Cash reserve counts 0% nominal for
    market-shock rows, but risky-leg coverage is tracked separately: a row
    backed ONLY by the reserve is UNAVAILABLE, never 0%. `legacy_key` /
    `legacy_kind` preserve the pre-rename identifiers for old consumers."""
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

    band_method = ("±1σ annualized shock from realized 1Y daily volatility, zero drift, "
                   "distributions excluded — a statistical band, NOT a return forecast")
    beta_method = "stated market shock × measured 1Y beta vs SPY (fallback: 3Y factsheet beta)"
    hist_method = ("realized price return over the stated historical window, for each leg "
                   "whose price history covers it")
    rows = [
        {"key": "plus_1_sigma", "legacy_key": "bull_1y",
         "kind": "STATISTICAL_BAND", "legacy_kind": "FORECAST",
         "label": "+1σ statistical shock (1Y realized vol, zero drift — NOT a forecast)",
         "methodology": band_method, "date_range": None,
         "fn": lambda p, f: p.get("volatility_1y_pct")},
        {"key": "zero_drift_reference", "legacy_key": "base_1y",
         "kind": "STATISTICAL_BAND", "legacy_kind": "FORECAST",
         "label": "Zero-drift reference (midpoint of ±1σ band — NOT a base-case forecast)",
         "methodology": band_method, "date_range": None,
         "fn": lambda p, f: 0.0 if p.get("volatility_1y_pct") is not None else None},
        {"key": "minus_1_sigma", "legacy_key": "bear_1y",
         "kind": "STATISTICAL_BAND", "legacy_kind": "FORECAST",
         "label": "−1σ statistical shock (1Y realized vol, zero drift — NOT a forecast)",
         "methodology": band_method, "date_range": None,
         "fn": lambda p, f: -p["volatility_1y_pct"] if p.get("volatility_1y_pct") is not None else None},
        {"key": "equity_drawdown_20", "legacy_key": "equity_drawdown_20",
         "kind": "DETERMINISTIC_SHOCK", "legacy_kind": "DETERMINISTIC_MODEL",
         "label": "Equity drawdown −20% — measured 1Y beta × −20% market shock",
         "methodology": beta_method, "date_range": None,
         "fn": lambda p, f: round(-20.0 * beta_of(p, f), 2) if beta_of(p, f) is not None else None},
        {"key": "tech_selloff_25", "legacy_key": "tech_selloff_25",
         "kind": "DETERMINISTIC_SHOCK", "legacy_kind": "DETERMINISTIC_MODEL",
         "label": "Technology selloff −25% — look-through technology weight × −25%; other sectors flat",
         "methodology": "look-through technology weight × −25% sector shock; other sectors flat",
         "date_range": None,
         "fn": lambda p, f: (round(-25.0 * _tech_weight(f), 2) if _tech_weight(f) is not None else None)},
        {"key": "rate_shock_2022", "legacy_key": "rate_shock_2022",
         "kind": "HISTORICAL_OBSERVATION", "legacy_kind": "HISTORICAL_OBSERVATION",
         "label": "Rate shock — realized 2022-01-03 → 2022-10-12 (Fed +300bp cycle)",
         "methodology": hist_method, "date_range": "2022-01-03 → 2022-10-12",
         "fn": lambda p, f: _stress_pct(p, "rate_shock_2022")},
        {"key": "inflation_shock_2022", "legacy_key": "inflation_shock_2022",
         "kind": "HISTORICAL_OBSERVATION", "legacy_kind": "HISTORICAL_OBSERVATION",
         "label": "Inflation shock — realized 2022 window (CPI 9.1% peak); note: 2022 combined the "
                  "rate and inflation shocks — separate attribution is unavailable, not fabricated",
         "methodology": hist_method, "date_range": "2022-01-03 → 2022-10-12",
         "fn": lambda p, f: _stress_pct(p, "rate_shock_2022")},
        {"key": "recession_2020", "legacy_key": "recession_2020",
         "kind": "HISTORICAL_OBSERVATION", "legacy_kind": "HISTORICAL_OBSERVATION",
         "label": "Recession — realized COVID crash 2020-02-19 → 2020-03-23",
         "methodology": hist_method, "date_range": "2020-02-19 → 2020-03-23",
         "fn": lambda p, f: _stress_pct(p, "covid_2020")},
        {"key": "geopolitical_2022", "legacy_key": "geopolitical_2022",
         "kind": "HISTORICAL_OBSERVATION", "legacy_kind": "HISTORICAL_OBSERVATION",
         "label": "Geopolitical escalation — realized Russia-Ukraine invasion window 2022-02-18 → 2022-03-14",
         "methodology": hist_method, "date_range": "2022-02-18 → 2022-03-14",
         "fn": lambda p, f: _stress_pct(p, "geopolitical_2022")},
        {"key": "regime_transition", "legacy_key": "regime_transition",
         "kind": "DETERMINISTIC_SHOCK", "legacy_kind": "DETERMINISTIC_MODEL",
         "label": f"Regime transition — measured 1Y beta × −10% regime-break shock (current regime: {regime or 'unknown'})",
         "methodology": "−10% regime-break shock × measured 1Y beta vs SPY (fallback: 3Y factsheet beta)",
         "date_range": None,
         "fn": lambda p, f: round(-10.0 * beta_of(p, f), 2) if beta_of(p, f) is not None else None},
    ]

    risky_total = sum(_as_float(l.get("target_dollars")) for l in plan_legs
                      if not l.get("is_reserve") and _as_float(l.get("target_dollars")) > 0)

    out = []
    for r in rows:
        acc, covered, risky_covered = 0.0, 0.0, 0.0
        for leg in plan_legs:
            pct_val, dollars = leg_value(leg, r["fn"])
            if pct_val is not None and dollars > 0:
                acc += dollars * pct_val
                covered += dollars
                if not leg.get("is_reserve"):
                    risky_covered += dollars
        # defect #11: reserve-only coverage must never render a 0% plan number
        risky_unavailable = risky_total > 0 and risky_covered <= 0
        unavailable = covered <= 0 or risky_unavailable
        if covered <= 0:
            note = "no leg has the data this scenario needs — reported unavailable, never zero"
        elif risky_unavailable:
            note = "UNAVAILABLE FOR RISKY LEGS — reserve-only coverage; not zero"
        else:
            note = None
        out.append({
            "key": r["key"], "legacy_key": r["legacy_key"],
            "kind": "UNAVAILABLE" if unavailable else r["kind"],
            "legacy_kind": r["legacy_kind"],
            "label": r["label"],
            "methodology": r["methodology"],
            "date_range": r["date_range"],
            "income_included": False,
            "plan_pct": round(acc / covered, 2) if not unavailable else None,
            "coverage_pct_of_plan": round(covered / total * 100.0, 1),
            "risky_coverage_pct_of_invested": (
                round(risky_covered / risky_total * 100.0, 1) if risky_total > 0 else None
            ),
            "unavailable": unavailable,
            "note": note,
        })
    return out


def plan_performance(cur, event: dict[str, Any], plan_legs: list[dict[str, Any]],
                     *, bench_symbol: str = "SPY") -> dict[str, Any]:
    """Per-leg detail + TWO plan-level views (defect map #7):

    invested_sleeve — non-reserve legs only (what the legacy plan_weighted was);
    whole_plan      — all legs incl. reserve: reserve contributes 0% return /
                      0 expense and its vehicle yield when determinable.
    Income everywhere comes from the canonical lib.redeploy_income model (#8/#9).
    """
    sold = str(event.get("symbol") or "").upper() or None
    legs_out = []
    invested_alloc = 0.0
    reserve_alloc = 0.0
    weighted = {"1Y": 0.0, "3Y": 0.0, "5Y": 0.0}
    weight_cov = {"1Y": 0.0, "3Y": 0.0, "5Y": 0.0}
    weighted_yield, yield_cov = 0.0, 0.0
    weighted_er, er_cov = 0.0, 0.0
    income_by_leg: list[dict[str, Any]] = []
    invested_income_usd = 0.0          # $/yr from invested legs with a known yield
    reserve_income_usd = 0.0           # $/yr from reserve vehicles with a known yield
    reserve_yield_cov = 0.0            # reserve dollars whose vehicle yield is determinable
    reserve_yield_notes: list[str] = []

    for leg in plan_legs:
        dollars = _as_float(leg.get("target_dollars"))
        if leg.get("is_reserve"):
            reserve_alloc += dollars
            vehicle = str(leg.get("ticker") or "").upper()
            snap = (income_snapshot(cur, [vehicle]).get(vehicle) if vehicle else None) or {}
            # canonical snapshot first (cross-tab consistency), live snapshot as fallback
            r_yield = leg.get("expected_yield_pct") if "expected_yield_pct" in leg \
                else snap.get("yield_pct")
            # canonical basis: yield is credited only on the MODELED vehicle position
            # (whole shares), exactly as the plan engine does — the sweep remainder
            # earns 0% (this was the $28 cross-tab income drift, P2-7)
            yield_dollars = dollars
            if leg.get("reserve_vehicle_dollars") is not None:
                yield_dollars = _as_float(leg.get("reserve_vehicle_dollars"))
            if r_yield is not None and yield_dollars > 0:
                reserve_income_usd += yield_dollars * r_yield / 100.0
                reserve_yield_cov += yield_dollars
            elif dollars > 0:
                reserve_yield_notes.append(
                    f"{vehicle or 'reserve'}: reserve vehicle yield unavailable — contributes at 0%")
            legs_out.append({"ticker": "CASH_RESERVE",
                             "reserve_vehicle": vehicle or None,
                             "target_dollars": dollars,
                             "income": snap or None,
                             "note": "reserve leg — no market performance"})
            income_by_leg.append({
                "ticker": vehicle or "CASH_RESERVE", "is_reserve": True,
                "target_dollars": dollars,
                "yield_pct": r_yield,
                "yield_type": snap.get("yield_type") or "unavailable",
                "income_status": snap.get("income_status") or "UNAVAILABLE",
                "expected_annual_income_usd": (
                    round(dollars * r_yield / 100.0, 2) if r_yield is not None else None
                ),
                "note": None if r_yield is not None else "reserve vehicle yield unavailable",
            })
            continue
        sym = str(leg.get("ticker") or "").upper()
        perf = leg_performance(cur, sym, sold_symbol=sold, bench_symbol=bench_symbol)
        perf["target_dollars"] = dollars
        legs_out.append(perf)
        invested_alloc += dollars
        basis = perf.get("total_return") or perf.get("price_return") or {}
        for win in ("1Y", "3Y", "5Y"):
            w = basis.get(win)
            if w and w.get("pct") is not None:
                weighted[win] += dollars * w["pct"]
                weight_cov[win] += dollars
        # cross-tab consistency (Phase 1): prefer the yield pinned into the leg at plan
        # generation (the canonical snapshot Plan Lab shows) over a re-read that can
        # drift with the latest close; provenance stays in perf["income"].
        if "expected_yield_pct" in leg:
            # canonical: use the generation snapshot VERBATIM (a None stays None so this
            # tab shows exactly what Plan Lab shows; provenance remains in perf["income"])
            leg_yield = leg.get("expected_yield_pct")
            if leg_yield is not None:
                perf["yield_basis"] = "plan-generation snapshot (canonical across tabs)"
                perf["distribution_yield_pct"] = leg_yield
        else:
            leg_yield = perf.get("distribution_yield_pct")
        if leg_yield is not None:
            weighted_yield += dollars * leg_yield
            yield_cov += dollars
            invested_income_usd += dollars * leg_yield / 100.0
        if perf.get("expense_ratio_pct") is not None:
            weighted_er += dollars * perf["expense_ratio_pct"]
            er_cov += dollars
        snap = perf.get("income") or {}
        income_by_leg.append({
            "ticker": sym, "is_reserve": False,
            "target_dollars": dollars,
            "yield_pct": leg_yield,
            "yield_type": snap.get("yield_type") or "unavailable",
            "income_status": snap.get("income_status") or "UNAVAILABLE",
            "expected_annual_income_usd": (
                round(dollars * leg_yield / 100.0, 2) if leg_yield is not None else None
            ),
            "note": snap.get("recurring_income_note"),
        })

    total_plan = invested_alloc + reserve_alloc
    total_alloc = invested_alloc  # legacy name: invested sleeve only

    sold_perf = series_profile(cur, sold, bench_symbol=bench_symbol) if sold else None
    sold_income = (income_snapshot(cur, [sold]).get(sold) if sold else None) or None
    sold_facts = get_instrument_facts(cur, [sold]).get(sold, {}) if sold else {}

    leg_syms = [str(l.get("ticker") or "").upper() for l in plan_legs if not l.get("is_reserve")]
    facts_map = get_instrument_facts(cur, leg_syms) if leg_syms else {}
    profiles = {p.get("symbol"): p for p in legs_out if p.get("symbol")}
    scenarios = plan_scenarios(cur, plan_legs, profiles, facts_map)

    plan_yield = round(weighted_yield / yield_cov, 2) if yield_cov > 0 else None

    invested_return_windows = {
        win: {
            "pct": round(weighted[win] / weight_cov[win], 2),
            "coverage_pct_of_allocation": round(weight_cov[win] / total_alloc * 100.0, 1),
        } if weight_cov[win] > 0 and total_alloc > 0 else None
        for win in ("1Y", "3Y", "5Y")
    }
    # whole plan: reserve is covered at 0% return; but a window with NO risky-leg
    # data stays None (reserve-only coverage is not a 0% plan return)
    whole_return_windows = {
        win: {
            "pct": round(weighted[win] / (weight_cov[win] + reserve_alloc), 2),
            "coverage_pct_of_plan": round(
                (weight_cov[win] + reserve_alloc) / total_plan * 100.0, 1),
        } if (weight_cov[win] > 0 or invested_alloc <= 0) and total_plan > 0 else None
        for win in ("1Y", "3Y", "5Y")
    }
    whole_plan_income_usd = invested_income_usd + reserve_income_usd
    whole_plan_yield = (
        round(whole_plan_income_usd / total_plan * 100.0, 2) if total_plan > 0 else None
    )
    yield_coverage_pct = (
        round((yield_cov + reserve_yield_cov) / total_plan * 100.0, 1) if total_plan > 0 else None
    )
    invested_income = round(invested_income_usd, 2) if yield_cov > 0 else None

    plan_weighted = {
        "return_windows": invested_return_windows,
        "yield_pct": plan_yield,
        "expected_annual_income_usd": invested_income,
        "expense_ratio_pct": round(weighted_er / er_cov, 3) if er_cov > 0 else None,
        "note": ("INVESTED SLEEVE ONLY — dollar-weighted across non-reserve legs with data; "
                 "see whole_plan for the view including the reserve; coverage shows how much "
                 "of the invested allocation each number represents"),
    }
    return {
        "ok": True,
        "advisory_only": True,
        "engine_version": ENGINE_VERSION,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "benchmark": bench_symbol,
        "scenarios": scenarios,
        "scenario_kinds_note": ("STATISTICAL_BAND = ±1σ realized-vol shock (NOT a forecast); "
                                "DETERMINISTIC_SHOCK = stated shock × measured sensitivity; "
                                "HISTORICAL_OBSERVATION = realized window return; "
                                "UNAVAILABLE = required data missing. Every row reports plan "
                                "coverage AND risky-leg coverage; missing data is 'unavailable', "
                                "never zero. legacy_key/legacy_kind carry the pre-rename ids."),
        "legs": legs_out,
        # DEPRECATED alias of invested_sleeve — kept for backward compatibility.
        "plan_weighted": plan_weighted,
        "invested_sleeve": {
            "pct_of_plan": round(invested_alloc / total_plan * 100.0, 1) if total_plan > 0 else None,
            "return_windows": invested_return_windows,
            "yield_pct": plan_yield,
            "expense_ratio_pct": plan_weighted["expense_ratio_pct"],
            "expected_annual_income_usd": invested_income,
        },
        "whole_plan": {
            "pct_of_plan": 100.0,
            "return_windows": whole_return_windows,
            "yield_pct": whole_plan_yield,
            "expense_ratio_pct": (
                round(weighted_er / (er_cov + reserve_alloc), 3)
                if (er_cov + reserve_alloc) > 0 else None
            ),
            "expected_annual_income_usd": (
                round(whole_plan_income_usd, 2) if total_plan > 0 else None
            ),
            "coverage": {
                "invested_pct": round(invested_alloc / total_plan * 100.0, 1) if total_plan > 0 else None,
                "reserve_pct": round(reserve_alloc / total_plan * 100.0, 1) if total_plan > 0 else None,
                "return_coverage_pct": (
                    round((weight_cov["1Y"] + reserve_alloc) / total_plan * 100.0, 1)
                    if total_plan > 0 else None
                ),
                "yield_coverage_pct": yield_coverage_pct,
            },
            "reserve_yield_notes": reserve_yield_notes or None,
            "note": ("ALL legs incl. reserve — reserve contributes 0% return / 0 expense and "
                     "its vehicle yield when determinable (0% with a note otherwise)"),
        },
        "plan_income": {
            "expected_annual_income_usd": (
                round(whole_plan_income_usd, 2) if total_plan > 0 else None
            ),
            "income_by_leg": income_by_leg,
            "calculation_as_of": datetime.now(timezone.utc).isoformat(),
            "coverage_pct": yield_coverage_pct,
        },
        "sold_reference": {
            "symbol": sold,
            "profile": sold_perf,
            # legacy field (kept): canonical value now comes from income_snapshot
            "trailing_yield_pct": (sold_income or {}).get("trailing_distribution_yield_pct"),
            "expense_ratio_pct": sold_facts.get("expense_ratio_pct"),
            "income": sold_income,
        } if sold else None,
    }
