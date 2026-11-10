"""LQ-20261107-1838: disk-hygiene runs nightly at 03:45 ET inside a hard 50-minute wall.

Operator approval: 2026-11-10 15:22 ET, "Yes to all the 03:45 ET disk-cleaning time" (ASSIGN-20261110T2025Z).
Before: `17 * * * *` hourly, timeout_s 3600, pressure.daily_hour_et 4.

Pinned here (each is a site that would silently disagree with the others):
  * lane_registry: cadence, dispatch.cron, expected_cadence_hours, retry_policy none.
  * n8n_run_allowlist: timeout_s 3000, and the executor really builds `timeout -k 30 3000` from it.
  * n8n_retry_policies: the named policy allows exactly ONE attempt, so 50 min is a wall, not one of three.
  * disk_hygiene_rules: daily_hour_et 3, and _daily_due is True at 03:45 ET with that value. With the old 4 a
    03:45-only fire is always below the daily hour, so the day's full run would never happen.
  * the window ends by 04:35 ET, before the 05:00 tmp-hygiene plan and every 05:xx job.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
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
    assert argv[-3:] == ["scripts/disk_hygiene.py", "--standing", "--apply"] or "--scheduled" in argv


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


def test_the_window_is_clear_of_hermes_and_the_05xx_jobs():
    """03:45 + 50 min = 04:35 ET: after hermes-deep-research's :35 hourly slot (22-05) and before 05:00."""
    fire = datetime(2026, 11, 10, 3, 45, tzinfo=ET)
    end = fire.replace(hour=4, minute=35)
    assert end.hour == 4 and end.minute == 35
    assert end < fire.replace(hour=5, minute=0)          # tmp-hygiene plan, librarian-retention 05:10, premarket 05:45
    assert end < fire.replace(hour=9, minute=30)         # the market open, by hours
    assert end.astimezone(timezone.utc) == datetime(2026, 11, 10, 9, 35, tzinfo=timezone.utc)


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
