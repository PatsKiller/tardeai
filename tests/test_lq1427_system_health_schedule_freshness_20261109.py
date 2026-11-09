"""Schedule-aware system_health_checks freshness for the worker pool.

ANCHOR: LQ1427_SYSTEM_HEALTH_SCHEDULE_FRESHNESS_20261109

The only writer is health_tick step system-health-agent (weekdays 1-5, hours
9-20, cadence 5). A wall-clock 48h limit raises every weekend after Sun 20:55 ET
even though the table is idle by design from Fri 20:55 to Mon 09:00. The gate
now requires the last write to be at or after the latest due tick of that step
which has had one config-derived grace (max of cadence and timeout) to finish.

Synthetic clocks only. No database.

Mon 2026-11-09 01:00 ET, last write Fri 2026-11-06 20:55 ET -> pass.
Tue 2026-11-10 14:00 ET, last write Tue 2026-11-10 08:00 ET -> raise.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from lib.hermes_discovery import coverage, coverage_lanes  # noqa: E402

ET = ZoneInfo("America/New_York")
_CFG = {"max_candidates_per_run": 1}


def _et(year: int, month: int, day: int, hour: int, minute: int) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=ET)


class _Rows:
    """Answers the freshness probe and the findings read. Never opens a database."""

    def __init__(self, last):
        self.last = last
        self.calls = []

    def __call__(self, sql, params=None, *, strict=False):
        self.calls.append(strict)
        if "max(updated_at)" in sql:
            return [{"last": self.last}]
        return []


def _pin_clock(monkeypatch, now: datetime) -> None:
    monkeypatch.setenv("TRADEAI_CRON_TZ", "America/New_York")
    utc = now.astimezone(timezone.utc)
    monkeypatch.setattr(coverage_lanes, "_utc_now", lambda: utc)


def _run(monkeypatch, now: datetime, last):
    _pin_clock(monkeypatch, now)
    monkeypatch.setattr(coverage, "_rows", _Rows(last))
    return coverage_lanes.system_ops_runner(_CFG, dry_run=True)


def test_weekend_quiet_is_fresh(monkeypatch):
    """Mon 01:00 ET, last write Fri 20:55 ET. The writer has not been due yet."""
    now = _et(2026, 11, 9, 1, 0)
    last = _et(2026, 11, 6, 20, 55)
    assert _run(monkeypatch, now, last) == []
    deadline, step = coverage_lanes.system_health_deadline(now.astimezone(timezone.utc))
    assert deadline == last.astimezone(timezone.utc)
    assert step["step_id"] == "system-health-agent"
    assert step["weekdays"] == [1, 2, 3, 4, 5]
    assert 20 in step["hours"] and 9 in step["hours"]


def test_first_monday_slot_still_inside_grace(monkeypatch):
    """Mon 09:04 ET is one minute short of cadence-after-09:00. Friday's write holds."""
    now = _et(2026, 11, 9, 9, 4)
    last = _et(2026, 11, 6, 20, 55)
    assert _run(monkeypatch, now, last) == []


def test_writer_silent_after_the_window_opens(monkeypatch):
    """Mon 09:05 ET, grace after the 09:00 tick has elapsed, Friday's write is stale."""
    now = _et(2026, 11, 9, 9, 5)
    last = _et(2026, 11, 6, 20, 55)
    with pytest.raises(RuntimeError, match="stale") as raised:
        _run(monkeypatch, now, last)
    text = str(raised.value)
    assert "cadence_minutes=5" in text
    assert "> 48" not in text
    deadline, _step = coverage_lanes.system_health_deadline(now.astimezone(timezone.utc))
    assert deadline == _et(2026, 11, 9, 9, 0).astimezone(timezone.utc)


def test_stall_inside_the_writer_window_raises(monkeypatch):
    """Tue 14:00 ET, last write Tue 08:00 ET. Six wall hours, and the 13:55 tick is due."""
    now = _et(2026, 11, 10, 14, 0)
    last = _et(2026, 11, 10, 8, 0)
    with pytest.raises(RuntimeError, match="stale") as raised:
        _run(monkeypatch, now, last)
    assert "cadence_minutes=5" in str(raised.value)
    assert "> 48" not in str(raised.value)
    deadline, _step = coverage_lanes.system_health_deadline(now.astimezone(timezone.utc))
    assert deadline == _et(2026, 11, 10, 13, 55).astimezone(timezone.utc)


def test_write_at_the_deadline_is_fresh(monkeypatch):
    now = _et(2026, 11, 10, 14, 0)
    last = _et(2026, 11, 10, 13, 55)
    assert _run(monkeypatch, now, last) == []


def test_deadline_follows_an_injected_step(monkeypatch):
    """A Tuesday-11:00-only step must not inherit the real 9-20 window or a 48h limit."""
    step = {
        "step_id": "system-health-agent",
        "cadence_minutes": 60,
        "minute_offset": 0,
        "hours": [11],
        "weekdays": [2],
        "timeout_s": 0,
        "enabled": True,
    }
    monkeypatch.setattr(coverage_lanes, "_load_health_writer_schedule", lambda: (step, 5))
    now = _et(2026, 11, 10, 14, 0)
    _pin_clock(monkeypatch, now)
    monkeypatch.setattr(coverage, "_rows", _Rows(_et(2026, 11, 10, 11, 0)))
    assert coverage_lanes.system_ops_runner(_CFG, dry_run=True) == []
    monkeypatch.setattr(coverage, "_rows", _Rows(_et(2026, 11, 10, 10, 0)))
    with pytest.raises(RuntimeError, match="stale") as raised:
        coverage_lanes.system_ops_runner(_CFG, dry_run=True)
    assert "hours=[11]" in str(raised.value)
    assert "cadence_minutes=60" in str(raised.value)


def test_missed_friday_is_stale_on_monday_morning(monkeypatch):
    """Mon 01:00 ET with only Thursday's 20:55 write: Friday's slot never landed."""
    now = _et(2026, 11, 9, 1, 0)
    last = _et(2026, 11, 5, 20, 55)
    with pytest.raises(RuntimeError, match="stale"):
        _run(monkeypatch, now, last)


def test_empty_table_raises_without_reading_the_schedule(monkeypatch):
    def boom():
        raise AssertionError("schedule must not be consulted when the table is empty")

    monkeypatch.setattr(coverage_lanes, "_load_health_writer_schedule", boom)
    monkeypatch.setattr(coverage, "_rows", _Rows(None))
    with pytest.raises(RuntimeError, match="empty"):
        coverage_lanes.system_ops_runner(_CFG, dry_run=True)


def test_db_error_propagates(monkeypatch):
    def down(sql, params=None, *, strict=False):
        raise RuntimeError("db down")

    monkeypatch.setattr(coverage, "_rows", down)
    with pytest.raises(RuntimeError, match="db down"):
        coverage_lanes.system_ops_runner(_CFG, dry_run=True)


def test_missing_writer_step_refuses_to_look_fresh(monkeypatch, tmp_path):
    table = {
        "schema": "HealthTickSteps@v1",
        "tick_minutes": 5,
        "steps": [{
            "step_id": "other",
            "command": ["python3", "-c", "pass"],
            "cadence_minutes": 5,
            "finding_rc": [],
        }],
    }
    path = tmp_path / "steps.json"
    path.write_text(json.dumps(table), encoding="utf-8")
    ht = coverage_lanes._health_tick_module()
    monkeypatch.setattr(ht, "DEFAULT_TABLE", path)
    now = _et(2026, 11, 9, 1, 0)
    last = _et(2026, 11, 6, 20, 55)
    with pytest.raises(RuntimeError, match="missing"):
        _run(monkeypatch, now, last)


def test_unreadable_table_refuses_to_look_fresh(monkeypatch, tmp_path):
    ht = coverage_lanes._health_tick_module()
    monkeypatch.setattr(ht, "DEFAULT_TABLE", tmp_path / "absent.json")
    now = _et(2026, 11, 10, 14, 0)
    last = now
    with pytest.raises(RuntimeError, match="unreadable"):
        _run(monkeypatch, now, last)


def test_disabled_writer_is_not_fresh(monkeypatch):
    step = {
        "step_id": "system-health-agent",
        "cadence_minutes": 5,
        "minute_offset": 0,
        "hours": [9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20],
        "weekdays": [1, 2, 3, 4, 5],
        "timeout_s": 240,
        "enabled": False,
    }
    monkeypatch.setattr(coverage_lanes, "_load_health_writer_schedule", lambda: (step, 5))
    now = _et(2026, 11, 10, 14, 0)
    with pytest.raises(RuntimeError, match="no scheduled fire"):
        coverage_lanes.system_health_deadline(now.astimezone(timezone.utc))


def test_bad_cron_zone_refuses(monkeypatch):
    monkeypatch.setenv("TRADEAI_CRON_TZ", "Not/AZone")
    now = _et(2026, 11, 10, 14, 0)
    with pytest.raises(RuntimeError, match="TRADEAI_CRON_TZ"):
        coverage_lanes.system_health_deadline(now.astimezone(timezone.utc))
