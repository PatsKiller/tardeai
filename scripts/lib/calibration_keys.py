"""Deterministic natural keys for the agent-calibration store (LQ-20261107-1032).

Before 2026-11-08 the engine minted a random ``ACE_<UTC stamp>_<nonce>`` (and ``ACW_...``) per
row, so every weekly run INSERTed the same recommendation again: measured 2026-11-08 12:20 ET,
6,411 ``(recommendation_id, scoring_window)`` groups held 41,257 extra rows.
``ON CONFLICT (calibration_event_id) DO NOTHING`` could never fire, because the key it conflicted
on was fresh on every run.

A calibration event IS one recommendation scored inside one scoring window, so its identity is
that pair: the same pair maps to the same row forever, and a re-run updates the row instead of
adding one. The id keeps the table's existing prefix followed by a 96-bit digest, so it stays
readable beside the rows the random generator wrote (those are the ones
``scripts/archive_duplicate_calibration_events.py`` archives).

The id is NOT a digest of the outcome. A recommendation's outcome changes over time (a trade
opens, then closes); the row is updated in place. Its identity is the question it answers.

A window is the same idea at agent granularity. Its bounds are normalised to whole UTC days by
:func:`day_bounds`, because the old ``str(now - 90 days)`` moved on every run — so the unique key
``(agent_name, window_start, window_end, domain, strategy_id)`` could never match either (and
``strategy_id`` was never inserted, so it was NULL, and a NULL is distinct from itself in a
PostgreSQL unique index).
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

EVENT_PREFIX = "ACE_"
WINDOW_PREFIX = "ACW_"
_KEY_HEX = 24  # 96 bits of sha256


def _digest(*parts: object) -> str:
    raw = "\x1f".join("" if p is None else str(p) for p in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:_KEY_HEX]


def event_key(recommendation_id: str, scoring_window: str | None) -> str:
    """``ACE_`` + digest of the natural key: one recommendation in one scoring window."""
    return EVENT_PREFIX + _digest(recommendation_id, scoring_window)


def window_key(agent_name: str, window_start: object, window_end: object,
               domain: str | None = "general", strategy_id: str | None = None) -> str:
    """``ACW_`` + digest of the natural key: one agent's window over one day-aligned span."""
    return WINDOW_PREFIX + _digest(agent_name, _stamp(window_start), _stamp(window_end),
                                   domain, strategy_id)


def day_bounds(now: datetime, window_days: int) -> tuple[datetime, datetime]:
    """(window_start, window_end) at whole-UTC-day granularity, so a second run the same day upserts.

    ``window_end`` is midnight UTC of ``now``'s day: the window is "the N days ending today",
    stated at the resolution the weekly cadence actually needs.
    """
    base = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    end = base.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return end - timedelta(days=int(window_days)), end


def _stamp(value: object) -> str:
    """A datetime is stamped in UTC: the same instant from the DB (session tz) and from the run
    clock must produce the same key."""
    if isinstance(value, datetime):
        v = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc).isoformat()
    return "" if value is None else str(value)
