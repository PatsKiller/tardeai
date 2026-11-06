"""Overnight and Sunday futures-open sessions for ``market_quotes_extended`` (Market Risk Engine, DSN-20261031).

Why: the engine went blind from 20:00 to 04:00 ET and from the Sunday 18:00 futures open (operator, 2026-10-31:
"No excuses"). #2384's store accepted only ``premarket`` and ``afterhours``; this module defines the two sessions
added by ``migrations/2026_10_31_market_quotes_extended_overnight.sql``:

* ``overnight``    -- ``afterhours_close_et`` (20:00) up to, not including, ``premarket_open_et`` (04:00) ET, from
  Sunday 20:00 to Friday 04:00. Friday 20:00 to Sunday 20:00 has no overnight session. A print at exactly 04:00:00
  is pre-market (``market_quotes_extended.session_of``), never overnight.
* ``futures_open`` -- Sunday ``futures_open_et`` (18:00) up to 20:00 ET, futures only (``futures_open_asset_types``).
  It is kept apart from ``overnight`` so that a row labelled ``overnight`` always lies in the 20:00-04:00 window,
  and a reader can tell that equities could not trade when the row was printed.

The trading date (``session_date``) of both is the NEXT NYSE trading day: the session the night leads into (the
futures convention). The reference session is the trading day before it (``previous_session``): the last regular close
before the night began. Weekends, holidays and early closes come from ``scripts/market_session.py``
(``market_holidays``), the same calendar that ``scripts/market_day_gate.sh`` uses. Times come from
``config/market_quotes_extended.json``; nothing is hardcoded here.

Pure: no network, no database. AUTHORITY: READ_ONLY_ADVISORY. MBI_BEHAVIOR = 0.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

try:
    from scripts.market_session import market_holidays
except ImportError:  # imported with scripts/ on sys.path (cron entries, offhours_quotes)
    from market_session import market_holidays  # type: ignore[no-redef]

ET = ZoneInfo("America/New_York")
OVERNIGHT = "overnight"
FUTURES_OPEN = "futures_open"
SESSIONS = (OVERNIGHT, FUTURES_OPEN)
_DAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
_MAX_CLOSED_DAYS = 10  # longest NYSE closure run plus margin; a calendar bug fails loudly instead of looping


def _hhmm(s: str) -> time:
    h, m = str(s).split(":")
    return time(int(h), int(m))


def _spec(cfg: dict[str, Any]) -> dict[str, Any]:
    o = cfg.get("overnight")
    if not isinstance(o, dict):
        raise ValueError("config/market_quotes_extended.json: 'overnight' section missing")
    return o


def is_trading_day(d: date) -> bool:
    return d.weekday() < 5 and d.isoformat() not in market_holidays(d.year)


def next_trading_day(d: date) -> date:
    """The first NYSE trading day on or after ``d``."""
    for i in range(_MAX_CLOSED_DAYS):
        c = d + timedelta(days=i)
        if is_trading_day(c):
            return c
    raise ValueError(f"no NYSE trading day within {_MAX_CLOSED_DAYS} days of {d}")


def previous_trading_day(d: date) -> date:
    """The last NYSE trading day strictly before ``d``: the reference session of a night leading into ``d``."""
    for i in range(1, _MAX_CLOSED_DAYS + 1):
        c = d - timedelta(days=i)
        if is_trading_day(c):
            return c
    raise ValueError(f"no NYSE trading day within {_MAX_CLOSED_DAYS} days before {d}")


def _overnight_start_weekdays(o: dict[str, Any]) -> set[int]:
    """Weekdays a 20:00 overnight may START on: from ``first_open_day`` to the day before ``last_close_day``."""
    first, last = _DAYS[str(o["first_open_day"]).lower()], _DAYS[str(o["last_close_day"]).lower()]
    out, d = set(), first
    for _ in range(7):
        if (d + 1) % 7 == last:
            out.add(d)
            return out
        out.add(d)
        d = (d + 1) % 7
    raise ValueError("overnight first_open_day/last_close_day do not form a week window")


def label(instant: datetime, cfg: dict[str, Any], asset_type: str = "") -> tuple[str, date] | None:
    """(session, trading_date) for a print at ``instant`` (tz-aware) in an overnight or futures-open session, else
    None. ``cfg`` is ``config/market_quotes_extended.json``."""
    if instant.tzinfo is None:
        raise ValueError("instant must be timezone-aware")
    o = _spec(cfg)
    et = instant.astimezone(ET)
    d, t = et.date(), et.time().replace(tzinfo=None)
    opens, closes = _hhmm(cfg["afterhours_close_et"]), _hhmm(cfg["premarket_open_et"])
    start_day = d if t >= opens else (d - timedelta(days=1) if t < closes else None)
    if start_day is not None and start_day.weekday() in _overnight_start_weekdays(o):
        return OVERNIGHT, next_trading_day(start_day + timedelta(days=1))
    fo_types = {str(x).upper() for x in o.get("futures_open_asset_types") or []}
    if (
        str(asset_type).upper() in fo_types
        and d.weekday() == _DAYS[str(o["futures_open_day"]).lower()]
        and _hhmm(o["futures_open_et"]) <= t < opens
    ):
        return FUTURES_OPEN, next_trading_day(d + timedelta(days=1))
    return None


def reference_date(trading_date: date) -> date:
    """The session whose close is the reference for a night leading into ``trading_date``."""
    return previous_trading_day(trading_date)
