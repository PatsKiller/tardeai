"""Schedule contract isolation — never activates production schedules."""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

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


@pytest.fixture
def scheduler_scratch(tmp_path, monkeypatch):
    """Source-only scheduler bytes; every process API here is a refusal spy."""
    cron = tmp_path / "crontab.fixture"
    cron.write_bytes(b"# synthetic scheduler fixture\n*/15 * * * * fixture-job\n")
    unit_dir = tmp_path / "systemd"
    unit_dir.mkdir()
    (unit_dir / "existing.fixture.service").write_bytes(b"[Service]\nType=oneshot\n")
    calls = []

    def refuse_process_call(command, *args, **kwargs):
        calls.append(command)
        raise AssertionError("scheduler fixture refused process call")

    for api in ("run", "Popen", "call", "check_call", "check_output"):
        monkeypatch.setattr(subprocess, api, refuse_process_call)
    monkeypatch.setattr(os, "system", refuse_process_call)
    return cron, unit_dir, calls


def _scheduler_fixture_snapshot(cron, unit_dir):
    return {"cron": cron.read_bytes(),
            "units": {str(p.relative_to(unit_dir)): p.read_bytes()
                      for p in unit_dir.rglob("*") if p.is_file()}}


def test_crontab_unchanged_by_contract_evaluation(scheduler_scratch):
    """Contract evaluation preserves fixture bytes and calls no scheduler."""
    cron, unit_dir, calls = scheduler_scratch
    before = _scheduler_fixture_snapshot(cron, unit_dir)
    c = ScheduleContract("cio", "r")
    h = evaluate_health(c, now=NOW, completed_slots=[], never_scheduled=True)
    assert h.state == "never_scheduled"
    after = _scheduler_fixture_snapshot(cron, unit_dir)
    assert before == after
    assert calls == []


@pytest.mark.parametrize("command", [["crontab", "-"],
                                     ["systemctl", "--user", "start", "fixture.timer"]])
def test_scheduler_contract_rejects_introduced_process_mutation(scheduler_scratch, monkeypatch, command):
    """An accidental scheduler call makes the original contract test fail."""
    before = _scheduler_fixture_snapshot(*scheduler_scratch[:2])

    def mutation(*args, **kwargs):
        subprocess.run(command)

    monkeypatch.setitem(globals(), "evaluate_health", mutation)
    with pytest.raises(AssertionError, match="scheduler fixture refused process call"):
        test_crontab_unchanged_by_contract_evaluation(scheduler_scratch)
    assert scheduler_scratch[2] == [command]
    assert _scheduler_fixture_snapshot(*scheduler_scratch[:2]) == before


@pytest.mark.parametrize("destination", ["cron", "timer"])
def test_scheduler_contract_detects_introduced_fixture_write(scheduler_scratch, monkeypatch, destination):
    """Byte comparisons catch file-based changes even without a subprocess."""
    original = evaluate_health
    cron, unit_dir, _ = scheduler_scratch

    def mutation(*args, **kwargs):
        if destination == "cron":
            cron.write_bytes(cron.read_bytes() + b"* * * * * injected-job\n")
        else:
            (unit_dir / "persistent-agent-wake.timer").write_bytes(b"[Timer]\nOnBootSec=1s\n")
        return original(*args, **kwargs)

    monkeypatch.setitem(globals(), "evaluate_health", mutation)
    with pytest.raises(AssertionError):
        test_crontab_unchanged_by_contract_evaluation(scheduler_scratch)
