"""Shared helpers for the market-data categories: row timestamps, per-symbol close series, scoring by points.

Row shapes accepted from the DataReader (production reader or fixture): a timestamp in ``as_of``, ``observed_at``,
``date`` or ``ts``; a symbol in ``symbol``; a price in ``close`` (bars) or ``value`` (FRED); FRED series in
``series_id`` or ``series``.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timezone
from typing import Any, Iterable

from scripts.lib.market_risk.contract import CategoryObservation, Evidence, assert_no_behavior_fields


def ts(row: dict[str, Any]) -> datetime | None:
    v = row.get("as_of") or row.get("observed_at") or row.get("date") or row.get("ts")
    if v is None:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if isinstance(v, date):
        return datetime(v.year, v.month, v.day, 21, tzinfo=timezone.utc)  # a daily close ~16:00-17:00 ET
    s = str(v).replace("Z", "+00:00")
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        return None
    if len(s) == 10:
        return d.replace(hour=21, tzinfo=timezone.utc)
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def num(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def closes_by_symbol(rows: Iterable[dict[str, Any]]) -> dict[str, list[tuple[datetime, float]]]:
    """{symbol: [(ts, close), ...] oldest first, one row per day (last wins)}."""
    tmp: dict[str, dict[str, tuple[datetime, float]]] = {}
    for r in rows:
        sym, t, c = r.get("symbol"), ts(r), num(r.get("close", r.get("value")))
        if not sym or t is None or c is None:
            continue
        tmp.setdefault(str(sym), {})[t.date().isoformat()] = (t, c)
    return {s: [d[k] for k in sorted(d)] for s, d in tmp.items()}


DEFAULT_BREAK_RATIO = 2.5


def price_break(closes: list[float], max_ratio: float = DEFAULT_BREAK_RATIO) -> tuple[int, float] | None:
    """The newest one-session move of at least ``max_ratio`` either way, as (index of the first close after it, the
    after/before ratio); None when there is none (PKG-SELLOFF-INTEL-20261106 F).

    An index or sector ETF does not move 2.5x in one session (the market-wide circuit breaker halts trading at -20%), so
    such a step is a break in the price history, almost always an unadjusted split. SOXX on 2026-11-05: 451.20 -> 130.94
    (a 3-for-1 split on a falling day) made "SOXX -79.1% off 52w high" out of a pre-split high. Measures must not span it.
    """
    ratio = float(max_ratio)
    for i in range(len(closes) - 1, 0, -1):
        a, b = closes[i - 1], closes[i]
        if a and b and a > 0 and b > 0 and max(b / a, a / b) >= ratio:
            return i, b / a
    return None


def break_note(sym: str, when: Any, step: float, kept: int) -> str:
    day = when.date().isoformat() if isinstance(when, datetime) else str(when)[:10]
    return (
        f"{sym} price history breaks on {day} (close x{step:.2f} in one session; likely an unadjusted split): "
        f"only the {kept} session{'' if kept == 1 else 's'} since are used"
    )


def series_by_id(rows: Iterable[dict[str, Any]]) -> dict[str, list[tuple[datetime, float]]]:
    tmp: dict[str, dict[str, tuple[datetime, float]]] = {}
    for r in rows:
        sid, t, v = r.get("series_id") or r.get("series"), ts(r), num(r.get("value"))
        if not sid or t is None or v is None:
            continue
        tmp.setdefault(str(sid), {})[t.date().isoformat()] = (t, v)
    return {s: [d[k] for k in sorted(d)] for s, d in tmp.items()}


def pct(a: float, b: float) -> float:
    return (a / b - 1.0) * 100.0 if b else 0.0


def sma(vals: list[float], n: int) -> float | None:
    return sum(vals[-n:]) / n if len(vals) >= n else None


def stale(newest: datetime | None, now: datetime, hours: float, decay_cfg: dict[str, Any] | None = None) -> bool:
    """True when ``newest`` is missing or unusable at ``now``. With ``decay_cfg`` (the policy's ``decay`` block) this is
    ``scoring.staleness``: the same market clock, future-stamp check and hard caps the scorer applies, so a weekend
    does not age a category's inputs and truly old inputs are still refused. Without it, wall-clock hours."""
    if newest is None:
        return True
    if decay_cfg:
        from scripts.lib.market_risk.scoring import staleness

        return staleness(newest, now, decay_cfg, float(hours))[1] is not None
    return (now - newest).total_seconds() / 3600.0 > float(hours)


def iso(t: datetime | None) -> str | None:
    return t.astimezone(timezone.utc).isoformat() if t else None


def observation(
    category: str,
    cfg: dict[str, Any],
    fired: list[tuple[str, Evidence]],
    context: list[Evidence],
    newest: datetime,
    *,
    headline_prefix: str,
    improving: list[Evidence] | None = None,
) -> CategoryObservation:
    """Sum the points of fired sub-signals (capped at 100) and map to CALM / WARN / STRESS. A CALM category with an
    ``improving`` signal (design §5.2 Green inputs) is IMPROVING; WARN/STRESS are never softened by it."""
    pts = cfg["points"]
    score = float(min(100, sum(int(pts[k]) for k, _ in fired)))
    state = "STRESS" if score >= cfg["stress_score"] else "WARN" if score >= cfg["warn_score"] else "CALM"
    if state == "CALM" and improving:
        state = "IMPROVING"
        headline = f"{headline_prefix} improving: " + " · ".join(e.detail or e.label for e in improving[:3])
        context = list(improving) + list(context)
    elif fired:
        top = sorted(fired, key=lambda kv: -int(pts[kv[0]]))[:3]
        headline = f"{headline_prefix}: " + " · ".join(e.detail or e.label for _, e in top)
    else:
        headline = f"{headline_prefix}: no stress signal"
    obs = CategoryObservation(
        category=category,
        state=state,  # type: ignore[arg-type]
        score=score,
        observed_at=iso(newest) or "",
        headline=headline,
        evidence=tuple(e for _, e in fired) + tuple(context),
        stale_after_hours=float(cfg["stale_after_hours"]),
    )
    assert_no_behavior_fields(obs.to_dict())
    return obs
