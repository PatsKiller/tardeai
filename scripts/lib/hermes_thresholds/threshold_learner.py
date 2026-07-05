"""Explainable statistical threshold learner — Phase 2 multi-metric scoring."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from lib.hermes_outcome_bus.bus import load_outcome_bus_trend, read_outcome_bus
from lib.hermes_outcome_bus.bus_traceability import make_snapshot_id

from .scoring import (
    collect_key_trigger_days,
    counterfactual_trigger_count,
    passes_asymmetric_bar,
    passes_loosen_component_guard,
    regime_breakdown,
    resolve_confidence,
    scan_candidates,
    score_efficiency_candidate,
    score_stop_quality_candidate,
    split_holdout,
    validate_holdout_candidate,
)
from .counterfactual_evidence import attach_counterfactual_to_proposal
from .evidence_gates import enrich_proposal_evidence_gates
from .store import (
    append_audit,
    get_active_value,
    load_proposals,
    load_threshold_config,
    new_proposal_id,
    save_proposals,
    static_defaults,
)


def _num(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _clamp_step(current: float, proposed: float, max_step: float, band: dict[str, float]) -> float:
    lo = float(band.get("min", proposed))
    hi = float(band.get("max", proposed))
    delta = max(-max_step, min(max_step, proposed - current))
    return max(lo, min(hi, current + delta))


def _enrich_series(series: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach regime_label per day from governed universe history when available."""
    regime_by_day: dict[str, str] = {}
    try:
        from pathlib import Path
        import json
        from lib.hermes_scope_governor.universe import read_universe_feed, HISTORY_DIR, _parse_generated_at
        feed = read_universe_feed()
        if feed and feed.get("regime_label"):
            day = str(feed.get("generated_at", ""))[:10]
            if day:
                regime_by_day[day] = str(feed["regime_label"])
        if HISTORY_DIR.exists():
            for path in HISTORY_DIR.glob("universe_*.json"):
                try:
                    snap = json.loads(path.read_text(encoding="utf-8"))
                    ts = _parse_generated_at(snap.get("generated_at"))
                    if ts and snap.get("regime_label"):
                        regime_by_day[ts.strftime("%Y-%m-%d")] = str(snap["regime_label"])
                except Exception:
                    continue
    except Exception:
        pass

    out = []
    for s in series:
        row = dict(s)
        day = str(s.get("day") or "")
        if day and day in regime_by_day:
            row["regime_label"] = regime_by_day[day]
        out.append(row)
    return out


def _usable_efficiency_series(series: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [s for s in series if _num(s.get("resource_efficiency_score")) is not None
            and _num(s.get("hit_rate_promotions")) is not None]


def _usable_stop_series(series: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [s for s in series if _num(s.get("stop_hot_cold_trail_delta")) is not None
            and _num(s.get("aligned_pct")) is not None]


def _format_candidate_table(
    candidates: list[dict[str, Any]],
    current: float,
    proposed: float | None = None,
    limit: int = 8,
) -> list[dict[str, Any]]:
    """CLI-parity candidate grid for UI — value, score, trigger rate."""
    rows: list[dict[str, Any]] = []
    for c in candidates[:limit]:
        val = float(c["value"])
        rows.append({
            "value": val,
            "score": round(float(c["score"]), 4),
            "trigger_rate": c.get("trigger_rate"),
            "is_current": abs(val - current) < 0.001,
            "is_proposed": proposed is not None and abs(val - proposed) < 0.001,
        })
    return rows


def _build_proposal(
    threshold_id: str,
    label: str,
    current: float,
    proposed: float,
    direction: str,
    spec: dict[str, Any],
    candidates: list[dict[str, Any]],
    current_score: float,
    regime: dict[str, Any],
    cfg: dict[str, Any],
    reasoning_fn: Callable[..., str],
    extra_evidence: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    best = candidates[0] if candidates else None
    if not best or abs(proposed - current) < float(spec.get("min_step", 0.01)):
        return None

    runner_up = candidates[1] if len(candidates) > 1 else None
    score_delta = best["score"] - current_score
    runner_up_gap = best["score"] - (runner_up["score"] if runner_up else 0)
    confidence, factors = resolve_confidence(
        regime.get("total_days", 0),
        score_delta,
        regime,
        runner_up_gap,
        cfg,
    )

    if not passes_loosen_component_guard(direction, best.get("metric_contributions"), cfg):
        append_audit({
            "action": "no_proposal",
            "threshold_id": threshold_id,
            "reason": "loosen_component_guard_failed",
            "metric_contributions": best.get("metric_contributions"),
        })
        return None

    if not passes_asymmetric_bar(direction, score_delta, confidence, cfg):
        append_audit({
            "action": "no_proposal",
            "threshold_id": threshold_id,
            "reason": f"asymmetric_bar_failed:{direction}",
            "score_delta": score_delta,
            "confidence": confidence,
        })
        return None

    sparse = regime.get("total_days", 0) < int((cfg.get("learning") or {}).get("sparse_data_days", 20))
    max_step = float(spec.get("max_step", 0.03))
    if sparse:
        max_step *= 0.5
        proposed = _clamp_step(current, proposed, max_step, spec.get("safe_band") or {})

    raw = {
        "threshold_id": threshold_id,
        "label": label,
        "current_value": current,
        "proposed_value": proposed,
        "direction": direction,
        "max_step": max_step,
        "reasoning": reasoning_fn(best, proposed, direction, score_delta, confidence),
        "expected_impact": (
            f"Conservative {'tightening' if direction == 'tighten' else 'loosening'}; "
            f"confidence {confidence}; composite score +{score_delta:.4f}."
        ),
        "evidence": {
            "version": "scoring-v2",
            "confidence": confidence,
            "confidence_factors": factors,
            "sample_days": regime.get("total_days"),
            "sample_size": regime.get("total_days"),
            "lookback_days": int((cfg.get("learning") or {}).get("analysis_window_days", 30)),
            "regime_count": max(1, 2 if regime.get("high_vol_days") else 1),
            "sparse_data": sparse,
            "regime_breakdown": regime,
            "current_threshold_score": round(current_score, 4),
            "proposed_threshold_score": round(best["score"], 4),
            "score_delta": round(score_delta, 4),
            "runner_up": {
                "value": runner_up["value"],
                "score": runner_up["score"],
            } if runner_up else None,
            "metric_contributions": best.get("metric_contributions"),
            "candidate_metrics": {k: v for k, v in best.items() if k not in ("value",)},
            "candidate_table": _format_candidate_table(candidates, current, proposed),
            "safe_band": spec.get("safe_band"),
            **(extra_evidence or {}),
        },
    }
    return enrich_proposal_evidence_gates(raw, cfg)


def _candidate_snapshot(
    threshold_id: str,
    series: list[dict[str, Any]],
    spec: dict[str, Any],
    current: float,
    cfg: dict[str, Any],
) -> dict[str, Any] | None:
    """Last-learn scan grid — persisted even when no proposal is generated."""
    if threshold_id == "efficiency.tighten_threshold":
        usable = _usable_efficiency_series(series)
        scorer = lambda s, t: score_efficiency_candidate(s, t, cfg)
    elif threshold_id == "stop_quality.divergence_delta_pp":
        usable = _usable_stop_series(series)
        scorer = lambda s, t: score_stop_quality_candidate(s, t, cfg)
    else:
        return None

    min_n = int((cfg.get("learning") or {}).get("min_sample_days", 10))
    if len(usable) < min_n:
        return {
            "threshold_id": threshold_id,
            "current_value": current,
            "reason": "insufficient_sample_days",
            "sample_days": len(usable),
        }

    band = spec.get("safe_band") or {}
    candidates, holdout_info = _select_best_with_holdout(usable, scorer, current, band, cfg)
    current_meta = scorer(usable, current)
    return {
        "threshold_id": threshold_id,
        "current_value": current,
        "current_score": round(float(current_meta.get("score") or 0), 4),
        "best_candidate": candidates[0] if candidates else None,
        "candidate_table": _format_candidate_table(candidates, current),
        "holdout_validation": holdout_info,
        "sample_days": len(usable),
    }


def _holdout_days(cfg: dict[str, Any]) -> int:
    hold_cfg = (cfg.get("scoring") or {}).get("holdout") or {}
    if not hold_cfg.get("enabled", True):
        return 0
    return int(hold_cfg.get("holdout_days", 7))


def _key_days_limit(cfg: dict[str, Any]) -> int:
    return int((cfg.get("scoring") or {}).get("key_evidence_days", 5))


def _counterfactual_window(cfg: dict[str, Any]) -> int:
    return int((cfg.get("scoring") or {}).get("counterfactual_window_days", 14))


def _select_best_with_holdout(
    usable: list[dict[str, Any]],
    scorer,
    current: float,
    band: dict[str, float],
    cfg: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Scan on train window; require holdout validation for the top candidate."""
    holdout_n = _holdout_days(cfg)
    train, holdout = split_holdout(usable, holdout_n)
    if len(train) < 5:
        train = usable
        holdout = []

    candidates = scan_candidates(train, scorer, current, band)
    if not candidates:
        return [], None

    best = candidates[0]
    if not holdout:
        return candidates, {"skipped": True, "reason": "insufficient_holdout_window"}

    holdout_meta = scorer(holdout, best["value"])
    ok, holdout_info = validate_holdout_candidate(best["score"], holdout_meta, cfg)
    if not ok:
        append_audit({
            "action": "no_proposal",
            "reason": "holdout_validation_failed",
            "candidate_value": best["value"],
            "holdout": holdout_info,
        })
        return [], None
    return candidates, holdout_info


def _propose_efficiency(
    series: list[dict[str, Any]],
    spec: dict[str, Any],
    current: float,
    cfg: dict[str, Any],
) -> dict[str, Any] | None:
    usable = _usable_efficiency_series(series)
    min_n = int((cfg.get("learning") or {}).get("min_sample_days", 10))
    if len(usable) < min_n:
        return None

    regime = regime_breakdown(usable, cfg)
    scorer = lambda s, t: score_efficiency_candidate(s, t, cfg)
    band = spec.get("safe_band") or {}
    candidates, holdout_info = _select_best_with_holdout(usable, scorer, current, band, cfg)
    if not candidates:
        return None

    current_meta = score_efficiency_candidate(usable, current, cfg)
    current_score = current_meta["score"]
    best = candidates[0]
    if best["value"] == current and best["score"] <= current_score + 0.001:
        append_audit({
            "action": "no_proposal",
            "threshold_id": "efficiency.tighten_threshold",
            "reason": "no_improvement",
            "current_score": current_score,
            "best_score": best["score"],
        })
        return None

    proposed = _clamp_step(current, best["value"], float(spec.get("max_step", 0.03)), band)
    direction = "tighten" if proposed < current else "loosen"
    trigger_fn = lambda s: (_num(s.get("resource_efficiency_score")) or 1) < proposed
    extra = {
        "holdout_validation": holdout_info,
        "key_trigger_days": collect_key_trigger_days(usable, trigger_fn, _key_days_limit(cfg)),
        "counterfactual": counterfactual_trigger_count(usable, trigger_fn, _counterfactual_window(cfg)),
        "current_trigger_count": counterfactual_trigger_count(
            usable, lambda s: (_num(s.get("resource_efficiency_score")) or 1) < current,
            _counterfactual_window(cfg),
        ),
    }

    def reasoning(best_m, prop, dir_, delta, conf):
        sep = best_m.get("raw_separations") or {}
        cf = extra.get("counterfactual") or {}
        return (
            f"Composite v2 score {best_m['score']:.4f} (+{delta:.4f} vs current {current_score:.4f}). "
            f"Hit-rate separation {sep.get('hit_rate', 0):.1%}, maturity Δ{sep.get('maturity', 0)}pts. "
            f"Trigger rate {best_m.get('trigger_rate', 0):.0%}, early-detection bonus {best_m.get('early_detection_bonus', 0):.3f}. "
            f"Would fire {cf.get('trigger_count', '—')}× in last {cf.get('window_days', 14)}d. "
            f"Proposing {dir_} {current:.2f}→{prop:.2f} (confidence: {conf})."
        )

    proposal = _build_proposal(
        "efficiency.tighten_threshold",
        spec.get("label", "Efficiency reaction trigger"),
        current, proposed, direction, spec, candidates, current_score, regime, cfg, reasoning, extra,
    )
    if not proposal:
        return None
    return attach_counterfactual_to_proposal(
        proposal,
        usable,
        proposed_trigger_fn=trigger_fn,
        current_trigger_fn=lambda s: (_num(s.get("resource_efficiency_score")) or 1) < current,
        window_days=_counterfactual_window(cfg),
    )


def _propose_stop_quality(
    series: list[dict[str, Any]],
    spec: dict[str, Any],
    current: float,
    cfg: dict[str, Any],
) -> dict[str, Any] | None:
    usable = _usable_stop_series(series)
    min_n = int((cfg.get("learning") or {}).get("min_sample_days", 10))
    if len(usable) < min_n:
        return None

    regime = regime_breakdown(usable, cfg)
    scorer = lambda s, t: score_stop_quality_candidate(s, t, cfg)
    band = spec.get("safe_band") or {}
    candidates, holdout_info = _select_best_with_holdout(usable, scorer, current, band, cfg)
    if not candidates:
        return None

    current_meta = score_stop_quality_candidate(usable, current, cfg)
    current_score = current_meta["score"]
    best = candidates[0]
    if best["value"] == current and best["score"] <= current_score + 0.001:
        append_audit({
            "action": "no_proposal",
            "threshold_id": "stop_quality.divergence_delta_pp",
            "reason": "no_improvement",
            "current_score": current_score,
            "best_score": best["score"],
        })
        return None

    proposed = _clamp_step(current, best["value"], float(spec.get("max_step", 0.02)), band)
    direction = "tighten" if proposed > current else "loosen"
    trigger_fn = lambda s: (_num(s.get("stop_hot_cold_trail_delta")) or 1) < proposed
    extra = {
        "holdout_validation": holdout_info,
        "key_trigger_days": collect_key_trigger_days(usable, trigger_fn, _key_days_limit(cfg)),
        "counterfactual": counterfactual_trigger_count(usable, trigger_fn, _counterfactual_window(cfg)),
        "current_trigger_count": counterfactual_trigger_count(
            usable, lambda s: (_num(s.get("stop_hot_cold_trail_delta")) or 1) < current,
            _counterfactual_window(cfg),
        ),
    }

    def reasoning(best_m, prop, dir_, delta, conf):
        sep = best_m.get("raw_separations") or {}
        cf = extra.get("counterfactual") or {}
        return (
            f"Stop-quality composite {best_m['score']:.4f} (+{delta:.4f}). "
            f"Alignment separation {sep.get('alignment', 0):.1%}, trail Δ{sep.get('trail_delta', 0):.1%}. "
            f"Trigger rate {best_m.get('trigger_rate', 0):.0%}. "
            f"Would fire {cf.get('trigger_count', '—')}× in last {cf.get('window_days', 14)}d. "
            f"Proposing {dir_} divergence floor {current:.0%}→{prop:.0%} (confidence: {conf})."
        )

    proposal = _build_proposal(
        "stop_quality.divergence_delta_pp",
        spec.get("label", "Stop quality divergence"),
        current, proposed, direction, spec, candidates, current_score, regime, cfg, reasoning, extra,
    )
    if not proposal:
        return None
    return attach_counterfactual_to_proposal(
        proposal,
        usable,
        proposed_trigger_fn=trigger_fn,
        current_trigger_fn=lambda s: (_num(s.get("stop_hot_cold_trail_delta")) or 1) < current,
        window_days=_counterfactual_window(cfg),
    )


def _bus_lineage_for_proposal(store: dict[str, Any], threshold_id: str) -> dict[str, Any]:
    """Capture outcome bus snapshot + prior proposal chain at proposal time."""
    bus = read_outcome_bus() or {}
    g = bus.get("global") or {}
    sq = bus.get("stop_quality") or {}
    re = bus.get("resource_efficiency") or {}
    run_id = bus.get("run_id")
    gen_at = bus.get("generated_at")
    prior_ids: list[str] = []
    for p in (store.get("decided") or []) + (store.get("pending") or []):
        if p.get("threshold_id") == threshold_id and p.get("id"):
            prior_ids.append(str(p["id"]))
    return {
        "outcome_bus_run_id": run_id,
        "outcome_bus_snapshot_id": make_snapshot_id(str(run_id or ""), str(gen_at or "")),
        "outcome_bus_generated_at": gen_at,
        "metrics_at_generation": {
            "hit_rate_promotions": g.get("hit_rate_promotions"),
            "resource_efficiency_score": re.get("score") or re.get("resource_efficiency_score"),
            "trail_activation_rate": sq.get("trail_activation_rate"),
            "aligned_pct": sq.get("aligned_pct"),
            "maturity_composite_score": (bus.get("maturity") or {}).get("composite_score"),
        },
        "prior_proposal_ids": prior_ids,
    }


def run_learning_cycle(apply_proposals: bool = False) -> dict[str, Any]:
    """Analyze bus history and create threshold proposals (never auto-applies)."""
    cfg = load_threshold_config()
    learning = cfg.get("learning") or {}
    if not learning.get("enabled", True):
        return {"ok": False, "reason": "learning_disabled"}

    window = int(learning.get("analysis_window_days", 30))
    min_hist = int(learning.get("min_history_days", 14))
    review_mode = bool(learning.get("review_mode", True))

    trend = load_outcome_bus_trend(days=window)
    series = _enrich_series(trend.get("series") or [])
    if len(series) < min_hist:
        return {
            "ok": False,
            "reason": "insufficient_history",
            "history_days": len(series),
            "min_required": min_hist,
        }

    defaults = static_defaults(cfg)
    proposals_out: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    generators = {
        "efficiency.tighten_threshold": _propose_efficiency,
        "stop_quality.divergence_delta_pp": _propose_stop_quality,
    }

    for tid, gen in generators.items():
        spec = defaults.get(tid)
        if not spec:
            continue
        current = get_active_value(tid, cfg) or float(spec["value"])
        raw = gen(series, spec, current, cfg)
        if not raw:
            skipped.append({"threshold_id": tid, "reason": "no_improvement_or_insufficient_signal"})
            continue
        gates_cfg = (cfg.get("evidence_gates") or {})
        cf = (raw.get("counterfactual_evidence") or {})
        if gates_cfg.get("counterfactual_examples_required", True) and not cf.get("has_sufficient_examples"):
            skipped.append({
                "threshold_id": tid,
                "reason": "counterfactual_evidence_insufficient",
            })
            continue
        if not raw.get("can_be_called_learned") and gates_cfg.get("block_insufficient_sample", True):
            skipped.append({
                "threshold_id": tid,
                "reason": raw.get("evidence", {}).get("blocked_reason") or "insufficient_evidence",
            })
            continue
        raw["id"] = new_proposal_id()
        raw["status"] = "pending"
        raw["review_mode"] = review_mode
        raw["advisory_only"] = True
        raw["created_at"] = datetime.now(timezone.utc).isoformat()
        raw["scoring_version"] = "scoring-v2"
        proposals_out.append(raw)

    snapshots: list[dict[str, Any]] = []
    for tid, gen in generators.items():
        spec = defaults.get(tid)
        if not spec:
            continue
        current = get_active_value(tid, cfg) or float(spec["value"])
        snap = _candidate_snapshot(tid, series, spec, current, cfg)
        if snap:
            snapshots.append(snap)

    store = load_proposals()
    pending_ids = {p["threshold_id"] for p in store.get("pending") or []}
    new_pending = list(store.get("pending") or [])
    added = 0
    for p in proposals_out:
        if p["threshold_id"] in pending_ids:
            skipped.append({"threshold_id": p["threshold_id"], "reason": "pending_proposal_exists"})
            continue
        tid = p["threshold_id"]
        lineage = _bus_lineage_for_proposal(store, tid)
        p["lineage"] = lineage
        evidence = dict(p.get("evidence") or {})
        evidence["metrics_at_generation"] = lineage.get("metrics_at_generation")
        evidence["outcome_bus_run_id"] = lineage.get("outcome_bus_run_id")
        p["evidence"] = evidence
        new_pending.append(p)
        pending_ids.add(p["threshold_id"])
        added += 1
        append_audit({"action": "proposed", "proposal": p})

    last_learn = {
        "at": datetime.now(timezone.utc).isoformat(),
        "history_days": len(series),
        "window_days": window,
        "scoring_version": "scoring-v2",
        "snapshots": snapshots,
    }
    store_payload = {
        **store,
        "pending": new_pending if apply_proposals else list(store.get("pending") or []),
        "review_mode": review_mode,
        "scoring_version": "scoring-v2",
        "last_learn": last_learn,
    }
    if apply_proposals or snapshots:
        save_proposals(store_payload)

    return {
        "ok": True,
        "scoring_version": "scoring-v2",
        "review_mode": review_mode,
        "window_days": window,
        "history_days": len(series),
        "proposals_generated": added,
        "proposals": proposals_out,
        "skipped": skipped,
        "pending_count": len(new_pending if apply_proposals else store.get("pending") or []),
        "last_learn": last_learn,
        "note": "Phase 2 multi-metric scoring; human --approve required",
    }