"""One read-only execution projection for /ops/jobs and the five monitoring embeds.

Existing lane registry, wrapper events, run receipts and watchdog readback only.
No scheduler discovery subprocess, producer execution, DB migration or sender.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
import json
import os
import re
from pathlib import Path
import threading
import time
from zoneinfo import ZoneInfo

from scripts.lib import cron_outage_watchdog as W, recovery_validator as RV
from scripts.lib.cron_schedule import fires_between
from scripts.lib.n8n_dlq_disposition import cause, instant
from scripts.lib.scheduler_operations import successful_execution

SCHEMA = "JobsHealth@v1"
ROOT = Path(__file__).resolve().parents[2]
_CACHE = {}
_LOCK = threading.Lock()
_FAILURES = {"RUN_FAILED", "RUN_TIMEOUT", "RUN_REFUSED"}


def last_log_success(path: Path, *, now: datetime):
    """An explicit completed/exit-zero marker, never the log's write time.

    Older logs without a success protocol remain unmeasured. Host plaintext
    timestamps without an offset use the declared host timezone, America/New_York.
    """
    try:
        with path.open("rb") as stream:
            stream.seek(0, 2)
            start = max(0, stream.tell() - 256 * 1024)
            stream.seek(start)
            raw = stream.read(256 * 1024)
        if start:
            raw = raw.partition(b"\n")[2]
    except OSError:
        return None
    latest = None
    for line in raw.decode("utf-8", errors="replace").splitlines():
        at = None
        try:
            event = json.loads(line)
        except ValueError:
            event = None
        if isinstance(event, dict):
            if type(event.get("exit_code")) is int and W.business_success(event):
                at = instant(event.get("ts"))
            elif successful_execution({**event, "receipt": event}, now):
                at = instant(event.get("finished_at"))
        elif (re.search(r"\b(?:completed|finished|succeeded|SUCCESS)\b", line, re.I)
              and re.search(r"\b(?:exit_code|exit|rc)\s*[=: ]\s*0\b", line)
              and not re.search(r"dry[-_ ]?run|preflight|shadow", line, re.I)):
            match = re.search(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:\d{2})?", line)
            if match:
                try:
                    parsed = datetime.fromisoformat(match[0].replace(",", ".").replace("Z", "+00:00"))
                    at = parsed if parsed.tzinfo else parsed.replace(tzinfo=ZoneInfo("America/New_York"))
                except ValueError:
                    pass
        if at and at <= now:
            latest = max(latest, at) if latest else at
    return latest


def _json(path, limit=8 * 1024 * 1024):
    try:
        with Path(path).open("rb") as stream:
            raw = stream.read(limit + 1)
        doc = json.loads(raw) if len(raw) <= limit else None
        return doc if isinstance(doc, dict) else {}
    except (OSError, ValueError):
        return {}


def _schedule(lane, now, trading_day):
    expressions, tz, issue = W.schedules(lane)
    zone = ZoneInfo(tz)
    today = now.astimezone(zone).replace(hour=0, minute=0, second=0, microsecond=0)
    scheduler = lane.get("scheduler") or {}
    gated = lane.get("respect_calendar") is True or "market_day_gate.sh" in str(scheduler.get("command_text") or scheduler.get("expression") or "")
    def allowed(fire):
        return not gated or trading_day(fire.at.astimezone(zone))
    day_end = today + timedelta(days=1) - timedelta(microseconds=1)
    today_fires = sorted({f.at.astimezone(timezone.utc) for ex in expressions
                         for f in fires_between(ex, today - timedelta(microseconds=1), day_end, tz) if allowed(f)})
    due = [at for at in today_fires if at <= now]
    next_due = None
    for days in (1, 8, 32, 400):
        upcoming = [f.at.astimezone(timezone.utc) for ex in expressions
                    for f in fires_between(ex, now, now + timedelta(days=days), tz) if allowed(f)]
        if upcoming:
            next_due = min(upcoming)
            break
        if not expressions:
            break
    return due, next_due, issue, gated, bool(today_fires)


def build(registry: dict, snapshot: dict, runs: list[dict], watchdog: dict, *, now: datetime, trading_day) -> dict:
    if now.tzinfo is None:
        raise ValueError("jobs health requires an aware clock")
    by_lane = {}
    for run in runs:
        at = instant(run.get("finished_at") or run.get("started_at") or run.get("requested_at"))
        pending_live = run.get("mode") == "live" and run.get("state") in {"REQUESTED", "RUNNING"}
        if at and at <= now and (RV.effective_mode(run) == "live" or pending_live):
            by_lane.setdefault(run.get("lane_id"), []).append(run)
    for values in by_lane.values():
        values.sort(key=lambda r: instant(r.get("finished_at") or r.get("started_at") or r.get("requested_at")))
    captured = {**snapshot, "successes": {k: list(v) for k, v in (snapshot.get("successes") or {}).items()}}
    for lane, values in by_lane.items():
        for run in values:
            if successful_execution(run, now):
                captured["successes"].setdefault(lane, []).append({"at": run["finished_at"], "validated_success": True})
    report = W.evaluate(registry, captured.get("events") or [], captured["successes"], now=now, trading_day=trading_day)
    checks = {r["lane_id"]: r for r in report["rows"]}
    rows = []
    for lane in registry.get("lanes") or []:
        lane_id = W.identity(lane)
        check = checks.get(lane_id) or {}
        state = lane.get("state") or "UNKNOWN"
        scheduler = lane.get("scheduler") or {}
        values = by_lane.get(lane_id) or []
        last = values[-1] if values else {}
        successful = [r for r in values if successful_execution(r, now)]
        success = instant(check.get("last_success_at"))
        last_at = instant(last.get("finished_at") or last.get("started_at"))
        diagnostic = None
        failure_at = None
        component = W.component(lane)
        events = [e for e in captured.get("events") or [] if component and e.get("component") == component
                  and instant(e.get("ts")) and instant(e["ts"]) <= now
                  and e.get("mode") not in {"dry_run", "preflight", "shadow"}]
        for event in sorted(events, key=lambda e: instant(e["ts"])):
            at = instant(event["ts"])
            if event.get("event_type") in {"completed", "refused"}:
                last_at = max(filter(None, [last_at, at]))
            if event.get("event_type") == "refused" or (event.get("event_type") == "completed" and event.get("exit_code") != 0):
                failure_at, diagnostic = at, cause(event)
        if last.get("state") in _FAILURES:
            if failure_at is None or last_at and last_at >= failure_at:
                failure_at, diagnostic = instant(last.get("finished_at")), cause(RV.receipt_of(last), last.get("reason"))
        try:
            due, upcoming, issue, gated, due_today = _schedule(lane, now, trading_day)
        except (ValueError, TypeError, KeyError):
            due, upcoming, issue, gated, due_today = [], None, "schedule could not be measured", False, False
        outcome, reason = "unknown", "Successful execution is not yet measured"
        if state in {"PAUSED", "RETIRED", "DISABLED"}:
            outcome, reason = ("retired" if state == "RETIRED" else "paused"), lane.get("state_reason") or f"Job is {state.lower()}"
            upcoming = None
        elif failure_at and (success is None or failure_at > success):
            outcome, reason = "failed", diagnostic
        elif check.get("status") == "MISSED_RUNS":
            outcome, reason = "missed", "Two scheduled opportunities elapsed without a successful execution"
        elif success and due and success >= due[-1] and now - success <= timedelta(hours=24):
            outcome, reason = "succeeded", "Successful execution receipt; output correctness is checked separately"
        elif last.get("state") in {"REQUESTED", "RUNNING"}:
            outcome, reason = "due", "Execution requested" if last.get("state") == "REQUESTED" else "Execution started; completion pending"
        elif issue:
            reason = "Schedule is not measured" if issue else reason
        elif check.get("status") == "OUTSIDE_WINDOW":
            outcome, reason = "outside_window", "Outside the scheduled window"
        elif due and success and success < due[-1]:
            outcome, reason = "due", "Waiting for the next successful execution"
        rows.append({"lane_id": lane_id, "job": lane.get("display_name") or lane_id.replace("-", " ").replace("_", " ").capitalize(),
            "scheduler": scheduler.get("kind") or "unknown", "state": state, "result": outcome,
            "last_run_at": W.iso(last_at) if last_at else None, "last_success_at": W.iso(success) if success else None,
            "successful_run_id": successful[-1].get("run_id") if successful else None,
            "next_due_at": W.iso(upcoming) if upcoming else None, "due_today": due_today,
            "missed_fires": check.get("missed_fires"), "market_hours_only": gated,
            "cause": reason, "evidence": last.get("run_id") or ("wrapper event" if events else None)})
    counts = Counter(row["result"] for row in rows)
    seen = instant(watchdog.get("observed_at"))
    monitor_ok = bool(watchdog.get("schema") == W.SCHEMA and watchdog.get("mode") == "monitor"
                      and seen and 0 <= (now - seen).total_seconds() <= 180)
    monitor = {"observed_at": watchdog.get("observed_at"), "status": watchdog.get("status") if monitor_ok else "UNKNOWN",
        "cause": None if monitor_ok else "Independent monitor receipt missing, stale or a dry run",
        "notification": watchdog.get("notification") if monitor_ok else None}
    incidents = [{"id": row["lane_id"], "severity": "critical" if row["result"] == "failed" else "warning",
                  "title": f"{row['job']}: {row['result'].replace('_', ' ')}", "message": row["cause"],
                  "href": "/ops/jobs", "source": "job_execution"}
                 for row in rows if row["result"] in {"failed", "missed"}]
    if not monitor_ok:
        incidents.append({"id": "job_monitor_unmeasured", "severity": "warning", "title": "Job monitoring needs attention",
                          "message": monitor["cause"], "href": "/ops/jobs", "source": "job_execution"})
    return {"schema": SCHEMA, "as_of": W.iso(now), "authority": "READ_ONLY_ADVISORY", "rows": rows,
        "summary": {"due_today": sum(r["due_today"] and r["state"] == "ACTIVE" for r in rows),
                    **{key: counts[key] for key in ("succeeded", "failed", "missed", "paused", "retired", "unknown", "due", "outside_window")}},
        "monitor": monitor, "incidents": incidents, "incident_count": len(incidents),
        "coverage_gaps": captured.get("collection_gaps") or [],
        "note": "Execution evidence only. An enabled schedule, fresh log or dry run does not prove successful work."}


def _load(root: Path, registry_path: Path, now: datetime):
    from scripts.cron_outage_watchdog import bind_components, collect
    from scripts.lib.scheduler_operations import read_run_ledger
    from scripts.market_session import is_trading_day
    registry = _json(registry_path)
    registry = bind_components(registry, _json(ROOT / "config/cron_outage_watchdog.json"))
    snapshot = collect(registry, root)
    log_paths = Counter(str((lane.get("output_signal") or {}).get("path")) for lane in registry.get("lanes") or []
                        if (lane.get("output_signal") or {}).get("kind") == "file_mtime")
    for lane in registry.get("lanes") or []:
        signal = lane.get("output_signal") or {}
        declared = str(signal.get("path") or "")
        if signal.get("kind") != "file_mtime" or not declared.endswith(".log"):
            continue
        path = (root / declared).resolve()
        if not path.is_relative_to((root / "logs").resolve()) or log_paths[declared] != 1:
            continue
        at = last_log_success(path, now=now)
        if at:
            snapshot["successes"].setdefault(W.identity(lane), []).append({"at": W.iso(at), "validated_success": True})
    runs, measured, why = read_run_ledger(root / "data/governance/n8n_coordination_ledger.sqlite")
    if not measured:
        snapshot.setdefault("collection_gaps", []).append(why or "run ledger unavailable")
    if not registry.get("lanes"):
        snapshot.setdefault("collection_gaps", []).append("lane registry unavailable")
    report = build(registry, snapshot, runs, _json(root / "data/runtime/cron_outage_watchdog_latest.json"),
                   now=now, trading_day=is_trading_day)
    from scripts.lib.jobs_conflict_errors import get_data_errors
    report["data_errors"] = get_data_errors(root)
    return report


def get_jobs_health(query=None, *, state_root=None, registry_path=None, now=None):
    root = Path(state_root or os.environ.get("TRADEAI_STATE_ROOT") or Path.home() / "trade-ai-releases/persistent-state")
    registry = Path(registry_path or ROOT / "config/lane_registry.json")
    query = query or {}
    clock = now or datetime.now(timezone.utc)
    key = (str(root), str(registry))
    with _LOCK:
        cached = _CACHE.get(key)
        if now is not None or cached is None or time.monotonic() - cached[0] > 60:
            result = _load(root, registry, clock)
            if now is None:
                _CACHE.clear()
                _CACHE[key] = (time.monotonic(), result)
        else:
            result = cached[1]
    scope = query.get("filter", "attention")
    rows = [r for r in result["rows"] if scope == "all" or scope == "attention" and r["result"] in {"failed", "missed", "unknown"}
            or scope == "market" and r["market_hours_only"] or scope in {"n8n", "cron"} and r["scheduler"] == scope]
    if query.get("job"):
        rows = [r for r in result["rows"] if r["lane_id"] == query["job"]]
    rows.sort(key=lambda r: ({"failed": 0, "missed": 1, "unknown": 2, "due": 3}.get(r["result"], 4), r["job"]))
    try:
        offset = max(0, int(query.get("offset", 0)))
        limit = max(1, min(100, int(query.get("limit", 50))))
    except (ValueError, TypeError):
        offset, limit = 0, 50
    return {**result, "rows": rows[offset:offset+limit], "total": len(rows), "offset": offset, "limit": limit,
            "has_more": offset + limit < len(rows)}
