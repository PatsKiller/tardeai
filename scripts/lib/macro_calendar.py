"""Reader for the macro-release calendar (``MacroCalendar@v1``): may the release train use the 08:00 ET window?

Operator ruling 2026-10-21: FRED is the primary source, plus a yearly file for FOMC and overrides
(``config/macro_calendar_overrides.json``); n8n runs the refresh (lane ``macro-calendar-refresh``,
``scripts/macro_calendar_refresh.py``); the host controller decides; fail closed.

The refresh writes ``<state root>/data/runtime/macro_calendar.json``. This module only reads it:

* :func:`skip_0800` ``(day) -> (skip, reason)``: skip when the day has an 08:30 ET release (a date entry with
  ``skip_0800`` true: every mapped 08:30 FRED release, an operator ``add``, FOMC only if the operator set it),
  and skip (fail closed)
  when the file is missing, corrupt, older than :data:`MAX_AGE_H` (3 days) or does not cover the day.
* :func:`verdict` ``(day, now) -> (verdict, reason)`` with the release-train controller's vocabulary
  (``CLEAR`` / ``MACRO_DAY`` / ``STALE`` / ``UNAVAILABLE``); ``skip_0800`` is ``verdict != CLEAR``.
* :class:`ReleaseTrainCalendar`: a drop-in for ``release_train_controller.MacroCalendar`` (same ``verdict(day, now)``
  signature), so ``TrainController(calendar=ReleaseTrainCalendar())`` keeps its ``WINDOW_SKIPPED_MACRO_<verdict>``
  halts unchanged.

``day`` is an ET calendar date. A ``datetime`` is accepted too: an aware one is converted to America/New_York first
(so 2026-11-02T13:00Z is the 08:00 EST window of 2026-11-02), a naive one is taken as ET wall time. Age is measured
on absolute instants, so a DST change inside the 3-day window neither adds nor removes an hour.

Pure stdlib, no network, no DB, never writes. Authority: READ_ONLY_ADVISORY. MBI_BEHAVIOR = 0.
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional, Union
from zoneinfo import ZoneInfo

SCHEMA = "MacroCalendar@v1"
FILE_NAME = "macro_calendar.json"
LANE_ID = "macro-calendar-refresh"
ET = ZoneInfo("America/New_York")
#: Operator 2026-10-21: older than 3 days is stale.
MAX_AGE_H = 72.0
#: A calendar stamped further than this in the future is a clock or writer fault, not a fresh file.
FUTURE_SKEW_H = 1.0

CLEAR, MACRO_DAY, STALE, UNAVAILABLE = "CLEAR", "MACRO_DAY", "STALE", "UNAVAILABLE"

DayLike = Union[date, datetime, str]


def default_path() -> Path:
    """``<state root>/data/runtime/macro_calendar.json`` — the same root the lane receipts use
    (``TRADEAI_STATE_ROOT``, else the persistent-state resolver), never the checkout the code runs from."""
    env = os.environ.get("TRADEAI_STATE_ROOT")
    if env:
        return Path(env) / "data" / "runtime" / FILE_NAME
    try:
        from scripts.lib.persistent_state_root import resolve_durable_dir
    except ImportError:  # scripts/ on sys.path, repo root not
        from lib.persistent_state_root import resolve_durable_dir  # type: ignore[no-redef]
    return Path(resolve_durable_dir("data/runtime")) / FILE_NAME


def et_date(day: DayLike) -> date:
    """The ET calendar date of ``day`` (see the module docstring)."""
    if isinstance(day, datetime):
        return (day.astimezone(ET) if day.tzinfo else day).date()
    if isinstance(day, date):
        return day
    return date.fromisoformat(str(day))


def _parse_instant(value: Any) -> datetime:
    dt = datetime.fromisoformat(str(value))
    if dt.tzinfo is None:
        raise ValueError("timestamp has no UTC offset")
    return dt


def load(path: Optional[Union[str, Path]] = None) -> dict:
    """Read and validate the calendar. Raises ``FileNotFoundError`` / ``ValueError`` (never returns a partial body)."""
    p = Path(path) if path is not None else default_path()
    if not p.is_file():
        raise FileNotFoundError(str(p))
    body = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(body, dict) or body.get("schema") != SCHEMA:
        raise ValueError(f"schema is not {SCHEMA}")
    _parse_instant(body["fetched_at"])
    frm, thru = date.fromisoformat(str(body["covers_from"])), date.fromisoformat(str(body["valid_through"]))
    if thru < frm:
        raise ValueError("valid_through is before covers_from")
    dates = body["dates"]
    if not isinstance(dates, dict):
        raise ValueError("dates is not an object")
    for key, entry in dates.items():
        date.fromisoformat(key)
        if not isinstance(entry, dict) or not isinstance(entry.get("has_0830"), bool) \
                or not isinstance(entry.get("skip_0800"), bool) or not isinstance(entry.get("events"), list):
            raise ValueError(f"dates[{key}] is malformed")
    return body


def verdict(day: DayLike, now: Optional[datetime] = None, *, path: Optional[Union[str, Path]] = None,
            max_age_h: float = MAX_AGE_H) -> tuple[str, str]:
    """``(CLEAR | MACRO_DAY | STALE | UNAVAILABLE, reason)`` for the 08:00 ET window of ``day``. Never raises."""
    try:
        d = et_date(day)
    except (TypeError, ValueError) as exc:
        return UNAVAILABLE, f"bad day {day!r}: {type(exc).__name__}"
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        return UNAVAILABLE, "now has no UTC offset"
    try:
        target = Path(path) if path is not None else default_path()
    except Exception as exc:  # noqa: BLE001 — an unresolvable root is an unavailable calendar
        return UNAVAILABLE, f"calendar path unresolved: {type(exc).__name__}"
    try:
        body = load(target)
    except FileNotFoundError:
        return UNAVAILABLE, f"calendar missing: {target} (lane {LANE_ID} has not written it)"
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return UNAVAILABLE, f"calendar corrupt: {target}: {type(exc).__name__}: {str(exc)[:120]}"
    fetched = _parse_instant(body["fetched_at"])
    age_h = (now - fetched).total_seconds() / 3600.0
    if age_h > max_age_h:
        return STALE, f"calendar fetched_at {fetched.isoformat()} is {age_h:.1f} h old (max {max_age_h:g} h)"
    if age_h < -FUTURE_SKEW_H:
        return STALE, f"calendar fetched_at {fetched.isoformat()} is in the future ({-age_h:.1f} h)"
    frm, thru = date.fromisoformat(str(body["covers_from"])), date.fromisoformat(str(body["valid_through"]))
    if not frm <= d <= thru:
        return STALE, f"calendar covers {frm}..{thru}, not {d}"
    entry = body["dates"].get(d.isoformat())
    if entry and entry["skip_0800"]:
        names = [f"{e.get('event')}@{e.get('time_et')} ({e.get('source')}"
                 f"{':' + str(e['release_id']) if e.get('release_id') else ''})"
                 for e in entry["events"] if isinstance(e, dict) and e.get("skips_0800")]
        return MACRO_DAY, f"{d} has a macro release that skips 08:00: {', '.join(names) or 'unnamed'}"
    others = [str(e.get("event")) for e in (entry or {}).get("events", []) if isinstance(e, dict)]
    tail = f"; other events recorded: {', '.join(others)}" if others else ""
    return CLEAR, f"{d} has no 08:30 ET release (calendar fetched {fetched.isoformat()}){tail}"


def skip_0800(day: DayLike, now: Optional[datetime] = None, *, path: Optional[Union[str, Path]] = None,
              max_age_h: float = MAX_AGE_H) -> tuple[bool, str]:
    """``(skip, reason)``: True on an 08:30 release day and on every fail-closed case. Never raises."""
    v, why = verdict(day, now, path=path, max_age_h=max_age_h)
    return v != CLEAR, f"{v}: {why}"


class ReleaseTrainCalendar:
    """Drop-in for ``release_train_controller.MacroCalendar``: ``verdict(day, now) -> (verdict, detail)``."""

    SCHEMA = SCHEMA

    def __init__(self, path: Optional[Union[str, Path]] = None, *, max_age_h: float = MAX_AGE_H) -> None:
        self.path, self.max_age_h = (Path(path) if path is not None else None), max_age_h

    def verdict(self, day: DayLike, now: datetime) -> tuple[str, str]:
        return verdict(day, now, path=self.path, max_age_h=self.max_age_h)
