"""Per-lane scheduler health: late / missed counts and the Home "Schedulers" row (LQ-20261107-2148, Home v010).

Spec: coordinator ``lead/scratch/HOME-BACKEND-SPEC-20261111.md`` section LQ-2148. One row per ACTIVE registry lane
with a wall schedule, written to ``lane_health_current`` by the n8n lane ``lane-health-snapshot``. Pure compute over
stores that already exist; every store is read read-only:

* ``config/lane_registry.json`` — the expected schedule (``cron_outage_watchdog.schedules`` +
  ``jobs_history.expected_slots``: DST via ``cron_schedule.fires_between``, the market-day gate, llm-priority
  deferral) and ``active_days`` (ET weekday numbers);
* the n8n coordination ledger, table ``runs`` (sqlite ``mode=ro`` + ``PRAGMA query_only``) — every dispatcher run in
  the window. ``jobs_history.read_ledger`` keeps only the newest 30 per lane; a 5-minute lane has 288 slots a day;
* each lane's ``output_signal`` through ``lane_registry.observe_signal`` (the one reader; not re-implemented) and its
  own receipt ``data/runtime/<lane>_last.json`` ``ok_at``.

Honesty rules (Engineering Constitution v1.5; Home v010 REPORT section 7; spec A4):
* REGISTRATION IS NOT EXECUTION. An n8n lane's expected slot with no ledger run is MISSED, even for a lane that has
  never run (``jobs_history.lane_history`` reports that lane's missed count as ``None``; this module does not). The
  ledger records every dispatch, so its coverage is global, not per lane.
* UNKNOWN NEVER READS AS OK. Cron and systemd lanes have no per-slot run ledger: their late and missed counts are
  ``None`` and their state is NOT_MEASURED (or STALE when their output signal is provably old) — never OK, never 0.
  An unreadable ledger or schedule is UNKNOWN with the cause named.
* A dry run never satisfies a live slot (QA-GOLDEN-RULES E7): a lane dispatched ``live`` is judged on live runs.
* Every row carries ``measured_at`` and its window, and every value its age, so a reader can show age + threshold.

AUTHORITY: READ_ONLY_ADVISORY. MBI_BEHAVIOR = 0 (no broker, no order, no sizing, no live flag).
"""
from __future__ import annotations

import bisect
from collections import Counter
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any, Callable, Iterable, Mapping
from zoneinfo import ZoneInfo

from scripts.lib import cron_outage_watchdog as W
from scripts.lib import jobs_history as JH

LANE_ID = "lane-health-snapshot"
SCHEMA = "LaneHealthSnapshot@v1"
ROW_SCHEMA = "LaneHealthRow@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config/lane_health.json"
TABLE = "lane_health_current"
#: Row states, worst first (the table's CHECK constraint carries the same six words).
STATES = ("UNKNOWN", "FAILING", "LATE", "STALE", "NOT_MEASURED", "OK")
ROLLUP_STATES = ("OK", "WARN", "UNKNOWN")
ET = ZoneInfo("America/New_York")

DEFAULTS: dict[str, Any] = {
    "window_hours": 24,
    "lookback_days": 8,
    "late_grace_minutes": 10,
    "stale_after_slots": 3,
    "warn_states": ["LATE", "STALE", "FAILING"],
    "unknown_states": ["UNKNOWN", "NOT_MEASURED"],
    "business_critical_value_classes": [],
    "stale_after_minutes": 30,
    "owner": "platform",
    "max_listed_slots": 5,
    "max_listed_lanes": 10,
}

#: Where each scheduler kind's runs are recorded (named on every row as its source of record).
SOURCE_OF_RECORD = {"n8n": "n8n run ledger", "cron": "output signal only (cron has no per-run ledger)",
                    "systemd": "output signal only (systemd has no per-run ledger)"}

CAUSE_TEXT = {
    "on_schedule": "All {expected} judged slot(s) ran within {grace} min of their time",
    "never_dispatched": "Registered, but the n8n run ledger has no run of it: {missed} expected slot(s) missed",
    "missed_slot": "{missed} of {expected} expected slot(s) have no run in the n8n run ledger",
    "late_start": "{late} of {expected} slot(s) started more than {grace} min after their time",
    "last_slot_missed": "Its last expected slot ({last}) has no run in the n8n run ledger",
    "last_slot_failed": "Its last expected slot ({last}) ran and failed",
    "output_stale": "Its output signal is older than its last {n} expected slots",
    "schedule_unreadable": "The registry schedule could not be read",
    "ledger_unreadable": "The n8n run ledger could not be read: {gap}",
    "no_run_ledger": "Lateness is not measured: {kind} lanes have no per-run ledger (A4); output signal {signal}",
    "no_slot_judged": "No expected slot has been due long enough to judge",
}


def load_config(path: Path | None = None) -> dict:
    """The policy file merged over DEFAULTS; an unreadable file falls back to DEFAULTS and says so."""
    target = Path(path or CONFIG_PATH)
    try:
        doc = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {**DEFAULTS, "_config_gap": f"{target.name} unreadable ({type(exc).__name__}); defaults used"}
    policy = doc.get("policy") if isinstance(doc, dict) else None
    return {**DEFAULTS, **(policy if isinstance(policy, dict) else {})}


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds") if value else None


def _cause(code: str, **kw) -> str:
    try:
        return CAUSE_TEXT[code].format(**kw)
    except (KeyError, IndexError):
        return CAUSE_TEXT.get(code, code)


# ── the run ledger (read-only) ────────────────────────────────────────────────────────────────────────────────────

def read_ledger_window(path: Path, since: datetime) -> dict:
    """Every ledger run requested since ``since``.

    ``mode=ro`` (a missing ledger is never created) and ``PRAGMA query_only``. ``covered_from`` is the instant from
    which a lane with NO row provably was not dispatched: ``since`` when the ledger holds an older row, else its oldest
    row. ``readable`` False is a gap ("UNKNOWN"), never "no runs".
    """
    out: dict[str, Any] = {"readable": False, "runs": [], "covered_from": None, "newest": None, "gap": None}
    if not Path(path).is_file():
        out["gap"] = "the ledger file is absent"
        return out
    try:
        conn = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True, timeout=5)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA query_only = ON")
            cols = {r[1] for r in conn.execute("PRAGMA table_info(runs)")}
            if not {"lane_id", "mode", "state", "requested_at", "started_at"} <= cols:
                out["gap"] = "the ledger has no runs table of the expected shape"
                return out
            opt = lambda c: f'"{c}"' if c in cols else f"NULL AS {c}"  # noqa: E731
            rows = conn.execute(
                f"SELECT {opt('run_id')}, lane_id, mode, state, requested_at, started_at, {opt('finished_at')}, "
                f"{opt('exit_code')} FROM runs WHERE requested_at >= ? ORDER BY requested_at",
                (since.isoformat(),)).fetchall()
            older = conn.execute("SELECT 1 FROM runs WHERE requested_at < ? LIMIT 1", (since.isoformat(),)).fetchone()
            out["newest"] = conn.execute("SELECT max(requested_at) FROM runs").fetchone()[0]
        finally:
            conn.close()
    except (sqlite3.Error, OSError, ValueError) as exc:
        out["gap"] = f"{type(exc).__name__}: {str(exc)[:120]}"
        return out
    out["runs"] = [dict(r) for r in rows]
    out["readable"] = True
    oldest = JH._at(out["runs"][0]["requested_at"]) if out["runs"] else None
    out["covered_from"] = since if older else (oldest or since)
    return out


# ── per-lane judgement ────────────────────────────────────────────────────────────────────────────────────────────

def expected_mode(lane: Mapping[str, Any]) -> str:
    """``live`` (only live runs satisfy a slot) or ``dry_run`` (a shadow lane: any run does)."""
    mode = str((lane.get("dispatch") or {}).get("mode") or "live")
    return "dry_run" if mode == "dry_run" else "live"


#: Ledger results that are a run of the slot. A lock skip (another run held the lock) and an in-flight row are not.
_COUNTED = {"succeeded", "failed", "timed_out", "refused", "unknown"}


def judge(slots: list[dict], runs: list[dict], *, now: datetime, covered_from: datetime | None) -> list[dict]:
    """``jobs_history.judge_slots`` semantics — the first counted run starting in [slot - EARLY_TOLERANCE,
    window_end) — with a bisect over sorted starts so a 1-minute lane's 1,440 slots stay linear.

    A run is matched on ``_match`` when it has one (a ledger run's ``requested_at``: the dispatch of the slot) and
    on ``_start`` otherwise; lateness is always ``_start`` - slot. Matching on the start alone counted a slot whose
    run waited in the executor queue past the next slot as MISSED (measured 2026-11-11: momentum-cache-reconcile
    19:00 UTC slot, requested 19:00:13, started 19:05:53)."""
    key = lambda r: r.get("_match") or r.get("_start")  # noqa: E731
    timed = sorted((r for r in runs if r.get("_start") and r.get("result") in _COUNTED), key=key)
    starts = [key(r) for r in timed]
    out = []
    for slot in slots:
        lo, hi = slot["at"] - JH.EARLY_TOLERANCE, slot["window_end"]
        i = bisect.bisect_left(starts, lo)
        match = timed[i] if i < len(timed) and starts[i] < hi else None
        base = {"slot_at": slot["at"], "run_id": None, "started_at": None, "late_s": None}
        if match:
            status = "failed" if match.get("result") in JH._FAILED else "done"
            out.append({**base, "status": status, "run_id": match.get("run_id"), "started_at": match["_start"],
                        "late_s": max(0.0, (match["_start"] - slot["at"]).total_seconds())})
        elif covered_from is None or slot["at"] < covered_from:
            out.append({**base, "status": "not_measured"})
        elif now < slot["judge_at"]:
            out.append({**base, "status": "pending"})
        else:
            out.append({**base, "status": "missed"})
    return out


def _active_day(lane: Mapping[str, Any], at: datetime) -> bool:
    """Is ``at`` a day this lane is expected to run: an ``active_days`` ET weekday, on or after its ``state_since``
    (a slot before the lane became ACTIVE was never owed)."""
    local = at.astimezone(ET)
    days = lane.get("active_days")
    if isinstance(days, (list, tuple)) and days and local.weekday() not in days:
        return False
    since = str(lane.get("state_since") or "")[:10]
    return not (len(since) == 10 and local.date().isoformat() < since)


def lane_slots(lane: Mapping[str, Any], cadence: dict, *, now: datetime, trading_day: Callable, guard_window,
               policy: Mapping[str, Any]) -> tuple[list[dict], list[dict]]:
    """(slots in the window, the newest elapsed slots within ``lookback_days`` — up to 64)."""
    window_from = now - timedelta(hours=float(policy["window_hours"]))
    days = max(1.0, float(policy["window_hours"]) / 24.0)
    window = JH.expected_slots(cadence, now, trading_day, days=days, limit=100_000, guard_window=guard_window)
    window = [s for s in window if s["at"] >= window_from and _active_day(lane, s["at"])]
    recent = JH.expected_slots(cadence, now, trading_day, days=float(policy["lookback_days"]), limit=64,
                               guard_window=guard_window)
    recent = [s for s in recent if s["judge_at"] <= now and _active_day(lane, s["at"])]
    return window, recent


def output_signal(lane: Mapping[str, Any], *, state_root: Path, db_query=None) -> dict:
    """``lane_registry.observe_signal`` for the lane's declared signal, plus its own receipt's ``ok_at``."""
    from scripts.lib.lane_registry import observe_signal
    sig = dict(lane.get("output_signal") or {})
    kind = str(sig.get("kind") or "none")
    try:
        seen = observe_signal(sig, root=state_root, db_query=db_query) if kind != "systemd_result" else \
            {"last_output_at": None, "readable": False, "detail": "systemd_result is not read by this lane"}
    except Exception as exc:  # noqa: BLE001 -- observe_signal promises not to raise; a reader never fails the lane
        seen = {"last_output_at": None, "readable": False, "detail": type(exc).__name__}
    receipt = JH._read_json(Path(state_root) / "data/runtime" / f"{W.identity(lane)}_last.json", 512 * 1024) or {}
    return {"kind": kind, "at": seen.get("last_output_at"), "readable": bool(seen.get("readable")),
            "ok_receipt_at": JH._at(receipt.get("ok_at"))}


def _stale(signal: Mapping[str, Any], recent: list[dict], n: int) -> bool | None:
    """True when the output signal is older than the lane's n-th newest expected slot (session-aware: the market-day
    gate and active_days already shaped ``recent``); None when it cannot be judged."""
    if not signal.get("readable") or signal.get("kind") in {"none", None} or len(recent) < n:
        return None
    anchor = recent[-n]["at"]
    return signal.get("at") is None or signal["at"] < anchor


def born_covered(lane: Mapping[str, Any], covered: datetime | None, ledger_runs: list[dict]) -> datetime | None:
    """``state_since`` is a date, so on the day a lane became ACTIVE the slots before its first dispatch were not owed:
    coverage starts at that first dispatch. A lane with NO dispatch keeps the global coverage, so registration
    without execution still reads MISSED."""
    since = str(lane.get("state_since") or "")[:10]
    first = min((r.get("_match") or r["_start"] for r in ledger_runs if r.get("_start")), default=None)
    if covered is None or first is None or first.astimezone(ET).date().isoformat() != since:
        return covered
    return max(covered, first - JH.EARLY_TOLERANCE)


def lane_row(lane: Mapping[str, Any], *, now: datetime, trading_day: Callable, guard_window,
             ledger: Mapping[str, Any], ledger_runs: list[dict], signal: Mapping[str, Any],
             policy: Mapping[str, Any], run_id: str) -> dict | None:
    """One ACTIVE lane's ``lane_health_current`` row, or None (not ACTIVE, or no recurring wall schedule)."""
    if lane.get("state") != "ACTIVE":
        return None
    expressions, _tz, issue = W.schedules(dict(lane))
    if issue in {"recurring_schedule_not_measured", "reboot_has_no_recurring_wall_schedule"}:
        return None
    kind = str((lane.get("scheduler") or {}).get("kind") or "unknown")
    grace = float(policy["late_grace_minutes"])
    n_stale = int(policy["stale_after_slots"])
    cadence_h = lane.get("expected_cadence_hours")
    row: dict[str, Any] = {
        "lane_id": W.identity(lane), "scheduler_kind": kind,
        "stage": (lane.get("scheduler") or {}).get("stage"), "owner": str(lane.get("owner") or "UNREGISTERED"),
        "value_class": lane.get("value_class"), "schedule_expr": " | ".join(expressions) or None,
        "expected_cadence_h": float(cadence_h) if isinstance(cadence_h, (int, float)) else None,
        "expected_slots_24h": None, "done_slots_24h": None, "late_count_24h": None, "missed_count_24h": None,
        "failed_count_24h": None, "pending_slots": 0,
        "last_expected_at": None, "last_run_done_at": None, "last_ok_receipt_at": _iso(signal.get("ok_receipt_at")),
        "output_signal_kind": signal.get("kind"), "output_signal_at": _iso(signal.get("at")),
        "output_age_s": int((now - signal["at"]).total_seconds()) if signal.get("at") else None,
        "state": "UNKNOWN", "cause_code": None, "cause": None,
        "source_of_record": SOURCE_OF_RECORD.get(kind, "output signal only"),
        "expected_mode": expected_mode(lane) if kind == "n8n" else "live",
        "measured_at": _iso(now), "run_id": run_id, "missed_slots": [], "late_slots": [],
    }
    cadence = JH.cadence_of(dict(lane))
    if not cadence["expressions"]:
        row.update(cause_code="schedule_unreadable", cause=_cause("schedule_unreadable"))
        return row
    window, recent = lane_slots(lane, cadence, now=now, trading_day=trading_day, guard_window=guard_window,
                                policy=policy)
    row["last_expected_at"] = _iso(recent[-1]["at"]) if recent else None
    stale = _stale(signal, recent, n_stale)
    if kind != "n8n":
        # Spec A4: no per-slot ledger for cron/systemd, so lateness is NOT_MEASURED — never 0, never OK.
        sig_word = ("is older than its last %d expected slots" % n_stale if stale else
                    "is current" if stale is False else "cannot be judged")
        row.update(state="STALE" if stale else "NOT_MEASURED",
                   cause_code="output_stale" if stale else "no_run_ledger",
                   cause=_cause("output_stale", n=n_stale) + " (lateness not measured: no per-run ledger)" if stale
                   else _cause("no_run_ledger", kind=kind, signal=sig_word))
        return row
    if not ledger.get("readable"):
        row.update(cause_code="ledger_unreadable", cause=_cause("ledger_unreadable", gap=ledger.get("gap") or "?"))
        return row
    runs = ledger_runs if row["expected_mode"] == "dry_run" else [r for r in ledger_runs if r.get("mode") != "dry_run"]
    done = [r for r in runs if r.get("result") == "succeeded" and r.get("_start")]
    row["last_run_done_at"] = _iso(max((r["_start"] for r in done), default=None))
    covered = born_covered(lane, ledger.get("covered_from"), ledger_runs)
    judged = judge(window, runs, now=now, covered_from=covered)
    last = judge(recent[-1:], runs, now=now, covered_from=covered) if recent else []
    counts = Counter(s["status"] for s in judged)
    measured = [s for s in judged if s["status"] in {"done", "failed", "missed"}]
    late = [s for s in measured if s["late_s"] is not None and s["late_s"] > grace * 60]
    cap = int(policy["max_listed_slots"])
    row.update(
        expected_slots_24h=len(measured), done_slots_24h=counts["done"], late_count_24h=len(late),
        missed_count_24h=counts["missed"], failed_count_24h=counts["failed"], pending_slots=counts["pending"],
        missed_slots=[_iso(s["slot_at"]) for s in judged if s["status"] == "missed"][-cap:],
        late_slots=[{"slot_at": _iso(s["slot_at"]), "started_at": _iso(s["started_at"]),
                     "late_s": round(s["late_s"], 1)} for s in late][-cap:],
    )
    last_status = last[0]["status"] if last else None
    fmt = dict(expected=len(measured), missed=counts["missed"], late=len(late), grace=f"{grace:g}", n=n_stale,
               last=_iso(recent[-1]["at"]) if recent else "?")
    if last_status == "failed":
        row.update(state="FAILING", cause_code="last_slot_failed", cause=_cause("last_slot_failed", **fmt))
    elif counts["missed"] and not ledger_runs:
        row.update(state="LATE", cause_code="never_dispatched", cause=_cause("never_dispatched", **fmt))
    elif counts["missed"]:
        row.update(state="LATE", cause_code="missed_slot", cause=_cause("missed_slot", **fmt))
    elif late:
        row.update(state="LATE", cause_code="late_start", cause=_cause("late_start", **fmt))
    elif last_status == "missed":
        row.update(state="LATE", cause_code="never_dispatched" if not ledger_runs else "last_slot_missed",
                   cause=_cause("never_dispatched", **{**fmt, "missed": 1}) if not ledger_runs
                   else _cause("last_slot_missed", **fmt))
    elif not measured and last_status != "done":
        row.update(state="NOT_MEASURED", cause_code="no_slot_judged", cause=_cause("no_slot_judged"))
    elif stale and row["expected_mode"] == "live":
        # a shadow (dry-run) lane writes no output by design, so only a live lane can be STALE
        row.update(state="STALE", cause_code="output_stale", cause=_cause("output_stale", **fmt))
    else:
        row.update(state="OK", cause_code="on_schedule",
                   cause=_cause("on_schedule", **{**fmt, "expected": len(measured) or 1}))
    return row


# ── the whole snapshot ────────────────────────────────────────────────────────────────────────────────────────────

def build(registry: Mapping[str, Any], *, ledger: Mapping[str, Any], now: datetime, trading_day: Callable,
          signals: Mapping[str, Mapping[str, Any]] | Callable[[Mapping[str, Any]], Mapping[str, Any]],
          guard_window=None, policy: Mapping[str, Any] | None = None, run_id: str = "preview",
          inputs_meta: Iterable[dict] = ()) -> dict:
    """Per-lane rows plus the Home Schedulers rollup. ``now`` must be aware. ``signals`` maps lane_id → output
    signal (as ``output_signal`` returns), or is a callable taking the lane row."""
    if now.tzinfo is None:
        raise ValueError("lane health requires an aware clock")
    policy = {**DEFAULTS, **(policy or {})}
    by_lane: dict[str, list[dict]] = {}
    for raw in ledger.get("runs") or []:
        run = JH.ledger_run(raw)
        run["_match"] = JH._at(raw.get("requested_at")) or run.get("_start")
        by_lane.setdefault(str(raw.get("lane_id")), []).append(run)
    lanes = [lane for lane in (registry.get("lanes") or []) if isinstance(lane, dict)]
    rows, states, unscheduled = [], Counter(), 0
    for lane in lanes:
        states[str(lane.get("state") or "UNKNOWN")] += 1
        if lane.get("state") != "ACTIVE":
            continue
        lane_id = W.identity(lane)
        sig = signals(lane) if callable(signals) else (signals.get(lane_id) or {})
        row = lane_row(lane, now=now, trading_day=trading_day, guard_window=guard_window, ledger=ledger,
                       ledger_runs=by_lane.get(lane_id, []), signal=sig, policy=policy, run_id=run_id)
        if row is None:
            unscheduled += 1
            continue
        rows.append(row)
    rows.sort(key=lambda r: (STATES.index(r["state"]), -(r["missed_count_24h"] or 0), r["lane_id"]))
    return {
        "schema": SCHEMA, "authority": AUTHORITY, "lane_id": LANE_ID, "run_id": run_id, "measured_at": _iso(now),
        "stale_after_s": int(float(policy["stale_after_minutes"]) * 60),
        "policy": {k: policy[k] for k in DEFAULTS},
        "schedulers": rollup(rows, registry_ok=bool(lanes), ledger=ledger, policy=policy),
        "registry_states": dict(sorted(states.items())),
        "lanes_active_unscheduled": unscheduled,
        "inputs": list(inputs_meta),
        "lanes": rows,
    }


def rollup(rows: list[dict], *, registry_ok: bool, ledger: Mapping[str, Any], policy: Mapping[str, Any]) -> dict:
    """The Home Schedulers row (Home v010: WARN never blocks trading). An unreadable registry or ledger is UNKNOWN
    outright; else any lane in ``warn_states`` (limited to ``business_critical_value_classes`` when that list is
    set) is WARN; else any lane in ``unknown_states`` is UNKNOWN; else OK. Counts are None when unknowable."""
    policy = {**DEFAULTS, **policy}
    critical = set(policy["business_critical_value_classes"])
    by = Counter(r["state"] for r in rows)
    warn = [r for r in rows if r["state"] in set(policy["warn_states"])
            and (not critical or r.get("value_class") in critical)]
    unknown = [r for r in rows if r["state"] in set(policy["unknown_states"])]
    n8n = [r for r in rows if r["scheduler_kind"] == "n8n"]
    sum_or_none = lambda key: sum(r[key] for r in n8n if r[key] is not None) if ledger.get("readable") else None  # noqa: E731
    out = {
        "status": "OK", "cause_code": None, "cause": None,
        "source": "config/lane_registry.json expected slots vs n8n run ledger (runs); output signals via "
                  "lane_registry.observe_signal",
        "owner": str(policy["owner"]),
        "counts": {s.lower(): by[s] for s in STATES},
        "lanes_judged": len(rows), "lanes_n8n": len(n8n),
        "missed_total_24h": sum_or_none("missed_count_24h"), "late_total_24h": sum_or_none("late_count_24h"),
        "failed_total_24h": sum_or_none("failed_count_24h"),
        "warn_causes": dict(Counter(r["cause_code"] for r in warn)),
        "unknown_causes": dict(Counter(r["cause_code"] for r in unknown)),
        "worst": [{k: r[k] for k in ("lane_id", "owner", "state", "cause", "missed_count_24h", "late_count_24h",
                                     "expected_slots_24h", "last_expected_at")}
                  for r in warn[: int(policy["max_listed_lanes"])]],
    }
    if not registry_ok:
        out.update(status="UNKNOWN", cause_code="registry_unreadable", cause="The lane registry could not be read",
                   counts=None)
    elif not ledger.get("readable"):
        out.update(status="UNKNOWN", cause_code="ledger_unreadable",
                   cause=f"The n8n run ledger could not be read: {ledger.get('gap') or '?'}")
    elif warn:
        first = warn[0]
        out.update(status="WARN", cause_code="lanes_off_schedule",
                   cause=f"{len(warn)} lane(s) LATE/STALE/FAILING ({out['missed_total_24h']} missed, "
                         f"{out['late_total_24h']} late n8n slot(s) in 24 h); worst: {first['lane_id']} — "
                         f"{first['cause']}")
    elif unknown:
        out.update(status="UNKNOWN", cause_code="lanes_not_measured",
                   cause=f"{len(unknown)} of {len(rows)} scheduled lane(s) cannot be judged (mostly cron/systemd: "
                         f"no per-run ledger)")
    else:
        out.update(cause_code="on_schedule", cause=f"All {len(rows)} scheduled lane(s) on schedule")
    return out


# ── the table ─────────────────────────────────────────────────────────────────────────────────────────────────────

COLUMNS = ("lane_id", "scheduler_kind", "stage", "owner", "value_class", "schedule_expr", "expected_cadence_h",
           "expected_slots_24h", "done_slots_24h", "late_count_24h", "missed_count_24h", "failed_count_24h",
           "pending_slots", "last_expected_at", "last_run_done_at", "last_ok_receipt_at", "output_signal_kind",
           "output_signal_at", "output_age_s", "state", "cause_code", "cause", "source_of_record", "detail",
           "measured_at", "run_id")

UPSERT_SQL = (
    f"INSERT INTO {TABLE} ({', '.join(COLUMNS)}) VALUES ({', '.join(['%s'] * len(COLUMNS))}) "
    "ON CONFLICT (lane_id) DO UPDATE SET "
    + ", ".join(f"{c} = EXCLUDED.{c}" for c in COLUMNS if c != "lane_id")
)

#: What a reader (GET /api/v2/home/schedulers, W2-a) selects: only the rows of the newest run. A lane that left
#: ACTIVE keeps its last row (nothing is deleted — AGENTS.md rule 6) but drops out of the read.
READ_CURRENT_SQL = (
    f"SELECT * FROM {TABLE} WHERE run_id = (SELECT run_id FROM {TABLE} ORDER BY measured_at DESC LIMIT 1)"
)


def db_params(row: Mapping[str, Any]) -> tuple:
    detail = {"missed_slots": row.get("missed_slots"), "late_slots": row.get("late_slots"),
              "expected_mode": row.get("expected_mode"), "schema": ROW_SCHEMA}
    return tuple(json.dumps(detail, sort_keys=True) if c == "detail" else row.get(c) for c in COLUMNS)


def table_exists(conn) -> bool:
    cur = conn.cursor()
    cur.execute("SELECT to_regclass(%s)", (TABLE,))
    found = cur.fetchone()
    return bool(found and found[0])


def write(conn, snapshot: Mapping[str, Any]) -> int:
    """Upsert every row in ONE transaction (keyed on lane_id: a re-run of the slot rewrites the same rows). No DDL:
    a missing table is the caller's fail-closed error, never created here."""
    rows = list(snapshot.get("lanes") or [])
    cur = conn.cursor()
    try:
        for row in rows:
            cur.execute(UPSERT_SQL, db_params(row))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return len(rows)


# ── production entry (all reads) ──────────────────────────────────────────────────────────────────────────────────

def compute(*, state_root: Path, registry_path: Path | None = None, now: datetime | None = None,
            policy: Mapping[str, Any] | None = None, run_id: str = "preview", db_query=None) -> dict:
    """Read the stores and build the snapshot."""
    from scripts.cron_outage_watchdog import bind_components, read_crontab_snapshot
    from scripts.lib.llm_priority_guard import load_guard_window
    from scripts.market_session import is_trading_day

    now = now or datetime.now(timezone.utc)
    policy = {**load_config(), **(policy or {})}
    root = Path(state_root)
    registry = JH._read_json(Path(registry_path or ROOT / "config/lane_registry.json"), 32 * 1024 * 1024) or {}
    crontab = read_crontab_snapshot(root)
    registry = bind_components(registry, JH._read_json(ROOT / "config/cron_outage_watchdog.json") or {},
                               crontab_text=crontab)
    since = now - timedelta(days=float(policy["lookback_days"]), hours=6)
    ledger = read_ledger_window(root / "data/governance/n8n_coordination_ledger.sqlite", since)
    window = load_guard_window(crontab_text=crontab)  # the same wiring jobs_history._load uses
    meta = [
        {"name": "lane registry", "readable": bool(registry.get("lanes")), "lanes": len(registry.get("lanes") or [])},
        {"name": "n8n run ledger", "readable": bool(ledger.get("readable")), "newest_record_at": ledger.get("newest"),
         "covers_from": _iso(ledger.get("covered_from")), "runs_read": len(ledger.get("runs") or []),
         "gap": ledger.get("gap")},
    ]
    if policy.get("_config_gap"):
        meta.append({"name": "policy", "readable": False, "gap": policy["_config_gap"]})
    return build(registry, ledger=ledger, now=now, trading_day=is_trading_day, guard_window=window,
                 signals=lambda lane: output_signal(lane, state_root=root, db_query=db_query),
                 policy=policy, run_id=run_id, inputs_meta=meta)
