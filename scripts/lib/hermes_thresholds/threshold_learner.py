"""Explainable statistical threshold learner — Phase 2 multi-metric scoring."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from lib.hermes_outcome_bus.bus import load_outcome_bus_trend

from .scoring import (
    passes_asymmetric_bar,
    regime_breakdown,
    resolve_confidence,
    scan_candidates,
    score_efficiency_candidate,
    score_stop_quality_candidate,
)
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

    return {
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
            "safe_band": spec.get("safe_band"),
        },
    }


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
    candidates = scan_candidates(usable, scorer, current, spec.get("safe_band") or {})
    if not candidates:
        return None

    current_meta = score_efficiency_candidate(usable, current, cfg)
    current_score = current_meta["score"]
    best = candidates[0]
    if best["value"] == current and best["score"] <= current_score + 0.001:
        return None

    proposed = _clamp_step(current, best["value"], float(spec.get("max_step", 0.03)), spec.get("safe_band") or {})
    direction = "tighten" if proposed < current else "loosen"

    def reasoning(best_m, prop, dir_, delta, conf):
        sep = best_m.get("raw_separations") or {}
        return (
            f"Composite v2 score {best_m['score']:.4f} (+{delta:.4f} vs current {current_score:.4f}). "
            f"Hit-rate separation {sep.get('hit_rate', 0):.1%}, maturity Δ{sep.get('maturity', 0)}pts. "
            f"Trigger rate {best_m.get('trigger_rate', 0):.0%}, early-detection bonus {best_m.get('early_detection_bonus', 0):.3f}. "
            f"Proposing {dir_} {current:.2f}→{prop:.2f} (confidence: {conf})."
        )

    return _build_proposal(
        "efficiency.tighten_threshold",
        spec.get("label", "Efficiency reaction trigger"),
        current, proposed, direction, spec, candidates, current_score, regime, cfg, reasoning,
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
    candidates = scan_candidates(usable, scorer, current, spec.get("safe_band") or {})
    if not candidates:
        return None

    current_meta = score_stop_quality_candidate(usable, current, cfg)
    current_score = current_meta["score"]
    best = candidates[0]
    if best["value"] == current and best["score"] <= current_score + 0.001:
        return None

    proposed = _clamp_step(current, best["value"], float(spec.get("max_step", 0.02)), spec.get("safe_band") or {})
    direction = "tighten" if proposed > current else "loosen"

    def reasoning(best_m, prop, dir_, delta, conf):
        sep = best_m.get("raw_separations") or {}
        return (
            f"Stop-quality composite {best_m['score']:.4f} (+{delta:.4f}). "
            f"Alignment separation {sep.get('alignment', 0):.1%}, trail Δ{sep.get('trail_delta', 0):.1%}. "
            f"Trigger rate {best_m.get('trigger_rate', 0):.0%}. "
            f"Proposing {dir_} divergence floor {current:.0%}→{prop:.0%} (confidence: {conf})."
        )

    return _build_proposal(
        "stop_quality.divergence_delta_pp",
        spec.get("label", "Stop quality divergence"),
        current, proposed, direction, spec, candidates, current_score, regime, cfg, reasoning,
    )


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
        raw["id"] = new_proposal_id()
        raw["status"] = "pending"
        raw["review_mode"] = review_mode
        raw["created_at"] = datetime.now(timezone.utc).isoformat()
        raw["scoring_version"] = "scoring-v2"
        proposals_out.append(raw)

    store = load_proposals()
    pending_ids = {p["threshold_id"] for p in store.get("pending") or []}
    new_pending = list(store.get("pending") or [])
    added = 0
    for p in proposals_out:
        if p["threshold_id"] in pending_ids:
            skipped.append({"threshold_id": p["threshold_id"], "reason": "pending_proposal_exists"})
            continue
        new_pending.append(p)
        pending_ids.add(p["threshold_id"])
        added += 1
        append_audit({"action": "proposed", "proposal": p})

    if apply_proposals and added:
        save_proposals({**store, "pending": new_pending, "review_mode": review_mode, "scoring_version": "scoring-v2"})

    return {
        "ok": True,
        "scoring_version": "scoring-v2",
        "review_mode": review_mode,
        "window_days": window,
        "history_days": len(series),
        "proposals_generated": added,
        "proposals": proposals_out,
        "skipped": skipped,
        "pending_count": len(new_pending),
        "note": "Phase 2 multi-metric scoring; human --approve required",
    }