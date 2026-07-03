"""Composite maturity scoring (v2) — 0–100 with weighted sub-components."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
MATURITY_CFG_PATH = PROJECT_ROOT / "config" / "hermes_maturity.yaml"
MATURITY_SNAPSHOT_PATH = PROJECT_ROOT / "state" / "hermes" / "hermes_maturity.json"

_TIER_ORDER = ["nascent", "developing", "mature", "optimized"]
_STATUS_RANK = {"nascent": 1, "developing": 2, "mature": 3, "optimized": 4, "at_risk": 1, "maturing": 2}


def load_maturity_config(path: Path | None = None) -> dict[str, Any]:
    try:
        import yaml
        return yaml.safe_load((path or MATURITY_CFG_PATH).read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def _clamp100(v: float) -> float:
    return max(0.0, min(100.0, float(v)))


def _linear_score(value: float | None, floor: float, target: float) -> float:
    if value is None:
        return 50.0
    if value >= target:
        return 100.0
    if value <= floor:
        return 0.0
    return _clamp100((float(value) - floor) / max(target - floor, 1e-9) * 100.0)


def _component_trend(series: list[dict[str, Any]], key: str, current: float) -> str:
    vals = [float(s[key]) for s in series if s.get(key) is not None]
    if len(vals) < 2:
        return "stable"
    prior = vals[0] if len(vals) <= 7 else vals[-7]
    delta = current - prior
    if delta > 3:
        return "improving"
    if delta < -3:
        return "declining"
    return "stable"


def _score_outcome_yield(bus: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    c = (cfg.get("components") or {}).get("outcome_yield") or {}
    g = bus.get("global") or {}
    hr = g.get("hit_rate_promotions")
    thr = g.get("hit_rate_trades")
    graded = int(g.get("graded_claims_90d") or 0)
    avg_r = g.get("avg_realized_r_trades_90d")

    hr_score = _linear_score(hr, float(c.get("hit_rate_floor", 0.25)), float(c.get("hit_rate_target", 0.40)))
    thr_score = _linear_score(thr, 0.35, 0.55) if thr is not None else 50.0
    sample_score = _clamp100(graded / max(int(c.get("graded_claims_cap", 200)), 1) * 100.0)
    r_bonus = 10.0 if avg_r is not None and float(avg_r) >= 0 else 0.0

    tw = float(c.get("trade_hit_weight", 0.25))
    score = _clamp100(hr_score * (1 - tw) + thr_score * tw * 0.5 + sample_score * 0.3 + r_bonus)
    if graded < int(c.get("min_graded_claims", 50)):
        score = min(score, 55.0)

    return {
        "score": round(score, 1),
        "weight": float((cfg.get("weights") or {}).get("outcome_yield", 0.30)),
        "signals": {
            "hit_rate_promotions": hr,
            "hit_rate_trades": thr,
            "graded_claims_90d": graded,
            "avg_realized_r_trades_90d": avg_r,
        },
    }


def _score_scope_discipline(bus: dict[str, Any], alerts: dict[str, Any], trend: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    c = (cfg.get("components") or {}).get("scope_discipline") or {}
    resource = bus.get("resource_efficiency") or {}
    eff = resource.get("score") or resource.get("resource_efficiency_score")
    live = resource.get("live_universe")
    baseline = float((cfg.get("_resource_baseline") or 4171))

    eff_score = _linear_score(eff, float(c.get("efficiency_floor", 0.45)), float(c.get("efficiency_target", 0.60)))
    universe_score = 100.0
    if live is not None and baseline > 0:
        pct = float(live) / baseline
        cap = float(c.get("universe_cap_pct", 0.25))
        universe_score = _clamp100(100.0 - max(0.0, pct - cap) / cap * 100.0) if pct > cap else 100.0

    series = trend.get("series") or []
    scope_growth = None
    sym_vals = [(s.get("symbols_in_bus")) for s in series if s.get("symbols_in_bus") is not None]
    if len(sym_vals) >= 2 and sym_vals[0] and sym_vals[0] > 0:
        scope_growth = (sym_vals[-1] - sym_vals[0]) / sym_vals[0]

    growth_score = 100.0
    if scope_growth is not None:
        max_g = float(c.get("max_scope_growth_pct", 0.15))
        if scope_growth > max_g:
            growth_score = _clamp100(100.0 - (scope_growth - max_g) / max_g * 100.0)

    alert_pen = 15.0 if "scope_creep" in {a.get("id") for a in (alerts.get("active") or [])} else 0.0
    score = _clamp100(eff_score * 0.45 + universe_score * 0.30 + growth_score * 0.25 - alert_pen)

    return {
        "score": round(score, 1),
        "weight": float((cfg.get("weights") or {}).get("scope_discipline", 0.25)),
        "signals": {
            "resource_efficiency_score": eff,
            "live_universe": live,
            "scope_growth_pct": round(scope_growth, 3) if scope_growth is not None else None,
            "write_reduction_pct": resource.get("write_reduction_vs_baseline_pct"),
        },
    }


def _score_stop_quality(bus: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    c = (cfg.get("components") or {}).get("stop_quality") or {}
    stop_q = bus.get("stop_quality") or {}
    by_tier = stop_q.get("by_tier") or {}
    hot = (by_tier.get("hot") or {}).get("trail_activation_rate")
    cold = (by_tier.get("cold") or {}).get("trail_activation_rate")
    trail_delta = float(hot) - float(cold) if hot is not None and cold is not None else None

    delta_score = _linear_score(trail_delta, 0.05, float(c.get("trail_delta_target", 0.15))) if trail_delta is not None else 50.0
    align_score = _linear_score(stop_q.get("aligned_pct"), 0.40, float(c.get("aligned_target", 0.60)))
    sample_n = int(stop_q.get("sample_n") or 0)
    sample_pen = 30.0 if sample_n < int(c.get("min_sample_n", 5)) else 0.0

    score = _clamp100(delta_score * 0.55 + align_score * 0.45 - sample_pen)
    return {
        "score": round(score, 1),
        "weight": float((cfg.get("weights") or {}).get("stop_quality", 0.20)),
        "signals": {
            "trail_hot_cold_delta": round(trail_delta, 3) if trail_delta is not None else None,
            "aligned_pct": stop_q.get("aligned_pct"),
            "sample_n": sample_n,
        },
    }


def _score_feedback_loop(bus: dict[str, Any], alerts: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    c = (cfg.get("components") or {}).get("feedback_loop") or {}
    gov_fb = len(bus.get("feedback_to_governor") or [])
    res_fb = len(bus.get("feedback_to_research") or [])
    active = len(alerts.get("active") or [])

    gov_score = 100.0 if gov_fb >= int(c.get("min_governor_feedback", 1)) else 40.0
    res_score = 80.0 if res_fb > 0 else 50.0
    alert_pen = float(c.get("alert_penalty_per_active", 8)) * active
    score = _clamp100(gov_score * 0.5 + res_score * 0.3 + 20.0 - alert_pen)

    return {
        "score": round(score, 1),
        "weight": float((cfg.get("weights") or {}).get("feedback_loop", 0.15)),
        "signals": {
            "governor_feedback_count": gov_fb,
            "research_feedback_count": res_fb,
            "active_alerts": active,
        },
    }


def _score_research_actionability(bus: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    c = (cfg.get("components") or {}).get("research_actionability") or {}
    g = bus.get("global") or {}
    res_hr = g.get("hit_rate_research_actioned")
    hr_score = _linear_score(res_hr, 0.30, float(c.get("research_hit_target", 0.50)))

    by_tag = bus.get("by_tag") or {}
    pos = sum(1 for m in by_tag.values() if (m.get("lift") or 0) >= float(c.get("positive_tag_lift_min", 0.02)))
    tag_ratio = pos / max(len(by_tag), 1)
    tag_score = _clamp100(tag_ratio * 100.0)

    score = _clamp100(hr_score * 0.65 + tag_score * 0.35)
    return {
        "score": round(score, 1),
        "weight": float((cfg.get("weights") or {}).get("research_actionability", 0.10)),
        "signals": {
            "hit_rate_research_actioned": res_hr,
            "positive_lift_tags": pos,
            "tags_total": len(by_tag),
        },
    }


def _resolve_tier(composite: float, components: dict[str, Any], cfg: dict[str, Any]) -> str:
    tiers = cfg.get("tiers") or {}
    tier = "nascent"
    for name in _TIER_ORDER:
        band = tiers.get(name) or {}
        lo, hi = float(band.get("min", 0)), float(band.get("max", 100))
        if lo <= composite <= hi:
            tier = name
    if tier == "optimized":
        floor = float(cfg.get("optimized_min_component", 55))
        if any((components.get(k) or {}).get("score", 0) < floor for k in components):
            tier = "mature"
    return tier


def _overall_status_compat(tier: str) -> str:
    return {"nascent": "at_risk", "developing": "maturing", "mature": "mature", "optimized": "mature"}.get(tier, "maturing")


def _composite_trend(series: list[dict[str, Any]], composite: float, cfg: dict[str, Any]) -> str:
    tc = cfg.get("trend") or {}
    key = "maturity_composite_score"
    vals = [float(s[key]) for s in series if s.get(key) is not None]
    if len(vals) < 2:
        return "stable"
    window = int(tc.get("window_points", 7))
    prior = vals[0] if len(vals) <= window else vals[-window]
    delta = composite - prior
    if delta >= float(tc.get("delta_improving", 3)):
        return "improving"
    if delta <= float(tc.get("delta_declining", -3)):
        return "declining"
    return "stable"


def build_maturity_status(
    bus: dict[str, Any],
    trend: dict[str, Any],
    alerts: dict[str, Any],
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build v2 composite maturity (0–100) with weighted sub-components."""
    mcfg = load_maturity_config() if cfg is None else {**load_maturity_config(), **(cfg.get("maturity_v2") or cfg.get("maturity") or {})}
    if cfg and cfg.get("resource_efficiency"):
        mcfg["_resource_baseline"] = (cfg.get("resource_efficiency") or {}).get("pre_governor_live_universe", 4171)

    series = trend.get("series") or []
    components = {
        "outcome_yield": _score_outcome_yield(bus, mcfg),
        "scope_discipline": _score_scope_discipline(bus, alerts, trend, mcfg),
        "stop_quality": _score_stop_quality(bus, mcfg),
        "feedback_loop": _score_feedback_loop(bus, alerts, mcfg),
        "research_actionability": _score_research_actionability(bus, mcfg),
    }

    for key, comp in components.items():
        comp["trend"] = _component_trend(series, f"maturity_{key}_score", comp["score"])

    weights = mcfg.get("weights") or {}
    composite = sum(comp["score"] * float(weights.get(k, comp["weight"])) for k, comp in components.items())
    composite = round(_clamp100(composite), 1)

    tier = _resolve_tier(composite, components, mcfg)
    trend_label = _composite_trend(series, composite, mcfg)

    return {
        "version": mcfg.get("version", "maturity-v2"),
        "composite_score": composite,
        "tier": tier,
        "overall_status": _overall_status_compat(tier),
        "maturity_score": round(composite / 20.0, 2),
        "trend": trend_label,
        "weights": weights,
        "components": components,
        "symbols_in_bus": len(bus.get("by_symbol") or {}),
        "active_alerts": len(alerts.get("active") or []),
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "design_ref": "config/hermes_maturity.yaml",
        "note": "Composite 0–100 maturity-v2; legacy maturity_score is composite/20 for chart compat",
    }


def build_maturity_trend(trend: dict[str, Any]) -> dict[str, Any]:
    """Daily maturity composite + component series for Closed Loop panel."""
    series = trend.get("series") or []
    points = []
    for s in series:
        composite = s.get("maturity_composite_score")
        if composite is None:
            legacy = s.get("maturity_score")
            if legacy is not None:
                composite = float(legacy) * 20.0
        if composite is None and s.get("maturity_overall_status") is None:
            continue
        points.append({
            "day": s.get("day"),
            "at": s.get("at"),
            "composite_score": composite,
            "tier": s.get("maturity_tier") or s.get("maturity_overall_status"),
            "overall_status": s.get("maturity_overall_status"),
            "outcome_yield_score": s.get("maturity_outcome_yield_score"),
            "scope_discipline_score": s.get("maturity_scope_discipline_score"),
            "stop_quality_score": s.get("maturity_stop_quality_score"),
            "feedback_loop_score": s.get("maturity_feedback_loop_score"),
            "research_actionability_score": s.get("maturity_research_actionability_score"),
            "active_alert_count": s.get("active_alert_count"),
        })
    scores = [float(p["composite_score"]) for p in points if p.get("composite_score") is not None]
    trend_label = "stable"
    if len(scores) >= 2:
        delta = scores[-1] - scores[0]
        if delta > 3:
            trend_label = "improving"
        elif delta < -3:
            trend_label = "declining"
    return {
        "count": len(points),
        "series": points,
        "trend": trend_label,
        "current_score": scores[-1] if scores else None,
        "delta_window": round(scores[-1] - scores[0], 1) if len(scores) >= 2 else None,
        "current_tier": points[-1].get("tier") if points else None,
    }


def write_maturity_snapshot(maturity: dict[str, Any], apply: bool = True) -> Path | None:
    """Persist current maturity + rolling daily history for Closed Loop trend."""
    if not apply:
        return None
    MATURITY_SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)

    history: list[dict[str, Any]] = []
    if MATURITY_SNAPSHOT_PATH.exists():
        try:
            prev = json.loads(MATURITY_SNAPSHOT_PATH.read_text(encoding="utf-8"))
            history = list(prev.get("history") or [])
        except Exception:
            history = []

    day = str(maturity.get("computed_at") or datetime.now(timezone.utc).isoformat())[:10]
    point = {
        "day": day,
        "composite_score": maturity.get("composite_score"),
        "tier": maturity.get("tier"),
        "overall_status": maturity.get("overall_status"),
        "trend": maturity.get("trend"),
        "components": {
            k: {"score": (v or {}).get("score"), "trend": (v or {}).get("trend")}
            for k, v in (maturity.get("components") or {}).items()
        },
        "active_alerts": maturity.get("active_alerts"),
    }
    history = [h for h in history if h.get("day") != day]
    history.append(point)
    history.sort(key=lambda h: str(h.get("day") or ""))
    history = history[-30:]

    payload = {**maturity, "history": history, "history_days": len(history)}
    tmp = MATURITY_SNAPSHOT_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    tmp.replace(MATURITY_SNAPSHOT_PATH)
    return MATURITY_SNAPSHOT_PATH