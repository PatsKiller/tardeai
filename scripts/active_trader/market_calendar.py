"""Stage 5 harness — deterministic US equity (NYSE/Nasdaq) exchange calendar.

Dependency-free, checked-in dataset for the supported years {2026, 2027}. Fails CLOSED
outside that range (never guesses "weekday == market day"). Holidays follow NYSE rules
with weekend observance; early-close (half) days are an explicit dataset. Times are
timezone-aware America/New_York.

Used by the premarket observation harness to (a) pick the next qualifying session and
(b) confirm a target date is a normal 09:30 open with a close at/after 10:05 ET.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, asdict
from typing import Optional, Protocol, runtime_checkable
from zoneinfo import ZoneInfo

CALENDAR_VERSION = "nyse-checkedin-1"
CALENDAR_SOURCE = "NYSE published holiday & early-close schedule (2026, 2027)"
CALENDAR_SOURCE_RETRIEVED_AT = "2026-07-23"
MARKET_TZ = "America/New_York"
SUPPORTED_YEARS = (2026, 2027)

REGULAR_OPEN = _dt.time(9, 30)
REGULAR_CLOSE = _dt.time(16, 0)
EARLY_CLOSE = _dt.time(13, 0)

# Observation eligibility constants (controller §6.3)
PREFLIGHT = _dt.time(6, 55)
CAPTURE_START = _dt.time(7, 0)
REQUIRED_RTH_COMPLETION = _dt.time(10, 5)


class CalendarError(RuntimeError):
    pass


class UnsupportedYearError(CalendarError):
    pass


# ---- holiday rules (evaluated only within supported years) -----------------

def _easter(year: int) -> _dt.date:
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return _dt.date(year, month, day)


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> _dt.date:
    if n > 0:
        d = _dt.date(year, month, 1)
        return d + _dt.timedelta(days=(weekday - d.weekday()) % 7 + 7 * (n - 1))
    last = (_dt.date(year, 12, 31) if month == 12
            else _dt.date(year, month + 1, 1) - _dt.timedelta(days=1))
    return last - _dt.timedelta(days=(last.weekday() - weekday) % 7)


def _observed(d: _dt.date) -> _dt.date:
    if d.weekday() == 5:
        return d - _dt.timedelta(days=1)
    if d.weekday() == 6:
        return d + _dt.timedelta(days=1)
    return d


def _full_holidays(year: int) -> set[_dt.date]:
    h = {
        _observed(_dt.date(year, 1, 1)),
        _nth_weekday(year, 1, 0, 3),
        _nth_weekday(year, 2, 0, 3),
        _easter(year) - _dt.timedelta(days=2),
        _nth_weekday(year, 5, 0, -1),
        _observed(_dt.date(year, 6, 19)),
        _observed(_dt.date(year, 7, 4)),
        _nth_weekday(year, 9, 0, 1),
        _nth_weekday(year, 11, 3, 4),
        _observed(_dt.date(year, 12, 25)),
    }
    return h


# Explicit early-close (1:00 PM ET) dataset for the supported years.
_EARLY_CLOSES: dict[int, set[_dt.date]] = {
    2026: {_dt.date(2026, 11, 27), _dt.date(2026, 12, 24)},   # day after Thanksgiving; Christmas Eve
    2027: {_dt.date(2027, 11, 26)},                            # day after Thanksgiving
}


# ---- typed interface -------------------------------------------------------

@dataclass(frozen=True)
class SessionInfo:
    exchange: str
    calendar_version: str
    local_date: str
    timezone: str
    is_session: bool
    open_time: Optional[str]          # ISO tz-aware, or None on a non-session day
    close_time: Optional[str]
    is_early_close: bool
    source: str
    source_retrieved_at: str
    supported_year: bool

    def as_dict(self) -> dict:
        return asdict(self)

    def qualifies_for_observation(self) -> bool:
        """Normal 09:30 open and a close at/after 10:05 ET (early-close days still qualify)."""
        if not self.is_session or not self.open_time or not self.close_time:
            return False
        o = _dt.datetime.fromisoformat(self.open_time)
        c = _dt.datetime.fromisoformat(self.close_time)
        return (o.timetz().replace(tzinfo=None) == REGULAR_OPEN
                and c.timetz().replace(tzinfo=None) >= REQUIRED_RTH_COMPLETION)


@runtime_checkable
class ExchangeCalendar(Protocol):
    def session_for_date(self, date: _dt.date) -> SessionInfo: ...
    def next_session(self, after: _dt.datetime) -> SessionInfo: ...
    def is_session(self, date: _dt.date) -> bool: ...


class NyseCalendar:
    """Deterministic checked-in NYSE calendar for SUPPORTED_YEARS. Fails closed elsewhere."""

    exchange = "XNYS"

    def _guard_year(self, year: int) -> None:
        if year not in SUPPORTED_YEARS:
            raise UnsupportedYearError(
                f"year {year} outside supported range {SUPPORTED_YEARS} — fail closed")

    def is_session(self, date: _dt.date) -> bool:
        self._guard_year(date.year)
        return date.weekday() < 5 and date not in _full_holidays(date.year)

    def session_for_date(self, date: _dt.date) -> SessionInfo:
        self._guard_year(date.year)
        tz = ZoneInfo(MARKET_TZ)
        is_sess = self.is_session(date)
        early = date in _EARLY_CLOSES.get(date.year, set())
        open_dt = close_dt = None
        if is_sess:
            open_dt = _dt.datetime.combine(date, REGULAR_OPEN, tz).isoformat()
            close_dt = _dt.datetime.combine(date, EARLY_CLOSE if early else REGULAR_CLOSE, tz).isoformat()
        return SessionInfo(
            exchange=self.exchange, calendar_version=CALENDAR_VERSION,
            local_date=date.isoformat(), timezone=MARKET_TZ, is_session=is_sess,
            open_time=open_dt, close_time=close_dt, is_early_close=is_sess and early,
            source=CALENDAR_SOURCE, source_retrieved_at=CALENDAR_SOURCE_RETRIEVED_AT,
            supported_year=True)

    def next_session(self, after: _dt.datetime) -> SessionInfo:
        """First trading session strictly after `after`'s local date."""
        d = after.astimezone(ZoneInfo(MARKET_TZ)).date() + _dt.timedelta(days=1)
        while True:
            self._guard_year(d.year)
            if self.is_session(d):
                return self.session_for_date(d)
            d += _dt.timedelta(days=1)

    def next_observation_session(self, after: _dt.datetime) -> SessionInfo:
        """First session at/after `after` that qualifies for observation (09:30 open, >=10:05 close)."""
        s = self.next_session(after)
        while not s.qualifies_for_observation():
            s = self.next_session(_dt.datetime.fromisoformat(s.open_time))
        return s
