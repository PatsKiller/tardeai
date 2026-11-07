"""ANCHOR: DEADMAN_WINDOW_20261107 — a lane designed to run 06:00-11:59 ET Mon-Fri is not late at 22:27.

WORK-QUEUE 2026-11-07, item 13. `premarket-delivery-deadman` is a `tradeai-health-tick.timer` step
(config/health_tick_steps.json: cadence_minutes 15, minute_offset 0, hours 6-11, weekdays 1-5,
market_day_gate true). The registry row carried only a human-readable `scheduler.expression`, so
`cron_outage_watchdog.schedules()` declared no wall schedule, `expected_slots()` was empty, and
`jobs_history` charged the 0.25 h `expected_cadence_hours` around the clock — "Nothing recorded for
0.25 h × 1.5" for the ~18 hours a weekday the step is designed to be silent, and all weekend.

The row now declares the same window the step runs on, in the field the scheduler-of-record reader
already reads for a systemd lane (`scheduler.cadence`, as `cron-outage-watchdog` does), and marks
itself calendar-respecting so a market holiday is not charged either.

Hermetic: synthetic clocks and a synthetic trading-day calendar; no database, no host state.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts.lib import cron_outage_watchdog as W
from scripts.lib import jobs_history as J
from scripts.lib.cron_schedule import fires_between

ROOT = Path(__file__).resolve().parents[1]
ET = ZoneInfo("America/New_York")
LANE_ID = "premarket-delivery-deadman"


def registry_row() -> dict:
    lanes = json.loads((ROOT / "config" / "lane_registry.json").read_text())["lanes"]
    return next(lane for lane in lanes if lane["lane_id"] == LANE_ID)


def health_tick_step() -> dict:
    steps = json.loads((ROOT / "config" / "health_tick_steps.json").read_text())
    steps = steps["steps"] if isinstance(steps, dict) else steps
    return next(step for step in steps if step["step_id"] == LANE_ID)


def receipts_for(*, started_et: datetime) -> dict:
    """The lane's own receipt, as `write_lane_receipt` writes it: live, exit 0, ok."""
    finished = started_et.astimezone(ZoneInfo("UTC"))
    return {LANE_ID: J.receipt_run({"started_at": started_et.isoformat(), "finished_at": finished.isoformat(),
                                    "ok_at": finished.isoformat(), "exit": 0, "status": "ok"}, None)}


def build(*, now_et: datetime, started_et: datetime, trading_day=None):
    lane = registry_row()
    inputs = {"ledger_since": now_et.astimezone(ZoneInfo("UTC")) - timedelta(days=10),
              "journal_since": now_et.astimezone(ZoneInfo("UTC")) - timedelta(days=10),
              "receipts": receipts_for(started_et=started_et)}
    return J.build({"lanes": [lane]}, inputs, now=now_et.astimezone(ZoneInfo("UTC")),
                   trading_day=trading_day or (lambda day: day.isoweekday() <= 5))


def row_of(result) -> dict:
    return next(row for row in result["rows"] if row["lane_id"] == LANE_ID)


FRIDAY = date(2026, 11, 6)
LAST_TICK = datetime(2026, 11, 6, 11, 45, 43, tzinfo=ET)  # the live receipt: 2026-11-06T16:45:43Z
FRIDAY_EVENING = datetime(2026, 11, 6, 22, 27, tzinfo=ET)


def test_the_row_declares_the_window_the_step_runs():
    row, step = registry_row(), health_tick_step()
    cadence = row["scheduler"].get("cadence")
    assert cadence, "the deadman row declares no machine-readable schedule; its cadence is charged around the clock"
    expressions, _tz, issue = W.schedules(row)
    assert issue is None and expressions, "the declared window is not readable by the scheduler of record"
    # Every fire of the declared window falls inside the step's own hours/weekdays, on its minute grid.
    start = datetime(2026, 11, 2, tzinfo=ET)  # a Monday
    fires = [fire.at.astimezone(ET) for expression in expressions
             for fire in fires_between(expression, start, start + timedelta(days=14), "America/New_York")]
    assert fires, "the declared window produces no fires"
    assert {fire.hour for fire in fires} == set(step["hours"])
    assert {fire.isoweekday() for fire in fires} == set(step["weekdays"])
    assert {fire.minute for fire in fires} == set(range(0, 60, step["cadence_minutes"]))
    assert all(fire.minute % step["cadence_minutes"] == step["minute_offset"] for fire in fires)
    assert row.get("respect_calendar") is step["market_day_gate"], (
        "a market-day-gated step must respect the trading calendar, or every holiday reads late")


def test_friday_evening_is_not_late():
    row = row_of(build(now_et=FRIDAY_EVENING, started_et=LAST_TICK))
    assert row["status"] != "late", row["status_reason"]
    assert row["status"] == "ok"
    assert row["missed_count"] is None


def test_weekend_is_not_late():
    saturday = datetime(2026, 11, 7, 20, 0, tzinfo=ET)
    row = row_of(build(now_et=saturday, started_et=LAST_TICK))
    assert row["status"] != "late", row["status_reason"]


def test_a_missing_monday_tick_is_still_late():
    """The window must not hide a real stall: by 06:20 ET Monday the 06:00 tick should have written a receipt."""
    monday = datetime(2026, 11, 9, 6, 20, tzinfo=ET)
    row = row_of(build(now_et=monday, started_et=LAST_TICK))
    assert row["status"] == "late"
    assert row["status_reason"] == "No run or output recorded since the latest scheduled time"


def test_a_market_holiday_is_not_late():
    holiday = date(2026, 11, 11)  # Veterans Day: a weekday the market is closed and the step is gated off

    def trading_day(day: datetime) -> bool:
        return day.isoweekday() <= 5 and day.date() != holiday

    row = row_of(build(now_et=datetime(2026, 11, 11, 8, 30, tzinfo=ET),
                       started_et=datetime(2026, 11, 10, 11, 45, tzinfo=ET), trading_day=trading_day))
    assert row["status"] != "late", row["status_reason"]


def test_a_lane_with_no_wall_schedule_still_gets_the_hours_rule():
    """Guard: the 0.25 h × 1.5 rule is a real signal for a lane that declares hours and no window."""
    lane = {"lane_id": "synthetic-hours-only", "state": "ACTIVE", "expected_cadence_hours": 0.25,
            "scheduler": {"kind": "systemd", "expression": "synthetic-fifteen-minute.timer"},
            "output_signal": {"kind": "file_mtime", "path": "data/runtime/synthetic-hours-only.json"}}
    now = datetime(2026, 11, 6, 22, 27, tzinfo=ET).astimezone(ZoneInfo("UTC"))
    out = J.build({"lanes": [lane]}, {"ledger_since": now - timedelta(days=10),
                                      "journal_since": now - timedelta(days=10),
                                      "output_times": {"synthetic-hours-only": now - timedelta(hours=2)}},
                  now=now, trading_day=lambda day: day.isoweekday() <= 5)
    row = next(r for r in out["rows"] if r["lane_id"] == "synthetic-hours-only")
    assert row["status"] == "late"
    assert row["status_reason"] == "Nothing recorded for 0.25 h × 1.5"
