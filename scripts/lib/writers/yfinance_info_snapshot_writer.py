"""The one write path for ``yfinance_info_snapshot`` (registry domain ``yfinance_info_snapshot``).

Operator decision 2026-10-10 ~17:45 ET (CONSOLIDATION_PLAN.md §D.13): a new store holding one raw
yfinance ``.info`` payload per symbol, so the reference owner fetches once and the ten lanes that
call ``.info`` today (API_OVERLAP_CONSOLIDATION.md §2.3) can read instead. Table:
``migrations/2026_10_10_yfinance_info_snapshot.sql``. Read path: ``lib.data_broker.yfinance_info``.

This module writes; it never fetches. The producer (the ``yfinance-reference-ingest`` owner lane,
§D.12) is not built or scheduled; whoever it becomes calls :func:`write_info_snapshots` and nothing
else may carry an INSERT/UPDATE for this table (tests/test_broker_domains_q1_20261010.py).

Rails, one rule each, rejected rows returned on the receipt and logged, never dropped:

* ``symbol`` non-empty, stored upper-case.
* ``fetched_at`` required and timezone-aware: a naive time is ambiguous between host-local and
  UTC, which is exactly the error that ages a whole cache by the UTC offset.
* ``status`` in ``ok | no_profile | error``; ``ok`` needs a non-empty dict payload.
* ``payload`` must be JSON-serialisable (stored as JSONB, unmodified).

Conflict rule: one row per symbol; a write replaces it only when its ``fetched_at`` is not older
than the stored one (an out-of-order retry never regresses a newer snapshot).

Does not commit — the producer owns the transaction. AUTHORITY: READ_ONLY_ADVISORY. Market
reference data only; never touches a broker or an order.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from .receipt import WriteReceipt, cursor_of, rowcount_of

TABLE = "yfinance_info_snapshot"
WRITTEN_BY = "scripts/lib/writers/yfinance_info_snapshot_writer.py"
SOURCE = "yfinance"
STATUSES = frozenset({"ok", "no_profile", "error"})
CONFLICT_RULE = "upsert on symbol; replace only when fetched_at >= stored fetched_at"

# The table name is spelled out so check_data_source_authority.count_writers sees exactly one
# file carrying this statement -- this one.
UPSERT_SQL = (
    "INSERT INTO yfinance_info_snapshot "
    "(symbol, fetched_at, status, quote_type, payload, payload_keys, error, source, written_by, run_id) "
    "VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s) "
    "ON CONFLICT (symbol) DO UPDATE SET "
    "fetched_at = EXCLUDED.fetched_at, status = EXCLUDED.status, quote_type = EXCLUDED.quote_type, "
    "payload = EXCLUDED.payload, payload_keys = EXCLUDED.payload_keys, error = EXCLUDED.error, "
    "source = EXCLUDED.source, written_by = EXCLUDED.written_by, run_id = EXCLUDED.run_id, "
    "written_at = now() "
    "WHERE yfinance_info_snapshot.fetched_at <= EXCLUDED.fetched_at"
)


class RowRejected(ValueError):
    pass


def _fetched_at(v: Any) -> datetime:
    if isinstance(v, str) and v.strip():
        try:
            v = datetime.fromisoformat(v.strip().replace("Z", "+00:00"))
        except ValueError:
            raise RowRejected(f"fetched_at: unparseable {v!r}")
    if not isinstance(v, datetime):
        raise RowRejected(f"fetched_at: required datetime, got {type(v).__name__}")
    if v.tzinfo is None:
        raise RowRejected("fetched_at: naive datetime (host-local vs UTC is ambiguous); pass an aware time")
    return v


def coerce_info_row(row: dict[str, Any]) -> dict[str, Any]:
    """Type-coerce one row and apply the rails. Raises RowRejected with the reason."""
    if not isinstance(row, dict):
        raise RowRejected(f"row is {type(row).__name__}, not dict")
    sym = str(row.get("symbol") or "").strip().upper()
    if not sym:
        raise RowRejected("symbol: empty")
    status = str(row.get("status") or "").strip()
    if status not in STATUSES:
        raise RowRejected(f"status: {status!r} not in {sorted(STATUSES)}")
    payload = row.get("payload")
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise RowRejected(f"payload: {type(payload).__name__}, not dict")
    if status == "ok" and not payload:
        raise RowRejected("payload: empty for status ok (use status no_profile)")
    try:
        payload_json = json.dumps(payload, default=str, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise RowRejected(f"payload: not JSON-serialisable ({exc})")
    quote_type = row.get("quote_type", payload.get("quoteType"))
    return {
        "symbol": sym,
        "fetched_at": _fetched_at(row.get("fetched_at")),
        "status": status,
        "quote_type": str(quote_type) if quote_type else None,
        "payload": payload_json,
        "payload_keys": len(payload),
        "error": (str(row.get("error"))[:500] if row.get("error") else None),
    }


def write_info_snapshots(conn_or_cursor: Any, rows: list[dict[str, Any]], *, run_id: str | None = None) -> WriteReceipt:
    """Upsert one snapshot per symbol. Does not commit. Returns the receipt (rejections on it)."""
    receipt = WriteReceipt(
        table=TABLE,
        source=SOURCE,
        written_by=WRITTEN_BY,
        run_id=run_id,
        conflict_rule=CONFLICT_RULE,
        rows_in=len(rows or []),
    )
    accepted: list[dict[str, Any]] = []
    for row in rows or []:
        try:
            accepted.append(coerce_info_row(row))
        except RowRejected as exc:
            receipt.reject(row, str(exc))
    if not accepted:
        return receipt
    cur = cursor_of(conn_or_cursor)
    for r in accepted:
        cur.execute(
            UPSERT_SQL,
            (
                r["symbol"],
                r["fetched_at"],
                r["status"],
                r["quote_type"],
                r["payload"],
                r["payload_keys"],
                r["error"],
                SOURCE,
                WRITTEN_BY,
                run_id,
            ),
        )
        receipt.statements += 1
        receipt.rows_accepted += 1
        receipt.rows_written += rowcount_of(cur)
    return receipt
