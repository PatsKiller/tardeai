"""Watchlist health scoring — composite 0–100 with confidence discount."""
from __future__ import annotations

from typing import Any

HIGH_VOL_REGIME_TOKENS = ("high_vol", "volatility", "risk_off", "elevated")


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def _norm_0_100(value: float | None, lo: float, hi: float, default: float = 50.0) -> float:
    if value is None:
        return default
    if hi <= lo:
        return default
    return _clamp(100.0 * (float(value) - lo) / (hi - lo))


def fetch_promotion_success_rates(cur, lookback_days: int = 90) -> dict[str, dict[str, Any]]:
    """Per-symbol promotion → outcome hit rate from hermes_outcome_ledger."""
    out: dict[str, dict[str, Any]] = {}
    try:
        cur.execute("""SELECT UPPER(symbol) AS sym,
                              count(*) FILTER (WHERE subject_type = 'promotion'
                                               AND verdict = 'hit') AS hits,
                              count(*) FILTER (WHERE subject_type = 'promotion') AS total
                       FROM hermes_outcome_ledger
                       WHERE symbol IS NOT NULL
                         AND emitted_at > NOW() - make_interval(days => %s)
                       GROUP BY UPPER(symbol)
                       HAVING count(*) FILTER (WHERE subject_type = 'promotion') >= 1""",
                    (lookback_days,))
        for sym, hits, total in cur.fetchall():
            t = int(total or 0)
            h = int(hits or 0)
            out[str(sym)] = {
                "promotion_hits": h,
                "promotion_total": t,
                "promotion_hit_rate": round(h / t, 3) if t else None,
            }
    except Exception:
        pass
    return out


def _regime_alignment_score(regime_label: str | None, atr_pct: float | None, cfg: dict[str, Any]) -> float:
    if not regime_label:
        return 55.0
    rl = regime_label.lower()
    tokens = tuple((cfg.get("regime") or {}).get("high_vol_tokens") or HIGH_VOL_REGIME_TOKENS)
    if any(t in rl for t in tokens):
        base = 40.0
        if atr_pct is not None and float(atr_pct) > 8:
            base = 30.0
        return base
    if "trend" in rl:
        return 75.0
    return 60.0


def compute_health_components(
    sym: str,
    sig: Any,
    edge_detail: dict[str, Any],
    bus_sym: dict[str, Any] | None,
    promo_stats: dict[str, Any] | None,
    stop_global: dict[str, Any],
    regime_label: str | None,
    cfg: dict[str, Any],
) -> dict[str, float]:
    bus_sym = bus_sym or {}
    promo_stats = promo_stats or {}
    components: dict[str, float] = {}

    hits = int(getattr(sig, "outcome_hits", 0) or bus_sym.get("outcome_hits") or bus_sym.get("hits") or 0)
    misses = int(getattr(sig, "outcome_misses", 0) or bus_sym.get("misses") or 0)
    neutral = int(getattr(sig, "outcome_neutral", 0) or 0)
    graded = hits + misses + neutral
    hit_rate = hits / graded if graded else None
    avg_r = getattr(sig, "avg_realized_r", None)
    if avg_r is None:
        avg_r = bus_sym.get("avg_r")

    outcome_pts = 50.0
    if hit_rate is not None:
        outcome_pts = _norm_0_100(hit_rate, 0.25, 0.65, 45.0)
    if avg_r is not None:
        outcome_pts = _clamp(0.6 * outcome_pts + 0.4 * _norm_0_100(float(avg_r), -0.5, 1.5, 50.0))
    components["outcome_performance"] = round(outcome_pts, 1)

    promo_rate = promo_stats.get("promotion_hit_rate")
    promo_total = int(promo_stats.get("promotion_total") or 0)
    if promo_total >= 1 and promo_rate is not None:
        components["promotion_success_rate"] = round(_norm_0_100(float(promo_rate), 0.30, 0.70, 40.0), 1)
    else:
        components["promotion_success_rate"] = 50.0

    lift = bus_sym.get("lift")
    precision = bus_sym.get("precision")
    tag_pts = 55.0
    if lift is not None:
        tag_pts = _norm_0_100(float(lift), -0.05, 0.15, 50.0)
    if precision is not None:
        tag_pts = _clamp(0.65 * tag_pts + 0.35 * _norm_0_100(float(precision), 0.35, 0.75, 50.0))
    if bus_sym.get("tag_flagged"):
        tag_pts = _clamp(tag_pts - 20)
    components["tag_lift_consistency"] = round(tag_pts, 1)

    aligned = stop_global.get("aligned_pct")
    trail = stop_global.get("trail_activation_rate")
    stop_pts = 60.0
    if aligned is not None:
        stop_pts = _norm_0_100(float(aligned), 0.40, 0.85, 55.0)
    if trail is not None and float(trail) < 0.35:
        stop_pts = _clamp(stop_pts - 12)
    components["stop_quality"] = round(stop_pts, 1)

    atr = getattr(sig, "atr_pct", None)
    components["regime_alignment"] = round(_regime_alignment_score(regime_label, atr, cfg), 1)

    research_pts = 55.0
    actioned = getattr(sig, "research_actioned_rate", None)
    if actioned is not None:
        research_pts = _norm_0_100(float(actioned), 0.10, 0.60, 50.0)
    elif edge_detail.get("components", {}).get("outcome_yield"):
        research_pts = float(edge_detail["components"]["outcome_yield"])
    components["research_efficiency"] = round(research_pts, 1)

    edge = float(edge_detail.get("edge_score") or 50.0)
    components["edge_blend"] = round(_clamp(edge), 1)

    return components


def apply_confidence_discount(score: float, graded_n: int, cfg: dict[str, Any]) -> tuple[float, str]:
    conf = cfg.get("confidence") or {}
    min_full = int(conf.get("min_graded_for_full", 5))
    min_samples = int(conf.get("min_graded_samples", 3))
    mult_low = float(conf.get("low_graded_multiplier", 0.75))
    mult_sparse = float(conf.get("sparse_multiplier", 0.85))

    if graded_n < min_samples:
        return round(_clamp(score * mult_sparse), 1), "sparse_data"
    if graded_n < min_full:
        return round(_clamp(score * mult_low), 1), "low_confidence"
    return round(score, 1), "full"


def compute_watchlist_health_score(
    components: dict[str, float],
    graded_n: int,
    cfg: dict[str, Any],
) -> tuple[float, float, str]:
    """Return (raw_score, final_score, confidence_tier)."""
    weights = cfg.get("health_weights") or {}
    total_w = sum(float(v) for v in weights.values()) or 1.0
    raw = sum(float(weights.get(k, 0)) * components.get(k, 50.0) for k in weights) / total_w
    raw = _clamp(raw)
    final, tier = apply_confidence_discount(raw, graded_n, cfg)
    return round(raw, 1), final, tier


def blend_display_score(health: float, edge: float | None, cfg: dict[str, Any]) -> float:
    blend = cfg.get("conviction_blend") or {}
    hw = float(blend.get("health_weight", 0.70))
    ew = float(blend.get("edge_weight", 0.30))
    e = float(edge or 50.0)
    return round(_clamp(hw * health + ew * e), 1)


def passes_promotion_health_gate(
    health_score: float,
    confidence_tier: str,
    graded_n: int,
    cfg: dict[str, Any],
) -> tuple[bool, str]:
    """Conservative gate for outcome-driven S1 promotions."""
    thr = cfg.get("health_thresholds") or {}
    floor = float(thr.get("promote_floor", 62))
    rules = cfg.get("transition_rules") or {}
    min_graded = int(rules.get("min_graded_samples", 3))

    if graded_n < min_graded:
        return False, f"graded_n={graded_n}<{min_graded}"
    if confidence_tier == "sparse_data":
        return False, "confidence_sparse_data"
    if health_score < floor:
        return False, f"health={health_score:.0f}<{floor:.0f}"
    if confidence_tier == "low_confidence" and health_score < floor + 5:
        return False, f"low_confidence_health={health_score:.0f}"
    return True, "ok"


def health_trend_delta(history: list[dict[str, Any]], days: int = 7) -> float | None:
    if len(history) < 2:
        return None
    recent = history[-1].get("health_score")
    old = None
    if len(history) > days:
        old = history[-1 - days].get("health_score")
    elif len(history) >= 2:
        old = history[0].get("health_score")
    if recent is None or old is None:
        return None
    return round(float(recent) - float(old), 1)