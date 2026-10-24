"""CIO display truth over existing registered projections; no store or authority.

All functions are read-only. Callers may inject projections for fixture rendering.
Missing evidence stays None with a reason. No provider, broker or execution calls.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any


def stance_for(security_guid: str, *, db_query=None, now: datetime | None = None,
               projection: dict[str, Any] | None = None, **projection_kwargs) -> dict[str, Any]:
    """One GUID's CIO stance/conviction, conflicts and provenance.

    Wraps data_broker.cio_prospect, including its store/shadow admission and
    freshness rules. A symbol match is never a substitute for a GUID match.
    ``projection`` is the unmodified get_prospects response for batch consumers.
    Lower-level advice remains in conflicts; it never replaces the CIO stance.
    """
    guid = str(security_guid or "").strip()
    if projection is None and guid:
        from .data_broker.cio_prospect import get_prospects
        projection = get_prospects(db_query=db_query, symbols=[guid], now=now, **projection_kwargs)
    doc = projection or {}
    rows = [r for r in doc.get("prospects", []) if str(r.get("security_guid") or "") == guid and guid]
    row = max(rows, key=lambda r: (str(r.get("as_of") or ""), int(r.get("revision") or 0)), default={})
    missing = not row or row.get("stance") is None or row.get("conviction") is None
    return {
        "security_guid": guid or None,
        "symbol": row.get("symbol"),
        "stance": row.get("stance"),
        "conviction": row.get("conviction"),
        "conflicts": deepcopy(row.get("conflicts") or []),
        "revision": row.get("revision"),
        "as_of": row.get("as_of") or doc.get("as_of"),
        "age_hours": row.get("age_hours", doc.get("age_hours")),
        "stale": bool(row.get("stale", doc.get("stale", True))),
        "source": deepcopy(doc.get("source") or {}),
        "gap": {"reason": "CIO stance or conviction unavailable for this security GUID"} if missing else None,
    }
