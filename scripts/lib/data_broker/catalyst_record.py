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
