#!/usr/bin/env python3
"""schwab_activity_capture.py — Stage 2a poll-based ACCT_ACTIVITY capture (Part A3). STRICTLY READ-ONLY.

Streaming ACCT_ACTIVITY is deferred (operator decision); the canary fill tests need the real payloads,
so this polls the fenced transport READS on a short cadence and captures, deduplicated:
  • order_status — every (orderId, status, filledQuantity) transition seen via get_orders_raw
  • transaction  — every raw transaction (fills incl. fees/legs) via get_transactions_raw
into schwab_activity_log (JSONB payloads). Surfaced read-only in the Broker Orders safety log.

NEVER submits/replaces/cancels: transport reads only; the write fence (NotProvenWrite) is upstream.

  python3 scripts/schwab_activity_capture.py --once
  python3 scripts/schwab_activity_capture.py --watch [--interval 30]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


def _conn():
    from db_adapter import _get_conn
    return _get_conn()


def _schwab_accounts() -> list[str]:
    cur = _conn().cursor()
    cur.execute("SELECT account_key FROM broker_accounts WHERE broker ILIKE '%schwab%' ORDER BY account_key")
    return [r[0] for r in cur.fetchall()]


def _store(cur, account_key, kind, key, payload, broker_order_id=None, symbol=None, status=None, event_time=None):
    cur.execute("""INSERT INTO schwab_activity_log
                     (account_key, activity_key, kind, broker_order_id, symbol, status, payload, event_time)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (activity_key) DO NOTHING""",
                (account_key, key, kind, broker_order_id, symbol, status, json.dumps(payload), event_time))
    return cur.rowcount


def run_once(accounts=None) -> dict:
    import schwab_transport as st
    accounts = accounts or _schwab_accounts()
    conn = _conn(); cur = conn.cursor()
    new_status = new_txn = 0
    errors = []
    for ak in accounts:
        orders = st.get_orders_raw(ak)
        if isinstance(orders, dict):
            errors.append(f"{ak}/orders: {orders.get('status')}")
        else:
            for o in orders:
                oid = str(o.get("orderId") or "")
                stx = o.get("status") or ""
                legs = o.get("orderLegCollection") or [{}]
                sym = ((legs[0].get("instrument") or {}).get("symbol") or "").upper()
                # one row per observed (order, status, filledQty) transition — the poll-based lifecycle
                key = f"{ak}|order|{oid}|{stx}|{o.get('filledQuantity', 0)}"
                new_status += _store(cur, ak, "order_status", key, o, oid, sym, stx,
                                     o.get("closeTime") or o.get("enteredTime"))
        txns = st.get_transactions_raw(ak)
        if isinstance(txns, dict):
            errors.append(f"{ak}/transactions: {txns.get('status')}")
        else:
            for t in txns:
                tid = str(t.get("activityId") or t.get("transactionId") or "")
                item = (t.get("transferItems") or [{}])[0]
                sym = ((item.get("instrument") or {}).get("symbol") or "").upper()
                key = f"{ak}|txn|{tid}"
                new_txn += _store(cur, ak, "transaction", key, t, None, sym, t.get("type"),
                                  t.get("tradeDate") or t.get("time"))
    conn.commit()
    report = {"accounts": accounts, "new_order_status_rows": new_status, "new_transaction_rows": new_txn,
              "errors": errors or None}
    print(json.dumps(report, default=str))
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--watch", action="store_true")
    ap.add_argument("--interval", type=int, default=30)
    ap.add_argument("--accounts")
    a = ap.parse_args()
    accounts = [s.strip() for s in a.accounts.split(",")] if a.accounts else None
    if a.watch:
        print(f"activity capture watching every {a.interval}s — Ctrl-C to stop (READ-ONLY)")
        while True:
            run_once(accounts)
            time.sleep(a.interval)
    else:
        run_once(accounts)


if __name__ == "__main__":
    main()
