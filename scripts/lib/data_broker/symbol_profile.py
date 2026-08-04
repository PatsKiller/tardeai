"""Symbol Profile — Data Broker read model for per-symbol fundamental metadata.

Batch-reads symbol_profiles (canonical store for earnings_date, sector, industry, instrument_type).
Normalized for decision desks and entry planner consumers.
"""
from __future__ import annotations

from typing import Any


def get_symbol_profiles(db_query, symbols: list[str]) -> dict[str, dict[str, Any]]:
    """Return {SYMBOL: {sector, industry, instrument_type, next_earnings_date, ...}} for a batch.

    Args:
        db_query: a callable(sql, params, fetch="all"|"one") injected by the caller.
        symbols: list of upper-case symbols.
    """
    symbols = [str(s).upper().strip() for s in symbols if s and str(s).strip()]
    if not symbols:
        return {}
    rows = db_query(
        """SELECT upper(symbol) AS symbol, sector, industry, instrument_type,
                  next_earnings_date, market_cap, avg_volume, beta, dividend_yield
           FROM symbol_profiles
           WHERE upper(symbol) = ANY(%s)""",
        (symbols,),
    ) or []
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        sym = str(row.get("symbol") or "").upper()
        if sym:
            out[sym] = {
                "sector": row.get("sector"),
                "industry": row.get("industry"),
                "instrument_type": row.get("instrument_type"),
                "next_earnings_date": row.get("next_earnings_date"),
                "market_cap": row.get("market_cap"),
                "avg_volume": row.get("avg_volume"),
                "beta": row.get("beta"),
                "dividend_yield": row.get("dividend_yield"),
            }
    return out
