"""Board 8: timer evidence is required before advertising a future run."""
from datetime import datetime, timezone
from subprocess import CalledProcessError

import pytest

from lib import advisory_desk_schedule as desk

NOW = datetime(2026, 10, 24, 22, tzinfo=timezone.utc)
NEXT = datetime(2026, 10, 26, 13, 15, tzinfo=timezone.utc)


def observe(monkeypatch, *, enabled="enabled", active="active", load="loaded", fire=None):
    monkeypatch.setattr(desk, "_SYSTEMD_CACHE", {"at": 0, "iso": None})
    text = (f"LoadState={load}\nActiveState={active}\nUnitFileState={enabled}\n"
            f"NextElapseUSecRealtime={fire if fire is not None else int(NEXT.timestamp() * 1_000_000)}\n")
    calls = []
    def read(args, **kwargs):
        calls.append(args)
        return text
    monkeypatch.setattr(desk.subprocess, "check_output", read)
    return calls


@pytest.mark.parametrize("enabled,active,load,state", [
    ("disabled", "inactive", "loaded", "DISABLED"),
    ("disabled", "active", "loaded", "DISABLED"),
    ("masked", "inactive", "loaded", "DISABLED"),
    ("enabled", "inactive", "loaded", "INACTIVE"),
    ("enabled", "active", "not-found", "MISSING"),
    ("", "", "", "UNKNOWN"),
])
def test_no_next_run_for_nonrunning_timer_even_with_a_timestamp(monkeypatch, enabled, active, load, state):
    calls = observe(monkeypatch, enabled=enabled, active=active, load=load)
    out = desk.schedule_payload(NOW)
    assert out["schedule_state"] == state and out["schedule_reason"]
    assert out["next_run_at"] is None and out["next_run_et"] is None
    assert len(calls) == 1 and calls[0][:3] == ["systemctl", "--user", "show"]
    assert "start" not in calls[0] and "enable" not in calls[0]


@pytest.mark.parametrize("fire", [
    str(int(NEXT.timestamp() * 1_000_000)), NEXT.isoformat(),
    "Mon 2026-10-26 09:15:00 EDT", "Mon 2026-10-26 13:15:00 UTC",
])
def test_enabled_active_timer_uses_observed_fire_and_cached_properties(monkeypatch, fire):
    calls = observe(monkeypatch, fire=fire)
    out = desk.schedule_payload(NOW)
    again = desk.schedule_payload(NOW)
    assert out == again and len(calls) == 1
    assert out["source"] == "systemd" and out["schedule_state"] == "SCHEDULED"
    assert out["next_run_et"] == "Mon 2026-10-26 09:15 EDT"
    assert out["next_run_at"] == "2026-10-26T09:15:00-04:00"


@pytest.mark.parametrize("fire", ["n/a", "0", "not a timestamp", "2026-10-26T09:15:00", "Mon 2026-10-26 09:15:00 EST"])
def test_unverifiable_fire_is_unknown_without_calendar_guess(monkeypatch, fire):
    observe(monkeypatch, fire=fire)
    out = desk.schedule_payload(NOW)
    assert out["schedule_state"] == "UNKNOWN" and out["next_run_at"] is None


def test_elapsed_next_fire_is_not_advertised_until_observed_again(monkeypatch):
    observe(monkeypatch)
    out = desk.schedule_payload(datetime(2026, 10, 26, 14, tzinfo=timezone.utc))
    assert out["schedule_state"] == "UNKNOWN" and out["next_run_at"] is None
    assert "future" in out["schedule_reason"]


def test_unavailable_timer_query_is_a_visible_gap(monkeypatch):
    monkeypatch.setattr(desk, "_SYSTEMD_CACHE", {"at": 0, "iso": None})
    def fail(*args, **kwargs):
        raise CalledProcessError(1, "systemctl")
    monkeypatch.setattr(desk.subprocess, "check_output", fail)
    out = desk.schedule_payload(NOW)
    assert out["schedule_state"] == "UNKNOWN" and out["next_run_at"] is None
    assert out["schedule_reason"] == "Timer state could not be observed."


def test_clock_cache_refreshes_after_ttl(monkeypatch):
    calls = observe(monkeypatch)
    clock = iter([100, 130, 161])
    monkeypatch.setattr(desk.time, "monotonic", lambda: next(clock))
    for _ in range(3):
        desk.schedule_payload(NOW)
    assert len(calls) == 2
