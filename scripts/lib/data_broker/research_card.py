"""Research Card — Data Broker read model for watchlist per-symbol CIO research recommendations.

Batch-reads watchlist_research_cards (agent-curated CIO recommendation per symbol).
Normalized for decision desks and entry planner consumers.
"""
from __future__ import annotations

from typing import Any


def get_research_cards(db_query, symbols: list[str]) -> dict[str, dict[str, Any]]:
    """Return {SYMBOL: {latest_recommendation, confidence, latest_summary}} for a batch.

    Args:
        db_query: a callable(sql, params, fetch="all"|"one") injected by the caller.
        symbols: list of upper-case symbols.
    """
    symbols = [str(s).upper().strip() for s in symbols if s and str(s).strip()]
    if not symbols:
        return {}
    rows = db_query(
        """SELECT DISTINCT ON (upper(symbol))
                  upper(symbol) AS symbol, latest_recommendation, confidence,
                  latest_summary, research_status, needs_iteration, updated_at
           FROM watchlist_research_cards
           WHERE upper(symbol) = ANY(%s)
           ORDER BY upper(symbol), updated_at DESC NULLS LAST""",
        (symbols,),
    ) or []
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        sym = str(row.get("symbol") or "").upper()
        if sym:
            out[sym] = {
                "latest_recommendation": row.get("latest_recommendation"),
                "confidence": row.get("confidence"),
                "latest_summary": row.get("latest_summary"),
                "research_status": row.get("research_status"),
                "needs_iteration": row.get("needs_iteration"),
                "updated_at": row.get("updated_at"),
            }
    return out
