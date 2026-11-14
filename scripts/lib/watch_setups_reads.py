"""LQ-20261107-2993c: Watch v002 Setups/Sectors/Alerts read shapes with an honest as_of (WV-02).

as_of is data time or evaluator liveness, never request time; None means "unknown", never "now".
"""
from __future__ import annotations

from datetime import datetime


def _iso(v):
    if v is None:
        return None
    return v.isoformat() if isinstance(v, datetime) else str(v)


def sectors_payload(db_query) -> dict:
    rows = db_query("""SELECT sector, count(DISTINCT symbol) AS n,
                              (array_agg(DISTINCT symbol ORDER BY symbol))[1:10] AS sample
                       FROM incubator_universe WHERE sector IS NOT NULL AND sector <> ''
                       GROUP BY sector ORDER BY count(DISTINCT symbol) DESC""")
    if rows is None:
        # _db_required returns None for "ran, no rows" and RAISES on a failed read (a 503), so None means EMPTY, not failed.
        return {"sectors": [], "as_of": None, "as_of_basis": None, "status": "empty"}
    stamp = db_query("SELECT max(updated_at) AS as_of, count(*) AS n FROM incubator_universe")
    as_of = _iso(stamp[0].get("as_of")) if stamp else None
    return {"sectors": [{"sector": r["sector"], "count": r["n"], "sample": r.get("sample") or []} for r in rows],
            "as_of": as_of, "as_of_basis": "incubator_universe.updated_at"}


def _newest(rows, keys):
    best = None
    for r in rows:
        for k in keys:
            v = r.get(k)
            if v is not None and (best is None or str(v) > str(best)):
                best = v
    return _iso(best)


def alerts_payload(rows, *, root=None, now=None) -> dict:
    from lib.watch_alerts_record import read_record
    ev = read_record(root=root, now=now)
    newest = _newest(rows, ("last_fired_at", "created_at"))
    # as_of keeps its WV-02 meaning (store data time). Liveness is a separate, evaluator-derived field.
    return {"ok": True, "active_count": sum(1 for r in rows if r.get("active")),
            "as_of": newest, "rows_newest_at": newest,
            "liveness_at": ev["last_run_at"], "liveness_basis": "evaluator_last_run", "evaluator": ev}


def pins_as_of(pins) -> dict:
    """Clock of the screener-find rows the Discover tab lists (NOT the dead watch_candidate_events feed).

    Newest research stamp over the shown pins, else newest pinned_at; None when there are no pins (unknown, never now)."""
    for key in ("auto_research_at", "pinned_at"):
        best = _newest(list(pins or []), (key,))
        if best is not None:
            return {"pins_as_of": best, "pins_as_of_basis": f"screener_find_pins.{key}"}
    return {"pins_as_of": None, "pins_as_of_basis": None}
