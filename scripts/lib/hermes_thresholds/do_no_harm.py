"""Do-no-harm regression report after threshold evaluation cycles."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
REPORT_PATH = PROJECT_ROOT / "data" / "runtime" / "hermes_do_no_harm_report.json"


def _num(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _window_avg(series: list[dict[str, Any]], key: str) -> float | None:
    vals = [_num(s.get(key)) for s in series]
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else None


def _delta(before: float | None, after: float | None) -> dict[str, Any]:
    if before is None or after is None:
        return {"before": before, "after": after, "delta": None}
    return {"before": round(before, 4), "after": round(after, 4), "delta": round(after - before, 4)}


def build_do_no_harm_report(
    before_series: list[dict[str, Any]],
    after_series: list[dict[str, Any]],
    *,
    evaluation: dict[str, Any] | None = None,
    threshold_id: str | None = None,
) -> dict[str, Any]:
    """Compare before/after windows; recommend revert if metrics degrade."""
    metrics = {
        "hit_rate": _delta(
            _window_avg(before_series, "hit_rate_promotions"),
            _window_avg(after_series, "hit_rate_promotions"),
        ),
        "alert_volume_proxy": _delta(
            _window_avg(before_series, "active_alert_count"),
            _window_avg(after_series, "active_alert_count"),
        ),
        "research_usefulness": _delta(
            _window_avg(before_series, "hit_rate_research_actioned"),
            _window_avg(after_series, "hit_rate_research_actioned"),
        ),
        "scope_churn": _delta(
            _window_avg(before_series, "symbols_in_bus"),
            _window_avg(after_series, "symbols_in_bus"),
        ),
        "false_positives_proxy": _delta(
            _window_avg(before_series, "resource_efficiency_score"),
            _window_avg(after_series, "resource_efficiency_score"),
        ),
        "resource_efficiency": _delta(
            _window_avg(before_series, "resource_efficiency_score"),
            _window_avg(after_series, "resource_efficiency_score"),
        ),
    }

    hr_delta = (metrics["hit_rate"].get("delta"))
    eff_delta = (metrics["resource_efficiency"].get("delta"))
    scope_delta = (metrics["scope_churn"].get("delta"))
    alert_delta = (metrics["alert_volume_proxy"].get("delta"))

    degraded = []
    if hr_delta is not None and hr_delta < -0.02:
        degraded.append("hit_rate_declined")
    if eff_delta is not None and eff_delta < -0.03:
        degraded.append("resource_efficiency_declined")
    if scope_delta is not None and scope_delta > 50:
        degraded.append("scope_churn_increased")
    if alert_delta is not None and alert_delta > 1:
        degraded.append("alert_volume_increased")

    eval_rec = (evaluation or {}).get("recommendation")
    if eval_rec == "revert":
        recommendation = "revert"
        reason = "evaluation_engine_recommends_revert"
    elif degraded:
        recommendation = "revert"
        reason = f"metrics_degraded:{','.join(degraded)}"
    elif hr_delta is not None and hr_delta > 0.01:
        recommendation = "keep"
        reason = "hit_rate_improved"
    else:
        recommendation = "monitor"
        reason = "mixed_or_insufficient_signal"

    return {
        "version": "do-no-harm-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "threshold_id": threshold_id or (evaluation or {}).get("threshold_id"),
        "evaluation_id": (evaluation or {}).get("id"),
        "before_after": metrics,
        "degraded_signals": degraded,
        "recommendation": recommendation,
        "reason": reason,
        "questions": {
            "did_hit_rate_improve": hr_delta is not None and hr_delta > 0,
            "did_false_positives_rise": eff_delta is not None and eff_delta < -0.02,
            "did_useful_alerts_improve": eff_delta is not None and eff_delta > 0,
            "did_scope_churn_increase": scope_delta is not None and scope_delta > 25,
            "holdings_crowd_out": False,
            "incorrect_demotions_detected": False,
        },
        "advisory_only": True,
        "note": "Regression report is advisory — operator must approve any revert",
    }


def persist_do_no_harm_report(report: dict[str, Any]) -> Path:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    history: list[dict[str, Any]] = []
    if REPORT_PATH.exists():
        try:
            prev = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
            history = list(prev.get("history") or [])
        except Exception:
            history = []
    history.append(report)
    history = history[-30:]
    payload = {**report, "history": history, "latest": report}
    tmp = REPORT_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    tmp.replace(REPORT_PATH)
    return REPORT_PATH


def load_do_no_harm_report() -> dict[str, Any]:
    if not REPORT_PATH.exists():
        return {"version": "do-no-harm-v1", "history": [], "note": "no report yet"}
    try:
        return json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"version": "do-no-harm-v1", "history": [], "error": "corrupt_report"}