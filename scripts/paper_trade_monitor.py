#!/usr/bin/env python3
"""paper_trade_monitor.py — Active position management for Alpaca paper trades.

Runs every 5 minutes during market hours. For each open position:
  1. Checks current price vs entry, stop, target
  2. Computes R-multiple (profit in units of initial risk)
  3. Adjusts stop loss based on R progression (trailing)
  4. Closes position when target hit
  5. Sends alerts on significant changes
  6. Updates paper_trades with current state

Stop Adjustment Rules (R-multiple trailing):
  R >= 1.0: Move stop to breakeven (entry price)
  R >= 1.5: Move stop to lock 0.5R profit
  R >= 2.0: Move stop to lock 1.0R profit
  R >= 3.0: Move stop to lock 2.0R profit (tight trail)

These are the strategy risk-to-reward rules applied in real time.
The R-multiple trailing IS the strategy discipline in action — it
automatically protects profits as the trade moves in your favor.

Schedule: Every 5 min during market hours (cron)

Usage:
    .venv/bin/python scripts/paper_trade_monitor.py
    .venv/bin/python scripts/paper_trade_monitor.py --dry-run
"""
import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

log = logging.getLogger("paper_trade_monitor")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")


def _f(v):
    return float(v) if isinstance(v, Decimal) else v


def _alpaca_headers():
    return {
        'APCA-API-KEY-ID': os.getenv('ALPACA_API_KEY'),
        'APCA-API-SECRET-KEY': os.getenv('ALPACA_SECRET_KEY'),
    }

ALPACA_BASE = 'https://paper-api.alpaca.markets'


def _get_conn():
    from session13_db import get_conn
    return get_conn()


def _api_get(path):
    import requests
    resp = requests.get(f'{ALPACA_BASE}{path}', headers=_alpaca_headers(), timeout=10)
    return resp.json() if resp.status_code == 200 else []


def _api_post(path, data):
    import requests
    return requests.post(f'{ALPACA_BASE}{path}', json=data, headers=_alpaca_headers(), timeout=10)


def _api_delete(path):
    import requests
    return requests.delete(f'{ALPACA_BASE}{path}', headers=_alpaca_headers(), timeout=10)


def replace_stop(symbol, qty, new_stop, old_order_id=None):
    """Cancel old stop, place new one higher."""
    import time
    if old_order_id:
        _api_delete(f'/v2/orders/{old_order_id}')
        time.sleep(1)

    resp = _api_post('/v2/orders', {
        'symbol': symbol, 'qty': str(qty), 'side': 'sell',
        'type': 'stop', 'stop_price': str(round(new_stop, 2)),
        'time_in_force': 'gtc',
    })
    if resp.status_code in (200, 201):
        log.info(f"[{symbol}] Stop adjusted to ${new_stop:.2f}")
        return resp.json().get('id')
    log.error(f"[{symbol}] Stop failed: {resp.text[:100]}")
    return None


def monitor(dry_run=False):
    """Check all positions, adjust stops, take profits."""
    positions = _api_get('/v2/positions')
    if not isinstance(positions, list) or not positions:
        log.info("No open positions")
        return []

    conn = _get_conn()
    import psycopg2.extras
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    results = []

    for pos in positions:
        sym = pos['symbol']
        qty = int(pos['qty'])
        entry = float(pos['avg_entry_price'])
        current = float(pos['current_price'])
        pnl = float(pos['unrealized_pl'])
        pnl_pct = float(pos['unrealized_plpc']) * 100

        # Get DB trade record
        cur.execute("""
            SELECT id, stop_loss, target_1, strategy_id, entry_price
            FROM paper_trades WHERE symbol = %s AND status = 'open'
            ORDER BY created_at DESC LIMIT 1
        """, [sym])
        trade = cur.fetchone()
        if not trade:
            results.append({"symbol": sym, "action": "no_record",
                            "reason": "Position on Alpaca but no DB record",
                            "current": current, "pnl": round(pnl, 2), "pnl_pct": round(pnl_pct, 1)})
            continue

        stop = _f(trade.get('stop_loss')) or 0
        target = _f(trade.get('target_1')) or 0
        db_entry = _f(trade.get('entry_price')) or entry
        risk = abs(db_entry - stop) if stop and stop < db_entry else db_entry * 0.05
        r_mult = (current - db_entry) / risk if risk > 0 else 0

        # Current stop order on Alpaca
        orders = _api_get(f'/v2/orders?status=open&symbols={sym}')
        if not isinstance(orders, list):
            orders = []
        stop_orders = [o for o in orders if o.get('type') == 'stop' and o.get('side') == 'sell']
        stop_order_id = stop_orders[0]['id'] if stop_orders else None
        alpaca_stop = float(stop_orders[0]['stop_price']) if stop_orders else stop

        action = "hold"
        new_stop = alpaca_stop
        reason = f"R={r_mult:.1f} P&L=${pnl:+.0f} ({pnl_pct:+.1f}%)"

        # ── TARGET HIT → close position ──
        if target and current >= target:
            action = "close_target"
            reason = f"TARGET HIT ${current:.2f} >= ${target:.2f} (R={r_mult:.1f}, P&L=${pnl:+.0f})"
            if not dry_run:
                # Cancel stop first so shares are freed, then market sell
                if stop_order_id:
                    _api_delete(f'/v2/orders/{stop_order_id}')
                    import time; time.sleep(1)
                _api_delete(f'/v2/positions/{sym}')
                cur.execute("""UPDATE paper_trades SET status='closed', exit_price=%s,
                    close_date=NOW(), pnl=%s, r_multiple=%s WHERE id=%s""",
                    [current, round(pnl, 2), round(r_mult, 2), trade['id']])
                conn.commit()

        # ── NEAR TARGET (>80% of move) → tighten stop aggressively ──
        elif target and db_entry and target > db_entry:
            target_move = target - db_entry
            current_move = current - db_entry
            pct_to_target = current_move / target_move if target_move > 0 else 0
            if pct_to_target >= 0.80:
                # Within 80% of target — tighten stop to lock most of the gain
                new_stop = round(db_entry + target_move * 0.65, 2)  # lock 65% of target move
                if new_stop > alpaca_stop:
                    action = "tighten_near_target"
                    reason = f"NEAR TARGET ({pct_to_target*100:.0f}% of move) → tight stop ${new_stop:.2f} to lock gains"

        # ── R-MULTIPLE TRAILING STOP (the strategy's R:R in action) ──
        elif r_mult >= 3.0:
            new_stop = round(db_entry + risk * 2.0, 2)
            reason = f"R={r_mult:.1f} → lock 2.0R profit (stop ${new_stop:.2f})"
        elif r_mult >= 2.0:
            new_stop = round(db_entry + risk * 1.0, 2)
            reason = f"R={r_mult:.1f} → lock 1.0R profit (stop ${new_stop:.2f})"
        elif r_mult >= 1.5:
            new_stop = round(db_entry + risk * 0.5, 2)
            reason = f"R={r_mult:.1f} → lock 0.5R profit (stop ${new_stop:.2f})"
        elif r_mult >= 1.0:
            new_stop = round(db_entry, 2)
            reason = f"R={r_mult:.1f} → breakeven stop (${new_stop:.2f})"

        # Only move stop UP, never down
        if new_stop > alpaca_stop and action in ("hold", "tighten_near_target"):
            if action == "hold":
                action = "adjust_stop"
            if not dry_run:
                new_id = replace_stop(sym, qty, new_stop, stop_order_id)
                if new_id:
                    cur.execute("UPDATE paper_trades SET stop_loss=%s WHERE id=%s", [new_stop, trade['id']])
                    conn.commit()

        # Ensure stop exists if missing
        if not stop_orders and action == "hold" and stop > 0:
            action = "add_stop"
            reason = f"No stop on Alpaca — placing at ${stop:.2f}"
            if not dry_run:
                replace_stop(sym, qty, stop)

        # Update DB with current state
        if not dry_run:
            cur.execute("""UPDATE paper_trades SET current_price=%s, r_multiple=%s,
                pnl=%s, updated_at=NOW() WHERE id=%s""",
                [current, round(r_mult, 2), round(pnl, 2), trade['id']])
            conn.commit()

        results.append({
            "symbol": sym, "action": action, "entry": db_entry,
            "current": current, "stop": alpaca_stop,
            "new_stop": new_stop if action == "adjust_stop" else None,
            "target": target, "r_multiple": round(r_mult, 2),
            "pnl": round(pnl, 2), "pnl_pct": round(pnl_pct, 1),
            "reason": reason,
        })
        log.info(f"[{sym}] {action}: {reason}")

    # Alert on actions taken
    actions = [r for r in results if r['action'] != 'hold']
    if actions and not dry_run:
        try:
            from alert_dispatcher import dispatch_alert
            lines = ["*Paper Trade Monitor*", ""]
            for r in results:
                icon = {"hold": "—", "adjust_stop": "↑", "close_target": "$",
                        "tighten_near_target": "⬆", "add_stop": "+", "no_record": "?"}.get(r['action'], "•")
                lines.append(f"{icon} *{r['symbol']}* R={r.get('r_multiple',0):.1f} "
                             f"P&L=${r.get('pnl',0):+.0f} ({r.get('pnl_pct',0):+.1f}%)")
                if r['action'] != 'hold':
                    lines.append(f"  {r['reason']}")
            dispatch_alert("paper_trade_monitor", f"Trade Monitor: {len(actions)} action(s)",
                           "\n".join(lines), tier="ALERT", source="paper_trade_monitor",
                           dedupe_scope="global")
        except Exception:
            pass

    conn.close()
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    print(f"[paper_trade_monitor] {datetime.now().isoformat()}")
    results = monitor(dry_run=args.dry_run)
    for r in results:
        print(f"  {r['symbol']}: {r['action']} — {r['reason']}")


if __name__ == "__main__":
    main()
