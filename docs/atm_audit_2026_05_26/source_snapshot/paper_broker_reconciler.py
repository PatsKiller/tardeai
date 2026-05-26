#!/usr/bin/env python3
"""paper_broker_reconciler.py — Enhanced paper broker reconciliation engine.

Reconciles local paper_trades DB state against Alpaca paper broker positions/orders.
Writes structured results to paper_broker_reconciliation_runs/items tables.

PAPER ONLY. Does not modify broker orders. --repair-safe only updates local metadata.

Usage:
    .venv/bin/python scripts/paper_broker_reconciler.py --dry-run --json
    .venv/bin/python scripts/paper_broker_reconciler.py --sync --json
    .venv/bin/python scripts/paper_broker_reconciler.py --sync --symbol AAPL
    .venv/bin/python scripts/paper_broker_reconciler.py --sync --repair-safe
"""
import argparse, json, logging, os, sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from session13_db import get_conn
from alpaca_paper_adapter import AlpacaPaperAdapter

log = logging.getLogger("paper_broker_reconciler")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")


def _mask_account_id(acct_id):
    if not acct_id or len(acct_id) < 8:
        return "***"
    return acct_id[:4] + "..." + acct_id[-4:]


def get_db_open_trades(conn, symbol=None):
    cur = conn.cursor()
    sql = """SELECT id, symbol, strategy_id, proposal_id, shares, entry_price,
                    stop_loss, target_1, status, broker_order_id, broker_status,
                    client_order_id, created_at, last_synced_at
             FROM paper_trades WHERE account='ALPACA_PAPER' AND status='open'"""
    params = []
    if symbol:
        sql += " AND symbol=%s"
        params.append(symbol)
    sql += " ORDER BY created_at DESC"
    cur.execute(sql, params)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def reconcile(conn, adapter, symbol_filter=None):
    """Full reconciliation pass."""
    run_id = f"recon_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    alpaca_mode = os.getenv("ALPACA_MODE", "paper")

    # Safety check
    if alpaca_mode != "paper":
        return {"run_id": run_id, "status": "blocked", "error": "ALPACA_MODE is not paper"}, []

    # Fetch broker state
    broker_positions = adapter.get_positions() or []
    broker_orders = adapter.get_open_orders() or []
    account = adapter.get_account() or {}
    acct_masked = _mask_account_id(account.get("id", ""))

    # Fetch local state
    db_trades = get_db_open_trades(conn, symbol_filter)

    # Build lookups
    bp_by_sym = {p.get("symbol"): p for p in broker_positions}
    bo_by_sym = {}
    for o in broker_orders:
        bo_by_sym.setdefault(o.get("symbol", ""), []).append(o)
    db_by_sym = {}
    for t in db_trades:
        db_by_sym.setdefault(t["symbol"], []).append(t)

    items = []
    matched_broker_syms = set()
    matched_db_ids = set()

    # 1. Match broker positions → DB trades
    for sym, pos in bp_by_sym.items():
        if symbol_filter and sym != symbol_filter:
            continue
        broker_qty = int(float(pos.get("qty", 0)))
        broker_avg = float(pos.get("avg_entry_price", 0))
        local_trades = db_by_sym.get(sym, [])

        if not local_trades:
            items.append(_item(run_id, sym, None, pos.get("asset_id"), None,
                               "broker_position_missing_db_trade", "warning",
                               broker_snapshot=_sanitize(pos)))
        else:
            for lt in local_trades:
                local_qty = int(lt.get("shares") or 0)
                diff = {}
                itype = "position_match"
                sev = "info"

                if local_qty != broker_qty:
                    itype = "qty_mismatch"
                    sev = "warning"
                    diff["qty"] = {"db": local_qty, "broker": broker_qty}

                local_entry = float(lt.get("entry_price") or 0)
                if local_entry and broker_avg and abs(local_entry - broker_avg) / max(local_entry, 0.01) > 0.01:
                    if itype == "position_match":
                        itype = "avg_entry_mismatch"
                    sev = "warning"
                    diff["avg_entry"] = {"db": local_entry, "broker": broker_avg}

                items.append(_item(run_id, sym, lt["id"], pos.get("asset_id"), lt.get("broker_order_id"),
                                   itype, sev, db_snapshot=_trade_snap(lt), broker_snapshot=_sanitize(pos),
                                   difference=diff or None))
                matched_db_ids.add(lt["id"])

        matched_broker_syms.add(sym)

        # Check stop/limit orders for this symbol
        sym_orders = bo_by_sym.get(sym, [])
        has_stop = any(o.get("type") in ("stop", "stop_limit") for o in sym_orders)
        has_limit = any(o.get("type") in ("limit",) and o.get("side") == "sell" for o in sym_orders)
        if local_trades and not has_stop:
            items.append(_item(run_id, sym, local_trades[0]["id"], None, None,
                               "stop_order_mismatch", "warning",
                               difference={"stop_order": "missing_at_broker"}))
        if local_trades and not has_limit and any(t.get("target_1") for t in local_trades):
            items.append(_item(run_id, sym, local_trades[0]["id"], None, None,
                               "limit_order_mismatch", "info",
                               difference={"limit_order": "missing_at_broker"}))

    # 2. DB trades missing broker position
    for t in db_trades:
        if t["id"] not in matched_db_ids:
            items.append(_item(run_id, t["symbol"], t["id"], None, t.get("broker_order_id"),
                               "db_trade_missing_broker_position", "warning",
                               db_snapshot=_trade_snap(t)))

    # 3. Broker orders not tied to any DB trade
    for sym, orders in bo_by_sym.items():
        if symbol_filter and sym != symbol_filter:
            continue
        for o in orders:
            oid = o.get("id", "")
            # Check if any DB trade references this order
            linked = any(t.get("broker_order_id") == oid or t.get("client_order_id") == o.get("client_order_id")
                         for t in db_trades)
            if not linked and sym not in matched_broker_syms:
                items.append(_item(run_id, sym, None, None, oid,
                                   "order_missing_db_reference", "info",
                                   broker_snapshot=_sanitize(o)))

    # Build summary
    summary = {
        "run_id": run_id,
        "status": "completed",
        "alpaca_mode": alpaca_mode,
        "broker_account_id_masked": acct_masked,
        "db_open_trades": len(db_trades),
        "broker_open_positions": len(broker_positions),
        "broker_open_orders": len(broker_orders),
        "matched_positions": sum(1 for i in items if i["item_type"] == "position_match"),
        "unmatched_db_trades": sum(1 for i in items if i["item_type"] == "db_trade_missing_broker_position"),
        "unmatched_broker_positions": sum(1 for i in items if i["item_type"] == "broker_position_missing_db_trade"),
        "unmatched_orders": sum(1 for i in items if i["item_type"] == "order_missing_db_reference"),
        "issues": [i for i in items if i["severity"] != "info"],
    }
    return summary, items


def _item(run_id, symbol, trade_id, broker_pos_id, broker_ord_id, itype, severity,
          db_snapshot=None, broker_snapshot=None, difference=None):
    return {
        "run_id": run_id, "symbol": symbol, "paper_trade_id": trade_id,
        "broker_position_id": broker_pos_id, "broker_order_id": broker_ord_id,
        "item_type": itype, "severity": severity, "status": "open",
        "db_snapshot": db_snapshot, "broker_snapshot": broker_snapshot,
        "difference": difference, "recommended_action": None,
    }


def _trade_snap(t):
    return {"id": t["id"], "symbol": t["symbol"], "shares": t.get("shares"),
            "entry_price": str(t.get("entry_price")), "stop": str(t.get("stop_loss")),
            "target": str(t.get("target_1")), "broker_order_id": t.get("broker_order_id")}


def _sanitize(obj):
    """Remove secret-like fields from broker data."""
    if not isinstance(obj, dict):
        return obj
    skip = {"account_id", "api_key", "secret_key"}
    return {k: v for k, v in obj.items() if k.lower() not in skip}


def save_run(conn, summary, items):
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO paper_broker_reconciliation_runs
            (run_id, status, alpaca_mode, broker_account_id_masked,
             db_open_trades, broker_open_positions, broker_open_orders,
             matched_positions, unmatched_db_trades, unmatched_broker_positions,
             unmatched_orders, errors, summary, finished_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now())
    """, [summary["run_id"], summary["status"], summary.get("alpaca_mode"),
          summary.get("broker_account_id_masked"),
          summary["db_open_trades"], summary["broker_open_positions"],
          summary["broker_open_orders"], summary["matched_positions"],
          summary["unmatched_db_trades"], summary["unmatched_broker_positions"],
          summary["unmatched_orders"],
          json.dumps([{"type": i["item_type"], "symbol": i["symbol"]}
                      for i in summary.get("issues", [])], default=str),
          json.dumps({k: v for k, v in summary.items() if k != "issues"}, default=str)])

    for it in items:
        cur.execute("""
            INSERT INTO paper_broker_reconciliation_items
                (run_id, symbol, paper_trade_id, broker_position_id, broker_order_id,
                 item_type, severity, status, db_snapshot, broker_snapshot,
                 difference, recommended_action)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, [it["run_id"], it["symbol"], it.get("paper_trade_id"),
              it.get("broker_position_id"), it.get("broker_order_id"),
              it["item_type"], it["severity"], it["status"],
              json.dumps(it.get("db_snapshot"), default=str) if it.get("db_snapshot") else None,
              json.dumps(it.get("broker_snapshot"), default=str) if it.get("broker_snapshot") else None,
              json.dumps(it.get("difference"), default=str) if it.get("difference") else None,
              it.get("recommended_action")])
    conn.commit()
    return summary["run_id"]


def main():
    parser = argparse.ArgumentParser(description="Paper broker reconciliation engine")
    parser.add_argument("--dry-run", action="store_true", help="Reconcile but do not write DB")
    parser.add_argument("--sync", action="store_true", help="Reconcile and write to DB")
    parser.add_argument("--once", action="store_true", help="Run once (default)")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--symbol", help="Filter to single symbol")
    parser.add_argument("--repair-safe", action="store_true", help="Update local metadata only")
    args = parser.parse_args()

    if not args.dry_run and not args.sync:
        args.dry_run = True  # default safe

    adapter = AlpacaPaperAdapter(dry_run=args.dry_run)
    conn = get_conn()
    try:
        if not adapter.enabled:
            out = {"status": "disabled", "message": "Alpaca paper not enabled", "items": []}
            print(json.dumps(out, indent=2, default=str) if args.json else f"[recon] {out['message']}")
            return

        summary, items = reconcile(conn, adapter, args.symbol)

        if args.sync:
            rid = save_run(conn, summary, items)
            log.info(f"Reconciliation {rid} saved: {summary['matched_positions']} matched, "
                     f"{len(summary.get('issues', []))} issues")

        out = {
            "mode": "dry_run" if args.dry_run else "sync",
            "run_id": summary["run_id"],
            "status": summary["status"],
            "db_open_trades": summary["db_open_trades"],
            "broker_positions": summary["broker_open_positions"],
            "broker_orders": summary["broker_open_orders"],
            "matched": summary["matched_positions"],
            "issues": len(summary.get("issues", [])),
            "items_by_type": {},
        }
        for it in items:
            out["items_by_type"][it["item_type"]] = out["items_by_type"].get(it["item_type"], 0) + 1

        if args.json:
            print(json.dumps(out, indent=2, default=str))
        else:
            print(f"[recon] {out['status']}: {out['matched']} matched, {out['issues']} issues, "
                  f"DB={out['db_open_trades']} broker_pos={out['broker_positions']} broker_ord={out['broker_orders']}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
