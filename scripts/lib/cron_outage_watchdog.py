"""Independent schedule/success evidence, never a producer, scheduler or repairer.

The caller supplies captured observations. A log mtime, lock skip, dry run,
request receipt or exit-zero without a completed event is never success here.
AUTHORITY: READ_ONLY_ADVISORY. No DB, subprocess, provider or sender imports.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts.lib.cron_schedule import cron_schedules, last_fire_at_or_before, parse

SCHEMA = "CronOutageWatchdog@v1"


def instant(value: object) -> datetime | None:
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return result.astimezone(timezone.utc) if result.tzinfo else None
    except (ValueError, TypeError):
        return None


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def identity(row: dict) -> str:
    return str(row.get("lane_id") or row.get("id") or "UNKNOWN_LANE")


def schedules(row: dict) -> tuple[list[str], str, str | None]:
    """Only actual declared wall schedules; never infer fires from max-gap hours."""
    scheduler, dispatch = row.get("scheduler") or {}, row.get("dispatch") or {}
    tz = str(dispatch.get("tz") or scheduler.get("timezone") or "America/New_York")
    kind = scheduler.get("kind")
    raw = dispatch.get("cron") if kind == "n8n" else None
    if not raw:
        raw = scheduler.get("cadence") or (scheduler.get("expression") if kind == "cron" else None)
    if isinstance(raw, str):
        raw = [raw]
    result = [schedule for value in raw or [] for schedule in cron_schedules(value)]
    if not result:
        return [], tz, "recurring_schedule_not_measured"
    if any(value == "@reboot" for value in result):
        return [], tz, "reboot_has_no_recurring_wall_schedule"
    return result, tz, None


def component(row: dict) -> str | None:
    if row.get("watchdog_wrapper_component"):
        return str(row["watchdog_wrapper_component"])
    scheduler = row.get("scheduler") or {}
    text = str(scheduler.get("command_text") or scheduler.get("expression") or "")
    match = re.search(r"safe_flock\.sh\s+([^\s;&|]+)", text)
    if not match:
        return None
    return Path(match.group(1).strip("\"'")).name.removesuffix(".lock")


def job_key(value: object) -> str:
    """One spelling for a wrapper job id: lock basename without `.lock`/`.lock.dryrun`."""
    text = str(value or "").strip().strip("\"'").rsplit("/", 1)[-1]
    return text.removesuffix(".dryrun").removesuffix(".lock")


def recurring_jobs(events: list[dict], *, now: datetime) -> set[str]:
    """Job ids proven scheduled by history: business completions in >=2 distinct hours.

    A one-off probe or proof (2026-10-24 "rl1/rl2/rl3": one run each, from an agent
    scratch lock) never qualifies; a real hourly/daily/weekly job does within the window.
    """
    hours: dict[str, set[str]] = {}
    for event in events:
        when = instant(event.get("ts"))
        if when is None or when > now or not business_success(event):
            continue
        hours.setdefault(job_key(event.get("job_id") or event.get("component")), set()).add(when.strftime("%Y%m%d%H"))
    return {job for job, seen in hours.items() if len(seen) >= 2}


#: A fire that lands inside a wrapper run's own execution window is IN PROGRESS, not missed — the lane is
#: working. A run older than this at the fire is a stall, not progress, and does not cover it.
IN_PROGRESS_LIMIT_SECONDS = 3600
#: The launch may start a few seconds after the scheduler's fire instant; that still counts as the fire landing.
LAUNCH_GRACE_SECONDS = 120


def run_windows(events: list[dict], *, now: datetime) -> dict[str, list[tuple[datetime, datetime | None]]]:
    """``{job: [(start, end_or_None)]}`` — when each wrapper job was actually executing.

    Built from ``safe_flock`` events: a ``started`` opens a window and the next ``completed`` for the same
    job closes it; a window still open at ``now`` means the job is running right now. Future events are
    ignored, as everywhere in this module: an observation is never backdated.
    """
    by_job: dict[str, list[tuple[datetime, str]]] = {}
    for event in events:
        when = instant(event.get("ts"))
        if when is None or when > now:
            continue
        kind = str(event.get("event_type") or "")
        if kind not in {"started", "completed"}:
            continue
        job = job_key(event.get("job_id") or event.get("component"))
        if job:
            by_job.setdefault(job, []).append((when, kind))
    windows: dict[str, list[tuple[datetime, datetime | None]]] = {}
    for job, rows in by_job.items():
        rows.sort(key=lambda r: r[0])
        out: list[tuple[datetime, datetime | None]] = []
        open_start: datetime | None = None
        for when, kind in rows:
            if kind == "started":
                if open_start is not None:          # a started without a completed: keep the earliest
                    continue
                open_start = when
            elif open_start is not None:
                out.append((open_start, when))
                open_start = None
        if open_start is not None:
            out.append((open_start, None))
        windows[job] = out
    return windows


def fire_was_in_progress(fire: datetime, windows: list[tuple[datetime, datetime | None]], *,
                         now: datetime, limit_seconds: int = IN_PROGRESS_LIMIT_SECONDS,
                         launch_grace_seconds: int = LAUNCH_GRACE_SECONDS) -> bool:
    """True when a wrapper run is still executing and covers the fire (or started within the launch grace).

    Only an OPEN window counts (claude-lead BLOCK on #2553, 2026-11-05): a closed run is over, whatever it did.
    If it closed successfully, its success time is after the fire and the fire is not late at all; if it closed
    with a non-zero exit, the lane did not do the work, so the fire is missed. Counting closed windows let a lane
    failing every run report OK forever — each fire was covered by the very run it launched (two fires, each run
    exiting 1 after a minute, gave missed_fires 0).
    """
    for start, end in windows:
        if end is not None:
            continue                      # a closed run is not in progress: see the docstring
        if start - timedelta(seconds=launch_grace_seconds) <= fire <= now and \
                (fire - start) <= timedelta(seconds=limit_seconds):
            return True
    return False


def business_success(event: dict) -> bool:
    """New events declare mode; legacy commands can prove an explicit dry run only.

    Legacy events without mode remain usable as wrapper-execution evidence when
    their command is present and contains no dry-run flag. They do not prove
    business output correctness. Missing command/mode is unmeasured.
    """
    if event.get("event_type") != "completed" or event.get("exit_code") != 0:
        return False
    mode = event.get("mode")
    if mode is not None:
        return mode == "business"
    command = event.get("command")
    if not isinstance(command, str) or not command.strip():
        return False
    return not re.search(r"(?:--dry[-_]run|--plan(?:\s|$)|--wrapper-preflight|\.dryrun(?:\s|$))", command)


def evaluate(
    registry: dict, events: list[dict], successes: dict[str, list[dict]], *,
    now: datetime, grace_seconds: int = 120, lookback_days: int = 400,
    previous_refusal_keys: set[str] | None = None, trading_day=None,
    registered_jobs: set[str] | None = None, acknowledged: dict[str, dict] | None = None,
    in_progress_limit_seconds: int = IN_PROGRESS_LIMIT_SECONDS,
) -> dict:
    """One point-in-time result. Future observations are ignored, never backdated.

    successes maps lane IDs to explicitly validated receipt timestamps (ok_at /
    finished_at+RUN_DONE+exit0) from the caller, not filesystem timestamps.
    Existing calendar-gated lanes use the same injected market calendar as their
    wrapper. Unsupported schedules/evidence are visible coverage gaps.
    """
    if now.tzinfo is None:
        raise ValueError("watchdog requires an aware observation clock")
    now = now.astimezone(timezone.utc)
    floor = now - timedelta(days=lookback_days)
    completed: dict[str, list[datetime]] = {}
    refusals = []
    seen_refusals = set()
    for event in events:
        when = instant(event.get("ts"))
        if when is None or when > now:
            continue
        if business_success(event):
            completed.setdefault(str(event.get("component")), []).append(when)
        if event.get("event_type") == "refused":
            key = str(event.get("event_id") or "")
            if not key:
                # A stable event position/content identity is supplied by the reader.
                key = str(event.get("capture_key") or "")
            if key and key in seen_refusals:
                continue
            if key:
                seen_refusals.add(key)
            refusals.append({"key": key, "job_id": event.get("job_id") or event.get("component"),
                             "component": event.get("component"),
                             "mode": event.get("mode") or "UNKNOWN",
                             "reason": event.get("reason") or "wrapper_refused", "at": iso(when),
                             "new": not key or key not in (previous_refusal_keys or set())})
    for refusal in refusals:
        after = completed.get(str(refusal["component"]), [])
        refusal["active"] = not any(at > instant(refusal["at"]) for at in after)
    # Attribution: only a refusal of a registered lane/crontab job (or one with a recurring
    # business history) is an outage finding. registered_jobs=None means the registration
    # census was unavailable: then every refusal stays attributed (fail toward alerting).
    known = None if registered_jobs is None else {job_key(j) for j in registered_jobs} | recurring_jobs(events, now=now)
    acknowledged = acknowledged or {}
    attributed, unattributed, acked = [], [], []
    for refusal in refusals:
        job = job_key(refusal["job_id"])
        refusal["attribution"] = ("registration_census_unavailable" if known is None
                                  else "registered" if job in known else "unattributed")
        ack = acknowledged.get(refusal["key"]) if refusal["key"] else None
        if ack is not None:
            refusal.update(acknowledged=True, acknowledged_by=ack.get("acknowledged_by"),
                           acknowledged_at=ack.get("acknowledged_at"), ack_reason=ack.get("reason"),
                           still_active_unrecovered=refusal["active"], active=False, new=False)
            acked.append(refusal)
        elif refusal["attribution"] == "unattributed":
            unattributed.append(refusal)
        else:
            attributed.append(refusal)
    refusals = attributed
    windows = run_windows(events, now=now)
    rows = []
    for lane in registry.get("lanes", []):
        if lane.get("state") != "ACTIVE" or not lane.get("expected_cadence_hours"):
            continue
        lane_id = identity(lane)
        expressions, tz, issue = schedules(lane)
        result = {"lane_id": lane_id, "schedule_timezone": tz, "status": "NOT_MEASURED",
                  "reason": issue, "missed_fires": None, "last_success_at": None,
                  "missed_fire_count_scope": "last_two_elapsed_opportunities; at_least_threshold_not_total_history",
                  "success_scope": "wrapper_or_receipt_execution; business output is separate"}
        kind = (lane.get("scheduler") or {}).get("kind")
        if issue == "reboot_has_no_recurring_wall_schedule" or (
                issue == "recurring_schedule_not_measured" and kind in {"none", "event"}):
            # On-demand, event-emitted, one-shot (`at ...`) and @reboot lanes have no wall-clock fire
            # that can be missed: not blindness, so not a coverage gap (still listed, never hidden).
            result.update(status="NOT_APPLICABLE", reason=f"no_recurring_wall_schedule:{kind}:{issue}")
            rows.append(result)
            continue
        if issue:
            rows.append(result)
            continue
        signal = lane.get("output_signal") or {}
        times = []
        for receipt in successes.get(lane_id, []):
            at = instant(receipt.get("at"))
            if receipt.get("validated_success") is True and at and at <= now:
                times.append(at)
        times.extend(completed.get(component(lane) or "", []))
        if times:
            result["last_success_at"] = iso(max(times))
        try:
            zone = ZoneInfo(tz)
            local = now.astimezone(zone)
            in_hours = any(local.hour in parse(expression)[1] for expression in expressions)
        except (ValueError, TypeError, KeyError):
            result["reason"] = "schedule_unreadable"
            rows.append(result)
            continue
        scheduler = lane.get("scheduler") or {}
        command = str(scheduler.get("command_text") or scheduler.get("expression") or "")
        gated = lane.get("respect_calendar") is True or "market_day_gate.sh" in command
        if gated:
            if trading_day is None:
                result["reason"] = "market_calendar_not_measured"
                rows.append(result)
                continue
        required = set()
        for expression in expressions:
            cursor = now - timedelta(seconds=grace_seconds)
            count = 0
            while cursor > floor and count < 2:
                fire = last_fire_at_or_before(expression, cursor, tz, lookback_days=lookback_days)
                if fire is None:
                    break
                at = fire.at.astimezone(timezone.utc)
                cursor = at - timedelta(microseconds=1)
                if gated and not trading_day(at.astimezone(zone)):
                    continue
                required.add(at)
                count += 1
        eligible = sorted(required)[-2:]
        # No new missed-run alert outside a declared schedule's hour/day. The
        # previous opportunity may be yesterday (daily lanes still need two).
        today_due = any(at.astimezone(zone).date() == local.date() for at in eligible)
        if not in_hours or not today_due:
            result.update(status="OUTSIDE_WINDOW", reason="no_elapsed_fire_in_current_window", missed_fires=0)
        elif not times:
            result["reason"] = ("success_not_measured_file_mtime_is_not_success" if signal.get("kind") == "file_mtime"
                                else "success_not_measured")
            # Missing receipt coverage is explicit; never declare healthy or
            # fabricate a successful history to calculate missed runs.
        else:
            last = max(times)
            job_windows = windows.get(job_key(component(lane) or ""), [])
            late = [fire for fire in eligible if fire > last]
            in_progress = [fire for fire in late
                           if fire_was_in_progress(fire, job_windows, now=now,
                                                   limit_seconds=in_progress_limit_seconds)]
            missed = len(late) - len(in_progress)
            result.update(last_success_at=iso(last), missed_fires=missed,
                          in_progress_fires=len(in_progress),
                          status="MISSED_RUNS" if missed >= 2 else "OK",
                          reason="two_or_more_scheduled_successes_missing" if missed >= 2 else None)
        rows.append(result)
    gaps = [row["lane_id"] for row in rows if row["status"] == "NOT_MEASURED"]
    not_applicable = [row["lane_id"] for row in rows if row["status"] == "NOT_APPLICABLE"]
    missed = [row["lane_id"] for row in rows if row["status"] == "MISSED_RUNS"]
    return {"schema": SCHEMA, "observed_at": iso(now), "rows": rows,
            "missed_lane_ids": missed, "coverage_gap_lane_ids": gaps, "not_applicable_lane_ids": not_applicable,
            "refusals": refusals, "unattributed_refusals": unattributed, "acknowledged_refusals": acked,
            "alert_required": bool(missed or any(x["new"] for x in refusals)),
            "status": "CRIT" if missed or any(x["active"] for x in refusals) else ("UNKNOWN" if gaps else "OK"),
            "note": "Execution success is distinct from output, consumer and alert-delivery acceptance."}
