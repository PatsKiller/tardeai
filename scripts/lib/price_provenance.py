"""Which ``ticker_prices`` rows may serve a price — one definition (LQ-20261107-1695).

The operator price rule (2026-11-07, WORKERS.md "N8N ONBOARDING + PRICE WORK") is
"Finviz cache first (30 min), a fresh Schwab/Alpaca/moomoo quote second, the stored mark only
flagged stale. Never yfinance." LQ-20261107-1679 removed the last yfinance *writers*. The store
still holds their history — measured read-only on 2026-11-09:

    source             rows       newest price_date
    yfinance           687,708    2026-10-30
    market_quotes      527,080    2026-11-09
    price_cache_backfill 10,378   2026-04-24
    alpaca               7,071    2026-11-06
    finviz               6,774    2026-11-09
    portfolio_repricer   2,792    2026-11-09
    holdings               570    2026-11-02
    yfinance_eod             1    2026-11-02

So "no yfinance writes remain" was true and "no yfinance price is served" was not: readers that
did not name a source served a nine-day-old (or year-old) yfinance close as the current close.
This module is the *reader* half of the rule. A query over ``ticker_prices`` that feeds a signal,
a level, a mark, a score or a learning outcome appends :func:`sql_source_allowed`.

The predicate is deliberately NULL-tolerant: ``COALESCE(source, '')`` lets a row with no recorded
source through, because "unknown" is not "known-bad" and the table was written by many producers
before Phase 9. The live table has zero NULL sources today; the clause exists so a future writer
that omits the column is not silently dropped from every series.

This is a pure module: no DB, no network, no state. ``MBI_BEHAVIOR = 0``.
"""
from __future__ import annotations

#: ``ticker_prices.source`` values that may never serve a price. ``yfinance`` is the operator's
#: named ban; ``yfinance_eod`` is the pre-LQ-455 consolidated-close label it wrote; ``yahoo`` and
#: ``yahoo_finance`` are the same feed under the names used by the snapshot/vix paths. Every one
#: of them was measured as a live source value in this store or its sibling stores.
BANNED_PRICE_SOURCES: frozenset[str] = frozenset(
    {"yfinance", "yfinance_eod", "yahoo", "yahoo_finance"}
)

_SQL_PREDICATES = {
    # No alias: the SELECT reads one table, so ``source`` is unambiguous.
    "source": "COALESCE(source, '') NOT IN ('yfinance', 'yfinance_eod', 'yahoo', 'yahoo_finance')",
    # Table aliases already used by queries in this repository. A new alias is added here, never
    # interpolated at the call site.
    "tp": "COALESCE(tp.source, '') NOT IN ('yfinance', 'yfinance_eod', 'yahoo', 'yahoo_finance')",
    "t": "COALESCE(t.source, '') NOT IN ('yfinance', 'yfinance_eod', 'yahoo', 'yahoo_finance')",
    "p": "COALESCE(p.source, '') NOT IN ('yfinance', 'yfinance_eod', 'yahoo', 'yahoo_finance')",
}


def sql_source_allowed(alias: str = "source") -> str:
    """SQL predicate restricting ``ticker_prices`` to allowed price sources.

    ``alias`` must be one of the keys in :data:`_SQL_PREDICATES` — a KeyError names the alias, so
    no call site can build the predicate from caller input.
    """
    return _SQL_PREDICATES[alias]


def is_banned_source(source: object) -> bool:
    """True when ``source`` is a banned feed. ``None`` is *unknown*, not banned."""
    return str(source).strip().lower() in BANNED_PRICE_SOURCES if source is not None else False


def ban_reason(source: object) -> str | None:
    """Why a source may not serve a price, or None when it may (used in ``data_gaps`` text)."""
    return f"banned price source {source!r} (operator price rule 2026-11-07: never yfinance)" \
        if is_banned_source(source) else None


__all__ = ["BANNED_PRICE_SOURCES", "ban_reason", "is_banned_source", "sql_source_allowed"]
