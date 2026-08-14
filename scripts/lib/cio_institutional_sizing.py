"""cio_institutional_sizing.py — Phase 5 objective-driven position sizing.

A default 10% trim is only a fallback candidate — never the sole "solved" answer
when concentration fire / policy cap objectives are known.

READ_ONLY_ADVISORY. Pure math — no broker execution.
"""
from __future__ import annotations

from typing import Any, Optional

SIZING_VERSION = "institutional_sizing_1.0.0"

# Policy defaults (aligned with capital_plan)
POLICY_CAP_PCT_DEFAULT = 12.0
CONCENTRATION_FIRE_PCT_DEFAULT = 16.5
# After clearing fire, leave a small buffer under the fire line when staging
FIRE_CLEAR_BUFFER_PP = 0.5  # percentage points under fire
# When only advisory TRIM and under policy: fallback fraction of *excess* or position
FALLBACK_TRIM_FRACTION = 0.10
STAGED_FRACTION_OF_FULL_POLICY = 0.45  # staged between fire-clear and full policy
NEW_POSITION_DEFAULT_USD = 5_000.0


def _f(v: Any, default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def compute_trim_objectives(
    *,
    market_value_usd: float,
    weight_pct: float,
    portfolio_value_usd: float,
    policy_cap_pct: float = POLICY_CAP_PCT_DEFAULT,
    fire_pct: float = CONCENTRATION_FIRE_PCT_DEFAULT,
) -> dict[str, Any]:
    """Dollar objectives for concentration / policy sizing."""
    v = max(0.0, _f(market_value_usd))
    p = max(0.0, _f(portfolio_value_usd))
    w = _f(weight_pct)
    if p > 0 and v > 0 and w <= 0:
        w = v / p * 100.0
    fire = _f(fire_pct, CONCENTRATION_FIRE_PCT_DEFAULT)
    cap = _f(policy_cap_pct, POLICY_CAP_PCT_DEFAULT)

    fire_value = p * fire / 100.0 if p > 0 else 0.0
    policy_value = p * cap / 100.0 if p > 0 else 0.0
    # Target slightly under fire when clearing (safety margin)
    fire_safe_value = p * max(0.0, fire - FIRE_CLEAR_BUFFER_PP) / 100.0 if p > 0 else 0.0

    trim_to_clear_fire = max(0.0, v - fire_value)
    trim_to_fire_safe = max(0.0, v - fire_safe_value)
    trim_to_policy = max(0.0, v - policy_value)
    fallback_10pct = round(v * FALLBACK_TRIM_FRACTION, 2)

    above_fire = w > fire + 1e-9
    above_policy = w > cap + 1e-9

    return {
        "sizing_version": SIZING_VERSION,
        "market_value_usd": round(v, 2),
        "weight_pct": round(w, 4),
        "portfolio_value_usd": round(p, 2),
        "fire_pct": fire,
        "policy_cap_pct": cap,
        "fire_value_usd": round(fire_value, 2),
        "policy_value_usd": round(policy_value, 2),
        "trim_to_clear_fire_usd": round(trim_to_clear_fire, 2),
        "trim_to_fire_safe_usd": round(trim_to_fire_safe, 2),
        "trim_to_policy_usd": round(trim_to_policy, 2),
        "fallback_10pct_usd": fallback_10pct,
        "above_fire": above_fire,
        "above_policy": above_policy,
    }


def recommend_trim(
    *,
    market_value_usd: float,
    weight_pct: float,
    portfolio_value_usd: float,
    policy_cap_pct: float = POLICY_CAP_PCT_DEFAULT,
    fire_pct: float = CONCENTRATION_FIRE_PCT_DEFAULT,
    tax_class: str = "TAXABLE",
    advisory_trim: bool = True,
) -> dict[str, Any]:
    """Choose a recommended trim with objective rationale (not blind 10%)."""
    obj = compute_trim_objectives(
        market_value_usd=market_value_usd,
        weight_pct=weight_pct,
        portfolio_value_usd=portfolio_value_usd,
        policy_cap_pct=policy_cap_pct,
        fire_pct=fire_pct,
    )
    v = obj["market_value_usd"]
    clear = obj["trim_to_clear_fire_usd"]
    safe = obj["trim_to_fire_safe_usd"]
    full = obj["trim_to_policy_usd"]
    fb = obj["fallback_10pct_usd"]

    why_not_min = ""
    why_not_max = ""
    method = "fallback_10pct"
    recommended = fb
    target_weight = obj["policy_cap_pct"]

    if obj["above_fire"]:
        # Must clear fire; stage between fire-safe and full policy
        method = "clear_fire_staged"
        # Prefer fire-safe (buffer under fire) as minimum objective
        min_obj = max(clear, safe) if safe > 0 else clear
        if full > min_obj + 1.0:
            # Stage: min_obj + fraction of remaining to policy
            recommended = round(min_obj + STAGED_FRACTION_OF_FULL_POLICY * (full - min_obj), 2)
            why_not_min = (
                f"Minimum to clear fire (${min_obj:,.0f}) leaves little safety margin "
                f"under the {obj['fire_pct']}% fire line."
            )
            why_not_max = (
                f"Full normalization to policy max {obj['policy_cap_pct']}% "
                f"(${full:,.0f}) may be more than needed in one step given conviction "
                f"and tax/account constraints."
            )
            if tax_class == "TAXABLE":
                why_not_max += " Taxable account: lot/tax review before full realization."
        else:
            recommended = round(min_obj, 2)
            why_not_min = "Clearing fire is the binding objective."
            why_not_max = "Already at or near policy once fire is cleared."
        # Target weight after recommended trim
        if portfolio_value_usd > 0:
            target_weight = max(
                0.0,
                (v - recommended) / portfolio_value_usd * 100.0,
            )
    elif obj["above_policy"]:
        method = "policy_normalize_staged"
        # Stage toward policy (not full dump, not blind 10% of whole book)
        if full > 0:
            recommended = round(max(full * STAGED_FRACTION_OF_FULL_POLICY, min(fb, full)), 2)
            recommended = min(recommended, full)
        else:
            recommended = 0.0
        why_not_min = (
            f"A token trim below the excess over policy "
            f"(${full:,.0f} to fully normalize) does not restore the policy cap."
        )
        why_not_max = (
            f"Full cut to {obj['policy_cap_pct']}% (${full:,.0f}) in one step may be "
            f"oversized relative to desk conviction and replacement capital."
        )
        if portfolio_value_usd > 0:
            target_weight = max(0.0, (v - recommended) / portfolio_value_usd * 100.0)
    elif advisory_trim:
        method = "advisory_fallback_10pct"
        recommended = fb
        why_not_min = "No concentration fire; advisory trim uses the 10% fallback candidate only."
        why_not_max = "Position is within policy cap; larger cuts need a stronger objective."
        target_weight = obj["weight_pct"] * (1.0 - FALLBACK_TRIM_FRACTION)
    else:
        method = "none"
        recommended = 0.0
        why_not_min = why_not_max = "No trim objective."

    recommended = round(max(0.0, min(recommended, v)), 2)

    return {
        **obj,
        "recommended_trim_usd": recommended,
        "recommended_delta_usd": -recommended if recommended > 0 else 0.0,
        "target_weight_pct": round(target_weight, 2),
        "method": method,
        "why_not_min": why_not_min,
        "why_not_max": why_not_max,
        "objective_summary": (
            f"Current weight {obj['weight_pct']:.2f}% · Fire {obj['fire_pct']}% · "
            f"Policy max {obj['policy_cap_pct']}% · "
            f"Min clear fire ${obj['trim_to_clear_fire_usd']:,.0f} · "
            f"Full to policy ${obj['trim_to_policy_usd']:,.0f} · "
            f"Alex recommend ${recommended:,.0f} ({method})"
        ),
        "fallback_candidate_only": method == "advisory_fallback_10pct",
    }


def recommend_exit(*, market_value_usd: float) -> dict[str, Any]:
    v = max(0.0, _f(market_value_usd))
    return {
        "sizing_version": SIZING_VERSION,
        "method": "full_exit",
        "recommended_delta_usd": -v,
        "recommended_trim_usd": v,
        "target_weight_pct": 0.0,
        "objective_summary": f"Full exit of ${v:,.0f}",
        "why_not_min": "Partial exit would leave residual book risk the desk marked EXIT.",
        "why_not_max": "Already 100% of position.",
        "fallback_candidate_only": False,
    }


def recommend_add(
    *,
    headroom_usd: float,
    default_usd: float = NEW_POSITION_DEFAULT_USD,
) -> dict[str, Any]:
    h = max(0.0, _f(headroom_usd))
    d = max(0.0, _f(default_usd))
    amt = round(min(d, h) if h > 0 else 0.0, 2)
    return {
        "sizing_version": SIZING_VERSION,
        "method": "headroom_bounded_default",
        "recommended_delta_usd": amt,
        "objective_summary": f"Add ${amt:,.0f} (default ${d:,.0f} bounded by ${h:,.0f} headroom)",
        "fallback_candidate_only": False,
    }


def size_decision(
    *,
    stance: str,
    market_value_usd: float,
    weight_pct: float,
    portfolio_value_usd: float,
    policy_cap_pct: float = POLICY_CAP_PCT_DEFAULT,
    fire_pct: float = CONCENTRATION_FIRE_PCT_DEFAULT,
    tax_class: str = "TAXABLE",
    headroom_usd: float = 0.0,
) -> dict[str, Any]:
    """Dispatch sizing by stance."""
    s = (stance or "HOLD").upper()
    if s == "EXIT":
        return recommend_exit(market_value_usd=market_value_usd)
    if s == "TRIM":
        return recommend_trim(
            market_value_usd=market_value_usd,
            weight_pct=weight_pct,
            portfolio_value_usd=portfolio_value_usd,
            policy_cap_pct=policy_cap_pct,
            fire_pct=fire_pct,
            tax_class=tax_class,
            advisory_trim=True,
        )
    if s in ("ADD", "RE_ENTER"):
        return recommend_add(headroom_usd=headroom_usd)
    return {
        "sizing_version": SIZING_VERSION,
        "method": "hold",
        "recommended_delta_usd": 0.0,
        "target_weight_pct": round(_f(weight_pct), 2),
        "objective_summary": "Hold — no size change",
        "fallback_candidate_only": False,
    }
