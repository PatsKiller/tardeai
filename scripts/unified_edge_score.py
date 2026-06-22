#!/usr/bin/env python3
"""unified_edge_score.py — Shared 0–100 edge composite for proposals across modules.

Combines technicals, regime, catalyst strength, and strategy-specific factors.
Options engine uses the same weighting philosophy; trade proposals can adopt via
compute_unified_edge() as maturity work continues.
"""
from __future__ import annotations

from typing import Any, Dict, Optional


def _f(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def compute_unified_edge(
    *,
    pop_pct: float = 50.0,
    iv_rank: float = 25.0,
    risk_reward: float = 0.5,
    catalyst_strength: float = 0.0,
    conviction: float = 0.0,
    regime_alignment: float = 0.0,
    technical_score: float = 0.0,
    weights: Optional[Dict[str, float]] = None,
) -> float:
    """Return 0–100 edge score. All inputs normalized to sensible ranges."""
    w = weights or {
        "pop": 0.30,
        "iv": 0.15,
        "rr": 0.15,
        "catalyst": 0.15,
        "conviction": 0.15,
        "regime": 0.05,
        "technical": 0.05,
    }
    pop_s = min(100.0, max(0.0, pop_pct)) * w["pop"]
    iv_s = min(100.0, max(0.0, iv_rank)) * w["iv"]
    rr_s = min(100.0, risk_reward * 25.0) * w["rr"]
    cat_s = min(100.0, catalyst_strength * 100.0) * w["catalyst"]
    conv_s = min(100.0, conviction * 100.0) * w["conviction"]
    reg_s = min(100.0, max(0.0, regime_alignment)) * w["regime"]
    tech_s = min(100.0, max(0.0, technical_score)) * w["technical"]
    return round(pop_s + iv_s + rr_s + cat_s + conv_s + reg_s + tech_s, 1)


def edge_from_trade_context(ctx: Dict[str, Any]) -> float:
    """Convenience wrapper for trade/strategy proposal rows."""
    return compute_unified_edge(
        pop_pct=_f(ctx.get("pop_pct"), 55),
        iv_rank=_f(ctx.get("iv_rank"), 25),
        risk_reward=_f(ctx.get("risk_reward"), 0.5),
        catalyst_strength=_f(ctx.get("catalyst_strength") or ctx.get("catalyst_score"), 0.5),
        conviction=_f(ctx.get("confidence") or ctx.get("conviction"), 0.5),
        regime_alignment=_f(ctx.get("regime_alignment"), 50),
        technical_score=_f(ctx.get("technical_score") or ctx.get("confluence_score"), 50),
    )