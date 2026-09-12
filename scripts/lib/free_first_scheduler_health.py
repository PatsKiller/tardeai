"""Read-only health for the FREE_FIRST_ONLY systemd timer.

A successful FRESH_NO_CHANGE / NO_NEW_INFO run is healthy. Timer freshness
does not mean an LLM call is required.

Why this file was rewritten (2026-09-12)
----------------------------------------
The previous predicate was:

    last_ok = bool(rec) and paid == 0 and rec.get("overlap") is not True

Three questions, none of which can become false again once one good receipt
exists. The service had been SIGTERM'd at its 900s start timeout on every run
since 2026-09-08 -- 93 consecutive failures, zero successful runs in 4 days --
and this returned healthy=true throughout, while printing the 4.4-day-old
finished_at and the non-served source_sha in its own output. It had the
evidence of its own falseness and did not consult it.

`paid == 0` was the worst of the three: a dead service spends nothing, so total
outage scored as maximal health. Absence of spend is now recorded but is never
what makes a verdict positive.

Health is now a conjunction of things that can each go false:
  a receipt exists and its timestamp parses;
  the receipt is younger than the expected cadence (with a grace multiple);
  the receipt was produced on the epoch being served, when that is knowable;
  the unit is not in a failed state, when unit state is supplied;
  the run did not overlap and did not dispatch paid work in a free-only mode.

Every failing condition is named in `unhealthy_reasons`, because "unhealthy"
without a reason is the same dead end as "healthy" without evidence.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

AUTHORITY = "READ_ONLY_ADVISORY"
RECEIPT = "data/cio/free_first_last_run.json"
FAILURE_RECEIPT = "data/cio/free_first_last_failure.json"
TIMER = "tradeai-free-first-circulation.timer"
SERVICE = "tradeai-free-first-circulation.service"

#: How many cadence periods a receipt may age before it is stale. One missed
#: run is a blip; two consecutive misses is a lane that has stopped.
DEFAULT_CADENCE_HOURS = 1.0
STALENESS_GRACE_PERIODS = 2.0

#: systemd ActiveState values that mean the unit is not working.
FAILED_UNIT_STATES = {"failed"}


def load_receipt(root: Path | str) -> dict[str, Any] | None:
    path = Path(root) / RECEIPT
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def load_failure_receipt(root: Path | str) -> dict[str, Any] | None:
    """Last recorded failure, if the producer left one.

    Staleness alone already flips the verdict; this supplies the diagnosis, so
    an operator sees WHY the lane stopped rather than only that it did.
    """
    path = Path(root) / FAILURE_RECEIPT
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def timer_health(
    root: Path | str,
    *,
    timer_show: dict[str, str] | None = None,
    expected_cadence_hours: float = DEFAULT_CADENCE_HOURS,
    served_sha: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    rec = load_receipt(root) or {}
    when = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    reasons: list[str] = []

    paid = int(rec.get("paid_dispatch_entered") or rec.get("paid_calls_attempted") or 0)
    finished_raw = rec.get("finished_at") or rec.get("as_of")
    finished = _parse_ts(finished_raw)

    age_hours: float | None = None
    if not rec:
        reasons.append("no_receipt")
    elif finished is None:
        # An unreadable timestamp must never be treated as "recent enough".
        reasons.append("receipt_timestamp_unreadable")
    else:
        age_hours = (when - finished).total_seconds() / 3600.0
        if age_hours > float(expected_cadence_hours) * STALENESS_GRACE_PERIODS:
            reasons.append("receipt_stale")

    epoch_agreement = "UNPROVEN"
    receipt_sha = str(rec.get("source_sha") or "")
    if served_sha and receipt_sha:
        if receipt_sha == str(served_sha):
            epoch_agreement = "AGREES"
        else:
            epoch_agreement = "DISAGREES"
            # Evidence from another epoch describes that epoch, not this one.
            reasons.append("receipt_from_prior_epoch")

    unit_state = str((timer_show or {}).get("ActiveState") or "").strip().lower()
    if unit_state in FAILED_UNIT_STATES:
        # The receipt is written on success, so a SIGTERM'd run leaves the last
        # good receipt untouched. Unit state is the only witness to that run.
        reasons.append("unit_failed")

    if rec.get("overlap") is True:
        reasons.append("overlapped")
    if paid > 0:
        reasons.append("paid_dispatch_in_free_only_mode")

    failure = load_failure_receipt(root) or {}
    failure_at = _parse_ts(failure.get("finished_at") or failure.get("as_of"))
    last_run_failed = bool(failure) and (finished is None or (failure_at and failure_at > finished))
    if last_run_failed:
        reasons.append("last_run_failed")

    return {
        "schema": "FreeFirstSchedulerHealth@v2",
        "authority": AUTHORITY,
        "timer": TIMER,
        "service": SERVICE,
        "timer_show": timer_show or {},
        "last_run_mode": rec.get("mode"),
        "last_source_sha": rec.get("source_sha"),
        "last_run_id": rec.get("run_id"),
        "last_finished_at": finished_raw,
        "receipt_age_hours": round(age_hours, 2) if age_hours is not None else None,
        "expected_cadence_hours": float(expected_cadence_hours),
        "staleness_threshold_hours": float(expected_cadence_hours) * STALENESS_GRACE_PERIODS,
        "served_sha": served_sha,
        "epoch_agreement": epoch_agreement,
        "unit_active_state": unit_state or None,
        # Recorded, never a reason to call anything healthy: a dead lane also
        # dispatches nothing paid.
        "paid_dispatch_count": paid,
        "fresh_no_change": rec.get("fresh_no_change"),
        "healthy": not reasons,
        "unhealthy_reasons": reasons,
        "last_failure": (
            {
                "at": failure.get("finished_at") or failure.get("as_of"),
                "error_class": failure.get("error_class"),
                "error_message": failure.get("error_message"),
            }
            if last_run_failed
            else None
        ),
        "note": "NO_NEW_INFO / FRESH_NO_CHANGE is a healthy outcome; a stale or prior-epoch receipt is not",
        # This reporter reads files and returns a dict. The assertion is a
        # property of this code path, not a check performed on someone else.
        "financial_action": False,
    }
