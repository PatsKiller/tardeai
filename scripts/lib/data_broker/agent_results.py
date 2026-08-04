"""Agent Results — Data Broker read model for per-symbol watchlist agent recommendations.

Batch-reads watchlist_agent_results (Maria/Steph/Risk/Tax recommendations and confidences).
Normalized for rotation proposals and synthesis consumers.
"""
from __future__ import annotations

from typing import Any


def get_agent_results(db_query, symbols: list[str], days: int = 14) -> dict[str, list[dict[str, Any]]]:
    """Return {SYMBOL: [{agent, recommendation, confidence, narrative, ...}]} for a batch.

    Args:
        db_query: a callable(sql, params, fetch="all"|"one") injected by the caller.
        symbols: list of upper-case symbols.
        days: lookback window in days (default 14).
    """
    symbols = [str(s).upper().strip() for s in symbols if s and str(s).strip()]
    if not symbols:
        return {}
    rows = db_query(
        """SELECT upper(symbol) AS symbol, agent, recommendation, confidence,
                  narrative, evidence, completed_at
           FROM watchlist_agent_results
           WHERE upper(symbol) = ANY(%s)
             AND completed_at > now() - make_interval(days => %s)
           ORDER BY completed_at DESC""",
        (symbols, days),
    ) or []
    out: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        sym = str(row.get("symbol") or "").upper()
        if sym:
            out.setdefault(sym, []).append({
                "agent": row.get("agent"),
                "recommendation": row.get("recommendation"),
                "confidence": row.get("confidence"),
                "narrative": row.get("narrative"),
                "evidence": row.get("evidence"),
                "completed_at": row.get("completed_at"),
            })
    return out
