"""ANCHOR: JOBS_HISTORY_20261106 — per-job run history, missed slots and "fixed" events for /ops/jobs.

Operator 2026-11-06: "We should see all of the jobs, when they ran, when they didn't run, when it had to be fixed".
Hermetic: synthetic lanes, a tmp SQLite ledger and tmp journal/incident files only. No real holdings or lanes.
"""
from datetime import datetime, timedelta, timezone
import json
import sqlite3
import time

import pytest

from scripts.lib import jobs_history as J

NOW = datetime(2026, 11, 4, 15, 7, tzinfo=timezone.utc)  # Wednesday 10:07 ET
WEEKDAY = lambda d: d.weekday() < 5  # noqa: E731


def _z(dt):
    return dt.astimezone(timezone.utc).isoformat()


def n8n_lane(lane_id="synthetic-n8n-lane", cron="*/30 * * * *"):
    return {"lane_id": lane_id, "state": "ACTIVE", "expected_cadence_hours": 0.5,
            "scheduler": {"kind": "n8n"}, "dispatch": {"cron": cron, "tz": "America/New_York"}}


def cron_lane(lane_id="synthetic-cron-lane", expr="0 * * * *", component="synthetic_cron_job"):
    return {"lane_id": lane_id, "state": "ACTIVE", "expected_cadence_hours": 1,
            "scheduler": {"kind": "cron", "expression": expr}, "watchdog_wrapper_component": component}


def systemd_lane(lane_id="synthetic-timer-lane"):
    return {"lane_id": lane_id, "state": "ACTIVE", "expected_cadence_hours": 1, "scheduler": {"kind": "systemd"},
            "output_signal": {"kind": "file_mtime", "path": "data/runtime/synthetic_timer_out.json"}}


def ledger_row(lane, slot, *, state="RUN_DONE", attempt=1, parent=None, exit_code=0, offset_s=5, dur=30, mode="live",
               reason=None, attempt_states=None):
    start = slot + timedelta(seconds=offset_s)
    run_id = f"d:{lane}:{mode}:{slot:%Y%m%dT%H%M}" + (f":a{attempt}" if attempt > 1 else "")
    return {"run_id": run_id, "lane_id": lane, "mode": mode, "state": state, "requested_by": "n8n:workflow:synthetic",
            "requested_at": _z(start), "started_at": _z(start), "finished_at": _z(start + timedelta(seconds=dur)),
            "exit_code": exit_code, "duration_s": dur, "attempt": attempt, "parent_run_id": parent,
            "slot_key": run_id.split(":a")[0], "reason": reason,
            "attempt_states": json.dumps(attempt_states) if attempt_states else None}


def build(lanes, **inputs):
    inputs.setdefault("ledger_since", NOW - timedelta(days=10))
    inputs.setdefault("journal_since", NOW - timedelta(days=10))
    return J.build({"lanes": lanes}, inputs, now=NOW, trading_day=WEEKDAY)


def row_of(result, lane_id):
    return next(r for r in result["rows"] if r["lane_id"] == lane_id)


def every_slot(lane, n=12, step=30):
    last = NOW.replace(minute=0, second=0) if NOW.minute < 30 else NOW.replace(minute=30, second=0)
    return [last - timedelta(minutes=step * i) for i in range(n)]


def test_n8n_failure_then_retry_shows_as_fixed_and_slot_ran():
    lane = "synthetic-n8n-lane"
    slots = every_slot(lane)
    rows = [ledger_row(lane, s) for s in slots[1:]]
    first = ledger_row(lane, slots[0], state="RUN_FAILED", exit_code=1, reason="exit_1 upstream timeout")
    retry = ledger_row(lane, slots[0], attempt=2, parent=first["run_id"], offset_s=95)
    out = build([n8n_lane()], ledger_runs=rows + [first, retry])
    row = row_of(out, lane)
    assert row["status"] == "ok"
    assert row["missed_count"] == 0
    assert row["last_run"]["run_id"].endswith(":a2") and row["last_run"]["result"] == "succeeded"
    assert row["last_success_at"] == retry["finished_at"].replace("+00:00", "Z")
    retries = [f for f in row["fixes"] if f["kind"] == "retry"]
    assert len(retries) == 1 and retries[0]["outcome"] == "succeeded" and "after failed" in retries[0]["detail"]
    assert row["runs"][0]["retry_of"] == first["run_id"]
    assert len(row["runs"]) <= J.RUN_LIMIT
    # Writer times, never the compute clock.
    assert out["computed_at"] == "2026-11-04T15:07:00Z"
    assert all(r["started_at"] != out["computed_at"] for r in row["runs"])


def test_missing_slot_inside_ledger_coverage_is_missed_with_reason():
    lane = "synthetic-n8n-lane"
    slots = every_slot(lane)
    rows = [ledger_row(lane, s) for s in slots if s not in (slots[0], slots[1], slots[3])]
    row = row_of(build([n8n_lane()], ledger_runs=rows), lane)
    assert row["missed_count"] == 2  # slots[0] fired 7 min ago: still inside the grace, so pending, not missed
    assert row["status"] == "missed"
    assert "n8n run ledger" in row["status_reason"]
    missed = [s for s in row["slots"] if s["status"] == "missed"]
    assert {s["slot_at"] for s in missed} == {J._iso(slots[1]), J._iso(slots[3])}
    assert row["slots"][0]["status"] == "pending"


def test_slot_before_coverage_is_not_measured_and_pending_slot_not_missed():
    lane = "synthetic-n8n-lane"
    slots = every_slot(lane)
    rows = [ledger_row(lane, s) for s in slots[1:4]]
    out = build([n8n_lane()], ledger_runs=rows, ledger_since=slots[3] - timedelta(minutes=1))
    row = row_of(out, lane)
    statuses = {s["slot_at"]: s["status"] for s in row["slots"]}
    assert statuses[J._iso(slots[5])] == "not_measured"
    assert statuses[J._iso(slots[0])] == "pending"  # 10:00 ET fire, 7 min ago < grace
    assert row["missed_count"] == 0


def test_inline_retry_and_dead_letter_and_breaker_are_fix_events():
    lane = "synthetic-n8n-lane"
    slots = every_slot(lane)
    rows = [ledger_row(lane, s) for s in slots]
    rows[1] = ledger_row(lane, slots[1], attempt_states=["RUN_TIMEOUT", "RUN_DONE"])
    dead = [{"lane_id": lane, "attempts": 3, "last_run_id": "x", "last_state": "RUN_FAILED", "last_reason": "exit_2",
             "verdict": "dead", "dead_at": _z(NOW - timedelta(days=1)), "released_at": _z(NOW - timedelta(hours=20)),
             "released_by": "operator", "release_note": "fixed config"}]
    breakers = [{"lane_id": lane, "opened_at": _z(NOW - timedelta(days=2)), "consecutive": 5, "released_at": None}]
    row = row_of(build([n8n_lane()], ledger_runs=rows, dead_letters=dead, breakers=breakers), lane)
    kinds = [f["kind"] for f in row["fixes"]]
    assert {"retry", "dead_letter", "dead_letter_released", "breaker_opened"} <= set(kinds)
    inline = next(f for f in row["fixes"] if f["by"] == "executor (inline retry)")
    assert "timeout → done" in inline["detail"]
    assert [f["at"] for f in row["fixes"]] == sorted((f["at"] for f in row["fixes"]), reverse=True)


def test_cron_journal_runs_pair_and_skip_dry_runs():
    lane = cron_lane()
    events = []
    for hours in range(1, 6):
        fire = NOW.replace(minute=0, second=0) - timedelta(hours=hours - 1)
        code = 1 if hours == 1 else 0
        events += [{"ts": _z(fire + timedelta(seconds=1)), "component": "synthetic_cron_job", "event_type": "started",
                    "run_id": f"r{hours}", "mode": "business"},
                   {"ts": _z(fire + timedelta(seconds=40)), "component": "synthetic_cron_job", "event_type": "completed",
                    "run_id": f"r{hours}", "exit_code": code, "mode": "business"}]
    events.append({"ts": _z(NOW - timedelta(minutes=2)), "component": "synthetic_cron_job.lock.dryrun",
                   "event_type": "started", "run_id": "dry", "mode": "dry_run"})
    events.append({"ts": _z(NOW - timedelta(minutes=50)), "component": "synthetic_cron_job", "event_type": "lock_skip",
                   "mode": "business"})
    covered = NOW.replace(minute=0, second=0) - timedelta(hours=4, minutes=1)
    row = row_of(build([lane], journal_events=events, journal_since=covered), "synthetic-cron-lane")
    assert row["history_sources"] == ["cron wrapper journal"]
    assert row["status"] == "failed" and row["status_reason"] == "Exit code 1"
    assert row["runs"][0]["duration_s"] == 39.0
    assert any(r["result"] == "skipped_lock" for r in row["runs"])
    assert all(r["run_id"] != "dry" for r in row["runs"])
    assert row["missed_count"] == 0


def test_output_file_time_is_never_a_success_and_gap_is_explained():
    lane = systemd_lane()
    out = build([lane], output_times={"synthetic-timer-lane": NOW - timedelta(minutes=20)})
    row = row_of(out, "synthetic-timer-lane")
    assert row["last_success_at"] is None
    assert row["missed_count"] is None
    assert "systemd" in row["history_gap"] and row["missed_gap"]
    assert row["status"] == "ok_unverified"
    assert row["output"]["written_at"] == "2026-11-04T14:47:00Z"
    stale = row_of(build([lane], output_times={"synthetic-timer-lane": NOW - timedelta(hours=3)}), "synthetic-timer-lane")
    assert stale["status"] == "late"
    none = row_of(build([lane]), "synthetic-timer-lane")
    assert none["status"] == "not_measured" and none["status_reason"]


def test_receipt_only_lane_shows_last_run_with_label():
    lane = systemd_lane()
    receipt = J.receipt_run({"started_at": _z(NOW - timedelta(minutes=30)), "finished_at": _z(NOW - timedelta(minutes=29)),
                             "ok_at": _z(NOW - timedelta(minutes=29)), "exit": 0, "status": "ok"}, None)
    row = row_of(build([lane], receipts={"synthetic-timer-lane": receipt}), "synthetic-timer-lane")
    assert row["history_sources"] == ["run receipt (last run only)"]
    assert row["history_gap"].startswith("only the last run is known")
    assert row["last_run"]["started_at"] == "2026-11-04T14:37:00Z"
    assert row["missed_count"] is None


def test_incidents_heal_and_diagnosis_are_fixes_without_argv_or_output():
    lane = n8n_lane()
    incident = {"id": "INC-SYN-1", "opened_at": _z(NOW - timedelta(hours=5)), "title": "Synthetic lane failed",
                "source": {"kind": "watcher", "watcher": "synthetic-watcher", "job": "synthetic-n8n-lane"},
                "status": "fixed", "closed_at": _z(NOW - timedelta(hours=4)), "resolution": "auto_resolved",
                "attempts": [{"at": _z(NOW - timedelta(hours=4, minutes=30)), "action": "restart_workflow", "ok": True,
                              "argv": ["secret-argv"], "output_tail": "SECRET OUTPUT"}]}
    fixer = {"job_id": "fx1", "lane": "incident-synthetic-n8n-lane", "failure_kind": "code_defect",
             "history": [{"at": _z(NOW - timedelta(hours=3)), "state": "fix_requested"}]}
    episode = {"lane": "synthetic-n8n-lane", "status": "resolved", "opened_at": _z(NOW - timedelta(hours=6)),
               "resolved_at": _z(NOW - timedelta(hours=2)), "severity": "WARN"}
    action = {"lane": "synthetic-n8n-lane", "at": _z(NOW - timedelta(hours=1)), "outcome": "reap_orphan_run",
              "action_id": "a1"}
    old = {**incident, "id": "INC-OLD", "attempts": [], "opened_at": _z(NOW - timedelta(days=30)), "closed_at": _z(NOW - timedelta(days=29))}
    out = build([lane], incidents=[incident, old], fixer_jobs=[fixer], episodes=[episode], actions=[action])
    row = row_of(out, "synthetic-n8n-lane")
    kinds = {f["kind"] for f in row["fixes"]}
    assert {"incident_opened", "heal_attempt", "incident_closed", "self_heal_fixer", "diagnosis_opened",
            "self_healed", "self_heal_action"} <= kinds
    assert all(f["ref"] != "INC-OLD" for f in row["fixes"])
    blob = json.dumps(out)
    assert "secret-argv" not in blob and "SECRET OUTPUT" not in blob
    closed = next(f for f in row["fixes"] if f["kind"] == "incident_closed")
    assert "automatically" in closed["detail"] and "restart_workflow" in closed["detail"]


def test_inactive_and_unscheduled_states_are_honest():
    paused = {**n8n_lane("synthetic-paused"), "state": "PAUSED"}
    event = {"lane_id": "synthetic-event", "state": "ACTIVE", "scheduler": {"kind": "event"}}
    out = build([paused, event])
    assert row_of(out, "synthetic-paused")["status"] == "paused"
    ev = row_of(out, "synthetic-event")
    assert ev["status"] == "not_measured" and "event-driven" in ev["status_reason"]
    assert ev["missed_count"] is None and ev["missed_gap"]


def test_unreadable_schedule_is_reported_not_raised():
    lane = cron_lane(expr="l * * * *")
    row = row_of(build([lane]), "synthetic-cron-lane")
    assert row["cadence"]["schedule_gap"] == "The declared schedule could not be read"
    assert row["slots"] == []


def test_naive_clock_refused():
    with pytest.raises(ValueError):
        J.build({"lanes": []}, {}, now=NOW.replace(tzinfo=None), trading_day=WEEKDAY)


def _state_root(tmp_path, lanes):
    gov = tmp_path / "data/governance"
    gov.mkdir(parents=True)
    conn = sqlite3.connect(gov / "n8n_coordination_ledger.sqlite")
    conn.execute("create table runs (run_id text, lane_id text, mode text, state text, requested_by text, "
                 "requested_at text, started_at text, finished_at text, exit_code int, duration_s real, attempt int, "
                 "parent_run_id text, slot_key text, receipt_json text)")
    conn.execute("create table dead_letters (lane_id text, mode text, attempts int, last_run_id text, last_state text, "
                 "last_reason text, verdict text, dead_at text, released_at text, released_by text, release_note text)")
    conn.execute("create table breakers (lane_id text, opened_at text, consecutive int, released_at text, released_by text)")
    for s in every_slot("synthetic-n8n-lane"):
        r = ledger_row("synthetic-n8n-lane", s)
        conn.execute("insert into runs values (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (r["run_id"], r["lane_id"], "live", r["state"], r["requested_by"], r["requested_at"],
                      r["started_at"], r["finished_at"], 0, 30, 1, None, r["slot_key"],
                      json.dumps({"attempt_states": ["RUN_DONE"], "reason": None, "big": "x" * 1000})))
    conn.commit()
    conn.close()
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs/safe_flock_events.jsonl").write_text(
        "not json {\"event_type\":\"started\"\n" + json.dumps(
            {"ts": _z(NOW - timedelta(minutes=7)), "component": "synthetic_cron_job", "event_type": "started",
             "run_id": "c1", "mode": "business"}) + "\n")
    inc = tmp_path / "data/coordination/incidents"
    inc.mkdir(parents=True)
    (inc / "index.json").write_text(json.dumps({"schema": "IncidentIndex@v1", "incidents": []}))
    reg = tmp_path / "lane_registry.json"
    reg.write_text(json.dumps({"lanes": lanes}))
    return reg


def test_load_reads_stores_read_only_and_api_filters(tmp_path):
    reg = _state_root(tmp_path, [n8n_lane(), cron_lane(), systemd_lane()])
    before = (tmp_path / "data/governance/n8n_coordination_ledger.sqlite").stat().st_mtime_ns
    started = time.monotonic()
    snap = J.snapshot(state_root=tmp_path, registry_path=reg, now=NOW)
    assert time.monotonic() - started < 2
    assert (tmp_path / "data/governance/n8n_coordination_ledger.sqlite").stat().st_mtime_ns == before
    assert not (tmp_path / "data/runtime").exists()  # nothing written
    n8n = row_of(snap, "synthetic-n8n-lane")
    assert n8n["history_sources"] == ["n8n run ledger"] and n8n["missed_count"] == 0
    cron = row_of(snap, "synthetic-cron-lane")
    assert cron["status"] == "running"
    journal = next(s for s in snap["sources"] if s["name"] == "cron wrapper journal")
    assert journal["note"] == "1 journal line(s) could not be read"
    assert "big" not in json.dumps(snap)

    J._CACHE.clear()
    full = J.get_jobs_history({"filter": "all"}, state_root=tmp_path, registry_path=reg)
    assert full["total"] == 3 and "rows" in full and "runs" not in full["rows"][0]
    detail = J.get_jobs_history({"job": "synthetic-n8n-lane"}, state_root=tmp_path, registry_path=reg)
    assert detail["row"]["lane_id"] == "synthetic-n8n-lane" and detail["row"]["runs"]
    assert J.get_jobs_history({"filter": "systemd"}, state_root=tmp_path, registry_path=reg)["total"] == 1
    with pytest.raises(ValueError):
        J.get_jobs_history({"filter": "nope"}, state_root=tmp_path, registry_path=reg)
    J._CACHE.clear()


def test_missing_ledger_is_a_gap_not_an_error(tmp_path):
    reg = tmp_path / "reg.json"
    reg.write_text(json.dumps({"lanes": [n8n_lane()]}))
    snap = J.snapshot(state_root=tmp_path, registry_path=reg, now=NOW)
    assert "the n8n run ledger is absent" in snap["gaps"]
    assert not (tmp_path / "data/governance/n8n_coordination_ledger.sqlite").exists()
    row = row_of(snap, "synthetic-n8n-lane")
    assert row["missed_count"] is None and row["status"] == "not_measured"
