"""cron_schedule.py — when does a 5-field cron expression next fire?

Used to turn a declared schedule into an honest ETA ("the gap resolver next
runs Mon 10:00 EDT") instead of a guess. Standard crontab semantics:

  minute hour day-of-month month day-of-week
  `*`, `*/n`, `a`, `a-b`, `a-b/n`, and comma lists; day-of-week 0 and 7 are
  Sunday. When both day-of-month and day-of-week are restricted, a day matches
  if EITHER matches (Vixie cron).

Times are naive or aware `datetime`s in the crontab's own timezone (cron runs
in the host's local time); the result keeps the tzinfo of `after`. No third-party
dependency (croniter is not installed).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable, Optional

_RANGES = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 7))
#: Search horizon. Every valid expression fires within about four years (Feb 29);
#: operational schedules fire within days. Beyond this, None.
_HORIZON_MINUTES = 366 * 24 * 60


def _parse_field(spec: str, lo: int, hi: int) -> tuple[set[int], bool]:
    """(values, restricted). Raises ValueError on a malformed field."""
    spec = spec.strip()
    if not spec:
        raise ValueError("empty cron field")
    values: set[int] = set()
    restricted = spec != "*"
    for part in spec.split(","):
        step = 1
        if "/" in part:
            part, step_s = part.split("/", 1)
            step = int(step_s)
            if step < 1:
                raise ValueError(f"bad step in {spec!r}")
        if part == "*":
            start, end = lo, hi
        elif "-" in part:
            a, b = part.split("-", 1)
            start, end = int(a), int(b)
        else:
            start = int(part)
            end = hi if step > 1 else start
        if start < lo or end > hi or start > end:
            raise ValueError(f"cron field {spec!r} out of range {lo}-{hi}")
        values.update(range(start, end + 1, step))
    return values, restricted


def parse(expr: str) -> tuple[set[int], set[int], set[int], set[int], set[int], bool, bool]:
    fields = str(expr or "").split()
    if len(fields) != 5:
        raise ValueError(f"expected 5 cron fields, got {len(fields)} in {expr!r}")
    parsed = [_parse_field(f, lo, hi) for f, (lo, hi) in zip(fields, _RANGES)]
    minutes, hours, doms, months = (parsed[i][0] for i in range(4))
    dows = {0 if d == 7 else d for d in parsed[4][0]}
    return minutes, hours, doms, months, dows, parsed[2][1], parsed[4][1]


def next_run(expr: str, after: datetime) -> Optional[datetime]:
    """First firing strictly after ``after`` (to the minute), or None."""
    minutes, hours, doms, months, dows, dom_r, dow_r = parse(expr)
    t = after.replace(second=0, microsecond=0) + timedelta(minutes=1)
    end = t + timedelta(minutes=_HORIZON_MINUTES)
    while t <= end:
        cron_dow = (t.weekday() + 1) % 7
        if dom_r and dow_r:
            day_ok = t.day in doms or cron_dow in dows
        else:
            day_ok = t.day in doms and cron_dow in dows
        if t.month not in months or not day_ok:
            t = (t + timedelta(days=1)).replace(hour=0, minute=0)
            continue
        if t.hour not in hours:
            t = (t + timedelta(hours=1)).replace(minute=0)
            continue
        if t.minute in minutes:
            return t
        t += timedelta(minutes=1)
    return None


def next_run_any(exprs: Iterable[str], after: datetime) -> Optional[datetime]:
    """Earliest next firing across several expressions; malformed ones are skipped."""
    best: Optional[datetime] = None
    for e in exprs or ():
        try:
            n = next_run(e, after)
        except ValueError:
            continue
        if n is not None and (best is None or n < best):
            best = n
    return best
