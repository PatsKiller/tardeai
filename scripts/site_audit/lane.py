"""Site-audit lane: when it runs, which market session it audits, and the guardrails it obeys.

SPEC_SITE_AUDIT_AUTOREMEDIATE_LOOP_20261104.md §2.1 and the live-crawl rule (operator 2026-11-03):

* never cron — the lane is an n8n workflow (the operator's standing rule for new schedules);
* at most 48 h between full scans: Mon/Wed/Fri 06:30 ET pre-market plus Sunday 21:00 ET, which is 48 h at the weekend;
* the week rotates through pre-market / regular / after-hours, so a session-only defect is caught within a week;
* a live crawl has a health gate before every page, >= 4 s pacing, one browser, and aborts on slowdown or a server
  restart (a restart during a crawl raises an incident).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

LANE_ID = "site-audit"
MAX_GAP_HOURS = 48
SESSIONS = ("premarket", "regular", "afterhours")
PACE_SECONDS = 4.0
HEALTH_PATH = "/api/v2/health"


@dataclass(frozen=True)
class Window:
    weekday: int      # Monday=0 … Sunday=6
    hour_et: int
    minute_et: int
    session: str


#: The fixed starts, in ET.
#:
#: The spec names Mon/Wed/Fri 06:30 plus Sun 21:00. Those four cannot satisfy its own ceiling: Friday 06:30 → Sunday 21:00
#: is 62.5 h, not <= 48. Saturday 06:30 is added as the bridge (Fri→Sat 24 h, Sat→Sun 38.5 h, Sun→Mon 9.5 h,
#: Mon→Wed 48 h), which keeps every named slot and makes the ceiling true. If the operator would rather move the Sunday
#: run than add one, that is a one-line change here — the test measures it either way.
WINDOWS: tuple[Window, ...] = (
    Window(weekday=0, hour_et=6, minute_et=30, session="premarket"),
    Window(weekday=2, hour_et=6, minute_et=30, session="premarket"),
    Window(weekday=4, hour_et=6, minute_et=30, session="premarket"),
    Window(weekday=5, hour_et=6, minute_et=30, session="premarket"),
    Window(weekday=6, hour_et=21, minute_et=0, session="premarket"),
)


def session_for_week(week_index: int) -> str:
    """Rotation by ISO week: pre-market → regular → after-hours → pre-market…"""
    return SESSIONS[max(0, int(week_index)) % len(SESSIONS)]


def gap_hours(previous: datetime, current: datetime) -> float:
    return (current - previous).total_seconds() / 3600.0


def exceeds_max_gap(previous: datetime, current: datetime, *, max_hours: float = MAX_GAP_HOURS) -> bool:
    """True when two consecutive runs are further apart than the operator's ceiling."""
    return gap_hours(previous, current) > max_hours


def windows_between(start: datetime, end: datetime) -> list[datetime]:
    """The scheduled starts in [start, end), evaluated in UTC against the ET wall clock."""
    from zoneinfo import ZoneInfo

    et = ZoneInfo("America/New_York")
    out: list[datetime] = []
    day = start.astimezone(et).date()
    last = end.astimezone(et).date()
    while day <= last:
        for w in WINDOWS:
            if day.weekday() != w.weekday:
                continue
            local = datetime(day.year, day.month, day.day, w.hour_et, w.minute_et, tzinfo=et)
            moment = local.astimezone(timezone.utc)
            if start <= moment < end:
                out.append(moment)
        day += timedelta(days=1)
    return sorted(out)


def largest_gap_hours(start: datetime, end: datetime) -> float:
    """The longest stretch between consecutive scheduled runs inside the range (0 with fewer than two)."""
    runs = windows_between(start, end)
    if len(runs) < 2:
        return 0.0
    return max(gap_hours(a, b) for a, b in zip(runs, runs[1:]))


#: Monday of the week the lane was specified; run slots are counted from here so the counter is stable across weeks.
RUN_EPOCH = datetime(2026, 1, 5, tzinfo=timezone.utc)


def run_slot(moment: datetime) -> int:
    """A counter that advances by exactly one at each scheduled run.

    cx-openai-4 R4 on #2648: detail sampling rotated on the ISO week, so the five runs in a week all re-opened the same
    twenty rows and the rest of a long table was never reached — while before the first window of a week a run and its
    predecessor got the same index. Coverage is a property of RUNS, so the rotation counts runs.
    """
    moment = moment.astimezone(timezone.utc)
    year, week, _ = moment.isocalendar()
    week_start = datetime.fromisocalendar(year, week, 1).replace(tzinfo=timezone.utc)
    runs_this_week = len(windows_between(week_start, moment + timedelta(seconds=1)))
    weeks_since_epoch = (week_start - RUN_EPOCH).days // 7
    return weeks_since_epoch * len(WINDOWS) + runs_this_week
