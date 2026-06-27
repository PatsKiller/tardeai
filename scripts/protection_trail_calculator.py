#!/usr/bin/env python3
"""Compute Alpaca trailing_stop trail_percent for protection adjustments.

Hybrid industry-standard method (operator-selected):
  trail% = clamp(max(strategy-family base %, ATR14% × family ATR multiplier), 2–12%)

R-multiple gate (family thresholds from backtest_profit_protection_rules):
  momentum ≥1.5R · swing ≥2R · income/position ≥3R · unknown ≥2R

Computed at proposal generation; re-validated at apply time.
"""
from __future__ import annotations

from datetime import datetime, timezone

# Whole-percent bases — aligned with backtest_profit_protection_rules family trails
FAMILY_BASE_PCT: dict[str, float] = {
    "momentum": 3.0,
    "swing": 5.0,
    "income": 8.0,
    "position": 8.0,
    "unknown": 5.0,
}
FAMILY_MIN_R: dict[str, float] = {
    "momentum": 1.5,
    "swing": 2.0,
    "income": 3.0,
    "position": 3.0,
    "unknown": 2.0,
}
# ATR multipliers — aligned with config/stop_trailing_hybrid.yaml base_atr_mult
FAMILY_ATR_MULT: dict[str, float] = {
    "momentum": 2.5,
    "swing": 3.0,
    "income": 3.5,
    "position": 4.0,
    "unknown": 3.0,
}
TRAIL_PCT_MIN = 2.0
TRAIL_PCT_MAX = 12.0
# At apply time: if live recompute drifts > this from stored value, use live (quote moved)
MAX_STORED_DRIFT_PCT = 15.0


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def r_multiple(
    entry_price: float | None,
    planned_stop: float | None,
    current_price: float | None,
    current_stop: float | None = None,
) -> float | None:
    if not entry_price or not current_price:
        return None
    risk_stop = None
    if planned_stop is not None and float(entry_price) - float(planned_stop) > 0:
        risk_stop = float(planned_stop)
    elif current_stop is not None and float(entry_price) - float(current_stop) > 0:
        risk_stop = float(current_stop)
    if risk_stop is None:
        return None
    risk = float(entry_price) - risk_stop
    return round((float(current_price) - float(entry_price)) / risk, 2)


def fetch_atr14(symbol: str) -> float | None:
    try:
        from strategy_trailing_policy import _structural_levels
        cfg = {"atr_period": 14, "chandelier_lookback": 22}
        lv = _structural_levels((symbol or "").upper(), cfg)
        if lv and lv.get("atr"):
            return float(lv["atr"])
    except Exception:
        pass
    return None


def compute_trail_percent(
    strategy_id: str | None,
    symbol: str | None,
    entry_price: float | None,
    planned_stop: float | None,
    current_price: float | None,
    *,
    current_stop: float | None = None,
) -> dict:
    """Return eligibility + trail_percent + audit metadata for evidence_refs."""
    from strategy_trailing_policy import get_strategy_family

    sym = (symbol or "").upper()
    family = get_strategy_family(strategy_id or "")
    r_mult = r_multiple(entry_price, planned_stop, current_price, current_stop=current_stop)
    min_r = FAMILY_MIN_R.get(family, FAMILY_MIN_R["unknown"])
    base = {
        "trail_method": "hybrid",
        "trail_family": family,
        "strategy_id": strategy_id,
        "symbol": sym,
        "r_multiple": r_mult,
        "r_threshold": min_r,
        "entry_price": entry_price,
        "planned_stop": planned_stop,
        "current_stop": current_stop,
        "current_price": current_price,
        "computed_at": datetime.now(timezone.utc).isoformat()[:19],
    }
    if not current_price or float(current_price) <= 0:
        return {**base, "eligible": False, "reason": "no_current_price"}
    if r_mult is None:
        return {**base, "eligible": False, "reason": "invalid_risk_definition"}
    if r_mult < min_r:
        return {
            **base,
            "eligible": False,
            "reason": f"R={r_mult} below {min_r} threshold for {family}",
        }

    family_base = FAMILY_BASE_PCT.get(family, FAMILY_BASE_PCT["unknown"])
    atr_mult = FAMILY_ATR_MULT.get(family, FAMILY_ATR_MULT["unknown"])
    atr = fetch_atr14(sym)
    atr_component = None
    atr_pct = None
    if atr and atr > 0:
        atr_pct = round(atr / float(current_price) * 100, 2)
        atr_component = round(atr_mult * atr / float(current_price) * 100, 2)

    if atr_component is not None:
        raw = max(family_base, atr_component)
    else:
        raw = family_base

    trail_pct = round(_clamp(raw, TRAIL_PCT_MIN, TRAIL_PCT_MAX), 2)
    return {
        **base,
        "eligible": True,
        "trail_percent": trail_pct,
        "family_base_pct": family_base,
        "atr14": atr,
        "atr_pct": atr_pct,
        "atr_mult": atr_mult,
        "atr_component_pct": atr_component,
        "reason": (
            f"hybrid max({family_base}% family, {atr_component or 'n/a'}% ATR) "
            f"→ {trail_pct}% at R={r_mult}"
        ),
    }


def resolve_trail_percent_for_apply(
    stored: dict | None,
    strategy_id: str | None,
    symbol: str | None,
    entry_price: float | None,
    planned_stop: float | None,
    current_price: float | None,
    current_stop: float | None = None,
) -> dict:
    """Recompute at apply time; prefer stored value if live drift is small."""
    live = compute_trail_percent(
        strategy_id, symbol, entry_price, planned_stop, current_price, current_stop=current_stop,
    )
    if not live.get("eligible"):
        return live
    stored_pct = None
    if isinstance(stored, dict):
        try:
            stored_pct = float(stored.get("trail_percent"))
        except (TypeError, ValueError):
            stored_pct = None
    if stored_pct is None:
        return live
    live_pct = float(live["trail_percent"])
    if stored_pct <= 0:
        return live
    drift = abs(live_pct - stored_pct) / stored_pct * 100
    if drift <= MAX_STORED_DRIFT_PCT:
        out = dict(live)
        out["trail_percent"] = round(stored_pct, 2)
        out["trail_source"] = "stored_proposal"
        out["live_trail_percent"] = live_pct
        out["stored_drift_pct"] = round(drift, 1)
        return out
    out = dict(live)
    out["trail_source"] = "live_recompute_drift"
    out["stored_trail_percent"] = stored_pct
    out["stored_drift_pct"] = round(drift, 1)
    return out