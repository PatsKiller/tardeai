"""Conservative, reversible Scope Governor reactions to outcome_bus signals."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from lib.hermes_outcome_bus.bus import load_outcome_bus, load_outcome_bus_trend

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
REACTIONS_RUNTIME_PATH = PROJECT_ROOT / "data" / "runtime" / "hermes_bus_reactions.json"
REACTIONS_CFG_PATH = PROJECT_ROOT / "config" / "hermes_reactions.yaml"
COOLDOWN_STATE_PATH = PROJECT_ROOT / "data" / "runtime" / "hermes_reaction_cooldown_state.json"


@dataclass
class BusReactionPlan:
    """One-run overrides derived from outcome bus — not persisted in governor config."""
    hot_min_score_delta: int = 0
    max_outcome_promotions_delta: int = 0
    demotion_pressure_multiplier: float = 1.0
    hot_tier_research_boost: float = 1.0
    warm_cold_edge_penalty: float = 0.0
    hot_high_edge_boost: float = 0.0
    tag_multiplier_overrides: dict[str, float] = field(default_factory=dict)
    reactions: list[dict[str, Any]] = field(default_factory=list)
    suppressed: list[dict[str, Any]] = field(default_factory=list)
    enabled: bool = True
    review_mode: bool = False
    regime_label: str | None = None
    regime_modifier: str = "normal"
    bus_metrics: dict[str, Any] = field(default_factory=dict)
    run_id: str | None = None


def load_reactions_config(governor_cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """Load hermes_reactions.yaml, learned thresholds, and legacy bus_reactions."""
    rc: dict[str, Any] = {}
    try:
        import yaml
        rc = yaml.safe_load(REACTIONS_CFG_PATH.read_text(encoding="utf-8")) or {}
    except Exception:
        rc = {}

    try:
        from lib.hermes_thresholds.store import merge_learned_into_reactions
        rc = merge_learned_into_reactions(rc)
    except Exception:
        pass

    legacy = (governor_cfg or {}).get("bus_reactions") or {}
    if not legacy:
        return rc

    merged = dict(rc)
    merged["enabled"] = legacy.get("enabled", merged.get("enabled", True))
    merged["trend_window_days"] = legacy.get("trend_window_days", merged.get("trend_window_days", 14))

    eff = dict(merged.get("efficiency") or {})
    eff.setdefault("tighten_threshold", legacy.get("efficiency_tighten_threshold", 0.50))
    eff.setdefault("consecutive_days", legacy.get("efficiency_consecutive_days", 3))
    eff.setdefault("hot_min_score_bump", legacy.get("hot_min_score_bump", 10))
    eff.setdefault("demotion_pressure_multiplier", legacy.get("demotion_pressure_multiplier", 1.25))
    merged["efficiency"] = eff

    sq_legacy = legacy.get("stop_quality_reactions") or {}
    sq = dict(merged.get("stop_quality") or {})
    if sq_legacy:
        sq["enabled"] = sq_legacy.get("enabled", sq.get("enabled", True))
        for k, lk in [
            ("divergence_delta_pp", "divergence_delta_pp"),
            ("divergence_consecutive_days", "divergence_consecutive_days"),
            ("warm_cold_hot_min_bump", "warm_cold_hot_min_bump"),
            ("warm_cold_edge_penalty", "warm_cold_edge_penalty"),
            ("divergence_hot_research_boost", "divergence_hot_research_boost"),
            ("strong_advantage_pp", "strong_advantage_pp"),
            ("strong_advantage_hot_min_relax", "strong_advantage_hot_min_relax"),
            ("strong_advantage_hot_edge_boost", "strong_advantage_hot_edge_boost"),
        ]:
            if k in sq_legacy:
                sq[lk] = sq_legacy[k]
    sq.setdefault("strong_advantage_pp", legacy.get("stop_hot_advantage_pp", 0.12))
    sq.setdefault("divergence_hot_research_boost", legacy.get("hot_research_priority_boost", 1.08))
    merged["stop_quality"] = sq

    sc = dict(merged.get("scope_creep") or {})
    sc.setdefault("promotion_cap_reduction", legacy.get("scope_creep_promotion_cap_reduction", 5))
    merged["scope_creep"] = sc

    tags = dict(merged.get("tags") or {})
    tags.setdefault("poor_outcomes_days", legacy.get("tag_poor_outcomes_days", 7))
    tags.setdefault("multiplier_reduction", legacy.get("tag_multiplier_reduction", 0.85))
    tags.setdefault("multiplier_floor", legacy.get("tag_multiplier_floor", 0.45))
    merged["tags"] = tags
    return merged


def _active_alert_ids(bus: dict[str, Any]) -> set[str]:
    return {str(a.get("id")) for a in (bus.get("alerts") or {}).get("active") or [] if a.get("id")}


def _bus_metrics_snapshot(bus: dict[str, Any]) -> dict[str, Any]:
    resource = bus.get("resource_efficiency") or {}
    stop_q = bus.get("stop_quality") or {}
    maturity = bus.get("maturity") or {}
    return {
        "resource_efficiency_score": resource.get("score") or resource.get("resource_efficiency_score"),
        "live_universe": resource.get("live_universe"),
        "hit_rate_promotions": (bus.get("global") or {}).get("hit_rate_promotions"),
        "stop_hot_cold_trail_delta": _hot_cold_trail_delta(bus),
        "maturity_composite_score": maturity.get("composite_score"),
        "maturity_tier": maturity.get("tier"),
        "active_alerts": sorted(_active_alert_ids(bus)),
        "symbols_in_bus": len(bus.get("by_symbol") or {}),
    }


def _resolve_regime_modifier(rc: dict[str, Any], regime_label: str | None) -> tuple[str, dict[str, Any]]:
    label = (regime_label or "normal").lower()
    mods = rc.get("regime_modifiers") or {}
    for name, spec in mods.items():
        if name == "normal":
            continue
        for token in spec.get("match") or []:
            if token.lower() in label:
                return name, spec
    return "normal", mods.get("normal") or {
        "hot_min_score_bump_mult": 1.0,
        "promotion_cap_mult": 1.0,
        "demotion_pressure_mult": 1.0,
    }


def _load_cooldown_state() -> dict[str, Any]:
    if not COOLDOWN_STATE_PATH.exists():
        return {"last_applied": {}}
    try:
        return json.loads(COOLDOWN_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"last_applied": {}}


def _save_cooldown_state(state: dict[str, Any]) -> None:
    COOLDOWN_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = COOLDOWN_STATE_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
    tmp.replace(COOLDOWN_STATE_PATH)


def _cooldown_active(
    reaction_id: str,
    rc: dict[str, Any],
    bus: dict[str, Any],
    state: dict[str, Any],
) -> tuple[bool, str | None]:
    cd = rc.get("cooldown") or {}
    if not cd.get("enabled", True):
        return False, None
    last = (state.get("last_applied") or {}).get(reaction_id)
    if not last:
        return False, None
    try:
        last_dt = datetime.fromisoformat(str(last))
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=timezone.utc)
    except Exception:
        return False, None
    hours = float(cd.get("hours_per_reaction", 12))
    if datetime.now(timezone.utc) - last_dt < timedelta(hours=hours):
        hysteresis = (cd.get("hysteresis") or {})
        if reaction_id == "tighten_promotion_gate":
            eff = (bus.get("resource_efficiency") or {}).get("score")
            release = float(hysteresis.get("efficiency_release_threshold", 0.55))
            if eff is not None and float(eff) >= release:
                return False, "hysteresis_efficiency_release"
        return True, f"cooldown_{hours}h"
    return False, None


def _record_cooldown(reaction_ids: list[str], apply: bool, review_mode: bool) -> None:
    if not apply or review_mode or not reaction_ids:
        return
    state = _load_cooldown_state()
    now = datetime.now(timezone.utc).isoformat()
    last = dict(state.get("last_applied") or {})
    for rid in reaction_ids:
        last[rid] = now
    state["last_applied"] = last
    state["updated_at"] = now
    _save_cooldown_state(state)


def _append_reaction(
    plan: BusReactionPlan,
    rc: dict[str, Any],
    bus: dict[str, Any],
    cooldown_state: dict[str, Any],
    reaction: dict[str, Any],
) -> None:
    rid = str(reaction.get("id") or "unknown")
    blocked, reason = _cooldown_active(rid, rc, bus, cooldown_state)
    if blocked:
        plan.suppressed.append({
            "id": rid,
            "reason": reason,
            "would_apply": reaction,
        })
        return
    enriched = {
        **reaction,
        "metrics": {**plan.bus_metrics, **(reaction.get("metrics") or {})},
        "regime": plan.regime_label,
        "regime_modifier": plan.regime_modifier,
        "review_mode": plan.review_mode,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
    }
    plan.reactions.append(enriched)


def _consecutive_low_efficiency(series: list[dict[str, Any]], threshold: float, min_days: int) -> tuple[bool, int]:
    vals = [
        float(s["resource_efficiency_score"])
        for s in series
        if s.get("resource_efficiency_score") is not None
    ]
    if len(vals) < min_days:
        return False, 0
    streak = 0
    for v in reversed(vals):
        if v < threshold:
            streak += 1
        else:
            break
    return streak >= min_days, streak


def _hot_cold_trail_delta(bus: dict[str, Any]) -> float | None:
    stop_q = bus.get("stop_quality") or {}
    for corr in stop_q.get("correlations") or []:
        if corr.get("metric") == "trail_activation_rate":
            raw = corr.get("hot_vs_cold_trail_activation_delta")
            if raw is not None:
                return float(raw)
            pct = corr.get("hot_vs_cold_delta_pct")
            if pct is not None:
                return float(pct) / 100.0
    by_tier = stop_q.get("by_tier") or {}
    hot = (by_tier.get("hot") or {}).get("trail_activation_rate")
    cold = (by_tier.get("cold") or {}).get("trail_activation_rate")
    if hot is not None and cold is not None:
        return float(hot) - float(cold)
    return None


def _consecutive_trail_delta_below(
    series: list[dict[str, Any]],
    threshold: float,
    min_days: int,
) -> tuple[bool, int, float | None]:
    vals = [
        float(s["stop_hot_cold_trail_delta"])
        for s in series
        if s.get("stop_hot_cold_trail_delta") is not None
    ]
    if len(vals) < min_days:
        return False, 0, vals[-1] if vals else None
    streak = 0
    for v in reversed(vals):
        if v < threshold:
            streak += 1
        else:
            break
    return streak >= min_days, streak, vals[-1]


def _tag_poor_outcomes_streak(series: list[dict[str, Any]], tag: str, min_days: int) -> int:
    streak = 0
    for s in reversed(series):
        neg = set(s.get("negative_lift_tags") or [])
        down = set(s.get("research_downrank_tags") or [])
        if tag in neg and tag in down:
            streak += 1
        else:
            break
    return streak


def _apply_efficiency_reaction(
    plan: BusReactionPlan,
    rc: dict[str, Any],
    bus: dict[str, Any],
    series: list[dict[str, Any]],
    regime_spec: dict[str, Any],
    cooldown_state: dict[str, Any],
) -> None:
    eff_cfg = rc.get("efficiency") or {}
    if not eff_cfg.get("enabled", True):
        return
    eff_floor = float(eff_cfg.get("tighten_threshold", 0.50))
    eff_days = int(eff_cfg.get("consecutive_days", 3))
    resource = bus.get("resource_efficiency") or {}
    score = resource.get("score") or resource.get("resource_efficiency_score")
    low_eff, streak = _consecutive_low_efficiency(series, eff_floor, eff_days)
    if not (low_eff or (score is not None and float(score) < eff_floor and streak >= eff_days - 1)):
        return

    bump_mult = float(regime_spec.get("hot_min_score_bump_mult", 1.0))
    dem_mult = float(regime_spec.get("demotion_pressure_mult", 1.0))
    delta = int(round(float(eff_cfg.get("hot_min_score_bump", 10)) * bump_mult))
    demotion = float(eff_cfg.get("demotion_pressure_multiplier", 1.25)) * dem_mult
    plan.hot_min_score_delta += delta
    plan.demotion_pressure_multiplier = max(plan.demotion_pressure_multiplier, demotion)
    _append_reaction(plan, rc, bus, cooldown_state, {
        "id": "tighten_promotion_gate",
        "reason": (
            f"bus_reaction:efficiency_below_{eff_floor:.2f}_for_{max(streak, eff_days)}d "
            f"(score={score}, regime={plan.regime_modifier})"
        ),
        "hot_min_score_delta": delta,
        "demotion_pressure_multiplier": plan.demotion_pressure_multiplier,
        "metrics": {"efficiency_streak_days": streak, "efficiency_score": score},
    })


def _apply_stop_quality_reactions(
    plan: BusReactionPlan,
    rc: dict[str, Any],
    bus: dict[str, Any],
    series: list[dict[str, Any]],
    regime_spec: dict[str, Any],
    cooldown_state: dict[str, Any],
) -> None:
    sq = rc.get("stop_quality") or {}
    if not sq.get("enabled", True):
        return
    delta = _hot_cold_trail_delta(bus)
    if delta is None:
        return

    bump_mult = float(regime_spec.get("hot_min_score_bump_mult", 1.0))
    div_floor = float(sq.get("divergence_delta_pp", 0.13))
    div_days = int(sq.get("divergence_consecutive_days", 4))
    strong_pp = float(sq.get("strong_advantage_pp", 0.20))
    low_streak, streak, current = _consecutive_trail_delta_below(series, div_floor, div_days)

    if low_streak or (current is not None and current < div_floor and streak >= div_days - 1):
        bump = int(round(float(sq.get("warm_cold_hot_min_bump", 5)) * bump_mult))
        plan.hot_min_score_delta += bump
        plan.warm_cold_edge_penalty = float(sq.get("warm_cold_edge_penalty", 5.0))
        boost = float(sq.get("divergence_hot_research_boost", 1.10))
        plan.hot_tier_research_boost = max(plan.hot_tier_research_boost, boost)
        _append_reaction(plan, rc, bus, cooldown_state, {
            "id": "stop_quality_divergence",
            "reason": (
                f"bus_reaction:stop_quality_divergence delta={current:.1%} "
                f"below_{div_floor:.0%}_for_{max(streak, div_days)}d "
                f"(regime={plan.regime_modifier})"
            ),
            "hot_vs_cold_trail_activation_delta": current,
            "hot_min_score_delta": bump,
            "warm_cold_edge_penalty": plan.warm_cold_edge_penalty,
            "hot_tier_research_boost": boost,
            "metrics": {"trail_delta_streak_days": streak},
        })
    elif delta >= strong_pp:
        relax = int(sq.get("strong_advantage_hot_min_relax", 5))
        edge_boost = float(sq.get("strong_advantage_hot_edge_boost", 5.0))
        plan.hot_min_score_delta -= relax
        plan.hot_high_edge_boost = edge_boost
        _append_reaction(plan, rc, bus, cooldown_state, {
            "id": "stop_quality_strong_advantage",
            "reason": (
                f"bus_reaction:stop_quality_strong_advantage delta={delta:.1%} "
                f"(regime={plan.regime_modifier})"
            ),
            "hot_vs_cold_trail_activation_delta": delta,
            "hot_min_score_relax": relax,
            "hot_high_edge_boost": edge_boost,
        })


def _apply_tag_reactions(
    plan: BusReactionPlan,
    rc: dict[str, Any],
    bus: dict[str, Any],
    series: list[dict[str, Any]],
    cooldown_state: dict[str, Any],
) -> None:
    tag_cfg = rc.get("tags") or {}
    if not tag_cfg.get("enabled", True):
        return
    tag_floor = float(tag_cfg.get("multiplier_floor", 0.45))
    tag_reduction = float(tag_cfg.get("multiplier_reduction", 0.85))
    tag_streak_days = int(tag_cfg.get("poor_outcomes_days", 7))
    for tag, meta in (bus.get("by_tag") or {}).items():
        lift = meta.get("lift")
        if lift is None or float(lift) >= 0:
            continue
        streak = _tag_poor_outcomes_streak(series, str(tag), tag_streak_days)
        if streak < tag_streak_days:
            continue
        cur_mult = float(meta.get("quality_multiplier") or 1.0)
        new_mult = max(tag_floor, cur_mult * tag_reduction)
        plan.tag_multiplier_overrides[str(tag)] = round(new_mult, 3)
        _append_reaction(plan, rc, bus, cooldown_state, {
            "id": "tag_quality_reduction",
            "tag": tag,
            "reason": f"bus_reaction:negative_lift_{lift}_poor_outcomes_{streak}d",
            "quality_multiplier": new_mult,
            "metrics": {"tag_lift": lift, "poor_outcomes_streak_days": streak},
        })


def _apply_scope_creep_reaction(
    plan: BusReactionPlan,
    rc: dict[str, Any],
    bus: dict[str, Any],
    alerts: set[str],
    regime_spec: dict[str, Any],
    cooldown_state: dict[str, Any],
) -> None:
    sc = rc.get("scope_creep") or {}
    if not sc.get("enabled", True) or "scope_creep" not in alerts:
        return
    cap_mult = float(regime_spec.get("promotion_cap_mult", 1.0))
    cap_cut = int(round(float(sc.get("promotion_cap_reduction", 5)) * cap_mult))
    plan.max_outcome_promotions_delta -= cap_cut
    _append_reaction(plan, rc, bus, cooldown_state, {
        "id": "scope_creep_cap_reduction",
        "reason": f"bus_reaction:scope_creep_alert_active (regime={plan.regime_modifier})",
        "max_outcome_promotions_delta": -cap_cut,
    })


def build_bus_reaction_plan(
    cfg: dict[str, Any],
    run_id: str | None = None,
    regime_label: str | None = None,
    review_mode: bool | None = None,
) -> BusReactionPlan:
    """Read latest outcome bus + trend history; produce conservative one-run adjustments."""
    rc = load_reactions_config(cfg)
    if not rc.get("enabled", True):
        return BusReactionPlan(enabled=False, run_id=run_id)

    bus = load_outcome_bus()
    if not bus or not bus.get("generated_at"):
        return BusReactionPlan(enabled=False, run_id=run_id, reactions=[{"skipped": "no_bus"}])

    rm = review_mode if review_mode is not None else bool(rc.get("review_mode", False))
    mod_name, regime_spec = _resolve_regime_modifier(rc, regime_label)
    trend_days = int(rc.get("trend_window_days", 14))
    trend = load_outcome_bus_trend(days=trend_days)
    series = trend.get("series") or []
    plan = BusReactionPlan(
        enabled=True,
        run_id=run_id,
        review_mode=rm,
        regime_label=regime_label,
        regime_modifier=mod_name,
        bus_metrics=_bus_metrics_snapshot(bus),
    )
    alerts = _active_alert_ids(bus)
    cooldown_state = _load_cooldown_state()

    _apply_efficiency_reaction(plan, rc, bus, series, regime_spec, cooldown_state)
    _apply_stop_quality_reactions(plan, rc, bus, series, regime_spec, cooldown_state)
    _apply_tag_reactions(plan, rc, bus, series, cooldown_state)
    _apply_scope_creep_reaction(plan, rc, bus, alerts, regime_spec, cooldown_state)

    return plan


def apply_reaction_edge_adjustments(
    edge_scores: dict[str, float],
    edge_details: dict[str, dict],
    plan: BusReactionPlan,
    tier_map: dict[str, str],
) -> tuple[dict[str, float], dict[str, dict]]:
    """Light edge adjustments from bus reactions — never bulk demotions."""
    if plan.review_mode:
        return edge_scores, edge_details

    updated = dict(edge_scores)
    details = {k: dict(v) for k, v in edge_details.items()}

    if plan.demotion_pressure_multiplier > 1.0:
        rc_threshold = 40.0
        extra_pen = 5.0 * (plan.demotion_pressure_multiplier - 1.0)
        for sym, score in edge_scores.items():
            if score > rc_threshold:
                continue
            tier = tier_map.get(sym.upper(), "S3")
            if tier in ("S0",):
                continue
            updated[sym] = max(0.0, updated[sym] - extra_pen)
            d = details.setdefault(sym, {})
            reasons = list(d.get("reasons") or [])
            reasons.append(f"bus_reaction:demotion_pressure_x{plan.demotion_pressure_multiplier:.2f}")
            d["reasons"] = reasons

    if plan.warm_cold_edge_penalty > 0:
        for sym, score in updated.items():
            tier = tier_map.get(sym.upper(), "S3")
            if tier not in ("S2", "S3"):
                continue
            updated[sym] = max(0.0, score - plan.warm_cold_edge_penalty)
            d = details.setdefault(sym, {})
            reasons = list(d.get("reasons") or [])
            reasons.append(f"bus_reaction:warm_cold_promotion_tighten_{plan.warm_cold_edge_penalty:.0f}")
            d["reasons"] = reasons

    if plan.hot_high_edge_boost > 0:
        hot_min = 65.0
        for sym, score in updated.items():
            tier = tier_map.get(sym.upper(), "S3")
            if tier not in ("S0", "S1") or score < hot_min:
                continue
            updated[sym] = min(100.0, score + plan.hot_high_edge_boost)
            d = details.setdefault(sym, {})
            reasons = list(d.get("reasons") or [])
            reasons.append(f"bus_reaction:hot_high_edge_boost_{plan.hot_high_edge_boost:.0f}")
            d["reasons"] = reasons

    return updated, details


def write_reactions_runtime(plan: BusReactionPlan, apply: bool = True) -> Path | None:
    """Expose tag/hot-tier research overrides for research_scheduler (one cycle)."""
    if not apply or not plan.enabled or plan.review_mode:
        return None
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_id": plan.run_id,
        "review_mode": plan.review_mode,
        "regime_label": plan.regime_label,
        "regime_modifier": plan.regime_modifier,
        "hot_tier_research_boost": plan.hot_tier_research_boost,
        "warm_cold_edge_penalty": plan.warm_cold_edge_penalty,
        "hot_high_edge_boost": plan.hot_high_edge_boost,
        "hot_min_score_delta": plan.hot_min_score_delta,
        "tag_multiplier_overrides": plan.tag_multiplier_overrides,
        "reactions": plan.reactions,
        "suppressed": plan.suppressed,
        "bus_metrics": plan.bus_metrics,
        "expires_after_run": True,
    }
    REACTIONS_RUNTIME_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = REACTIONS_RUNTIME_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    tmp.replace(REACTIONS_RUNTIME_PATH)
    _record_cooldown([r.get("id") for r in plan.reactions if r.get("id")], apply=True, review_mode=False)
    return REACTIONS_RUNTIME_PATH


def log_reactions_audit(cur, run_id: str, plan: BusReactionPlan, apply: bool) -> int:
    """Insert bus_reaction rows into scope_governor_audit (system-level, auditable)."""
    if not apply or not plan.reactions:
        return 0
    logged = 0
    prefix = "bus_reaction_review:" if plan.review_mode else "bus_reaction:"
    for rx in plan.reactions:
        base = str(rx.get("reason") or f"bus_reaction:{rx.get('id', 'unknown')}")
        metrics = rx.get("metrics") or {}
        metric_bits = ", ".join(f"{k}={v}" for k, v in list(metrics.items())[:6])
        reason = f"{prefix}{base}"
        if metric_bits:
            reason = f"{reason}|{metric_bits}"
        if plan.review_mode:
            reason = f"{reason}|review_mode=true"
        reason = reason[:500]
        cur.execute(
            """INSERT INTO scope_governor_audit (run_id, symbol, action, from_tier, to_tier, reason)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (run_id, "__BUS__", "bus_reaction", None, None, reason),
        )
        logged += 1
    return logged


def read_reactions_runtime() -> dict[str, Any]:
    if not REACTIONS_RUNTIME_PATH.exists():
        return {}
    try:
        return json.loads(REACTIONS_RUNTIME_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}