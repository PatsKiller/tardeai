"""Market Quote Batch — Data Broker read model for batch symbol pricing.

Batch-reads market_quotes (primary, Alpaca-repriced) with get_best_quote waterfall fallback.
Normalized for enrichment sweep consumers. Replaces direct market_quotes SQL + yfinance fallback
in watchlist_enrichment_sweep.py._price().
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent


def _best_quote(symbol: str, max_age_s: int = 900) -> dict[str, Any] | None:
    """Fallback: call get_best_quote if market_quotes has no fresh row."""
    try:
        scripts = str(PROJECT_ROOT / "scripts")
        if scripts not in sys.path:
            sys.path.insert(0, scripts)
        from market_quote_provider import get_best_quote
        q = get_best_quote(symbol, max_age_seconds=max_age_s)
        if q and q.get("price"):
            return {"price": float(q["price"]), "chg_pct": q.get("change_percent")}
    except Exception:
        pass
    return None


def get_price_batch(db_query, symbols: list[str], max_age_hours: int = 12) -> dict[str, dict[str, Any]]:
    """Return {SYMBOL: {price, chg_pct, source}} for a batch.

    Primary: market_quotes table (fresh row within max_age_hours).
    Fallback: get_best_quote waterfall (lazily, for symbols without fresh market_quotes).

    Args:
        db_query: a callable(sql, params, fetch="all"|"one") injected by the caller.
        symbols: list of upper-case symbols.
        max_age_hours: max age of market_quotes rows to consider fresh.
    """
    symbols = [str(s).upper().strip() for s in symbols if s and str(s).strip()]
    if not symbols:
        return {}

    # First pass: read from market_quotes
    rows = db_query(
        """SELECT DISTINCT ON (upper(symbol))
                  upper(symbol) AS symbol, price, day_change_pct, fetched_at
           FROM market_quotes
           WHERE upper(symbol) = ANY(%s)
             AND fetched_at > NOW() - make_interval(hours => %s)
           ORDER BY upper(symbol), fetched_at DESC""",
        (symbols, max_age_hours),
    ) or []

    out: dict[str, dict[str, Any]] = {}
    found: set[str] = set()
    for row in rows:
        sym = str(row.get("symbol") or "").upper()
        if sym and row.get("price") is not None:
            out[sym] = {
                "price": float(row["price"]),
                "chg_pct": float(row["day_change_pct"]) if row.get("day_change_pct") is not None else None,
                "source": "market_quotes",
            }
            found.add(sym)

    # Second pass: get_best_quote fallback for missing symbols
    missing = [s for s in symbols if s not in found]
    if missing:
        for sym in missing:
            q = _best_quote(sym)
            if q:
                out[sym] = {
                    "price": q["price"],
                    "chg_pct": q.get("chg_pct"),
                    "source": "get_best_quote",
                }
    return out
