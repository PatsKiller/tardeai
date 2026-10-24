"""W4 execution truth over pinned registry/receipt/event fixtures; no live services."""
from datetime import datetime, timedelta, timezone
import json

import pytest

from scripts.lib import jobs_health as J
from scripts.lib import scheduler_operations as SO, releases_schedules_view as RS
from scripts.lib.data_broker import n8n_today as NT

NOW = datetime(2026, 10, 23, 16, 20, tzinfo=timezone.utc)


def lane(name="test-job", **extra):
    return {"lane_id": name, "state": "ACTIVE", "expected_cadence_hours": 1/12,
        "scheduler": {"kind": "cron", "expression": "*/5 9-16 * * 1-5"},
        "output_signal": {"kind": "file_mtime", "path": "logs/job.log"}, **extra}


def run(*, at=NOW-timedelta(minutes=1), state="RUN_DONE", code=0, mode="live", **receipt):
    base = {"run_id": "test-run", "lane_id": "test-job", "mode": "live", "state": state,
            "exit_code": code, "finished_at": at.isoformat(), "requested_at": at.isoformat()}
    return {**base, "receipt": {**base, "mode": mode, "schema": "RunReceipt@v3",
            "output_verdict": {"verdict": "produced"}, **receipt}}


def build(lanes=None, *, runs=None, events=None, now=NOW):
    return J.build({"lanes": lanes or [lane()]}, {"events": events or [], "successes": {}}, runs or [], {},
                   now=now, trading_day=lambda d: d.weekday() < 5)


def test_fresh_error_log_is_not_a_success():
    row, = build()["rows"]
    assert row["result"] == "unknown" and row["last_success_at"] is None
    assert row["next_due_at"] == "2026-10-23T16:25:00Z"


def test_failed_receipt_keeps_stderr_cause_even_when_output_file_is_fresh():
    result = build(runs=[run(state="RUN_FAILED", code=1, reason="exit_1", stderr_tail="safe_flock: refusing symlink_component")])
    row, = result["rows"]
    assert row["result"] == "failed" and "symlink_component" in row["cause"]
    assert row["last_success_at"] is None
    assert result["incident_count"] == 2  # failed job plus independently unmeasured monitor


def test_success_needs_effective_live_and_output_receipt():
    row, = build(runs=[run(at=NOW)])["rows"]
    assert row["result"] == "succeeded" and row["successful_run_id"] == "test-run"
    for bad in [run(mode="dry_run"), run(output_verdict={"verdict": "unverifiable"}), run(exit_code=None)]:
        row, = build(runs=[bad])["rows"]
        assert row["result"] != "succeeded" and row["last_success_at"] is None


def test_two_missed_opportunities_beat_old_success():
    row, = build(runs=[run(at=NOW-timedelta(hours=1))])["rows"]
    assert row["result"] == "missed" and row["missed_fires"] == 2


def test_later_success_recovers_failure_and_paused_never_claims_next_due():
    failed = run(at=NOW-timedelta(minutes=10), state="RUN_FAILED", code=1, reason="exit_1")
    success = run(at=NOW)
    result = build([lane(), lane("paused", state="PAUSED"), lane("retired", state="RETIRED")], runs=[failed, success])
    a, b, c = result["rows"]
    assert a["result"] == "succeeded" and b["result"] == "paused" and c["result"] == "retired"
    assert b["next_due_at"] is None and c["next_due_at"] is None


def test_wrapper_refusal_and_business_completion_are_execution_evidence():
    lanes = [lane(watchdog_wrapper_component="test")]
    refuse = {"component": "test", "event_type": "refused", "ts": (NOW-timedelta(minutes=5)).isoformat(),
              "mode": "business", "reason": "lock wrapper refused the release path"}
    row, = build(lanes, events=[refuse])["rows"]
    assert row["result"] == "failed" and "refused" in row["cause"]
    done = {"component": "test", "event_type": "completed", "ts": NOW.isoformat(), "exit_code": 0, "mode": "business"}
    row, = build(lanes, events=[refuse, done])["rows"]
    assert row["result"] == "succeeded"
    row, = build(lanes, events=[refuse, {**done, "mode": "dry_run"}])["rows"]
    assert row["result"] == "failed"


def test_weekend_is_outside_window_and_no_future_receipts_count():
    weekend = NOW + timedelta(days=1)
    row, = build(now=weekend, runs=[run(at=weekend+timedelta(minutes=1))])["rows"]
    assert row["result"] == "outside_window" and row["next_due_at"] == "2026-10-26T13:00:00Z"


def test_paging_counts_and_cache_do_not_mutate_shared_snapshot(monkeypatch, tmp_path):
    original = build([lane(f"test-{i}") for i in range(152)])
    monkeypatch.setattr(J, "_load", lambda *a: original)
    a = J.get_jobs_health({"filter": "all", "limit": "10000"}, state_root=tmp_path, now=NOW)
    b = J.get_jobs_health({"filter": "all", "offset": "100", "limit": "50"}, state_root=tmp_path, now=NOW)
    assert a["total"] == 152 and len(a["rows"]) == 100 and a["has_more"]
    assert len(b["rows"]) == 50 and a["summary"] == b["summary"]
    assert len(original["rows"]) == 152


def test_n8n_today_counts_workflow_namespace_by_execution_date(tmp_path):
    directory = tmp_path / NT.RUNS_REL
    directory.mkdir(parents=True)
    for i, day in enumerate([NOW, NOW-timedelta(days=1), NOW]):
        doc = {"run_id": f"n8n-wf-workflow-{i}", "lane_id": "test-job", "mode": "live",
               "state": "RUN_FAILED", "reason": "exit_1", "stderr_tail": "lock wrapper refused release path",
               "finished_at": day.isoformat(), "exit_code": 1}
        (directory / (doc["run_id"] + ".json")).write_text(json.dumps(doc))
    result = NT.build(tmp_path, NOW)
    assert result["runs"]["observed_totals"]["live"] == 2
    assert result["coverage"]["sources"]["runs"]["complete"]
    assert len(result["failures"]) == 2 and result["failures"][0]["cause"] == "lock wrapper refused release path"


def test_stderr_preserved_on_releases_and_scheduler_projection(tmp_path):
    receipt = {"reason": "exit_1", "stderr_tail": "Permission denied for wrapper"}
    assert RS._receipt_bits(json.dumps(receipt))["reason"] == receipt["stderr_tail"]
    assert "stderr_tail" in SO.RECEIPT_KEYS and "stage_clamp" in SO.RECEIPT_KEYS


def test_naive_clock_refused():
    with pytest.raises(ValueError, match="aware"):
        build(now=NOW.replace(tzinfo=None))


def test_log_freshness_uses_completed_exit_zero_marker_not_error_write_time(tmp_path):
    path = tmp_path / "job.log"
    path.write_text('2026-10-23T15:00:00Z completed rc=0\n2026-10-23T16:19:00Z safe_flock: refusing path\n')
    assert J.last_log_success(path, now=NOW).isoformat() == '2026-10-23T15:00:00+00:00'
    path.write_text('2026-10-23T16:19:00Z dry-run completed rc=0\n2026-10-23T16:19:00Z safe_flock: refusing path\n')
    assert J.last_log_success(path, now=NOW) is None
    path.write_text(json.dumps({"event_type": "completed", "mode": "business", "exit_code": 0, "ts": NOW.isoformat()})+'\n')
    assert J.last_log_success(path, now=NOW) == NOW


def test_health_log_scraper_catches_wrapper_refusal_without_level_token(tmp_path, monkeypatch):
    import health_agent as agent
    import time
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW if tz else NOW.replace(tzinfo=None)
    monkeypatch.setattr(agent, "datetime", Clock)
    monkeypatch.setattr(agent, "LOG_DIR", tmp_path)
    monkeypatch.setattr(agent, "_POLICY", {"log_errors": {"watch": ["wrapper.log"], "error_threshold": 1}})
    path = tmp_path / "wrapper.log"
    path.write_text('2026-10-23 16:19:00 safe_flock: refusing symlink_component\n')
    monkeypatch.setattr(time, "time", lambda: NOW.timestamp())
    finding, = agent.collect_log_errors()
    assert finding["type"] == "log_errors" and "symlink_component" in finding["sample"]
    assert agent._file_age_h(path) is None


def test_platform_job_execution_cannot_be_green_while_jobs_failed(tmp_path):
    from scripts.lib import platform_health as PH
    report = build(runs=[run(state="RUN_FAILED", code=1, stderr_tail="wrapper refused path")])
    deps = PH.Deps(state_root=tmp_path, now=lambda: NOW, extra={"jobs_health_reader": lambda *a, **k: report})
    item, = PH.probe_job_execution(deps)
    assert item["status"] == "CRIT" and item["detail"]["summary"]["failed"] == 1
    report["summary"]["failed"] = 0
    item, = PH.probe_job_execution(deps)
    assert item["status"] == "UNKNOWN"  # no operational independent monitor receipt


def test_release_failures_survive_a_later_successful_receipt(tmp_path):
    deploy, windows = tmp_path / "deploy", tmp_path / "windows"
    deploy.mkdir()
    (deploy / "deploy_receipt.json").write_text(json.dumps({"at": NOW.isoformat(), "mode": "promote", "ok": True}))
    attempts = [{"at": (NOW-timedelta(minutes=i+1)).isoformat(), "mode": "promote", "ok": False,
                 "extra": "wrapper refusal"} for i in range(5)]
    (deploy / "deploy_receipt_history.jsonl").write_text(''.join(json.dumps(a)+'\n' for a in attempts))
    rows = RS.read_release_errors(deploy, windows, NOW)["value"]["rows"]
    assert len(rows) == 5 and all(r["detail"] == "wrapper refusal" for r in rows)


def test_jobs_due_today_includes_future_fires_without_claiming_they_ran():
    result = build([lane(scheduler={"kind": "cron", "expression": "0 20 * * 1-5"})])
    assert result["summary"]["due_today"] == 1
    assert result["rows"][0]["last_run_at"] is None
    assert result["rows"][0]["result"] != "succeeded"


def test_pending_live_request_is_due_but_never_success_or_run_start():
    requested = {"run_id": "pending", "lane_id": "test-job", "mode": "live", "state": "REQUESTED", "requested_at": NOW.isoformat()}
    row, = build(runs=[requested])["rows"]
    assert row["result"] == "due" and row["last_run_at"] is None and row["last_success_at"] is None
