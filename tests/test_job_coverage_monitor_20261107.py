"""LQ-20261107-145 — job coverage monitor: a run clock and an output clock that are never confused.

Every dependency of ``evaluate`` is injected here: no crontab, no database, no ledger, no host log is read. The
defect these tests pin is the one the audit found live: a lane that n8n dispatches read NOT_SCHEDULED because the
crontab had been retired, and an OUTPUT row's age was printed as "since last run".
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts import job_coverage_monitor as jcm

NOW = datetime(2026, 11, 7, 17, tzinfo=timezone.utc)


def _job(name="lane-a", *, cadence=30, signal=("db", "SELECT 1")):
    return {"name": name, "schedule_match": f"{name}.py", "cadence_h": cadence, "signal": signal}


def _evaluate(jobs, *, cron=(), log_age=None, db_age=None, last_runs=None, lane_map=None, schedulers=None):
    hits = last_runs or {}
    return jcm.evaluate(cron_lines=list(cron), log_age=(log_age or (lambda _a: None)),
                        db_age=(db_age or (lambda _a: None)), last_run=lambda job: hits.get(job["name"]),
                        lane_map=(lane_map or {}), schedulers=schedulers, now=NOW)


@pytest.fixture(autouse=True)
def _synthetic_registry(monkeypatch):
    monkeypatch.setattr(jcm, "REGISTRY", [])


def _rows(monkeypatch, jobs, **kwargs):
    monkeypatch.setattr(jcm, "REGISTRY", jobs)
    return {r["job"]: r for r in _evaluate(jobs, **kwargs)}


def test_an_n8n_ledger_run_is_a_schedule_even_with_no_crontab_line(monkeypatch):
    job = _job("catalyst_momentum_engine")
    runs = {"catalyst_momentum_engine": {"state": "RUN_DONE", "finished_at": (NOW - timedelta(hours=14)).isoformat()}}
    row = _rows(monkeypatch, [job], cron=[], last_runs=runs)["catalyst_momentum_engine"]
    assert row["scheduled"] is True and row["status"] == "OK", row
    assert row["run_source"].startswith("n8n ledger") and row["run_age_hours"] == 14.0


def test_a_fresh_run_with_an_old_output_is_stale_output_not_since_last_run(monkeypatch):
    job = _job("catalyst_momentum_engine")
    runs = {"catalyst_momentum_engine": {"state": "RUN_DONE", "finished_at": (NOW - timedelta(hours=14)).isoformat()}}
    row = _rows(monkeypatch, [job], cron=[], last_runs=runs, db_age=lambda _s: 219.9)["catalyst_momentum_engine"]
    assert row["status"] == "STALE_OUTPUT", row
    assert row["run_age_hours"] == 14.0 and row["output_age_hours"] == 219.9
    assert "ran 14.0h ago" in row["detail"] and "output is 219.9h old" in row["detail"]
    assert "since last run" not in row["detail"], "the output age is never called a run age"


def test_a_run_that_staged_nothing_still_does_not_excuse_an_old_output(monkeypatch):
    """The run's own "staged 0" is evidence to report, never a licence to grade a stale output green."""
    job = _job("catalyst_momentum_engine")
    runs = {"catalyst_momentum_engine": {"state": "RUN_DONE",
                                         "finished_at": (NOW - timedelta(hours=14)).isoformat()}}
    row = _rows(monkeypatch, [job], cron=[], last_runs=runs, db_age=lambda _s: 219.9)["catalyst_momentum_engine"]
    assert row["status"] == "STALE_OUTPUT", "an absence the run cannot account for is the finding"
    assert row["run_age_hours"] == 14.0 and row["output_age_hours"] == 219.9


def test_a_run_clock_past_the_cadence_is_stale_and_an_old_output_is_not(monkeypatch):
    job = _job("lane-a")
    runs = {"lane-a": {"state": "RUN_DONE", "finished_at": (NOW - timedelta(hours=40)).isoformat()}}
    row = _rows(monkeypatch, [job], cron=["*/30 * * * * lane-a.py"], last_runs=runs)["lane-a"]
    assert (row["status"], row["run_age_hours"]) == ("STALE", 40.0)
    assert "since last run" in row["detail"]


def test_no_cron_no_lane_and_no_run_is_still_not_scheduled(monkeypatch):
    row = _rows(monkeypatch, [_job("orphan")], cron=[], db_age=lambda _s: 5.0)["orphan"]
    assert row["status"] == "NOT_SCHEDULED" and row["scheduled"] is False
    assert "n8n ledger run" in row["detail"]


def test_scheduled_without_any_heartbeat_is_no_signal_not_a_pass(monkeypatch):
    row = _rows(monkeypatch, [_job("quiet")], cron=["0 * * * * quiet.py"])["quiet"]
    assert row["status"] == "NO_SIGNAL" and row["run_age_hours"] is None


def test_an_output_only_clock_without_a_run_record_is_named_output(monkeypatch):
    row = _rows(monkeypatch, [_job("old-out")], cron=["0 * * * * old-out.py"], db_age=lambda _s: 40.0)["old-out"]
    assert row["status"] == "STALE_OUTPUT" and "no run record" in row["detail"]


def test_the_lane_map_is_derived_from_the_allowlist_and_several_lanes_are_kept(monkeypatch, tmp_path):
    """Several lanes for one job is normal (three catalyst bands), and the newest run settles it."""
    jobs = [_job("one"), _job("two")]
    monkeypatch.setattr(jcm, "REGISTRY", jobs)
    monkeypatch.setattr(jcm, "PROJECT_ROOT", tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config/n8n_run_allowlist.json").write_text(json.dumps({"lanes": [
        {"lane_id": "one-lane", "command": ["$PY", "scripts/one.py"]},
        {"lane_id": "two-lane", "command": ["$PY", "scripts/two.py"]},
        {"lane_id": "two-a", "command": ["$PY", "scripts/two.py"]},
    ]}))
    lane_map, error = jcm._lane_map()
    assert lane_map == {"one": ["one-lane"], "two": ["two-a", "two-lane"]}, lane_map
    assert error.endswith("Error"), f"the missing lane registry is reported, not hidden: {error}"


def test_the_lane_map_reads_the_lane_registry_so_a_wrapper_scheduler_is_found(monkeypatch, tmp_path):
    """The live case: cron runs `run_family_slot.py --family topic-ingestion`, not `topic_ingestion.py`."""
    jobs = [_job("topic_ingestion"), _job("multi")]
    monkeypatch.setattr(jcm, "REGISTRY", jobs)
    monkeypatch.setattr(jcm, "PROJECT_ROOT", tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config/lane_registry.json").write_text(json.dumps({"lanes": [
        {"lane_id": "topic-ingestion", "state": "ACTIVE",
         "scheduler": {"kind": "cron", "match": "scripts/run_family_slot.py --family topic-ingestion"},
         "command": ["bash gate.sh timeout 30m $PY scripts/topic_ingestion.py --use-llm-queries"]},
        {"lane_id": "multi-a", "state": "ACTIVE",
         "scheduler": {"kind": "cron", "match": ["scripts/multi.py --band open", "scripts/multi.py --band close"]}},
        {"lane_id": "unrelated", "state": "ACTIVE", "scheduler": {"kind": "cron", "match": "scripts/other.py"}},
    ]}))  # nosemgrep: tq-py-nonatomic-store-write -- tmp_path fixture, not a store
    lane_map, error = jcm._lane_map()
    assert error.endswith("Error"), f"the missing allowlist is reported: {error}"
    assert lane_map == {"topic_ingestion": ["topic-ingestion"], "multi": ["multi-a"]}, lane_map


def test_an_unreadable_catalogue_reports_an_error_and_maps_nothing(monkeypatch, tmp_path):
    monkeypatch.setattr(jcm, "PROJECT_ROOT", tmp_path)
    lane_map, error = jcm._lane_map()
    assert lane_map == {} and error in ("FileNotFoundError", "JSONDecodeError")


def _registry(tmp_path, lanes):
    (tmp_path / "config").mkdir(exist_ok=True)
    (tmp_path / "config/lane_registry.json").write_text(json.dumps({"lanes": lanes}))  # nosemgrep: tq-py-nonatomic-store-write -- tmp_path fixture


def test_a_wrapper_lane_schedules_the_job_it_runs(monkeypatch, tmp_path):
    """LQ-20261107-355: the crontab names the wrapper. topic_ingestion was NOT_SCHEDULED with cron running it."""
    job = _job("topic_ingestion", cadence=42, signal=("log", "topic_ingestion.log"))
    monkeypatch.setattr(jcm, "REGISTRY", [job])
    monkeypatch.setattr(jcm, "PROJECT_ROOT", tmp_path)
    _registry(tmp_path, [{"lane_id": "topic-ingestion", "state": "ACTIVE",
                          "scheduler": {"kind": "cron",
                                        "match": "scripts/run_family_slot.py --family topic-ingestion"},
                          "command": ["$PY scripts/topic_ingestion.py --use-llm-queries"]}])
    row = _rows(monkeypatch, [job],
                cron=["45 20 * * 1-5 cd $PROJ && $PY scripts/run_family_slot.py --family topic-ingestion"],
                lane_map={"topic_ingestion": ["topic-ingestion"]}, log_age=lambda _a: 14.3)["topic_ingestion"]
    assert row["scheduled"] is True and row["status"] == "OK", row
    assert row["schedule_source"] == "crontab:scripts/run_family_slot.py --family topic-ingestion", row


def test_a_retired_lane_does_not_schedule_a_job(monkeypatch, tmp_path):
    """A RETIRED lane still names the script; letting it schedule the job would turn NOT_SCHEDULED into a false OK."""
    job = _job("hermes_industry_novelty_discovery")
    monkeypatch.setattr(jcm, "REGISTRY", [job])
    monkeypatch.setattr(jcm, "PROJECT_ROOT", tmp_path)
    _registry(tmp_path, [{"lane_id": "hermes-industry-novelty-discovery", "state": "RETIRED",
                          "scheduler": {"kind": "cron",
                                        "match": "scripts/hermes_industry_novelty_discovery.py"}}])
    runs = {"hermes_industry_novelty_discovery": {
        "lane_id": "hermes-industry-novelty-discovery", "state": "RUN_DONE",
        "finished_at": (NOW - timedelta(hours=2)).isoformat()}}
    row = _rows(monkeypatch, [job], cron=[], last_runs=runs, log_age=lambda _a: 15.1,
                lane_map={"hermes_industry_novelty_discovery": ["hermes-industry-novelty-discovery"]}
                )["hermes_industry_novelty_discovery"]
    assert row["status"] == "NOT_SCHEDULED" and row["scheduled"] is False, row
    assert row["run_age_hours"] == 2.0, "a retired lane's run is still printed as a heartbeat: " + str(row)


def test_an_active_lane_run_schedules_and_a_retired_lane_run_alone_does_not(monkeypatch, tmp_path):
    live, dead = _job("live-lane"), _job("dead-lane")
    monkeypatch.setattr(jcm, "REGISTRY", [live, dead])
    monkeypatch.setattr(jcm, "PROJECT_ROOT", tmp_path)
    _registry(tmp_path, [{"lane_id": "live-lane", "state": "ACTIVE", "scheduler": {"kind": "n8n"}},
                         {"lane_id": "dead-lane", "state": "RETIRED", "scheduler": {"kind": "n8n"}}])
    runs = {name: {"lane_id": name, "state": "RUN_DONE", "finished_at": (NOW - timedelta(hours=1)).isoformat()}
            for name in ("live-lane", "dead-lane")}
    rows = _rows(monkeypatch, [live, dead], cron=[], last_runs=runs,
                 lane_map={"live-lane": ["live-lane"], "dead-lane": ["dead-lane"]})
    assert rows["live-lane"]["status"] == "OK" and rows["live-lane"]["schedule_source"] == "n8n ledger", rows
    assert rows["dead-lane"]["status"] == "NOT_SCHEDULED" and rows["dead-lane"]["scheduled"] is False, rows


def test_the_systemd_unit_comes_from_the_lane_not_only_the_registry_field(monkeypatch, tmp_path):
    """aegis_overnight read NOT_SCHEDULED while its ACTIVE lane's unit was a different name from the hard-coded one."""
    job = {**_job("aegis_overnight", signal=("log", "aegis-overnight.log")),
           "systemd_timer": "aegis-overnight.timer"}
    monkeypatch.setattr(jcm, "REGISTRY", [job])
    monkeypatch.setattr(jcm, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(jcm, "_timer_active", lambda unit: unit == "aegis-surveillance.timer")
    _registry(tmp_path, [{"lane_id": "aegis-overnight", "state": "ACTIVE",
                          "scheduler": {"kind": "systemd", "expression": "aegis-surveillance.timer"}}])
    row = _rows(monkeypatch, [job], cron=[], lane_map={"aegis_overnight": ["aegis-overnight"]},
                log_age=lambda _a: 8.0)["aegis_overnight"]
    assert row["scheduled"] is True and row["schedule_source"] == "systemd:aegis-surveillance.timer", row
    assert row["status"] == "OK", row


def test_the_newest_run_across_a_jobs_lanes_is_the_heartbeat(monkeypatch):
    job = _job("catalyst_momentum_engine")
    runs = {"catalyst_momentum_engine": {"state": "RUN_DONE",
                                         "finished_at": (NOW - timedelta(hours=2)).isoformat()}}
    row = _rows(monkeypatch, [job], cron=[], last_runs=runs,
                lane_map={"catalyst_momentum_engine": ["band-a", "band-b"]})["catalyst_momentum_engine"]
    assert row["status"] == "OK" and row["run_age_hours"] == 2.0, row


def _ledger(path, *, runs=(), outcomes=()):
    import sqlite3
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE runs (run_id TEXT, lane_id TEXT, mode TEXT, state TEXT, "
                 "finished_at TEXT, exit_code INTEGER)")
    conn.execute("CREATE TABLE run_outcomes (run_id TEXT, lane_id TEXT, mode TEXT, status TEXT, "
                 "run_state TEXT, finished_at TEXT, exit_code INTEGER)")
    conn.executemany("INSERT INTO runs VALUES (?,?,?,?,?,?)", runs)
    conn.executemany("INSERT INTO run_outcomes (run_id,lane_id,mode,status,run_state,finished_at,exit_code) "
                     "VALUES (?,?,?,?,?,?,?)", outcomes)
    conn.commit()
    conn.close()


def test_a_run_outcomes_row_is_a_run_even_when_runs_has_none(monkeypatch, tmp_path):
    """The ledger writes a finished run twice; reading only `runs` makes one table's lag into blindness."""
    ledger = tmp_path / "ledger.sqlite"
    _ledger(ledger, outcomes=[("r1", "lane-x", "live", "success", "RUN_DONE", "2026-11-07T15:00:00+00:00", 0)])
    monkeypatch.setenv("TRADEAI_N8N_COORDINATION_LEDGER", str(ledger))
    newest = jcm._ledger_newest(["lane-x"])
    assert newest["lane-x"]["table"] == "run_outcomes" and newest["lane-x"]["state"] == "RUN_DONE", newest
    assert jcm._run_source_label(newest["lane-x"]) == "n8n run_outcomes (RUN_DONE)"


def test_the_newer_of_the_two_ledger_tables_wins_and_a_failed_run_is_not_a_heartbeat(monkeypatch, tmp_path):
    ledger = tmp_path / "ledger.sqlite"
    _ledger(ledger,
            runs=[("r1", "lane-x", "live", "RUN_DONE", "2026-11-07T10:00:00+00:00", 0),
                  ("r2", "lane-x", "live", "RUN_FAILED", "2026-11-07T16:00:00+00:00", 1)],
            outcomes=[("r3", "lane-x", "live", "success", "RUN_DONE", "2026-11-07T14:00:00+00:00", 0)])
    monkeypatch.setenv("TRADEAI_N8N_COORDINATION_LEDGER", str(ledger))
    hit = jcm._ledger_newest(["lane-x"])["lane-x"]
    assert (hit["run_id"], hit["table"]) == ("r3", "run_outcomes"), "a failed run is not a healthy heartbeat"
    assert jcm._ledger_newest(["lane-y"]) == {}, "an unknown lane has no evidence, not a guess"


def test_a_missing_ledger_is_no_evidence_and_never_a_crash(monkeypatch, tmp_path):
    monkeypatch.setenv("TRADEAI_N8N_COORDINATION_LEDGER", str(tmp_path / "absent.sqlite"))
    assert jcm._ledger_newest(["lane-x"]) == {}


def test_a_run_receipt_is_evidence_when_the_ledger_has_no_row(monkeypatch, tmp_path):
    """The 80k-file receipts folder is read by a glob that names the lane, never by parsing every file."""
    import lib.lane_registry as lr  # the module the monitor imports (scripts/ is on sys.path)
    folder = tmp_path / "n8n_runs"
    folder.mkdir()
    (folder / "d:lane-x:dry_run:20261107T1400.json").write_text(json.dumps(
        {"run_id": "d:lane-x:dry_run:20261107T1400", "lane_id": "lane-x", "mode": "dry_run",
         "state": "RUN_DONE", "finished_at": "2026-11-07T14:00:00+00:00", "exit_code": 0}))
    (folder / "d:lane-xy:dry_run:20261107T1500.json").write_text(json.dumps(
        {"lane_id": "lane-xy", "state": "RUN_DONE", "finished_at": "2026-11-07T15:00:00+00:00"}))
    (folder / "d:lane-x:dry_run:20261107T1600.json").write_text(json.dumps(
        {"lane_id": "lane-x", "state": "RUN_FAILED", "finished_at": "2026-11-07T16:00:00+00:00"}))
    monkeypatch.setenv("TRADEAI_N8N_COORDINATION_LEDGER", str(tmp_path / "absent.sqlite"))
    monkeypatch.setattr(lr, "n8n_runs_dir", lambda root=None: folder)
    hit = jcm._receipt_newest(["lane-x"])["lane-x"]
    assert (hit["finished_at"], hit["table"]) == ("2026-11-07T14:00:00+00:00", "receipt"), hit


def test_the_durable_record_carries_every_row_and_the_summary(monkeypatch, tmp_path):
    job = _job("lane-a")
    monkeypatch.setattr(jcm, "REGISTRY", [job])
    rows = _evaluate([job], cron=[], db_age=lambda _s: 5.0)
    res = jcm.write_results(rows, root=tmp_path, generated_at="2026-11-07T17:00:00+00:00")
    assert res["ok"] is True and res["error"] is None, res
    doc = json.loads(Path(res["path"]).read_text())
    assert (doc["schema"], doc["generated_at"]) == (jcm.RESULTS_SCHEMA, "2026-11-07T17:00:00+00:00")
    assert doc["summary"]["total"] == 1 and doc["summary"]["fail"] == 1
    assert doc["summary"]["not_scheduled"] == 1
    assert doc["results"][0]["job"] == "lane-a" and "run_age_hours" in doc["results"][0]


def test_a_failed_write_answers_an_explicit_unknown(monkeypatch, tmp_path):
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("")  # a root that cannot be a directory: the write has to fail
    monkeypatch.setattr(jcm, "REGISTRY", [_job("lane-a")])
    res = jcm.write_results(_evaluate([_job("lane-a")], cron=[]), root=blocker)
    assert res["ok"] is False and res["error"], "a failed write is reported by name, never as a silent file"


def test_the_durable_record_goes_to_the_persistent_state_root(monkeypatch, tmp_path):
    monkeypatch.setenv("TRADEAI_PERSISTENT_STATE_ROOT", str(tmp_path))
    monkeypatch.chdir(tmp_path)  # a wrong resolver would write into the checkout, not here
    job = _job("lane-a")
    monkeypatch.setattr(jcm, "REGISTRY", [job])
    res = jcm.write_results(_evaluate([job], cron=[]))
    assert res["ok"] is True and Path(res["path"]) == tmp_path / jcm.RESULTS_REL, "the record must land in the state root"
    assert Path(res["path"]).is_file()


def test_a_dry_run_writes_no_durable_record_and_a_real_run_writes_one(monkeypatch):
    calls = []
    monkeypatch.setattr(jcm, "REGISTRY", [_job("lane-a")])
    monkeypatch.setattr(jcm, "write_results", lambda *a, **k: calls.append(a) or None)
    monkeypatch.setattr(jcm.sys, "argv", ["job_coverage_monitor.py", "--dry-run"])
    kwargs = dict(cron_lines=[], log_age=lambda _a: None, db_age=lambda _s: 5.0,
                  last_run=lambda _j: None, lane_map={}, now=NOW)
    assert jcm.main(write=False, **kwargs) == 0
    assert calls == [], "a dry run never writes the durable record"
    assert jcm.main(write=True, **kwargs) == 0
    assert len(calls) == 1
