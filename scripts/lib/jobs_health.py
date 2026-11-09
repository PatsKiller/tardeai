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
_SINGLE = threading.Lock()
_FAILURES = {"RUN_FAILED", "RUN_TIMEOUT", "RUN_REFUSED"}
#: The independent watchdog writes every minute. An observation arms the Jobs light for this long.
MONITOR_MAX_AGE = timedelta(seconds=180)
#: A receipt may be stamped just ahead of the clock that reads it (rewritten while this projection
#: was being built, or small skew between the writers). Beyond this it is not trusted: a receipt
#: from the future is not evidence that anything ran.
MONITOR_CLOCK_SKEW = timedelta(seconds=60)
#: Modes that execute the lane without doing the work. Evidence that a lane RUNS; never evidence that it worked.
_DRY_MODES = {"dry_run", "shadow", "preflight"}
#: Why a job's execution could not be measured, as the page groups it (LQ-20261107-246). The order here is the
#: order the breakdown reads in: a lane no scheduler installs explains the unknown before a schedule this reader
#: cannot parse does, and both before an absent run.
NOT_MEASURED_GROUPS = (
    ("never_scheduled", "never scheduled"),
    ("schedule_not_measured", "schedule this reader cannot measure"),
    ("no_run_source", "no run source"),
    ("dry_run_only", "dry run only"),
    ("no_success_measured", "run recorded, no success"),
)
#: The generic text cause() returns when a failure carries no stderr and no specific reason.
NO_DIAGNOSTIC = "Failure recorded; stderr diagnostic was not retained"
#: A job log's last error line explains a wrapper failure only if the log was written this close to it.
LOG_DIAGNOSTIC_SLACK = timedelta(minutes=5)
_ERROR_LINE = re.compile(r"^[A-Za-z_][\w.]*(?:Error|Exception|Exit|Interrupt)(?::|$)")
_LINE_TIME = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?")


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


def _line_time(line: str):
    """The timestamp printed on a log line, or None. A naive stamp is host time, America/New_York."""
    match = _LINE_TIME.search(line)
    if not match:
        return None
    try:
        at = datetime.fromisoformat(match.group(0).replace(" ", "T", 1).replace("Z", "+00:00"))
    except ValueError:
        return None
    return (at if at.tzinfo else at.replace(tzinfo=ZoneInfo("America/New_York"))).astimezone(timezone.utc)


def last_log_error(path: Path):
    """The last exception line in a job's own log tail, with the time that error was written.

    Host cron lines send stderr into the job log (``>> logs/<job>.log 2>&1``), so the safe_flock
    wrapper event records only ``exit_code: 1``. The traceback's final line is in this log.
    2026-10-30: the stop supervisor failed 137 times on ``AssertionError: ALPACA_MODE must be paper``
    and the Jobs page could only say the diagnostic was not retained.

    The time belongs to the error, not to the file: the nearest timestamp printed in the error's own
    block (after the previous error line), else the file's last write only when the error line is
    the last thing in the log. An older error followed by later untimed output has no time and is
    never attached to a newer failure. The line is returned raw; the caller shows it via ``cause()``,
    which redacts it.
    """
    try:
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        with path.open("rb") as stream:
            stream.seek(0, 2)
            start = max(0, stream.tell() - 64 * 1024)
            stream.seek(start)
            raw = stream.read(64 * 1024)
        if start:
            raw = raw.partition(b"\n")[2]
    except OSError:
        return None
    lines = [line.strip() for line in raw.decode("utf-8", errors="replace").splitlines()]
    lines = [line for line in lines if line]
    found = None
    for index, line in enumerate(lines):
        if _ERROR_LINE.match(line):
            found = index
    if found is None:
        return None
    at = None
    for index in range(found, -1, -1):
        if index != found and _ERROR_LINE.match(lines[index]):
            break
        at = _line_time(lines[index])
        if at:
            break
    if at is None and found == len(lines) - 1:
        at = mtime
    if at is None:
        return None
    line = lines[found]
    if len(line) > 400:
        # Cut at a word boundary: a cut through the middle of a token would leave a fragment that no
        # redaction pattern recognises (review 2026-11-01).
        line = line[:400].rsplit(" ", 1)[0] + " …"
    return {"line": line, "at": at}


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


# Operator-facing wording for evidence codes (2026-10-25: the Ops Controls Jobs "Missed" explanation printed raw codes
# and a script path). Codes and paths stay in the stores; the UI gets sentences.
_GAP_TEXT = {
    "journal_history_window_truncated": "the run journal is longer than the part that was read, so older runs are not counted",
    "journal_malformed_line": "some run-journal lines could not be read",
    "journal_unavailable": "the run journal could not be read",
    "wrapper_journal_unavailable": "the run journal could not be read",
    "lane registry unavailable": "the job list could not be read",
    "run ledger unavailable": "the n8n run ledger could not be read",
    "ledger absent": "the n8n run ledger could not be read",
    "ledger unreadable": "the n8n run ledger could not be read",
}
_LANE_GAP_TEXT = {
    "fallback_log_unavailable": "its log could not be read",
    "receipt_path_not_admitted": "its run receipt is stored outside the allowed folders",
    "receipt_unavailable": "its run receipt could not be read",
}
_REASON_TEXT = {
    "output_unverifiable": "The run finished but its output could not be verified",
    "empty_output": "The run finished but produced no output",
    "run_timeout": "The run timed out",
    "lock_skip": "The run was skipped because another copy was still running",
}
# A path-like token: anything with a slash and a file name, or a bare file name with a script/data extension.
_PATH_RE = re.compile(r"(?:~|\.{1,2})?/?(?:[\w.@-]+/)+[\w.@-]+|\b[\w.-]+\.(?:sh|py|mjs|js|ts|json|jsonl|log|sqlite|db|env|yaml|yml|txt)\b")


def _path_word(match: re.Match) -> str:
    token = match.group(0)
    low = token.lower()
    if "secret" in low or low.endswith(".env") or "bws" in low:
        return "the secrets loader"
    if low.endswith((".sh", ".py", ".mjs", ".js", ".ts")):
        return "a script"
    if low.endswith(".log"):
        return "a log file"
    return "a file"


def plain_reason(text) -> str | None:
    """Plain-language version of an evidence code / diagnostic for the UI: known codes become sentences and no file
    path is ever shown (it becomes "a script", "a log file", "the secrets loader", ...).

    Only for evidence codes and diagnostics. Never pass operator-authored prose such as a lane's ``state_reason``:
    it is already written for the operator and is rendered verbatim (#2178 F1)."""
    if text is None:
        return None
    raw = str(text).strip()
    if not raw:
        return raw
    if raw in _GAP_TEXT:
        return _GAP_TEXT[raw]
    if raw.lower() in _REASON_TEXT:
        return _REASON_TEXT[raw.lower()]
    lane, sep, code = raw.rpartition(":")
    if sep and code in _LANE_GAP_TEXT and lane and " " not in lane:
        return f"{lane}: {_LANE_GAP_TEXT[code]}"
    return _PATH_RE.sub(_path_word, raw)


def _measurement(unknown: int, collection_gaps: list, groups: dict | None = None) -> dict:
    """A count that cannot be measured is a gap, never 0 (operator design rule 2026-10-25).

    ``missed`` is only countable for jobs whose schedule and run receipts are measured. With unmeasured jobs
    (or an incomplete collection) a ``missed`` of 0 is not a fact, so readers get ``missed_measured`` False
    and the reason; ``missed`` itself stays the measured floor for existing readers (platform_health).

    ``not_measured_groups`` splits the same total by WHY it is unmeasured (LQ-20261107-246). It is additive:
    the flat ``not_measured`` count and ``gap_reasons`` stay exactly as they were for every existing reader.
    """
    reasons = []
    if unknown:
        reasons.append(f"{unknown} job{'s' if unknown != 1 else ''} not measured (no run receipt or no measurable "
                       "schedule), so missed runs among them cannot be counted")
    if collection_gaps:
        reasons.append("execution evidence incomplete: " + "; ".join(plain_reason(g) for g in collection_gaps[:3]))
    return {"not_measured": unknown, "missed_measured": not reasons,
            "gap_reasons": {"missed": " · ".join(reasons) or None,
                            "not_measured": "No run receipt or no measurable schedule" if unknown else None},
            "not_measured_groups": dict(groups or {})}


#: The operations watchers surfaced by the Jobs & health stoplight strip (operator 2026-10-28: "a mode in the
#: command center that shows stoplights when these along with the alerts"). Each is a guard that must actually run
#: for "did it die and did anyone notice" to be answered honestly. An absent or unwired watcher renders red/amber,
#: never silently green — the same "a component reporting success is not evidence" rule as the rows below.
WATCHER_LANES = {
    "self-heal-fixer": "Self-heal fixer",
    "pr-merge-telegram-notify": "Merge notifier",
    "delivery-failure-alerts": "Failure pager",
}


def _watchers(registry: dict, rows: list[dict], monitor: dict, monitor_ok: bool) -> list[dict]:
    """Deterministic read-only watcher lights from the registry, the run rows and the independent monitor.

    ``status`` is one of ok / degraded / down / absent; the strip maps it to green / amber / red / red.
    """
    by_lane = {r["lane_id"]: r for r in rows}
    out = [{"id": "missed-run-watchdog", "label": "Missed-run watchdog",
            "status": "ok" if monitor_ok else "degraded", "cause": None if monitor_ok else monitor["cause"]}]
    for lane_id, label in WATCHER_LANES.items():
        row = by_lane.get(lane_id)
        if row is None:
            out.append({"id": lane_id, "label": label, "status": "absent",
                        "cause": "Not a registered job — it cannot run, watch or page"})
            continue
        state, result = row["state"], row["result"]
        if result == "failed":
            status, cause = "down", row["cause"]
        elif state in {"PAUSED", "DISABLED"}:
            status, cause = "degraded", row["cause"] or f"{label} is {state.lower()}: designed, not running"
        elif state == "NEVER_SCHEDULED":
            status, cause = "degraded", f"{label} is never scheduled: its unit is not installed"
        elif state == "RETIRED":
            status, cause = "absent", f"{label} is retired"
        elif result in {"succeeded", "due", "skipped", "outside_window"}:
            status, cause = "ok", None
        else:
            status, cause = "degraded", row["cause"] or f"{label} is not proven running"
        out.append({"id": lane_id, "label": label, "status": status, "cause": cause})
    return out


def _grade_monitor(watchdog: dict, read_at: datetime) -> tuple[dict, bool]:
    """Age the independent-monitor receipt against the clock that read it.

    ``read_at`` is that clock, not the projection clock captured before a slow jobs-board build.
    A receipt rewritten during the build is newer than the build clock; measuring against the
    build clock makes a fresh receipt look future-dated and the 180 s check reports UNKNOWN.
    """
    if read_at.tzinfo is None:
        raise ValueError("jobs health requires an aware receipt clock")
    seen = instant(watchdog.get("observed_at"))
    age = (read_at - seen) if seen else None
    monitor_ok = bool(
        watchdog.get("schema") == W.SCHEMA and watchdog.get("mode") == "monitor"
        and age is not None and -MONITOR_CLOCK_SKEW <= age <= MONITOR_MAX_AGE)
    monitor = {
        "observed_at": watchdog.get("observed_at"),
        "status": watchdog.get("status") if monitor_ok else "UNKNOWN",
        "cause": None if monitor_ok else "Independent monitor receipt missing, stale or a dry run",
        "notification": watchdog.get("notification") if monitor_ok else None,
    }
    return monitor, monitor_ok


def _apply_monitor(result: dict, watchdog: dict, read_at: datetime) -> dict:
    """Re-grade the monitor on a served jobs-board body. Row data stays. The cached body is not mutated.

    The jobs board is a request cache (no lane writes it) and may be served for up to six hours.
    Its frozen monitor verdict is whatever the 180 s check said at compute time. The page prints
    that verdict, so an hour-old snapshot keeps reporting UNKNOWN after the watchdog receipt,
    which is rewritten every minute, has recovered. The receipt is a small read; the row rebuild is not.
    """
    if not isinstance(result, dict) or "monitor" not in result:
        return result
    monitor, monitor_ok = _grade_monitor(watchdog, read_at)
    watchers = []
    for row in result.get("watchers") or []:
        if row.get("id") == "missed-run-watchdog":
            watchers.append({**row, "status": "ok" if monitor_ok else "degraded",
                             "cause": None if monitor_ok else monitor["cause"]})
        else:
            watchers.append(row)
    incidents = [row for row in (result.get("incidents") or []) if row.get("id") != "job_monitor_unmeasured"]
    if not monitor_ok:
        incidents.append({"id": "job_monitor_unmeasured", "severity": "warning",
                          "title": "Job monitoring needs attention", "message": monitor["cause"],
                          "href": "/ops/jobs", "source": "job_execution"})
    out = {**result, "monitor": monitor, "incidents": incidents, "incident_count": len(incidents)}
    if result.get("watchers") is not None:
        out["watchers"] = watchers
    return out


def build(registry: dict, snapshot: dict, runs: list[dict], watchdog: dict, *, now: datetime, trading_day,
          read_at: datetime | None = None) -> dict:
    """``now`` is the projection clock. ``read_at`` is when the watchdog receipt was read.

    Defaults to ``now`` so a caller that captured every store at one clock keeps that clock.
    ``_load`` passes the wall clock just after the receipt read, so a receipt rewritten during
    collection is graded against that read, not against the clock from before collection.
    """
    if now.tzinfo is None:
        raise ValueError("jobs health requires an aware clock")
    read_at = read_at or now
    by_lane = {}
    #: Lanes the ledger shows EXECUTING, but only as a dry run / shadow. Today they are dropped here and the
    #: page cannot tell them from a lane that never ran at all (LQ-20261107-246: 191 "not measured" rows, of
    #: which 9 run every few minutes in shadow). A dry run is not proof of work — but "it runs, in shadow" is
    #: a different, actionable fact from "nothing records this lane", so it is carried, never counted as success.
    dry_only = {}
    for run in runs:
        at = instant(run.get("finished_at") or run.get("started_at") or run.get("requested_at"))
        pending_live = run.get("mode") == "live" and run.get("state") in {"REQUESTED", "RUNNING"}
        if at and at <= now and (RV.effective_mode(run) == "live" or pending_live):
            by_lane.setdefault(run.get("lane_id"), []).append(run)
        elif (at and at <= now and (RV.effective_mode(run) or run.get("mode")) in _DRY_MODES
              and run.get("lane_id")):
            dry_only[run["lane_id"]] = max(at, dry_only.get(run["lane_id"], at))
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
        log_error = (captured.get("log_errors") or {}).get(lane_id)
        if (diagnostic == NO_DIAGNOSTIC and failure_at and log_error
                and abs(log_error["at"] - failure_at) <= LOG_DIAGNOSTIC_SLACK):
            source = (lane.get("output_signal") or {}).get("path") or "the job log"
            diagnostic = cause({}, f"{log_error['line']} (last error line in {source})")
        if last.get("state") in _FAILURES:
            if failure_at is None or last_at and last_at >= failure_at:
                failure_at, diagnostic = instant(last.get("finished_at")), cause(RV.receipt_of(last), last.get("reason"))
        try:
            due, upcoming, issue, gated, due_today = _schedule(lane, now, trading_day)
        except (ValueError, TypeError, KeyError):
            due, upcoming, issue, gated, due_today = [], None, "schedule could not be measured", False, False
        outcome, reason = "unknown", "Successful execution is not yet measured"
        # state_reason is operator-authored prose from the registry, not an evidence code: it is shown verbatim.
        # Feeding it to plain_reason rewrites timezones and section references into "a file" (#2178 F1).
        reason_is_prose = False
        if state in {"PAUSED", "RETIRED", "DISABLED"}:
            outcome, reason = ("retired" if state == "RETIRED" else "paused"), lane.get("state_reason") or f"Job is {state.lower()}"
            reason_is_prose = True
            upcoming = None
        elif failure_at and (success is None or failure_at > success):
            outcome, reason = "failed", diagnostic
        elif check.get("status") == "SKIPPED_BY_POLICY":
            # Deliberate off-peak / policy skip (receipt reason offpeak_skip): the lane fired and the
            # dispatcher refused the child by design. That is not a missed run (LQ-20261107-1408 /
            # page defect 144 — Hermes usefulness backfill labelled Missed on /v3/ops/jobs).
            gate = check.get("offpeak_gate") or "policy"
            n = len(check.get("policy_skipped_fires") or [])
            fires = f"{n} scheduled fire{'s' if n != 1 else ''}" if n else "scheduled fires"
            outcome, reason = (
                "skipped",
                f"Off-peak gate ({gate}) skipped {fires}; RUN_DONE offpeak_skip is deliberate, not a miss",
            )
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
        # An unmeasured row still names WHAT is missing. "Not measured" as one flat number is the defect
        # (LQ-20261107-246): the page could not separate a lane nothing records from one that runs every five
        # minutes in shadow, so neither could be acted on.
        gap = None
        if outcome == "unknown":
            if state == "NEVER_SCHEDULED":
                # A registered lane with no installed unit. "Schedule not measured" would blame the reader for a
                # schedule that does not exist; this is a registration the operator either wires up or retires.
                gap, reason = "never_scheduled", "Never scheduled: no scheduler installs this lane"
            elif issue:
                gap = "schedule_not_measured"
            elif not values and lane_id in dry_only:
                gap, reason = "dry_run_only", f"Runs only as a dry run (last {W.iso(dry_only[lane_id])}); a dry run does not prove work"
            elif values:
                gap, reason = "no_success_measured", "A run is recorded but no successful execution is measured"
            else:
                gap, reason = "no_run_source", "No run ledger row, wrapper event or proven log for this lane"
        rows.append({"lane_id": lane_id, "job": lane.get("display_name") or lane_id.replace("-", " ").replace("_", " ").capitalize(),
            "scheduler": scheduler.get("kind") or "unknown", "state": state, "result": outcome,
            "last_run_at": W.iso(last_at) if last_at else None, "last_success_at": W.iso(success) if success else None,
            "successful_run_id": successful[-1].get("run_id") if successful else None,
            "next_due_at": W.iso(upcoming) if upcoming else None, "due_today": due_today,
            "missed_fires": check.get("missed_fires"), "market_hours_only": gated,
            "cause": reason if reason_is_prose else plain_reason(reason),
            "evidence_gap": gap,
            "evidence": last.get("run_id") or ("wrapper event" if events else None)})
    counts = Counter(row["result"] for row in rows)
    monitor, monitor_ok = _grade_monitor(watchdog, read_at)
    incidents = [{"id": row["lane_id"], "severity": "critical" if row["result"] == "failed" else "warning",
                  "title": f"{row['job']}: {row['result'].replace('_', ' ')}", "message": row["cause"],
                  "href": "/ops/jobs", "source": "job_execution"}
                 for row in rows if row["result"] in {"failed", "missed"}]
    if not monitor_ok:
        incidents.append({"id": "job_monitor_unmeasured", "severity": "warning", "title": "Job monitoring needs attention",
                          "message": monitor["cause"], "href": "/ops/jobs", "source": "job_execution"})
    gaps = Counter(row["evidence_gap"] for row in rows if row["result"] == "unknown" and row.get("evidence_gap"))
    return {"schema": SCHEMA, "as_of": W.iso(now), "authority": "READ_ONLY_ADVISORY", "rows": rows,
        "summary": {"due_today": sum(r["due_today"] and r["state"] == "ACTIVE" for r in rows),
                    **{key: counts[key] for key in (
                        "succeeded", "failed", "missed", "skipped", "paused", "retired", "unknown", "due", "outside_window",
                    )},
                    **_measurement(counts["unknown"], captured.get("collection_gaps") or [],
                                   {key: gaps[key] for key, _ in NOT_MEASURED_GROUPS})},
        "monitor": monitor, "watchers": _watchers(registry, rows, monitor, monitor_ok),
        "incidents": incidents, "incident_count": len(incidents),
        "coverage_gaps": captured.get("collection_gaps") or [],
        "note": "Execution evidence only. An enabled schedule, fresh log or dry run does not prove successful work."}


def _load(root: Path, registry_path: Path, now: datetime, *, read_at: datetime | None = None):
    """``read_at`` pins the monitor clock in tests. None reads the wall clock after the receipt."""
    from scripts.cron_outage_watchdog import bind_components, collect
    from scripts.lib.scheduler_operations import read_run_ledger
    from scripts.market_session import is_trading_day
    registry = _json(registry_path)
    cfg = _json(ROOT / "config/cron_outage_watchdog.json")
    allowlist = _json(ROOT / "config/n8n_run_allowlist.json") or None
    registry = bind_components(registry, cfg, allowlist)
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
        error = last_log_error(path)
        if error:
            snapshot.setdefault("log_errors", {})[W.identity(lane)] = error
    runs, measured, why = read_run_ledger(root / "data/governance/n8n_coordination_ledger.sqlite")
    if not measured:
        snapshot.setdefault("collection_gaps", []).append(why or "run ledger unavailable")
    if not registry.get("lanes"):
        snapshot.setdefault("collection_gaps", []).append("lane registry unavailable")
    watchdog = _json(root / "data/runtime/cron_outage_watchdog_latest.json")
    report = build(registry, snapshot, runs, watchdog, now=now, trading_day=is_trading_day,
                   read_at=read_at or datetime.now(timezone.utc))
    from scripts.lib.jobs_conflict_errors import get_data_errors
    report["data_errors"] = get_data_errors(root)
    return report


FRESH_S = 60.0           # a body this young is served as is
MAX_STALE_S = 6 * 3600.0  # an older last-good body is not served; the request computes inline
_REFRESHING: set = set()
LAST_GOOD_REL = "data/runtime/jobs_health_last_good.json"


def _store_last_good(root: Path, result: dict, as_of: str) -> None:
    """Atomic 0600 copy of the last good body so a portfolio-server restart does not start cold."""
    try:
        path = root / LAST_GOOD_REL
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
            json.dump({"as_of": as_of, "result": result}, fh, default=str)
        os.replace(tmp, path)
    except Exception:
        pass  # a cache write failing never fails the read


def _read_last_good(root: Path):
    try:
        raw = json.loads((root / LAST_GOOD_REL).read_text())
        at = datetime.fromisoformat(raw["as_of"])
        if isinstance(raw.get("result"), dict) and "rows" in raw["result"]:
            return time.time() - at.timestamp(), raw["result"], raw["as_of"]
    except Exception:
        pass
    return None


def _compute(root: Path, registry: Path, key) -> tuple:
    result = _load(root, registry, datetime.now(timezone.utc))
    as_of = datetime.now(timezone.utc).isoformat()
    with _LOCK:
        _CACHE.clear()
        _CACHE[key] = (time.time(), result, as_of)
    _store_last_good(root, result, as_of)
    return result, as_of


def _refresh(root: Path, registry: Path, key) -> None:
    try:
        _compute(root, registry, key)
    except Exception:
        pass
    finally:
        with _LOCK:
            _REFRESHING.discard(key)


def _start_refresh(root: Path, registry: Path, key) -> bool:
    """One background refresh per key; the caller holds _LOCK."""
    if key in _REFRESHING:
        return True
    _REFRESHING.add(key)
    threading.Thread(target=_refresh, args=(root, registry, key), daemon=True, name="jobs-health-refresh").start()
    return True


def get_jobs_health(query=None, *, state_root=None, registry_path=None, now=None):
    """Stale-while-revalidate (LQ-20261107-219): the full projection takes 15-33 s cold, past the 30 s browser
    limit, so a body up to MAX_STALE_S old is served at once (stamped _swr) while ONE background thread
    recomputes; no caller waits on a held lock. With no last-good body (cold start, nothing on disk) the
    request computes inline, as before. An explicit ``now`` bypasses all caching (tests)."""
    root = Path(state_root or os.environ.get("TRADEAI_STATE_ROOT") or Path.home() / "trade-ai-releases/persistent-state")
    registry = Path(registry_path or ROOT / "config/lane_registry.json")
    query = query or {}
    key = (str(root), str(registry))
    if now is not None:
        result = _load(root, registry, now)
        swr = None
    else:
        with _LOCK:
            cached = _CACHE.get(key)
        source = "memory"
        if cached is None:
            disk = _read_last_good(root)
            if disk is not None and disk[0] <= MAX_STALE_S:
                cached = (time.time() - disk[0], disk[1], disk[2])
                source = "disk"
        if cached is not None and time.time() - cached[0] <= MAX_STALE_S:
            age = time.time() - cached[0]
            result, as_of = cached[1], cached[2]
            stale = age > FRESH_S
            with _LOCK:
                refreshing = _start_refresh(root, registry, key) if stale else key in _REFRESHING
            swr = {"as_of": as_of, "age_s": round(age, 1), "stale": stale, "refreshing": refreshing, "source": source}
        else:
            with _SINGLE:  # concurrent cold callers share one compute
                cached = _CACHE.get(key)
                if cached is not None and time.time() - cached[0] <= FRESH_S:
                    result, as_of = cached[1], cached[2]
                else:
                    result, as_of = _compute(root, registry, key)
            swr = {"as_of": as_of, "age_s": 0.0, "stale": False, "refreshing": False, "source": "computed"}
        # The served body can be an hour old. Re-grade only the monitor from the live receipt so
        # the 180 s check sees that receipt, not the snapshot's frozen observed_at.
        result = _apply_monitor(result, _json(root / "data/runtime/cron_outage_watchdog_latest.json"),
                                datetime.now(timezone.utc))
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
    out = {**result, "rows": rows[offset:offset+limit], "total": len(rows), "offset": offset, "limit": limit,
           "has_more": offset + limit < len(rows)}
    if swr:
        out["_swr"] = swr
    return out
