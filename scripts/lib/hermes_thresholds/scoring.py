"""Phase 2 composite threshold scoring — multi-metric, explainable, conservative."""
from __future__ import annotations

from typing import Any

# Efficiency composite weights (sum = 1.0) — outcome yield prioritized
EFFICIENCY_WEIGHTS = {
    "hit_rate_separation": 0.40,
    "maturity_separation": 0.25,
    "realized_r_separation": 0.15,
    "efficiency_stability": 0.10,
    "early_detection": 0.10,
}

# Stop quality composite weights
STOP_QUALITY_WEIGHTS = {
    "alignment_separation": 0.35,
    "trail_delta_separation": 0.25,
    "maturity_stop_separation": 0.20,
    "early_detection": 0.10,
    "trigger_guard": 0.10,
}


def _num(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _avg(vals: list[float]) -> float | None:
    return sum(vals) / len(vals) if vals else None


def _separation(triggered: list[float], baseline: list[float]) -> float:
    if not triggered or not baseline:
        return 0.0
    return _avg(baseline) - _avg(triggered)  # type: ignore[operator]


def _high_vol_tokens(cfg: dict[str, Any]) -> list[str]:
    regime = cfg.get("regime") or {}
    return [str(t).lower() for t in (regime.get("scoring_high_vol_match") or [
        "high_vol", "volatility", "risk_off", "elevated",
    ])]


def is_high_vol_day(point: dict[str, Any], cfg: dict[str, Any]) -> bool:
    label = str(point.get("regime_label") or "").lower()
    tokens = _high_vol_tokens(cfg)
    if label and any(t in label for t in tokens):
        return True
    # Fallback stress proxy when regime not on series point
    alerts = point.get("active_alert_ids") or []
    eff = _num(point.get("resource_efficiency_score"))
    return bool(alerts) and eff is not None and eff < 0.52


def regime_breakdown(series: list[dict[str, Any]], cfg: dict[str, Any]) -> dict[str, Any]:
    high = sum(1 for s in series if is_high_vol_day(s, cfg))
    total = max(len(series), 1)
    pct = high / total
    return {
        "total_days": len(series),
        "high_vol_days": high,
        "high_vol_pct": round(pct, 3),
        "regime_stable": pct <= float((cfg.get("regime") or {}).get("high_vol_pct_cap", 0.30)),
    }


def resolve_confidence(
    sample_days: int,
    score_delta: float,
    regime: dict[str, Any],
    runner_up_gap: float,
    cfg: dict[str, Any],
) -> tuple[str, list[str]]:
    """Return (low|medium|high, factors list)."""
    conf_cfg = (cfg.get("scoring") or {}).get("confidence") or {}
    factors: list[str] = []
    tier = "medium"

    if sample_days >= int(conf_cfg.get("high_sample_days", 22)):
        factors.append(f"sample_days={sample_days}≥22")
        tier = "high"
    elif sample_days < int(conf_cfg.get("low_sample_days", 14)):
        factors.append(f"sample_days={sample_days}<14")
        tier = "low"

    if not regime.get("regime_stable", True):
        factors.append(f"high_vol_pct={regime.get('high_vol_pct', 0):.0%}>cap")
        tier = "low" if tier == "medium" else ("medium" if tier == "high" else "low")

    min_delta = float(conf_cfg.get("high_score_delta", 0.005))
    if score_delta < min_delta:
        factors.append(f"score_delta={score_delta:.4f}<min")
        if tier == "high":
            tier = "medium"

    gap_min = float(conf_cfg.get("runner_up_gap", 0.005))
    if runner_up_gap < gap_min:
        factors.append("runner_up_within_gap")
        if tier == "high":
            tier = "medium"
        elif tier == "medium":
            tier = "low"

    if not factors:
        factors.append("default_medium")
    return tier, factors


def _early_detection_bonus(
    series: list[dict[str, Any]],
    trigger_fn,
    yield_key: str = "hit_rate_promotions",
    lookahead: int = 3,
) -> float:
    """Reward thresholds that fire before subsequent yield drops."""
    bonuses: list[float] = []
    for i, s in enumerate(series):
        if not trigger_fn(s):
            continue
        cur = _num(s.get(yield_key))
        if cur is None:
            continue
        future: list[float] = []
        for j in range(1, min(lookahead + 1, len(series) - i)):
            v = _num(series[i + j].get(yield_key))
            if v is not None:
                future.append(v)
        if not future:
            continue
        drop = cur - _avg(future)  # type: ignore[operator]
        if drop > 0.02:
            bonuses.append(min(0.08, drop))
    return _avg(bonuses) or 0.0  # type: ignore[return-value]


def _trigger_guard_score(trigger_rate: float, cap: float = 0.35) -> float:
    penalty = max(0.0, trigger_rate - cap) * 0.5
    return max(0.0, 1.0 - penalty)


def score_efficiency_candidate(
    series: list[dict[str, Any]],
    candidate: float,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Composite score for efficiency tighten_threshold candidate."""
    cfg = cfg or {}
    weights = (cfg.get("scoring") or {}).get("efficiency_weights") or EFFICIENCY_WEIGHTS

    trig_hr: list[float] = []
    base_hr: list[float] = []
    trig_mat: list[float] = []
    base_mat: list[float] = []
    trig_r: list[float] = []
    base_r: list[float] = []
    trig_eff: list[float] = []
    base_eff: list[float] = []

    for s in series:
        eff = _num(s.get("resource_efficiency_score"))
        if eff is None:
            continue
        triggered = eff < candidate
        hr = _num(s.get("hit_rate_promotions"))
        mat = _num(s.get("maturity_composite_score"))
        r = _num(s.get("avg_realized_r_trades_90d"))

        if triggered:
            if hr is not None:
                trig_hr.append(hr)
            if mat is not None:
                trig_mat.append(mat)
            if r is not None:
                trig_r.append(r)
            if eff is not None:
                trig_eff.append(eff)
        else:
            if hr is not None:
                base_hr.append(hr)
            if mat is not None:
                base_mat.append(mat)
            if r is not None:
                base_r.append(r)
            if eff is not None:
                base_eff.append(eff)

    n_trig = len(trig_hr) + len(trig_mat)
    n_total = max(len([s for s in series if _num(s.get("resource_efficiency_score")) is not None]), 1)
    trigger_rate = (len(trig_hr) or 0) / n_total if trig_hr else 0.0
    if trig_hr and base_hr:
        trigger_rate = len(trig_hr) / (len(trig_hr) + len(base_hr))

    hr_sep = _separation(trig_hr, base_hr)
    mat_sep = _separation(trig_mat, base_mat) / 100.0 if trig_mat and base_mat else 0.0  # scale to ~pp
    r_sep = _separation(trig_r, base_r) if trig_r and base_r else 0.0
    eff_sep = _separation(trig_eff, base_eff) if trig_eff and base_eff else 0.0
    # stability: prefer triggered days not far below baseline efficiency (avoid noise)
    eff_stab = max(0.0, eff_sep) if trig_eff else 0.0

    early = _early_detection_bonus(
        series,
        lambda s: (_num(s.get("resource_efficiency_score")) or 1) < candidate,
    )

    contributions = {
        "hit_rate_separation": round(hr_sep * weights.get("hit_rate_separation", 0.40), 4),
        "maturity_separation": round(mat_sep * weights.get("maturity_separation", 0.25), 4),
        "realized_r_separation": round(r_sep * weights.get("realized_r_separation", 0.15), 4),
        "efficiency_stability": round(eff_stab * weights.get("efficiency_stability", 0.10), 4),
        "early_detection": round(early * weights.get("early_detection", 0.10), 4),
    }
    guard = _trigger_guard_score(trigger_rate)
    raw = sum(contributions.values()) * guard

    return {
        "score": round(max(0.0, raw), 4),
        "trigger_rate": round(trigger_rate, 3),
        "metric_contributions": contributions,
        "raw_separations": {
            "hit_rate": round(hr_sep, 4),
            "maturity": round(mat_sep * 100, 2) if mat_sep else None,
            "realized_r": round(r_sep, 4) if r_sep else None,
        },
        "conditional_hit_rate": round(_avg(trig_hr), 3) if trig_hr else None,
        "baseline_hit_rate": round(_avg(base_hr), 3) if base_hr else None,
        "triggered_days": len(trig_hr),
        "baseline_days": len(base_hr),
        "early_detection_bonus": round(early, 4),
        "trigger_guard": round(guard, 3),
    }


def score_stop_quality_candidate(
    series: list[dict[str, Any]],
    candidate: float,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Composite score for stop_quality divergence_delta_pp candidate."""
    cfg = cfg or {}
    weights = (cfg.get("scoring") or {}).get("stop_quality_weights") or STOP_QUALITY_WEIGHTS

    low_align: list[float] = []
    high_align: list[float] = []
    low_trail: list[float] = []
    high_trail: list[float] = []
    low_mat: list[float] = []
    high_mat: list[float] = []

    for s in series:
        delta = _num(s.get("stop_hot_cold_trail_delta"))
        if delta is None:
            continue
        triggered = delta < candidate
        align = _num(s.get("aligned_pct"))
        mat = _num(s.get("maturity_stop_quality_score"))

        if triggered:
            if align is not None:
                low_align.append(align)
            low_trail.append(delta)
            if mat is not None:
                low_mat.append(mat)
        else:
            if align is not None:
                high_align.append(align)
            high_trail.append(delta)
            if mat is not None:
                high_mat.append(mat)

    trigger_rate = len(low_align) / max(len(low_align) + len(high_align), 1) if low_align else 0.0
    align_sep = _separation(low_align, high_align)
    trail_sep = _separation(low_trail, high_trail)  # higher trail on non-triggered is good
    mat_sep = _separation(low_mat, high_mat) / 100.0 if low_mat and high_mat else 0.0

    early = _early_detection_bonus(
        series,
        lambda s: (_num(s.get("stop_hot_cold_trail_delta")) or 1) < candidate,
        yield_key="maturity_composite_score",
    )

    guard = _trigger_guard_score(trigger_rate, cap=0.40)
    contributions = {
        "alignment_separation": round(align_sep * weights.get("alignment_separation", 0.35), 4),
        "trail_delta_separation": round(trail_sep * weights.get("trail_delta_separation", 0.25), 4),
        "maturity_stop_separation": round(mat_sep * weights.get("maturity_stop_separation", 0.20), 4),
        "early_detection": round(early * weights.get("early_detection", 0.10), 4),
        "trigger_guard": round(guard * weights.get("trigger_guard", 0.10), 4),
    }
    raw = sum(contributions.values())

    return {
        "score": round(max(0.0, raw), 4),
        "trigger_rate": round(trigger_rate, 3),
        "metric_contributions": contributions,
        "raw_separations": {
            "alignment": round(align_sep, 4),
            "trail_delta": round(trail_sep, 4),
            "maturity_stop": round(mat_sep * 100, 2) if mat_sep else None,
        },
        "low_delta_aligned_pct": round(_avg(low_align), 3) if low_align else None,
        "high_delta_aligned_pct": round(_avg(high_align), 3) if high_align else None,
        "triggered_days": len(low_align),
        "baseline_days": len(high_align),
        "early_detection_bonus": round(early, 4),
        "trigger_guard": round(guard, 3),
    }


def scan_candidates(
    series: list[dict[str, Any]],
    scorer,
    current: float,
    band: dict[str, float],
    step: float = 0.01,
) -> list[dict[str, Any]]:
    """Score every candidate in safe band; return sorted by score desc."""
    lo, hi = float(band.get("min", current)), float(band.get("max", current))
    results: list[dict[str, Any]] = []
    t = lo
    while t <= hi + 1e-9:
        t = round(t, 3)
        meta = scorer(series, t)
        results.append({"value": t, **meta})
        t = round(t + step, 3)
    results.sort(key=lambda x: x["score"], reverse=True)
    return results


def passes_asymmetric_bar(
    direction: str,
    score_delta: float,
    confidence: str,
    cfg: dict[str, Any],
) -> bool:
    """Loosening requires stronger evidence than tightening."""
    asym = (cfg.get("scoring") or {}).get("asymmetric") or {}
    tighten_min = float(asym.get("tighten_min_score_delta", 0.002))
    loosen_mult = float(asym.get("loosen_score_delta_mult", 2.0))
    loosen_min_conf = str(asym.get("loosen_min_confidence", "medium"))

    conf_rank = {"low": 0, "medium": 1, "high": 2}
    if direction == "tighten":
        return score_delta >= tighten_min
    # loosen
    if score_delta < tighten_min * loosen_mult:
        return False
    return conf_rank.get(confidence, 0) >= conf_rank.get(loosen_min_conf, 1)