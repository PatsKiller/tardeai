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
    """Fallback: call get_best_quote if market_quotes has no fresh row.
    Guarded by a 5s timeout — the broker waterfall reaches Schwab/Yahoo
    which can stall for 10+ seconds on delisted/CUSIP symbols."""
    import concurrent.futures
    try:
        scripts = str(PROJECT_ROOT / "scripts")
        if scripts not in sys.path:
            sys.path.insert(0, scripts)

        def _fetch():
            from market_quote_provider import get_best_quote
            return get_best_quote(symbol, max_age_seconds=max_age_s) or {}

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            fut = ex.submit(_fetch)
            q = fut.result(timeout=5)
        price = q.get("price") or q.get("last_price")
        if price is not None:
            return {
                "price": float(price),
                "chg_pct": q.get("change_percent") or q.get("chg_pct"),
                "as_of": q.get("quote_timestamp") or q.get("as_of") or q.get("fetched_at"),
                "provider": q.get("provider"),
            }
    except Exception:
        pass
    return None


def get_price_batch(db_query, symbols: list[str], max_age_hours: int = 12,
                    *, skip_live: bool = False) -> dict[str, dict[str, Any]]:
    """Return {SYMBOL: {price, chg_pct, source}} for a batch.

    Primary: market_quotes table (fresh row within max_age_hours).
    Fallback: get_best_quote waterfall (lazily, for symbols without fresh market_quotes).

    Args:
        db_query: a callable(sql, params, fetch="all"|"one") injected by the caller.
        symbols: list of upper-case symbols.
        max_age_hours: max age of market_quotes rows to consider fresh.
        skip_live: when True, skip the get_best_quote live-API fallback entirely.
            Use for bulk-symbol pages (decision desk, watchlists) where blocking
            on 250+ Schwab/Yahoo calls would wedge the request thread.
    """
    symbols = [str(s).upper().strip() for s in symbols if s and str(s).strip()]
    if not symbols:
        return {}

    # First pass: read from market_quotes (Data Broker canonical live quote store)
    rows = db_query(
        """SELECT DISTINCT ON (upper(symbol))
                  upper(symbol) AS symbol, price, day_change_pct, fetched_at, source
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
            as_of = row.get("fetched_at")
            if hasattr(as_of, "isoformat"):
                as_of = as_of.isoformat()
            src = str(row.get("source") or "market_quotes")
            out[sym] = {
                "price": float(row["price"]),
                "chg_pct": float(row["day_change_pct"]) if row.get("day_change_pct") is not None else None,
                "as_of": as_of,
                "source": f"data_broker.market_quotes:{src}",
            }
            found.add(sym)

    # Second pass: broker waterfall only for missing symbols (still Data Broker path)
    if not skip_live:
        missing = [s for s in symbols if s not in found]
        if missing:
            for sym in missing:
                q = _best_quote(sym, max_age_s=max(900, max_age_hours * 3600))
                if q:
                    out[sym] = {
                        "price": q["price"],
                        "chg_pct": q.get("chg_pct"),
                        "as_of": q.get("as_of") or q.get("quote_timestamp"),
                        "source": "data_broker.market_quote:get_best_quote",
                    }
    return out
