"""Overnight and Sunday futures-open prints for the extended_hours category (operator 2026-10-31: "No excuses").

Rows come from ``market_quotes_extended`` with session ``overnight`` (20:00-04:00 ET, Sunday night to Friday 04:00)
or ``futures_open`` (Sunday 18:00-20:00 ET, futures). Their ``session_date`` is the NEXT trading day
(scripts/lib/overnight_session.py). Two rules live here, kept apart from extended_hours.py so the category's own
logic is untouched:

* **No reference, no guess.** A level-only row (Schwab gave no previous close or settlement for that date) is
  compared with the EARLIEST stored level of the same symbol and trading date (``prior_stored_level``), and the
  evidence says so. A symbol with only one stored level has no move at all.
* **Stale is UNKNOWN, never CALM.** An overnight / futures-open row older than
  ``extended_hours.overnight.stale_after_minutes`` is dropped from the measurement. When nothing fresher remains,
  the category is UNKNOWN, and the reason names each symbol, its session, its trading date and its age.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from scripts.lib.market_risk.contract import Evidence

NIGHT_SESSIONS = ("overnight", "futures_open")
ET = ZoneInfo("America/New_York")


def _at(row: dict[str, Any]) -> datetime | None:
    try:
        d = datetime.fromisoformat(str(row.get("as_of")).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else None


def _night(row: dict[str, Any]) -> bool:
    return str(row.get("session") or "").lower() in NIGHT_SESSIONS


def _ocfg(cfg: dict[str, Any]) -> dict[str, Any]:
    o = cfg.get("overnight")
    if not isinstance(o, dict) or "stale_after_minutes" not in o:
        raise ValueError("config/market_risk_policy.yaml extended_hours.overnight.stale_after_minutes missing")
    return o


def with_baselines(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Level-only night rows get ``prev_close`` = the earliest stored level of that symbol and trading date, and say
    so (``reference_basis`` prior_stored_level, ``reference_label``). Rows with a reference are returned unchanged."""
    first: dict[tuple[str, str], dict[str, Any]] = {}
    for r in rows:
        if _night(r) and _at(r) is not None:
            k = (str(r.get("symbol") or "").upper(), str(r.get("session_date")))
            if k not in first or _at(r) < _at(first[k]):
                first[k] = r
    out = []
    for r in rows:
        if not _night(r) or r.get("prev_close") not in (None, ""):
            out.append(r)
            continue
        base = first.get((str(r.get("symbol") or "").upper(), str(r.get("session_date"))))
        if base is None or base is r or _at(base) is None or _at(base) >= _at(r):
            out.append(r)  # nothing earlier: a level with no move
            continue
        hhmm = _at(base).astimezone(ET).strftime("%a %H:%M ET")
        out.append({**r, "prev_close": base["price"], "reference_basis": "prior_stored_level", "reference_date": None,
                    "reference_label": f"first stored {base.get('session')} level {hhmm} (no close in payload)"})
    return out


def split_stale(latest: dict[str, dict[str, Any]], now: datetime, cfg: dict[str, Any]):
    """(fresh rows, stale night rows as dicts). Only overnight / futures-open rows are aged here; premarket and
    after-hours rows keep the category's own ``stale_after_hours``."""
    fresh, stale = {}, []
    for s, r in latest.items():
        if not _night(r):
            fresh[s] = r
            continue
        limit = float(_ocfg(cfg)["stale_after_minutes"])  # required once a night row is present; fails loudly
        at = _at(r)
        age = None if at is None else (now - at).total_seconds() / 60.0
        if age is None or age > limit:
            stale.append({"symbol": s, "session": r.get("session"), "session_date": str(r.get("session_date")),
                          "as_of": r.get("as_of"), "age_minutes": None if age is None else round(age)})
        else:
            fresh[s] = r
    return fresh, stale


def stale_reason(stale: list[dict[str, Any]], cfg: dict[str, Any]) -> str:
    limit = _ocfg(cfg)["stale_after_minutes"]
    parts = [
        f"{x['symbol']} {x['session']} (trading date {x['session_date']}) "
        + (f"{x['age_minutes']} min old" if x["age_minutes"] is not None else "has no timestamp")
        for x in sorted(stale, key=lambda x: x["symbol"])
    ]
    return f"stale {'/'.join(sorted({str(x['session']) for x in stale}))} quotes: " + ", ".join(parts) + (
        f"; stale after {limit} min, so not measured (never CALM)"
    )


def stale_evidence(stale: list[dict[str, Any]], cfg: dict[str, Any]) -> list[Evidence]:
    limit = _ocfg(cfg)["stale_after_minutes"]
    return [
        Evidence(
            label=f"{x['symbol']} {x['session']} quote stale (not used)",
            value=x["age_minutes"],
            as_of=x["as_of"],
            source="market_quotes_extended",
            detail=f"{x['age_minutes']} min old > {limit} min (trading date {x['session_date']})",
        )
        for x in stale
    ]


def stale_after_hours(latest: dict[str, dict[str, Any]], cfg: dict[str, Any], default: float) -> float:
    """The observation's own staleness: the overnight limit when a night row is measured, else ``default``."""
    if any(_night(r) for r in latest.values()):
        return min(default, float(_ocfg(cfg)["stale_after_minutes"]) / 60.0)
    return default
