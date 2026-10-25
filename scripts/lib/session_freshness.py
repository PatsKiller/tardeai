"""Market-session-aware freshness: the one helper every "is this stale?" display uses.

Why (live page audit 2026-10-25, a Sunday): Friday-close quotes were labelled
STALE, the CIO market view said "refresh overdue", Ready-now hid every packet
under a 48 h wall-clock rule and Holdings read "Updated 2d ago" in amber. None
of that data was broken. It was the latest data that can exist while the
exchange is shut, and each surface aged it in wall-clock hours with its own
threshold.

Rules (built on ``cio_market_aware_freshness`` and the injectable NYSE
``cio_market_session`` service, so holidays and early closes are the same
everywhere):

* Market OPEN (regular hours): wall-clock age against ``max_age_h`` — unchanged.
* Market CLOSED: evidence stamped at or after the most recent session close
  (less a per-source ``grace_minutes`` for sources that sample shortly before
  the bell) is the latest possible. It is not stale, and the display says
  "Market closed · last close Fri 4:00 PM ET · next update Mon".
* Evidence older than that last close still ages: against
  ``closed_max_age_h`` (the data_source_authority ``stale_after_hours_closed``)
  when the source declares one, else ``max_age_h``. A missed session reprice is
  still caught; nothing is made to look younger than it is.

``trading_age_hours`` is the second, separate measure: wall-clock hours minus
the hours that fall on non-trading ET calendar days (weekends, exchange
holidays). A "48 h" expiry measured with it means "48 h of trading days".

No network, no I/O, READ_ONLY_ADVISORY. The TypeScript mirror is
``apps/command-center-v3/src/lib/marketSessionFreshness.ts``; both are pinned by
the same date table in tests/test_session_freshness_20261025.py and
marketSessionFreshness.test.ts.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from .cio_market_aware_freshness import last_session_close, market_is_open
from .cio_market_session import get_session_service

SCHEMA = "SessionFreshness@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
_LOOKAHEAD_DAYS = 10


_AUTHORITY_PATH = Path(__file__).resolve().parents[2] / "config" / "data_source_authority.json"


@lru_cache(maxsize=8)
def _authority_doc(path: str) -> dict:
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def authority_thresholds(domain: str, registry_path: Optional[Path] = None) -> Optional[dict[str, float]]:
    """{'open_h', 'closed_h'} from config/data_source_authority.json (domains, then proposed)."""
    doc = _authority_doc(str(registry_path or _AUTHORITY_PATH))
    for group in ("domains", "proposed_domains"):
        for dom in doc.get(group) or []:
            if isinstance(dom, dict) and dom.get("domain") == domain:
                try:
                    out = {"open_h": float(dom["stale_after_hours"])}
                except (KeyError, TypeError, ValueError):
                    return None
                closed = dom.get("stale_after_hours_closed")
                if isinstance(closed, (int, float)):
                    out["closed_h"] = float(closed)
                return out
    return None


def _aware(value: Any) -> Optional[datetime]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    # A naive stamp has no zone; never guess one (fail closed to "unknown").
    if dt.tzinfo is None:
        return None
    return dt


def next_session_open(now: datetime, service: Optional[Any] = None) -> Optional[datetime]:
    """Official regular-session open of the next trading session strictly after ``now``."""
    svc = service or get_session_service()
    et_now = svc._aware(now)
    day = et_now.date()
    for _ in range(_LOOKAHEAD_DAYS):
        if svc.is_trading_day(day):
            open_dt, _close, _early = svc.official_bounds(day)
            if open_dt is not None and open_dt > et_now:
                return open_dt
        day = day + timedelta(days=1)
    return None


def _clock(dt: datetime) -> str:
    text = dt.strftime("%I:%M %p").lstrip("0")
    return f"{text} ET"


def closed_phrase(now: datetime, service: Optional[Any] = None) -> Optional[str]:
    """"Market closed · last close Fri 4:00 PM ET · next update Mon", or None while open."""
    svc = service or get_session_service()
    if market_is_open(now, svc):
        return None
    close = last_session_close(now, svc)
    nxt = next_session_open(now, svc)
    et_now = svc._aware(now)
    parts = ["Market closed"]
    if close is not None:
        when = f"today {_clock(close)}" if close.date() == et_now.date() else f"{close.strftime('%a')} {_clock(close)}"
        parts.append(f"last close {when}")
    if nxt is not None:
        if nxt.date() == et_now.date():
            parts.append(f"next update today {_clock(nxt)}")
        elif (nxt.date() - et_now.date()).days < 7:
            parts.append(f"next update {nxt.strftime('%a')}")
        else:
            parts.append(f"next update {nxt.strftime('%a %b')} {nxt.day}")
    return " · ".join(parts)


def evaluate(
    as_of: Any,
    now: Optional[datetime] = None,
    *,
    max_age_h: float,
    closed_max_age_h: Optional[float] = None,
    grace_minutes: float = 0.0,
    future_skew_minutes: float = 5.0,
    service: Optional[Any] = None,
) -> dict[str, Any]:
    """Freshness verdict for one stamp. ``state`` is fresh | latest_close | stale | unknown.

    ``latest_close`` means: the market is closed and this is the latest data that
    can exist; show ``phrase`` instead of an age warning.
    """
    svc = service or get_session_service()
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    at = _aware(as_of)
    base: dict[str, Any] = {"schema": SCHEMA, "authority": AUTHORITY, "as_of": at.isoformat() if at else None,
                            "age_hours": None, "market_open": market_is_open(now, svc),
                            "last_close": None, "next_open": None, "phrase": None}
    close = last_session_close(now, svc)
    nxt = next_session_open(now, svc)
    base["last_close"] = close.isoformat() if close else None
    base["next_open"] = nxt.isoformat() if nxt else None
    if at is None:
        return {**base, "state": "unknown", "stale": True, "reason": "no usable update time"}
    age_h = (now - at).total_seconds() / 3600
    base["age_hours"] = round(age_h, 3)
    if at > now + timedelta(minutes=future_skew_minutes):
        return {**base, "state": "unknown", "stale": True, "reason": "update time is in the future"}
    if base["market_open"]:
        stale = age_h > max_age_h
        return {**base, "state": "stale" if stale else "fresh", "stale": stale,
                "reason": f"older than {max_age_h:g} h while the market is open" if stale else None}
    phrase = closed_phrase(now, svc)
    if close is not None and at >= close - timedelta(minutes=grace_minutes):
        return {**base, "state": "latest_close", "stale": False, "phrase": phrase, "reason": None}
    limit = closed_max_age_h if closed_max_age_h is not None else max_age_h
    stale = age_h > limit
    return {**base, "state": "stale" if stale else "fresh", "stale": stale, "phrase": phrase,
            "reason": (f"older than the last session close and than {limit:g} h" if stale else None)}


def trading_age_hours(as_of: Any, now: Optional[datetime] = None, *, service: Optional[Any] = None) -> Optional[float]:
    """Wall-clock hours since ``as_of`` minus hours on non-trading ET calendar days."""
    svc = service or get_session_service()
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    at = _aware(as_of)
    if at is None:
        return None
    start, end = svc._aware(at), svc._aware(now)
    if end <= start:
        return 0.0
    total = (end - start).total_seconds()
    day: date = start.date()
    while day <= end.date():
        if not svc.is_trading_day(day):
            day_start = datetime.combine(day, datetime.min.time(), tzinfo=svc.tz)
            day_end = datetime.combine(day + timedelta(days=1), datetime.min.time(), tzinfo=svc.tz)
            lo, hi = max(start, day_start), min(end, day_end)
            if hi > lo:
                total -= (hi - lo).total_seconds()
        day += timedelta(days=1)
    return round(max(0.0, total) / 3600, 3)


__all__ = ["SCHEMA", "authority_thresholds", "closed_phrase", "evaluate", "next_session_open", "trading_age_hours"]
