"""NYSE trading sessions for the Market Risk Engine — one helper for every "how many sessions" question.

Hysteresis (``scoring._hysteresis``) and episode resolution (``escalation.observe``) both count sessions spent below a
tier. A session counts only when it is a real NYSE trading day AND its close has passed (16:00 ET, 13:00 ET on early
closes). Weekends and holidays never count (review of #2362, B4: Sat/Sun and Thanksgiving were counted, so an ORANGE
fell to BLUE on a Sunday after one trading session). The calendar is ``cio_market_session.nyse_holidays`` /
``nyse_early_closes`` — the same no-network NYSE calendar the CIO uses; nothing is hardcoded here.
"""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

try:
    from lib.cio_market_session import nyse_early_closes, nyse_holidays
except ImportError:  # pragma: no cover - imported as scripts.lib
    from scripts.lib.cio_market_session import nyse_early_closes, nyse_holidays

ET = ZoneInfo("America/New_York")
UTC = timezone.utc
REGULAR_CLOSE = time(16, 0)
EARLY_CLOSE = time(13, 0)


def is_trading_day(d: date) -> bool:
    return d.weekday() < 5 and d not in nyse_holidays(d.year)


def close_time(d: date) -> time:
    return EARLY_CLOSE if d in nyse_early_closes(d.year) else REGULAR_CLOSE


def completed_session(now: datetime) -> str | None:
    """ISO date of the session that has closed as of ``now`` when ``now`` falls on that trading day after its close;
    None on weekends, holidays and before the close. Callers append it once to their ``below_sessions`` list."""
    local = now.astimezone(ET)
    d = local.date()
    if not is_trading_day(d):
        return None
    return d.isoformat() if local.time() >= close_time(d) else None


OVERNIGHT_START = time(20, 0)  # the 24/5 overnight session (Blue Ocean ATS; Schwab/Robinhood overnight) 20:00-04:00 ET
PREMARKET_START = time(4, 0)
REGULAR_OPEN = time(9, 30)


def _next_trading_day(d: date) -> date:
    from datetime import timedelta

    n = d + timedelta(days=1)
    while not is_trading_day(n):
        n += timedelta(days=1)
    return n


def session_label(now: datetime) -> str:
    """US equity session of ``now``: ``premarket`` 04:00-09:30, ``regular`` 09:30-close (13:00 on early closes),
    ``afterhours`` close-20:00, ``overnight`` 20:00-04:00 when a trading day follows (Sunday 20:00 to Friday 04:00 —
    the 24/5 session), else ``closed`` (weekends, holidays, Friday 20:00 to Sunday 20:00)."""
    local = now.astimezone(ET)
    d, t = local.date(), local.time()
    if is_trading_day(d):
        if PREMARKET_START <= t < REGULAR_OPEN:
            return "premarket"
        if REGULAR_OPEN <= t < close_time(d):
            return "regular"
        if close_time(d) <= t < OVERNIGHT_START:
            return "afterhours"
        if t < PREMARKET_START:
            return "overnight"  # 00:00-04:00 of a trading day: the night session that opened the evening before
    if t >= OVERNIGHT_START:
        from datetime import timedelta

        nxt = d + timedelta(days=1)
        return "overnight" if is_trading_day(nxt) else "closed"
    return "closed"


def market_hours_between(start: datetime, end: datetime, *, reopen: time | None = None) -> float:
    """Hours from ``start`` to ``end`` that the market could have produced newer information in. A whole calendar day
    (ET) that is not an NYSE trading day (weekend, holiday) does not count, except from ``reopen`` (e.g. 18:00, when
    index futures and Asia open on Sunday) when the next calendar day is a trading day. Friday 16:00 -> Sunday 18:30
    is 8.5 hours with ``reopen=18:00`` (Friday 16:00-24:00 plus Sunday 18:00-18:30), not 50.5. Never negative."""
    from datetime import timedelta

    if end <= start:
        return 0.0
    a, b = start.astimezone(ET), end.astimezone(ET)
    a_utc, b_utc = start.astimezone(UTC), end.astimezone(UTC)
    total = 0.0
    day = a.date()
    while day <= b.date():
        day_start = datetime.combine(day, time(0, 0), ET)
        day_end = datetime.combine(day + timedelta(days=1), time(0, 0), ET)
        if is_trading_day(day):
            lo = day_start
        elif reopen is not None and is_trading_day(day + timedelta(days=1)):
            lo = datetime.combine(day, reopen, ET)
        else:
            day += timedelta(days=1)
            continue
        # compare and subtract in UTC: two datetimes sharing one ZoneInfo subtract as naive wall times, which would
        # miscount the DST change (2026-11-01 is 25 hours long)
        lo, hi = max(lo.astimezone(UTC), a_utc), min(day_end.astimezone(UTC), b_utc)
        if hi > lo:
            total += (hi - lo).total_seconds() / 3600.0
        day += timedelta(days=1)
    return total


def last_closed_session(now: datetime) -> date:
    """The most recent NYSE trading day whose close (plus the 59-second closing-snapshot cutoff) had passed by
    ``now``: the session an extended-hours print must be measured against (after-hours on D -> D; Sunday overnight
    and Monday pre-market -> Friday; the day after a holiday -> the day before it)."""
    from datetime import timedelta

    local = now.astimezone(ET)
    d = local.date()
    for _ in range(15):
        if is_trading_day(d):
            cl = close_time(d)
            if d < local.date() or local.time() > time(cl.hour, cl.minute, 59):
                return d
        d -= timedelta(days=1)
    return d
