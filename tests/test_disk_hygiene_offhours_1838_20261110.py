"""LQ-20261107-1838: disk-hygiene runs nightly at 03:45 ET inside a hard 50-minute wall.

Operator approval: 2026-11-10 15:22 ET, "Yes to all the 03:45 ET disk-cleaning time" (ASSIGN-20261110T2025Z).
Before: `17 * * * *` hourly, timeout_s 3600, pressure.daily_hour_et 4.

Pinned here (each is a site that would silently disagree with the others):
  * lane_registry: cadence, dispatch.cron, expected_cadence_hours, retry_policy none.
  * n8n_run_allowlist: timeout_s 3000, and the executor really builds `timeout -k 30 3000` from it.
  * n8n_retry_policies: the named policy allows exactly ONE attempt, so 50 min is a wall, not one of three.
  * disk_hygiene_rules: daily_hour_et 3, and _daily_due is True at 03:45 ET with that value. With the old 4 a
    03:45-only fire is always below the daily hour, so the day's full run would never happen.
  * the script's own prose and `--help` say nightly, not hourly (LQ-1838 review F1).
  * the window's worst case (REWORK 1, review F2): 03:45 + timeout_s 3000 + KILL_AFTER_S 30 + one dispatcher tick =
    ~04:36:30 ET — before the 05:00 tmp-hygiene run and every 05:xx job, but overlapping hermes-deep-research's 04:35
    fire by <= 90 s. The overlap is pinned as a bound, not asserted away.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
ET = ZoneInfo("America/New_York")


def _doc(name: str):
    return json.loads((ROOT / "config" / name).read_text(encoding="utf-8"))


def _registry_row(lane: str = "disk-hygiene"):
    return next(r for r in _doc("lane_registry.json")["lanes"] if r["lane_id"] == lane)


def _allow_entry(lane: str = "disk-hygiene"):
    return next(e for e in _doc("n8n_run_allowlist.json")["lanes"] if e["lane_id"] == lane)


def _contract(lane: str = "disk-hygiene"):
    return next(c for c in _doc("n8n_health_contracts.json")["contracts"] if c["id"] == lane)


def test_registry_row_is_nightly_not_hourly():
    row = _registry_row()
    assert row["scheduler"]["kind"] == "n8n" and row["scheduler"]["expression"] == "dispatcher"
    assert row["scheduler"]["cadence"] == "45 3 * * *"
    assert row["dispatch"]["cron"] == ["45 3 * * *"]
    assert row["dispatch"]["tz"] == "America/New_York"
    assert row["expected_cadence_hours"] == 24.0
    assert row["state"] == "ACTIVE" and row["scheduler"]["stage"] == "canary"


def test_retry_policy_is_none_so_the_cap_is_a_wall():
    """With transient-2 the same slot could spend 3 x 3000 s + backoff, well past 04:35 and into the 05:xx jobs."""
    from scripts.lib import n8n_retry_policy as RP

    name = _registry_row()["dispatch"]["retry_policy"]
    assert name == "none"
    policies = RP.load_policies()
    assert RP.effective_max_attempts(policies.get(name), "hygiene") == 1


def test_allowlist_timeout_is_the_50_minute_wall_and_the_executor_builds_it():
    entry = _allow_entry()
    assert entry["timeout_s"] == 3000 == 50 * 60
    assert entry["live_arg"] == ["--standing", "--apply", "--scheduled"]

    from scripts import n8n_run_executor as EX

    argv = EX.build_argv(
        entry, "live",
        env={"TRADEAI_VENV_PYTHON": "/venv/python"},
        state_root=ROOT / "fixtures-state",
        code_root=ROOT,
    )
    flat = " ".join(argv)
    assert "timeout -k %d 3000 " % EX.KILL_AFTER_S in flat, flat  # the wrapper, not the lane, owns the cap
    assert argv[-3:] == entry["live_arg"], argv  # exactly --standing --apply --scheduled; no 'or' escape


def test_daily_run_is_due_at_the_0345_fire(tmp_path):
    """daily_hour_et must be <= 3: _daily_due is False below the hour, so with one 03:45 fire a 4 never runs."""
    from scripts import disk_hygiene as DH

    rules = DH.load_rules()
    hour = rules["standing_apply"]["pressure"]["daily_hour_et"]
    assert hour == 3
    at_fire = datetime(2026, 11, 10, 3, 45, tzinfo=ET)
    assert DH._daily_due(rules, tmp_path, at_fire, hour) is True
    # one second before the hour is still due (the check is hour-granular); a fire at 02:59 is not.
    assert DH._daily_due(rules, tmp_path, datetime(2026, 11, 10, 2, 59, tzinfo=ET), hour) is False
    # once today's full run is recorded, the same hour is owed no second full run.
    daily = DH.manifest_dir(rules, tmp_path) / DH.DAILY_STATE
    daily.parent.mkdir(parents=True, exist_ok=True)
    daily.write_text(json.dumps({"date_et": "2026-11-10"}))
    assert DH._daily_due(rules, tmp_path, at_fire, hour) is False


def _cron_hm(cron: str) -> tuple[int, int]:
    """(hour, minute) of a `M H * * *` cron string — the only shape these lanes use."""
    minute, hour = cron.split()[:2]
    return int(hour), int(minute)


#: hermes-deep-research-local.timer `OnCalendar=*-*-* 22,23,00,01,02,03,04,05:35:00 America/New_York`, read from the
#: live user unit on 2026-11-10. It is a systemd timer, so the registry carries no cron for it; the drift guard below
#: re-reads the unit when this host has it.
HERMES_DEEP_RESEARCH_HOURS = (22, 23, 0, 1, 2, 3, 4, 5)
HERMES_DEEP_RESEARCH_MINUTE = 35
#: the dispatcher template cron is `* * * * *` (scripts/n8n_workflow_templates.py), so a due slot starts up to one
#: tick late. This is the only slack the window test allows.
DISPATCH_TICK_S = 60
#: librarian-retention and premarket-data-pipeline, from their timers/registry rows: the next jobs after 05:00.
LIBRARIAN_RETENTION_HM = (5, 10)
PREMARKET_DATA_PIPELINE_HM = (5, 45)
#: KILL_AFTER_S (30) + one dispatcher tick: the most the run can overrun the 04:35 hermes fire by.
EX_OVERLAP_BOUND_S = 90


def _worst_case_end(fire: datetime):
    """The real worst case, from committed values: the fire, the allowlist cap, the kill delay and one dispatcher tick."""
    from scripts import n8n_run_executor as EX

    entry = _allow_entry()
    return fire + timedelta(seconds=entry["timeout_s"] + EX.KILL_AFTER_S + DISPATCH_TICK_S)


def test_the_window_is_bounded_by_the_committed_timeout_not_by_arithmetic_on_constants():
    """REWORK 1 / review F2: the old test built its own expected value (03:45 -> 04:35) and read no timeout_s.

    At the committed 3000 s cap the worst case is 03:45 + 3000 + 30 + 60 = 04:36:30 ET, not 04:35. The assertions that
    follow are bounds against named neighbours, and the hermes overlap is asserted as a bound (<= 90 s).
    """
    hour, minute = _cron_hm(_registry_row()["dispatch"]["cron"][0])
    fire = datetime(2026, 11, 10, hour, minute, tzinfo=ET)
    assert (hour, minute) == (3, 45)
    end = _worst_case_end(fire)
    assert end == datetime(2026, 11, 10, 4, 36, 30, tzinfo=ET)

    # no overlap with the next fixed jobs
    for hm, why in ((_cron_hm(_registry_row("tmp-hygiene")["dispatch"]["cron"][0]), "tmp-hygiene 05:00"),
                    (LIBRARIAN_RETENTION_HM, "librarian-retention 05:10"),
                    (PREMARKET_DATA_PIPELINE_HM, "premarket-data-pipeline 05:45"),
                    ((9, 30), "market open 09:30")):
        assert end < fire.replace(hour=hm[0], minute=hm[1]), why

    # the one overlap that is real, bounded and disclosed: hermes-deep-research fires at 04:35, inside the last 90 s.
    hermes = fire.replace(hour=4, minute=HERMES_DEEP_RESEARCH_MINUTE)
    assert 4 in HERMES_DEEP_RESEARCH_HOURS and fire < hermes < end
    overlap_s = (end - hermes).total_seconds()
    assert 0 < overlap_s <= EX_OVERLAP_BOUND_S, overlap_s
    # and it cannot reach the *next* hermes fire at 05:35
    assert end < fire.replace(hour=5, minute=HERMES_DEEP_RESEARCH_MINUTE)


@pytest.mark.host_state("reads the user's hermes-deep-research-local.timer; skips where it is absent (CI)")
def test_the_hermes_overlap_constant_matches_the_live_unit_when_present():
    """A drift guard, not a dependency: on a host without the user unit the assertions are skipped."""
    unit = Path.home() / ".config" / "systemd" / "user" / "hermes-deep-research-local.timer"
    if not unit.exists():
        pytest.skip("hermes-deep-research-local.timer not installed on this host")
    line = next((ln.strip() for ln in unit.read_text().splitlines() if ln.strip().startswith("OnCalendar=")), "")
    hours, minute = line.split("OnCalendar=")[1].split(":", 1)
    got_hours = tuple(int(h) % 24 for h in hours.rsplit(" ", 1)[-1].split(","))
    assert got_hours == HERMES_DEEP_RESEARCH_HOURS, line
    assert int(minute[:2]) == HERMES_DEEP_RESEARCH_MINUTE, line


def test_the_script_prose_and_help_say_nightly_not_hourly():
    """REWORK 1 / review F1: the old prose test never opened the script, though its name promised it would."""
    from scripts import disk_hygiene as DH

    source = (ROOT / "scripts" / "disk_hygiene.py").read_text(encoding="utf-8")
    assert "hourly" not in source.lower(), "stale 'hourly' prose in scripts/disk_hygiene.py"

    proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "disk_hygiene.py"), "--help"],
                          cwd=str(ROOT), capture_output=True, text=True, timeout=120,
                          env={**os.environ, "PYTHONPATH": str(ROOT)})
    assert proc.returncode == 0, proc.stderr
    help_text = proc.stdout.lower()
    assert "hourly" not in help_text, proc.stdout
    assert "dispatch.cron" in help_text  # the assertion above is about a real help page, not an empty string
    # the budget constant is below the wall, and the wall is the allowlist's
    assert DH.RUN_BUDGET_S == 2400 < _allow_entry()["timeout_s"] == 3000


def test_the_contract_and_prose_say_nightly_0345_and_not_hourly():
    text = _contract()["purpose"]["text"]
    assert _contract()["status"] == "REVIEWED"
    assert "03:45" in text and "50-min" in text
    assert "hourly" not in text.lower()
    row = _registry_row()
    assert row["scheduler"]["cadence"] == "45 3 * * *" and row["dispatch"]["cron"] == ["45 3 * * *"]
    # the row may RECORD the history; it may not still CLAIM the old schedule as current.
    assert "fired by tradeai-dispatcher hourly" not in row["state_reason"]
    assert "hourly" not in _allow_entry()["source"].lower()
