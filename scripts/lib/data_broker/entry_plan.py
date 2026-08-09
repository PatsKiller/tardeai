"""Entry Plan — Data Broker read model for watchlist entry zone / stop / target plans.

Batch-reads watchlist_entry_plans (LLM-generated entry zones with stops and targets).
Normalized for decision desks and entry planner consumers.
"""
from __future__ import annotations

from typing import Any


def get_entry_plans(db_query, symbols: list[str]) -> dict[str, dict[str, Any]]:
    """Return {SYMBOL: {entry_zone_low, entry_zone_high, stop_price, target_price, ...}}
    for a batch, taking only the latest plan per symbol.

    Args:
        db_query: a callable(sql, params, fetch="all"|"one") injected by the caller.
        symbols: list of upper-case symbols.
    """
    symbols = [str(s).upper().strip() for s in symbols if s and str(s).strip()]
    if not symbols:
        return {}
    rows = db_query(
        """SELECT DISTINCT ON (upper(symbol))
                  upper(symbol) AS symbol, entry_zone_low, entry_zone_high,
                  stop_price, target_price, risk_reward, urgency,
                  proposal_tag
           FROM watchlist_entry_plans
           WHERE upper(symbol) = ANY(%s) AND entry_zone_low IS NOT NULL
           ORDER BY upper(symbol), created_at DESC""",
        (symbols,),
    ) or []
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        sym = str(row.get("symbol") or "").upper()
        if sym:
            out[sym] = {
                "entry_zone_low": row.get("entry_zone_low"),
                "entry_zone_high": row.get("entry_zone_high"),
                "stop_price": row.get("stop_price"),
                "target_price": row.get("target_price"),
                "risk_reward": row.get("risk_reward"),
                "urgency": row.get("urgency"),
                "proposal_tag": row.get("proposal_tag"),
            }
    return out
