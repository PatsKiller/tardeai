"""stoplight_regime_thresholds.py — Regime-adjusted Yellow/Amber/Red stop proximity thresholds.

Implements MOMENTUM_SCALP_STOP_MONITORING_PROTOCOL.md § Dynamic Regime-Based Stoplight v2.0.
Layer 2 breakeven is never relaxed by regime (policy §3).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from momentum_scalp_regime import DEFAULT_CFG_PATH, _load_yaml

LEVEL_RANK = {"red": 3, "amber": 2, "yellow": 1, None: 0}
RANK_LEVEL = {3: "red", 2: "amber", 1: "yellow", 0: None}


def _max_level(a: str | None, b: str | None) -> str | None:
    return RANK_LEVEL[max(LEVEL_RANK.get(a), LEVEL_RANK.get(b))] or None


def _escalate(level: str | None, steps: int = 1) -> str | None:
    r = LEVEL_RANK.get(level, 0) + steps
    return RANK_LEVEL.get(min(r, 3))


def regime_thresholds(regime: str, cfg: dict | None = None) -> dict:
    cfg = cfg or _load_yaml()
    sl = (cfg.get("stoplight") or {}).get(regime) or (cfg.get("stoplight") or {}).get("trending") or {}
    return sl


def distance_level(
    dist_r: float | None,
    dist_pct: float | None,
    thresholds: dict,
) -> tuple[str | None, str | None]:
    """Return (level, reason_fragment) from distance to stop."""
    if dist_r is not None and dist_r >= 0:
        if dist_r <= thresholds.get("red_r", 0.10):
            return "red", f"within {dist_r:.2f}R of stop (red ≤{thresholds.get('red_r')}R)"
        if dist_r <= thresholds.get("amber_r", 0.18):
            return "amber", f"within {dist_r:.2f}R of stop (amber ≤{thresholds.get('amber_r')}R)"
        if dist_r <= thresholds.get("yellow_r", 0.30):
            return "yellow", f"within {dist_r:.2f}R of stop (yellow ≤{thresholds.get('yellow_r')}R)"
        return None, None
    if dist_pct is not None:
        if dist_pct <= thresholds.get("red_pct", 1.5):
            return "red", f"within {dist_pct}% of stop (regime red ≤{thresholds.get('red_pct')}%)"
        if dist_pct <= thresholds.get("amber_pct", 3.0):
            return "amber", f"within {dist_pct}% of stop (regime amber ≤{thresholds.get('amber_pct')}%)"
        if dist_pct <= thresholds.get("yellow_pct", 6.0):
            return "yellow", f"within {dist_pct}% of stop (regime yellow ≤{thresholds.get('yellow_pct')}%)"
    return None, None


def evaluate_regime_stoplight(
    *,
    regime: str,
    regime_meta: dict | None = None,
    dist_r: float | None,
    dist_pct: float | None,
    dist_atr: float | None = None,
    modifiers: dict | None = None,
    cfg: dict | None = None,
) -> dict[str, Any]:
    """Compute regime-aware alert level, reasons, and policy suggestions."""
    cfg = cfg or _load_yaml()
    mod = modifiers or {}
    regime_meta = regime_meta or {}
    th = regime_thresholds(regime, cfg)
    mod_cfg = cfg.get("modifiers") or {}

    red, amber, yellow = [], [], []
    suggestions = []

    # Regime shift → immediate amber + Layer 4 tighten (policy §3 Layer 4.1)
    if regime_meta.get("regime_shift_detected") or regime == "regime_shift":
        amber.append(
            f"regime shift {regime_meta.get('regime_shift_direction') or 'detected'} "
            f"(Layer 4 — tighten trail 0.5× ATR)"
        )
        suggestions.append(
            "Tighten trail by 0.5× ATR — Layer 4 Regime Shift rule "
            f"({regime_meta.get('regime_shift_direction') or 'shift in progress'})"
        )
        if th.get("force_amber"):
            level_floor = "amber"
        else:
            level_floor = None
    else:
        level_floor = None

    dist_level, dist_reason = distance_level(dist_r, dist_pct, th)
    if dist_level == "red" and dist_reason:
        red.append(dist_reason)
    elif dist_level == "amber" and dist_reason:
        amber.append(dist_reason)
    elif dist_level == "yellow" and dist_reason:
        yellow.append(dist_reason)

    if dist_atr is not None and dist_atr <= 1.0 and regime in ("ranging", "high_volatility"):
        amber.append(f"within {dist_atr}×ATR of stop (tight in {regime_meta.get('regime_label', regime)})")

    # Modifiers — escalate severity (protocol v2.0 secondary modifiers)
    heat = mod.get("heat_contribution_pct")
    if heat is not None and heat >= mod_cfg.get("portfolio_heat_contrib_amber", 1.5):
        amber.append(f"{heat:.1f}% portfolio heat contribution")

    price_street = mod.get("price_vs_consensus_pct")
    unreal_r = mod.get("unrealized_r")
    if price_street is not None:
        if price_street >= mod_cfg.get("price_above_street_red_pct", 8.0) and (unreal_r or 0) >= mod_cfg.get("profit_r_tighten_suggest", 2.5):
            red.append(
                f"price {price_street:.1f}% above Street mean with {unreal_r:.1f}R profit — extended vs consensus"
            )
            suggestions.append(
                f"Tighten stop / consider partial — price {price_street:.1f}% above Street + {unreal_r:.1f}R "
                f"(Layer 4 + consensus extension)"
            )
        elif price_street >= mod_cfg.get("price_above_street_amber_pct", 5.0):
            amber.append(f"price {price_street:.1f}% above Street consensus mean")
            if (unreal_r or 0) >= 2.0:
                suggestions.append(
                    f"Move toward breakeven or tighten trail — {unreal_r:.1f}R profit while extended vs Street"
                )

    if mod.get("trailing_should_be_active") and (unreal_r or 0) >= mod_cfg.get("trail_inactive_amber_r", 2.0):
        amber.append(f"trailing eligible but not active (>+{mod_cfg.get('trail_inactive_amber_r')}R)")

    if mod.get("naked") and mod.get("is_active_trade"):
        amber.append(mod.get("naked_reason") or "active trade naked")

    if mod.get("divergence") == "broker looser than advised":
        amber.append("broker looser than advised")

    if mod.get("risk_off") and mod.get("naked"):
        red.append("active trade naked in risk-off regime")

    level = None
    if red:
        level = "red"
    elif amber:
        level = "amber"
    elif yellow:
        level = "yellow"

    if level_floor:
        level = _max_level(level, level_floor)

    reasons = red + amber + yellow
    return {
        "alert_level": level,
        "alert_reasons": reasons,
        "policy_suggestions": suggestions,
        "thresholds_used": {
            "regime": regime,
            "yellow_r": th.get("yellow_r"),
            "amber_r": th.get("amber_r"),
            "red_r": th.get("red_r"),
            "distance_metric": "R" if dist_r is not None else "pct",
        },
    }