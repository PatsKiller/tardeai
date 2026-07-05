"""Before/after evaluation of applied threshold changes — read-only recommendations."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from lib.hermes_outcome_bus.bus import load_outcome_bus_trend

from .evaluation_store import append_eval_audit, load_evaluations, new_evaluation_id, save_evaluations
from .store import load_active_thresholds, load_threshold_config


def _num(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _parse_day(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.strptime(str(s)[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _window_avg(series: list[dict[str, Any]], key: str) -> float | None:
    vals = [_num(s.get(key)) for s in series]
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else None


def _metric_delta(before: float | None, after: float | None) -> dict[str, Any]:
    if before is None or after is None:
        return {"before": before, "after": after, "delta": None}
    return {"before": round(before, 4), "after": round(after, 4), "delta": round(after - before, 4)}


# Per threshold type — metric weights for impact score (−1 to +1 scale)
EFFICIENCY_EVAL_WEIGHTS = {
    "hit_rate_promotions": 0.35,
    "maturity_composite_score": 0.25,
    "avg_realized_r_trades_90d": 0.20,
    "resource_efficiency_score": 0.10,
    "stop_hot_cold_trail_delta": 0.10,
}

STOP_EVAL_WEIGHTS = {
    "aligned_pct": 0.30,
    "maturity_stop_quality_score": 0.25,
    "stop_hot_cold_trail_delta": 0.20,
    "hit_rate_promotions": 0.15,
    "maturity_composite_score": 0.10,
}

METRIC_KEYS = [
    "hit_rate_promotions",
    "avg_realized_r_trades_90d",
    "resource_efficiency_score",
    "stop_hot_cold_trail_delta",
    "aligned_pct",
    "maturity_composite_score",
    "maturity_stop_quality_score",
]


def _impact_score(metrics: dict[str, dict[str, Any]], weights: dict[str, float]) -> float:
    """Positive = metrics improved after change (higher is better for all tracked)."""
    total_w = 0.0
    score = 0.0
    for key, w in weights.items():
        m = metrics.get(key) or {}
        delta = m.get("delta")
        if delta is None:
            continue
        total_w += w
        # normalize: pp-scale for rates, points for maturity
        norm = float(delta)
        if key in ("hit_rate_promotions", "aligned_pct", "stop_hot_cold_trail_delta"):
            norm = delta * 10  # amplify small pp moves
        elif key == "maturity_composite_score":
            norm = delta / 10.0
        score += w * norm
    if total_w <= 0:
        return 0.0
    return round(score / total_w, 4)


def _verdict(impact: float, before_n: int, after_n: int, cfg: dict[str, Any]) -> tuple[str, str, str]:
    ev = (cfg.get("evaluation") or {})
    helped = float(ev.get("helped_impact_floor", 0.15))
    hurt = float(ev.get("hurt_impact_ceiling", -0.15))
    min_days = int(ev.get("min_window_days", 7))

    if before_n < min_days or after_n < min_days:
        return "insufficient_data", "low", "needs_more_data"
    if impact >= helped:
        return "helped", "medium", "keep"
    if impact <= hurt:
        return "hurt", "medium", "revert"
    return "neutral", "medium", "monitor"


def _confidence(before_n: int, after_n: int, cfg: dict[str, Any]) -> str:
    ev = cfg.get("evaluation") or {}
    pref = int(ev.get("preferred_window_days", 14))
    if before_n >= pref and after_n >= pref:
        return "high"
    if before_n >= 7 and after_n >= 7:
        return "medium"
    return "low"


def _slice_windows(
    series: list[dict[str, Any]],
    change_day: str,
    before_days: int,
    after_days: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    change_dt = _parse_day(change_day)
    if not change_dt:
        return [], []
    before: list[dict[str, Any]] = []
    after: list[dict[str, Any]] = []
    for s in series:
        d = _parse_day(s.get("day"))
        if not d:
            continue
        if d < change_dt and d >= change_dt - timedelta(days=before_days):
            before.append(s)
        elif d > change_dt and d <= change_dt + timedelta(days=after_days):
            after.append(s)
    return before, after


def evaluate_change(
    change: dict[str, Any],
    series: list[dict[str, Any]],
    cfg: dict[str, Any],
) -> dict[str, Any] | None:
    """Evaluate one approved history entry."""
    tid = change.get("threshold_id")
    at = change.get("at")
    if not tid or not at:
        return None

    ev_cfg = cfg.get("evaluation") or {}
    before_days = int(ev_cfg.get("before_window_days", 14))
    after_days = int(ev_cfg.get("after_window_days", 14))
    min_after = int(ev_cfg.get("min_days_after_change", 14))

    change_day = str(at)[:10]
    change_dt = _parse_day(change_day)
    if not change_dt:
        return None
    days_since = (datetime.now(timezone.utc) - change_dt).days
    if days_since < min_after:
        return None

    before, after = _slice_windows(series, change_day, before_days, after_days)
    if not before and not after:
        return None

    metrics: dict[str, dict[str, Any]] = {}
    for key in METRIC_KEYS:
        metrics[key] = _metric_delta(_window_avg(before, key), _window_avg(after, key))

    weights = EFFICIENCY_EVAL_WEIGHTS if "efficiency" in tid else STOP_EVAL_WEIGHTS
    impact = _impact_score(metrics, weights)
    verdict, _vconf, recommendation = _verdict(impact, len(before), len(after), cfg)
    confidence = _confidence(len(before), len(after), cfg)

    reasoning_parts = []
    hr = metrics.get("hit_rate_promotions", {})
    mat = metrics.get("maturity_composite_score", {})
    if hr.get("delta") is not None:
        reasoning_parts.append(f"promotion hit rate Δ{hr['delta']:+.1%}")
    if mat.get("delta") is not None:
        reasoning_parts.append(f"maturity composite Δ{mat['delta']:+.1f}")
    reasoning = (
        f"Threshold {tid} changed {change.get('from')}→{change.get('to')} on {change_day}. "
        f"Before {len(before)}d / after {len(after)}d windows. "
        + ("; ".join(reasoning_parts) if reasoning_parts else "Limited metric movement.")
        + f" Impact score {impact:+.3f} → {verdict}."
    )

    return {
        "id": new_evaluation_id(),
        "threshold_id": tid,
        "proposal_id": change.get("proposal_id"),
        "approved_at": at,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "change": {"from": change.get("from"), "to": change.get("to")},
        "windows": {
            "before": {"start": (change_dt - timedelta(days=before_days)).strftime("%Y-%m-%d"),
                       "end": change_day, "days": len(before)},
            "after": {"start": (change_dt + timedelta(days=1)).strftime("%Y-%m-%d"),
                      "end": (change_dt + timedelta(days=after_days)).strftime("%Y-%m-%d"), "days": len(after)},
        },
        "metrics": metrics,
        "impact_score": impact,
        "verdict": verdict,
        "confidence": confidence,
        "recommendation": recommendation,
        "reasoning": reasoning,
        "days_since_change": days_since,
    }


def run_evaluation_cycle(lookback_days: int | None = None) -> dict[str, Any]:
    """Evaluate all eligible approved changes; read-only — never modifies thresholds."""
    cfg = load_threshold_config()
    ev_cfg = cfg.get("evaluation") or {}
    if not ev_cfg.get("enabled", True):
        return {"ok": False, "reason": "evaluation_disabled"}

    window = lookback_days or int(ev_cfg.get("lookback_days", 60))
    trend = load_outcome_bus_trend(days=window)
    series = trend.get("series") or []

    active = load_active_thresholds()
    history = [h for h in (active.get("history") or []) if h.get("action") == "approved"]

    store = load_evaluations()
    existing_keys = {
        (e.get("threshold_id"), e.get("approved_at"))
        for e in (store.get("evaluations") or [])
    }

    new_evals: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for change in history:
        key = (change.get("threshold_id"), change.get("at"))
        if key in existing_keys:
            skipped.append({"threshold_id": change.get("threshold_id"), "reason": "already_evaluated"})
            continue
        ev = evaluate_change(change, series, cfg)
        if ev is None:
            skipped.append({
                "threshold_id": change.get("threshold_id"),
                "reason": "not_ready_or_insufficient_windows",
                "at": change.get("at"),
            })
            continue
        new_evals.append(ev)
        append_eval_audit({"action": "evaluated", "evaluation_id": ev["id"], "verdict": ev["verdict"]})
        try:
            from .do_no_harm import build_do_no_harm_report, persist_do_no_harm_report
            change_day = str(change.get("at") or "")[:10]
            before, after = _slice_windows(
                series,
                change_day,
                int(ev_cfg.get("before_window_days", 14)),
                int(ev_cfg.get("after_window_days", 14)),
            )
            dnh = build_do_no_harm_report(before, after, evaluation=ev, threshold_id=change.get("threshold_id"))
            ev["do_no_harm"] = dnh
            persist_do_no_harm_report(dnh)
        except Exception:
            pass

    all_evals = list(store.get("evaluations") or []) + new_evals
    summary = _build_summary(all_evals)

    payload = {
        "version": "evaluations-v1",
        "evaluations": all_evals[-100:],
        "summary": summary,
    }
    save_evaluations(payload)

    closed_loop: dict[str, Any] = {}
    try:
        from .closed_loop_evaluation import run_closed_loop_evaluation_cycle
        closed_loop = run_closed_loop_evaluation_cycle(lookback_days=window)
    except Exception as cl_err:
        closed_loop = {"ok": False, "error": str(cl_err)[:120]}

    do_no_harm_latest = None
    try:
        from .do_no_harm import load_do_no_harm_report
        do_no_harm_latest = load_do_no_harm_report().get("latest")
    except Exception:
        pass

    return {
        "ok": True,
        "lookback_days": window,
        "evaluations_new": len(new_evals),
        "evaluations_total": len(all_evals),
        "evaluations": new_evals,
        "summary": summary,
        "skipped": skipped,
        "closed_loop": closed_loop,
        "do_no_harm_report": do_no_harm_latest,
        "advisory_only": True,
        "note": "Read-only — recommendations do not auto-apply",
    }


def _build_summary(evaluations: list[dict[str, Any]]) -> dict[str, Any]:
    by_verdict: dict[str, int] = {}
    by_rec: dict[str, int] = {}
    for e in evaluations:
        by_verdict[e.get("verdict", "unknown")] = by_verdict.get(e.get("verdict"), 0) + 1
        by_rec[e.get("recommendation", "unknown")] = by_rec.get(e.get("recommendation"), 0) + 1
    latest = evaluations[-1] if evaluations else None
    return {
        "count": len(evaluations),
        "by_verdict": by_verdict,
        "by_recommendation": by_rec,
        "latest_evaluation_at": latest.get("evaluated_at") if latest else None,
    }


def evaluation_status() -> dict[str, Any]:
    store = load_evaluations()
    closed_loop: dict[str, Any] = {}
    try:
        from .closed_loop_evaluation import closed_loop_evaluation_status
        closed_loop = closed_loop_evaluation_status()
    except Exception:
        pass
    return {
        "ok": True,
        "summary": store.get("summary") or {},
        "evaluations": (store.get("evaluations") or [])[-20:],
        "updated_at": store.get("updated_at"),
        "closed_loop": closed_loop,
    }