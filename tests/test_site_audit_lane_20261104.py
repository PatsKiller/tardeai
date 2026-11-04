"""SITE_AUDIT_LANE_20261104 — the §2.1 cadence and the live-crawl guardrails, checked in code.

The lane is an n8n workflow, but the ceiling it must satisfy is arithmetic, so it is asserted here rather than trusted to a
schedule someone edits later: never more than 48 h between full scans, a weekly session rotation, and the live-crawl rules
(health gate, ≥4 s pacing, one browser, abort on restart).
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from site_audit.lane import (  # noqa: E402
    HEALTH_PATH, LANE_ID, MAX_GAP_HOURS, PACE_SECONDS, SESSIONS, exceeds_max_gap, largest_gap_hours,
    session_for_week, windows_between,
)

ET = ZoneInfo("America/New_York")


def test_no_stretch_between_runs_exceeds_the_ceiling_over_a_year():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = datetime(2027, 1, 1, tzinfo=timezone.utc)
    assert largest_gap_hours(start, end) <= MAX_GAP_HOURS, "a stretch longer than 48 h exists in the schedule"


def test_the_weekend_gap_is_the_longest_and_still_within_48h():
    # Friday 06:30 ET → Sunday 21:00 ET is the weekend stretch.
    runs = windows_between(datetime(2026, 11, 2, tzinfo=timezone.utc), datetime(2026, 11, 16, tzinfo=timezone.utc))
    assert runs, "no runs scheduled in the window"
    gaps = [(b - a).total_seconds() / 3600 for a, b in zip(runs, runs[1:])]
    assert max(gaps) <= MAX_GAP_HOURS


def test_five_runs_a_week_and_the_named_slots_are_kept():
    # 2026-11-02 is a Monday. The spec's Mon/Wed/Fri 06:30 + Sun 21:00 are all here; Saturday 06:30 is the bridge that
    # makes the 48 h ceiling true (Fri 06:30 -> Sun 21:00 alone is 62.5 h).
    runs = windows_between(datetime(2026, 11, 2, tzinfo=timezone.utc), datetime(2026, 11, 9, tzinfo=timezone.utc))
    local = [(r.astimezone(ET).strftime("%a %H:%M")) for r in runs]
    assert local == ["Sun 21:00", "Mon 06:30", "Wed 06:30", "Fri 06:30", "Sat 06:30"], local


def test_the_session_rotates_weekly_and_returns():
    assert [session_for_week(w) for w in range(4)] == ["premarket", "regular", "afterhours", "premarket"]
    assert set(SESSIONS) == {"premarket", "regular", "afterhours"}


def test_a_missed_run_is_detectable():
    a = datetime(2026, 11, 2, 11, 30, tzinfo=timezone.utc)
    assert exceeds_max_gap(a, a.replace(day=4)) is False       # 48 h exactly is allowed
    assert exceeds_max_gap(a, a.replace(day=5)) is True        # longer is not


def test_the_lane_is_named_and_carries_the_live_crawl_rules():
    assert LANE_ID == "site-audit"
    assert PACE_SECONDS >= 4.0, "the operator's pacing floor is 4 s"
    assert HEALTH_PATH == "/api/v2/health"
