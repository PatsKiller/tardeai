"""LQ-20261107-1253 amendment 3 — the "Last updated" strip of the since-close card.

Pure logic plus one read-only fetch.  Every per-source chip carries the source's OWN clock (the newest row's
timestamp or the file's mtime), never the build time: a build that ran a minute ago over a three-day-old stop capture
must still say the stops are three days old.  A missing clock is a stated gap, not a fresh chip.

Amber ("warn") rules, one place:
  * older than 24 h                         -> "⚠ N days old" (or "⚠ N h old" under two days)
  * older than the last regular-session close -> same, because a recap window starts there
  * prices while the market is closed       -> the label is the close ("Fri close"), amber only if there is no quote
    from the last session day at all
  * no timestamp / source absent            -> "⚠ not available"

``next_refresh`` mirrors the n8n cadence in the DONE note; if the lane is registered differently, change FIXED_SLOTS / _day_slots here.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

try:
    from lib.market_risk import sessions
except ImportError:  # pragma: no cover - imported as scripts.lib
    from scripts.lib.market_risk import sessions

ET = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")
STALE_AFTER = timedelta(hours=24)

# (key, label) in display order.
SOURCES: tuple[tuple[str, str], ...] = (
    ("news", "News"),
    ("positions", "Positions"),
    ("market_risk", "Market risk"),
    ("cio_brief", "CIO brief"),
    ("prices", "Prices"),
    ("stops", "Schwab stops"),
)

SQL_CLOCKS: dict[str, str] = {
    "news": "SELECT max(published_at) FROM news_articles WHERE published_at <= now()",
    "positions": "SELECT max(as_of) FROM positions_current",
    "prices": "SELECT max(fetched_at) FROM market_quotes",
    "stops": "SELECT max(captured_at) FROM stop_last_known",
}


def _dt(v: Any) -> datetime | None:
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=UTC)
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=UTC)


def _iso(d: datetime) -> str:
    return d.astimezone(UTC).isoformat().replace("+00:00", "Z")


def stamp_text(d: datetime) -> str:
    """'Sun 11-08 · 5:51 PM ET' — the day of week, the date and the clock in ET."""
    e = d.astimezone(ET)
    return f"{e.strftime('%a')} {e.strftime('%m-%d')} · {e.strftime('%-I:%M %p')} ET"


def age_text(seconds: float) -> str:
    if seconds < 90:
        return "just now"
    if seconds < 3600:
        return f"{int(seconds // 60)} min ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)} h ago"
    days = int(seconds // 86400)
    return f"{days} day{'s' if days != 1 else ''} ago"


def _warn_text(seconds: float) -> str:
    if seconds >= 86400:
        days = int(seconds // 86400)
        return f"⚠ {days} day{'s' if days != 1 else ''} old"
    return f"⚠ {int(seconds // 3600)} h old"


def source_chip(
    key: str, label: str, at: Any, *, now: datetime, window_start: datetime, market_open: bool, close_tag: str, session_day: date,
) -> dict[str, Any]:
    d = _dt(at)
    if d is None:
        return {"key": key, "label": label, "at": None, "at_text": None, "age_seconds": None, "age_text": "not available", "warn": True, "warn_text": "⚠ not available", "note": None}
    age = max(0.0, (now - d).total_seconds())
    chip: dict[str, Any] = {
        "key": key, "label": label, "at": _iso(d), "at_text": stamp_text(d), "age_seconds": age, "age_text": age_text(age),
        "warn": False, "warn_text": None, "note": None,
    }
    if key == "prices" and not market_open:
        # a closed market has one honest price: the close.  Amber only when not even the last session day has a quote.
        chip["age_text"] = close_tag
        chip["note"] = f"market closed; last quote fetched {stamp_text(d)}"
        if d.astimezone(ET).date() < session_day:
            chip["warn"], chip["warn_text"] = True, _warn_text(age)
        return chip
    if age > STALE_AFTER.total_seconds() or d < window_start:
        chip["warn"], chip["warn_text"] = True, _warn_text(age)
    return chip


# ---------------------------------------------------------------------------- the cadence


FIXED_SLOTS = (time(6, 0), time(8, 30), time(9, 15), time(9, 45), time(10, 30), time(12, 0), time(14, 0), time(15, 30), time(16, 15))
CIO_SLOTS = (time(6, 0), time(9, 15), time(12, 0), time(16, 15))
MISSED_GRACE = timedelta(minutes=30)


def _checks(d: date) -> list[time]:
    """The 15-min --if-changed checks, 09:30-16:00."""
    out, t = [], datetime.combine(d, time(9, 30))
    while t <= datetime.combine(d, time(16, 0)):
        out.append(t.time())
        t += timedelta(minutes=15)
    return out


def _day_slots(d: date) -> list[time]:
    """Run times (ET) on calendar day ``d`` (operator cadence, amendment 1260/1261): a trading day = the nine fixed full
    rebuilds, the 15-min --if-changed checks 09:30-16:00, hourly 18:00-04:00; a weekend or holiday = every 2 h."""
    if not sessions.is_trading_day(d):
        return [time(h, 0) for h in range(0, 24, 2)]
    out = set(FIXED_SLOTS) | set(_checks(d)) | {time(h, 0) for h in range(0, 5)} | {time(h, 0) for h in range(18, 24)}
    return sorted(out)


def schedule_for(d: date) -> dict[str, Any]:
    """Today's slots for the chip row.  The client marks done/next/missed against its own clock."""
    trading = sessions.is_trading_day(d)

    def iso(t: time) -> str:
        return _iso(datetime.combine(d, t, ET))

    if not trading:
        return {"trading_day": False, "fixed": [{"at": iso(t), "text": t.strftime("%-I:%M %p")} for t in _day_slots(d)], "cio": [], "market_open": None, "market_close": None}
    return {
        "trading_day": True,
        "fixed": [{"at": iso(t), "text": t.strftime("%-I:%M %p")} for t in FIXED_SLOTS],
        "cio": [iso(t) for t in CIO_SLOTS],
        "market_open": iso(time(9, 30)), "market_close": iso(sessions.close_time(d)),
        "check_every_min": 15,
        "grace_min": int(MISSED_GRACE.total_seconds() // 60),
    }


def missed_slot(now: datetime, updated_at: datetime) -> datetime | None:
    """A fixed slot during market hours that is more than 30 min past with no build since it -> the lane failed."""
    e = now.astimezone(ET)
    d = e.date()
    if not sessions.is_trading_day(d):
        return None
    lo, hi = datetime.combine(d, time(9, 30), ET), datetime.combine(d, sessions.close_time(d), ET) + timedelta(minutes=15)
    for t in FIXED_SLOTS:
        s = datetime.combine(d, t, ET)
        if lo <= s <= hi and e - s > MISSED_GRACE and updated_at < s:
            return s
    return None


def next_refresh(now: datetime) -> datetime:
    e = now.astimezone(ET)
    for add in range(0, 5):
        d = e.date() + timedelta(days=add)
        for t in _day_slots(d):
            c = datetime.combine(d, t, ET)
            if c > e:
                return c
    raise RuntimeError("no scheduled refresh within 4 days")  # pragma: no cover - the calendar always has a slot


# ---------------------------------------------------------------------------- the strip


def file_clock(path: Path) -> datetime | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, UTC)
    except OSError:
        return None


def cio_clock(brief: Mapping[str, Any] | None) -> Any:
    if not brief:
        return None
    for k in ("generated_at", "generated_at_utc", "as_of", "created_at"):
        if brief.get(k):
            return brief[k]
    return None


def build_stamp(*, now: datetime, window: Mapping[str, Any], clocks: Mapping[str, Any]) -> dict[str, Any]:
    """``clocks`` maps SOURCES keys to a datetime / ISO string / None.  ``now`` is the build instant: it is the card's
    own "last updated", and is never copied onto a source chip."""
    start = _dt(window["start"]) or now
    session_day = date.fromisoformat(window["session_date"])
    chips = [
        source_chip(k, lbl, clocks.get(k), now=now, window_start=start, market_open=bool(window.get("session_open")),
                    close_tag=str(window.get("close_tag") or "last close"), session_day=session_day)
        for k, lbl in SOURCES
    ]
    nxt = next_refresh(now)
    return {
        "updated_at": _iso(now), "updated_text": stamp_text(now),
        "next_refresh_at": _iso(nxt), "next_refresh_text": stamp_text(nxt),
        "sources": chips, "any_warn": any(c["warn"] for c in chips),
        "schedule": schedule_for(now.astimezone(ET).date()),
    }


def fetch_clocks(conn: Any) -> dict[str, datetime | None]:
    """Newest-row clocks from the four tables, read-only.  Each read is isolated: a failed statement rolls back so it
    cannot poison the next one, and that source reads as None (shown as 'not available', never as fresh)."""
    out: dict[str, datetime | None] = {}
    for key, sql in SQL_CLOCKS.items():
        try:
            with conn.cursor() as cur:
                cur.execute(sql)
                row = cur.fetchone()
            out[key] = row[0] if row else None
        except Exception:  # noqa: BLE001 -- one missing table leaves one chip amber, not the card
            try:
                conn.rollback()
            except Exception:  # noqa: BLE001 -- a dead connection fails the next read the same way
                pass
            out[key] = None
    return out
