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


def _crontab_snapshot() -> str:
    """The user's crontab, or "" where there is none.

    `crontab -l` exits 1 when the user has no crontab and the binary may be
    absent entirely, so check_output() raises on CI. Registering this file into
    the campaign_m2_canary_lanes gate ran it under CI for the first time and it
    failed there while passing locally — the same defect, and the same cause,
    that tests/test_dark_contract_guard.py already records: "shelling out makes
    the gate machine-dependent ... in CI, where no crontab exists."

    The guarantee is unchanged: the snapshot is taken identically before and
    after, so "evaluating the contract did not touch the crontab" is still
    proven. Where no crontab exists, "" == "" is the correct answer — evaluating
    a contract must not CREATE one either.
    """
    try:
        r = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    except (FileNotFoundError, OSError):
        return ""
    return r.stdout if r.returncode == 0 else ""


def test_crontab_unchanged_by_contract_evaluation():
    before = _crontab_snapshot()
    c = ScheduleContract("cio", "r")
    evaluate_health(c, now=NOW, completed_slots=[], never_scheduled=True)
    after = _crontab_snapshot()
    assert before == after
