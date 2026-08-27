"""Canonical catalyst read helper — single verification model for catalyst_record.

Authority: catalyst_events.confidence >= 0.3 ⇒ verified (matches scoring.validate_catalyst_relevance).
"""
from __future__ import annotations

from typing import Any


def _confidence(row: dict[str, Any]) -> float | None:
    for key in ("confidence", "impact_score"):
        v = row.get(key)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                pass
    return None


def normalize_catalyst_row(row: dict[str, Any] | None) -> dict[str, Any] | None:
    """Normalize a catalyst_events (or compatible) row to the broker schema."""
    if not row:
        return None
    conf = _confidence(row)
    verified = row.get("verified")
    if verified is None and conf is not None:
        verified = conf >= 0.3
    return {
        "symbol": row.get("symbol"),
        "headline": row.get("headline") or row.get("title"),
        "catalyst_type": row.get("catalyst_type"),
        "verified": bool(verified),
        "confidence": conf,
        "severity": row.get("severity"),
        "impact_score": row.get("impact_score"),
        "source_url": row.get("source_url"),
        "at": row.get("published_at") or row.get("created_at") or row.get("ts"),
    }


def get_catalyst_record(db_query, symbol: str, *, days: int = 45) -> dict[str, Any] | None:
    """Fetch the latest catalyst_events row for symbol via injected _db_query callable."""
    sym = (symbol or "").upper()
    if not sym:
        return None
    row = db_query(
        """
        SELECT symbol, catalyst_type, headline, severity, impact_score, confidence,
               source_url, COALESCE(published_at, created_at) AS at
        FROM catalyst_events
        WHERE upper(symbol) = upper(%s) AND catalyst_type <> 'other'
          AND COALESCE(published_at, created_at) > now() - make_interval(days => %s)
        ORDER BY COALESCE(published_at, created_at) DESC
        LIMIT 1
        """,
        (sym, days),
        fetch="one",
    )
    return normalize_catalyst_row(row)


def _db_query(sql, params=None, fetch="all"):
    """Injected-callable shape the module's functions expect."""
    try:
        from db_adapter import _get_conn
        conn = _get_conn()
        if not conn:
            return [] if fetch == "all" else None
        cur = conn.cursor()
        cur.execute(sql, params or [])
        cols = [d[0] for d in cur.description]
        if fetch == "one":
            row = cur.fetchone()
            return dict(zip(cols, row)) if row else None
        rows = cur.fetchall()
        return [dict(zip(cols, r)) for r in rows]
    except Exception:
        return [] if fetch == "all" else None


def _jsonable(value: Any) -> Any:
    """Postgres hands back Decimal and datetime; the snapshot content-hashes
    every domain payload with json.dumps, which raises on both. A collector that
    returns them takes the whole snapshot down, not just its own domain."""
    from datetime import date, datetime as _dt
    from decimal import Decimal
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (_dt, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def get_catalysts(days: int = 7) -> dict[str, Any]:
    """Domain collector for `catalysts`, resolved by the snapshot by name.

    `get_catalyst_record(db_query, symbol)` exists but requires arguments the
    snapshot never passes, so calling it raised TypeError and the domain
    reported unavailable -- while 133,659 catalyst rows sat in the table, 646 of
    them from the last 24 hours. The per-symbol function is untouched; this is
    the domain-level view it never had.

    `as_of` is the newest event's own timestamp, never `now()`: stamping the
    read time would report the domain fresh on a feed that had stopped.
    """
    rows = _db_query(
        """SELECT symbol, catalyst_type, headline, severity, impact_score, confidence,
                  COALESCE(published_at, created_at) AS at
           FROM catalyst_events
           WHERE catalyst_type <> 'other'
             AND COALESCE(published_at, created_at) > now() - make_interval(days => %s)
           ORDER BY COALESCE(published_at, created_at) DESC
           LIMIT 500""",
        (int(days),),
    ) or []

    normalized = [c for c in (normalize_catalyst_row(r) for r in rows) if c]
    if not normalized:
        return {"state": "DATA_UNAVAILABLE", "as_of": "", "catalysts": [],
                "gap_reason": "no_catalyst_events_in_window"}

    newest = max((r.get("at") for r in rows if r.get("at")), default=None)
    return {
        "state": "AVAILABLE",
        "as_of": newest.isoformat() if hasattr(newest, "isoformat") else str(newest or ""),
        "catalyst_count": len(normalized),
        "symbols_covered": sorted({str(r.get("symbol")).upper() for r in rows if r.get("symbol")}),
        "catalysts": _jsonable(normalized[:100]),
    }
