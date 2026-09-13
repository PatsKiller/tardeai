"""The one write path for ``ticker_prices`` (registry domain ``technicals``).

Before Phase 9 four files carried their own SQL for this table, with three
different conflict rules and two rounding policies:

* ``portfolio_repricer._sync_ticker_prices``: UPDATE today's row, INSERT if
  none, ``source='portfolio_repricer'``, ``created_at=now()``, no rounding.
* ``price_db_sync``: finviz closes upsert-overwrite (``source='finviz'``);
  holdings closes ``DO NOTHING``; yfinance backfill ``DO NOTHING``; and a
  set-based INSERT..SELECT from ``market_quotes`` bounded against the prior
  close whose conflict rule keeps an authoritative source
  (finviz/holdings/portfolio_repricer) over a quote-derived one.
* ``lib/redeploy_price_history.backfill_symbol_history``: yfinance ``DO NOTHING``.
* ``scrub_ticker_price_outliers.restore``: INSERT..SELECT back from
  ``ticker_prices_quarantine``, ``ON CONFLICT DO NOTHING``.

Every one of those is now an explicit parameter or function here, so the
semantics each producer relied on are preserved by name rather than by a
second copy of the SQL:

``write_ticker_prices(..., on_conflict="nothing" | "overwrite", round_to=4 | None,
stamp_created_at=False | True)`` covers the five row-based writers. The
repricer's UPDATE-then-INSERT is the same effect as ``overwrite`` under the
``(symbol, price_date)`` unique index every other writer already relied on.
``restore_ticker_prices_from_quarantine`` and
``sync_ticker_prices_from_market_quotes`` carry the two set-based statements
verbatim -- they are distinct row kinds (rows come from another table, not
from the producer), not a second path for the same rows.

Rails (the ``px <= 0: continue`` / ``price > 0`` checks each writer had, made
one rule): close_price must be a finite number strictly greater than zero;
negative, zero, NaN (which ``float(row["Close"]) <= 0`` never caught) and
non-numeric are rejected and returned on the receipt. Symbol must be non-empty
and price_date must be a date. The ratio-against-prior-close guard
(``price_db_sync.is_price_outlier``, C3 Stage A) stays in the producer: it
needs a DB read of the prior close per symbol, and the quarantine ledger it
writes belongs to that producer. The set-based sync carries its bound inline
as before.

The corruption *detector* (``scrub_ticker_price_outliers.scan``, two-sided
medians, single pass) is untouched; only its restore INSERT moved here, with
identical SQL. Its DELETE of quarantined rows is a different verb and remains
in the scrub.

Identity: the table has no identity column (rule (e)); none is written. The
receipt carries ``subject_guid`` per symbol via the registry-first resolver.

AUTHORITY: READ_ONLY_ADVISORY. Never touches a broker or an order.
"""
from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any

from .receipt import WriteReceipt, attach_identity, cursor_of, rowcount_of

TABLE = "ticker_prices"
QUARANTINE_TABLE = "ticker_prices_quarantine"
WRITTEN_BY = "scripts/lib/writers/ticker_prices_writer.py"

COLUMNS: tuple[str, ...] = ("symbol", "price_date", "close_price", "source", "created_at")
ROW_KEYS: frozenset[str] = frozenset({"symbol", "price_date", "close_price", "source"})

# The only two conflict behaviours any legacy writer used. There is no third.
CONFLICT_RULES: dict[str, str] = {
    "nothing": "ON CONFLICT (symbol, price_date) DO NOTHING",
    "overwrite": ("ON CONFLICT (symbol, price_date) DO UPDATE SET "
                  "close_price = EXCLUDED.close_price, source = EXCLUDED.source"),
}
# Sources the quotes->closes sync must not overwrite (price_db_sync, verbatim).
AUTHORITATIVE_SOURCES: tuple[str, ...] = ("finviz", "holdings", "portfolio_repricer")


class RowRejected(ValueError):
    pass


def _price(v: Any, *, round_to: int | None) -> float:
    if v is None or v == "":
        raise RowRejected("close_price: missing")
    try:
        f = float(str(v).replace(",", "")) if isinstance(v, str) else float(v)
    except (TypeError, ValueError):
        raise RowRejected(f"close_price: non-numeric {v!r}")
    if math.isnan(f) or math.isinf(f):
        raise RowRejected(f"close_price: not finite ({v!r})")
    if f <= 0:
        raise RowRejected(f"close_price: must be > 0, got {v!r}")
    return round(f, round_to) if round_to is not None else f


def _date(v: Any) -> date | None:
    """A date, or None meaning 'the DB's CURRENT_DATE' (the repricer's contract)."""
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if hasattr(v, "date") and callable(v.date):  # pandas Timestamp
        d = v.date()
        if isinstance(d, date):
            return d
    if isinstance(v, str) and v.strip():
        try:
            return date.fromisoformat(v.strip()[:10])
        except ValueError:
            raise RowRejected(f"price_date: unparseable {v!r}")
    raise RowRejected(f"price_date: unsupported {type(v).__name__}")


def coerce_price_row(row: dict[str, Any], *, source: str, round_to: int | None) -> dict[str, Any]:
    """Type-coerce one row and apply the rails. Raises RowRejected with the reason."""
    if not isinstance(row, dict):
        raise RowRejected(f"row is {type(row).__name__}, not dict")
    unknown = sorted(k for k in row if k not in ROW_KEYS)
    if unknown:
        raise RowRejected(f"unknown column(s) {unknown}")
    if "source" in row and row["source"] not in (None, source):
        raise RowRejected(f"source on row ({row['source']!r}) disagrees with writer source ({source!r})")
    sym = str(row.get("symbol") or "").strip().upper()
    if not sym:
        raise RowRejected("symbol: empty")
    if not str(source or ""):
        raise RowRejected("source: empty")
    return {
        "symbol": sym,
        "price_date": _date(row.get("price_date")),
        "close_price": _price(row.get("close_price"), round_to=round_to),
        "source": str(source),
    }


def _sql_for(*, current_date: bool, stamp_created_at: bool, on_conflict: str) -> str:
    cols = ["symbol", "price_date", "close_price", "source"]
    vals = ["%s", "CURRENT_DATE" if current_date else "%s", "%s", "%s"]
    if stamp_created_at:
        cols.append("created_at")
        vals.append("now()")
    # The table name is spelled out so check_data_source_authority.count_writers sees
    # exactly one file carrying this statement -- this one.
    return (f"INSERT INTO ticker_prices ({', '.join(cols)}) VALUES ({', '.join(vals)}) "
            f"{CONFLICT_RULES[on_conflict]}")


def write_ticker_prices(conn_or_cursor: Any, rows: list[dict[str, Any]], *, source: str,
                        on_conflict: str = "nothing", round_to: int | None = 4,
                        stamp_created_at: bool = False, run_id: str | None = None,
                        resolve_identity: bool = True) -> WriteReceipt:
    """Upsert daily closes for one ``source``. Does not commit -- the producer owns the transaction.

    ``rows``: dicts with symbol, close_price and price_date (a date, ISO string,
    pandas Timestamp, or None for the DB's CURRENT_DATE). ``on_conflict`` is
    ``"nothing"`` (keep the existing close) or ``"overwrite"`` (replace close and
    source). ``round_to`` is the legacy 4-decimal rounding; pass None to write
    the value as given (the repricer's contract). ``stamp_created_at`` adds
    ``created_at = now()`` as the repricer did.
    """
    if on_conflict not in CONFLICT_RULES:
        raise ValueError(f"on_conflict must be one of {sorted(CONFLICT_RULES)}, got {on_conflict!r}")
    receipt = WriteReceipt(table=TABLE, source=str(source), written_by=WRITTEN_BY, run_id=run_id,
                           conflict_rule=CONFLICT_RULES[on_conflict], rows_in=len(rows or []))
    cur = cursor_of(conn_or_cursor)
    accepted: list[dict[str, Any]] = []
    for row in rows or []:
        try:
            accepted.append(coerce_price_row(row, source=source, round_to=round_to))
        except RowRejected as exc:
            receipt.reject(row, str(exc))
    for r in accepted:
        current = r["price_date"] is None
        sql = _sql_for(current_date=current, stamp_created_at=stamp_created_at, on_conflict=on_conflict)
        params = (r["symbol"], r["close_price"], r["source"]) if current else \
                 (r["symbol"], r["price_date"], r["close_price"], r["source"])
        cur.execute(sql, params)
        receipt.statements += 1
        receipt.rows_accepted += 1
        receipt.rows_written += rowcount_of(cur)
    if resolve_identity:
        attach_identity(receipt, accepted)
    return receipt


RESTORE_SQL = """INSERT INTO ticker_prices (symbol, price_date, close_price, source, created_at)
           SELECT symbol, price_date, close_price, source, created_at
             FROM ticker_prices_quarantine WHERE symbol = %s
           ON CONFLICT DO NOTHING"""


def restore_ticker_prices_from_quarantine(conn_or_cursor: Any, symbol: str, *,
                                          run_id: str | None = None) -> WriteReceipt:
    """Put a symbol's quarantined rows back (the scrub's ``--restore``), SQL unchanged.

    Rows come from ``ticker_prices_quarantine`` with their original source and
    created_at, so this is a copy back, not a new observation: no coercion, no
    rail, ``ON CONFLICT DO NOTHING`` so a live row is never displaced. Deleting
    the quarantine copy afterwards is the scrub's job, as before.
    """
    # The symbol is passed through as given, not normalised: the scrub's DELETE of
    # the quarantine copies uses the same argument, and the two must select the
    # same rows.
    sym = str(symbol) if symbol is not None else ""
    receipt = WriteReceipt(table=TABLE, source=f"{QUARANTINE_TABLE}:restore", written_by=WRITTEN_BY,
                           run_id=run_id, conflict_rule="ON CONFLICT DO NOTHING", rows_in=0)
    if not sym.strip():
        receipt.reject({"symbol": symbol}, "symbol: empty")
        return receipt
    cur = cursor_of(conn_or_cursor)
    cur.execute(RESTORE_SQL, (sym,))
    receipt.statements = 1
    receipt.rows_written = receipt.rows_accepted = rowcount_of(cur)
    attach_identity(receipt, [{"symbol": sym}])
    return receipt


def _quotes_sync_sql(symbol_filter: str) -> str:
    keep = ", ".join(f"'{s}'" for s in AUTHORITATIVE_SOURCES)
    return f"""WITH candidates AS (
               SELECT DISTINCT ON (UPPER(symbol), fetched_at::date)
                      UPPER(symbol) AS symbol, fetched_at::date AS price_date, price
               FROM market_quotes
               WHERE price IS NOT NULL AND price > 0
                 {symbol_filter}
               ORDER BY UPPER(symbol), fetched_at::date, fetched_at DESC
           ),
           bounded AS (
               SELECT c.symbol, c.price_date, c.price, prior.close_price AS prior_price
               FROM candidates c
               LEFT JOIN LATERAL (
                   SELECT tp.close_price FROM ticker_prices tp
                   WHERE tp.symbol = c.symbol AND tp.price_date < c.price_date
                   ORDER BY tp.price_date DESC LIMIT 1
               ) prior ON true
           )
           INSERT INTO ticker_prices (symbol, price_date, close_price, source)
           SELECT symbol, price_date, price, 'market_quotes'
           FROM bounded
           WHERE prior_price IS NULL
              OR price BETWEEN prior_price * %(min_ratio)s AND prior_price * %(max_ratio)s
           ON CONFLICT (symbol, price_date) DO UPDATE SET
             close_price = EXCLUDED.close_price,
             source = CASE
               WHEN ticker_prices.source IN ({keep})
               THEN ticker_prices.source
               ELSE EXCLUDED.source
             END"""


def sync_ticker_prices_from_market_quotes(conn_or_cursor: Any, symbols: list[str] | None, *,
                                          min_ratio: float, max_ratio: float,
                                          run_id: str | None = None) -> WriteReceipt:
    """Daily closes from the last quote per symbol per day (price_db_sync), SQL unchanged.

    Bounded inline against the prior close: a candidate outside
    [min_ratio, max_ratio] of the most recent prior ``ticker_prices`` row is
    not written (the producer separately lists and quarantines those). A symbol
    with no prior row always passes. An authoritative source already on the row
    (finviz / holdings / portfolio_repricer) is kept over 'market_quotes'.
    """
    syms = [str(s).upper() for s in (symbols or []) if s]
    symbol_filter = "AND UPPER(symbol) = ANY(%(syms)s)" if syms else ""
    receipt = WriteReceipt(table=TABLE, source="market_quotes", written_by=WRITTEN_BY, run_id=run_id,
                           conflict_rule="ON CONFLICT (symbol, price_date) DO UPDATE SET close_price, "
                                         "source kept when authoritative", rows_in=len(syms))
    cur = cursor_of(conn_or_cursor)
    cur.execute(_quotes_sync_sql(symbol_filter),
                {"syms": syms, "min_ratio": min_ratio, "max_ratio": max_ratio})
    receipt.statements = 1
    receipt.rows_written = receipt.rows_accepted = rowcount_of(cur)
    if syms:
        attach_identity(receipt, [{"symbol": s} for s in syms])
    return receipt
