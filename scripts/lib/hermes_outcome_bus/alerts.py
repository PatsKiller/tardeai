"""Trend-based alerts and bus-native maturity mapping for outcome-bus-v1."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _acfg(cfg: dict[str, Any]) -> dict[str, Any]:
    return cfg.get("alerts") or {}


def _series_values(series: list[dict[str, Any]], key: str) -> list[tuple[str, float]]:
    out: list[tuple[str, float]] = []
    for s in series:
        v = s.get(key)
        if v is None:
            continue
        try:
            out.append((str(s.get("day") or s.get("at") or ""), float(v)))
        except (TypeError, ValueError):
            continue
    return out


def _consecutive_days_below(
    series: list[dict[str, Any]],
    key: str,
    threshold: float,
    min_days: int,
) -> tuple[bool, int, str | None]:
    """True when the last N consecutive daily points are all below threshold."""
    vals = _series_values(series, key)
    if len(vals) < min_days:
        return False, 0, None
    streak = 0
    since = None
    for day, v in reversed(vals):
        if v < threshold:
            streak += 1
            since = day or since
        else:
            break
    return streak >= min_days, streak, since


def _consecutive_days_condition(
    series: list[dict[str, Any]],
    key: str,
    predicate,
    min_days: int,
) -> tuple[bool, int, str | None]:
    vals = [(str(s.get("day") or ""), s.get(key)) for s in series if s.get(key) is not None]
    if len(vals) < min_days:
        return False, 0, None
    streak = 0
    since = None
    for day, v in reversed(vals):
        try:
            fv = float(v)
        except (TypeError, ValueError):
            break
        if predicate(fv):
            streak += 1
            since = day or since
        else:
            break
    return streak >= min_days, streak, since


def _hit_rate_declining(series: list[dict[str, Any]], cfg: dict[str, Any]) -> dict[str, Any] | None:
    ac = _acfg(cfg)
    window = int(ac.get("hit_rate_window_days", 7))
    drop_pp = float(ac.get("hit_rate_decline_pp", 0.08))
    flat_pp = float(ac.get("hit_rate_flat_pp", 0.02))

    vals = _series_values(series, "hit_rate_promotions")
    if len(vals) < 2:
        return None

    recent = vals[-1][1]
    # Compare to earliest point within window (approx: first point if series shorter than window)
    baseline = vals[0][1] if len(vals) <= window else vals[-window][1]
    delta = recent - baseline
    if delta <= -drop_pp:
        return {
            "id": "hit_rate_declining",
            "severity": "warning",
            "since": vals[0][0],
            "detail": (
                f"hit_rate_promotions fell {abs(delta):.1%} over {min(window, len(vals) - 1)}d "
                f"({baseline:.1%} → {recent:.1%})"
            ),
            "metrics": {
                "baseline": baseline,
                "current": recent,
                "delta_pp": delta,
                "window_days": min(window, len(vals) - 1),
            },
        }
    if abs(delta) <= flat_pp and recent < baseline:
        return None  # minor drift — not an alert
    return None


def _efficiency_declining(series: list[dict[str, Any]], cfg: dict[str, Any]) -> dict[str, Any] | None:
    ac = _acfg(cfg)
    threshold = float(ac.get("efficiency_score_floor", 0.55))
    min_days = int(ac.get("efficiency_consecutive_days", 3))
    active, streak, since = _consecutive_days_below(series, "resource_efficiency_score", threshold, min_days)
    if not active:
        return None
    current = _series_values(series, "resource_efficiency_score")[-1][1]
    return {
        "id": "efficiency_declining",
        "severity": "warning",
        "since": since,
        "detail": f"resource_efficiency.score below {threshold:.2f} for {streak} consecutive days (now {current:.3f})",
        "metrics": {"threshold": threshold, "streak_days": streak, "current_score": current},
    }


def _scope_creep(series: list[dict[str, Any]], cfg: dict[str, Any]) -> dict[str, Any] | None:
    ac = _acfg(cfg)
    window = int(ac.get("scope_creep_window_days", 14))
    growth_pct = float(ac.get("scope_growth_pct", 0.15))
    flat_pp = float(ac.get("hit_rate_flat_pp", 0.02))

    sym_vals = _series_values(series, "symbols_in_bus")
    hr_vals = _series_values(series, "hit_rate_promotions")
    if len(sym_vals) < 2 or len(hr_vals) < 2:
        return None

    sym_baseline = sym_vals[0][1] if len(sym_vals) <= window else sym_vals[-window][1]
    sym_current = sym_vals[-1][1]
    if sym_baseline <= 0:
        return None
    growth = (sym_current - sym_baseline) / sym_baseline

    hr_baseline = hr_vals[0][1] if len(hr_vals) <= window else hr_vals[-window][1]
    hr_current = hr_vals[-1][1]
    hr_delta = hr_current - hr_baseline
    hit_flat_or_down = hr_delta <= flat_pp

    if growth > growth_pct and hit_flat_or_down:
        return {
            "id": "scope_creep",
            "severity": "warning",
            "since": sym_vals[0][0],
            "detail": (
                f"symbols_in_bus grew {growth:.1%} over {min(window, len(sym_vals) - 1)}d "
                f"({int(sym_baseline)} → {int(sym_current)}) while hit_rate_promotions "
                f"{'declined' if hr_delta < -flat_pp else 'stayed flat'} ({hr_baseline:.1%} → {hr_current:.1%})"
            ),
            "metrics": {
                "symbol_growth_pct": growth,
                "hit_rate_delta_pp": hr_delta,
                "symbols_baseline": sym_baseline,
                "symbols_current": sym_current,
            },
        }
    return None


def _stop_quality_divergence(series: list[dict[str, Any]], cfg: dict[str, Any]) -> dict[str, Any] | None:
    ac = _acfg(cfg)
    min_delta_pp = float(ac.get("stop_hot_cold_delta_pp", 0.15))
    min_days = int(ac.get("stop_divergence_consecutive_days", 5))

    active, streak, since = _consecutive_days_condition(
        series,
        "stop_hot_cold_trail_delta",
        lambda d: d < min_delta_pp,
        min_days,
    )
    if not active:
        return None
    current = _series_values(series, "stop_hot_cold_trail_delta")
    delta = current[-1][1] if current else None
    delta_str = f"{delta:.1%}" if delta is not None else "n/a"
    return {
        "id": "stop_quality_divergence",
        "severity": "warning",
        "since": since,
        "detail": (
            f"Hot vs Cold trail_activation_rate delta below {min_delta_pp:.0%} "
            f"for {streak} consecutive days (now {delta_str})"
        ),
        "metrics": {"min_delta_pp": min_delta_pp, "streak_days": streak, "current_delta_pp": delta},
    }


def evaluate_alerts(
    bus: dict[str, Any],
    trend: dict[str, Any],
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate conservative trend alerts from bus history."""
    cfg = cfg or {}
    ac = _acfg(cfg)
    series = trend.get("series") or []
    history_window = int(ac.get("history_window_days", 14))

    detectors = [_hit_rate_declining, _efficiency_declining, _scope_creep, _stop_quality_divergence]
    active: list[dict[str, Any]] = []
    for fn in detectors:
        alert = fn(series, cfg)
        if alert:
            active.append(alert)

    return {
        "active": active,
        "active_count": len(active),
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "history_window_days": history_window,
        "trend_points": len(series),
        "enabled": ac.get("enabled", True),
    }


def _gate_pass(label: str, passed: bool, value: Any, target: str) -> dict[str, Any]:
    return {"label": label, "pass": passed, "value": value, "target": target}


def _rating_from_gates(gates: list[dict[str, Any]]) -> tuple[int, int, int]:
    total = len(gates)
    passed = sum(1 for g in gates if g.get("pass"))
    if total == 0:
        return 1, 0, 0
    share = passed / total
    if passed == total:
        rating = 4
    elif share >= 0.75:
        rating = 3
    elif share >= 0.5:
        rating = 2
    else:
        rating = 1
    return rating, passed, total


def build_maturity_status(
    bus: dict[str, Any],
    trend: dict[str, Any],
    alerts: dict[str, Any],
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Delegate to maturity-v2 composite scorer (backward-compatible import path)."""
    from .maturity import build_maturity_status as _build_v2
    return _build_v2(bus, trend, alerts, cfg)


def _build_maturity_status_legacy(
    bus: dict[str, Any],
    trend: dict[str, Any],
    alerts: dict[str, Any],
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Legacy gate-based maturity (v1) — retained for reference/tests only."""
    cfg = cfg or {}
    mc = cfg.get("maturity") or {}
    global_m = bus.get("global") or {}
    resource = bus.get("resource_efficiency") or {}
    stop_q = bus.get("stop_quality") or {}
    series = trend.get("series") or []
    active_ids = {a.get("id") for a in (alerts.get("active") or [])}

    hr = global_m.get("hit_rate_promotions")
    eff = resource.get("score") or resource.get("resource_efficiency_score")
    sym_count = len(bus.get("by_symbol") or {})
    live = resource.get("live_universe")
    baseline_live = float((cfg.get("resource_efficiency") or {}).get("pre_governor_live_universe", 4171))
    gov_fb = len(bus.get("feedback_to_governor") or [])
    res_fb = len(bus.get("feedback_to_research") or [])

    hot_trail = (stop_q.get("by_tier") or {}).get("hot", {}).get("trail_activation_rate")
    cold_trail = (stop_q.get("by_tier") or {}).get("cold", {}).get("trail_activation_rate")
    trail_delta = None
    if hot_trail is not None and cold_trail is not None:
        trail_delta = float(hot_trail) - float(cold_trail)

    min_hr = float(mc.get("outcome_hit_rate_min", 0.35))
    min_eff = float(mc.get("scope_efficiency_min", 0.55))
    max_scope_growth = float(mc.get("scope_growth_max_pct", 0.15))

    sym_vals = _series_values(series, "symbols_in_bus")
    scope_growth = None
    if len(sym_vals) >= 2 and sym_vals[0][1] > 0:
        scope_growth = (sym_vals[-1][1] - sym_vals[0][1]) / sym_vals[0][1]

    outcome_gates = [
        _gate_pass("promotion_hit_rate", hr is not None and float(hr) >= min_hr, hr, f">={min_hr:.0%}"),
        _gate_pass("graded_claims", int(global_m.get("graded_claims_90d") or 0) >= int(mc.get("min_graded_claims", 50)),
                   global_m.get("graded_claims_90d"), ">=50"),
        _gate_pass("no_hit_rate_declining_alert", "hit_rate_declining" not in active_ids, True, "no active alert"),
        _gate_pass("positive_trade_r", global_m.get("avg_realized_r_trades_90d") is None
                   or float(global_m.get("avg_realized_r_trades_90d") or 0) >= 0,
                   global_m.get("avg_realized_r_trades_90d"), ">=0"),
    ]
    oy_rating, oy_pass, oy_total = _rating_from_gates(outcome_gates)

    scope_gates = [
        _gate_pass("resource_efficiency", eff is not None and float(eff) >= min_eff, eff, f">={min_eff:.2f}"),
        _gate_pass("universe_vs_baseline", live is not None and float(live) <= baseline_live * 0.25,
                   live, f"<={int(baseline_live * 0.25)}"),
        _gate_pass("no_scope_creep_alert", "scope_creep" not in active_ids, True, "no active alert"),
        _gate_pass("scope_growth_bounded", scope_growth is None or scope_growth <= max_scope_growth,
                   round(scope_growth, 3) if scope_growth is not None else None, f"<={max_scope_growth:.0%}"),
    ]
    sd_rating, sd_pass, sd_total = _rating_from_gates(scope_gates)

    closed_gates = [
        _gate_pass("governor_feedback_active", gov_fb >= int(mc.get("min_governor_feedback", 1)), gov_fb, ">=1"),
        _gate_pass("research_feedback_active", res_fb >= 0, res_fb, "wired"),
        _gate_pass("stop_tier_advantage", trail_delta is None or trail_delta >= float(mc.get("stop_hot_cold_min_pp", 0.12)),
                   round(trail_delta, 3) if trail_delta is not None else None, ">=12pp hot-cold"),
        _gate_pass("no_efficiency_declining_alert", "efficiency_declining" not in active_ids, True, "no active alert"),
    ]
    cl_rating, cl_pass, cl_total = _rating_from_gates(closed_gates)

    ratings = [oy_rating, sd_rating, cl_rating]
    if any(r <= 2 for r in ratings) or len(active_ids) >= 2:
        overall = "at_risk"
    elif all(r >= 4 for r in ratings):
        overall = "mature"
    else:
        overall = "maturing"

    maturity_score = round(sum(ratings) / len(ratings), 2) if ratings else None
    trend_label = _maturity_trend_from_series(series, maturity_score)

    return {
        "outcome_yield": {
            "rating": oy_rating,
            "gates_passed": oy_pass,
            "gates_total": oy_total,
            "gates": outcome_gates,
        },
        "scope_discipline": {
            "rating": sd_rating,
            "gates_passed": sd_pass,
            "gates_total": sd_total,
            "gates": scope_gates,
        },
        "closed_loop": {
            "rating": cl_rating,
            "gates_passed": cl_pass,
            "gates_total": cl_total,
            "gates": closed_gates,
        },
        "overall_status": overall,
        "maturity_score": maturity_score,
        "trend": trend_label,
        "symbols_in_bus": sym_count,
        "active_alerts": len(active_ids),
        "design_ref": "docs/design/HERMES_MATURITY_5_DESIGN.md",
        "note": "Bus-native maturity proxy — full 5/5 still requires hermes_maturity_gates.py DB persistence",
    }


_STATUS_RANK = {"at_risk": 1, "maturing": 2, "mature": 3}


def _maturity_trend_from_series(series: list[dict[str, Any]], current_score: float | None) -> str:
    """Compare current maturity score to ~7d ago in bus history."""
    scores = [s.get("maturity_score") for s in series if s.get("maturity_score") is not None]
    if current_score is None or len(scores) < 2:
        return "stable"
    prior = float(scores[0]) if len(scores) <= 7 else float(scores[-7])
    delta = float(current_score) - prior
    if delta > 0.25:
        return "improving"
    if delta < -0.25:
        return "declining"
    return "stable"


def build_maturity_trend(trend: dict[str, Any]) -> dict[str, Any]:
    """Delegate to maturity-v2 trend builder."""
    from .maturity import build_maturity_trend as _build_v2
    return _build_v2(trend)


def _build_maturity_trend_legacy(trend: dict[str, Any]) -> dict[str, Any]:
    """Legacy 1–5 maturity trend — retained for reference only."""
    series = trend.get("series") or []
    points = []
    for s in series:
        status = s.get("maturity_overall_status")
        score = s.get("maturity_score")
        if status is None and score is None:
            continue
        points.append({
            "day": s.get("day"),
            "at": s.get("at"),
            "overall_status": status,
            "maturity_score": score,
            "outcome_yield_rating": s.get("maturity_outcome_yield"),
            "scope_discipline_rating": s.get("maturity_scope_discipline"),
            "closed_loop_rating": s.get("maturity_closed_loop"),
            "active_alert_count": s.get("active_alert_count"),
        })
    scores = [float(p["maturity_score"]) for p in points if p.get("maturity_score") is not None]
    statuses = [p.get("overall_status") for p in points if p.get("overall_status")]
    trend_label = "stable"
    if len(scores) >= 2:
        delta = scores[-1] - scores[0]
        if delta > 0.25:
            trend_label = "improving"
        elif delta < -0.25:
            trend_label = "declining"
    elif len(statuses) >= 2:
        first_r = _STATUS_RANK.get(str(statuses[0]), 2)
        last_r = _STATUS_RANK.get(str(statuses[-1]), 2)
        if last_r > first_r:
            trend_label = "improving"
        elif last_r < first_r:
            trend_label = "declining"
    return {
        "count": len(points),
        "series": points,
        "trend": trend_label,
        "current_score": scores[-1] if scores else None,
        "delta_window": round(scores[-1] - scores[0], 2) if len(scores) >= 2 else None,
        "current_status": statuses[-1] if statuses else None,
    }