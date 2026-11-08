"""The "now" a card shows for a name, and what replaces it when no session is open (LQ-20261107-1264).

Why: a card that prints "now —" tells the operator nothing, and a bare "stale" pretends the instrument is broken when
it is simply between sessions. Two things are needed, and both are computed here rather than in a renderer:

* ``mark_label`` — one line naming WHICH session the newest observation came from, when it printed, the price and the
  change: ``after-hours Fri 7:58 PM $424.10 (+0.3%)``. A level with no dated reference never gets a change; it says
  ``level only``. This is the shape the operator asked for (2026-11-08 17:56 ET: "named with session and time").
* ``next_session_text`` — when nothing is open: ``futures open Sun 6:00 PM ET`` for the futures/overnight block and
  ``next trading: overnight session opens Sun 8:00 PM ET`` for equity marks. Never a bare dash.

Pure: no clock beyond the ``now`` the caller passes, no database, no network. ET is the display zone; the instants
returned are timezone-aware in ET so a caller never has to guess.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

#: Display name per ``market_quotes_extended.session`` value. An unknown session is shown by its raw value.
SESSION_LABELS = {
    "regular": "close",
    "premarket": "pre-market",
    "afterhours": "after-hours",
    "overnight": "overnight",
    "futures_open": "futures open",
}


def _et(now: datetime) -> datetime:
    return now.astimezone(ET) if now.tzinfo else now.replace(tzinfo=ET)


def next_futures_open(now: datetime) -> datetime:
    """The next Sunday 18:00 ET futures open strictly after ``now`` (the CME Sunday session)."""
    et = _et(now)
    days = (6 - et.weekday()) % 7  # 6 == Sunday
    candidate = datetime.combine((et + timedelta(days=days)).date(), time(18, 0), tzinfo=ET)
    if candidate <= et:
        candidate += timedelta(days=7)
    return candidate


def next_overnight_open(now: datetime) -> datetime:
    """The next 20:00 ET overnight-equity open (Sunday through Thursday) strictly after ``now``."""
    et = _et(now)
    for step in range(8):
        day = et + timedelta(days=step)
        if day.weekday() in (4, 5):  # Friday and Saturday nights do not open the overnight equity session
            continue
        candidate = datetime.combine(day.date(), time(20, 0), tzinfo=ET)
        if candidate > et:
            return candidate
    return et + timedelta(days=7)


def opens_phrase(at: datetime) -> str:
    """``Sun 6:00 PM ET`` -- the day, the clock in the operator's zone, and the zone itself."""
    et = _et(at)
    return f"{et:%a} {et.hour % 12 or 12}:{et.minute:02d} {'AM' if et.hour < 12 else 'PM'} ET"


def next_session_text(now: datetime, kind: str = "futures") -> str:
    """What the card says when nothing is open. ``kind`` is ``futures`` (the overnight-markets block, which is futures
    and cash-index levels) or ``overnight`` (an equity mark between sessions)."""
    if kind == "futures":
        return f"futures open {opens_phrase(next_futures_open(now))}"
    return f"next trading: overnight session opens {opens_phrase(next_overnight_open(now))}"


def mark_label(session: Any, at: datetime | None, price: Any, change_pct: Any = None) -> str:
    """One line for the newest observation: ``after-hours Fri 7:58 PM $424.10 (+0.3%)``.

    Missing pieces are omitted, never invented: an unknown session is its raw value, an unparsable time is left out,
    a level with no change says ``level only`` rather than showing a fabricated ``+0.0%``."""
    name = SESSION_LABELS.get(str(session or "").strip(), str(session or "").strip())
    parts: list[str] = [name] if name else []
    if isinstance(at, datetime):
        et = _et(at)
        parts.append(f"{et:%a} {et.hour % 12 or 12}:{et.minute:02d} {'AM' if et.hour < 12 else 'PM'}")
    try:
        px = float(price)
    except (TypeError, ValueError):
        px = None
    if px is not None:
        parts.append(f"${px:,.2f}")
    try:
        pct = None if change_pct is None else float(change_pct)
    except (TypeError, ValueError):
        pct = None
    if pct is None:
        parts.append("level only")
    else:
        parts.append(f"({pct:+.1f}%)")
    return " ".join(parts)
