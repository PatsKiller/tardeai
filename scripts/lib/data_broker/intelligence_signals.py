"""Intelligence Signals — Data Broker read model for per-symbol research signals.

Batch-reads intelligence_entities (canonical store for rvol, confluence_score, social_score,
social_sentiment, catalyst presence per symbol). Normalized for Hermes scorer and decision desks.
"""
from __future__ import annotations

from typing import Any


def get_intelligence_signals(db_query, symbols: list[str]) -> dict[str, dict[str, Any]]:
    """Return {SYMBOL: {rvol, confluence_score, social_score, social_sentiment, ...}} for a batch.

    Args:
        db_query: a callable(sql, params, fetch="all"|"one") injected by the caller.
        symbols: list of upper-case symbols.
    """
    symbols = [str(s).upper().strip() for s in symbols if s and str(s).strip()]
    if not symbols:
        return {}
    rows = db_query(
        """SELECT DISTINCT ON (upper(display_name))
                  upper(display_name) AS symbol, rvol, confluence_score,
                  social_score, social_sentiment, catalyst, catalyst_verified, sector
           FROM intelligence_entities
           WHERE upper(display_name) = ANY(%s)
           ORDER BY upper(display_name), updated_at DESC NULLS LAST""",
        (symbols,),
    ) or []
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        sym = str(row.get("symbol") or "").upper()
        if sym:
            out[sym] = {
                "rvol": row.get("rvol"),
                "confluence_score": row.get("confluence_score"),
                "social_score": row.get("social_score"),
                "social_sentiment": row.get("social_sentiment"),
                "catalyst": row.get("catalyst"),
                "catalyst_verified": row.get("catalyst_verified"),
                "entity_sector": row.get("sector"),
            }
    return out
