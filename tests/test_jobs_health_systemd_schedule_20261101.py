"""ANCHOR: JOBS_HEALTH_SYSTEMD_SCHEDULE_20261101 — a systemd lane is measured from the host census.

`config/lane_registry.json` names a systemd lane by its unit, and `schedules()` only reads a cron
expression for `kind == "cron"`, so 121 ACTIVE lanes could never leave "Not measured". The
projection now reads the persisted census and gives them a real next due, a measured schedule and
a success derived from their validated receipts.

Hermetic: fixture registry rows and census dicts; no systemctl, no state-root read.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from scripts.lib import jobs_health as J

NOW = datetime(2026, 11, 1, 15, 30, tzinfo=timezone.utc)


def lane(name: str = "svc", **extra) -> dict:
    return {"lane_id": name, "state": "ACTIVE",
            "scheduler": {"kind": "systemd", "expression": "tradeai-svc.timer"},
            "output_signal": {"kind": "file_mtime", "path": f"data/runtime/{name}.json"}, **extra}


def census(next_elapse="2026-11-01T23:30:00Z", last_trigger="2026-11-01T13:00:00Z") -> dict:
    return {"tradeai-svc.timer": {"active_state": "active", "next_elapse": next_elapse,
                                  "last_trigger": last_trigger}}


def build(lanes, host, successes=None, runs=()):
    snapshot = {"events": [], "successes": successes or {}, "collection_gaps": []}
    return J.build({"lanes": lanes}, snapshot, list(runs), {}, now=NOW, trading_day=lambda d: True,
                   host_schedule=host)


def test_systemd_lane_gets_a_real_next_due_and_a_measured_schedule():
    row = build([lane()], census())["rows"][0]
    assert row["next_due_at"] == "2026-11-01T23:30:00Z"
    assert row["schedule_measured"] is True
    assert row["schedule_source"] == "systemd_timer"
    # Scheduled, but nothing proves a successful run yet: that is a missing receipt, not a
    # missing schedule.
    assert row["evidence_gap"] == "execution_not_measured"


def test_systemd_success_after_the_last_trigger_is_succeeded():
    row = build([lane()], census(),
                successes={"svc": [{"at": "2026-11-01T14:00:00Z", "validated_success": True}]})["rows"][0]
    assert row["result"] == "succeeded"


def test_missing_census_leaves_the_lane_schedule_not_declared():
    row = build([lane()], {})["rows"][0]
    assert row["schedule_measured"] is False
    assert row["schedule_source"] is None
    assert row["evidence_gap"] == "schedule_not_declared"


def test_a_service_with_no_elapse_does_not_invent_a_schedule():
    host = {"tradeai-svc.timer": {"active_state": "inactive", "next_elapse": None, "last_trigger": None}}
    row = build([lane()], host)["rows"][0]
    assert row["schedule_measured"] is False and row["evidence_gap"] == "schedule_not_declared"


def test_census_is_fresh_for_two_hours_and_then_stale(tmp_path):
    path = tmp_path / J.SYSTEMD_CENSUS_REL
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"schema": "SystemdScheduleCensus@v1",
                                "observed_at": "2026-11-01T15:00:00Z",
                                "coverage": "COMPLETE", "units": {"tradeai-svc.timer": {}}}))
    units, state = J._systemd_census(tmp_path, NOW)
    assert state["state"] == "fresh" and "tradeai-svc.timer" in units
    units, state = J._systemd_census(tmp_path, NOW + timedelta(hours=3))
    assert state["state"] == "stale" and units == {}


def test_a_census_from_the_future_is_not_trusted(tmp_path):
    path = tmp_path / J.SYSTEMD_CENSUS_REL
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"schema": "SystemdScheduleCensus@v1",
                                "observed_at": "2026-11-01T18:00:00Z", "units": {"x": {}}}))
    units, state = J._systemd_census(tmp_path, NOW)
    assert state["state"] == "stale" and units == {}
