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


def _evaluate(jobs, *, cron=(), log_age=None, db_age=None, last_runs=None, lane_map=None):
    hits = last_runs or {}
    return jcm.evaluate(cron_lines=list(cron), log_age=(log_age or (lambda _a: None)),
                        db_age=(db_age or (lambda _a: None)), last_run=lambda job: hits.get(job["name"]),
                        lane_map=(lane_map or {}), now=NOW)


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


def test_the_lane_map_is_derived_from_the_allowlist_and_ambiguous_lanes_stay_unmapped(monkeypatch, tmp_path):
    jobs = [_job("one"), _job("two"), _job("ambiguous")]
    monkeypatch.setattr(jcm, "REGISTRY", jobs)
    monkeypatch.setattr(jcm, "PROJECT_ROOT", tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config/n8n_run_allowlist.json").write_text(json.dumps({"lanes": [
        {"lane_id": "one-lane", "command": ["$PY", "scripts/one.py"]},
        {"lane_id": "two-lane", "command": ["$PY", "scripts/two.py"]},
        {"lane_id": "two-a", "command": ["$PY", "scripts/two.py"]},
    ]}))
    lane_map, error = jcm._lane_map()
    assert error is None
    assert lane_map == {"one": "one-lane"}, "two.py has two lanes: ambiguity must not become a guess"


def test_an_unreadable_allowlist_reports_an_error_and_maps_nothing(monkeypatch, tmp_path):
    monkeypatch.setattr(jcm, "PROJECT_ROOT", tmp_path)
    lane_map, error = jcm._lane_map()
    assert lane_map == {} and error in ("FileNotFoundError", "JSONDecodeError")


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
