"""Schedule contract isolation — never activates production schedules."""
from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT)]

from scripts.lib.persistent_wake_schedule import (  # noqa: E402
    SCHEDULE_STATES,
    ScheduleContract,
    assert_schedule_states_complete,
    evaluate_health,
)

NOW = datetime(2026, 9, 7, 19, 30, tzinfo=timezone.utc)


def test_all_required_states_defined():
    assert_schedule_states_complete()
    assert set(SCHEDULE_STATES) == {
        "never_scheduled", "due", "running", "completed", "partial", "failed",
        "replay_suppressed", "stale_dependency", "no_relevant_memory",
    }


def test_slot_derivation_deterministic():
    c = ScheduleContract("cio", "scheduled_persistent_review", cadence_minutes=60)
    a = c.slot_for(NOW)
    b = c.slot_for(NOW.replace(minute=59))
    assert a == b == "2026-09-07T19:00Z"


def test_crontab_unchanged_by_contract_evaluation():
    before = subprocess.check_output(["crontab", "-l"], text=True)
    c = ScheduleContract("cio", "r")
    evaluate_health(c, now=NOW, completed_slots=[], never_scheduled=True)
    after = subprocess.check_output(["crontab", "-l"], text=True)
    assert before == after
