#!/usr/bin/env python3
"""paper_trade_monitor.py — Monitor open/submitted Alpaca paper trades.

Fetches broker status, computes unrealized P/L, checks stop/target proximity,
and writes paper_execution_events. NEVER closes trades automatically.

SAFETY: Paper trading ONLY. Live trading is permanently blocked.

Usage:
    .venv/bin/python scripts/paper_trade_monitor.py --dry-run
    .venv/bin/python scripts/paper_trade_monitor.py --apply
    .venv/bin/python scripts/paper_trade_monitor.py --paper-trade-id 42 --apply
"""
import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

os.environ.setdefault("DOTENV_LOADED", "0")
if os.environ["DOTENV_LOADED"] == "0":
    try:
        from dotenv import load_dotenv
        load_dotenv(PROJECT_ROOT / ".env")
        os.environ["DOTENV_LOADED"] = "1"
    except Exception:
        pass

import psycopg2
import psycopg2.extras

log = logging.getLogger("paper_trade_monitor")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")

ALPACA_MODE = os.getenv("ALPACA_MODE", "paper").lower()
LIVE_TRADING_ENABLED = os.getenv("LIVE_TRADING_ENABLED", "false").lower() == "true"


def get_db():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        port=int(os.getenv("DB_PORT", 5432)),
        dbname=os.getenv("DB_NAME", "trade_ai"),
        user=os.getenv("DB_USER", "trade_ai"),
        password=os.getenv("DB_PASSWORD", ""),
        cursor_factory=psycopg2.extras.RealDictCursor,
    )


def _write_execution_event(conn, paper_trade_id, symbol, event_type, payload, dry_run=False):
    """Write to paper_execution_events table."""
    if dry_run:
        log.info(f"[dry-run] Would write event: {event_type} for {symbol} (trade #{paper_trade_id})")
        return
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO paper_execution_events
                (paper_trade_id, symbol, event_type, event_source, payload, created_at)
            VALUES (%s, %s, %s, 'paper_trade_monitor', %s, NOW())
        """, [paper_trade_id, symbol, event_type, json.dumps(payload, default=str)])
        conn.commit()
    except Exception as e:
        log.warning(f"Failed to write execution event: {e}")
        try:
            conn.rollback()
        except Exception:
            pass


def get_latest_price(adapter, symbol):
    """Get latest price from Alpaca for a symbol."""
    try:
        # Check positions first
        positions = adapter.get_positions()
        for pos in positions:
            if pos.get("symbol") == symbol:
                return {
                    "price": float(pos.get("current_price", 0)),
                    "source": "position",
                    "unrealized_pl": float(pos.get("unrealized_pl", 0)),
                    "qty": int(float(pos.get("qty", 0))),
                    "avg_entry": float(pos.get("avg_entry_price", 0)),
                    "market_value": float(pos.get("market_value", 0)),
                }
        return {"price": 0, "source": "not_in_positions"}
    except Exception as e:
        log.warning(f"Failed to get price for {symbol}: {e}")
        return {"price": 0, "source": "error", "error": str(e)}


def get_order_status(adapter, broker_order_id):
    """Get order status from Alpaca."""
    if not broker_order_id:
        return None
    try:
        return adapter._api_get(f"/v2/orders/{broker_order_id}")
    except Exception as e:
        log.warning(f"Failed to get order {broker_order_id}: {e}")
        return None


def monitor_trade(conn, trade, adapter, dry_run=False):
    """Monitor a single paper trade. Returns monitoring result dict."""
    trade_id = trade["id"]
    symbol = trade["symbol"]
    entry_price = float(trade.get("entry_price") or trade.get("planned_entry") or 0)
    stop_loss = float(trade.get("stop_loss") or 0)
    target_1 = float(trade.get("target_1") or 0)
    shares = int(trade.get("shares") or 0)
    broker_order_id = trade.get("broker_order_id")
    current_status = trade.get("status", "")

    result = {
        "paper_trade_id": trade_id,
        "symbol": symbol,
        "status": current_status,
        "broker_order_id": broker_order_id,
        "entry_price": entry_price,
        "stop_loss": stop_loss,
        "target_1": target_1,
        "shares": shares,
    }

    # Fetch Alpaca order status if we have a broker_order_id
    order_status = None
    if broker_order_id and adapter.enabled:
        order_status = get_order_status(adapter, broker_order_id)
        if order_status:
            result["broker_status"] = order_status.get("status")
            result["filled_qty"] = order_status.get("filled_qty")
            result["filled_avg_price"] = order_status.get("filled_avg_price")

            # Update broker_status in paper_trades if changed
            new_broker_status = order_status.get("status", "")
            if new_broker_status and new_broker_status != trade.get("broker_status"):
                if not dry_run:
                    cur = conn.cursor()
                    cur.execute("""
                        UPDATE paper_trades SET broker_status = %s, updated_at = NOW()
                        WHERE id = %s
                    """, [new_broker_status, trade_id])
                    conn.commit()
                _write_execution_event(conn, trade_id, symbol, "BROKER_STATUS_CHANGED", {
                    "old_status": trade.get("broker_status"),
                    "new_status": new_broker_status,
                    "order_id": broker_order_id,
                }, dry_run=dry_run)

    # Fetch latest price
    price_info = get_latest_price(adapter, symbol)
    current_price = price_info.get("price", 0)
    result["current_price"] = current_price
    result["price_source"] = price_info.get("source")

    # Compute unrealized P/L and R
    if current_price > 0 and entry_price > 0 and shares > 0:
        unrealized_pnl = round((current_price - entry_price) * shares, 2)
        unrealized_pnl_pct = round(((current_price - entry_price) / entry_price) * 100, 2)
        risk_per_share = abs(entry_price - stop_loss) if stop_loss > 0 else 0
        r_multiple = round((current_price - entry_price) / risk_per_share, 2) if risk_per_share > 0 else None

        result["unrealized_pnl"] = unrealized_pnl
        result["unrealized_pnl_pct"] = unrealized_pnl_pct
        result["r_multiple"] = r_multiple

        # Update paper_trades
        if not dry_run:
            cur = conn.cursor()
            cur.execute("""
                UPDATE paper_trades
                SET current_price = %s, unrealized_pnl = %s, last_synced_at = NOW(), updated_at = NOW()
                WHERE id = %s
            """, [current_price, unrealized_pnl, trade_id])
            conn.commit()

        # Check stop/target proximity
        if stop_loss > 0:
            stop_distance_pct = round(((current_price - stop_loss) / current_price) * 100, 2)
            result["stop_distance_pct"] = stop_distance_pct
            if stop_distance_pct <= 1.0:
                result["stop_proximity"] = "NEAR_STOP"
                _write_execution_event(conn, trade_id, symbol, "NEAR_STOP_ALERT", {
                    "current_price": current_price,
                    "stop_loss": stop_loss,
                    "distance_pct": stop_distance_pct,
                    "r_multiple": r_multiple,
                }, dry_run=dry_run)
            if current_price <= stop_loss:
                result["stop_proximity"] = "BELOW_STOP"
                _write_execution_event(conn, trade_id, symbol, "BELOW_STOP_ALERT", {
                    "current_price": current_price,
                    "stop_loss": stop_loss,
                    "r_multiple": r_multiple,
                }, dry_run=dry_run)

        if target_1 > 0:
            target_distance_pct = round(((target_1 - current_price) / current_price) * 100, 2)
            result["target_distance_pct"] = target_distance_pct
            if target_distance_pct <= 1.0 and current_price < target_1:
                result["target_proximity"] = "NEAR_TARGET"
                _write_execution_event(conn, trade_id, symbol, "NEAR_TARGET_ALERT", {
                    "current_price": current_price,
                    "target_1": target_1,
                    "distance_pct": target_distance_pct,
                    "r_multiple": r_multiple,
                }, dry_run=dry_run)
            if current_price >= target_1:
                result["target_proximity"] = "AT_OR_ABOVE_TARGET"
                _write_execution_event(conn, trade_id, symbol, "TARGET_REACHED_ALERT", {
                    "current_price": current_price,
                    "target_1": target_1,
                    "r_multiple": r_multiple,
                }, dry_run=dry_run)

    # Write MONITOR_UPDATE event
    _write_execution_event(conn, trade_id, symbol, "MONITOR_UPDATE", {
        "current_price": current_price,
        "unrealized_pnl": result.get("unrealized_pnl"),
        "r_multiple": result.get("r_multiple"),
        "broker_status": result.get("broker_status"),
        "price_source": result.get("price_source"),
    }, dry_run=dry_run)

    return result


def monitor_all(conn, dry_run=False, paper_trade_id=None):
    """Monitor all open/submitted paper trades (or a specific one)."""
    # Safety checks
    if LIVE_TRADING_ENABLED:
        return {"error": "LIVE_TRADING_ENABLED is true -- monitor blocked", "results": []}
    if ALPACA_MODE != "paper":
        return {"error": f"ALPACA_MODE={ALPACA_MODE}, must be 'paper'", "results": []}

    # Import adapter
    try:
        from alpaca_paper_adapter import AlpacaPaperAdapter
        adapter = AlpacaPaperAdapter(dry_run=dry_run)
    except Exception as e:
        return {"error": f"Failed to load adapter: {e}", "results": []}

    cur = conn.cursor()
    if paper_trade_id:
        cur.execute("""
            SELECT * FROM paper_trades WHERE id = %s
        """, [paper_trade_id])
    else:
        cur.execute("""
            SELECT * FROM paper_trades
            WHERE status IN ('open', 'pending', 'submitted')
              AND account = 'ALPACA_PAPER'
            ORDER BY created_at DESC
        """)
    trades = cur.fetchall()

    results = []
    for trade in trades:
        try:
            result = monitor_trade(conn, trade, adapter, dry_run=dry_run)
            results.append(result)
        except Exception as e:
            log.error(f"Failed to monitor trade #{trade['id']}: {e}")
            results.append({
                "paper_trade_id": trade["id"],
                "symbol": trade["symbol"],
                "error": str(e),
            })

    return {
        "status": "dry_run" if dry_run else "applied",
        "monitored_count": len(results),
        "results": results,
        "alpaca_mode": ALPACA_MODE,
    }


def main():
    parser = argparse.ArgumentParser(description="Paper trade monitor")
    parser.add_argument("--dry-run", action="store_true", help="Compute but do not write")
    parser.add_argument("--apply", action="store_true", help="Write updates to DB")
    parser.add_argument("--paper-trade-id", type=int, help="Monitor specific trade")
    args = parser.parse_args()

    if not args.dry_run and not args.apply:
        parser.error("Specify --dry-run or --apply")

    conn = get_db()
    try:
        result = monitor_all(
            conn,
            dry_run=args.dry_run,
            paper_trade_id=args.paper_trade_id,
        )
        print(json.dumps(result, indent=2, default=str))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
