"""Counterfactual evidence for threshold proposals — help/hurt examples + impact estimates."""
from __future__ import annotations

from typing import Any, Callable


def _num(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _day_row(s: dict[str, Any]) -> dict[str, Any]:
    return {
        "day": s.get("day"),
        "hit_rate_promotions": _num(s.get("hit_rate_promotions")),
        "resource_efficiency_score": _num(s.get("resource_efficiency_score")),
        "stop_hot_cold_trail_delta": _num(s.get("stop_hot_cold_trail_delta")),
        "aligned_pct": _num(s.get("aligned_pct")),
        "maturity_composite_score": _num(s.get("maturity_composite_score")),
        "regime_label": s.get("regime_label"),
    }


def build_counterfactual_evidence(
    series: list[dict[str, Any]],
    *,
    proposed_trigger_fn: Callable[[dict[str, Any]], bool],
    current_trigger_fn: Callable[[dict[str, Any]], bool],
    window_days: int = 14,
    limit: int = 5,
) -> dict[str, Any]:
    """Top examples where proposed threshold would help vs hurt."""
    tail = series[-window_days:] if window_days > 0 else series

    help_rows: list[tuple[float, dict[str, Any]]] = []
    hurt_rows: list[tuple[float, dict[str, Any]]] = []

    for s in tail:
        hr = _num(s.get("hit_rate_promotions"))
        mat = _num(s.get("maturity_composite_score"))
        eff = _num(s.get("resource_efficiency_score"))
        proposed_fires = proposed_trigger_fn(s)
        current_fires = current_trigger_fn(s)

        stress = (1.0 - hr) if hr is not None else (1.0 - eff if eff is not None else 0.5)
        yield_score = hr if hr is not None else (mat / 100.0 if mat is not None else 0.5)

        if proposed_fires and not current_fires and stress > 0.15:
            help_rows.append((stress, _day_row(s)))
        elif proposed_fires and yield_score > 0.38:
            help_rows.append((yield_score * 0.5, _day_row(s)))
        elif proposed_fires and current_fires and yield_score < 0.30:
            hurt_rows.append((1.0 - yield_score, _day_row(s)))
        elif not proposed_fires and current_fires and stress > 0.20:
            hurt_rows.append((stress * 0.8, _day_row(s)))

    help_rows.sort(key=lambda x: x[0], reverse=True)
    hurt_rows.sort(key=lambda x: x[0], reverse=True)

    proposed_count = sum(1 for s in tail if proposed_trigger_fn(s))
    current_count = sum(1 for s in tail if current_trigger_fn(s))
    delta_triggers = proposed_count - current_count

    hr_vals = [_num(s.get("hit_rate_promotions")) for s in tail if _num(s.get("hit_rate_promotions")) is not None]
    avg_hr = sum(hr_vals) / len(hr_vals) if hr_vals else None

    fp_impact = round(max(0, delta_triggers) / max(len(tail), 1) * (1.0 - (avg_hr or 0.35)), 3)
    fn_impact = round(max(0, -delta_triggers) / max(len(tail), 1) * (avg_hr or 0.35), 3)

    resource_cost = round(abs(delta_triggers) * 0.02, 3)
    outcome_yield_impact = round(
        (fp_impact * -0.5) + (fn_impact * -0.3) + (len(help_rows) * 0.01),
        3,
    )

    primary_metric = None
    if help_rows:
        primary_metric = round(help_rows[0][0], 3)

    return {
        "window_days": window_days,
        "primary_metric_improvement": primary_metric,
        "estimated_false_positive_impact": fp_impact,
        "estimated_false_negative_impact": fn_impact,
        "coverage_impact": round(proposed_count / max(len(tail), 1), 3),
        "resource_cost_impact": resource_cost,
        "expected_outcome_yield_impact": outcome_yield_impact,
        "proposed_trigger_count": proposed_count,
        "current_trigger_count": current_count,
        "trigger_delta": delta_triggers,
        "top_examples_helped": [r for _, r in help_rows[:limit]],
        "top_examples_hurt": [r for _, r in hurt_rows[:limit]],
        "counterfactual_required": True,
        "has_sufficient_examples": len(help_rows) >= 1,
    }


def attach_counterfactual_to_proposal(
    proposal: dict[str, Any],
    series: list[dict[str, Any]],
    *,
    proposed_trigger_fn: Callable[[dict[str, Any]], bool],
    current_trigger_fn: Callable[[dict[str, Any]], bool],
    window_days: int = 14,
) -> dict[str, Any]:
    """Merge counterfactual block into proposal evidence."""
    cf = build_counterfactual_evidence(
        series,
        proposed_trigger_fn=proposed_trigger_fn,
        current_trigger_fn=current_trigger_fn,
        window_days=window_days,
    )
    out = dict(proposal)
    evidence = dict(out.get("evidence") or {})
    evidence["counterfactual_evidence"] = cf
    evidence["estimated_false_positive_impact"] = cf["estimated_false_positive_impact"]
    evidence["estimated_false_negative_impact"] = cf["estimated_false_negative_impact"]
    evidence["resource_cost_impact"] = cf["resource_cost_impact"]
    evidence["expected_outcome_yield_impact"] = cf["expected_outcome_yield_impact"]
    evidence["top_examples_helped"] = cf["top_examples_helped"]
    evidence["top_examples_hurt"] = cf["top_examples_hurt"]
    out["evidence"] = evidence
    out["counterfactual_evidence"] = cf
    return out