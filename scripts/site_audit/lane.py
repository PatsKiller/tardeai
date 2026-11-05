"""Site-audit lane: when it runs, which market session it audits, and the guardrails it obeys.

SPEC_SITE_AUDIT_AUTOREMEDIATE_LOOP_20261104.md §2.1 and the live-crawl rule (operator 2026-11-03):

* never cron — the lane is an n8n workflow (the operator's standing rule for new schedules);
* at most 48 h between full scans: Mon/Wed/Fri after the close plus a Saturday bridge and Sunday 21:00 ET;
* a live crawl has a health gate before every page, >= 4 s pacing, one browser, and aborts on slowdown or a server
  restart (a restart during a crawl raises an incident).

The spec's original Mon/Wed/Fri 06:30 ET pre-market starts sit INSIDE the AGENTS §28.8 boundary (no agent traffic to
the live server 04:00–16:15 ET on a market day), and the codex-cloud review at eae410a3b found that. The live runs are
therefore after the close; in-session (pre-market/regular) coverage is served by a fixture/replay backend, which the
gate in `live_access_violation()` deliberately permits. The operator's 48 h ceiling and the named Sunday 21:00 slot are
kept, and the Saturday bridge is what makes the weekend gap <= 48 h.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, time as wall_time, timedelta, timezone
from urllib.parse import urlparse

LANE_ID = "site-audit"
MAX_GAP_HOURS = 48
SESSIONS = ("premarket", "regular", "afterhours")
PACE_SECONDS = 4.0
HEALTH_PATH = "/api/v2/health"

#: AGENTS §28.8: no agent traffic to the live server 04:00–16:15 ET on a market day. Unsure means live.
LIVE_CRAWL_BLOCK_START_ET = wall_time(4, 0)
LIVE_CRAWL_BLOCK_END_ET = wall_time(16, 15)
#: The after-close live-smoke acknowledgement a live crawl outside the block must carry.
LIVE_AFTER_CLOSE_ENV = "TRADEAI_LIVE_SMOKE_AFTER_CLOSE"
#: The production Command Center port. A loopback fixture/replay backend runs on another port and is permitted.
LIVE_SERVER_PORT = 7777


@dataclass(frozen=True)
class Window:
    weekday: int      # Monday=0 … Sunday=6
    hour_et: int
    minute_et: int
    session: str


#: The fixed starts, in ET.
#:
#: The spec names Mon/Wed/Fri 06:30 (pre-market) plus Sun 21:00. 06:30 is inside the prohibited 04:00–16:15 window,
#: so the live runs are moved to the first safe after-hours slot (17:30). The 48 h ceiling still needs a Saturday
#: bridge: Fri 17:30 -> Sun 21:00 alone is 51.5 h. With the bridge the gaps are Sun->Mon 20.5 h, Mon->Wed 48 h,
#: Wed->Fri 48 h, Fri->Sat 24 h, Sat->Sun 27.5 h. If the operator would rather move the Sunday run than add one,
#: that is a one-line change here — the test measures the ceiling either way.
WINDOWS: tuple[Window, ...] = (
    Window(weekday=0, hour_et=17, minute_et=30, session="afterhours"),
    Window(weekday=2, hour_et=17, minute_et=30, session="afterhours"),
    Window(weekday=4, hour_et=17, minute_et=30, session="afterhours"),
    Window(weekday=5, hour_et=17, minute_et=30, session="afterhours"),
    Window(weekday=6, hour_et=21, minute_et=0, session="afterhours"),
)


def is_live_base(base: str) -> bool:
    """Whether `base` names the live production server the §28.8 boundary governs.

    The production Command Center listens on the loopback port 7777. A fixture/replay backend is a loopback
    server on ANOTHER port, which is how the tests and the in-session replay runs serve recorded data. Anything
    that cannot be parsed as an http(s) URL, and any non-loopback host, is treated as live ("unsure means live").
    """
    try:
        parsed = urlparse(str(base or ""))
    except Exception:  # noqa: BLE001 — unparseable is not proof of a fixture backend
        return True
    if parsed.scheme not in ("http", "https"):
        return True
    try:
        port = parsed.port
    except ValueError:  # a malformed port is not a fixture backend
        return True
    if port == LIVE_SERVER_PORT:
        return True
    host = (parsed.hostname or "").lower()
    return host not in ("127.0.0.1", "localhost", "::1")


def live_access_blocked(now: datetime | None = None) -> str | None:
    """None when a LIVE crawl may touch the server now; otherwise the reason it may not.

    AGENTS §28.8: no agent traffic to the live server 04:00–16:15 ET on a market day. Holidays and weekends are
    not market days (the market_session calendar owns that judgement). This is a wall-clock rule, not a
    session-label rule: `TRADEAI_LIVE_SMOKE_AFTER_CLOSE=1` does not open the blocked window.
    """
    from zoneinfo import ZoneInfo

    from market_session import is_trading_day

    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    if not is_trading_day(moment):
        return None
    et_time = moment.astimezone(ZoneInfo("America/New_York")).time()
    if LIVE_CRAWL_BLOCK_START_ET <= et_time < LIVE_CRAWL_BLOCK_END_ET:
        return (f"live server access is forbidden "
                f"{LIVE_CRAWL_BLOCK_START_ET.strftime('%H:%M')}-{LIVE_CRAWL_BLOCK_END_ET.strftime('%H:%M')} ET "
                f"on a market day (AGENTS §28.8); use a fixture/replay backend")
    return None


def live_access_violation(base: str, *, now: datetime | None = None,
                          environ: dict[str, str] | None = None) -> str | None:
    """The reason this base must not be crawled now, or None when it may be.

    Fixtures/replay backends are always permitted. A live base is refused inside the §28.8 window, and outside it
    requires the operator's after-close acknowledgement so that a live run is a deliberate act, not an accident.
    """
    if not is_live_base(base):
        return None
    blocked = live_access_blocked(now)
    if blocked:
        return blocked
    env = os.environ if environ is None else environ
    if str(env.get(LIVE_AFTER_CLOSE_ENV) or "").strip() != "1":
        return (f"a live crawl outside 04:00-16:15 ET requires {LIVE_AFTER_CLOSE_ENV}=1 (AGENTS §28.8)")
    return None


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
