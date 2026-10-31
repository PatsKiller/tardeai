"""NYSE trading sessions for the Market Risk Engine — one helper for every "how many sessions" question.

Hysteresis (``scoring._hysteresis``) and episode resolution (``escalation.observe``) both count sessions spent below a
tier. A session counts only when it is a real NYSE trading day AND its close has passed (16:00 ET, 13:00 ET on early
closes). Weekends and holidays never count (review of #2362, B4: Sat/Sun and Thanksgiving were counted, so an ORANGE
fell to BLUE on a Sunday after one trading session). The calendar is ``cio_market_session.nyse_holidays`` /
``nyse_early_closes`` — the same no-network NYSE calendar the CIO uses; nothing is hardcoded here.
"""

from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

try:
    from lib.cio_market_session import nyse_early_closes, nyse_holidays
except ImportError:  # pragma: no cover - imported as scripts.lib
    from scripts.lib.cio_market_session import nyse_early_closes, nyse_holidays

ET = ZoneInfo("America/New_York")
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
