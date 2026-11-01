"""Watchdog activation blockers (2026-10-25): refusal attribution, operator ack, receipt truth.

Fixture-only: owned tmp state roots, no crontab/systemd command, provider, DB or Telegram call.
COVERS = ["scripts/cron_outage_watchdog.py", "scripts/lib/cron_outage_watchdog.py"]
"""
from datetime import datetime
import json
import os
import sys

import pytest

from scripts import cron_outage_watchdog as watchdog
from scripts.lib.cron_outage_watchdog import evaluate, job_key, recurring_jobs

NOW = datetime.fromisoformat("2026-10-24T23:18:13-04:00")


def lane(**changes):
    value = {"lane_id": "options-tick", "state": "ACTIVE", "expected_cadence_hours": 0.25,
             "scheduler": {"kind": "cron", "expression": "7,22,37,52 * * * *", "match": "scripts/options_tick.py"},
             "output_signal": {"kind": "file_mtime", "path": "data/runtime/options_tick_last.json"}}
    value.update(changes)
    return value


def refused(job="rl3", key="safe_flock:2817912-1792876677401655717:refused", at="2026-10-24T21:17:57.487877+00:00"):
    return {"event_type": "refused", "job_id": job, "component": job, "wrapper": "safe_flock",
            "reason": "log_path_preflight_refused", "mode": "business", "event_id": key, "exit_code": 1, "ts": at}


def completed(job, at):
    return {"component": job, "job_id": job, "event_type": "completed", "exit_code": 0, "mode": "business", "ts": at}


def assess(events, **options):
    return evaluate({"lanes": [lane()]}, events, {}, now=NOW, trading_day=lambda at: True, **options)


def test_unregistered_one_off_refusal_is_listed_but_never_alerts_or_crits():
    result = assess([refused()], registered_jobs={"tradeai_incident_notifier"})
    assert result["refusals"] == [] and result["alert_required"] is False and result["status"] != "CRIT"
    assert [(r["job_id"], r["attribution"]) for r in result["unattributed_refusals"]] == [("rl3", "unattributed")]


def test_registered_refusal_still_alerts_and_crits():
    result = assess([refused(job="tradeai_incident_notifier", key="k1")], registered_jobs={"tradeai_incident_notifier"})
    assert result["status"] == "CRIT" and result["alert_required"] is True
    assert result["refusals"][0]["attribution"] == "registered"


def test_unknown_census_fails_toward_alerting():
    result = assess([refused()], registered_jobs=None)
    assert result["status"] == "CRIT" and result["refusals"][0]["attribution"] == "registration_census_unavailable"


def test_recurring_business_history_attributes_a_nested_job_but_one_off_proofs_do_not():
    history = [completed("drive_sync", "2026-10-24T20:05:01-04:00"), completed("drive_sync", "2026-10-24T21:05:01-04:00"),
               completed("rl2", "2026-10-24T17:17:57-04:00")]
    assert recurring_jobs(history, now=NOW) == {"drive_sync"}
    result = assess(history + [refused(job="drive_sync", key="k2", at="2026-10-24T22:05:01-04:00"), refused()],
                    registered_jobs=set())
    assert [r["job_id"] for r in result["refusals"]] == ["drive_sync"]
    assert [r["job_id"] for r in result["unattributed_refusals"]] == ["rl3"]


def test_acknowledged_refusal_is_kept_visible_but_not_active():
    key = "safe_flock:x:refused"
    ack = {key: {"key": key, "acknowledged_by": "operator", "acknowledged_at": "2026-10-25T03:00:00Z", "reason": "proof run"}}
    result = assess([refused(job="tradeai_incident_notifier", key=key)], registered_jobs={"tradeai_incident_notifier"},
                    acknowledged=ack)
    assert result["status"] != "CRIT" and result["alert_required"] is False and result["refusals"] == []
    row = result["acknowledged_refusals"][0]
    assert row["acknowledged_by"] == "operator" and row["still_active_unrecovered"] is True


def test_job_census_reads_active_crontab_locks_dryrun_suffix_and_cron_wrapper_names():
    text = ("*/5 * * * * bash $PROJ/scripts/safe_flock.sh /tmp/tradeai_incident_notifier.lock timeout 120 x\n"
            "5 * * * * bash scripts/cron_wrapper.sh nightly_pipeline python x.py\n")
    jobs = watchdog.job_census([text, '{"argv": ["bash", "scripts/safe_flock.sh", "/tmp/hermes_event_feeder.lock.dryrun"]}'])
    assert {"tradeai_incident_notifier", "nightly_pipeline", "hermes_event_feeder"} <= jobs
    assert job_key("/tmp/x/hermes_event_feeder.lock.dryrun") == "hermes_event_feeder"


def test_registered_jobs_ignores_commented_crontab_lines_and_reports_missing_snapshot(tmp_path):
    jobs, gaps = watchdog.registered_jobs(tmp_path, root=tmp_path)
    assert jobs is None and gaps == ["crontab_snapshot_unavailable"]
    snap = tmp_path / watchdog.CRONTAB_SNAPSHOT
    snap.parent.mkdir(parents=True)
    snap.write_text("# RETIRED * * * * * safe_flock.sh /tmp/retired_job.lock x\n* * * * * safe_flock.sh /tmp/live_job.lock x\n")
    jobs, gaps = watchdog.registered_jobs(tmp_path, root=tmp_path)
    assert "live_job" in jobs and "retired_job" not in jobs and gaps == []


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) if not isinstance(value, str) else value)


def test_collect_counts_only_explicit_ok_receipts_and_skips_inactive_lane_gaps(tmp_path):
    write(tmp_path / "logs/safe_flock_events.jsonl", "")
    write(tmp_path / watchdog.CRONTAB_SNAPSHOT, "")
    write(tmp_path / "data/runtime/options_tick_last.json", {"ok": True, "mode": "apply", "ended_at": "2026-10-25T03:22:03Z"})
    write(tmp_path / "data/runtime/fanin_last.json", {"ok": False, "mode": "apply", "as_of": "2026-10-25T03:22:03Z"})
    write(tmp_path / "data/runtime/consult.json", {"as_of": "2026-10-25T03:22:03Z"})
    rows = [lane(),
            lane(lane_id="fanin", output_signal={"kind": "file_mtime", "path": "data/runtime/fanin_last.json"}),
            lane(lane_id="consult", output_signal={"kind": "json_key", "path": "data/runtime/consult.json", "key": "as_of"}),
            lane(lane_id="paused", state="PAUSED", output_signal={"kind": "json_key", "path": "data/runtime/none.json", "key": "ok_at"}),
            lane(lane_id="retired", state="RETIRED", output_signal={"kind": "file_mtime", "path": "logs/gone.log"}),
            lane(lane_id="active-missing", output_signal={"kind": "json_key", "path": "data/runtime/none.json", "key": "ok_at"})]
    result = watchdog.collect({"lanes": rows}, tmp_path)
    assert result["successes"] == {"options-tick": [{"at": "2026-10-25T03:22:03Z", "validated_success": True, "source": "ended_at+ok"}]}
    assert result["collection_gaps"] == ["active-missing:receipt_unavailable"]


def test_advisory_lane_without_a_receipt_is_expected_not_a_gap(tmp_path):
    """A lane whose own declaration says it writes no live receipt is coverage, never a gap (2026-11-01)."""
    write(tmp_path / "logs/safe_flock_events.jsonl", "")
    write(tmp_path / watchdog.CRONTAB_SNAPSHOT, "")
    rows = [lane(lane_id="dry", dispatch={"mode": "dry_run"},
                 output_signal={"kind": "json_key", "path": "data/runtime/dry.json", "key": "ok_at"}),
            lane(lane_id="shadow",
                 scheduler={"kind": "n8n", "expression": "dispatcher", "cadence": "0 * * * *", "stage": "shadow"},
                 output_signal={"kind": "json_key", "path": "data/runtime/shadow.json", "key": "ok_at"}),
            lane(lane_id="live", dispatch={"mode": "live"},
                 output_signal={"kind": "json_key", "path": "data/runtime/live.json", "key": "ok_at"})]
    result = watchdog.collect({"lanes": rows}, tmp_path)
    assert result["collection_gaps"] == ["live:receipt_unavailable"]
    assert result["expected_absent_receipts"] == [{"lane_id": "dry", "mode": "dry_run"},
                                                  {"lane_id": "shadow", "mode": "shadow"}]


def test_live_dispatch_wins_over_a_shadow_stage(tmp_path):
    """An explicit live dispatch must still write its receipt; stage alone cannot excuse the gap."""
    write(tmp_path / "logs/safe_flock_events.jsonl", "")
    write(tmp_path / watchdog.CRONTAB_SNAPSHOT, "")
    row = lane(lane_id="live-shadow", dispatch={"mode": "live"},
               scheduler={"kind": "n8n", "expression": "dispatcher", "cadence": "0 * * * *", "stage": "shadow"},
               output_signal={"kind": "json_key", "path": "data/runtime/x.json", "key": "ok_at"})
    result = watchdog.collect({"lanes": [row]}, tmp_path)
    assert result["collection_gaps"] == ["live-shadow:receipt_unavailable"]
    assert result["expected_absent_receipts"] == []


def test_advisory_lane_still_counts_a_receipt_that_does_exist(tmp_path):
    """Suppression is about a missing receipt, never about ignoring one that is present."""
    write(tmp_path / "logs/safe_flock_events.jsonl", "")
    write(tmp_path / watchdog.CRONTAB_SNAPSHOT, "")
    write(tmp_path / "data/runtime/dry.json", {"ok_at": "2026-10-25T03:22:03Z"})
    row = lane(lane_id="dry", dispatch={"mode": "dry_run"},
               output_signal={"kind": "json_key", "path": "data/runtime/dry.json", "key": "ok_at"})
    result = watchdog.collect({"lanes": [row]}, tmp_path)
    assert result["collection_gaps"] == []
    assert result["successes"]["dry"][0]["source"] == "ok_at"


def test_receipt_success_rules():
    assert watchdog.receipt_success({"ok_at": "2026-10-25T03:00:00Z"}, "ok_at")[1] == "ok_at"
    assert watchdog.receipt_success({"finished_at": "2026-10-25T03:00:00Z", "state": "RUN_DONE", "exit_code": 0}, "finished_at")
    assert watchdog.receipt_success({"as_of": "2026-10-25T03:00:00Z", "ok": "true"}, "as_of") is None  # string is not explicit
    assert watchdog.receipt_success({"as_of": "2026-10-25T03:00:00Z", "ok": True, "dry_run": True}, None) is None
    assert watchdog.receipt_success({"generated_at": "2026-10-25T03:00:00Z", "ok": True}, None) is None


@pytest.mark.parametrize("scheduler", [{"kind": "none", "expression": "on-demand:x"},
                                       {"kind": "event", "expression": "openclaw-cron:x", "cadence": "at 2026-10-20T14:00:00Z"},
                                       {"kind": "cron", "expression": "@reboot"}])
def test_lanes_without_a_wall_schedule_are_not_applicable_not_gaps(scheduler):
    result = evaluate({"lanes": [lane(scheduler=scheduler)]}, [], {}, now=NOW, trading_day=lambda at: True)
    assert result["rows"][0]["status"] == "NOT_APPLICABLE"
    assert result["coverage_gap_lane_ids"] == [] and result["not_applicable_lane_ids"] == ["options-tick"]


def test_systemd_timer_stays_a_visible_coverage_gap():
    result = evaluate({"lanes": [lane(scheduler={"kind": "systemd", "expression": "x.timer"})]}, [], {}, now=NOW)
    assert result["coverage_gap_lane_ids"] == ["options-tick"]


def _ack_world(tmp_path, monkeypatch, *extra):
    state = tmp_path / "state"
    write(state / "logs/safe_flock_events.jsonl", json.dumps(refused()) + "\n")
    os.chmod(state / "logs/safe_flock_events.jsonl", 0o600)
    write(state / watchdog.CRONTAB_SNAPSHOT, "")
    reg = tmp_path / "registry.json"
    write(reg, {"lanes": []})
    monkeypatch.setattr(sys, "argv", ["watchdog", "--registry", str(reg), "--state-root", str(state), *extra])
    return state


def test_ack_previews_by_default_and_never_edits_the_journal(tmp_path, monkeypatch, capsys):
    state = _ack_world(tmp_path, monkeypatch, "--ack-refusal", refused()["event_id"], "--ack-by", "operator",
                       "--ack-reason", "agent real-layout proof")
    journal = (state / "logs/safe_flock_events.jsonl").read_bytes()
    assert watchdog.main() == 0
    assert json.loads(capsys.readouterr().out)["mode"] == "preview"
    assert not (state / watchdog.ACKS).exists()
    assert (state / "logs/safe_flock_events.jsonl").read_bytes() == journal


def test_ack_apply_appends_and_the_next_dry_run_is_not_crit(tmp_path, monkeypatch, capsys):
    state = _ack_world(tmp_path, monkeypatch, "--ack-refusal", refused()["event_id"], "--ack-by", "operator",
                       "--ack-reason", "agent real-layout proof", "--apply-ack")
    assert watchdog.main() == 0
    acks, gaps = watchdog.read_acks(state)
    assert list(acks) == [refused()["event_id"]] and gaps == []
    capsys.readouterr()
    cfg = tmp_path / "cfg.json"
    write(cfg, {"enabled": False})
    monkeypatch.setattr(sys, "argv", ["watchdog", "--registry", str(tmp_path / "registry.json"), "--config", str(cfg),
                                     "--state-root", str(state), "--dry-run"])
    watchdog.main()
    report = json.loads(capsys.readouterr().out)
    assert report["refusals"] == [] and report["acknowledged_refusals"][0]["job_id"] == "rl3"


@pytest.mark.parametrize("extra", [["--ack-refusal", "not-a-key", "--ack-by", "op", "--ack-reason", "r"],
                                   ["--ack-refusal", "safe_flock:2817912-1792876677401655717:refused", "--ack-by", "op"]])
def test_ack_refuses_unknown_key_or_missing_reason(tmp_path, monkeypatch, extra):
    state = _ack_world(tmp_path, monkeypatch, *extra, "--apply-ack")
    assert watchdog.main() != 0
    assert not (state / watchdog.ACKS).exists()
