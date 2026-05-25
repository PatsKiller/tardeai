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

# 2026 US market holidays (NYSE observed)
US_HOLIDAYS_2026 = {
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03",
    "2026-05-25", "2026-07-03", "2026-09-07", "2026-11-26", "2026-12-25",
}
US_EARLY_CLOSE_2026 = {"2026-11-27", "2026-12-24"}

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
    if date_str in US_HOLIDAYS_2026:
        return "holiday"
    if date_str in US_EARLY_CLOSE_2026:
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
        if candidate.weekday() < 5 and ds not in US_HOLIDAYS_2026:
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
