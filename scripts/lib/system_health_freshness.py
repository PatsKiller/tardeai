"""Pure freshness projection; activity, successful run receipts and acceptance stay distinct."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Mapping


def zoned_stamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return stamp.astimezone(timezone.utc) if stamp.tzinfo is not None else None


def schedule_intent(comp: Mapping[str, Any], registry: Any) -> dict[str, Any]:
    """Compare declarations only; a source row never proves an installed fire."""
    report = {
        "monitor_schedule": comp.get("schedule"),
        "installed_schedule": "NOT_MEASURED",
        "source_intent_status": "NOT_MEASURED",
        "source_intent": [],
        "declaration_differs": None,
    }
    wanted = comp.get("monitor_lane_ids") or []
    if not wanted:
        return dict(report, reason="component_registry_mapping_not_declared")
    if (
        not isinstance(registry, Mapping)
        or registry.get("schema") != "LaneRegistry@v1"
        or not isinstance(registry.get("lanes"), list)
    ):
        return dict(report, reason="source_registry_unavailable")
    declarations = []
    for lane_id in wanted:
        rows = [r for r in registry["lanes"] if isinstance(r, Mapping) and r.get("lane_id") == lane_id]
        if len(rows) != 1:
            return dict(report, reason="source_mapping_missing_or_ambiguous")
        row = rows[0]
        scheduler = row.get("scheduler")
        if not isinstance(scheduler, Mapping):
            return dict(report, reason="source_scheduler_invalid")
        raw = scheduler.get("schedules") or [
            scheduler.get("cadence") if scheduler.get("kind") == "n8n" else scheduler.get("expression")
        ]
        if not isinstance(raw, list) or not raw or any(not isinstance(s, str) or len(s.split()) != 5 for s in raw):
            return dict(report, reason="source_schedule_not_measured")
        declarations.append(
            {"lane_id": lane_id, "state": row.get("state"), "kind": scheduler.get("kind"), "schedules": raw}
        )
    active = [s for r in declarations if r["state"] == "ACTIVE" for s in r["schedules"]]
    declared = comp.get("schedule")
    legacy = declared if isinstance(declared, list) else [declared]
    return dict(
        report,
        source_intent_status="SOURCE_INTENT_ONLY",
        source_intent=declarations,
        declaration_differs=set(active) != set(legacy),
        semantic_equivalence="NOT_MEASURED",
        reason="installed_schedule_identity_requires_evidence",
    )


def freshness_at(
    stamp: datetime | None,
    *,
    now: datetime,
    max_age_min: float,
    prev_fire: datetime | None = None,
    grace_min: float = 15,
) -> dict[str, Any]:
    if now.tzinfo is None or (stamp is not None and stamp.tzinfo is None):
        return {"status": "ERROR", "age_min": None, "reason": "unresolved_timestamp_timezone"}
    observed = now.astimezone(timezone.utc)
    if stamp is None:
        return {"status": "MISSING", "age_min": None, "reason": "success_timestamp_missing"}
    stamp = stamp.astimezone(timezone.utc)
    if stamp > observed:
        return {"status": "ERROR", "age_min": None, "reason": "success_timestamp_in_future"}
    age = round((observed - stamp).total_seconds() / 60, 1)
    result = {"age_min": age, "success_at": stamp.isoformat(), "observed_at": observed.isoformat()}
    if prev_fire is not None:
        if prev_fire.tzinfo is None:
            return dict(result, status="ERROR", reason="unresolved_schedule_timezone")
        if observed < prev_fire + timedelta(minutes=grace_min):
            return dict(result, status="OK", reason="within_run_grace", note="within_run_grace")
        if stamp < prev_fire - timedelta(minutes=grace_min):
            return dict(result, status="STALE", reason="scheduled_success_missing")
        return dict(result, status="OK", reason="schedule_fresh")
    return dict(result, status="STALE" if age > max_age_min else "OK", reason="age_threshold")


def lane_receipt_freshness(
    doc: Any,
    *,
    lane_id: str,
    script: str,
    now: datetime,
    max_age_min: float,
    prev_fire: datetime | None = None,
    grace_min: float = 15,
    failure_debounce_min: float | None = None,
    failure_alert_consecutive: int | None = None,
) -> dict[str, Any]:
    """A failed attempt's carried ok_at is history, never proof of current success.

    Debounce (2026-10-23, Finviz Screener false page): a lane written by several callers (cron plus the
    hot-list and early-lane wrappers, ~120 attempts/hour) can record one killed attempt between successes.
    With ``failure_debounce_min`` set, a failed latest attempt whose carried ``ok_at`` is no older than that
    window -- and whose ``consecutive_failures`` (when the writer records it) is below
    ``failure_alert_consecutive`` -- reports ``status: OK`` with ``reason: latest_receipt_failed_debounced``
    and ``debounced: True``. The failure stays visible (``latest_attempt_status: failed``); it is just not a
    page. No success inside the window, or N consecutive failures, is ``FAILED`` exactly as before. Both
    knobs default off, so every caller that does not pass them keeps the strict behaviour.
    """
    base = {
        "signal_kind": "LaneRunReceipt@v1",
        "business_output_acceptance": "NOT_MEASURED",
        "last_line": None,
        "age_min": None,
    }
    if not isinstance(doc, Mapping) or doc.get("schema") != "LaneRunReceipt@v1":
        return dict(base, status="ERROR", reason="receipt_schema_invalid")
    if doc.get("lane_id") != lane_id or doc.get("script") != script:
        return dict(base, status="ERROR", reason="receipt_identity_mismatch")
    if doc.get("mode") != "live":
        return dict(base, status="ERROR", reason="receipt_not_live")
    if (
        not isinstance(doc.get("status"), str)
        or doc["status"] not in {"ok", "failed"}
        or type(doc.get("exit")) is not int
    ):
        return dict(base, status="ERROR", reason="receipt_outcome_invalid")
    finished = zoned_stamp(doc.get("finished_at"))
    started = zoned_stamp(doc.get("started_at"))
    success = zoned_stamp(doc.get("ok_at"))
    if now.tzinfo is None or finished is None or started is None or finished < started:
        return dict(base, status="ERROR", reason="receipt_attempt_timestamp_invalid")
    if finished > now.astimezone(timezone.utc) or (success is not None and success > finished):
        return dict(base, status="ERROR", reason="receipt_timestamp_in_future")
    if doc.get("ok_at") is not None and success is None:
        return dict(base, status="ERROR", reason="receipt_success_timestamp_invalid")
    base.update(latest_attempt_at=finished.isoformat(), latest_attempt_status=doc["status"])
    history = freshness_at(success, now=now, max_age_min=max_age_min, prev_fire=prev_fire, grace_min=grace_min)
    if doc["status"] == "failed":
        consecutive = doc.get("consecutive_failures")
        consecutive = consecutive if type(consecutive) is int and consecutive >= 0 else None
        verdict = debounce_failure(
            history,
            consecutive=consecutive,
            failure_debounce_min=failure_debounce_min,
            failure_alert_consecutive=failure_alert_consecutive,
        )
        if verdict["debounced"]:
            return {
                **base,
                **history,
                **verdict,
                "consecutive_failures": consecutive,
                "reason": "latest_receipt_failed_debounced",
            }
        return dict(
            base,
            status="FAILED",
            age_min=history.get("age_min"),
            success_at=history.get("success_at"),
            consecutive_failures=consecutive,
            reason="latest_receipt_failed",
            **verdict,
        )
    if doc["exit"] != 0 or success is None or success != finished:
        return dict(base, status="ERROR", reason="receipt_success_outcome_inconsistent")
    return dict(base, **history)


def debounce_failure(
    history: Mapping[str, Any],
    *,
    consecutive: int | None,
    failure_debounce_min: float | None,
    failure_alert_consecutive: int | None,
) -> dict[str, Any]:
    """Whether one failed attempt is absorbed by a recent success (see :func:`lane_receipt_freshness`)."""
    if failure_debounce_min is None or failure_debounce_min <= 0:
        return {"debounced": False}
    out: dict[str, Any] = {"debounced": False, "failure_debounce_min": failure_debounce_min}
    if failure_alert_consecutive is not None:
        out["failure_alert_consecutive"] = failure_alert_consecutive
    age = history.get("age_min")
    if history.get("status") != "OK" or age is None:
        return dict(out, debounce_verdict="no_current_success")
    if age > failure_debounce_min:
        return dict(out, debounce_verdict="no_success_within_window")
    if failure_alert_consecutive is not None and consecutive is not None and consecutive >= failure_alert_consecutive:
        return dict(out, debounce_verdict="consecutive_failures_reached")
    return dict(out, debounced=True, debounce_verdict="success_within_window")
