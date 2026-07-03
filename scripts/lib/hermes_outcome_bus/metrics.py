"""Resource efficiency score + stop-quality enrichment for outcome_bus.json v1."""
from __future__ import annotations

from typing import Any

CALCULATION_VERSION = "v1.1"


def _clamp01(v: float) -> float:
    return max(0.0, min(1.0, float(v)))


def calculate_resource_efficiency_score(
    hit_rate_promotions: float,
    research_rows_7d: int,
    positive_outcomes_7d: int,
    api_calls_7d: int = 0,
    *,
    universe_size_change_pct: float = 0.0,
) -> tuple[float, dict[str, Any]]:
    """v1.1 conservative formula — outcome yield outranks throughput.

    Components:
      45% promotion hit rate (capped at 0.55)
      35% research efficiency (rows per real positive outcome; target ≤45 rows)
      20% API overhead (calls per research row; lower is better)
    """
    if research_rows_7d == 0:
        return 0.5, {"api_overhead_factor": 0.0}

    hit_component = min(float(hit_rate_promotions), 0.55) / 0.55 * 0.45

    positive = max(0, int(positive_outcomes_7d))
    if positive > 0:
        rows_per_outcome = research_rows_7d / positive
        efficiency_component = max(0.0, 1.0 - (rows_per_outcome / 45.0)) * 0.35
    else:
        rows_per_outcome = None
        efficiency_component = 0.15

    if api_calls_7d > 0 and research_rows_7d > 0:
        calls_per_row = api_calls_7d / research_rows_7d
        overhead_component = max(0.0, 1.0 - (calls_per_row / 3.0)) * 0.20
    else:
        calls_per_row = 0.0
        overhead_component = 0.10

    score = round(_clamp01(hit_component + efficiency_component + overhead_component), 3)
    meta = {
        "rows_per_outcome": round(rows_per_outcome, 1) if rows_per_outcome is not None else None,
        "api_overhead_factor": round(calls_per_row, 3),
        "universe_stability": round(1.0 - abs(float(universe_size_change_pct)), 3),
    }
    return score, meta


def infer_trend_7d(
    current_score: float,
    prior_score: float | None,
    *,
    score_delta_threshold: float = 0.02,
) -> str:
    """Human-readable 7d trend label for the operator panel."""
    if prior_score is None:
        return "stable"
    delta = current_score - prior_score
    if delta > score_delta_threshold:
        return "improving"
    if delta < -score_delta_threshold:
        return "declining"
    return "stable"


def build_stop_correlations(by_tier: dict[str, Any]) -> list[dict[str, Any]]:
    """Surface simple tier deltas for the operator (v1 heuristics)."""
    hot = by_tier.get("hot") or {}
    warm = by_tier.get("warm") or {}
    cold = by_tier.get("cold") or {}
    out: list[dict[str, Any]] = []

    def _delta(metric: str) -> float | None:
        h, c = hot.get(metric), cold.get(metric)
        if h is None or c is None:
            return None
        return float(h) - float(c)

    trail_delta = _delta("trail_activation_rate")
    if trail_delta is not None and abs(trail_delta) >= 0.05:
        pct = int(round(trail_delta * 100))
        direction = "higher" if trail_delta > 0 else "lower"
        out.append({
            "metric": "trail_activation_rate",
            "hot_vs_cold_delta_pct": pct,
            "hot_vs_cold_trail_activation_delta": round(trail_delta, 3),
            "note": f"Hot tier symbols have {abs(pct)}% {direction} trail activation rate vs Cold",
        })

    align_delta = _delta("aligned_pct")
    if align_delta is not None and abs(align_delta) >= 0.05:
        pct = int(round(align_delta * 100))
        direction = "higher" if align_delta > 0 else "lower"
        out.append({
            "metric": "aligned_pct",
            "hot_vs_cold_delta_pct": pct,
            "note": f"Hot tier stop alignment is {abs(pct)}% {direction} than Cold",
        })

    mae_delta = _delta("mae_exceeded_planned_stop_pct")
    if mae_delta is not None and abs(mae_delta) >= 0.03:
        pct = int(round(mae_delta * 100))
        out.append({
            "metric": "mae_exceeded_planned_stop_pct",
            "hot_vs_cold_delta_pct": pct,
            "note": f"Hot tier MAE-exceeded-stop rate differs from Cold by {pct}pp",
        })

    if not out and hot.get("sample_n") and warm.get("sample_n"):
        out.append({
            "metric": "insufficient_spread",
            "note": "Tier samples present — correlations will appear as spread grows",
        })
    return out


def compute_resource_efficiency_score(
    global_m: dict[str, Any],
    resource: dict[str, Any],
    cfg: dict[str, Any],
    *,
    positive_outcomes_7d: int = 0,
    universe_size_change_pct: float = 0.0,
    prior_score_7d: float | None = None,
) -> dict[str, Any]:
    """Build canonical resource_efficiency section + backward-compatible aliases."""
    hit_rate = float(global_m.get("hit_rate_promotions") or 0.0)
    research_rows = int(global_m.get("throughput_research_rows_7d") or 0)
    positive = max(0, int(positive_outcomes_7d))
    api_calls = int(resource.get("hermes_api_calls_7d") or global_m.get("hermes_api_calls_7d") or 0)

    score, meta = calculate_resource_efficiency_score(
        hit_rate_promotions=hit_rate,
        research_rows_7d=research_rows,
        positive_outcomes_7d=positive,
        api_calls_7d=api_calls,
        universe_size_change_pct=universe_size_change_pct,
    )

    rows_per_outcome = meta.get("rows_per_outcome")
    trend_7d = infer_trend_7d(score, prior_score_7d)

    resource["score"] = score
    resource["components"] = {
        "hit_rate_promotions": round(hit_rate, 3),
        "research_rows_per_positive_outcome": rows_per_outcome,
        "api_overhead_factor": meta.get("api_overhead_factor"),
        "universe_stability": meta.get("universe_stability"),
    }
    resource["trend_7d"] = trend_7d
    resource["calculation_version"] = CALCULATION_VERSION

    resource["resource_efficiency_score"] = score
    resource["score_components"] = resource["components"]
    resource["positive_outcomes_7d"] = positive
    resource["research_rows_per_positive_outcome"] = rows_per_outcome
    resource["universe_size_change_pct_7d"] = round(universe_size_change_pct, 3)
    resource["prior_score_7d"] = prior_score_7d

    llm_calls = max(int(global_m.get("throughput_external_calls_7d") or 0), 1)
    resource["llm_calls_per_positive_outcome"] = (
        round(llm_calls / positive, 2) if positive else None
    )

    live = int(resource.get("live_universe") or 0)
    baseline_live = float((cfg.get("resource_efficiency") or {}).get("pre_governor_live_universe", 4171) or 4171)
    resource["live_universe_vs_baseline_pct"] = round(live / baseline_live, 3) if baseline_live else None

    return resource