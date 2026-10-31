"""Event concentration for the Market Risk Engine (DSN-20261031-market-risk-engine P1-T6).

``evaluate_concentration`` turns three deterministic inputs into ``event_concentration_score`` 0-100:

* earnings: the index-cap share of members reporting in the next 1/3/5 sessions (weights are index-cap shares from
  the caller; ``symbol_profiles.earnings_date`` rows come through ``DataReader.earnings_calendar``);
* macro: FOMC / CPI / employment releases from ``DataReader.macro_calendar`` (``config/macro_calendar_overrides.json``
  merged by ``scripts/macro_calendar_refresh.py``);
* calendar: month-end, quarter-end, options expiration (``scripts/lib/cio_market_calendar.py``) and the US federal
  election day in even years.

Missing weights make the earnings part UNKNOWN (reported, never counted as zero). Advisory only.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from scripts.lib import cio_market_calendar as mcal

ET = ZoneInfo("America/New_York")


def _hhmm(s: str) -> time:
    h, m = str(s).split(":")
    return time(int(h), int(m))


def _as_date(v: Any) -> date | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.astimezone(ET).date() if v.tzinfo else v.date()
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def election_day(year: int) -> date | None:
    """US federal general election: the Tuesday after the first Monday of November, even years only."""
    if year % 2:
        return None
    d = date(year, 11, 1)
    first_monday = d + timedelta(days=(0 - d.weekday()) % 7)
    return first_monday + timedelta(days=1)


def next_sessions(now: datetime, n: int) -> list[date]:
    """The next ``n`` sessions whose close is still ahead: today counts until 16:00 ET."""
    local = now.astimezone(ET)
    d = local.date()
    if not (mcal.is_us_trading_day(d) and local.time() < time(16, 0)):
        d += timedelta(days=1)
    out: list[date] = []
    while len(out) < n:
        if mcal.is_us_trading_day(d):
            out.append(d)
        d += timedelta(days=1)
    return out


def _earnings_counts(row: dict, now: datetime, window: list[date], cfg: dict) -> bool:
    d = _as_date(row.get("earnings_date") or row.get("date"))
    if d is None:
        return False
    local = now.astimezone(ET)
    timing = str(row.get("timing") or "AMC").upper()
    if d == local.date():
        if timing == "BMO":
            return local.time() < _hhmm(cfg.get("bmo_cutoff_et", "09:30"))
        return local.time() < _hhmm(cfg.get("amc_cutoff_et", "20:00"))
    return d in window


def earnings_share(
    now: datetime,
    rows: Iterable[dict],
    weights: dict[str, float],
    sessions: int,
    cfg: dict,
    symbols: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Index-cap share (0-1) reporting within ``sessions``; optionally restricted to ``symbols``."""
    window = next_sessions(now, sessions)
    aliases = {str(k).upper(): str(v).upper() for k, v in (cfg.get("issuer_aliases") or {}).items()}
    keep = {aliases.get(s.upper(), s.upper()) for s in symbols} if symbols is not None else None
    reporters: dict[str, float] = {}  # keyed by ISSUER: GOOG and GOOGL rows count Alphabet once
    for r in rows:
        sym = str(r.get("symbol") or "").upper()
        sym = aliases.get(sym, sym)
        if not sym or (keep is not None and sym not in keep):
            continue
        if _earnings_counts(r, now, window, cfg):
            reporters[sym] = float(weights.get(sym, 0.0))
    return {
        "sessions": sessions,
        "window": [d.isoformat() for d in window],
        "share": round(sum(reporters.values()), 6),
        "reporters": dict(sorted(reporters.items(), key=lambda kv: -kv[1])),
    }


def _macro_key(event: str, points: dict) -> str:
    e = event.lower()
    for k in points:
        if k != "default" and k in e:
            return k
    return "default"


def macro_events(now: datetime, rows: Iterable[dict], sessions: int) -> list[dict]:
    window = set(next_sessions(now, sessions))
    local = now.astimezone(ET)
    out = []
    for r in rows:
        d = _as_date(r.get("date"))
        if d is None or d not in window:
            continue
        t = r.get("time_et")
        if d == local.date() and t and local.time() >= _hhmm(t):
            continue  # already released
        out.append(
            {
                "date": d.isoformat(),
                "event": str(r.get("event") or ""),
                "time_et": t,
                "name": r.get("name") or r.get("event"),
            }
        )
    return out


def calendar_tags(now: datetime, sessions: int) -> list[dict]:
    window = next_sessions(now, sessions)
    tags: list[dict] = []
    for i, d in enumerate(window):
        nxt = window[i + 1] if i + 1 < len(window) else next_sessions(datetime.combine(d, time(17, 0), ET), 1)[0]
        if nxt.month != d.month:
            tags.append({"date": d.isoformat(), "tag": "quarter_end" if d.month in (3, 6, 9, 12) else "month_end"})
        if mcal.is_options_expiration(d):
            tags.append({"date": d.isoformat(), "tag": "options_expiration"})
    ed = election_day(now.astimezone(ET).year)
    if ed and window[0] <= ed <= window[-1] + timedelta(days=1):
        tags.append({"date": ed.isoformat(), "tag": "election_day"})
    return tags


def evaluate_concentration(
    now: datetime,
    earnings_rows: list[dict],
    macro_rows: list[dict],
    weights: dict[str, float] | None,
    cfg: dict,
) -> dict[str, Any]:
    """Deterministic event-concentration result. ``weights`` None -> earnings part UNKNOWN."""
    out: dict[str, Any] = {"as_of": now.isoformat(), "earnings": None, "earnings_unknown": None}
    if weights:
        shares = {
            str(n): earnings_share(now, earnings_rows, weights, int(n), cfg)
            for n in cfg.get("windows_sessions", [1, 3, 5])
        }
        out["earnings"] = shares
        drive = shares.get(str(cfg["earnings_window_sessions"])) or earnings_share(
            now, earnings_rows, weights, int(cfg["earnings_window_sessions"]), cfg
        )
        e_pts = float(cfg["earnings_max_points"]) * min(1.0, drive["share"] / float(cfg["earnings_share_full"]))
    else:
        out["earnings_unknown"] = "index weights unavailable"
        e_pts = 0.0
    mp = cfg["macro_points"]
    macros = macro_events(now, macro_rows, int(cfg["macro_window_sessions"]))
    m_pts = min(float(cfg["macro_max_points"]), sum(float(mp[_macro_key(m["event"], mp)]) for m in macros))
    tags = calendar_tags(now, int(cfg["calendar_window_sessions"]))
    cp = cfg["calendar_points"]
    c_pts = min(float(cfg["calendar_max_points"]), sum(float(cp.get(t["tag"], 0)) for t in tags))
    score = round(min(100.0, e_pts + m_pts + c_pts), 1)
    out.update(
        {
            "macro": macros,
            "calendar": tags,
            "points": {"earnings": round(e_pts, 1), "macro": round(m_pts, 1), "calendar": round(c_pts, 1)},
            "event_concentration_score": score,
        }
    )
    return out
