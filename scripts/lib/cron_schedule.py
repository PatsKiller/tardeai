"""cron_schedule.py — when does a 5-field cron expression next fire?

Used to turn a declared schedule into an honest ETA ("the gap resolver next
runs Mon 10:00 EDT") instead of a guess. Standard crontab semantics:

  minute hour day-of-month month day-of-week
  `*`, `*/n`, `a`, `a-b`, `a-b/n`, and comma lists; day-of-week 0 and 7 are
  Sunday. When both day-of-month and day-of-week are restricted, a day matches
  if EITHER matches (Vixie cron).

Old API (`next_run` / `next_run_any`): times are naive or aware `datetime`s in
the crontab's own timezone (cron runs in the host's local time); the result keeps
the tzinfo of `after`. It steps naive wall-clock minutes, so it is NOT DST-safe:
a gap minute can be returned and a fold minute is ambiguous. No third-party
dependency (croniter is not installed).

`fires_between` / `last_fire_at_or_before` are the DST-safe API used by the
registry dispatcher (docs/implementation/n8n-maturity/02 §3.2 step 1, F11).
They step in LOCAL wall time of an explicit IANA zone (stdlib `zoneinfo`):

  * spring-forward gap: a matching nonexistent local minute fires ONCE at the
    first valid instant after the gap; every matching minute of one gap
    coalesces into that fire, keyed by that instant's local minute;
  * fall-back fold: a repeated local minute fires once, on fold 0 (the first
    occurrence); fold 1 never fires.

The slot identity is the local wall-clock minute (`YYYYMMDDTHHMM`), so a key
can never be minted twice.

Contract of the DST-safe API (it differs from the old one):

  * inputs (`start`, `end`, `t`) MUST be timezone-aware; a naive datetime is a
    ValueError, never silently read as local time. `tz` is the crontab's zone.
  * returned `Fire.at` is aware in `tz` with fold 0. In the fall-back hour the
    repeated wall minute exists twice; only the first (EDT) instant is a fire, so
    a staleness check measured from `Fire.at` never expects a second run in the
    repeated hour and never treats the 60-minute "gap" after it as a miss.
  * `last_fire_at_or_before` looks back at most `lookback_days` (default
    8). Beyond that it returns None. None means UNKNOWN (no fire in the window,
    e.g. a yearly line), not "never due" and not "due now": callers fall back to
    their cadence rule or report unknown, and must not compute an age from it.
  * a malformed expression (or names / `@aliases`, which only `cron_last_fire`
    accepts) raises ValueError even when the window is empty.

Staleness for cron lanes (heartbeat watcher via `supervisor_breach_detector`,
dispatcher `due`) must use these two functions, never naive wall-clock math.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from typing import Iterable, Iterator, NamedTuple, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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


# --------------------------------------------------------------------------
# DST-safe firing in an explicit timezone (n8n-maturity 02 §3.2 step 1, F11)
# --------------------------------------------------------------------------

DEFAULT_TZ = "America/New_York"
_SLOT_FMT = "%Y%m%dT%H%M"
#: last_fire_at_or_before looks back at most this many days.
_LOOKBACK_DAYS = 8
#: Naive-window margin so a fold or gap at either end of the window is never cut
#: off; results are filtered on the real instant afterwards.
_EDGE_MARGIN = timedelta(hours=3)


class Fire(NamedTuple):
    """One firing: ``at`` is the real instant (aware, in the requested tz);
    ``slot_local`` is the local wall-clock minute ``YYYYMMDDTHHMM`` (slot identity)."""

    at: datetime
    slot_local: str


@lru_cache(maxsize=1024)
def _compiled(expr: str):
    minutes, hours, doms, months, dows, dom_r, dow_r = parse(expr)
    return (tuple(sorted(minutes)), tuple(sorted(hours)), frozenset(doms),
            frozenset(months), frozenset(dows), dom_r, dow_r)


@lru_cache(maxsize=64)
def _zone(tz: str) -> ZoneInfo:
    try:
        return ZoneInfo(str(tz))
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"unknown timezone {tz!r}") from exc


def _require_aware(name: str, dt: datetime) -> None:
    if not isinstance(dt, datetime) or dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError(f"{name} must be a timezone-aware datetime")


def slot_local(dt: datetime, tz: str = DEFAULT_TZ) -> str:
    """Local wall-clock minute of an aware ``dt`` in ``tz`` as ``YYYYMMDDTHHMM``."""
    _require_aware("dt", dt)
    return dt.astimezone(_zone(tz)).strftime(_SLOT_FMT)


def is_sub_hourly(expr: str) -> bool:
    """True when ``expr`` can fire more than once within one clock hour."""
    return len(_compiled(expr)[0]) > 1


def _day_matches(d: date, doms, months, dows, dom_r: bool, dow_r: bool) -> bool:
    if d.month not in months:
        return False
    cron_dow = (d.weekday() + 1) % 7
    if dom_r and dow_r:
        return d.day in doms or cron_dow in dows
    return d.day in doms and cron_dow in dows


def _naive_matches(expr: str, lo: datetime, hi: datetime) -> Iterator[datetime]:
    """Matching naive local minutes in [lo, hi], ascending; skips whole days/hours."""
    minutes, hours, doms, months, dows, dom_r, dow_r = _compiled(expr)
    d = lo.date()
    last = hi.date()
    while d <= last:
        if _day_matches(d, doms, months, dows, dom_r, dow_r):
            for h in hours:
                for m in minutes:
                    t = datetime(d.year, d.month, d.day, h, m)
                    if t < lo:
                        continue
                    if t > hi:
                        return
                    yield t
        d += timedelta(days=1)


def _day_offset(d: date, zone: ZoneInfo) -> Optional[timedelta]:
    """The day's single UTC offset, or None when an offset change happens that day."""
    a = datetime(d.year, d.month, d.day, tzinfo=zone).utcoffset()
    n = d + timedelta(days=1)
    b = datetime(n.year, n.month, n.day, tzinfo=zone).utcoffset()
    return a if a == b else None


def _exists(naive: datetime, zone: ZoneInfo) -> bool:
    aware = naive.replace(tzinfo=zone)
    return aware.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None) == naive


def _resolve_transition(naive: datetime, zone: ZoneInfo) -> datetime:
    """Fire instant (aware, fold 0) of a matching naive minute on a DST-change day."""
    if _exists(naive, zone):
        return naive.replace(tzinfo=zone, fold=0)
    # Spring-forward gap: first valid local minute after it.
    t = naive
    for _ in range(24 * 60):
        t += timedelta(minutes=1)
        if _exists(t, zone):
            return t.replace(tzinfo=zone, fold=0)
    raise ValueError(f"no valid local time after {naive} in {zone}")  # pragma: no cover


def _slot(t: datetime) -> str:
    return f"{t.year:04d}{t.month:02d}{t.day:02d}T{t.hour:02d}{t.minute:02d}"


def fires_between(expr: str, start: datetime, end: datetime,
                  tz: str = DEFAULT_TZ) -> list[Fire]:
    """Every fire of ``expr`` (in local wall time of ``tz``) with start < at <= end.

    ``start``/``end`` must be aware (any zone). Ascending by instant, deduped by
    ``slot_local``. DST gap/fold rules are in the module docstring. Days without
    an offset change take a fast path (one offset per day, no per-minute zone math).
    """
    _require_aware("start", start)
    _require_aware("end", end)
    _compiled(expr)  # validate even when the window is empty
    zone = _zone(tz)
    # Compare on naive UTC to avoid same-tzinfo (fold-blind) comparisons.
    start_n = start.astimezone(timezone.utc).replace(tzinfo=None)
    end_n = end.astimezone(timezone.utc).replace(tzinfo=None)
    if end_n <= start_n:
        return []
    lo = start.astimezone(zone).replace(tzinfo=None, second=0, microsecond=0) - _EDGE_MARGIN
    hi = end.astimezone(zone).replace(tzinfo=None, second=0, microsecond=0) + _EDGE_MARGIN
    out: list[tuple[datetime, Fire]] = []
    seen: set[str] = set()
    offsets: dict = {}
    for naive in _naive_matches(expr, lo, hi):
        d = naive.date()
        if d not in offsets:
            offsets[d] = _day_offset(d, zone)
        off = offsets[d]
        if off is not None:
            at_n = naive - off
            if at_n <= start_n or at_n > end_n:
                continue
            at = naive.replace(tzinfo=zone)
            key = _slot(naive)
        else:
            at = _resolve_transition(naive, zone)
            at_n = at.astimezone(timezone.utc).replace(tzinfo=None)
            if at_n <= start_n or at_n > end_n:
                continue
            key = _slot(at)
        if key in seen:
            continue
        seen.add(key)
        out.append((at_n, Fire(at, key)))
    out.sort(key=lambda p: p[0])
    return [f for _, f in out]


def last_fire_at_or_before(expr: str, t: datetime, tz: str = DEFAULT_TZ,
                           lookback_days: int = _LOOKBACK_DAYS) -> Optional[Fire]:
    """Most recent fire with at <= ``t`` within ``lookback_days``, else None."""
    _require_aware("t", t)
    _compiled(expr)
    end = t.astimezone(timezone.utc)
    floor = end - timedelta(days=lookback_days)
    while end > floor:
        start = max(floor, end - timedelta(days=1))
        fires = fires_between(expr, start, end, tz)
        if fires:
            return fires[-1]
        end = start
    return None
