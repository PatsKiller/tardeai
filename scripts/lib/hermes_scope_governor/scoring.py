"""Outcome-aware edge scoring for scope tier promotion/demotion ranking."""
from __future__ import annotations

from typing import Any

from .models import SymbolEdgeScore, SymbolSignals


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def _norm_0_100(value: float | None, lo: float, hi: float) -> float:
    if value is None:
        return 0.0
    if hi <= lo:
        return 0.0
    return _clamp(100.0 * (float(value) - lo) / (hi - lo))


def outcome_gate(sig: SymbolSignals, scfg: dict[str, Any]) -> str:
    """Graft-gate style outcome verdict before tier moves."""
    gates = scfg.get("outcome_gates") or {}
    min_n = int(gates.get("min_graded_samples", 3))
    demote_miss = float(gates.get("demote_miss_rate", 0.60))
    promote_hit = float(gates.get("promote_hit_rate", 0.50))
    pause_miss = float(gates.get("pause_miss_rate", 0.75))
    min_r = float(gates.get("promote_min_avg_r", 0.25))

    graded = sig.outcome_hits + sig.outcome_misses + sig.outcome_neutral
    if graded < min_n:
        return "neutral"

    hit_rate = sig.outcome_hits / graded if graded else 0.0
    miss_rate = sig.outcome_misses / graded if graded else 0.0

    if miss_rate >= pause_miss and graded >= min_n + 1:
        return "pause_eligible"
    if miss_rate >= demote_miss:
        return "demote_pressure"
    if hit_rate >= promote_hit and (sig.avg_realized_r is None or sig.avg_realized_r >= min_r):
        return "promote_eligible"
    return "neutral"


def compute_edge_score(sig: SymbolSignals, cfg: dict[str, Any], regime_label: str | None = None) -> SymbolEdgeScore:
    """Weighted 0-100 edge score. Outcome yield weighted highest."""
    scfg = cfg.get("scoring") or {}
    weights = scfg.get("weights") or {}
    w_portfolio = float(weights.get("portfolio_relevance", 25))
    w_outcome = float(weights.get("outcome_yield", 30))
    w_social = float(weights.get("social_conviction", 15))
    w_technical = float(weights.get("technical_edge", 15))
    w_event = float(weights.get("event_boost", 10))
    w_liquidity = float(weights.get("liquidity", 5))
    total_w = w_portfolio + w_outcome + w_social + w_technical + w_event + w_liquidity
    if total_w <= 0:
        total_w = 100.0

    reasons: list[str] = []
    components: dict[str, float] = {}

    # Portfolio relevance — capital exposed always maxes this component
    port_pts = 0.0
    if sig.is_holding:
        port_pts = 100.0
        reasons.append("holding")
    elif sig.is_open_scalp:
        port_pts = 95.0
        reasons.append("open_scalp")
    elif sig.is_open_position or sig.is_live_proposal:
        port_pts = 90.0
        reasons.append("open_exposure")
    elif sig.is_operator_directive:
        port_pts = 85.0
        reasons.append("operator_directive")
    elif sig.is_high_conviction_watch:
        port_pts = 70.0
        reasons.append("high_conviction_watch")
    components["portfolio_relevance"] = port_pts

    # Outcome yield — graded ledger dominates throughput signals
    graded = sig.outcome_hits + sig.outcome_misses + sig.outcome_neutral
    outcome_pts = 50.0  # conservative default when no evidence
    if graded > 0:
        hit_rate = sig.outcome_hits / graded
        outcome_pts = _clamp(100.0 * hit_rate)
        if sig.avg_realized_r is not None:
            outcome_pts = _clamp(0.6 * outcome_pts + 0.4 * _norm_0_100(sig.avg_realized_r, -1.0, 2.0))
        if sig.outcome_misses >= 3 and sig.outcome_hits == 0:
            outcome_pts = 10.0
            reasons.append("outcome_miss_streak")
        elif hit_rate >= 0.5:
            reasons.append(f"outcome_hit_rate={hit_rate:.0%}")
    elif sig.hermes_composite is not None and sig.hermes_composite >= 70:
        outcome_pts = 55.0  # throughput hint only — not enough to override misses later
    components["outcome_yield"] = outcome_pts

    # Social conviction + freshness
    social_pts = 0.0
    if sig.social_score is not None:
        social_pts = _norm_0_100(sig.social_score, 30, 90)
        if sig.social_fresh_hours is not None and sig.social_fresh_hours <= 24:
            social_pts = _clamp(social_pts + 15)
            reasons.append("fresh_social")
    components["social_conviction"] = social_pts

    # Technical edge — composite + RVOL proximity
    tech_pts = _norm_0_100(sig.hermes_composite, 40, 85)
    if sig.rvol is not None and sig.rvol >= 1.5:
        tech_pts = _clamp(tech_pts + _norm_0_100(sig.rvol, 1.5, 4.0) * 0.25)
        reasons.append("elevated_rvol")
    components["technical_edge"] = tech_pts

    # Event-driven boost
    event_pts = 0.0
    if sig.has_fresh_catalyst:
        event_pts = max(event_pts, 90.0)
        reasons.append("fresh_catalyst")
    if sig.has_fresh_directive_hit:
        event_pts = max(event_pts, 75.0)
    if sig.has_fresh_event:
        event_pts = max(event_pts, 80.0)
        reasons.append("pending_score_event")
    components["event_boost"] = event_pts

    # Liquidity / volatility filters
    liq_pts = 50.0
    filters = scfg.get("liquidity_filters") or {}
    min_vol = float(filters.get("min_avg_volume", 200_000))
    max_atr = float(filters.get("max_atr_pct", 12.0))
    if sig.avg_volume is not None:
        liq_pts = _norm_0_100(sig.avg_volume, min_vol, min_vol * 20)
        if sig.avg_volume < min_vol * 0.5:
            liq_pts = 20.0
            reasons.append("low_liquidity")
    if sig.atr_pct is not None and sig.atr_pct > max_atr:
        liq_pts = _clamp(liq_pts - 25)
        reasons.append("high_volatility")
    components["liquidity"] = liq_pts

    # Regime tilt — conservative in high vol, favor trend names in trending regime
    regime_mult = 1.0
    if regime_label:
        rl = regime_label.lower()
        if "high_vol" in rl or "volatility" in rl:
            regime_mult = 0.92
            if sig.atr_pct and sig.atr_pct > 8:
                reasons.append("regime_high_vol_penalty")
        elif "trend" in rl and (sig.hermes_composite or 0) >= 65:
            regime_mult = 1.05

    raw = (
        w_portfolio * port_pts + w_outcome * outcome_pts + w_social * social_pts
        + w_technical * tech_pts + w_event * event_pts + w_liquidity * liq_pts
    ) / total_w
    edge = _clamp(raw * regime_mult)

    gate = outcome_gate(sig, scfg)
    if gate == "demote_pressure":
        edge = _clamp(edge - float((scfg.get("outcome_gates") or {}).get("demote_score_penalty", 20)))
    elif gate == "promote_eligible":
        edge = _clamp(edge + float((scfg.get("outcome_gates") or {}).get("promote_score_boost", 8)))

    return SymbolEdgeScore(
        symbol=sig.symbol,
        edge_score=round(edge, 2),
        components={k: round(v, 2) for k, v in components.items()},
        signals=sig,
        reasons=reasons,
        outcome_gate=gate,
    )