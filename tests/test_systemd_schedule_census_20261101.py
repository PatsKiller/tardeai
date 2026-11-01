"""ANCHOR: SYSTEMD_SCHEDULE_CENSUS_20261101 — the host's timer calendar becomes a dated artifact
the Jobs projection can measure systemd lanes from, without a scheduler subprocess at read time.

Hermetic: a fake systemctl runner and a tmp state root; no host call, no durable write.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from scripts.lib import systemd_schedule_census as C

NOW = datetime(2026, 11, 1, 15, 30, tzinfo=timezone.utc)


def test_parse_instant_attaches_the_declared_zone():
    assert C.parse_instant("Sun 2026-11-01 18:30:00 EST", "America/New_York").isoformat() == "2026-11-01T23:30:00+00:00"
    assert C.parse_instant("", "America/New_York") is None
    assert C.parse_instant(None) is None


def test_parse_duration_reads_systemd_units():
    assert C.parse_duration("2min") == timedelta(minutes=2)
    assert C.parse_duration("1month 2w 5d 8h 11min 50.022431s") is not None
    assert C.parse_duration("nothing here") is None


def test_next_elapse_prefers_realtime_then_calendar_then_monotonic():
    expected = datetime(2026, 11, 1, 23, 30, tzinfo=timezone.utc)
    assert C.next_elapse({"NextElapseUSecRealtime": "Sun 2026-11-01 18:30:00 EST"}, now=NOW) == expected
    calendar = {"TimersCalendar": "{ OnCalendar=*-*-* 18:30:00 ; next_elapse=Sun 2026-11-01 18:30:00 EST }"}
    assert C.next_elapse(calendar, now=NOW) == expected
    monotonic = {"TimersMonotonic": "{ OnUnitActiveUSec=2min ; next_elapse=2min }"}
    assert C.next_elapse(monotonic, now=NOW) == NOW + timedelta(minutes=2)


def test_collect_parses_units_and_keeps_a_gap_for_a_missing_one():
    def runner(scope, names):
        assert names == ["a.timer", "b.timer"]
        return ("Id=a.timer\nActiveState=active\n"
                "NextElapseUSecRealtime=Sun 2026-11-01 18:30:00 EST\n"
                "LastTriggerUSec=Sat 2026-10-31 18:30:00 EDT\n\n"
                "Id=b.service\nActiveState=inactive\n")

    units = C.collect([("a.timer", "user", "America/New_York"),
                       ("b.timer", "user", "America/New_York")], now=NOW, runner=runner)
    assert units["a.timer"]["next_elapse"] == "2026-11-01T23:30:00Z"
    assert units["a.timer"]["last_trigger"] == "2026-10-31T22:30:00Z"
    assert units["b.service"]["next_elapse"] is None
    assert "b.timer" not in units  # absent is absent, never invented


def test_write_census_records_coverage(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config/lane_registry.json").write_text(json.dumps({"lanes": [
        {"lane_id": "x", "scheduler": {"kind": "systemd", "expression": "x.timer"}},
        {"lane_id": "y", "scheduler": {"kind": "cron", "expression": "0 * * * *"}}]}))

    def runner(scope, names):
        return "Id=x.timer\nActiveState=active\nNextElapseUSecRealtime=Sun 2026-11-01 18:30:00 EST\n"

    out = tmp_path / "census.json"
    assert C.write_census(tmp_path, out=out, now=NOW, runner=runner) == out
    doc = json.loads(out.read_text())
    assert doc["schema"] == "SystemdScheduleCensus@v1"
    assert doc["coverage"] == "COMPLETE" and "x.timer" in doc["units"]


def test_write_census_never_raises(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config/lane_registry.json").write_text(json.dumps({"lanes": [
        {"lane_id": "x", "scheduler": {"kind": "systemd", "expression": "x.timer"}}]}))

    def boom(*_a, **_k):
        raise RuntimeError("systemctl unavailable")

    assert C.write_census(tmp_path, out=tmp_path / "c.json", now=NOW, runner=boom) is None


def test_an_empty_registry_records_unmeasured_not_complete(tmp_path):
    out = tmp_path / "c.json"
    assert C.write_census(tmp_path, out=out, now=NOW, runner=lambda *_: "") == out
    assert json.loads(out.read_text())["coverage"] == "UNMEASURED"
