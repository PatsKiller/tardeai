"""Stale-guidance gates — an advisory or a stop prompt may not render as current when it is not.

Why this exists (operator P0 2026-11-03, Board row 33 piece E):
A held name stopped out. Days later its price was back above that stop, yet Home still said the name was
below its stop, and the CIO home still carried an advisory label whose narrative predated the stop by weeks.
The operator was looking at guidance that was true when it was written and false when he read it.

The concrete values from that incident are deliberately NOT recorded here: this is a public repository, and a
symbol together with a date and a fill price identifies a real execution. The gate needs the shape of the
failure, not the operator's trade.

Two rules, both pure and both testable without a live store:

* **Observation age.** An advisory whose OBSERVATION is older than ``max_observation_age_days`` (default 14) is
  STALE. The clock is the observation — ``surfaced_at`` on a hit, ``proposed_at`` on a staged row — never the
  directive's creation: a fresh hit against an old directive is a fresh observation, and an undrained staging
  row is as old as the day it was proposed.
* **Reality.** A stop prompt renders only while the price is at or below the stop on record. A row that still
  carries ``triggered`` from an event that has since passed (price recovered) is stale, not a live breach.

An unreadable or missing observation date is "age unknown": it is NOT treated as stale, so a source that
carries no clock is not silently dropped. The gate fires only on guidance we can prove is old.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Optional

DEFAULT_MAX_OBSERVATION_AGE_DAYS = 14
SECONDS_PER_DAY = 86400.0


def _parse_ts(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        raw = str(value).strip()
        if not raw:
            return None
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(raw)
        except ValueError:
            return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def age_days(value: Any, now: datetime) -> Optional[float]:
    """Age in days of an ISO timestamp, or None when it cannot be read."""
    dt = _parse_ts(value)
    if dt is None:
        return None
    return max(0.0, (now - dt).total_seconds() / SECONDS_PER_DAY)


def advisory_freshness(opportunity: dict, now: datetime, *,
                       max_observation_age_days: int = DEFAULT_MAX_OBSERVATION_AGE_DAYS) -> dict:
    """``{"stale": bool, "reason": str|None, "age_days": float|None}`` for one advisory row.

    The clock is the OBSERVATION (``surfaced_at``/``proposed_at``), not the directive's creation and not the
    row's own metadata. A hit surfaced today from a directive written a month ago is fresh; an undrained row
    proposed 60 days ago is stale. An unreadable clock is age-unknown and is not suppressed.
    """
    observed = opportunity.get("surfaced_at") or opportunity.get("proposed_at")
    age = age_days(observed, now)
    if age is None:
        return {"stale": False, "reason": None, "age_days": None, "age_known": False}
    if age > max_observation_age_days:
        return {"stale": True, "reason": f"observation_older_than_{max_observation_age_days}d",
                "age_days": round(age, 2), "age_known": True}
    return {"stale": False, "reason": None, "age_days": round(age, 2), "age_known": True}


def stop_prompt_is_stale(position: dict) -> bool:
    """True when a position row says its stop triggered but the price is no longer through the stop.

    ``distance_to_stop_pct`` is measured from the stop: > 0 means the price is ABOVE the stop on record, so
    a stored ``triggered`` flag is an event that has passed, not a live breach. An unknown distance is NOT
    treated as stale — a genuinely breached stop with an unmeasured distance must still page.
    """
    if not position.get("triggered"):
        return False
    try:
        distance = float(position.get("distance_to_stop_pct"))
    except (TypeError, ValueError):
        return False
    return distance > 0


def limits_from_env() -> dict:
    """The configured limit, with defaults. Never raises: a broken value falls back to the default."""
    try:
        value = int(os.environ.get("TRADEAI_MAX_OBSERVATION_AGE_DAYS") or DEFAULT_MAX_OBSERVATION_AGE_DAYS)
    except (TypeError, ValueError):
        return {"max_observation_age_days": DEFAULT_MAX_OBSERVATION_AGE_DAYS}
    return {"max_observation_age_days": value if value > 0 else DEFAULT_MAX_OBSERVATION_AGE_DAYS}


__all__ = ["DEFAULT_MAX_OBSERVATION_AGE_DAYS", "age_days", "advisory_freshness",
           "stop_prompt_is_stale", "limits_from_env"]
