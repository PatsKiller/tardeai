"""Watcher identity and notification evidence, with no sender or host reads."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

SPEC = importlib.util.spec_from_file_location("jobs_health_watcher_runtime_under_test",
                                            Path(__file__).resolve().parents[1] / "scripts/lib/jobs_health.py")
J = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = J
SPEC.loader.exec_module(J)
NOW = datetime(2026, 11, 2, 18, 30, tzinfo=timezone.utc)
STAMP = "2026-11-02T18:20:00Z"


def lights(rows=(), runtime=None, status="OK"):
    monitor = {"status": status, "observed_at": STAMP, "cause": None}
    return {x["id"]: x for x in J._watchers({}, list(rows), monitor, True, runtime=runtime, now=NOW)}


def test_event_pager_is_not_misrepresented_as_missing_cron():
    runtime = {"pager": {"implementation_present": True, "source": "fixture",
                        "receipt": {"schema": "DeliveryFailureAlert@v1", "as_of": STAMP,
                                    "accepted": True, "delivered": False, "delivery_status": "ROUTED"}}}
    light = lights(runtime=runtime)["delivery-failure-alerts"]
    assert light["status"] == "degraded"
    assert light["component_kind"] == "event_handler"
    assert light["display_status"] == "Event-driven · last delivery unconfirmed"
    assert light["last_delivery_observed"] is False
    assert light["as_of"] == STAMP


def test_a_delivery_receipt_needs_transport_confirmation():
    proof = {"schema": "DeliveryFailureAlert@v1", "as_of": STAMP, "delivered": True}
    runtime = {"pager": {"implementation_present": True, "receipt": proof}}
    assert lights(runtime=runtime)["delivery-failure-alerts"]["status"] == "degraded"
    proof["delivery_status"] = "DELIVERED"
    assert lights(runtime=runtime)["delivery-failure-alerts"]["status"] == "ok"


def test_dry_run_future_or_wrong_schema_is_not_a_live_delivery():
    for overrides in ({"mode": "dry_run"}, {"mode": "dry-run"}, {"dry_run": True}, {"as_of": "2026-11-03T00:00:00Z"}, {"schema": "Other@v1"}):
        proof = {"schema": "DeliveryFailureAlert@v1", "as_of": STAMP,
                 "delivered": True, "delivery_status": "DELIVERED", **overrides}
        row = lights(runtime={"pager": {"implementation_present": True, "receipt": proof}})["delivery-failure-alerts"]
        assert row["status"] == "degraded"
        assert row["runtime_observed"] is False


def test_digest_replaces_retired_per_pr_timer_and_exposes_registry_drift():
    rows = [{"lane_id": name, "state": "NEVER_SCHEDULED", "result": "unknown", "cause": "fixture"}
            for name in ["pr-merge-telegram-notify", "pr-merge-digest"]]
    runtime = {"merge_digest": {"source": "fixture", "receipt": {"at": STAMP, "apply": True, "ok": True}}}
    got = lights(rows, runtime)
    assert "pr-merge-telegram-notify" not in got
    assert got["pr-merge-digest"]["display_status"] == "Registry/runtime drift"
    assert got["pr-merge-digest"]["status"] == "degraded"
    assert "do not install a second timer" in got["pr-merge-digest"]["cause"]


def test_future_apply_receipt_does_not_prove_installation():
    rows = [{"lane_id": "pr-merge-digest", "state": "NEVER_SCHEDULED", "result": "unknown", "cause": "fixture"}]
    row = lights(rows, {"merge_digest": {"receipt": {"at": "2026-11-03T00:00:00Z", "apply": True, "ok": True}}})["pr-merge-digest"]
    assert row["display_status"] == "Schedule not verified"


def test_expected_next_run_is_not_success():
    row = {"lane_id": "self-heal-fixer", "state": "ACTIVE", "result": "due", "cause": "No completion"}
    assert lights([row])["self-heal-fixer"]["status"] == "degraded"


def test_self_heal_keeps_the_disarmed_receipt_clock():
    row = lights(runtime={"self_heal": {"receipt": {"schema": "SelfHealFixerReceipt@v1",
                 "finished_at": STAMP, "arming": {"armed": False, "why": "fixture grant absent"},
                 "policy": {"why": "fixture capability absent"}, "counts": {"fix_requested": 5}}}})["self-heal-fixer"]
    assert row["display_status"] == "Disarmed at last run"
    assert row["pending_requests"] == 5
    assert row["as_of"] == STAMP


def test_fresh_critical_monitor_is_not_a_green_platform_status():
    got = lights(status="CRIT")["missed-run-watchdog"]
    assert got["status"] == "degraded"
    assert got["display_status"] == "Watching · critical findings"
    assert got["incident_status"] == "CRIT"


def test_repeat_suppression_is_not_no_incident_or_a_delivery_this_poll():
    watchdog = {"status": "CRIT", "alert_required": True, "notification": {"status": "NOT_REQUIRED", "delivered": False}}
    key = hashlib.sha256(json.dumps({"missed": [], "monitor": []}, sort_keys=True).encode()).hexdigest()
    runtime = {"watchdog_state": {"last_delivered_at": STAMP, "finding_key": key}, "reminder_seconds": 1800}
    got = J._notification_view(watchdog, runtime, NOW)
    assert got["delivered"] is False
    assert got["incident_alert_required"] is True
    assert got["last_delivered_at"] == STAMP
    assert got["next_reminder_at"] == "2026-11-02T18:50:00Z"
    assert got["suppression_reason"] == "reminder_not_due"
    assert "incident remains CRIT" in got["summary"]


def test_different_finding_history_is_not_claimed_as_repeat_suppression():
    got = J._notification_view({"status": "CRIT", "alert_required": True,
                               "missed_lane_ids": ["fixture-new"],
                               "notification": {"status": "NOT_REQUIRED"}},
                              {"watchdog_state": {"last_delivered_at": STAMP, "finding_key": "different"}}, NOW)
    assert "suppression_reason" not in got
    assert "Repeat suppressed" not in got["summary"]


def test_fresh_unknown_coverage_does_not_become_green():
    row = lights(status="UNKNOWN")["missed-run-watchdog"]
    assert row["status"] == "degraded"
    assert row["display_status"] == "Watching · coverage not established"


def test_missing_or_future_delivery_history_stays_unknown():
    for state in ({}, {"last_delivered_at": "2026-11-03T00:00:00Z"}):
        got = J._notification_view({"status": "CRIT", "alert_required": True,
                                   "notification": {"status": "NOT_REQUIRED"}}, {"watchdog_state": state}, NOW)
        assert got["last_delivered_at"] is None
        assert "Previous delivery is not measured" in got["summary"]


def test_disabled_and_service_populations_do_not_invent_schedules():
    def lane(name, kind, expr, state="ACTIVE"):
        return {"lane_id": name, "state": state, "scheduler": {"kind": kind, "expression": expr},
                "expected_cadence_hours": 1}
    lanes = [lane("fixture-cron", "cron", "0 * * * *"),
             lane("fixture-never", "cron", "0 * * * *", "NEVER_SCHEDULED"),
             lane("fixture-service", "systemd", "fixture.service"),
             lane("fixture-event", "event", "")]
    out = J.build({"lanes": lanes}, {"events": [], "successes": {}}, [], {}, now=NOW, trading_day=lambda _: True)
    rows = {x["lane_id"]: x for x in out["rows"]}
    assert rows["fixture-never"]["result"] == "paused"
    assert rows["fixture-never"]["next_due_at"] is None
    assert rows["fixture-service"]["result"] == "unknown"
    assert rows["fixture-service"]["execution_population"] == "continuous_service"
    assert rows["fixture-event"]["execution_population"] == "event_driven"
    assert out["summary"]["not_scheduled"] == 1
    assert out["summary"]["registered_total"] == 4
    assert out["summary"]["due_today"] == 1
    assert out["summary"]["unknown"] == 3


def test_a_failed_run_exposes_real_diagnostics_in_the_operator_projection():
    lane = {"lane_id": "fixture-job", "state": "ACTIVE", "scheduler": {"kind": "n8n", "cadence": "0 * * * *"},
            "expected_cadence_hours": 1}
    trace = "Traceback (most recent call last):\n  File 'fixture.py', line 1\nValueError: synthetic failure"
    run = {"run_id": "fixture-run", "lane_id": "fixture-job", "mode": "live", "state": "RUN_FAILED",
           "requested_at": "2026-11-02T18:19:00Z", "started_at": "2026-11-02T18:19:00Z",
           "finished_at": STAMP, "exit_code": 1,
           "receipt": {"run_id": "fixture-run", "lane_id": "fixture-job", "mode": "live",
                       "stderr_tail": trace, "exit_code": 1}}
    out = J.build({"lanes": [lane]}, {"events": [], "successes": {}}, [run], {}, now=NOW, trading_day=lambda _: True)
    row = out["rows"][0]
    assert row["result"] == "failed"
    d = row["diagnostics"]
    assert d["schema"] == "JobFailureDiagnostics@v1"
    assert d["exception_type"] == "ValueError"
    assert d["traceback"]["available"] is True
    assert d["execution"]["exit_code"] == 1
    assert d["execution"]["duration_s"] == 60
    assert d["execution"]["host_role"] == "n8n_executor"
    assert d["remediation"]["suggestion"]
