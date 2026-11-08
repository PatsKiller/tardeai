"""LQ-20261107-510: the watchdog's in-hours gate must honour day-of-week.

A weekday-only expression (30 20 * * 1-5) must not put Saturday 20:xx "in window",
or a Saturday 00:15 fire of another expression reads as a missed run at 20:09 ET.
Fixture-only: no DB, subprocess, provider or crontab call.
COVERS = ["scripts/lib/cron_outage_watchdog.py"]
"""
from datetime import datetime

from scripts.lib.cron_outage_watchdog import evaluate

EXPRESSION = "30 20 * * 1-5 + 15 0 * * *"
LANE = {"lane_id": "run-research-intelligence-overnight", "state": "ACTIVE",
        "expected_cadence_hours": 24,
        "scheduler": {"kind": "cron", "expression": EXPRESSION, "match": "research_intelligence_overnight"},
        "output_signal": {"kind": "log_line", "path": "logs/ri_overnight.log"}}
# Last validated success: Friday 2026-11-06 01:05 ET (06:05Z).
SUCCESS = {"lane_id": "run-research-intelligence-overnight", "validated_success": True,
           "at": "2026-11-06T06:05:35+00:00"}
SATURDAY_2009_ET = datetime.fromisoformat("2026-11-08T01:09:00+00:00")  # Sat 2026-11-07 20:09 ET
SUNDAY_0030_ET = datetime.fromisoformat("2026-11-08T05:30:00+00:00")  # Sun 2026-11-08 00:30 ET


def row_at(now):
    result = evaluate({"lanes": [LANE]}, [], {LANE["lane_id"]: [SUCCESS]}, now=now,
                      trading_day=lambda at: True, registered_jobs=None)
    return next(r for r in result["rows"] if r["lane_id"] == LANE["lane_id"])


def test_saturday_2009_et_is_outside_window_not_missed_runs():
    row = row_at(SATURDAY_2009_ET)
    assert row["status"] == "OUTSIDE_WINDOW", row
    assert row.get("missed_fires", 0) == 0


def test_weekday_fire_still_counts_on_a_weekday():
    # Monday 2026-11-09 20:45 ET: the Monday 20:30 fire is in window and has no success after it.
    row = row_at(datetime.fromisoformat("2026-11-10T01:45:00+00:00"))
    assert row["status"] == "MISSED_RUNS", row
