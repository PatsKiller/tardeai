"""Analyst Detail — Data Broker read model for Yahoo target price consensus.

Batch-reads yahoo_analyst_targets_history (canonical store for target mean/low/high,
recommendation_key, analyst count). Normalized for entry planner consumers.
"""
from __future__ import annotations

from typing import Any


def get_analyst_targets(db_query, symbols: list[str]) -> dict[str, dict[str, Any]]:
    """Return {SYMBOL: {target_mean, target_low, target_high, recommendation_key, analyst_count}}
    for a batch, taking only the latest row per symbol.

    Args:
        db_query: a callable(sql, params, fetch="all"|"one") injected by the caller.
        symbols: list of upper-case symbols.
    """
    symbols = [str(s).upper().strip() for s in symbols if s and str(s).strip()]
    if not symbols:
        return {}
    rows = db_query(
        """SELECT DISTINCT ON (upper(symbol))
                  upper(symbol) AS symbol, target_mean_price, target_high_price, target_low_price,
                  recommendation_key, number_of_analyst_opinions, fetched_at
           FROM yahoo_analyst_targets_history
           WHERE upper(symbol) = ANY(%s)
           ORDER BY upper(symbol), fetched_at DESC NULLS LAST""",
        (symbols,),
    ) or []
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        sym = str(row.get("symbol") or "").upper()
        if sym:
            out[sym] = {
                "target_mean": row.get("target_mean_price"),
                "target_high": row.get("target_high_price"),
                "target_low": row.get("target_low_price"),
                "recommendation_key": row.get("recommendation_key"),
                "analyst_count": row.get("number_of_analyst_opinions"),
                "fetched_at": row.get("fetched_at"),
            }
    return out
