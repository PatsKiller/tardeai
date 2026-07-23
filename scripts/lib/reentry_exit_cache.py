"""Full-fidelity real-account exit cache for Portfolio Re-Entry.

The legacy Redeploy history response intentionally summarizes each sell. Re-Entry
needs the complete transaction row before downstream reconciliation, so the
scheduled Watch pass persists a read-only JSONB cache with action, quantity,
execution price, proceeds, description, source, trade time, and matching status.
"""
from __future__ import annotations

import datetime as dt
import json
from typing import Any, Callable

from lib.sale_event_detector import _is_real_account, _is_sell_row, _proceeds, event_key_for_row

CACHE_KEY = "portfolio.reentry.exit-universe.v1"


def _float(value: Any) -> float | None:
    try:
        number = float(value)
        return number if number == number else None
    except (TypeError, ValueError):
        return None


def refresh_exit_cache(ex: Callable[..., Any], days: int = 365) -> dict[str, Any]:
    transactions = ex(
        """SELECT id, trade_date, trade_time, action, symbol, quantity, price, amount,
                  fees, description, account, import_source, dedupe_key
           FROM trade_transactions
           WHERE trade_date >= CURRENT_DATE - %s
           ORDER BY trade_date DESC, trade_time DESC NULLS LAST, id DESC
           LIMIT 10000""",
        (int(days),), fetch="all",
    ) or []
    events = ex(
        """SELECT id, event_key, status, completion_status, operator_status,
                  proceeds_settled, sold_at, source
           FROM deploy_events
           WHERE sold_at >= CURRENT_DATE - %s""",
        (int(days),), fetch="all",
    ) or []
    event_map = {str(row.get("event_key") or ""): row for row in events if row.get("event_key")}
    rows: list[dict[str, Any]] = []
    account_counts: dict[str, int] = {}
    source_counts: dict[str, int] = {}
    matched = 0
    for transaction in transactions:
        if not _is_real_account(transaction.get("account")) or not _is_sell_row(transaction):
            continue
        symbol = str(transaction.get("symbol") or "").upper().strip()
        if not symbol:
            continue
        event_key = event_key_for_row(transaction)
        event = event_map.get(event_key)
        quantity = _float(transaction.get("quantity"))
        price = _float(transaction.get("price"))
        proceeds = _proceeds(transaction)
        if price is None and quantity not in (None, 0) and proceeds:
            price = proceeds / abs(quantity)
        if event:
            matched += 1
        account = str(transaction.get("account") or "")
        source = str(transaction.get("import_source") or "unknown")
        account_counts[account] = account_counts.get(account, 0) + 1
        source_counts[source] = source_counts.get(source, 0) + 1
        trade_date = transaction.get("trade_date")
        trade_time = transaction.get("trade_time")
        rows.append({
            "event_key": event_key,
            "transaction_id": transaction.get("id"),
            "trade_date": str(trade_date)[:10] if trade_date else None,
            "trade_time": str(trade_time) if trade_time else None,
            "action": transaction.get("action"),
            "symbol": symbol,
            "quantity": abs(quantity) if quantity is not None else None,
            "signed_quantity": quantity,
            "price": round(price, 6) if price is not None else None,
            "proceeds_usd": round(proceeds, 2),
            "fees": _float(transaction.get("fees")),
            "description": str(transaction.get("description") or "")[:500] or None,
            "account": account,
            "import_source": source,
            "dedupe_key": transaction.get("dedupe_key"),
            "matched_event_id": event.get("id") if event else None,
            "event_status": event.get("status") if event else None,
            "completion_status": event.get("completion_status") if event else None,
            "operator_status": event.get("operator_status") if event else None,
            "proceeds_settled": bool(event.get("proceeds_settled")) if event else None,
            "event_source": event.get("source") if event else None,
            "reconciliation": "matched" if event else "pending",
        })
    payload = {
        "version": "reentry_exit_universe_v1",
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "days": int(days),
        "counts": {
            "transactions_scanned": len(transactions),
            "exits_found": len(rows),
            "matched": matched,
            "pending_reconciliation": len(rows) - matched,
            "accounts": account_counts,
            "sources": source_counts,
        },
        "rows": rows,
    }
    ex(
        """INSERT INTO ui_prefs (key, value, updated_at)
           VALUES (%s,%s::jsonb,NOW())
           ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_at=NOW()""",
        (CACHE_KEY, json.dumps(payload)), fetch=None,
    )
    return payload
