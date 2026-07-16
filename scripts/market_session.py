#!/usr/bin/env python3
"""market_session.py — US equity market session and freshness utilities.

Determines market open/closed/premarket/afterhours status and provides
recommendation/approval staleness checks.

Usage:
    .venv/bin/python scripts/market_session.py --status --json
"""
import argparse, json, os, sys
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# US market hours (Eastern Time)
MARKET_OPEN = time(9, 30)
MARKET_CLOSE = time(16, 0)
PREMARKET_START = time(4, 0)
AFTERHOURS_END = time(20, 0)
EARLY_CLOSE_TIME = time(13, 0)

# NYSE observed holidays + early closes — COMPUTED for any year, per NYSE Rule 7.2 observance:
# a holiday falling on Saturday is observed the preceding Friday (except New Year's Day, which
# is then not observed); falling on Sunday, the following Monday. Replaces a hardcoded 2026-only
# set that (a) was missing Juneteenth — every gated cron ran on 2026-06-19 — and (b) would have
# silently treated ALL 2027 holidays as trading days.

def _easter(year: int):
    """Gregorian Easter (anonymous computus)."""
    from datetime import date
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


def _nth_weekday(year: int, month: int, weekday: int, n: int):
    """n-th (1-based) weekday of a month; n=-1 for the last."""
    from datetime import date, timedelta
    if n > 0:
        d = date(year, month, 1)
        d += timedelta(days=(weekday - d.weekday()) % 7)
        return d + timedelta(weeks=n - 1)
    d = date(year + (month == 12), (month % 12) + 1, 1) - timedelta(days=1)
    return d - timedelta(days=(d.weekday() - weekday) % 7)


def _observed(d):
    """NYSE observance shift: Sat → preceding Fri, Sun → following Mon."""
    from datetime import timedelta
    if d.weekday() == 5:
        return d - timedelta(days=1)
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


def market_holidays(year: int) -> set:
    """NYSE full-closure dates for a year, as YYYY-MM-DD strings."""
    from datetime import date, timedelta
    days = set()
    jan1 = date(year, 1, 1)
    if jan1.weekday() == 6:
        days.add(date(year, 1, 2))          # New Year's observed Monday
    elif jan1.weekday() != 5:
        days.add(jan1)                       # Saturday → not observed (NYSE)
    days.add(_nth_weekday(year, 1, 0, 3))    # MLK — 3rd Monday Jan
    days.add(_nth_weekday(year, 2, 0, 3))    # Washington's Birthday — 3rd Monday Feb
    days.add(_easter(year) - timedelta(days=2))   # Good Friday
    days.add(_nth_weekday(year, 5, 0, -1))   # Memorial Day — last Monday May
    days.add(_observed(date(year, 6, 19)))   # Juneteenth (NYSE since 2022)
    days.add(_observed(date(year, 7, 4)))    # Independence Day
    days.add(_nth_weekday(year, 9, 0, 1))    # Labor Day — 1st Monday Sep
    days.add(_nth_weekday(year, 11, 3, 4))   # Thanksgiving — 4th Thursday Nov
    days.add(_observed(date(year, 12, 25)))  # Christmas
    return {d.isoformat() for d in days}


def market_early_closes(year: int) -> set:
    """NYSE 1:00 pm ET early-close dates: July 3 (when a weekday and not the observed 4th),
    the Friday after Thanksgiving, and Christmas Eve (when a weekday and not itself a closure)."""
    from datetime import date, timedelta
    hols = market_holidays(year)
    out = set()
    for d in (date(year, 7, 3), date(year, 12, 24)):
        if d.weekday() < 5 and d.isoformat() not in hols:
            out.add(d.isoformat())
    out.add((_nth_weekday(year, 11, 3, 4) + timedelta(days=1)).isoformat())  # day after Thanksgiving
    return out


_CALENDAR_CACHE: dict = {}


def _calendar(year: int):
    if year not in _CALENDAR_CACHE:
        _CALENDAR_CACHE[year] = (market_holidays(year), market_early_closes(year))
    return _CALENDAR_CACHE[year]

# Freshness thresholds (minutes) by strategy type
# Multi-day strategies have multi-day validity windows.
# Staleness is checked against approved_at (when user acted), not created_at.
FRESHNESS_THRESHOLDS = {
    "intraday_scalp": 30, "momentum_scalp": 30, "scalp": 30, "gap_and_go": 30,
    "momentum": 60, "momentum_breakout": 60, "day_trade": 60,
    "swing": 4320, "swing_trade": 4320, "swing_breakout": 4320,  # 3 days
    "mean_reversion": 4320,
    "earnings_catalyst": 7200, "sector_rotation": 7200,  # 5 days
    "speculative_growth": 7200, "core_growth_compounder": 14400,  # 10 days
    "income": 14400, "income_add": 14400, "covered_call_income": 14400,
    "dividend_growth_compounder": 14400, "high_yield_income_bdc": 14400,
    "position": 14400, "dividend": 14400, "defense_thesis": 14400,
    "recovery_watch": 14400, "reit_income": 14400, "bond_income": 14400,
    "screener": 4320,
    "default": 60,
}


def _eastern_now():
    """Get current time in US/Eastern."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/New_York"))
    except ImportError:
        # Fallback: assume UTC-4 (EDT) or UTC-5 (EST)
        utc = datetime.now(timezone.utc)
        offset = timedelta(hours=-4)  # EDT approximation
        return utc + offset


def _to_eastern(dt):
    """Convert datetime to Eastern."""
    try:
        from zoneinfo import ZoneInfo
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(ZoneInfo("America/New_York"))
    except ImportError:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt + timedelta(hours=-4)


def current_market_session(now=None):
    """Return current market session state."""
    et = _to_eastern(now) if now else _eastern_now()
    date_str = et.strftime("%Y-%m-%d")
    t = et.time()
    weekday = et.weekday()

    if weekday >= 5:
        return "weekend"
    holidays, early_closes = _calendar(et.year)
    if date_str in holidays:
        return "holiday"
    if date_str in early_closes:
        if t < PREMARKET_START:
            return "closed"
        if t < MARKET_OPEN:
            return "premarket"
        if t < EARLY_CLOSE_TIME:
            return "regular"
        if t < AFTERHOURS_END:
            return "afterhours"
        return "closed"
    if t < PREMARKET_START:
        return "closed"
    if t < MARKET_OPEN:
        return "premarket"
    if t < MARKET_CLOSE:
        return "regular"
    if t < AFTERHOURS_END:
        return "afterhours"
    return "closed"


def is_market_open(now=None):
    return current_market_session(now) == "regular"


def is_research_intelligence_window(now=None):
    """True when Research Intelligence *content production* may run.

    Allowed: afterhours, closed, weekend, holiday.
    Blocked: regular RTH (09:30–16:00 ET) and premarket (04:00–09:30 ET)
    so overnight/after-close batches do not compete with the trading desk.
    Desk *read* APIs remain available 24/7.
    """
    return current_market_session(now) in ("afterhours", "closed", "weekend", "holiday")


def is_trading_day(now=None):
    """Return True if today is a regular trading day (not weekend, not holiday)."""
    session = current_market_session(now)
    return session not in ("weekend", "holiday")


def next_regular_session_open(now=None):
    """Return next regular session open time."""
    et = _to_eastern(now) if now else _eastern_now()
    candidate = et.replace(hour=9, minute=30, second=0, microsecond=0)
    if et.time() >= MARKET_OPEN:
        candidate += timedelta(days=1)
    for _ in range(10):
        ds = candidate.strftime("%Y-%m-%d")
        if candidate.weekday() < 5 and ds not in _calendar(candidate.year)[0]:
            return candidate
        candidate += timedelta(days=1)
    return candidate


def should_delay_execution(strategy_id=None, now=None):
    """Whether execution should be delayed for current session."""
    session = current_market_session(now)
    if session in ("closed", "weekend", "holiday"):
        return True, f"market_{session}"
    if session == "premarket":
        return True, "premarket_wait_for_open"
    if session == "afterhours":
        # Most strategies should not execute after hours
        if strategy_id and strategy_id.lower() in ("swing", "income", "position", "dividend"):
            return False, "afterhours_allowed_for_swing"
        return True, "afterhours_wait_for_session"
    return False, "regular_session"


def get_freshness_threshold(strategy_id=None):
    """Get max age in minutes before recommendation is stale."""
    if not strategy_id:
        return FRESHNESS_THRESHOLDS["default"]
    key = strategy_id.lower().replace("-", "_").replace(" ", "_")
    return FRESHNESS_THRESHOLDS.get(key, FRESHNESS_THRESHOLDS["default"])


def is_recommendation_stale(created_at, strategy_id=None, max_age_minutes=None):
    """Check if a recommendation is stale."""
    if not created_at:
        return True, "no_created_at"
    threshold = max_age_minutes or get_freshness_threshold(strategy_id)
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - created_at).total_seconds()
    age_min = age / 60
    return age_min > threshold, f"age={age_min:.0f}min threshold={threshold}min"


def is_approval_stale(approved_at, strategy_id=None, max_age_minutes=None):
    """Check if an approval is stale."""
    return is_recommendation_stale(approved_at, strategy_id, max_age_minutes)


def get_status():
    """Return full market session status."""
    et = _eastern_now()
    session = current_market_session()
    delay, delay_reason = should_delay_execution()
    nxt = next_regular_session_open()
    return {
        "eastern_time": et.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "session": session,
        "market_open": session == "regular",
        "should_delay": delay,
        "delay_reason": delay_reason,
        "next_regular_open": nxt.strftime("%Y-%m-%d %H:%M:%S") if nxt else None,
        "freshness_thresholds": FRESHNESS_THRESHOLDS,
    }


def main():
    parser = argparse.ArgumentParser(description="US market session status")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    status = get_status()
    if args.json:
        print(json.dumps(status, indent=2, default=str))
    else:
        print(f"Session: {status['session']}, Open: {status['market_open']}, "
              f"Delay: {status['should_delay']} ({status['delay_reason']})")


if __name__ == "__main__":
    main()
