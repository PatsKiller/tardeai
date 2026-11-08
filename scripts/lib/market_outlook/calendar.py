"""The macro/event calendar inside the formula (§2.6, §4.5): upcoming catalysts, the event tilt, U_event, FOMC windows.

Reads the existing ``MacroCalendar@v1`` runtime file (``scripts/macro_calendar.py``) plus the operator-owned FOMC dates
in ``config/macro_calendar_overrides.json``. Nothing here writes, and nothing here invents an event: a missing or stale
calendar yields an explicit reason, which the events category reports as UNKNOWN or as "no scheduled catalyst".
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from . import sessions_shim

ET = ZoneInfo("America/New_York")
PROJECT_ROOT = Path(__file__).resolve().parents[3]


@dataclass
class CalendarItem:
    date_et: str
    time_et: str
    event: str
    name: str
    impact: str          # HIGH | MED | LOW
    impact_weight: float
    source: str = ""
    consensus: str | None = None
    prior: str | None = None
    held_flag_per_account_id: list[str] = field(default_factory=list)
    at: str | None = None  # ISO instant of the scheduled time

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── the calendar file ------------------------------------------------------------------------------------------
def _state_root() -> Path:
    from . import state_root as srmod

    return srmod.resolve(None)


def _read_calendar(now: datetime) -> tuple[dict[str, Any] | None, str]:
    path = _state_root() / "data" / "runtime" / "macro_calendar.json"
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, f"macro calendar unreadable at {path} ({exc})"
    if body.get("schema") != "MacroCalendar@v1":
        return None, f"macro calendar schema {body.get('schema')!r}"
    fetched = _dt(body.get("fetched_at"))
    if fetched is None:
        return None, "macro calendar has no fetched_at"
    age_h = (now - fetched).total_seconds() / 3600.0
    if age_h > 72.0:
        return None, f"macro calendar is {age_h:.1f} h old (>72 h): fail closed"
    return body, ""


def _overrides() -> dict[str, Any]:
    path = PROJECT_ROOT / "config" / "macro_calendar_overrides.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


# ── impact vocabulary ------------------------------------------------------------------------------------------
def impact_of(event_key: str, policy: dict[str, Any]) -> tuple[float, str]:
    table = policy["events"]["impact"]
    weight = float(table.get(event_key, table["default"]))
    levels = policy["events"]["impact_levels"]
    if weight >= float(levels["high_at"]):
        return weight, "HIGH"
    if weight >= float(levels["med_at"]):
        return weight, "MED"
    return weight, "LOW"


def _fomc_dates(overrides: dict[str, Any], policy: dict[str, Any], start: date, end: date) -> list[CalendarItem]:
    block = (overrides or {}).get("fomc") or {}
    items: list[CalendarItem] = []
    for row in block.get("decision_dates") or []:
        try:
            d = date.fromisoformat(str(row.get("date")))
        except (TypeError, ValueError):
            continue
        weight, level = impact_of("fomc_decision", policy)
        if row.get("sep"):
            weight = min(1.0, weight * float(policy["events"]["sep_multiplier"]))
        t = str(block.get("time_et") or policy["events"]["presser_time_et"])
        if start <= d <= end:
            items.append(
                CalendarItem(date_et=d.isoformat(), time_et=t, event="fomc_decision",
                             name=str(block.get("name") or "FOMC rate decision"),
                             impact=level, impact_weight=weight, source="macro_calendar_overrides",
                             at=_instant(d, t).isoformat())
            )
        minutes = d + timedelta(days=int(policy["events"]["minutes_offset_days"]))
        if start <= minutes <= end:
            w2, l2 = impact_of("fomc_minutes", policy)
            items.append(
                CalendarItem(date_et=minutes.isoformat(), time_et=str(policy["events"]["minutes_time_et"]),
                             event="fomc_minutes", name="FOMC minutes", impact=l2, impact_weight=w2,
                             source="derived:decision+21d", at=_instant(minutes, str(policy["events"]["minutes_time_et"])).isoformat())
            )
    return items


def read_macro_events(now: datetime, horizon_days: int, policy: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Every scheduled catalyst from ``now`` through ``now + horizon_days`` (ET dates), oldest first."""
    policy = policy or _policy()
    body, why = _read_calendar(now)
    today = now.astimezone(ET).date()
    end = today + timedelta(days=int(horizon_days))
    items: list[CalendarItem] = []
    if body:
        for day, entry in (body.get("dates") or {}).items():
            try:
                d = date.fromisoformat(str(day))
            except (TypeError, ValueError):
                continue
            if not (today <= d <= end):
                continue
            for ev in entry.get("events") or []:
                key = str(ev.get("event") or "")
                weight, level = impact_of(key, policy)
                t = str(ev.get("time_et") or "08:30")
                items.append(
                    CalendarItem(
                        date_et=d.isoformat(), time_et=t, event=key,
                        name=str(ev.get("name") or key), impact=level, impact_weight=weight,
                        source=str(ev.get("source") or "fred"), at=_instant(d, t).isoformat(),
                    )
                )
    items.extend(_fomc_dates(_overrides(), policy, today, end))
    items.sort(key=lambda i: (i.date_et, i.time_et, i.event))
    return [i.to_dict() for i in items]


def calendar_reason(now: datetime) -> str | None:
    return _read_calendar(now)[1] or None


def _policy() -> dict[str, Any]:
    from . import policy as pmod

    return pmod.load_policy()


# ── the three effects ------------------------------------------------------------------------------------------
def sessions_until(d: date, now: datetime) -> int:
    """Sessions from the current one up to and including ``d`` (0 = today)."""
    today = now.astimezone(ET).date()
    if d <= today:
        return 0
    n, cur = 0, today
    while cur < d:
        cur += timedelta(days=1)
        if sessions_shim.is_trading_day(cur):
            n += 1
    return n


def upcoming(items: list[dict[str, Any]], now: datetime, sessions: int) -> list[dict[str, Any]]:
    out = []
    for it in items:
        try:
            d = date.fromisoformat(str(it["date_et"]))
        except (KeyError, ValueError):
            continue
        if sessions_until(d, now) <= int(sessions):
            out.append(it)
    return out


def tilt(items: list[dict[str, Any]], policy: dict[str, Any], now: datetime) -> tuple[float, str]:
    """tau = -tilt_per_impact * max impact inside the next ``tilt_sessions`` sessions (0 when nothing is scheduled)."""
    cfg = policy["events"]
    window = upcoming(items, now, int(cfg["tilt_sessions"]))
    if not window:
        return 0.0, f"no scheduled catalyst in the next {cfg['tilt_sessions']} sessions"
    top = max(window, key=lambda i: float(i["impact_weight"]))
    tau = -float(cfg["tilt_per_impact"]) * float(top["impact_weight"])
    return tau, f"{top['name']} {top['date_et']} {top['time_et']} ET ({top['impact']})"


def u_event(items: list[dict[str, Any]], policy: dict[str, Any], now: datetime, horizon_sessions: int) -> tuple[float, list[str]]:
    """Product over HIGH events inside the horizon of (1 - u_event_per_impact*impact), floored."""
    cfg = policy["events"]
    u, named = 1.0, []
    for it in upcoming(items, now, horizon_sessions):
        if str(it.get("impact")) != "HIGH":
            continue
        u *= 1.0 - float(cfg["u_event_per_impact"]) * float(it["impact_weight"])
        named.append(f"{it['event']} {it['date_et']}")
    return max(float(cfg["u_event_floor"]), u), named


def fomc_window(items: list[dict[str, Any]], policy: dict[str, Any], now: datetime) -> tuple[bool, str]:
    cfg = policy["fomc_window"]
    for it in upcoming(items, now, int(cfg["sessions"])):
        if str(it.get("event")) == "fomc_decision":
            return True, f"FOMC decision {it['date_et']} is inside the {cfg['sessions']}-session window"
    return False, ""


def prior_surprise(
    bundle: Any, policy: dict[str, Any], now: datetime, items: list[dict[str, Any]]
) -> tuple[float | None, str]:
    """Reaction proxy (§2.6c): the cash-index move in the 60 min after each HIGH/MED release, in 20-day ATR units."""
    cfg = policy["events"]["surprise"]
    window_min = int(cfg["window_minutes"])
    lookback = date.fromisoformat(str(now.astimezone(ET).date())) - timedelta(days=int(policy["events"]["horizon_days"]))
    atr_pct = _atr_pct(bundle, policy)
    if atr_pct is None:
        return None, "no 20-session ATR from the index bars; the reaction proxy cannot be normalised"
    prints = _index_prints(bundle)
    if not prints:
        return None, "no 60-minute cash-index prints in market_quotes_extended; no reaction proxy"
    weighed, total_w, notes = 0.0, 0.0, []
    for it in items:
        if str(it.get("impact")) not in ("HIGH", "MED"):
            continue
        try:
            d = date.fromisoformat(str(it["date_et"]))
            t = time.fromisoformat(str(it["time_et"]))
        except (KeyError, ValueError):
            continue
        if not (lookback <= d < now.astimezone(ET).date()):
            continue
        release = _instant(d, it["time_et"])
        if release > now:
            continue
        before = _nearest(prints, release, before=True)
        after = _nearest(prints, release + timedelta(minutes=window_min), before=True, floor=release)
        if before is None or after is None or not before[1]:
            continue
        move_atr = ((after[1] / before[1]) - 1.0) * 100.0 / atr_pct
        s = max(-1.0, min(1.0, move_atr / float(cfg["scale"])))
        weighed += float(it["impact_weight"]) * s
        total_w += float(it["impact_weight"])
        notes.append(f"{it['event']} {it['date_et']} {move_atr:+.2f} ATR")
    if total_w <= 0:
        return None, "no HIGH/MED release in the prior week with both prints available"
    return weighed / total_w, "; ".join(notes)


def _atr_pct(bundle: Any, policy: dict[str, Any]) -> float | None:
    bars = list((bundle.bars or {}).get("SPY") or [])
    n = int(policy["events"]["surprise"]["atr_sessions"])
    if len(bars) < n + 1:
        return None
    trs = []
    for i in range(len(bars) - n, len(bars)):
        high, low = _f(bars[i].get("high")), _f(bars[i].get("low"))
        prev = _f(bars[i - 1].get("close")) if i > 0 else None
        if high is None or low is None or prev is None:
            return None
        trs.append(max(high - low, abs(high - prev), abs(low - prev)))
    atr = sum(trs) / len(trs)
    close = _f(bars[-1].get("close")) or 0.0
    return (atr / close) * 100.0 if close else None


def _index_prints(bundle: Any) -> list[tuple[datetime, float]]:
    out: list[tuple[datetime, float]] = []
    for row in bundle.extended or []:
        if not str(row.get("symbol", "")).startswith("$SPX"):
            continue
        inst, price = _dt(row.get("bar_start")), _f(row.get("price"))
        if inst and price:
            out.append((inst, price))
    return sorted(out)


def _nearest(
    prints: list[tuple[datetime, float]], at: datetime, *, before: bool, floor: datetime | None = None
) -> tuple[datetime, float] | None:
    best = None
    for inst, price in prints:
        if before and inst > at:
            continue
        if not before and inst < at:
            continue
        if floor is not None and inst < floor:
            continue
        if best is None or (inst > best[0] if before else inst < best[0]):
            best = (inst, price)
    return best


# ── helpers ----------------------------------------------------------------------------------------------------
def _instant(d: date, hhmm: str) -> datetime:
    try:
        h, m = str(hhmm).split(":")
        t = time(int(h), int(m))
    except (ValueError, AttributeError):
        t = time(8, 30)
    return datetime.combine(d, t, ET)


def _dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _f(v: Any) -> float | None:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


__all__ = [
    "CalendarItem",
    "read_macro_events",
    "calendar_reason",
    "impact_of",
    "tilt",
    "u_event",
    "fomc_window",
    "prior_surprise",
    "upcoming",
    "sessions_until",
]
