"""Read-only observation freshness; this does not confirm an order or a watcher."""
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from scripts.market_session import is_trading_day, market_early_closes


ET = ZoneInfo("America/New_York")


def _clock(value):
    if not isinstance(value, (str, datetime)):
        return None
    try:
        stamp = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
        return stamp.astimezone(timezone.utc) if stamp.utcoffset() is not None else None
    except (ValueError, OverflowError):
        return None


def stop_observation_freshness(captured_at, *, now):
    """Refuse protection evidence older than one completed trading session.

    Count session closes strictly AFTER the observation and at or before now.
    Weekends, holidays and early closes use the existing market calendar. Two
    closes suffice to establish staleness; the result labels that as a lower
    bound, never as the exact age of a potentially much older observation.
    An explicit timezone is required; neither the host timezone nor UTC is
    guessed for an undated/naive wall clock.
    """
    observed, current = _clock(captured_at), _clock(now)
    result = {"status": "UNAVAILABLE", "as_of": observed.isoformat().replace("+00:00", "Z") if observed else None,
              "completed_sessions_since": None, "completed_sessions_at_least": None,
              "reason": "Stop observation time is unavailable"}
    if current is None:
        return {**result, "reason": "Current time is unavailable"}
    if observed is None:
        return result
    if observed > current:
        return {**result, "reason": "Stop observation time is ahead of the current clock"}
    try:
        day = current.astimezone(ET).date()
        completed = 0
        for offset in range(366):
            date = day - timedelta(days=offset)
            session = datetime.combine(date, time(12), tzinfo=ET)
            if not is_trading_day(session):
                continue
            hour = 13 if date.isoformat() in market_early_closes(date.year) else 16
            close = datetime.combine(date, time(hour), tzinfo=ET).astimezone(timezone.utc)
            if close > current:
                continue
            if close <= observed:
                return {**result, "status": "FRESH", "completed_sessions_since": completed, "reason": None}
            completed += 1
            if completed == 2:
                return {**result, "status": "STALE", "completed_sessions_at_least": 2,
                        "reason": "Stop not refreshed since " + result["as_of"]
                                  + "; more than one trading session has completed"}
    except (ValueError, OverflowError):
        pass
    return {**result, "reason": "Completed trading sessions could not be established"}
