"""cio_market_session.py — injectable deterministic NYSE session service.

No network. Holidays, weekends, DST, regular open/close, early closes, pre/post.

Returned `market_session` shape:
  exchange, session_date, state PRE|RTH|POST|CLOSED,
  official_open, official_close, early_close, source

Authority: READ_ONLY_ADVISORY.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Callable, Optional, Union
from zoneinfo import ZoneInfo

MARKET_SESSION_VERSION = "cio_nyse_session_1.0.0"
AUTHORITY = "READ_ONLY_ADVISORY"
EXCHANGE = "XNYS"
EXCHANGE_TZ_NAME = "America/New_York"

STATE_PRE = "PRE"
STATE_RTH = "RTH"
STATE_POST = "POST"
STATE_CLOSED = "CLOSED"
SESSION_STATES = frozenset({STATE_PRE, STATE_RTH, STATE_POST, STATE_CLOSED})

PREMARKET_START = time(4, 0)
RTH_OPEN = time(9, 30)
RTH_CLOSE = time(16, 0)
EARLY_CLOSE_TIME = time(13, 0)
POST_END = time(20, 0)

DateLike = Union[date, datetime, str]
HolidaysFn = Callable[[int], set[date]]
EarlyClosesFn = Callable[[int], set[date]]


def _as_date(value: DateLike) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """n-th (1-based) weekday of a month; weekday Mon=0 … Sun=6; n=-1 last."""
    if n > 0:
        d = date(year, month, 1)
        d += timedelta(days=(weekday - d.weekday()) % 7)
        return d + timedelta(weeks=n - 1)
    d = date(year + (month == 12), (month % 12) + 1, 1) - timedelta(days=1)
    return d - timedelta(days=(d.weekday() - weekday) % 7)


def _easter(year: int) -> date:
    """Gregorian Easter (anonymous computus)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    g = (8 * b + 13) // 25
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)


def _observed_weekday(d: date) -> date:
    """NYSE weekend observance: Sat → preceding Fri, Sun → following Mon.

    January 1 on Saturday is *not* observed the prior Friday (NYSE Rule 7.2).
    """
    if d.weekday() == 5:
        return d - timedelta(days=1)
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


def nyse_holidays(year: int) -> set[date]:
    """Full-closure NYSE dates for `year` (no network)."""
    days: set[date] = set()
    jan1 = date(year, 1, 1)
    if jan1.weekday() == 6:
        days.add(date(year, 1, 2))
    elif jan1.weekday() != 5:
        days.add(jan1)
    days.add(_nth_weekday(year, 1, 0, 3))  # MLK
    days.add(_nth_weekday(year, 2, 0, 3))  # Washington's Birthday
    days.add(_easter(year) - timedelta(days=2))  # Good Friday
    days.add(_nth_weekday(year, 5, 0, -1))  # Memorial Day
    if year >= 2022:
        days.add(_observed_weekday(date(year, 6, 19)))  # Juneteenth
    days.add(_observed_weekday(date(year, 7, 4)))  # Independence Day
    days.add(_nth_weekday(year, 9, 0, 1))  # Labor Day
    days.add(_nth_weekday(year, 11, 3, 4))  # Thanksgiving
    days.add(_observed_weekday(date(year, 12, 25)))  # Christmas
    return days


def nyse_early_closes(year: int) -> set[date]:
    """NYSE 1:00 pm ET early-close dates for `year`.

    July 3 (weekday and not itself a holiday), the Friday after Thanksgiving,
    and Christmas Eve (weekday and not itself a holiday).
    """
    hols = nyse_holidays(year)
    out: set[date] = set()
    for d in (date(year, 7, 3), date(year, 12, 24)):
        if d.weekday() < 5 and d not in hols:
            out.add(d)
    thanks = _nth_weekday(year, 11, 3, 4)
    out.add(thanks + timedelta(days=1))
    return out


def _to_dates(values: Optional[Any]) -> set[date]:
    if not values:
        return set()
    out: set[date] = set()
    for v in values:
        out.add(_as_date(v))
    return out


class NYSESessionService:
    """Deterministic, injectable NYSE session calendar. No network I/O."""

    def __init__(
        self,
        *,
        tzinfo: Optional[Any] = None,
        holidays_for_year: Optional[HolidaysFn] = None,
        early_closes_for_year: Optional[EarlyClosesFn] = None,
        extra_holidays: Optional[Any] = None,
        extra_early_closes: Optional[Any] = None,
    ) -> None:
        self.tz = tzinfo or ZoneInfo(EXCHANGE_TZ_NAME)
        self._holidays_fn = holidays_for_year or nyse_holidays
        self._early_fn = early_closes_for_year or nyse_early_closes
        self._extra_holidays = _to_dates(extra_holidays)
        self._extra_early = _to_dates(extra_early_closes)
        self._cache: dict[int, tuple[set[date], set[date]]] = {}

    def holidays(self, year: int) -> set[date]:
        hols, _ = self._year(year)
        return set(hols)

    def early_closes(self, year: int) -> set[date]:
        _, early = self._year(year)
        return set(early)

    def is_holiday(self, value: DateLike) -> bool:
        d = _as_date(value)
        return d in self.holidays(d.year)

    def is_early_close_day(self, value: DateLike) -> bool:
        d = _as_date(value)
        return d in self.early_closes(d.year)

    def is_trading_day(self, value: DateLike) -> bool:
        d = _as_date(value)
        return d.weekday() < 5 and d not in self.holidays(d.year)

    def _year(self, year: int) -> tuple[set[date], set[date]]:
        cached = self._cache.get(year)
        if cached is not None:
            return cached
        hols = set(self._holidays_fn(year)) | {d for d in self._extra_holidays if d.year == year}
        early = set(self._early_fn(year)) | {d for d in self._extra_early if d.year == year}
        early -= hols
        pair = (hols, early)
        self._cache[year] = pair
        return pair

    def _aware(self, now: Optional[datetime]) -> datetime:
        n = now if now is not None else datetime.now(timezone.utc)
        if n.tzinfo is None:
            n = n.replace(tzinfo=timezone.utc)
        return n.astimezone(self.tz)

    def official_bounds(self, session_date: date) -> tuple[Optional[datetime], Optional[datetime], bool]:
        """Return (official_open, official_close, early_close) in exchange tz."""
        if not self.is_trading_day(session_date):
            return None, None, False
        early = self.is_early_close_day(session_date)
        close_t = EARLY_CLOSE_TIME if early else RTH_CLOSE
        open_dt = datetime.combine(session_date, RTH_OPEN, tzinfo=self.tz)
        close_dt = datetime.combine(session_date, close_t, tzinfo=self.tz)
        return open_dt, close_dt, early

    def session_at(self, now: Optional[datetime] = None) -> dict[str, Any]:
        et = self._aware(now)
        session_date = et.date()
        t = et.time()
        holiday = self.is_holiday(session_date)
        weekend = session_date.weekday() >= 5
        trading = self.is_trading_day(session_date)
        open_dt, close_dt, early = self.official_bounds(session_date)

        if not trading:
            state = STATE_CLOSED
        elif t < PREMARKET_START:
            state = STATE_CLOSED
        elif t < RTH_OPEN:
            state = STATE_PRE
        elif close_dt is not None and t < close_dt.time():
            state = STATE_RTH
        elif t < POST_END:
            state = STATE_POST
        else:
            state = STATE_CLOSED

        return {
            "exchange": EXCHANGE,
            "session_date": session_date.isoformat(),
            "state": state,
            "official_open": open_dt.isoformat() if open_dt else None,
            "official_close": close_dt.isoformat() if close_dt else None,
            "early_close": bool(early),
            "source": MARKET_SESSION_VERSION,
            # Diagnostics — not required by the contract
            "holiday": holiday,
            "weekend": weekend,
            "is_trading_day": trading,
            "tz": EXCHANGE_TZ_NAME,
            "authority": AUTHORITY,
        }


_DEFAULT_SERVICE: Optional[NYSESessionService] = None


def get_session_service() -> NYSESessionService:
    global _DEFAULT_SERVICE
    if _DEFAULT_SERVICE is None:
        _DEFAULT_SERVICE = NYSESessionService()
    return _DEFAULT_SERVICE


def set_session_service(service: Optional[NYSESessionService]) -> None:
    """Inject (or reset) the process-wide default service. Tests only."""
    global _DEFAULT_SERVICE
    _DEFAULT_SERVICE = service


def get_market_session(
    now: Optional[datetime] = None,
    *,
    service: Optional[NYSESessionService] = None,
) -> dict[str, Any]:
    """Session at `now` via the injected or default NYSE service."""
    svc = service if service is not None else get_session_service()
    return svc.session_at(now)


def market_session(
    now: Optional[datetime] = None,
    *,
    service: Optional[NYSESessionService] = None,
) -> dict[str, Any]:
    """Alias of get_market_session (operator-facing name)."""
    return get_market_session(now, service=service)


def is_rth(now: Optional[datetime] = None, *, service: Optional[NYSESessionService] = None) -> bool:
    return get_market_session(now, service=service).get("state") == STATE_RTH


def is_trading_day(now: Optional[datetime] = None, *, service: Optional[NYSESessionService] = None) -> bool:
    return bool(get_market_session(now, service=service).get("is_trading_day"))
