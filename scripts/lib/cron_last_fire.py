"""cron_last_fire — the most recent scheduled fire time for a 5-field cron expression (no third-party dep).

Used by the supervisor breach detector (06 §5) so that NO_OUTPUT means "a scheduled run should have
produced since the last output and did not", instead of "the file is older than 3 × cadence" — which
paged every weekday-only lane on a Sunday (2026-09-27 triage: 6 of 25 breaches).

Supports: `*`, lists `a,b`, ranges `a-b`, steps `*/n` and `a-b/n`, names for months and weekdays,
`@hourly` / `@daily` / `@weekly` / `@monthly`. Day-of-month and day-of-week combine with OR when both
are restricted (Vixie cron semantics). Times are naive local wall-clock like the crontab itself.
Authority: READ_ONLY_ADVISORY (pure function).
"""
from __future__ import annotations

import datetime as _dt

_MONTHS = {m: i + 1 for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split())}
_DOWS = {d: i for i, d in enumerate("sun mon tue wed thu fri sat".split())}
_ALIASES = {"@hourly": "0 * * * *", "@daily": "0 0 * * *", "@midnight": "0 0 * * *", "@weekly": "0 0 * * 0",
            "@monthly": "0 0 1 * *", "@yearly": "0 0 1 1 *", "@annually": "0 0 1 1 *"}


def _field(spec: str, lo: int, hi: int, names: dict | None = None) -> tuple[set[int], bool]:
    """Return (allowed values, restricted?)."""
    spec = spec.strip().lower()
    if names:
        for k, v in names.items():
            spec = spec.replace(k, str(v))
    out: set[int] = set()
    restricted = spec != "*"
    for part in spec.split(","):
        step = 1
        if "/" in part:
            part, s = part.split("/", 1); step = max(1, int(s))
        if part == "*":
            a, b = lo, hi
        elif "-" in part:
            a, b = (int(x) for x in part.split("-", 1))
        else:
            a = b = int(part)
        if a > b:
            a, b = b, a
        out.update(range(max(lo, a), min(hi, b) + 1, step))
    if 7 in out and hi == 6:  # cron allows 7 = Sunday
        out.discard(7); out.add(0)
    return out, restricted


def parse(expr: str) -> dict | None:
    expr = _ALIASES.get(expr.strip(), expr.strip())
    parts = expr.split()
    if len(parts) != 5:
        return None
    try:
        mins, _ = _field(parts[0], 0, 59)
        hours, _ = _field(parts[1], 0, 23)
        doms, dom_r = _field(parts[2], 1, 31)
        months, _ = _field(parts[3], 1, 12, _MONTHS)
        dows, dow_r = _field(parts[4].replace("7", "0") if parts[4].strip() == "7" else parts[4], 0, 6, _DOWS)
    except (ValueError, TypeError):
        return None
    return {"minutes": sorted(mins), "hours": sorted(hours), "doms": doms, "dom_restricted": dom_r,
            "months": months, "dows": dows, "dow_restricted": dow_r}


def _day_matches(spec: dict, day: _dt.date) -> bool:
    if day.month not in spec["months"]:
        return False
    cron_dow = (day.weekday() + 1) % 7  # Python Mon=0 → cron Sun=0
    dom_ok = day.day in spec["doms"]; dow_ok = cron_dow in spec["dows"]
    if spec["dom_restricted"] and spec["dow_restricted"]:
        return dom_ok or dow_ok
    return dom_ok and dow_ok


def last_fire(expr: str, now: _dt.datetime, *, max_days: int = 400) -> _dt.datetime | None:
    """Most recent fire time ≤ now (naive, same wall-clock as ``now``), or None if none within max_days."""
    spec = parse(expr)
    if not spec:
        return None
    now = now.replace(second=0, microsecond=0)
    day = now.date()
    for back in range(max_days):
        d = day - _dt.timedelta(days=back)
        if not _day_matches(spec, d):
            continue
        for h in reversed(spec["hours"]):
            for m in reversed(spec["minutes"]):
                t = _dt.datetime.combine(d, _dt.time(h, m), tzinfo=now.tzinfo)
                if t <= now:
                    return t
    return None


def next_fire(expr: str, now: _dt.datetime, *, max_days: int = 400) -> _dt.datetime | None:
    spec = parse(expr)
    if not spec:
        return None
    day = now.date()
    for fwd in range(max_days):
        d = day + _dt.timedelta(days=fwd)
        if not _day_matches(spec, d):
            continue
        for h in spec["hours"]:
            for m in spec["minutes"]:
                t = _dt.datetime.combine(d, _dt.time(h, m), tzinfo=now.tzinfo)
                if t > now:
                    return t
    return None


__all__ = ["parse", "last_fire", "next_fire"]
