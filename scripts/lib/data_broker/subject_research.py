"""Subject Research — read-only Data Broker projection over hermes_research_intelligence.

Registry domain ``research_thesis`` (32 writer modules today, consolidation target
scripts/lib/hermes_librarian/librarian.py; stale after 168h). Keyed by symbol or
by ``subject_guid`` (the UUIDv5 security_identity spine — see
reference_identity_memory_spine). Before Phase 4 scripts/api_v2.py read this table
directly in 31 places.

This projection READS ONLY. It does not queue research, call a lane, or touch a
provider; the registry's no_coverage rule (``say_so_queue_only_if_producer_exists``)
is for the caller to act on, with the envelope's gap as the evidence.
"""
from __future__ import annotations

from typing import Any

from lib.data_broker.envelope import envelope, newest

DOMAIN = "research_thesis"

_COLS = """id, created_at, updated_at, source, hermes_agent_name, research_type, symbol,
           subject_guid, issuer_guid, gics_sector, topic, summary, thesis, thesis_type,
           confidence_score, quality_score, freshness_date, research_expires_at, status,
           model_used, lane_used, tags, strategy_tags, category_sector"""

BY_SYMBOL_SQL = f"""SELECT {_COLS} FROM hermes_research_intelligence
                    WHERE upper(symbol)=%s ORDER BY created_at DESC LIMIT %s"""
BY_GUID_SQL = f"""SELECT {_COLS} FROM hermes_research_intelligence
                  WHERE subject_guid=%s::uuid ORDER BY created_at DESC LIMIT %s"""
BY_SECTOR_SQL = f"""SELECT {_COLS} FROM hermes_research_intelligence
                    WHERE (gics_sector=%s OR category_sector=%s)
                    ORDER BY created_at DESC LIMIT %s"""


def _clean(row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in row.items():
        if hasattr(v, "isoformat"):
            v = v.isoformat()
        elif type(v).__name__ in ("Decimal", "UUID"):
            v = float(v) if type(v).__name__ == "Decimal" else str(v)
        out[k] = v
    return out


def get_subject_research(db_query, *, symbol: str | None = None, subject_guid: str | None = None,
                         sector: str | None = None, limit: int = 20, now=None, registry=None) -> dict[str, Any]:
    """Research rows for one subject, newest first, wrapped in the read envelope.

    Exactly one of symbol / subject_guid / sector selects the rows. ``as_of`` is
    the newest row's created_at for THIS subject — a busy table does not make a
    stale thesis fresh.
    """
    rows: list[dict[str, Any]] = []
    error = None
    key: dict[str, Any] = {}
    try:
        lim = max(1, min(int(limit), 500))
        if subject_guid:
            key = {"subject_guid": str(subject_guid)}
            rows = db_query(BY_GUID_SQL, (str(subject_guid), lim), fetch="all") or []
        elif symbol:
            key = {"symbol": str(symbol).upper().strip()}
            rows = db_query(BY_SYMBOL_SQL, (key["symbol"], lim), fetch="all") or []
        elif sector:
            key = {"sector": str(sector)}
            rows = db_query(BY_SECTOR_SQL, (sector, sector, lim), fetch="all") or []
        else:
            error = "one of symbol / subject_guid / sector is required"
    except Exception as e:  # noqa: BLE001
        error = str(e)[:200]
    items = [_clean(r) for r in rows]
    env = envelope(DOMAIN, newest([r.get("created_at") for r in rows]), now=now, registry=registry)
    out = {"ok": error is None, "key": key, "items": items, "n": len(items),
           "read_only": True, "provider_calls": 0}
    if error:
        out["error"] = error
    out.update(env)
    return out
