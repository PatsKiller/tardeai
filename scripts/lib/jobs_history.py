"""Per-job run history for /ops/jobs: every registered lane, when it ran, when it did not, and what fixed it.

Operator 2026-11-06: "We should see all of the jobs, when they ran, when they didn't run, when it had to be fixed,
etc." and n8n "should be self-healing with the APIs, and that should show up on the ops page."

Read-only projection over stores that already exist; it adds no scheduler, writer, subprocess or migration:

* ``config/lane_registry.json`` (+ ``config/cron_outage_watchdog.json`` wrapper bindings) — every lane, its scheduler,
  its declared schedule and output signal.
* n8n coordination ledger (``data/governance/n8n_coordination_ledger.sqlite``, opened ``mode=ro``) — ``runs`` (the
  RunReceipt@v1 rows ``scripts/n8n_run_executor.py`` writes: attempt, parent_run_id, attempt_states),
  ``dead_letters`` and ``breakers``.
* the safe_flock wrapper journal (``logs/safe_flock_events.jsonl``, tail only) — host cron runs that are wrapped.
* a lane's declared JSON receipt (``output_signal``) — last run only — and its output file's write time.
* the incident ledger index (``data/coordination/incidents/index.json``), the self-heal fixer state, the n8n failure
  diagnosis state and the cron self-heal state — the "fixed" events.

Honesty rules (AGENTS.md 28.9, operator design rule 2026-10-25):
* every time shown is the writer's own time (run start/finish, journal ``ts``, receipt field, incident time, file
  write time). The projection's compute time is ``computed_at`` and is never shown as a source's time;
* a lane without per-run evidence says WHY (``history_gap``) and its missed count is ``None``, never 0;
* an output file's write time is labelled as such and never counts as a successful run.

AUTHORITY: READ_ONLY_ADVISORY. MBI_BEHAVIOR = 0.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
import json
import logging
import os
from pathlib import Path
import sqlite3
import threading
import time
from zoneinfo import ZoneInfo

from scripts.lib import cron_outage_watchdog as W
from scripts.lib.cron_schedule import fires_between
from scripts.lib.jobs_health import plain_reason

SCHEMA = "JobRunHistory@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
ROOT = Path(__file__).resolve().parents[2]
#: Ledger rows older than this are not read; the slot window below must fit inside it.
LEDGER_DAYS = 10
#: Expected slots are evaluated over this window (and at most SLOT_LIMIT of the newest are returned).
SLOT_DAYS = 7
SLOT_LIMIT = 10
RUN_LIMIT = 10
#: A slot is only judged once this long has passed (or the next slot started, whichever is sooner).
SLOT_GRACE = timedelta(minutes=15)
#: A run is attributed to a slot when it started up to this long before the fire time (clock skew, early dispatch).
EARLY_TOLERANCE = timedelta(minutes=2)
#: Longest window after a fire in which a start still counts as that slot's run.
MAX_SLOT_WINDOW = timedelta(hours=6)
JOURNAL_TAIL_BYTES = 24 * 1024 * 1024
FIX_DAYS = 14
CACHE_SECONDS = 60
_INACTIVE = {"PAUSED": "paused", "RETIRED": "retired", "NEVER_SCHEDULED": "never_scheduled", "DISABLED": "paused"}
_LEDGER_RESULT = {"RUN_DONE": "succeeded", "RUN_FAILED": "failed", "RUN_TIMEOUT": "timed_out",
                  "RUN_REFUSED": "refused", "RUN_SKIPPED_LOCK": "skipped_lock", "REQUESTED": "requested",
                  "RUNNING": "running"}
_FAILED = {"failed", "timed_out", "refused"}
LOG = logging.getLogger(__name__)

# ── plain-English job descriptions + categories (operator 2026-11-06: "at least a line or two of normalization of what
# each job does" and "another page that categorizes all of the jobs") ─────────────────────────────────────────────
#: ``{"<lane_id>": {"title", "category", "does", "breaks"}}`` parts, merged in file-name order (a later part wins).
DESCRIPTIONS_DIR = ROOT / "config/job_descriptions"
#: The ordered category list ``[{"key", "label", "blurb"}]`` the catalog groups by.
CATEGORIES_PATH = ROOT / "config/job_categories.json"
_DESCRIPTION_FIELDS = ("title", "category", "does", "breaks")
#: Fallback category from the registry ``owner`` when a lane has no description (or names an unknown category).
OWNER_CATEGORY = {
    "platform": "ops", "os": "ops", "ops": "ops", "tradeai-core": "ops",
    "portfolio": "portfolio", "execution": "portfolio",
    "research": "research", "cio": "cio", "advisory": "cio", "learning": "learning",
    "proposals": "signals", "scalp": "signals", "watch": "signals", "options": "signals", "signals": "signals",
    "agents": "agents_llm", "hermes": "agents_llm", "coordination": "agents_llm",
    "comms": "alerts", "notifications": "alerts", "defense": "risk",
}


def _at(value):
    """An aware UTC instant from an ISO string or epoch seconds, else None."""
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
        return datetime.fromtimestamp(value, tz=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else None


def _iso(value):
    return W.iso(value) if value else None


def _text(value, limit=300):
    """Plain-language, path-free, bounded text for the page."""
    out = plain_reason(value)
    if not out:
        return None
    return out if len(out) <= limit else out[:limit].rsplit(" ", 1)[0] + " …"


# ── schedule ──────────────────────────────────────────────────────────────────────────────────────────────────────

def _readable(expr) -> bool:
    try:
        fires_between(expr, datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2026, 1, 1, tzinfo=timezone.utc), "UTC")
        return True
    except (ValueError, KeyError):
        return False


def cadence_of(lane: dict) -> dict:
    """What the registry declares: wall schedules (cron fields + timezone) and/or a cadence in hours."""
    expressions, tz, issue = W.schedules(lane)
    unreadable = [ex for ex in expressions if not _readable(ex)]
    expressions = [ex for ex in expressions if ex not in unreadable]
    if unreadable and not expressions:
        issue = "unreadable"
    hours = lane.get("expected_cadence_hours")
    hours = float(hours) if isinstance(hours, (int, float)) and not isinstance(hours, bool) and hours > 0 else None
    scheduler = lane.get("scheduler") or {}
    gated = lane.get("respect_calendar") is True or "market_day_gate.sh" in str(
        scheduler.get("command_text") or scheduler.get("expression") or "")
    return {"expressions": expressions, "timezone": tz, "every_hours": hours, "market_days_only": gated,
            "schedule_gap": None if expressions else (
                "The declared schedule could not be read" if issue == "unreadable"
                else "No wall-clock schedule is declared for this job" if issue == "recurring_schedule_not_measured"
                else "Runs at boot only; it has no recurring schedule" if issue else None)}


def _fires(expr, start, end, tz):
    """Fires of one expression; an expression the parser cannot read yields none (cadence_of reports it)."""
    try:
        return fires_between(expr, start, end, tz)
    except (ValueError, KeyError):
        return []


def expected_slots(cadence: dict, now: datetime, trading_day, *, days=SLOT_DAYS, limit=SLOT_LIMIT) -> list[dict]:
    """The newest ``limit`` fires in the last ``days``, oldest first, each with the end of its matching window."""
    exprs, tz = cadence["expressions"], cadence["timezone"]
    if not exprs:
        return []
    zone = ZoneInfo(tz)
    fires: list[datetime] = []
    for span in (timedelta(hours=6), timedelta(hours=48), timedelta(days=days)):
        start = now - span
        fires = sorted({f.at.astimezone(timezone.utc) for ex in exprs for f in _fires(ex, start, now, tz)
                        if not cadence["market_days_only"] or trading_day(f.at.astimezone(zone))})
        if len(fires) > limit:
            break
    fires = fires[-(limit + 1):]
    upcoming = sorted({f.at.astimezone(timezone.utc) for ex in exprs
                       for f in _fires(ex, now, now + MAX_SLOT_WINDOW, tz)})
    out = []
    for index, fire in enumerate(fires):
        nxt = fires[index + 1] if index + 1 < len(fires) else (upcoming[0] if upcoming else None)
        end = min(fire + MAX_SLOT_WINDOW, nxt) if nxt else fire + MAX_SLOT_WINDOW
        out.append({"at": fire, "window_end": end, "judge_at": min(fire + SLOT_GRACE, end)})
    return out[-limit:]


def judge_slots(slots: list[dict], runs: list[dict], *, now: datetime, covered_from: datetime | None) -> list[dict]:
    """Match each expected slot to a run that started in its window. ``runs`` carry aware ``_start``."""
    out = []
    for slot in slots:
        lo, hi = slot["at"] - EARLY_TOLERANCE, slot["window_end"]
        match = next((r for r in runs if r.get("_start") and lo <= r["_start"] < hi), None)
        if match:
            status = "ran" if match["mode"] != "dry_run" else "ran_dry_run"
            if match["result"] in _FAILED:
                status = "ran_failed"
            out.append({"slot_at": _iso(slot["at"]), "status": status, "run_id": match.get("run_id"),
                        "started_at": _iso(match["_start"])})
        elif covered_from is None or slot["at"] < covered_from:
            out.append({"slot_at": _iso(slot["at"]), "status": "not_measured", "run_id": None, "started_at": None})
        elif now < slot["judge_at"]:
            out.append({"slot_at": _iso(slot["at"]), "status": "pending", "run_id": None, "started_at": None})
        else:
            out.append({"slot_at": _iso(slot["at"]), "status": "missed", "run_id": None, "started_at": None})
    return out


# ── per-run evidence ──────────────────────────────────────────────────────────────────────────────────────────────

def ledger_run(row: dict) -> dict:
    states = row.get("attempt_states")
    if isinstance(states, str):
        try:
            states = json.loads(states)
        except ValueError:
            states = None
    started = _at(row.get("started_at")) or _at(row.get("requested_at"))
    return {"run_id": row.get("run_id"), "source": "n8n run ledger", "mode": "dry_run" if row.get("mode") == "dry_run" else "live",
            "result": _LEDGER_RESULT.get(row.get("state"), "unknown"), "requested_at": row.get("requested_at"),
            "started_at": _iso(started), "finished_at": _iso(_at(row.get("finished_at"))),
            "exit_code": row.get("exit_code") if type(row.get("exit_code")) is int else None,
            "duration_s": row.get("duration_s") if isinstance(row.get("duration_s"), (int, float)) else None,
            "attempt": row.get("attempt") if type(row.get("attempt")) is int else None,
            "retry_of": row.get("parent_run_id"), "requested_by": row.get("requested_by"),
            "inline_attempts": states if isinstance(states, list) and len(states) > 1 else None,
            "reason": _text(row.get("reason")), "_start": started}


def journal_runs(events: list[dict]) -> dict[str, list[dict]]:
    """Wrapper journal events -> runs per component (job_key), pairing ``started``/``completed`` by run_id."""
    by_run: dict[tuple, dict] = {}
    for event in events:
        component = str(event.get("component") or "")
        if not component or component.endswith(".dryrun") or not W.business_mode(event):
            continue
        kind = event.get("event_type")
        at = _at(event.get("ts"))
        if at is None or kind not in {"started", "completed", "lock_skip", "refused"}:
            continue
        key = (W.job_key(component), event.get("run_id") or f"{kind}:{event.get('ts')}")
        run = by_run.setdefault(key, {"run_id": event.get("run_id"), "source": "cron wrapper journal", "mode": "live",
                                      "result": "running", "requested_at": None, "started_at": None,
                                      "finished_at": None, "exit_code": None, "duration_s": None, "attempt": None,
                                      "retry_of": None, "requested_by": "host cron", "inline_attempts": None,
                                      "reason": None, "_start": None})
        if kind == "started":
            run["_start"], run["started_at"] = at, _iso(at)
        elif kind == "completed":
            code = event.get("exit_code")
            run["finished_at"] = _iso(at)
            run["exit_code"] = code if type(code) is int else None
            run["result"] = "succeeded" if code == 0 else "timed_out" if code in (124, 137) else "failed"
            if run["_start"] is None:
                run["_start"] = at
        elif kind == "lock_skip":
            run.update(result="skipped_lock", _start=at, started_at=_iso(at), finished_at=_iso(at),
                       reason="Skipped: the previous run still held the lock")
        else:
            run.update(result="refused", _start=at, started_at=_iso(at), finished_at=_iso(at),
                       reason=_text(event.get("message")) or "The wrapper refused to start the job")
    out: dict[str, list[dict]] = defaultdict(list)
    for (component, _), run in by_run.items():
        if run["started_at"] and run["finished_at"] and run["_start"]:
            finished = _at(run["finished_at"])
            run["duration_s"] = round((finished - run["_start"]).total_seconds(), 3) if finished else None
        out[component].append(run)
    for runs in out.values():
        runs.sort(key=lambda r: r["_start"] or datetime.min.replace(tzinfo=timezone.utc))
    return out


def receipt_run(receipt: dict, key: str | None) -> dict | None:
    """The single last run a lane's own receipt describes (it keeps no history)."""
    if not receipt or receipt.get("dry_run") is True or receipt.get("mode") in {"dry_run", "dry-run", "shadow", "preflight"}:
        return None
    started = _at(receipt.get("started_at"))
    finished = next((t for t in (_at(receipt.get(k)) for k in ("finished_at", "ended_at", "completed_at")) if t), None)
    from scripts.cron_outage_watchdog import receipt_success
    success = receipt_success(receipt, key)
    code = receipt.get("exit_code", receipt.get("exit"))
    status = str(receipt.get("status") or receipt.get("state") or "").lower()
    if success:
        result = "succeeded"
    elif (type(code) is int and code != 0) or receipt.get("ok") is False or status in {"failed", "error", "run_failed"}:
        result = "failed"
    else:
        result = "unknown"
    when = started or finished or (success[0] if success else None) or _at(receipt.get("as_of"))
    if when is None:
        return None
    return {"run_id": receipt.get("run_id"), "source": "run receipt (last run only)", "mode": "live", "result": result,
            "requested_at": None, "started_at": _iso(started), "finished_at": _iso(finished or (success[0] if success else None)),
            "exit_code": code if type(code) is int else None, "duration_s": None, "attempt": None, "retry_of": None,
            "requested_by": None, "inline_attempts": None,
            "reason": _text(receipt.get("error") or receipt.get("reason")) if result == "failed" else None,
            "_start": when, "_success_at": success[0] if success else None}


# ── fixed events ──────────────────────────────────────────────────────────────────────────────────────────────────

def fix_events(lane_id: str, keys: set[str], *, runs: list[dict], dead: list[dict], breakers: list[dict],
               incidents: list[dict], fixer_jobs: list[dict], episodes: list[dict], actions: list[dict],
               cron_heal: dict, since: datetime) -> list[dict]:
    """Every recorded retry / heal / incident for one lane, newest first. ``keys`` = lane id + wrapper component."""
    out = []

    def add(at, kind, by, outcome, detail, ref=None):
        when = _at(at)
        if when and when >= since:
            out.append({"at": _iso(when), "kind": kind, "by": by, "outcome": outcome, "detail": _text(detail), "ref": ref})

    by_id = {r["run_id"]: r for r in runs if r.get("run_id")}
    for run in runs:
        if run.get("attempt") and run["attempt"] > 1:
            parent = by_id.get(run.get("retry_of"))
            before = parent["result"].replace("_", " ") if parent else "an earlier attempt"
            add(run.get("requested_at") or run.get("started_at"), "retry", run.get("requested_by") or "retry policy",
                run["result"], f"Attempt {run['attempt']} of this slot after {before}", run.get("run_id"))
        if run.get("inline_attempts"):
            add(run.get("finished_at") or run.get("started_at"), "retry", "executor (inline retry)", run["result"],
                "Tries in one run: " + " → ".join(str(s).replace("RUN_", "").lower() for s in run["inline_attempts"]),
                run.get("run_id"))
    for row in dead:
        add(row.get("dead_at"), "dead_letter", "n8n dispatcher", "released" if row.get("released_at") else (row.get("verdict") or "dead"),
            f"Gave up after {row.get('attempts') or '?'} attempt(s): {(row.get('last_state') or '').replace('RUN_', '').lower()}"
            f"{' (' + str(row['last_reason']) + ')' if row.get('last_reason') else ''}", row.get("last_run_id"))
        if row.get("released_at"):
            add(row["released_at"], "dead_letter_released", row.get("released_by") or "operator", "released",
                row.get("release_note") or "Dead letter released", row.get("last_run_id"))
    for row in breakers:
        add(row.get("opened_at"), "breaker_opened", "n8n dispatcher", "open" if not row.get("released_at") else "released",
            f"Paused after {row.get('consecutive') or '?'} consecutive failures")
        if row.get("released_at"):
            add(row["released_at"], "breaker_released", "operator", "released", row.get("released_by") or "Breaker released")
    for rec in incidents:
        source = rec.get("source") or {}
        by = source.get("watcher") or source.get("agent") or source.get("kind") or "incident ledger"
        actions_tried = [a for a in rec.get("attempts") or [] if isinstance(a, dict)]
        tried = ", ".join(sorted({str(a.get("action") or a.get("class") or "action") for a in actions_tried}))
        refs = ", ".join(f"{r.get('kind')} {r.get('ref')}" for r in rec.get("fix_refs") or [] if isinstance(r, dict))
        add(rec.get("opened_at"), "incident_opened", by, rec.get("status"),
            f"{rec.get('severity') or ''} {rec.get('title') or ''}".strip(), rec.get("id"))
        for attempt in actions_tried:
            add(attempt.get("at"), "heal_attempt", attempt.get("actor") or by,
                "ok" if attempt.get("ok") is True else "failed" if attempt.get("ok") is False else "unknown",
                f"Tried {attempt.get('action') or attempt.get('class') or 'an action'}", rec.get("id"))
        if rec.get("closed_at") and rec.get("status") in {"fixed", "closed"}:
            how = "resolved automatically when the condition cleared" if rec.get("resolution") == "auto_resolved" else (
                f"fixed by {refs}" if refs else f"{rec.get('status')}")
            add(rec["closed_at"], "incident_closed", by, rec.get("status"),
                f"Incident {how}" + (f"; tried {tried}" if tried else ""), rec.get("id"))
    for job in fixer_jobs:
        for step in job.get("history") or []:
            add(step.get("at"), "self_heal_fixer", "self-heal fixer", step.get("state"),
                f"Code-fix job {job.get('job_id')} ({job.get('failure_kind') or 'failure'}): {str(step.get('state') or '').replace('_', ' ')}",
                job.get("incident_key"))
    for ep in episodes:
        add(ep.get("opened_at"), "diagnosis_opened", "n8n failure diagnosis", ep.get("status"),
            f"Failure episode opened ({ep.get('severity') or 'severity unknown'}; {ep.get('n') or 1} occurrence(s))")
        if ep.get("resolved_at"):
            add(ep["resolved_at"], "self_healed", "n8n failure diagnosis", "resolved", "Failure episode resolved: a later run succeeded")
    for act in actions:
        add(act.get("at"), "self_heal_action", "n8n self-heal", act.get("outcome"),
            f"Action {act.get('action_id')}: {str(act.get('outcome') or '').replace('_', ' ')}")
    for key in keys:
        state = cron_heal.get(key) or cron_heal.get(key.replace("-", "_"))
        if isinstance(state, dict) and state.get("last_act"):
            add(state["last_act"], "cron_self_heal", "cron self-heal", "acted",
                f"Cron self-heal acted (consecutive failures now {state.get('fails', 0)})")
    out.sort(key=lambda e: e["at"], reverse=True)
    return out


# ── assembly ──────────────────────────────────────────────────────────────────────────────────────────────────────

def _public(run: dict) -> dict:
    return {k: v for k, v in run.items() if not k.startswith("_")}


def lane_history(lane: dict, *, now: datetime, trading_day, ledger: list[dict], journal: list[dict],
                 ledger_since: datetime | None, journal_since: datetime | None, last_live_success: datetime | None,
                 receipt: dict | None, output_at: datetime | None, fixes: list[dict]) -> dict:
    lane_id = W.identity(lane)
    scheduler = lane.get("scheduler") or {}
    kind = scheduler.get("kind") or "unknown"
    state = lane.get("state") or "UNKNOWN"
    cadence = cadence_of(lane)
    component = W.component(lane)
    signal = lane.get("output_signal") or {}
    runs = sorted(ledger + journal, key=lambda r: r["_start"] or datetime.min.replace(tzinfo=timezone.utc))
    sources = list(dict.fromkeys(r["source"] for r in ledger + journal))
    covered = [t for t, rows in ((ledger_since, ledger), (journal_since, journal)) if rows and t]
    history_gap = None
    if not runs:
        if receipt:
            runs = [receipt]
            sources = ["run receipt (last run only)"]
        if kind == "systemd":
            history_gap = "no finished run recorded by the systemd unit snapshot (unit-run-snapshot lane) for this job yet"
        elif kind == "cron" and not component:
            history_gap = "this cron line is not wrapped by safe_flock, so its runs are not journaled"
        elif kind == "cron":
            history_gap = "no wrapper journal entry for this job in the last 11 days"
        elif kind == "n8n":
            history_gap = f"no n8n run ledger row in the last {LEDGER_DAYS} days"
        elif kind in {"event", "none"}:
            history_gap = "event-driven or unscheduled: there is no run schedule to compare against"
        else:
            history_gap = "no per-run record exists for this job"
        if receipt:
            history_gap = "only the last run is known (from its own receipt); " + history_gap
    live = [r for r in runs if r["mode"] == "live"]
    last = (live or runs)[-1] if runs else None
    success_times = [t for t in [last_live_success, *(_at(r["finished_at"]) for r in live if r["result"] == "succeeded"),
                                 receipt.get("_success_at") if receipt else None] if t and t <= now]
    last_success = max(success_times) if success_times else None
    slots = expected_slots(cadence, now, trading_day) if state == "ACTIVE" else []
    judged = judge_slots(slots, runs if sources and sources[0] != "run receipt (last run only)" else [],
                         now=now, covered_from=min(covered) if covered and sources and sources[0] != "run receipt (last run only)" else None)
    missed = [s for s in judged if s["status"] == "missed"]
    measured_slots = [s for s in judged if s["status"] != "not_measured"]
    missed_count = len(missed) if measured_slots else None
    elapsed = [s for s in slots if s["judge_at"] <= now]
    evidence_at = max([t for t in [last["_start"] if last else None, _at(last.get("finished_at")) if last else None, output_at] if t],
                      default=None)
    status, why = "ok", None
    if state in _INACTIVE:
        status, why = _INACTIVE[state], lane.get("state_reason") or f"Job is {state.lower().replace('_', ' ')}"
    elif state != "ACTIVE":
        status, why = "not_measured", f"Registry state {state} is not a known state"
    elif last and last["result"] in {"running", "requested"} and (not last_success or last["_start"] > last_success):
        status, why = "running", "Started; no completion recorded yet"
    elif last and last["result"] in _FAILED and (not last_success or (_at(last["finished_at"]) or last["_start"]) > last_success):
        status, why = "failed", last.get("reason") or (f"Exit code {last['exit_code']}" if last.get("exit_code") is not None
                                                       else f"Last run {last['result'].replace('_', ' ')}")
    elif judged and measured_slots and judged[-1]["status"] == "missed" or (
            missed and judged and judged[-1]["status"] == "pending" and len(judged) > 1 and judged[-2]["status"] == "missed"):
        status = "missed"
        why = f"No run recorded in the {' or '.join(sources)} for the {missed[-1]['slot_at']} slot"
        if output_at and output_at > _at(missed[-1]["slot_at"]):
            why += f"; its output file was still written at {_iso(output_at)} (it may run outside the recorded path)"
    elif not runs and not output_at:
        status, why = "not_measured", history_gap or "No run evidence"
    elif not sources or sources == ["run receipt (last run only)"]:
        # Evidence is a single receipt or an output file time: judge lateness against the schedule, never call it a run.
        latest_due = elapsed[-1]["at"] if elapsed else None
        if latest_due is None and cadence["every_hours"] and evidence_at:
            if now - evidence_at > timedelta(hours=cadence["every_hours"] * 1.5) + SLOT_GRACE:
                status, why = "late", f"Nothing recorded for {cadence['every_hours']:g} h × 1.5"
        elif latest_due and (evidence_at is None or evidence_at < latest_due - EARLY_TOLERANCE):
            status, why = "late", "No run or output recorded since the latest scheduled time"
        if status == "ok":
            status = "ok_unverified" if not (last and last["result"] == "succeeded") else "ok"
            why = None if status == "ok" else ("Output file was written on schedule; no run receipt proves success"
                                               if not last else "Last run's receipt does not state success")
    if why:
        why = why if state in _INACTIVE else _text(why)
    cadence_out = {k: cadence[k] for k in ("expressions", "timezone", "every_hours", "market_days_only", "schedule_gap")}
    missed_gap = None
    if missed_count is None:
        missed_gap = cadence["schedule_gap"] or history_gap or (
            "expected slots are older than the run history that was read" if slots else "no expected slot in the window")
    return {
        "lane_id": lane_id,
        "job": lane.get("display_name") or lane_id.replace("-", " ").replace("_", " ").capitalize(),
        "scheduler": kind, "state": state, "cadence": cadence_out,
        "status": status, "status_reason": why,
        "history_sources": sources, "history_gap": history_gap,
        "last_run": _public(last) if last else None,
        "last_success_at": _iso(last_success),
        "output": {"path_kind": signal.get("kind"), "written_at": _iso(output_at),
                   "note": "File write time of the job's declared output; not proof of a successful run"} if output_at else None,
        "missed_count": missed_count, "missed_gap": missed_gap,
        "runs": [_public(r) for r in runs[-RUN_LIMIT:]][::-1],
        "slots": judged[::-1],
        "fixes": fixes[:25],
        "fix_count": len(fixes),
        "last_fix": fixes[0] if fixes else None,
    }


def build(registry: dict, inputs: dict, *, now: datetime, trading_day) -> dict:
    if now.tzinfo is None:
        raise ValueError("job history requires an aware clock")
    since = now - timedelta(days=FIX_DAYS)
    ledger_by_lane = defaultdict(list)
    for row in inputs.get("ledger_runs") or []:
        ledger_by_lane[row.get("lane_id")].append(ledger_run(row))
    journal_by_component = journal_runs(inputs.get("journal_events") or [])
    unit_by_lane = unit_runs_by_lane(inputs.get("unit_runs") or [])
    group = lambda rows, key: {k: [r for r in rows if r.get(key) == k] for k in {r.get(key) for r in rows}}
    dead = group(inputs.get("dead_letters") or [], "lane_id")
    breakers = group(inputs.get("breakers") or [], "lane_id")
    episodes = group(inputs.get("episodes") or [], "lane")
    actions = group(inputs.get("actions") or [], "lane")
    incidents_by_job = defaultdict(list)
    for rec in inputs.get("incidents") or []:
        job = (rec.get("source") or {}).get("job")
        if job:
            incidents_by_job[str(job)].append(rec)
    fixer_by_lane = defaultdict(list)
    for job in inputs.get("fixer_jobs") or []:
        lane = str(job.get("lane") or "")
        fixer_by_lane[lane.removeprefix("incident-")].append(job)
    categories = inputs.get("categories") or []
    category_keys = {c["key"] for c in categories}
    rows = []
    for lane in registry.get("lanes") or []:
        lane_id = W.identity(lane)
        component = W.component(lane)
        keys = {lane_id} | ({component} if component else set())
        ledger = ledger_by_lane.get(lane_id, [])
        journal = (journal_by_component.get(component, []) if component else []) + unit_by_lane.get(lane_id, [])
        fixes = fix_events(lane_id, keys, runs=ledger, dead=dead.get(lane_id, []), breakers=breakers.get(lane_id, []),
                           incidents=[r for k in keys for r in incidents_by_job.get(k, [])],
                           fixer_jobs=[j for k in keys for j in fixer_by_lane.get(k, [])],
                           episodes=episodes.get(lane_id, []), actions=actions.get(lane_id, []),
                           cron_heal=inputs.get("cron_heal") or {}, since=since)
        row = lane_history(lane, now=now, trading_day=trading_day, ledger=ledger, journal=journal,
                           ledger_since=inputs.get("ledger_since"), journal_since=inputs.get("journal_since"),
                           last_live_success=_at((inputs.get("last_live_success") or {}).get(lane_id)),
                           receipt=(inputs.get("receipts") or {}).get(lane_id),
                           output_at=(inputs.get("output_times") or {}).get(lane_id), fixes=fixes)
        row.update(describe(lane, (inputs.get("descriptions") or {}).get(lane_id), category_keys))
        rows.append(row)
    # Every status key is present (a counted 0 is a real 0), so the page never has to default a missing count.
    counts = {k: 0 for k in ("ok", "ok_unverified", "failed", "missed", "late", "running", "not_measured", "paused",
                             "retired", "never_scheduled")}
    for row in rows:
        counts.setdefault(row["status"], 0)
        counts[row["status"]] += 1
    active = [r for r in rows if r["state"] == "ACTIVE"]
    return {
        "schema": SCHEMA, "authority": AUTHORITY, "computed_at": _iso(now),
        "summary": {"jobs": len(rows), "active": len(active), **dict(counts),
                    "with_missed": sum(1 for r in active if r["missed_count"]),
                    "missed_not_measured": sum(1 for r in active if r["missed_count"] is None),
                    "fixed_14d": sum(1 for r in rows if r["fix_count"]),
                    "no_run_history": sum(1 for r in active if not r["history_sources"] or r["history_sources"] == ["run receipt (last run only)"])},
        "sources": inputs.get("sources") or [],
        "gaps": inputs.get("gaps") or [],
        "categories": categories,
        "described": sum(1 for r in rows if r["does"]),
        "rows": rows,
        "note": "Times are the writers' own times. An output file's write time is not a successful run. "
                "Missed slots are counted only where per-run history covers the slot.",
    }


def describe(lane: dict, entry: dict | None, category_keys: set[str]) -> dict:
    """The lane's plain-English fields (each None when not written) plus its owner-based fallback category.

    ``category`` is only a described, known key; ``category_key`` is what the catalog groups by (described, else the
    owner fallback, else ``other``)."""
    entry = entry if isinstance(entry, dict) else {}
    out = {}
    for field in _DESCRIPTION_FIELDS:
        value = entry.get(field)
        out[field] = _text(value, 160 if field == "title" else 400) or None if isinstance(value, str) and value.strip() else None
    if out["category"] and category_keys and out["category"] not in category_keys:
        out["category"] = None
    owner = str(lane.get("owner") or "").strip() or None
    fallback = OWNER_CATEGORY.get(owner or "", "other")
    if category_keys and fallback not in category_keys:
        fallback = "other"
    return {**out, "owner": owner, "category_fallback": fallback, "category_key": out["category"] or fallback}


def read_categories(path: Path) -> tuple[list[dict], str | None]:
    """The ordered category list; a missing or malformed file is a gap, never an error."""
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        LOG.warning("job categories unreadable at %s: %s", path, type(exc).__name__)
        return [], "the job category list could not be read"
    items = doc.get("categories") if isinstance(doc, dict) else doc
    out, seen = [], set()
    for item in items if isinstance(items, list) else []:
        if isinstance(item, dict) and isinstance(item.get("key"), str) and item["key"] not in seen:
            seen.add(item["key"])
            out.append({"key": item["key"], "label": str(item.get("label") or item["key"]), "blurb": str(item.get("blurb") or "")})
    return out, None if out else "the job category list is empty"


def read_descriptions(directory: Path) -> tuple[dict, dict]:
    """Merge every ``*.json`` part (sorted by name; a later part wins per lane). A missing directory, an unreadable
    file or bad JSON is logged and noted, never raised."""
    merged, files, bad = {}, [], []
    try:
        parts = sorted(p for p in directory.glob("*.json") if p.is_file())
    except OSError:
        parts = []
    for part in parts:
        try:
            doc = json.loads(part.read_text(encoding="utf-8"))
            if not isinstance(doc, dict):
                raise ValueError("not an object")
        except (OSError, ValueError) as exc:
            LOG.warning("job descriptions part %s skipped: %s", part.name, exc)
            bad.append(part.name)
            continue
        files.append(part.name)
        for lane_id, entry in doc.items():
            if isinstance(lane_id, str) and isinstance(entry, dict):
                merged[lane_id] = entry
    note = f"{len(merged)} job descriptions from {len(files)} file(s)" if files else "no description file yet"
    if bad:
        note += f"; skipped unreadable: {', '.join(bad)}"
    return merged, {"name": "job descriptions", "newest_record_at": None, "covers_from": None, "note": note}


# ── loading (read-only) ───────────────────────────────────────────────────────────────────────────────────────────

def _read_json(path: Path, limit=8 * 1024 * 1024):
    try:
        with path.open("rb") as stream:
            raw = stream.read(limit + 1)
        doc = json.loads(raw) if len(raw) <= limit else None
        return doc if isinstance(doc, dict) else None
    except (OSError, ValueError):
        return None


def read_ledger(path: Path, now: datetime) -> dict:
    """Newest runs per lane plus retries, dead letters and breakers; ``mode=ro`` so a missing ledger is never created."""
    out = {"ledger_runs": [], "dead_letters": [], "breakers": [], "last_live_success": {}, "ledger_since": None}
    if not path.is_file():
        out["gap"] = "the n8n run ledger is absent"
        return out
    since = (now - timedelta(days=LEDGER_DAYS)).isoformat()
    fix_since = (now - timedelta(days=FIX_DAYS)).isoformat()
    try:
        conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=2)
        conn.row_factory = sqlite3.Row
        try:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(runs)")}
            opt = lambda c: f'"{c}"' if c in cols else f"NULL AS {c}"
            receipt = ("receipt_json -> '$.attempt_states' AS attempt_states, receipt_json ->> '$.reason' AS reason"
                       if "receipt_json" in cols else "NULL AS attempt_states, NULL AS reason")
            base = (f"run_id, lane_id, mode, state, requested_by, requested_at, started_at, finished_at, exit_code, "
                    f"duration_s, {opt('attempt')}, {opt('parent_run_id')}, {opt('slot_key')}, {receipt}")
            rows = conn.execute(
                f"SELECT * FROM (SELECT {base}, row_number() OVER (PARTITION BY lane_id ORDER BY requested_at DESC) AS rn "
                f"FROM runs WHERE requested_at >= ?) WHERE rn <= ? "
                + ("OR attempt > 1" if "attempt" in cols else ""), (since, 3 * RUN_LIMIT)).fetchall()
            out["ledger_runs"] = [dict(r) for r in rows]
            oldest = conn.execute("SELECT min(requested_at) FROM runs WHERE requested_at >= ?", (since,)).fetchone()[0]
            out["ledger_since"] = max(_at(oldest), now - timedelta(days=LEDGER_DAYS)) if _at(oldest) else None
            out["last_live_success"] = dict(conn.execute(
                "SELECT lane_id, max(finished_at) FROM runs WHERE mode = 'live' AND state = 'RUN_DONE' AND exit_code = 0 "
                "GROUP BY lane_id").fetchall())
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            if "dead_letters" in tables:
                out["dead_letters"] = [dict(r) for r in conn.execute(
                    "SELECT lane_id, mode, attempts, last_run_id, last_state, last_reason, verdict, dead_at, released_at, "
                    "released_by, release_note FROM dead_letters WHERE dead_at >= ? OR released_at >= ?", (fix_since, fix_since))]
            if "breakers" in tables:
                out["breakers"] = [dict(r) for r in conn.execute(
                    "SELECT lane_id, opened_at, consecutive, released_at, released_by FROM breakers")]
            out["newest"] = conn.execute("SELECT max(requested_at) FROM runs").fetchone()[0]
        finally:
            conn.close()
    except (sqlite3.Error, OSError, ValueError) as exc:
        out["gap"] = f"the n8n run ledger could not be read ({type(exc).__name__})"
    return out


def read_journal(path: Path) -> dict:
    """The tail of the wrapper journal; only run-shaped business lines are parsed (prefilter on bytes)."""
    out = {"journal_events": [], "journal_since": None}
    try:
        with path.open("rb") as stream:
            stream.seek(0, os.SEEK_END)
            size = stream.tell()
            start = max(0, size - JOURNAL_TAIL_BYTES)
            stream.seek(start)
            raw = stream.read(JOURNAL_TAIL_BYTES)
    except OSError:
        out["gap"] = "the cron wrapper journal could not be read"
        return out
    lines = raw.split(b"\n")
    if start:
        lines = lines[1:]
    bad = 0
    for line in lines:
        if b'"event_type"' not in line or b".dryrun" in line or b'"mode":"dry_run"' in line or b'"mode": "dry_run"' in line:
            continue
        if not any(t in line for t in (b'"started"', b'"completed"', b'"lock_skip"', b'"refused"')):
            continue
        try:
            event = json.loads(line)
        except ValueError:
            bad += 1
            continue
        if isinstance(event, dict):
            event.pop("command", None) if event.get("mode") else None
            out["journal_events"].append(event)
    times = [t for t in (_at(e.get("ts")) for e in out["journal_events"][:50]) if t]
    out["journal_since"] = min(times) if times and start else (min(times) if times else None)
    out["newest"] = out["journal_events"][-1].get("ts") if out["journal_events"] else None
    if bad:
        out["note"] = f"{bad} journal line(s) could not be read"
    return out


UNIT_RUNS_TAIL_BYTES = 8 * 1024 * 1024


def read_unit_runs(path: Path) -> dict:
    """The tail of ``data/runtime/unit_runs.jsonl`` (UnitRun@v1, written by the unit-run-snapshot lane)."""
    out = {"unit_runs": [], "newest": None}
    try:
        with path.open("rb") as stream:
            stream.seek(0, os.SEEK_END)
            size = stream.tell()
            start = max(0, size - UNIT_RUNS_TAIL_BYTES)
            stream.seek(start)
            raw = stream.read(UNIT_RUNS_TAIL_BYTES)
    except FileNotFoundError:
        return out
    except OSError:
        out["gap"] = "the systemd unit run snapshot could not be read"
        return out
    lines = raw.split(b"\n")[1:] if start else raw.split(b"\n")
    for line in lines:
        try:
            row = json.loads(line) if line.strip() else None
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("schema") == "UnitRun@v1" and row.get("lane_id"):
            out["unit_runs"].append(row)
    out["newest"] = out["unit_runs"][-1].get("observed_at") if out["unit_runs"] else None
    return out


def unit_runs_by_lane(rows: list[dict]) -> dict[str, list[dict]]:
    """UnitRun@v1 rows -> page runs per lane (one per InvocationID)."""
    out: dict[str, list[dict]] = defaultdict(list)
    seen = set()
    for row in rows:
        start, end = _at(row.get("started_at")), _at(row.get("finished_at"))
        key = (row["lane_id"], row.get("invocation_id") or row.get("started_at"))
        if start is None or end is None or key in seen:
            continue
        seen.add(key)
        code = row.get("exit_status")
        result = "succeeded" if row.get("succeeded") else "timed_out" if row.get("result") == "timeout" else "failed"
        out[row["lane_id"]].append({
            "run_id": row.get("invocation_id"), "source": "systemd unit snapshot", "mode": "live", "result": result,
            "requested_at": None, "started_at": _iso(start), "finished_at": _iso(end),
            "exit_code": code if type(code) is int else None, "duration_s": round((end - start).total_seconds(), 3),
            "attempt": None, "retry_of": None, "requested_by": "systemd timer", "inline_attempts": None,
            "reason": None if row.get("succeeded") else _text(f"systemd result {row.get('result')}"), "_start": start})
    for runs in out.values():
        runs.sort(key=lambda r: r["_start"])
    return out


def read_receipts(registry: dict, root: Path) -> tuple[dict, dict]:
    """Declared JSON receipts (last run) and declared output files' write times, inside data/ and logs/ only."""
    receipts, outputs = {}, {}
    base = root.resolve()
    allowed = (base / "data", base / "logs")
    for lane in registry.get("lanes") or []:
        if lane.get("state") != "ACTIVE":
            continue
        signal = lane.get("output_signal") or {}
        declared = str(signal.get("path") or "")
        if signal.get("kind") not in {"file_mtime", "json_key"} or not declared:
            continue
        path = (base / declared).resolve()
        if not any(path.is_relative_to(a) for a in allowed):
            continue
        lane_id = W.identity(lane)
        try:
            outputs[lane_id] = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        except OSError:
            continue
        if declared.endswith(".json"):
            doc = _read_json(path, 512 * 1024)
            run = receipt_run(doc, signal.get("key") if signal.get("kind") == "json_key" else None) if doc else None
            if run:
                receipts[lane_id] = run
    return receipts, outputs


def _load(root: Path, registry_path: Path, now: datetime, descriptions_dir: Path | None = None,
          categories_path: Path | None = None) -> dict:
    from scripts.cron_outage_watchdog import bind_components
    from scripts.market_session import is_trading_day
    registry = _read_json(registry_path, 32 * 1024 * 1024) or {}
    registry = bind_components(registry, _read_json(ROOT / "config/cron_outage_watchdog.json") or {})
    gaps, sources = [], []
    ledger = read_ledger(root / "data/governance/n8n_coordination_ledger.sqlite", now)
    journal = read_journal(root / "logs/safe_flock_events.jsonl")
    receipts, outputs = read_receipts(registry, root)
    units = read_unit_runs(root / "data/runtime/unit_runs.jsonl")
    for name, part in (("n8n run ledger", ledger), ("cron wrapper journal", journal), ("systemd unit snapshot", units)):
        if part.get("gap"):
            gaps.append(part["gap"])
        sources.append({"name": name, "newest_record_at": part.get("newest"),
                        "covers_from": _iso(part.get("ledger_since") or part.get("journal_since")), "note": part.get("note")})
    incidents_doc = _read_json(root / "data/coordination/incidents/index.json", 32 * 1024 * 1024)
    incidents = [r for r in (incidents_doc or {}).get("incidents") or [] if isinstance(r, dict)]
    if incidents_doc is None:
        gaps.append("the incident ledger could not be read")
    sources.append({"name": "incident ledger", "newest_record_at": (incidents_doc or {}).get("generated_at"), "covers_from": None, "note": None})
    fixer = _read_json(root / "data/runtime/self_heal_fixer_state.json") or {}
    fixer_last = _read_json(root / "data/runtime/self_heal_fixer_last.json") or {}
    sources.append({"name": "self-heal fixer", "newest_record_at": fixer_last.get("finished_at"), "covers_from": None,
                    "note": (fixer_last.get("arming") or {}).get("why") and f"not armed: {fixer_last['arming']['why']}"})
    diagnosis = _read_json(root / "data/runtime/n8n_failure_diagnosis_state.json", 32 * 1024 * 1024)
    if diagnosis is None:
        gaps.append("the n8n failure diagnosis state could not be read")
    diagnosis = diagnosis or {}
    episodes = [e for e in (diagnosis.get("episodes") or {}).values() if isinstance(e, dict)]
    actions = [d for d in (diagnosis.get("diagnosed") or {}).values() if isinstance(d, dict) and d.get("action_id")]
    diag_last = _read_json(root / "data/runtime/n8n_failure_diagnosis_last.json") or {}
    sources.append({"name": "n8n failure diagnosis", "newest_record_at": diag_last.get("finished_at") or diag_last.get("as_of"),
                    "covers_from": None, "note": None})
    cron_heal = _read_json(root / "data/runtime/cron_self_heal_state.json") or {}
    sources.append({"name": "lane receipts and output files", "newest_record_at": _iso(max(outputs.values(), default=None)),
                    "covers_from": None, "note": f"{len(receipts)} receipts, {len(outputs)} output files"})
    inputs = {**{k: ledger[k] for k in ("ledger_runs", "dead_letters", "breakers", "last_live_success", "ledger_since")},
              "journal_events": journal["journal_events"], "journal_since": journal["journal_since"],
              "unit_runs": units["unit_runs"],
              "receipts": receipts, "output_times": outputs, "incidents": incidents,
              "fixer_jobs": [j for j in (fixer.get("jobs") or {}).values() if isinstance(j, dict)],
              "episodes": episodes, "actions": actions, "cron_heal": cron_heal, "sources": sources, "gaps": gaps}
    descriptions, described_source = read_descriptions(descriptions_dir or DESCRIPTIONS_DIR)
    sources.append(described_source)
    categories, categories_gap = read_categories(categories_path or CATEGORIES_PATH)
    if categories_gap:
        gaps.append(categories_gap)
    inputs.update(descriptions=descriptions, categories=categories)
    if not registry.get("lanes"):
        gaps.append("the job list could not be read")
    result = build(registry, inputs, now=now, trading_day=is_trading_day)
    from scripts.lib.run_quality import attach  # per-row run QUALITY grade (RUNQ 2026-11-06); read-only
    return attach(result, registry, root, now=now)


# ── API with a stale-while-revalidate cache ───────────────────────────────────────────────────────────────────────
_CACHE: dict = {}
_LOCK = threading.Lock()
_REFRESHING: set = set()

_ATTENTION = {"failed", "missed", "late", "not_measured"}


def _refresh(key, root, registry, extra):
    try:
        result = _load(root, registry, datetime.now(timezone.utc), **extra)
        with _LOCK:
            _CACHE[key] = (time.monotonic(), result)
    finally:
        with _LOCK:
            _REFRESHING.discard(key)


def snapshot(*, state_root=None, registry_path=None, now=None, descriptions_dir=None, categories_path=None) -> dict:
    root = Path(state_root or os.environ.get("TRADEAI_STATE_ROOT") or Path.home() / "trade-ai-releases/persistent-state")
    registry = Path(registry_path or ROOT / "config/lane_registry.json")
    extra = {"descriptions_dir": Path(descriptions_dir) if descriptions_dir else None,
             "categories_path": Path(categories_path) if categories_path else None}
    if now is not None:
        return _load(root, registry, now, **extra)
    key = (str(root), str(registry), str(extra["descriptions_dir"]), str(extra["categories_path"]))
    with _LOCK:
        cached = _CACHE.get(key)
        stale = cached is None or time.monotonic() - cached[0] > CACHE_SECONDS
        background = cached is not None and stale and key not in _REFRESHING
        if background:
            _REFRESHING.add(key)
    if cached is None:
        result = _load(root, registry, datetime.now(timezone.utc), **extra)
        with _LOCK:
            _CACHE[key] = (time.monotonic(), result)
        return result
    if background:
        threading.Thread(target=_refresh, args=(key, root, registry, extra), name="jobs-history-refresh", daemon=True).start()
    return cached[1]


def _list_row(row: dict) -> dict:
    keep = ("lane_id", "job", "scheduler", "state", "status", "status_reason", "last_run", "last_success_at",
            "missed_count", "missed_gap", "fix_count", "last_fix", "history_sources", "history_gap",
            "title", "category", "does", "breaks", "owner", "category_fallback", "category_key", "quality")
    out = {k: row.get(k) for k in keep}
    out["cadence"] = {k: row["cadence"][k] for k in ("expressions", "timezone", "every_hours", "market_days_only")}
    out["output_written_at"] = (row.get("output") or {}).get("written_at")
    return out


#: ``?status=`` values. Each matches the summary tile of the same meaning, so a tapped tile's count is the list's total.
STATUS_FILTERS = {
    "failed": lambda r: r["status"] == "failed",
    "missed": lambda r: r["state"] == "ACTIVE" and bool(r["missed_count"]),  # = summary.with_missed
    "late": lambda r: r["status"] == "late",
    "ok": lambda r: r["status"] == "ok",
    "ok_unverified": lambda r: r["status"] == "ok_unverified",
    "running": lambda r: r["status"] == "running",
    "not_measured": lambda r: r["status"] == "not_measured",
    "paused": lambda r: r["status"] == "paused",
    "retired": lambda r: r["status"] == "retired",
    "never_scheduled": lambda r: r["status"] == "never_scheduled",
    "fixed": lambda r: bool(r["fix_count"]),  # = summary.fixed_14d
}
#: ``?quality=`` values: the run-quality grades of scripts/lib/run_quality.py (= summary.quality_counts keys).
QUALITY_GRADES = ("GOOD", "DEGRADED", "EMPTY", "FAILED", "NOT_LIVE", "UNPROVEN")
_ORDER = {"failed": 0, "missed": 1, "late": 2, "running": 3, "not_measured": 4, "ok_unverified": 5, "ok": 6}


def get_jobs_history(query=None, **kwargs) -> dict:
    query = query or {}
    result = snapshot(**kwargs)
    rows = result["rows"]
    if query.get("job"):
        match = [r for r in rows if r["lane_id"] == query["job"]]
        return {**{k: v for k, v in result.items() if k != "rows"}, "row": match[0] if match else None}
    scope = query.get("filter", "attention")
    if scope not in {"attention", "all", "fixed", "n8n", "cron", "systemd", "other"}:
        raise ValueError("unknown filter")
    status = str(query.get("status") or "").strip() or None
    if status and status not in STATUS_FILTERS:
        raise ValueError("unknown status")
    category = str(query.get("category") or "").strip() or None
    if category and category not in {c["key"] for c in result.get("categories") or []} | {r.get("category_key") for r in rows}:
        raise ValueError("unknown category")
    quality = str(query.get("quality") or "").strip().upper() or None
    if quality and quality not in QUALITY_GRADES:
        raise ValueError("unknown quality")
    if scope == "attention":
        rows = [r for r in rows if r["status"] in _ATTENTION or (r["missed_count"] or 0) > 0]
    elif scope == "fixed":
        rows = [r for r in rows if r["fix_count"]]
    elif scope in {"n8n", "cron", "systemd"}:
        rows = [r for r in rows if r["scheduler"] == scope]
    elif scope == "other":
        rows = [r for r in rows if r["scheduler"] not in {"n8n", "cron", "systemd"}]
    if status:
        rows = [r for r in rows if STATUS_FILTERS[status](r)]
    if category:
        rows = [r for r in rows if r.get("category_key") == category]
    if quality:
        rows = [r for r in rows if (r.get("quality") or {}).get("grade") == quality]
    text = str(query.get("q") or "").strip().lower()
    if text:
        rows = [r for r in rows if any(text in str(r.get(k) or "").lower() for k in ("lane_id", "job", "title", "does"))]
    rows = sorted(rows, key=lambda r: (_ORDER.get(r["status"], 7), -(r["missed_count"] or 0), (r.get("title") or r["job"]).lower()))
    try:
        offset = max(0, int(query.get("offset", 0)))
        limit = max(1, min(200, int(query.get("limit", 50))))
    except (TypeError, ValueError):
        offset, limit = 0, 50
    return {**{k: v for k, v in result.items() if k != "rows"}, "rows": [_list_row(r) for r in rows[offset:offset + limit]],
            "total": len(rows), "offset": offset, "limit": limit, "has_more": offset + limit < len(rows), "filter": scope,
            "status": status, "category": category, "quality": quality}


#: How the catalog buckets a job's status (the card's "3 failed · 40 ok · 12 not measured").
_MIX = {"failed": "failed", "missed": "missed", "late": "late", "running": "running", "ok": "ok",
        "ok_unverified": "ok_unverified", "not_measured": "not_measured", "paused": "inactive", "retired": "inactive",
        "never_scheduled": "inactive"}


def get_jobs_catalog(query=None, **kwargs) -> dict:
    """GET /api/v2/jobs-catalog: every category in config order with its job count, how many are described and a
    status mix. Computed from the same cached projection as jobs-history (no extra store read)."""
    result = snapshot(**kwargs)
    rows = result["rows"]
    cats = [dict(c) for c in result.get("categories") or []]
    known = {c["key"] for c in cats}
    for key in sorted({r["category_key"] for r in rows} - known):  # a fallback key the list lacks still shows
        cats.append({"key": key, "label": key.replace("_", " ").capitalize(), "blurb": ""})
    out = []
    for c in cats:
        members = [r for r in rows if r["category_key"] == c["key"]]
        mix = {k: 0 for k in ("failed", "missed", "late", "running", "ok", "ok_unverified", "not_measured", "inactive")}
        for r in members:
            mix[_MIX.get(r["status"], "not_measured")] += 1
        out.append({**c, "jobs": len(members), "described": sum(1 for r in members if r["does"]),
                    "with_missed": sum(1 for r in members if STATUS_FILTERS["missed"](r)),
                    "fixed_14d": sum(1 for r in members if r["fix_count"]), "status_mix": mix})
    return {"schema": "JobCatalog@v1", "authority": AUTHORITY, "computed_at": result["computed_at"],
            "jobs": len(rows), "described": result.get("described", 0), "categories": out,
            "sources": result.get("sources") or [], "gaps": result.get("gaps") or [],
            "note": "Categories come from the job descriptions; a job without one is grouped by its registry owner."}
