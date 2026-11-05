"""Jobs & health watcher stoplight strip (operator 2026-10-28: "a mode in the command center that
shows stoplights when these along with the alerts").

The four operations watchers — missed-run watchdog, self-heal fixer, merge notifier, failure pager —
render honestly: absent or unwired is red/amber, never silently green. This is the same
"a component reporting success is not evidence" rule as the execution rows; an unregistered pager
must show red, not disappear.
"""
from __future__ import annotations

from datetime import datetime, timezone

from scripts.lib import jobs_health as J

NOW = datetime(2026, 10, 28, 16, 0, tzinfo=timezone.utc)


def lane(name: str, state: str = "ACTIVE", **extra) -> dict:
    return {"lane_id": name, "state": state, "expected_cadence_hours": 1 / 12,
            "scheduler": {"kind": "cron", "expression": "*/5 9-16 * * 1-5"},
            "output_signal": {"kind": "file_mtime", "path": "logs/job.log"}, **extra}


def _row(name: str, state: str, result: str) -> dict:
    return {"lane_id": name, "state": state, "result": result,
            "cause": "Job is paused" if state == "PAUSED" else "Successful execution is not yet measured"}


def _watchers(lanes, *, monitor_ok: bool, rows=None):
    monitor = {"status": "OK" if monitor_ok else "UNKNOWN",
               "cause": None if monitor_ok else "Independent monitor receipt missing, stale or a dry run"}
    return J._watchers({"lanes": lanes}, rows or [_row(l["lane_id"], l["state"], "paused" if l["state"] == "PAUSED" else "unknown") for l in lanes], monitor, monitor_ok)


def test_watcher_lights_are_honest():
    lanes = [lane("self-heal-fixer", state="PAUSED"), lane("pr-merge-telegram-notify", state="NEVER_SCHEDULED")]
    w = {x["id"]: x for x in _watchers(lanes, monitor_ok=False)}
    assert list(w) == ["missed-run-watchdog", "self-heal-fixer", "pr-merge-telegram-notify", "delivery-failure-alerts"]
    assert w["missed-run-watchdog"]["status"] == "degraded"
    assert w["self-heal-fixer"]["status"] == "degraded"
    assert w["pr-merge-telegram-notify"]["status"] == "degraded"
    assert "not installed" in w["pr-merge-telegram-notify"]["cause"]
    # delivery_failure_alerts is not a registered lane -> absent (red), never silently green.
    assert w["delivery-failure-alerts"]["status"] == "absent"
    assert "not a registered job" in w["delivery-failure-alerts"]["cause"].lower()


def test_watchdog_ok_when_monitor_receipt_is_fresh():
    w = {x["id"]: x for x in _watchers([], monitor_ok=True)}
    assert w["missed-run-watchdog"]["status"] == "ok"
    assert w["missed-run-watchdog"]["cause"] is None


def test_active_successful_watcher_is_ok():
    lanes = [lane("self-heal-fixer", state="ACTIVE")]
    rows = [{"lane_id": "self-heal-fixer", "state": "ACTIVE", "result": "succeeded", "cause": "Successful execution receipt"}]
    monitor = {"status": "OK", "cause": None}
    w = {x["id"]: x for x in J._watchers({"lanes": lanes}, rows, monitor, True)}
    assert w["self-heal-fixer"]["status"] == "ok"


def test_failed_watcher_is_down():
    lanes = [lane("self-heal-fixer", state="ACTIVE")]
    rows = [{"lane_id": "self-heal-fixer", "state": "ACTIVE", "result": "failed", "cause": "exit_1: stderr tail"}]
    monitor = {"status": "OK", "cause": None}
    w = {x["id"]: x for x in J._watchers({"lanes": lanes}, rows, monitor, True)}
    assert w["self-heal-fixer"]["status"] == "down"
    assert "exit_1" in w["self-heal-fixer"]["cause"]
