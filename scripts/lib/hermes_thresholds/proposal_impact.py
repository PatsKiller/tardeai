"""Plain-language post-approval impact narratives for proposal history."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

# (metric_key, label, unit) — unit: pp | points | score
_PRIMARY_METRICS: dict[str, list[tuple[str, str, str]]] = {
    "efficiency.tighten_threshold": [
        ("resource_efficiency_score", "efficiency score", "score"),
        ("hit_rate_promotions", "promotion hit rate", "pp"),
        ("maturity_composite_score", "maturity", "points"),
    ],
    "stop_quality.divergence_delta_pp": [
        ("aligned_pct", "stop alignment", "pp"),
        ("stop_hot_cold_trail_delta", "hot/cold trail gap", "pp"),
        ("maturity_stop_quality_score", "stop quality maturity", "points"),
    ],
}


def _fmt_delta(key: str, unit: str, delta: float) -> str:
    if unit == "pp":
        return f"{delta * 100:+.1f}pp"
    if unit == "points":
        return f"{delta:+.1f} pts"
    if key == "resource_efficiency_score":
        return f"{delta:+.3f}"
    return f"{delta:+.3f}"


def _format_metric_line(key: str, label: str, unit: str, delta: float | None) -> str | None:
    if delta is None:
        return None
    if abs(delta) < 1e-9:
        return None
    return f"{label} {_fmt_delta(key, unit, delta)}"


def _window_days(evaluation: dict[str, Any] | None, default: int = 14) -> int:
    if not evaluation:
        return default
    windows = evaluation.get("windows") or {}
    after = windows.get("after") or {}
    return int(after.get("days") or default)


def build_impact_narrative(
    *,
    threshold_id: str,
    status: str,
    evaluation: dict[str, Any] | None = None,
    decided_at: str | None = None,
    min_eval_days: int = 14,
) -> dict[str, Any]:
    """
    Build operator-facing impact summary for a decided proposal.

    Returns dict with narrative, headline_metric, window_days, status hint.
    """
    if status == "rejected":
        return {
            "narrative": "No measured impact — proposal was rejected.",
            "status": "rejected",
            "window_days": None,
        }

    if status != "approved":
        return {
            "narrative": "Impact tracking applies to approved threshold changes only.",
            "status": "not_applicable",
            "window_days": None,
        }

    if evaluation:
        metrics = evaluation.get("metrics") or {}
        verdict = str(evaluation.get("verdict") or "neutral")
        window = _window_days(evaluation)
        primary = _PRIMARY_METRICS.get(threshold_id) or list(_PRIMARY_METRICS.values())[0]

        parts: list[str] = []
        for key, label, unit in primary:
            m = metrics.get(key) or {}
            line = _format_metric_line(key, label, unit, m.get("delta"))
            if line:
                parts.append(line)

        if not parts:
            if verdict == "insufficient_data":
                narrative = f"Collecting post-change data — need {min_eval_days}d window before impact can be scored."
            else:
                narrative = f"Limited metric movement over {window}d post-approval."
        else:
            joined = ", ".join(parts[:3])
            prefix = {
                "helped": "Contributed to improvement",
                "hurt": "Associated with decline",
                "neutral": "Mixed movement",
                "insufficient_data": "Early signal",
            }.get(verdict, "Post-approval")
            narrative = f"{prefix}: {joined} over {window}d since approval."

        headline = parts[0] if parts else None
        return {
            "narrative": narrative,
            "status": verdict,
            "window_days": window,
            "headline_metric": headline,
            "metrics": {k: v for k, v in metrics.items() if (v or {}).get("delta") is not None},
        }

    # Approved but no formal evaluation yet — progress hint
    days_since = None
    if decided_at:
        try:
            dt = datetime.fromisoformat(str(decided_at).replace("Z", "+00:00"))
            days_since = (datetime.now(timezone.utc) - dt).days
        except Exception:
            pass

    if days_since is not None and days_since < min_eval_days:
        return {
            "narrative": (
                f"Post-approval window in progress ({days_since}/{min_eval_days} days) — "
                "run hermes_threshold_learner.py --evaluate after window completes."
            ),
            "status": "pending_window",
            "window_days": min_eval_days,
            "days_since_approval": days_since,
        }

    return {
        "narrative": (
            f"Approved {days_since or '—'}d ago — run "
            "hermes_threshold_learner.py --evaluate to score post-change impact."
        ),
        "status": "awaiting_evaluation",
        "window_days": min_eval_days,
        "days_since_approval": days_since,
    }


def enrich_evaluation_outcome(evaluation: dict[str, Any]) -> dict[str, Any]:
    """Attach narrative fields to a stored evaluation record."""
    out = dict(evaluation)
    tid = str(out.get("threshold_id") or "")
    impact = build_impact_narrative(
        threshold_id=tid,
        status="approved",
        evaluation=out,
    )
    out["impact_narrative"] = impact.get("narrative")
    out["impact_headline"] = impact.get("headline_metric")
    return out