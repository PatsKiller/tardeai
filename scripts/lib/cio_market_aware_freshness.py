"""Freshness for domains whose source only updates while the market is open.

The CIO evidence gate blocked every run with a single gap: `portfolio` STALE.
The data was not broken. Measured 2026-09-13T01:00Z, a Saturday:

    portfolio generated_at   2026-09-11 16:45 ET   (Friday's post-close reprice)
    age                      28.2 hours
    freshness threshold      43,200 s = 12 hours wall-clock
    -> STALE -> EVIDENCE_GAP -> every SCHEDULED_CIO_BRIEF run blocked

Friday's close is the freshest portfolio state that can exist on a Saturday.
Nothing reprices a position while the exchange is shut. Measuring its age in
wall-clock time means the domain goes stale roughly twelve hours after every
close and stays stale until the next session -- so the CIO is structurally
blocked every weekend and every weeknight before the morning reprice. Not a
malfunction: a threshold in the wrong units.

The rule here is narrow on purpose:

  * While the market is OPEN, nothing changes. Wall-clock age applies, because
    the data genuinely should be updating and a stale file is a real fault.
  * While the market is CLOSED, evidence stamped at or after the most recent
    session close is as fresh as it is possible to be, so it is not stale.
  * Anything older than that last close still ages normally and can still go
    stale. Missing a session's reprice is still caught.

That last point is what keeps this from being a way of making old data look
young. It does not widen the threshold; it stops counting hours in which the
source could not possibly have changed.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from scripts.lib.cio_market_session import get_session_service

_MAX_LOOKBACK_DAYS = 10


def last_session_close(
    now: datetime, service: Optional[Any] = None
) -> Optional[datetime]:
    """The official close of the most recent trading session at or before `now`.

    Returns None if no trading day is found within the lookback window, which
    makes every caller fall back to plain wall-clock ageing.
    """
    svc = service or get_session_service()
    et_now = svc._aware(now)
    day = et_now.date()
    for _ in range(_MAX_LOOKBACK_DAYS):
        if svc.is_trading_day(day):
            _open, close_dt, _early = svc.official_bounds(day)
            if close_dt is not None and close_dt <= et_now:
                return close_dt
        day = day - timedelta(days=1)
    return None


def market_is_open(now: datetime, service: Optional[Any] = None) -> bool:
    """True during regular trading hours only.

    Pre- and post-market are treated as CLOSED here. A position snapshot taken
    at the official close is still the authoritative one during post-market;
    treating that window as open would re-introduce the very staleness this
    module exists to stop.
    """
    svc = service or get_session_service()
    try:
        return str(svc.session_at(now).get("state")) == "RTH"
    except Exception:  # noqa: BLE001 - an unusable calendar must not gate data
        return False


def is_stale(
    as_of: datetime,
    now: datetime,
    threshold_seconds: float,
    *,
    market_hours_only: bool = False,
    service: Optional[Any] = None,
) -> bool:
    """Whether evidence stamped `as_of` should be treated as STALE at `now`.

    With market_hours_only False this is exactly the wall-clock check it
    replaces, so non-market domains are unaffected.
    """
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=timezone.utc)
    wall_clock_stale = (now - as_of).total_seconds() > threshold_seconds

    if not market_hours_only or not wall_clock_stale:
        return wall_clock_stale

    if market_is_open(now, service):
        # The source should be updating right now; age means what it says.
        return True

    close = last_session_close(now, service)
    if close is None:
        return True

    # Fresh only if the evidence covers the most recent completed session.
    return as_of < close
