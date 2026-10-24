"""Fixture-only outage controls; no cron, systemd, provider, DB or Telegram calls."""
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import shlex

import pytest

from scripts.lib.cron_outage_watchdog import evaluate
from scripts.lib.release_wrapper_preflight import inspect, PROTOCOLS, receipt_check
from scripts.lib.wrapper_events import append_event
from scripts.check_shared_infra_pr import assess as metadata_gate
from scripts import cron_outage_watchdog as watchdog
from tests.support.real_release_layout import real_release_layout

ROOT = Path(__file__).resolve().parents[1]


def clock(value="2026-10-23T12:20:00-04:00"):
    return datetime.fromisoformat(value)


def lane(**changes):
    value = {"lane_id": "unified-stop-supervisor", "state": "ACTIVE", "expected_cadence_hours": 64.05,
             "scheduler": {"kind": "cron", "expression": "*/3 9-16 * * 1-5",
                           "command_text": "bash scripts/market_day_gate.sh bash scripts/safe_flock.sh /tmp/unified_stop_supervisor.lock true"},
             "output_signal": {"kind": "file_mtime", "path": "logs/job.log"}}
    value.update(changes)
    return value


def event(at="2026-10-23T12:06:02-04:00", **changes):
    value = {"component": "unified_stop_supervisor", "event_type": "completed", "exit_code": 0,
             "mode": "business", "ts": at}
    value.update(changes)
    return value


def assess(rows=None, events=None, **options):
    return evaluate({"lanes": rows or [lane()]}, events or [], {}, now=options.pop("now", clock()),
                    trading_day=options.pop("trading_day", lambda at: at.weekday() < 5), **options)


def test_stop_supervisor_uses_actual_three_minute_fires_not_weekend_gap():
    result = assess(events=[event()])
    assert result["alert_required"] is True
    assert result["missed_lane_ids"] == ["unified-stop-supervisor"]
    assert result["rows"][0]["missed_fires"] == 2
    assert result["rows"][0]["last_success_at"] == "2026-10-23T16:06:02Z"


@pytest.mark.parametrize("changes", [{"mode": "dry_run"}, {"mode": "preflight"},
    {"event_type": "started"}, {"event_type": "lock_skip"}, {"exit_code": 1},
    {"mode": None, "command": "python job.py --dry-run"}, {"mode": None}])
def test_non_success_cannot_mask_missed_runs(changes):
    result = assess(events=[event(), event("2026-10-23T12:18:30-04:00", **changes)])
    assert result["missed_lane_ids"] == ["unified-stop-supervisor"]


def test_future_success_cannot_be_backdated_into_historical_replay():
    result = assess(events=[event(), event("2026-10-24T12:18:30-04:00")])
    assert result["missed_lane_ids"] == ["unified-stop-supervisor"]


@pytest.mark.parametrize("now", ["2026-10-24T12:20:00-04:00", "2026-10-23T18:20:00-04:00",
                                 "2026-10-23T08:20:00-04:00"])
def test_no_new_missed_fire_alert_outside_schedule_window(now):
    result = assess(events=[event()], now=clock(now))
    assert result["rows"][0]["status"] == "OUTSIDE_WINDOW"
    assert result["alert_required"] is False


def test_market_holiday_is_not_an_expected_fire():
    result = assess(events=[event("2026-07-02T12:06:02-04:00")],
                    now=clock("2026-07-03T12:20:00-04:00"), trading_day=lambda at: at.date().isoformat() != "2026-07-03")
    assert result["rows"][0]["status"] == "OUTSIDE_WINDOW"


def test_two_daily_misses_are_detected_during_current_firing_hour():
    daily = lane(scheduler={"kind": "cron", "expression": "0 6 * * *", "command_text": "bash scripts/safe_flock.sh /tmp/unified_stop_supervisor.lock true"})
    result = assess([daily], [event("2026-10-21T06:01:00-04:00")], now=clock("2026-10-23T06:10:00-04:00"))
    assert result["missed_lane_ids"] == ["unified-stop-supervisor"]


def test_recent_success_has_no_missed_run_alert():
    result = assess(events=[event("2026-10-23T12:18:30-04:00")])
    assert result["rows"][0]["status"] == "OK"
    assert result["alert_required"] is False


def test_log_mtime_and_missing_success_are_explicit_coverage_gap():
    result = assess()
    assert result["rows"][0]["status"] == "NOT_MEASURED"
    assert result["rows"][0]["reason"] == "success_not_measured_file_mtime_is_not_success"
    assert result["rows"][0]["last_success_at"] is None


def test_disabled_lanes_are_not_in_enabled_population_and_unsupported_are_visible():
    rows = [lane(state="PAUSED"), lane(lane_id="timer", scheduler={"kind": "systemd", "expression": "timer.timer"})]
    result = assess(rows)
    assert [row["lane_id"] for row in result["rows"]] == ["timer"]
    assert result["coverage_gap_lane_ids"] == ["timer"]


def test_any_refusal_alerts_without_relying_on_job_cadence():
    refused = event(event_type="refused", event_id="refusal-1", reason="unsafe_path", job_id="job")
    result = assess(events=[refused])
    assert result["alert_required"] is True
    assert result["refusals"][0]["new"] is True
    replay = assess(events=[refused], previous_refusal_keys={"refusal-1"})
    assert replay["alert_required"] is False
    assert replay["status"] == "CRIT", "acknowledging delivery does not turn a refusal healthy"


def test_dst_fold_is_one_fire_and_spring_gap_follows_shared_schedule_contract():
    daily = lane(scheduler={"kind": "cron", "expression": "30 1 * * *", "command_text": "bash scripts/safe_flock.sh /tmp/unified_stop_supervisor.lock true"})
    result = assess([daily], [event("2026-11-01T01:31:00-04:00")], now=clock("2026-11-01T01:45:00-05:00"))
    assert result["rows"][0]["missed_fires"] == 0
    spring = lane(scheduler={"kind": "cron", "expression": "30 2 * * *", "command_text": "bash scripts/safe_flock.sh /tmp/unified_stop_supervisor.lock true"})
    result = assess([spring], [event("2026-03-08T03:01:00-04:00")], now=clock("2026-03-08T03:04:00-04:00"))
    assert result["alert_required"] is False


def test_naive_clock_is_never_silently_local():
    with pytest.raises(ValueError, match="aware"):
        assess(now=datetime(2026, 10, 23, 12, 20))


def test_real_layout_exercises_all_declared_generic_noop_protocols(tmp_path):
    layout = real_release_layout(tmp_path, ROOT)
    cron = "\n".join("* * * * * bash " + name for name in PROTOCOLS)
    result = inspect(layout.current, tmp_path / "scratch", cron)
    assert result["layout_issues"] == []
    assert result["ok"] is True, result
    assert {row["path"] for row in result["results"]} == set(PROTOCOLS)
    assert all(row["status"] == "PROVEN" for row in result["results"])
    events = [json.loads(line) for line in (layout.state / "logs/safe_flock_events.jsonl").read_text().splitlines()]
    assert events and all(item["mode"] == "preflight" for item in events)


def test_unknown_producer_never_invoked_and_probe_env_has_no_live_secrets(tmp_path, monkeypatch):
    layout = real_release_layout(tmp_path, ROOT)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fixture-must-not-be-inherited")
    monkeypatch.setenv("TRADEAI_EFFECT_CLAIM", "armed-fixture")
    calls = []
    def runner(argv, **kwargs):
        calls.append(argv)
        assert "TELEGRAM_BOT_TOKEN" not in kwargs["env"]
        assert "TRADEAI_EFFECT_CLAIM" not in kwargs["env"]
        assert "run_broker_fixture.sh" not in " ".join(argv)
        return SimpleNamespace(returncode=0, stdout="")
    result = inspect(layout.current, tmp_path / "scratch", "* * * * * bash scripts/run_broker_fixture.sh", runner=runner)
    assert result["ok"] is False
    assert result["coverage_gaps"] == ["scripts/run_broker_fixture.sh"]
    assert len(calls) == 1, "only the independently declared nested cron_wrapper no-op is invoked"


def test_flat_repo_is_not_real_layout_proof(tmp_path):
    layout = real_release_layout(tmp_path, ROOT)
    def runner(*args, **kwargs):
        pytest.fail("a flat layout must be rejected before executing any wrapper")
    result = inspect(layout.release, tmp_path / "scratch", "* * * * * bash scripts/safe_flock.sh", runner=runner)
    assert result["ok"] is False
    assert "CURRENT_not_symlink" in result["layout_issues"]


def test_unsafe_lock_refusal_is_journaled_without_touching_victim_or_running_child(tmp_path):
    layout = real_release_layout(tmp_path, ROOT)
    victim = tmp_path / "victim"
    victim.write_text("preserve")
    lock = layout.locks / "job.lock"
    lock.symlink_to(victim)
    ran = tmp_path / "ran"
    proc = subprocess.run(["bash", str(layout.current / "scripts/safe_flock.sh"), str(lock), "touch", str(ran)],
                          env={"PATH": os.defpath, "HOME": str(tmp_path), "PROJECT_ROOT": str(layout.current)},
                          text=True, capture_output=True, timeout=5)
    assert proc.returncode == 1
    assert victim.read_text() == "preserve"
    assert not ran.exists()
    rows = [json.loads(x) for x in (layout.state / "logs/safe_flock_events.jsonl").read_text().splitlines()]
    assert len(rows) == 1 and rows[0]["event_type"] == "refused"
    assert rows[0]["job_id"] == "job" and rows[0]["event_id"]


@pytest.mark.parametrize("failure", ["symlink", "permission"])
def test_refusal_journal_never_repairs_or_overrides_an_unsafe_sink(tmp_path, monkeypatch, failure):
    from scripts.lib import wrapper_events
    victim = tmp_path / "victim"
    victim.write_text("preserve")
    journal = tmp_path / "events.jsonl"
    if failure == "symlink":
        journal.symlink_to(victim)
    else:
        journal.write_text("original\n")
        def denied(*args, **kwargs):
            raise PermissionError("fixture immutable/permission refusal")
        monkeypatch.setattr(wrapper_events.os, "open", denied)
    assert append_event(journal, {"event_type": "refused"}) is False
    assert victim.read_text() == "preserve"
    if failure == "permission":
        assert journal.read_text() == "original\n"


@pytest.mark.parametrize("title,body", [("WP-33 ordinary", "Real-layout proof: isolated fixture command"),
                                       ("[shared-infra] WP-33 reliability", "Tests pass")])
def test_shared_infra_gate_requires_both_title_and_real_layout_reference(title, body):
    result = metadata_gate(["scripts/safe_flock.sh"], title, body, [])
    assert result["ok"] is False
    assert result["shared_infra"] is True


def test_shared_infra_list_cannot_be_removed_to_launder_its_own_change():
    result = metadata_gate(["config/shared_infra_paths.json"], "ordinary", "", [])
    assert result["ok"] is False
    assert metadata_gate(["scripts/safe_flock.sh"], "[shared-infra] WP-33 reliability",
                         "Real-layout proof: pytest -q tests/test_cron_outage_prevention_20261024.py", [])["ok"] is True


def test_failed_or_queued_alert_is_not_delivery_and_replay_is_suppressed_only_after_delivery():
    report = assess(events=[event(), event(event_type="refused", event_id="refusal-1")])
    calls = []
    def failed(body):
        calls.append(body)
        return {"accepted": True, "delivered": False, "status": "QUEUED"}
    outcome, state = watchdog.deliver(report, {}, sender=failed, now=clock())
    assert outcome["delivered"] is False and "delivered_refusal_keys" not in state and "last_delivered_at" not in state
    outcome, state = watchdog.deliver(report, state, sender=lambda body: {"accepted": True, "delivered": True, "status": "DELIVERED"}, now=clock())
    assert state["delivered_refusal_keys"] == ["refusal-1"]
    def must_not_repeat(body):
        pytest.fail("same delivered finding should not alert on each timer poll")
    outcome, _ = watchdog.deliver(report, state, sender=must_not_repeat, now=clock())
    assert outcome["status"] == "NOT_REQUIRED"


def test_collect_keeps_mtime_and_dry_run_receipts_out_of_success_population(tmp_path):
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs/safe_flock_events.jsonl").write_text("")
    (tmp_path / "data").mkdir()
    (tmp_path / "data/run.json").write_text(json.dumps({"ok_at": "2026-10-23T12:18:30-04:00", "mode": "dry_run"}))
    rows = [lane(), lane(lane_id="receipt", output_signal={"kind": "json_key", "path": "data/run.json", "key": "ok_at"})]
    result = watchdog.collect({"lanes": rows}, tmp_path)
    assert result["successes"] == {}
    (tmp_path / "data/run.json").write_text(json.dumps({"ok_at": "2026-10-23T12:18:30-04:00", "mode": "live"}))
    result = watchdog.collect({"lanes": rows}, tmp_path)
    assert list(result["successes"]) == ["receipt"]


@pytest.mark.parametrize("change", [{"release_sha": "wrong"}, {"admission": "INSPECTION_ONLY"},
                                   {"observed_at": "2026-10-22T12:20:00-04:00"}, {"config_sha256": "wrong"}])
def test_train_rejects_wrong_sha_stale_or_inspection_wrapper_receipt(tmp_path, change):
    release = tmp_path / "release"
    (release / "config").mkdir(parents=True)
    cfg = release / "config/release_wrapper_preflight.json"
    cfg.write_text(json.dumps({"enabled": True, "review_status": "REVIEWED", "approved_by": "synthetic-reviewer"}))
    proof = {"ok": True, "admission": "ENFORCED", "release_sha": "a" * 40, "release": str(release),
             "observed_at": "2026-10-23T12:20:00-04:00", "config_sha256": hashlib.sha256(cfg.read_bytes()).hexdigest()}
    receipt = tmp_path / "proof.json"
    receipt.write_text(json.dumps(proof))
    assert receipt_check(release, "a" * 40, receipt, clock())["ok"] is True
    receipt.write_text(json.dumps({**proof, **change}))
    assert receipt_check(release, "a" * 40, receipt, clock())["ok"] is False


@pytest.mark.parametrize("status", ["CRIT", "UNKNOWN", "OK"])
def test_health_page_projects_watchdog_finding_without_running_monitor(tmp_path, status):
    from scripts.lib import platform_health as health
    path = tmp_path / watchdog.LATEST
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"schema": "CronOutageWatchdog@v1", "mode": "monitor", "status": status,
                               "observed_at": "2026-10-23T12:20:00-04:00", "missed_lane_ids": [], "refusals": [],
                               "coverage_gap_lane_ids": []}))
    row = health.probe_wrapper_watchdog(health.Deps(state_root=tmp_path, now=clock))[0]
    assert row["status"] == status
    assert row["as_of"] == "2026-10-23T16:20:00Z"
    old = health.probe_wrapper_watchdog(health.Deps(state_root=tmp_path, now=lambda: clock("2026-10-23T12:24:00-04:00")))[0]
    assert old["status"] == "UNKNOWN" and old["as_of"] == row["as_of"]


def test_cron_wrapper_noop_does_not_reach_environment_loader(tmp_path):
    layout = real_release_layout(tmp_path, ROOT)
    (layout.release / ".env").write_text("FIXTURE_ENV_MARKER=unread\n")
    fakebin = tmp_path / "fakebin"
    fakebin.mkdir()
    marker = tmp_path / "environment_was_read"
    grep = fakebin / "grep"
    grep.write_text("#!/bin/sh\ntouch " + shlex.quote(str(marker)) + "\nexit 91\n")
    grep.chmod(0o700)
    proc = subprocess.run(["bash", str(layout.current / "scripts/cron_wrapper.sh"), "--wrapper-preflight", str(layout.current)],
                          env={"PATH": str(fakebin) + os.pathsep + os.defpath, "HOME": str(tmp_path)},
                          text=True, capture_output=True, timeout=5)
    assert proc.returncode == 0, proc.stderr
    assert not marker.exists()


def test_component_binding_is_exact_and_does_not_mutate_registry():
    row = lane(scheduler={"kind": "cron", "expression": "*/3 9-16 * * 1-5", "match": "scripts/fixture.py"})
    registry = {"lanes": [row]}
    cfg = {"wrapper_bindings": {row["lane_id"]: {"expression": row["scheduler"]["expression"],
             "scheduler_match": "scripts/fixture.py", "component": "unified_stop_supervisor"}}}
    bound = watchdog.bind_components(registry, cfg)
    assert bound["lanes"][0]["watchdog_wrapper_component"] == "unified_stop_supervisor"
    assert "watchdog_wrapper_component" not in row
    row["scheduler"]["match"] = "scripts/different.py"
    assert "watchdog_wrapper_component" not in watchdog.bind_components(registry, cfg)["lanes"][0]


def test_native_monitor_writes_health_and_direct_chokepoint_delivery_with_replay_safe_identity(tmp_path, monkeypatch, capsys):
    """Actual main path with only owned files and a fake gateway, not a pure-shape test."""
    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock()
    monkeypatch.setattr(watchdog, "datetime", Frozen)
    cfg = tmp_path / "cfg.json"
    cfg.write_text(json.dumps({"enabled": True, "review_status": "REVIEWED", "approved_by": "synthetic-fixture-review"}))
    reg = tmp_path / "registry.json"
    reg.write_text(json.dumps({"lanes": [lane()]}))
    snapshot = tmp_path / "snapshot.json"
    payload = {"events": [event(), event(event_type="refused", event_id="runA:refused", job_id="job")], "successes": {}}
    snapshot.write_text(json.dumps(payload))
    sent = []
    def sender(body, **kwargs):
        assert kwargs["priority"] == "P1" and kwargs["dedupe_minutes"] == 0
        sent.append(body)
        return {"accepted": True, "delivered": True, "status": "DELIVERED"}
    monkeypatch.setitem(sys.modules, "telegram_alert", SimpleNamespace(send_telegram_outcome=sender))
    monkeypatch.setattr(sys, "argv", ["watchdog", "--registry", str(reg), "--config", str(cfg), "--snapshot", str(snapshot),
                                     "--state-root", str(tmp_path / "state"), "--run", "--send-alerts"])
    assert watchdog.main() == 1
    first = watchdog.read_json(tmp_path / "state" / watchdog.LATEST)
    assert first["notification"]["delivered"] is True
    assert watchdog.main() == 1 and len(sent) == 1
    payload["events"].append(event(event_type="refused", event_id="runB:refused", job_id="job"))
    snapshot.write_text(json.dumps(payload))
    assert watchdog.main() == 1 and len(sent) == 2
    state = watchdog.read_json(tmp_path / "state" / watchdog.STATE)
    assert state["delivered_refusal_keys"] == ["runA:refused", "runB:refused"]
    assert first["mode"] == "monitor"


def test_disabled_native_admission_has_zero_writes_and_sends(tmp_path, monkeypatch):
    cfg = tmp_path / "cfg.json"
    cfg.write_text(json.dumps({"enabled": False}))
    monkeypatch.setattr(sys, "argv", ["watchdog", "--config", str(cfg), "--state-root", str(tmp_path / "state"), "--run", "--send-alerts"])
    assert watchdog.main() == 78
    assert not (tmp_path / "state").exists()


def test_actual_promote_functions_rollback_and_request_direct_alert_after_noop_failure(tmp_path):
    """Extracted functions run only against owned fake release/state/interpreter paths."""
    layout = real_release_layout(tmp_path, ROOT)
    previous = tmp_path / "previous"
    previous.mkdir()
    (previous / "BUILD_SHA").write_text("b" * 40)
    (layout.release / "BUILD_SHA").write_text("a" * 40)
    (layout.release / "config").mkdir()
    (layout.release / "config/release_wrapper_preflight.json").write_text('{"enabled":true}')
    trace = tmp_path / "calls.txt"
    fakepy = tmp_path / "fake-python"
    fakepy.write_text("""#!/bin/sh
if [ "$1" = "-" ]; then cat >/dev/null; echo enabled; exit 0; fi
for arg in "$@"; do
  if [ "$arg" = "--enforce" ]; then echo probe_failed >>"$FIXTURE_TRACE"; exit 1; fi
  if [ "$arg" = "--notify-failure" ]; then echo direct_alert_requested >>"$FIXTURE_TRACE"; exit 0; fi
done
exit 0
""")
    fakepy.chmod(0o700)
    source = (ROOT / "scripts/cio_phase2_exact_main_deploy.sh").read_text()
    def function(name):
        start = source.index(name + "() {\n")
        return source[start:source.index("\n}\n", start) + 3]
    harness = tmp_path / "harness.sh"
    harness.write_text("""set -euo pipefail
load_state() { :; }
current_release() { printf '%s' "$FIXTURE_PREVIOUS"; }
require_canonical_source_at() { :; }
release_grant_preflight() { :; }
conformance_gate() { :; }
release_pin_step() { echo "pin:$1" >>"$FIXTURE_TRACE"; }
write_state() { :; }
activate_release() { echo "activate:$1" >>"$FIXTURE_TRACE"; }
health_check() { echo "health:$1" >>"$FIXTURE_TRACE"; return 0; }
write_deploy_receipt() { echo "receipt:$*" >>"$FIXTURE_TRACE"; }
log() { echo "$*" >>"$FIXTURE_TRACE"; }
die() { echo "$*" >>"$FIXTURE_TRACE"; exit 1; }
restart_root_frozen_units() { echo forbidden_restart >>"$FIXTURE_TRACE"; }
write_expected_release_pin() { echo forbidden_pin >>"$FIXTURE_TRACE"; }
worker_pin_check() { :; }
ff_dev_tree_after_promote() { :; }
""" + function("wrapper_preflight_after_promote") + "\n" + function("cmd_promote") + '\ncmd_promote "$FIXTURE_CANDIDATE"\n')
    env = {"PATH": os.defpath, "HOME": str(tmp_path), "FIXTURE_TRACE": str(trace),
           "FIXTURE_PREVIOUS": str(previous), "FIXTURE_CANDIDATE": str(layout.release),
           "VENV_PYTHON": str(fakepy), "RELEASES_BASE": str(tmp_path), "ROOT": str(tmp_path),
           "CI_RECEIPT_FILE": str(tmp_path / "ci.json"), "STATE_DIR": str(tmp_path), "EMERGENCY_SHA": ""}
    proc = subprocess.run(["bash", str(harness)], env=env, text=True, capture_output=True, timeout=5)
    assert proc.returncode == 1, proc.stderr
    calls = trace.read_text().splitlines()
    assert calls.index("probe_failed") < calls.index("direct_alert_requested") < calls.index("activate:" + str(previous))
    assert any(line.startswith("receipt:false promote timeout true rolled_back_to_prev") for line in calls)
    assert not any("PROMOTE OK live=" in line or "pin:apply" == line or line.startswith("forbidden_") for line in calls)


def test_release_failure_notification_uses_existing_p1_chokepoint_only(tmp_path, monkeypatch, capsys):
    from scripts import release_wrapper_preflight as preflight
    calls = []
    def gateway(body, **kwargs):
        calls.append(kwargs)
        return {"accepted": True, "delivered": True, "status": "DELIVERED"}
    monkeypatch.setitem(sys.modules, "telegram_alert", SimpleNamespace(send_telegram_outcome=gateway))
    monkeypatch.setattr(sys, "argv", ["preflight", "--current", str(tmp_path), "--notify-failure", "wrapper_preflight_failed"])
    assert preflight.main() == 0
    assert calls == [{"priority": "P1", "dedupe_minutes": 0, "producer": "release_wrapper_preflight", "message_class": "operator_alert"}]


def test_unsafe_journal_refusal_reaches_monitor_via_explicit_timestamped_original_stderr(tmp_path):
    layout = real_release_layout(tmp_path, ROOT)
    victim = tmp_path / "journal-victim"
    victim.write_text("preserve")
    journal = layout.state / "logs/safe_flock_events.jsonl"
    journal.symlink_to(victim)
    proc = subprocess.run(["bash", str(layout.current / "scripts/safe_flock.sh"), str(layout.locks / "job.lock"), "true"],
                          env={"PATH": os.defpath, "HOME": str(tmp_path), "PROJECT_ROOT": str(layout.current)},
                          text=True, capture_output=True, timeout=5)
    assert proc.returncode == 1 and victim.read_text() == "preserve"
    (layout.state / "logs/job.log").write_text(proc.stderr)
    data = watchdog.collect({"lanes": [lane()]}, layout.state)
    captured = [x for x in data["events"] if x.get("journal_fallback") == "stderr"]
    assert len(captured) == 1 and captured[0]["event_id"]
    at = datetime.fromisoformat(captured[0]["ts"])
    result = assess(events=captured, now=at)
    assert result["alert_required"] is True
    assert result["refusals"][0]["job_id"] == "job"


def test_refusal_recovers_only_after_same_component_business_completion():
    result = assess(events=[event(event_type="refused", event_id="r"), event("2026-10-23T12:18:30-04:00")])
    assert result["refusals"][0]["active"] is False
    assert result["status"] == "OK"
    assert result["alert_required"] is True, "new refusal is still delivered even if recovery happened before the next poll"


def test_healthy_transition_rearms_same_named_future_missed_condition():
    broken = assess(events=[event()])
    _, prior = watchdog.deliver(broken, {}, sender=lambda body: {"status": "DELIVERED", "delivered": True}, now=clock())
    healthy = assess(events=[event("2026-10-23T12:18:30-04:00")])
    _, reset = watchdog.deliver(healthy, prior, sender=lambda body: pytest.fail("healthy must not send"), now=clock())
    calls = []
    outcome, _ = watchdog.deliver(broken, reset, sender=lambda body: calls.append(body) or {"status": "DELIVERED", "delivered": True}, now=clock())
    assert len(calls) == 1 and outcome["delivered"] is True


def test_journal_blindness_is_an_independent_incident_and_recovery_keeps_history_unmeasured(tmp_path):
    registry = {"lanes": [lane()]}
    snapshot = watchdog.collect(registry, tmp_path)
    report = evaluate(registry, snapshot["events"], snapshot["successes"], now=clock(), trading_day=lambda at: True)
    report = watchdog.monitor_findings(report, snapshot)
    assert report["monitor_incidents"][0]["kind"] == "MONITOR_BLINDNESS"
    assert report["rows"][0]["last_success_at"] is None and report["rows"][0]["missed_fires"] is None
    assert report["missed_lane_ids"] == [] and report["alert_required"] is True
    sent = []
    def sender(body):
        sent.append(body)
        return {"status": "DELIVERED", "delivered": True}
    outcome, state = watchdog.deliver(report, {}, sender=sender, now=clock())
    assert outcome["kind"] == "WATCHDOG_FINDING" and "wrapper_journal_unavailable" in sent[-1]
    outcome, state = watchdog.deliver(report, state, sender=sender, now=clock())
    assert outcome["status"] == "NOT_REQUIRED" and len(sent) == 1
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs/safe_flock_events.jsonl").write_text("")
    snapshot = watchdog.collect(registry, tmp_path)
    recovered = watchdog.monitor_findings(evaluate(registry, [], {}, now=clock(), trading_day=lambda at: True), snapshot)
    assert recovered["monitor_incidents"] == [] and recovered["rows"][0]["status"] == "NOT_MEASURED"
    outcome, state = watchdog.deliver(recovered, state, sender=sender, now=clock())
    assert outcome["kind"] == "MONITOR_RECOVERED" and "MONITOR COVERAGE RESTORED" in sent[-1]
    assert state["active_monitor_incidents"] == [] and "pending_monitor_recovery" not in state


def test_same_refusal_in_journal_and_stderr_is_one_event():
    refused = event(event_type="refused", event_id="one-stable-event")
    result = assess(events=[refused, {**refused, "journal_fallback": "stderr"}])
    assert len(result["refusals"]) == 1


def test_refusal_never_executes_a_helper_from_caller_selected_project_root(tmp_path):
    layout = real_release_layout(tmp_path, ROOT)
    untrusted = tmp_path / "caller-root"
    (untrusted / "scripts/lib").mkdir(parents=True)
    marker = tmp_path / "untrusted-helper-ran"
    (untrusted / "scripts/lib/wrapper_events.py").write_text("from pathlib import Path\nPath(" + repr(str(marker)) + ").write_text('bad')\n")
    (untrusted / "logs").mkdir()
    unsafe = tmp_path / "unsafe-log-link"
    unsafe.symlink_to(untrusted / "logs")
    proc = subprocess.run(["bash", str(layout.current / "scripts/safe_flock.sh"), str(layout.locks / "job.lock"), "true"],
                          env={"PATH": os.defpath, "HOME": str(tmp_path), "PROJECT_ROOT": str(untrusted),
                               "SAFE_FLOCK_LOG_DIR": str(unsafe)}, text=True, capture_output=True, timeout=5)
    assert proc.returncode == 1
    assert not marker.exists()
