"""Market Quote Batch — Data Broker read model for batch symbol pricing.

Batch-reads market_quotes (primary, Alpaca-repriced) through the ``latest_quote`` projection, with a
bounded live fallback for symbols that have no fresh stored row. Normalized for enrichment sweep
consumers. Replaces direct market_quotes SQL + yfinance fallback in watchlist_enrichment_sweep.py._price().

2026-10-10 (operator decision, CONSOLIDATION_PLAN.md §D.6/§D.7):

- The first pass reads :mod:`lib.data_broker.latest_quote` (one index probe per symbol) instead of
  ``DISTINCT ON (upper(symbol))``, which could not use the (symbol, fetched_at) index and
  sequentially scanned the append-only table on every call (96 ms vs 0.08 ms for five symbols).
- The live fallback was dead by accident: ``_best_quote`` passed ``max_age_seconds=`` to a
  ``get_best_quote(symbol)`` that took one argument, and the TypeError was swallowed, so a miss
  returned nothing. It now calls the quote-only mode of ``get_best_quote`` (stored quote first,
  then providers in chain order, stopping at the first fresh answer — never the four-provider
  fan-out), at most ``LIVE_FALLBACK_MAX_PER_BATCH`` symbols per call, each under a real 5 s bound
  (the executor no longer waits for a stalled provider on exit).
"""
from __future__ import annotations

import concurrent.futures
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent

#: A batch that misses more symbols than this answers the rest from the store or not at all. The
#: fallback was dead (0 provider calls) until 2026-10-10; this keeps a bulk page from turning into
#: hundreds of sequential provider calls now that it works.
LIVE_FALLBACK_MAX_PER_BATCH = 10
LIVE_FALLBACK_TIMEOUT_S = 5.0


def _ensure_scripts_path() -> None:
    scripts = str(PROJECT_ROOT / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)


def _best_quote(symbol: str, max_age_s: int = 900) -> dict[str, Any] | None:
    """Fallback for one symbol without a fresh stored row: quote-only ``get_best_quote``.

    Quote-only mode reads the stored quote first and asks providers in chain order only while the
    answer is stale, stopping at the first fresh one (no fan-out). Bounded by
    ``LIVE_FALLBACK_TIMEOUT_S``: the broker waterfall reaches Schwab/Yahoo, which can stall for
    10+ seconds on delisted/CUSIP symbols; on timeout the worker is abandoned, not awaited.
    The stored read is skipped (``skip_stored=True``): the caller has just read the store and the
    symbol was stale or missing there. The caller's DB handle never crosses into the worker thread.
    """
    _ensure_scripts_path()

    from market_quote_provider import quote_only_enabled

    if not quote_only_enabled():
        return None  # kill switch: the fallback is off, as it was (by accident) before 2026-10-10

    def _fetch():
        from market_quote_provider import get_best_quote
        return get_best_quote(symbol, max_age_seconds=max_age_s, skip_stored=True) or {}

    ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        q = ex.submit(_fetch).result(timeout=LIVE_FALLBACK_TIMEOUT_S)
    except Exception:
        return None
    finally:
        ex.shutdown(wait=False, cancel_futures=True)
    price = q.get("price") if q.get("price") is not None else q.get("last_price")
    if price is None:
        return None
    try:
        price = float(price)
    except (TypeError, ValueError):
        return None
    return {
        "price": price,
        "chg_pct": q.get("change_percent") or q.get("chg_pct") or q.get("day_change_pct"),
        "as_of": q.get("quote_timestamp") or q.get("as_of") or q.get("fetched_at"),
        "provider": q.get("provider"),
        "stale": bool(q.get("stale")),
    }


def get_price_batch(db_query, symbols: list[str], max_age_hours: int = 12,
                    *, skip_live: bool = False) -> dict[str, dict[str, Any]]:
    """Return {SYMBOL: {price, chg_pct, as_of, source}} for a batch.

    Primary: the newest market_quotes row per symbol (latest_quote projection), kept when it is
    within ``max_age_hours``.
    Fallback: quote-only get_best_quote for symbols without a fresh row, at most
    ``LIVE_FALLBACK_MAX_PER_BATCH`` per call.

    Args:
        db_query: a callable(sql, params, fetch="all"|"one") injected by the caller.
        symbols: list of upper-case symbols.
        max_age_hours: max age of market_quotes rows to consider fresh.
        skip_live: when True, skip the get_best_quote live-API fallback entirely.
            Use for bulk-symbol pages (decision desk, watchlists) where blocking
            on 250+ Schwab/Yahoo calls would wedge the request thread.
    """
    from lib.data_broker.latest_quote import get_latest_quotes

    symbols = [str(s).upper().strip() for s in symbols if s and str(s).strip()]
    if not symbols:
        return {}

    window_s = float(max_age_hours) * 3600.0
    latest = get_latest_quotes(db_query, symbols, max_age_seconds=window_s)

    out: dict[str, dict[str, Any]] = {}
    for sym in latest.get("fresh") or []:
        row = latest["symbols"][sym]
        out[sym] = {
            "price": row["price"],
            "chg_pct": row["chg_pct"],
            "as_of": row["as_of"],
            "source": f"data_broker.market_quotes:{row.get('provider') or 'market_quotes'}",
        }

    # Second pass: quote-only broker waterfall, only for missing symbols, bounded per batch.
    if not skip_live:
        missing = [s for s in symbols if s not in out][:LIVE_FALLBACK_MAX_PER_BATCH]
        for sym in missing:
            q = _best_quote(sym, max_age_s=int(max(900, window_s)))
            if q and not q.get("stale"):
                out[sym] = {
                    "price": q["price"],
                    "chg_pct": q.get("chg_pct"),
                    "as_of": q.get("as_of"),
                    "source": f"data_broker.market_quote:get_best_quote:{q.get('provider') or 'unknown'}",
                }
    return out
