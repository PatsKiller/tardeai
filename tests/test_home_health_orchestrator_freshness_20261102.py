"""Home health: the Trade AI Orchestrator is judged against its real schedule.

CC5's Home audit (D2, 2026-11-02): the component monitored `logs/screener_pm.log` with a 180-minute
wall-clock threshold, while the only ACTIVE lane that writes that log runs 17:30 ET Monday to Friday
(`orchestrator-slot`; `orchestrator-slot-midday` is RETIRED). The monitor therefore called the
component STALE every evening, all night and all weekend.

The fix is a schedule source, not a bigger timeout: the component declares
`schedule_source: "lane_registry"`, so its expected fire time and its freshness comparison come from
the ACTIVE lane rows, and `freshness_at(prev_fire=...)` judges "stale" against the last run that was
actually due.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

_spec = importlib.util.spec_from_file_location("health_agent_under_test", ROOT / "scripts" / "system_health_agent.py")
health = importlib.util.module_from_spec(_spec)
sys.modules["health_agent_under_test"] = health
_spec.loader.exec_module(health)  # type: ignore[union-attr]


def _orch() -> dict:
    return next(c for c in health.MONITORED_COMPONENTS if c["component"] == "trade_ai_orchestrator")


def test_the_orchestrator_schedule_comes_from_the_active_lane():
    resolved = health._resolve_component_schedule(_orch())
    assert resolved["schedule_resolved_from"] == "lane_registry"
    # The only ACTIVE lane writing screener_pm.log: weekdays 17:30 ET.
    assert resolved["schedule"] == "30 17 * * 1-5"


def test_the_fail_back_literal_matches_the_active_lane():
    """If the registry cannot be read, the component keeps its reviewed literal - and it must be true."""
    comp = _orch()
    assert comp["schedule"] == "30 17 * * 1-5"
    assert comp["schedule_source"] == "lane_registry"
    assert comp["monitor_lane_ids"] == ["orchestrator-slot", "orchestrator-slot-midday"]


def test_a_retired_lane_does_not_set_the_expectation():
    """orchestrator-slot-midday is RETIRED, so its 12/14/16 cadence must not drive freshness."""
    intent = health._component_schedule_intent(_orch())
    states = {row["lane_id"]: row["state"] for row in intent["source_intent"]}
    assert states == {"orchestrator-slot": "ACTIVE", "orchestrator-slot-midday": "RETIRED"}


# ---------------------------------------------------------------- freshness against the schedule
def _write_log(tmp_path: Path, when: datetime) -> Path:
    p = tmp_path / "screener_pm.log"
    p.write_text("run complete\n", encoding="utf-8")
    import os

    ts = when.timestamp()
    os.utime(p, (ts, ts))
    return p


@pytest.mark.parametrize(
    "label,last_run,now,expect_stale",
    [
        # Friday 17:30 run, checked on Saturday afternoon: nothing was due, so not stale.
        ("weekend", datetime(2026, 11, 6, 22, 35, tzinfo=timezone.utc), datetime(2026, 11, 7, 18, 0, tzinfo=timezone.utc), False),
        # Same run, checked Monday morning before the next slot: still nothing due.
        ("monday-morning", datetime(2026, 11, 6, 22, 35, tzinfo=timezone.utc), datetime(2026, 11, 9, 13, 0, tzinfo=timezone.utc), False),
        # A weekday evening after the run: fresh.
        ("weekday-evening", datetime(2026, 11, 9, 22, 40, tzinfo=timezone.utc), datetime(2026, 11, 10, 1, 0, tzinfo=timezone.utc), False),
        # The first weekday after the US DST change (2026-11-01): 17:30 ET is now 22:30 UTC.
        ("dst-weekday", datetime(2026, 11, 3, 22, 40, tzinfo=timezone.utc), datetime(2026, 11, 4, 3, 0, tzinfo=timezone.utc), False),
    ],
)
def test_freshness_is_judged_against_the_last_due_run(tmp_path, label, last_run, now, expect_stale):
    log = _write_log(tmp_path, last_run)
    prev_fire = _last_due_before(now)
    result = health._check_log_freshness(str(log), 180, prev_fire=prev_fire, now=now)
    assert result["status"] != "MISSING"
    if expect_stale:
        assert result["status"] == "STALE", (label, result)
    else:
        assert result["status"] != "STALE", (label, result)


def _last_due_before(now: datetime) -> datetime:
    """Most recent weekday 17:30 ET before `now` (the ACTIVE lane's slot), in UTC."""
    from zoneinfo import ZoneInfo

    et = ZoneInfo("America/New_York")
    local = now.astimezone(et)
    for back in range(0, 8):
        day = local.fromordinal(local.toordinal() - back)
        if day.weekday() >= 5:
            continue
        slot = day.replace(hour=17, minute=30, second=0, microsecond=0)
        slot_utc = slot.astimezone(timezone.utc)
        if slot_utc <= now:
            return slot_utc
    raise AssertionError("no slot found")


def test_a_missing_log_is_missing_not_stale(tmp_path):
    result = health._check_log_freshness(str(tmp_path / "absent.log"), 180, now=datetime.now(timezone.utc))
    assert result["status"] == "MISSING" and result["reason"] == "log_missing"


# ─────────────────────── cc3 review (2026-11-02): the fallback must not hide on the operator surface
def test_a_registry_failure_surfaces_on_the_row_the_page_reads(monkeypatch):
    """`schedule_resolved_from` used to be written and never read; `last_error` is what the page renders."""
    comp = dict(_orch())
    comp["schedule_resolved_from"] = "literal_fallback:source_registry_unavailable"
    resolved = health._resolve_component_schedule(comp)
    assert resolved["schedule"] == comp["declared_schedule"] or resolved["schedule"] == comp["schedule"]

    # The row the page renders carries the reason in `last_error` - the column that already persists.
    assert health.schedule_fallback_error(comp) == "schedule literal_fallback:source_registry_unavailable"
    # A resolved component produces no message: the fallback is the only case that speaks.
    assert health.schedule_fallback_error(_orch() | {"schedule_resolved_from": "lane_registry"}) is None
    assert health.schedule_fallback_error({}) is None


def test_the_original_declaration_is_kept_for_drift_comparison():
    comp = _orch()
    assert comp["declared_schedule"] == "0 9,10,12,14,16 * * 1-5"   # what was claimed before the repair
    assert comp["schedule"] == "30 17 * * 1-5"                      # what the ACTIVE lane actually runs
    assert comp["declared_schedule"] != comp["schedule"]


def test_a_missed_monday_run_is_stale(tmp_path):
    """The negative case that makes an all-OK mutation fail: the slot passed and nothing ran."""
    # Friday 17:30 ET run; checked Monday 18:00 ET, after Monday's 17:30 slot was missed.
    last_run = datetime(2026, 11, 6, 22, 35, tzinfo=timezone.utc)
    now = datetime(2026, 11, 9, 23, 0, tzinfo=timezone.utc)
    log = _write_log(tmp_path, last_run)
    result = health._check_log_freshness(str(log), 180, prev_fire=_last_due_before(now), now=now)
    assert result["status"] == "STALE", result
