"""cio_market_calendar.py — Phases 11–16 US equity calendar helpers.

Weekday / weekend. Prefer pandas_market_calendars or exchange_calendars when
installed; otherwise weekday + US federal holiday table.

Options expiration is the third Friday (or prior session if that Friday is
closed). Do NOT treat calendar days 15–21 as expiration.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Optional, Union

MARKET_CALENDAR_VERSION = "market_calendar_1.0.0"
AUTHORITY = "READ_ONLY_ADVISORY"

DateLike = Union[date, datetime, str]

_PMC = None
_PMC_TRIED = False
_XC = None
_XC_TRIED = False


def _as_date(value: DateLike) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value)[:10]
    return date.fromisoformat(s)


def is_weekday(value: DateLike) -> bool:
    return _as_date(value).weekday() < 5


def is_weekend(value: DateLike) -> bool:
    return _as_date(value).weekday() >= 5


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """n-th (1-based) weekday of a month; weekday Mon=0 … Sun=6; n=-1 last."""
    if n > 0:
        d = date(year, month, 1)
        d += timedelta(days=(weekday - d.weekday()) % 7)
        return d + timedelta(weeks=n - 1)
    d = date(year + (month == 12), (month % 12) + 1, 1) - timedelta(days=1)
    return d - timedelta(days=(d.weekday() - weekday) % 7)


def _observed_federal(d: date) -> date:
    """Federal Saturday→Friday, Sunday→Monday observance."""
    if d.weekday() == 5:
        return d - timedelta(days=1)
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


def us_federal_holidays(year: int) -> set[date]:
    """US federal holiday table (observed). Not an NYSE session calendar.

    Includes Columbus Day and Veterans Day (NYSE is typically open those days).
    Juneteenth included from 2021 onward.
    """
    days = {
        _observed_federal(date(year, 1, 1)),          # New Year's Day
        _nth_weekday(year, 1, 0, 3),                  # MLK
        _nth_weekday(year, 2, 0, 3),                  # Washington's Birthday
        _nth_weekday(year, 5, 0, -1),                 # Memorial Day
        _observed_federal(date(year, 7, 4)),          # Independence Day
        _nth_weekday(year, 9, 0, 1),                  # Labor Day
        _nth_weekday(year, 10, 0, 2),                 # Columbus Day / Indigenous Peoples'
        _observed_federal(date(year, 11, 11)),        # Veterans Day
        _nth_weekday(year, 11, 3, 4),                 # Thanksgiving
        _observed_federal(date(year, 12, 25)),        # Christmas
    }
    if year >= 2021:
        days.add(_observed_federal(date(year, 6, 19)))  # Juneteenth
    return days


def _try_pandas_market_calendars():
    global _PMC, _PMC_TRIED
    if _PMC_TRIED:
        return _PMC
    _PMC_TRIED = True
    try:
        import pandas_market_calendars as mcal  # type: ignore

        _PMC = mcal.get_calendar("XNYS")
    except Exception:
        _PMC = None
    return _PMC


def _try_exchange_calendars():
    global _XC, _XC_TRIED
    if _XC_TRIED:
        return _XC
    _XC_TRIED = True
    try:
        import exchange_calendars as xcals  # type: ignore

        _XC = xcals.get_calendar("XNYS")
    except Exception:
        _XC = None
    return _XC


def calendar_backend() -> str:
    if _try_pandas_market_calendars() is not None:
        return "pandas_market_calendars"
    if _try_exchange_calendars() is not None:
        return "exchange_calendars"
    return "weekday_us_federal_holiday_table"


def is_us_trading_day(value: DateLike) -> bool:
    """True if the date is a US equity session under the best available calendar."""
    d = _as_date(value)
    pmc = _try_pandas_market_calendars()
    if pmc is not None:
        try:
            days = pmc.valid_days(start_date=d.isoformat(), end_date=d.isoformat())
            return len(days) > 0
        except Exception:
            pass
    xc = _try_exchange_calendars()
    if xc is not None:
        try:
            return bool(xc.is_session(d.isoformat()))
        except Exception:
            pass
    if d.weekday() >= 5:
        return False
    return d not in us_federal_holidays(d.year)


def third_friday(year: int, month: int) -> date:
    return _nth_weekday(year, month, 4, 3)


def options_expiration_date(year: int, month: int) -> date:
    """Monthly equity-options expiration: 3rd Friday, else prior trading day.

    Explicitly not 'calendar day 15–21'.
    """
    d = third_friday(year, month)
    for _ in range(5):
        if is_us_trading_day(d):
            return d
        d -= timedelta(days=1)
    return third_friday(year, month)


def is_options_expiration(value: DateLike) -> bool:
    d = _as_date(value)
    return d == options_expiration_date(d.year, d.month)


def is_options_expiration_week(value: DateLike) -> bool:
    """Mon–Fri of the week that contains the 3rd-Friday expiration.

    A mid-month date that merely falls in 15–21 is not enough.
    """
    d = _as_date(value)
    exp = options_expiration_date(d.year, d.month)
    week_monday = exp - timedelta(days=exp.weekday())
    week_friday = week_monday + timedelta(days=4)
    return week_monday <= d <= week_friday and d.weekday() < 5


def calendar_tags(value: DateLike) -> list[str]:
    d = _as_date(value)
    tags: list[str] = []
    if is_weekend(d):
        tags.append("weekend")
    elif is_weekday(d):
        tags.append("weekday")
    if is_us_trading_day(d):
        tags.append("us_trading_day")
    else:
        tags.append("us_market_closed")
    if is_options_expiration(d):
        tags.append("options_expiration")
    if is_options_expiration_week(d):
        tags.append("options_expiration_week")
    return tags


def describe_calendar(value: Optional[DateLike] = None) -> dict[str, Any]:
    d = _as_date(value or date.today())
    return {
        "version": MARKET_CALENDAR_VERSION,
        "authority": AUTHORITY,
        "date": d.isoformat(),
        "backend": calendar_backend(),
        "weekday": is_weekday(d),
        "weekend": is_weekend(d),
        "us_trading_day": is_us_trading_day(d),
        "options_expiration": is_options_expiration(d),
        "options_expiration_week": is_options_expiration_week(d),
        "third_friday": third_friday(d.year, d.month).isoformat(),
        "options_expiration_date": options_expiration_date(d.year, d.month).isoformat(),
        "tags": calendar_tags(d),
        "note": "Does not treat day 15–21 as options expiration.",
    }
