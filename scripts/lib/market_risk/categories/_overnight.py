"""Overnight and Sunday futures-open prints for the extended_hours category (operator 2026-10-31: "No excuses").

Rows come from ``market_quotes_extended`` with session ``overnight`` (20:00-04:00 ET, Sunday night to Friday 04:00)
or ``futures_open`` (Sunday 18:00-20:00 ET, futures). Their ``session_date`` is the NEXT trading day
(scripts/lib/overnight_session.py). Built on #2425's per-symbol aging and fail-closed proof (``extended_hours._proof``).

* **A level-only print is tied to the close, or it is not used** (review of #2423, F1). Schwab sends no dated
  close for some prints, so they are stored as a level. Such a row gets the close of the last referenced print of
  the SAME symbol that measures against the SAME close (``reference_date`` == the session the night follows;
  e.g. Thursday's Alpaca 19:55 after-hours SPY, -1.9% vs Thursday's close). It then reads e.g. -1.9%, not +0.1% vs
  its own first print. A level-only row with no such anchor is dropped. It never replaces the symbol's referenced
  row, and when nothing else is left the symbol is named as unproven, so the category reads UNKNOWN.
* **Stale is UNKNOWN, never CALM.** An overnight / futures-open print older than
  ``extended_hours.overnight.stale_after_minutes`` (wall clock: the session is trading) is dropped. The reason names
  the symbol, session, trading date and age in minutes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable
from zoneinfo import ZoneInfo

from scripts.lib.market_risk import sessions

NIGHT_SESSIONS = ("overnight", "futures_open")
ET = ZoneInfo("America/New_York")


def _at(row: dict[str, Any]) -> datetime | None:
    try:
        d = datetime.fromisoformat(str(row.get("as_of")).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else None


def is_night(row: dict[str, Any]) -> bool:
    return str(row.get("session") or "").lower() in NIGHT_SESSIONS


def _limit_minutes(cfg: dict[str, Any]) -> float:
    o = cfg.get("overnight")
    if not isinstance(o, dict) or "stale_after_minutes" not in o:
        raise ValueError("config/market_risk_policy.yaml extended_hours.overnight.stale_after_minutes missing")
    return float(o["stale_after_minutes"])


def _hhmm(at: datetime) -> str:
    return at.astimezone(ET).strftime("%a %m-%d %H:%M ET")


def anchor_level_only(
    rows: list[dict[str, Any]], extended_sessions: tuple[str, ...], source_ok: Callable[[str], bool]
) -> tuple[list[dict[str, Any]], dict[str, tuple[dict[str, Any], str]]]:
    """(rows with every level-only night row either anchored or removed, {symbol: (newest unanchored row, why)}).

    An anchor is an earlier row of the same symbol in an extended session, from an allowed source, carrying a
    ``prev_close`` and a ``reference_date`` equal to the session the level-only print follows
    (``sessions.last_closed_session``). The anchored row keeps its own price and takes the anchor's close and date,
    so its move is measured from the close itself."""
    refd: dict[str, list[tuple[datetime, dict[str, Any]]]] = {}
    for r in rows:
        at = _at(r)
        if (
            at is not None
            and str(r.get("session") or "").lower() in extended_sessions
            and r.get("prev_close") not in (None, "")
            and r.get("reference_date")
            and source_ok(str(r.get("source") or ""))
        ):
            refd.setdefault(str(r.get("symbol") or "").upper(), []).append((at, r))
    out: list[dict[str, Any]] = []
    unanchored: dict[str, tuple[dict[str, Any], str]] = {}
    for r in rows:
        if not is_night(r) or r.get("prev_close") not in (None, ""):
            out.append(r)
            continue
        sym, at = str(r.get("symbol") or "").upper(), _at(r)
        want = sessions.last_closed_session(at).isoformat() if at is not None else None
        cands = [(t, a) for t, a in refd.get(sym, []) if at is not None and t < at
                 and str(a.get("reference_date"))[:10] == want]
        if not cands:
            why = f"level-only (no dated close); no earlier referenced {sym} print ties it to the {want} close"
            if sym not in unanchored or str(r.get("as_of")) > str(unanchored[sym][0].get("as_of")):
                unanchored[sym] = (r, why)
            continue
        t, a = max(cands, key=lambda c: c[0])
        out.append({
            **r,
            "prev_close": a["prev_close"],
            "reference_date": a["reference_date"],
            "reference_basis": f"anchored:{a.get('reference_basis') or a.get('source')}",
            "reference": f"{want} close (via {a.get('session')} {a.get('source')} print {_hhmm(t)})",
        })
    return out, unanchored


def is_fresh(row: dict[str, Any], market_age_h: float | None, stale_h: float, now: datetime,
             cfg: dict[str, Any]) -> bool:
    """Night rows: wall-clock minutes against ``overnight.stale_after_minutes``. Other rows: #2425's market-clock
    hours against ``stale_after_hours``. Each symbol is aged on its own row (review of #2423, F3)."""
    if not is_night(row):
        return market_age_h is not None and market_age_h <= stale_h
    at = _at(row)
    return at is not None and (now - at).total_seconds() / 60.0 <= _limit_minutes(cfg)


def stale_reason(sym: str, row: dict[str, Any], move: float | None, now: datetime, cfg: dict[str, Any]) -> str:
    at = _at(row)
    age = "with no timestamp" if at is None else f"{round((now - at).total_seconds() / 60.0)} min old"
    mv = f" {move:+.1f}%" if move is not None else ""
    return (f"{sym}{mv} {row.get('session')} (trading date {str(row.get('session_date'))[:10]}) at "
            f"{_hhmm(at) if at else 'time unknown'} is {age} (limit {_limit_minutes(cfg):g} min; never CALM)")


def stale_after_hours(latest: dict[str, dict[str, Any]], cfg: dict[str, Any], default: float) -> float:
    """The observation's own staleness: the overnight limit when a night row is measured, else ``default``."""
    if any(is_night(r) for r in latest.values()):
        return min(default, _limit_minutes(cfg) / 60.0)
    return default
