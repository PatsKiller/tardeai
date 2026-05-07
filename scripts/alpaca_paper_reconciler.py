#!/usr/bin/env python3
"""alpaca_paper_reconciler.py — Reconcile local paper_trades with Alpaca paper broker.

Compares local paper_trades (account=ALPACA_PAPER) with Alpaca paper positions
and open orders. Records reconciliation results for audit.

PAPER ONLY. Live trading is permanently blocked.

Usage:
    .venv/bin/python scripts/alpaca_paper_reconciler.py --dry-run
    .venv/bin/python scripts/alpaca_paper_reconciler.py --apply
"""
import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from session13_db import get_conn
from local_llm_config import get_local_llm_model  # noqa: F401
from alpaca_paper_adapter import AlpacaPaperAdapter

log = logging.getLogger("alpaca_reconciler")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")

# Reconciliation states
MATCHED = "MATCHED"
BROKER_ORDER_NO_LOCAL = "BROKER_ORDER_NO_LOCAL_TRADE"
LOCAL_NO_BROKER = "LOCAL_TRADE_NO_BROKER_ORDER"
SIZE_MISMATCH = "POSITION_SIZE_MISMATCH"
STATUS_MISMATCH = "STATUS_MISMATCH"
CLOSED_OK = "CLOSED_OK"
UNKNOWN = "UNKNOWN"


def get_local_open_trades(conn):
    """Get open local paper trades for ALPACA_PAPER account."""
    cur = conn.cursor()
    cur.execute("""
        SELECT id, symbol, strategy_id, proposal_id, shares, entry_price,
               status, broker_order_id, created_at
        FROM paper_trades
        WHERE account = 'ALPACA_PAPER'
          AND status = 'open'
        ORDER BY created_at DESC
    """)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def get_local_closed_trades(conn, days=7):
    """Get recently closed local paper trades for ALPACA_PAPER account."""
    cur = conn.cursor()
    cur.execute("""
        SELECT id, symbol, strategy_id, proposal_id, shares, entry_price,
               exit_price, status, broker_order_id, closed_at
        FROM paper_trades
        WHERE account = 'ALPACA_PAPER'
          AND status = 'closed'
          AND closed_at >= NOW() - INTERVAL '7 days'
        ORDER BY closed_at DESC
    """)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def reconcile(conn, adapter):
    """Run reconciliation between local trades and Alpaca broker state."""
    # Fetch broker state
    broker_positions = adapter.get_positions()
    broker_orders = adapter.get_open_orders()

    # Fetch local state
    local_open = get_local_open_trades(conn)
    local_closed = get_local_closed_trades(conn)

    # Build lookup maps
    broker_pos_by_symbol = {}
    for pos in broker_positions:
        sym = pos.get("symbol", "")
        broker_pos_by_symbol[sym] = pos

    broker_order_by_id = {}
    broker_order_by_symbol = {}
    for order in broker_orders:
        oid = order.get("id", "")
        sym = order.get("symbol", "")
        broker_order_by_id[oid] = order
        broker_order_by_symbol.setdefault(sym, []).append(order)

    local_by_symbol = {}
    local_by_broker_id = {}
    for trade in local_open:
        sym = trade["symbol"]
        local_by_symbol.setdefault(sym, []).append(trade)
        if trade.get("broker_order_id"):
            local_by_broker_id[trade["broker_order_id"]] = trade

    items = []
    matched_broker_symbols = set()
    matched_local_ids = set()

    # 1. Match broker positions against local open trades
    for sym, pos in broker_pos_by_symbol.items():
        broker_qty = int(float(pos.get("qty", 0)))
        local_trades = local_by_symbol.get(sym, [])

        if not local_trades:
            items.append({
                "broker_order_id": pos.get("asset_id"),
                "paper_trade_id": None,
                "proposal_id": None,
                "symbol": sym,
                "reconciliation_state": BROKER_ORDER_NO_LOCAL,
                "issue_code": "position_no_local_trade",
                "payload": {
                    "broker_qty": broker_qty,
                    "broker_avg_entry": pos.get("avg_entry_price"),
                    "broker_unrealized_pl": pos.get("unrealized_pl"),
                },
            })
        else:
            for lt in local_trades:
                local_shares = int(lt.get("shares") or 0)
                state = MATCHED
                issue = None

                if local_shares != broker_qty:
                    state = SIZE_MISMATCH
                    issue = f"local={local_shares} broker={broker_qty}"

                items.append({
                    "broker_order_id": lt.get("broker_order_id"),
                    "paper_trade_id": lt["id"],
                    "proposal_id": lt.get("proposal_id"),
                    "symbol": sym,
                    "reconciliation_state": state,
                    "issue_code": issue,
                    "payload": {
                        "local_shares": local_shares,
                        "broker_qty": broker_qty,
                        "broker_avg_entry": pos.get("avg_entry_price"),
                        "local_entry": str(lt.get("entry_price")),
                    },
                })
                matched_local_ids.add(lt["id"])

        matched_broker_symbols.add(sym)

    # 2. Match broker open orders against local trades
    for oid, order in broker_order_by_id.items():
        sym = order.get("symbol", "")
        if sym in matched_broker_symbols:
            continue  # already handled via positions

        local_trade = local_by_broker_id.get(oid)
        if not local_trade:
            items.append({
                "broker_order_id": oid,
                "paper_trade_id": None,
                "proposal_id": None,
                "symbol": sym,
                "reconciliation_state": BROKER_ORDER_NO_LOCAL,
                "issue_code": "open_order_no_local_trade",
                "payload": {
                    "order_status": order.get("status"),
                    "order_side": order.get("side"),
                    "order_qty": order.get("qty"),
                },
            })
        else:
            matched_local_ids.add(local_trade["id"])
            broker_status = order.get("status", "").lower()
            local_status = local_trade.get("status", "").lower()

            if broker_status != local_status and broker_status not in ("new", "accepted", "partially_filled"):
                items.append({
                    "broker_order_id": oid,
                    "paper_trade_id": local_trade["id"],
                    "proposal_id": local_trade.get("proposal_id"),
                    "symbol": sym,
                    "reconciliation_state": STATUS_MISMATCH,
                    "issue_code": f"broker={broker_status} local={local_status}",
                    "payload": {"broker_status": broker_status, "local_status": local_status},
                })

    # 3. Local open trades with no broker match
    for trade in local_open:
        if trade["id"] not in matched_local_ids:
            items.append({
                "broker_order_id": trade.get("broker_order_id"),
                "paper_trade_id": trade["id"],
                "proposal_id": trade.get("proposal_id"),
                "symbol": trade["symbol"],
                "reconciliation_state": LOCAL_NO_BROKER,
                "issue_code": "local_open_no_broker_order",
                "payload": {
                    "local_shares": trade.get("shares"),
                    "local_entry": str(trade.get("entry_price")),
                },
            })

    # 4. Recently closed trades — mark as CLOSED_OK
    for trade in local_closed:
        sym = trade["symbol"]
        if sym not in broker_pos_by_symbol:
            items.append({
                "broker_order_id": trade.get("broker_order_id"),
                "paper_trade_id": trade["id"],
                "proposal_id": trade.get("proposal_id"),
                "symbol": sym,
                "reconciliation_state": CLOSED_OK,
                "issue_code": None,
                "payload": {
                    "exit_price": str(trade.get("exit_price")),
                    "closed_at": str(trade.get("closed_at")),
                },
            })

    # Compute summary
    summary = {
        "orders_seen": len(broker_orders),
        "positions_seen": len(broker_positions),
        "trades_matched": sum(1 for i in items if i["reconciliation_state"] == MATCHED),
        "unmatched_broker_orders": sum(1 for i in items if i["reconciliation_state"] == BROKER_ORDER_NO_LOCAL),
        "unmatched_local_trades": sum(1 for i in items if i["reconciliation_state"] == LOCAL_NO_BROKER),
    }

    issues = [i for i in items if i["reconciliation_state"] not in (MATCHED, CLOSED_OK)]

    return summary, items, issues


def insert_reconciliation(conn, summary, items, issues):
    """Insert reconciliation run and items into DB."""
    cur = conn.cursor()

    # Insert run
    cur.execute("""
        INSERT INTO broker_reconciliation_runs
            (broker, run_status, orders_seen, positions_seen,
             trades_matched, unmatched_broker_orders, unmatched_local_trades,
             issues, finished_at)
        VALUES ('alpaca_paper', %s, %s, %s, %s, %s, %s, %s, NOW())
        RETURNING id
    """, [
        "completed",
        summary["orders_seen"], summary["positions_seen"],
        summary["trades_matched"],
        summary["unmatched_broker_orders"], summary["unmatched_local_trades"],
        json.dumps([{"state": i["reconciliation_state"], "symbol": i["symbol"],
                      "issue": i.get("issue_code")} for i in issues], default=str) if issues else None,
    ])
    run_id = cur.fetchone()[0]

    # Insert items
    for item in items:
        cur.execute("""
            INSERT INTO broker_reconciliation_items
                (run_id, broker, broker_order_id, paper_trade_id, proposal_id,
                 symbol, reconciliation_state, issue_code, payload)
            VALUES (%s, 'alpaca_paper', %s, %s, %s, %s, %s, %s, %s)
        """, [
            run_id, item.get("broker_order_id"), item.get("paper_trade_id"),
            item.get("proposal_id"), item["symbol"],
            item["reconciliation_state"], item.get("issue_code"),
            json.dumps(item.get("payload"), default=str) if item.get("payload") else None,
        ])

    conn.commit()
    return run_id


def main():
    parser = argparse.ArgumentParser(description="Alpaca paper broker reconciliation")
    parser.add_argument("--dry-run", action="store_true", help="Compute but do not write to DB")
    parser.add_argument("--apply", action="store_true", help="Write results to DB")
    args = parser.parse_args()

    if not args.dry_run and not args.apply:
        parser.error("Specify --dry-run or --apply")

    adapter = AlpacaPaperAdapter(dry_run=args.dry_run)
    conn = get_conn()

    try:
        if not adapter.enabled:
            output = {
                "status": "disabled",
                "message": "Alpaca paper adapter is disabled (ENABLE_ALPACA_PAPER != true)",
                "summary": {},
                "items": [],
            }
            print(json.dumps(output, indent=2, default=str))
            return

        summary, items, issues = reconcile(conn, adapter)

        run_id = None
        if args.apply:
            run_id = insert_reconciliation(conn, summary, items, issues)
            log.info(f"Reconciliation run {run_id} saved: {summary['trades_matched']} matched, "
                     f"{len(issues)} issues")

        output = {
            "status": "dry_run" if args.dry_run else "applied",
            "run_id": run_id,
            "summary": summary,
            "issues_count": len(issues),
            "state_counts": {},
            "items": items,
        }
        for item in items:
            s = item["reconciliation_state"]
            output["state_counts"][s] = output["state_counts"].get(s, 0) + 1

        print(json.dumps(output, indent=2, default=str))

    finally:
        conn.close()


if __name__ == "__main__":
    main()
