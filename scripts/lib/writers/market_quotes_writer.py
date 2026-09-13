"""The one write path for ``market_quotes`` (registry domain ``quote_price``).

Before Phase 9 three files carried their own INSERT for this table -- the
ingest (alpaca / finviz / yfinance tiers, three column shapes), the watchlist
enrichment sweep (yfinance backfill) and api_v2's protective-stop quote
refresh (``source = 'refresh:<provider>'``). Same table, three column lists,
three coercion rules, no shared rail. Now every producer calls
``write_market_quotes``; the ingest module re-exports it as the registry's
``writer_target``.

Semantics preserved from the legacy writers, on purpose:

* ``market_quotes`` is an append-only quote ledger. No writer ever declared a
  conflict rule, so none is added here; readers take ``ORDER BY fetched_at
  DESC LIMIT 1``.
* A producer supplies only the columns it has (alpaca has volume, yfinance has
  the fundamentals block, the sweep has price + change). The column list is
  owned here as a whitelist in a fixed order; a row's keys select which of them
  are written, so an absent column keeps its DB default exactly as before,
  and an unknown key is a rejected row, not a silently dropped value.
* ``fetched_at`` is the DB default unless the producer passes one (api_v2 does:
  the quote's own event time, not the write time).

Rails (these existed piecemeal -- every legacy writer skipped a falsy price --
and are now one rule): price must be a finite number strictly greater than
zero; a zero price with volume, a negative price, NaN or a non-numeric string
is rejected and returned on the receipt. Symbol and source must be non-empty.

Identity: the table has no identity column (rule (e) in the Phase 9 brief), so
none is written. The receipt carries ``subject_guid`` per symbol through the
registry-first resolver so the row's identity is on record for the operator's
future migration; see receipt.resolve_subject_identity.

AUTHORITY: READ_ONLY_ADVISORY. Never touches a broker or an order.
"""
from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any

from .receipt import WriteReceipt, attach_identity, cursor_of, rowcount_of

TABLE = "market_quotes"
WRITTEN_BY = "scripts/lib/writers/market_quotes_writer.py"

# Fixed order; a row selects a subset by the keys it carries. symbol/source/price
# are mandatory. Anything not listed here is not a market_quotes column this
# module knows about, and a row that carries it is rejected rather than having
# the key dropped on the floor (the Finviz-shift failure mode is a value
# landing in the wrong column; an unknown key is the same smell).
COLUMNS: tuple[str, ...] = (
    "symbol", "source", "price", "prev_close", "day_change_pct",
    "volume", "avg_volume", "market_cap", "pe_ratio", "forward_pe",
    "dividend_yield", "fifty_two_week_high", "fifty_two_week_low", "fetched_at",
)
REQUIRED: tuple[str, ...] = ("symbol", "price")
_FLOAT_COLS = frozenset({"price", "prev_close", "day_change_pct", "pe_ratio", "forward_pe",
                         "dividend_yield", "fifty_two_week_high", "fifty_two_week_low"})
_INT_COLS = frozenset({"volume", "avg_volume", "market_cap"})
CONFLICT_RULE = "none (append-only ledger)"


class RowRejected(ValueError):
    pass


def _float(v: Any, col: str) -> float | None:
    if v is None or v == "":
        return None
    try:
        f = float(str(v).replace(",", "")) if isinstance(v, str) else float(v)
    except (TypeError, ValueError):
        raise RowRejected(f"{col}: non-numeric {v!r}")
    if math.isnan(f) or math.isinf(f):
        raise RowRejected(f"{col}: not finite ({v!r})")
    return f


def _int(v: Any, col: str) -> int | None:
    f = _float(v, col)
    if f is None:
        return None
    return int(f)


def _fetched_at(v: Any) -> datetime | str:
    if isinstance(v, datetime):
        return v
    if isinstance(v, date):
        return datetime(v.year, v.month, v.day)
    if isinstance(v, str) and v.strip():
        try:
            return datetime.fromisoformat(v.strip().replace("Z", "+00:00"))
        except ValueError:
            raise RowRejected(f"fetched_at: unparseable {v!r}")
    raise RowRejected(f"fetched_at: unsupported {type(v).__name__}")


def coerce_quote_row(row: dict[str, Any], *, source: str) -> dict[str, Any]:
    """Type-coerce one row and apply the rails. Raises RowRejected with the reason."""
    if not isinstance(row, dict):
        raise RowRejected(f"row is {type(row).__name__}, not dict")
    unknown = sorted(k for k in row if k not in COLUMNS)
    if unknown:
        raise RowRejected(f"unknown column(s) {unknown}")
    if "source" in row and row["source"] not in (None, source):
        raise RowRejected(f"source on row ({row['source']!r}) disagrees with writer source ({source!r})")
    missing = [k for k in REQUIRED if row.get(k) in (None, "")]
    if missing:
        raise RowRejected(f"missing {missing}")
    out: dict[str, Any] = {"symbol": str(row["symbol"]).strip().upper(), "source": str(source)}
    if not out["symbol"]:
        raise RowRejected("symbol: empty")
    if not out["source"]:
        raise RowRejected("source: empty")
    for col in COLUMNS:
        if col in ("symbol", "source") or col not in row:
            continue
        v = row[col]
        if col in _FLOAT_COLS:
            out[col] = _float(v, col)
        elif col in _INT_COLS:
            out[col] = _int(v, col)
        elif col == "fetched_at":
            if v is not None:
                out[col] = _fetched_at(v)
    price = out.get("price")
    if price is None or price <= 0:
        # zero-with-volume, negative, and zero all fail here: a price of 0 is
        # never a quote, whatever the volume column says.
        raise RowRejected(f"price: must be > 0, got {row.get('price')!r}")
    return out


def _sql_for(cols: list[str]) -> str:
    # The table name is spelled out so check_data_source_authority.count_writers sees
    # exactly one file carrying this statement -- this one.
    return (f"INSERT INTO market_quotes ({', '.join(cols)}) "
            f"VALUES ({', '.join(['%s'] * len(cols))})")


def write_market_quotes(conn_or_cursor: Any, rows: list[dict[str, Any]], *, source: str,
                        run_id: str | None = None, resolve_identity: bool = True) -> WriteReceipt:
    """Append quote rows for one ``source``. Does not commit -- the producer owns the transaction.

    ``rows`` are dicts keyed by COLUMNS; ``source`` is the provenance for the
    whole batch (a row may repeat it, never contradict it). Returns the receipt;
    rejected rows are on it and logged, never dropped.
    """
    receipt = WriteReceipt(table=TABLE, source=str(source), written_by=WRITTEN_BY,
                           run_id=run_id, conflict_rule=CONFLICT_RULE, rows_in=len(rows or []))
    cur = cursor_of(conn_or_cursor)
    accepted: list[dict[str, Any]] = []
    for row in rows or []:
        try:
            accepted.append(coerce_quote_row(row, source=source))
        except RowRejected as exc:
            receipt.reject(row, str(exc))
    for r in accepted:
        cols = [c for c in COLUMNS if c in r]
        cur.execute(_sql_for(cols), tuple(r[c] for c in cols))
        receipt.statements += 1
        receipt.rows_accepted += 1
        receipt.rows_written += rowcount_of(cur)
    if resolve_identity:
        attach_identity(receipt, accepted)
    return receipt
