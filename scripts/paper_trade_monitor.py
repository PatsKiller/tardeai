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

# A just-submitted/just-filled order may not yet appear as an Alpaca position — don't void a trade as a
# phantom until it has been open past this grace window (prevents false phantoms from fill-settlement
# timing). A genuinely never-filled / never-submitted trade is still voided once it ages past the window.
PHANTOM_GRACE_MIN = 15

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

def _alpaca_base():
    """Get Alpaca base URL from ALPACA_MODE. Defaults to paper."""
    mode = os.getenv('ALPACA_MODE', 'paper').lower()
    if mode == 'paper':
        return 'https://paper-api.alpaca.markets'
    # Safety: block live unless explicitly configured
    raise RuntimeError(f"BLOCKED: ALPACA_MODE={mode} — only paper mode allowed in paper_trade_monitor")

ALPACA_BASE = _alpaca_base()


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


def _reconcile_broker_exit(broker_oid, stop_oid, tp_oid, entry_price, shares, dollar_risk=None):
    """Thin wrapper over the shared trade_outcome_helpers.reconcile_broker_exit (single source of truth,
    also used by alpaca_paper_adapter close-sync), bound to this module's Alpaca GET. See that helper for
    the {"kind": phantom|reconciled|filled_no_exit} contract."""
    from trade_outcome_helpers import reconcile_broker_exit
    return reconcile_broker_exit(_api_get, broker_oid, stop_oid, tp_oid, entry_price, shares, dollar_risk)


def replace_stop(symbol, qty, new_stop, old_order_id=None):
    """Cancel old stop, verify cancellation, place new one higher."""
    import time
    if old_order_id:
        _api_delete(f'/v2/orders/{old_order_id}')
        # Verify cancellation before placing new stop (Alpaca needs time to release qty)
        for _wait in range(5):
            time.sleep(1)
            try:
                check = _api_get(f'/v2/orders/{old_order_id}')
                if check.status_code == 200:
                    status = check.json().get('status', '')
                    if status in ('canceled', 'cancelled'):
                        break
                    log.info(f"[{symbol}] Waiting for stop cancel (status={status}, attempt {_wait+1})")
                else:
                    break  # order not found = cancelled
            except Exception:
                break
        else:
            log.warning(f"[{symbol}] Old stop cancel may not be confirmed — proceeding anyway")

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


def _fix_integrity_issues(conn, alpaca_symbols):
    """Fix data integrity issues before processing positions."""
    cur = conn.cursor()
    fixed = 0

    # Fix 1: Pending/open rows never submitted to broker after 15min → cancel (not phantom)
    cur.execute("""
        UPDATE paper_trades
        SET lifecycle_state = 'cancelled', status = 'cancelled',
            close_reason = 'cancelled_never_submitted_timeout',
            exit_reason = 'cancelled_never_submitted_timeout',
            notes = COALESCE(notes,'') || CASE WHEN COALESCE(notes,'')='' THEN '' ELSE ' | ' END
                  || 'CANCELLED — Never submitted (timeout): no broker order within 15 minutes',
            closed_via = 'integrity_check', closed_at = NOW(),
            outcome_verdict = 'CANCELLED', pnl = 0, pnl_pct = 0, r_multiple = 0, unrealized_pnl = 0
        WHERE status IN ('pending', 'open')
          AND COALESCE(broker_order_id, '') = ''
          AND filled_at IS NULL
          AND created_at < NOW() - INTERVAL '15 minutes'
        RETURNING id, symbol, proposal_id
    """)
    for r in cur.fetchall():
        log.warning(f"[integrity] CANCELLED never-submitted: {r[1]} id={r[0]} proposal={r[2]}")
        try:
            from telegram_alert import send_telegram
            send_telegram(
                f"🚫 *TRADE CANCELLED — {r[1]}*\n\n"
                f"Trade record #{r[0]} / proposal #{r[2] or '?'}\n"
                f"*Reason:* Never submitted (timeout)\n"
                f"*Detail:* No broker order within 15 minutes — auto-cancelled by monitor\n\n"
                f"No Alpaca order was submitted. DB record marked `cancelled`."
            )
        except Exception:
            pass
        fixed += 1

    # Fix 1b: Open trades with broker order but never filled after 30min → cancel
    cur.execute("""
        UPDATE paper_trades
        SET lifecycle_state = 'cancelled', status = 'cancelled',
            close_reason = 'auto_fix_never_filled',
            exit_reason = 'auto_fix_never_filled',
            closed_via = 'integrity_check', closed_at = NOW(),
            outcome_verdict = 'CANCELLED', pnl = 0, pnl_pct = 0, r_multiple = 0
        WHERE lifecycle_state = 'open' AND status = 'open'
          AND COALESCE(broker_order_id, '') <> ''
          AND filled_at IS NULL AND broker_status NOT IN ('filled')
          AND created_at < NOW() - INTERVAL '30 minutes'
        RETURNING id, symbol
    """)
    for r in cur.fetchall():
        log.info(f"[integrity] Auto-cancelled never-filled: {r[1]} id={r[0]}")
        fixed += 1

    # Fix 2: DB says open (broker-submitted) but Alpaca doesn't have it. Before voiding as a phantom,
    # check broker truth: a FILLED entry whose OCO exit leg also filled is a REAL closed position whose
    # exit the DB simply never recorded — reconcile its true P&L instead of falsely voiding it to $0.
    cur.execute("""SELECT id, symbol, entry_time, entry_price, shares, stop_loss, current_price, dollar_risk,
                          broker_order_id, stop_order_id, take_profit_order_id
                   FROM paper_trades
                   WHERE lifecycle_state='open' AND status='open'
                     AND (COALESCE(broker_order_id,'') <> '' OR filled_at IS NOT NULL)""")
    for row in cur.fetchall():
        tid, sym = row[0], row[1]
        _entry_t = row[2] if len(row) > 2 else None
        _entry_price = float(row[3]) if row[3] else None
        _shares = int(row[4]) if row[4] else 0
        _stop = float(row[5]) if row[5] else None
        _current = float(row[6]) if row[6] else None
        _dollar_risk = float(row[7]) if row[7] else None
        _broker_oid, _stop_oid, _tp_oid = row[8], row[9], row[10]
        if sym not in alpaca_symbols:
            _hold_min = None
            if _entry_t:
                try:
                    _now = datetime.now(timezone.utc)
                    _et = _entry_t.replace(tzinfo=timezone.utc) if _entry_t.tzinfo is None else _entry_t
                    _hold_min = round((_now - _et).total_seconds() / 60, 1)
                except Exception:
                    pass
            # GRACE: skip voiding a freshly-opened trade — an in-flight fill may not show as an Alpaca
            # position yet. It is re-checked next cycle and voided then if it still isn't on Alpaca.
            if _hold_min is not None and _hold_min < PHANTOM_GRACE_MIN:
                log.info(f"[integrity] {sym} id={tid} not on Alpaca but only {_hold_min}min old — grace, recheck next cycle")
                continue
            # BROKER TRUTH: reconcile a real closed position, or skip a filled-but-unresolved one.
            _recon = _reconcile_broker_exit(_broker_oid, _stop_oid, _tp_oid, _entry_price, _shares, _dollar_risk)
            if _recon["kind"] == "reconciled":
                cur.execute("""
                    UPDATE paper_trades SET lifecycle_state='closed', status='closed',
                        close_reason=%s, closed_at=NOW(),
                        exit_time=COALESCE(exit_time, NOW()),
                        entry_time=COALESCE(entry_time, filled_at, created_at),
                        closed_via='integrity_reconcile', exit_reason=%s, exit_price=%s,
                        pnl=%s, pnl_pct=%s, r_multiple=%s, unrealized_pnl=0,
                        hold_time_min=COALESCE(hold_time_min, %s),
                        outcome_verdict=%s
                    WHERE id=%s
                """, [_recon["exit_reason"], _recon["exit_reason"], _recon["exit_price"],
                      _recon["pnl"], _recon["pnl_pct"], _recon["r_multiple"], _hold_min,
                      _recon["verdict"], tid])
                log.warning(f"[integrity] Reconciled broker exit (NOT phantom): {sym} id={tid} "
                            f"exit={_recon['exit_price']} pnl={_recon['pnl']} {_recon['verdict']}")
                fixed += 1
                continue
            if _recon["kind"] == "filled_no_exit":
                # Real filled position whose exit isn't resolvable yet — NEVER void it; the hourly
                # alpaca_paper_adapter close-sync fetches the exit and books real P&L.
                log.warning(f"[integrity] {sym} id={tid} filled but exit not yet resolvable — leaving open "
                            f"for alpaca close-sync (NOT voiding as phantom)")
                continue
            # PHANTOM: entry order never filled → no real position. It must carry NO P&L —
            # computing (current-entry)*shares records a FAKE win/loss that pollutes the journal
            # (e.g. MRVL +$126, SNOW +$131 booked as bogus 'wins'). Void it: zero P&L, verdict PHANTOM,
            # excluded from real performance. (Real recovered positions like ANY stay open / on Alpaca
            # and never reach this branch.)
            cur.execute("""
                UPDATE paper_trades SET lifecycle_state='closed', status='closed',
                    close_reason='phantom_no_alpaca_position', closed_at=NOW(),
                    exit_time=COALESCE(exit_time, NOW()),
                    entry_time=COALESCE(entry_time, filled_at, created_at),
                    closed_via='integrity_check',
                    exit_reason='phantom_no_alpaca_position',
                    exit_price = entry_price,
                    pnl = 0, pnl_pct = 0, r_multiple = 0, unrealized_pnl = 0,
                    hold_time_min = COALESCE(hold_time_min, %s),
                    outcome_verdict = 'PHANTOM'
                WHERE id = %s
            """, [_hold_min, tid])
            log.warning(f"[integrity] Closed phantom: {sym} id={tid} — not on Alpaca, P&L voided (was never a real position)")
            fixed += 1

    # Fix 3: closed_at set but lifecycle_state still open
    cur.execute("""
        UPDATE paper_trades SET lifecycle_state = 'closed',
            outcome_verdict = CASE WHEN pnl > 0 THEN 'WIN' WHEN pnl < 0 THEN 'LOSS' ELSE 'BREAKEVEN' END
        WHERE lifecycle_state = 'open' AND closed_at IS NOT NULL
        RETURNING id, symbol
    """)
    for r in cur.fetchall():
        log.info(f"[integrity] Fixed stuck closed: {r[1]} id={r[0]}")
        fixed += 1

    if fixed > 0:
        conn.commit()
        log.info(f"[integrity] Fixed {fixed} data integrity issues")
    return fixed


def monitor(dry_run=False):
    """Check all positions, adjust stops, take profits."""
    positions = _api_get('/v2/positions')
    if not isinstance(positions, list) or not positions:
        log.info("No open positions")
        return []

    conn = _get_conn()

    # Run integrity check before processing
    alpaca_symbols = {p['symbol'] for p in positions}
    _fix_integrity_issues(conn, alpaca_symbols)

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
            SELECT id, stop_loss, target_1, strategy_id, entry_price,
                   max_favorable_excursion, max_adverse_excursion, updated_at
            FROM paper_trades WHERE symbol = %s AND status = 'open'
            ORDER BY created_at DESC LIMIT 1
        """, [sym])
        trade = cur.fetchone()
        if not trade:
            results.append({"symbol": sym, "action": "no_record",
                            "reason": "Position on Alpaca but no DB record",
                            "current": current, "pnl": round(pnl, 2), "pnl_pct": round(pnl_pct, 1)})
            continue

        # ── Gap 7 fix: Catch-up detection ──
        _last_update = trade.get('updated_at')
        if _last_update:
            try:
                _lu_dt = _last_update if hasattr(_last_update, 'timestamp') else datetime.fromisoformat(str(_last_update))
                if _lu_dt.tzinfo is None:
                    _lu_dt = _lu_dt.replace(tzinfo=timezone.utc)
                _gap_min = (datetime.now(timezone.utc) - _lu_dt).total_seconds() / 60
                if _gap_min > 10:
                    log.warning(f"[{sym}] CATCH-UP: last update was {_gap_min:.0f}min ago — forcing full re-evaluation")
            except Exception:
                pass

        stop = _f(trade.get('stop_loss')) or 0
        target = _f(trade.get('target_1')) or 0
        db_entry = _f(trade.get('entry_price')) or entry
        risk = abs(db_entry - stop) if stop and stop < db_entry else db_entry * 0.05
        r_mult = (current - db_entry) / risk if risk > 0 else 0

        # Track MFE/MAE (max favorable/adverse excursion as % from entry)
        current_excursion_pct = ((current - db_entry) / db_entry * 100) if db_entry else 0
        prev_mfe = _f(trade.get('max_favorable_excursion')) or 0
        prev_mae = _f(trade.get('max_adverse_excursion')) or 0
        new_mfe = max(prev_mfe, current_excursion_pct) if current_excursion_pct > 0 else prev_mfe
        new_mae = min(prev_mae, current_excursion_pct) if current_excursion_pct < 0 else prev_mae

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
                # Use full close path for journal completeness
                try:
                    from paper_trade_logger import close_paper_trade
                    close_paper_trade(sym, current, reason=f"target_hit: {reason}")
                except Exception as close_err:
                    log.warning(f"[{sym}] Full close failed ({close_err}), using fallback")
                    cur.execute("""UPDATE paper_trades SET status='closed', lifecycle_state='closed',
                        exit_price=%s,
                        exit_reason=%s, close_date=NOW(), closed_at=NOW(),
                        exit_time=COALESCE(exit_time, NOW()),
                        entry_time=COALESCE(entry_time, filled_at, created_at),
                        pnl=%s, pnl_pct=%s, r_multiple=%s, hold_time_min=%s,
                        outcome_verdict=%s WHERE id=%s""",
                        [current, f"target_hit: {reason}", round(pnl, 2),
                         round(pnl_pct, 1), round(r_mult, 2),
                         round((datetime.now(timezone.utc) - (trade.get('entry_time') or datetime.now(timezone.utc))).total_seconds() / 60, 1) if trade.get('entry_time') else None,
                         'CORRECT' if pnl > 0 else ('WRONG' if pnl < 0 else 'NEUTRAL'),
                         trade['id']])
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

        # ── STRATEGY-AWARE TRAILING STOP ──
        # Uses per-strategy family tiers from strategy_trailing_policy.py.
        # Income/position strategies trail wider (breakeven at 1.5R/2.0R),
        # momentum/swing trail tighter (breakeven at 1.0R).
        else:
            try:
                from strategy_trailing_policy import get_trailing_policy
                _policy = get_trailing_policy(trade.get('strategy_id', 'unknown'))
                _tiers = _policy.get('tiers', [])
                # Walk tiers in reverse (highest R threshold first)
                for _r_thresh, _lock_r, _desc in reversed(_tiers):
                    if r_mult >= _r_thresh:
                        new_stop = round(db_entry + risk * _lock_r, 2)
                        reason = f"R={r_mult:.1f} [{_policy.get('family','?')}] ≥{_r_thresh}R → {_desc} (stop ${new_stop:.2f})"
                        break
            except ImportError:
                # Fallback: original hard-coded tiers if policy module unavailable
                if r_mult >= 3.0:
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
                    cur.execute("UPDATE paper_trades SET stop_loss=%s, stop_order_id=%s, stop_updated_at=NOW() WHERE id=%s",
                                [new_stop, new_id, trade['id']])
                    conn.commit()
                    log.info(f"TRAILING STOP: {sym} R={r_mult:.1f} — stop ${alpaca_stop:.2f} → ${new_stop:.2f}")
                    try:
                        from stop_change_audit import log_stop_change
                        log_stop_change(conn, trade['id'], sym, alpaca_stop, new_stop,
                                        change_type='trailing_update', source='paper_trade_monitor',
                                        reason=reason, broker_order_id=new_id,
                                        strategy_id=trade.get('strategy_id'))
                    except Exception:
                        pass

        # Ensure stop exists if missing
        if not stop_orders and action == "hold" and stop > 0:
            action = "add_stop"
            reason = f"No stop on Alpaca — placing at ${stop:.2f}"
            if not dry_run:
                replace_stop(sym, qty, stop)

        # Update DB with current state
        if not dry_run:
            dollar_risk = round(abs(db_entry - stop) * qty, 2) if stop and db_entry else None
            cur.execute("""UPDATE paper_trades SET current_price=%s, r_multiple=%s,
                pnl=%s, unrealized_pnl=%s, dollar_risk=%s,
                max_favorable_excursion=%s, max_adverse_excursion=%s,
                updated_at=NOW() WHERE id=%s""",
                [current, round(r_mult, 2), round(pnl, 2), round(pnl, 2), dollar_risk,
                 round(new_mfe, 2), round(new_mae, 2), trade['id']])

            # ── Execution log: record every non-hold action for journal ──
            if action != "hold":
                try:
                    cur.execute("""
                        INSERT INTO agent_curation_events
                            (paper_trade_id, symbol, strategy_id, agent_name, event_type, event_summary, payload)
                        VALUES (%s, %s, %s, 'monitor', %s, %s, %s)
                    """, [trade['id'], sym, trade.get('strategy_id', ''),
                          f'MONITOR_{action.upper()}',
                          f"{action}: {reason}",
                          json.dumps({
                              'action': action, 'price': current, 'stop': alpaca_stop,
                              'new_stop': new_stop if action in ('adjust_stop', 'tighten_near_target') else None,
                              'r_multiple': round(r_mult, 2), 'pnl': round(pnl, 2),
                              'pnl_pct': round(pnl_pct, 1),
                              'mfe_pct': round(new_mfe, 2), 'mae_pct': round(new_mae, 2),
                          })])
                except Exception:
                    pass  # non-blocking
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

    # ── PHANTOM DETECTION: DB says open but Alpaca has no position ──
    alpaca_symbols = {pos['symbol'] for pos in positions}
    cur.execute("SELECT id, symbol, entry_price, shares, strategy_id, stop_loss, current_price, dollar_risk, entry_time, created_at, broker_order_id, stop_order_id, take_profit_order_id FROM paper_trades WHERE status = 'open'")
    db_open = cur.fetchall()
    for dbt in db_open:
        if dbt['symbol'] not in alpaca_symbols:
            log.warning(f"[{dbt['symbol']}] PHANTOM: open in DB but NOT on Alpaca — auto-closing")
            _ep = float(dbt['entry_price']) if dbt['entry_price'] else 0
            _sh = int(dbt['shares']) if dbt['shares'] else 0
            _cp = float(dbt['current_price']) if dbt['current_price'] else _ep
            _stop = float(dbt['stop_loss']) if dbt['stop_loss'] else None
            _dr = float(dbt['dollar_risk']) if dbt['dollar_risk'] else None
            _exit_p = _cp if _cp else _ep
            _pnl = round((_exit_p - _ep) * _sh, 2) if _ep and _sh else 0
            _pnl_pct = round((_exit_p - _ep) / _ep * 100, 2) if _ep > 0 else 0
            _r_mult = None
            if _dr and _dr > 0:
                _r_mult = round(_pnl / _dr, 3)
            elif _stop and _ep and abs(_ep - _stop) > 0:
                _r_mult = round((_exit_p - _ep) / abs(_ep - _stop), 3)
            _et = dbt.get('entry_time') or dbt.get('created_at')
            _hold_min = None
            if _et:
                try:
                    _now = datetime.now(timezone.utc)
                    _ett = _et.replace(tzinfo=timezone.utc) if _et.tzinfo is None else _et
                    _hold_min = round((_now - _ett).total_seconds() / 60, 1)
                except Exception:
                    pass
            # GRACE: an in-flight fill may not show as an Alpaca position yet — recheck next cycle.
            if _hold_min is not None and _hold_min < PHANTOM_GRACE_MIN:
                log.info(f"[{dbt['symbol']}] not on Alpaca but only {_hold_min}min old — grace, recheck next cycle")
                continue
            # BROKER TRUTH: reconcile a real closed position, or skip a filled-but-unresolved one, instead
            # of voiding with fabricated current-price P&L.
            _recon = _reconcile_broker_exit(dbt.get('broker_order_id'), dbt.get('stop_order_id'),
                                            dbt.get('take_profit_order_id'), _ep or None, _sh, _dr)
            if _recon["kind"] == "reconciled":
                cur.execute("""
                    UPDATE paper_trades SET status='closed', lifecycle_state='closed',
                        exit_reason=%s, close_reason=%s, exit_price=%s, pnl=%s, pnl_pct=%s,
                        r_multiple=%s, unrealized_pnl=0, hold_time_min=COALESCE(hold_time_min, %s),
                        outcome_verdict=%s, closed_via='integrity_reconcile',
                        closed_at=NOW(), exit_time=COALESCE(exit_time, NOW()),
                        entry_time=COALESCE(entry_time, filled_at, created_at), updated_at=NOW()
                    WHERE id=%s
                """, [_recon["exit_reason"], _recon["exit_reason"], _recon["exit_price"], _recon["pnl"],
                      _recon["pnl_pct"], _recon["r_multiple"], _hold_min, _recon["verdict"], dbt['id']])
                conn.commit()
                log.warning(f"[{dbt['symbol']}] Reconciled broker exit (NOT phantom): id={dbt['id']} "
                            f"exit={_recon['exit_price']} pnl={_recon['pnl']} {_recon['verdict']}")
                results.append({"symbol": dbt['symbol'], "action": "exit_reconciled",
                                "reason": "DB open but position closed on Alpaca — booked real exit",
                                "pnl": _recon["pnl"], "pnl_pct": _recon["pnl_pct"], "r_multiple": _recon["r_multiple"]})
                continue
            if _recon["kind"] == "filled_no_exit":
                log.warning(f"[{dbt['symbol']}] id={dbt['id']} filled but exit not yet resolvable — leaving "
                            f"open for alpaca close-sync (NOT voiding as phantom)")
                continue
            cur.execute("""
                UPDATE paper_trades
                SET status = 'closed', lifecycle_state = 'closed',
                    exit_reason = 'phantom_no_alpaca_position',
                    exit_price = %s, pnl = %s, pnl_pct = %s,
                    r_multiple = COALESCE(r_multiple, %s),
                    hold_time_min = COALESCE(hold_time_min, %s),
                    outcome_verdict = CASE WHEN %s > 0 THEN 'WIN' WHEN %s < 0 THEN 'LOSS' ELSE 'BREAKEVEN' END,
                    closed_at = NOW(), exit_time = COALESCE(exit_time, NOW()),
                    entry_time = COALESCE(entry_time, filled_at, created_at),
                    closed_via = 'monitor_phantom_check',
                    notes = COALESCE(notes, '') || ' | Auto-closed by monitor: no matching Alpaca position found.',
                    updated_at = NOW()
                WHERE id = %s
            """, [_exit_p, _pnl, _pnl_pct, _r_mult, _hold_min, _pnl, _pnl, dbt['id']])
            conn.commit()
            results.append({
                "symbol": dbt['symbol'], "action": "phantom_closed",
                "reason": f"DB open but no Alpaca position — auto-closed",
                "pnl": _pnl, "pnl_pct": _pnl_pct, "r_multiple": _r_mult or 0,
            })

    # Alert on actions taken
    actions = [r for r in results if r['action'] != 'hold']
    if actions and not dry_run:
        try:
            from alert_dispatcher import dispatch_alert
            lines = ["*Paper Trade Monitor*", ""]
            for r in results:
                icon = {"hold": "—", "adjust_stop": "↑", "close_target": "$",
                        "tighten_near_target": "⬆", "add_stop": "+", "no_record": "?",
                        "phantom_closed": "⛔"}.get(r['action'], "•")
                lines.append(f"{icon} *{r['symbol']}* R={r.get('r_multiple',0):.1f} "
                             f"P&L=${r.get('pnl',0):+.0f} ({r.get('pnl_pct',0):+.1f}%)")
                if r['action'] != 'hold':
                    lines.append(f"  {r['reason']}")
            dispatch_alert("paper_trade_monitor", f"Trade Monitor: {len(actions)} action(s)",
                           "\n".join(lines), tier="ALERT", source="paper_trade_monitor",
                           dedupe_scope="global")
        except Exception:
            pass

    # Run post-close processors for any trades closed this cycle
    closed_trades = [r for r in results if r['action'] == 'close_target']
    if closed_trades and not dry_run:
        try:
            import subprocess
            # Thesis reviewer: compares plan vs actual, classifies thesis outcome
            subprocess.Popen(
                [str(PROJECT_ROOT / ".venv/bin/python"),
                 str(PROJECT_ROOT / "scripts/post_trade_thesis_reviewer.py"), "--apply"],
                cwd=str(PROJECT_ROOT),
                stdout=open(str(PROJECT_ROOT / "logs/post_trade_thesis_auto.log"), "a"),
                stderr=subprocess.STDOUT,
            )
            # Scored thesis review → trade_thesis_reviews (journal-learning lane). Idempotent
            # (skips already-reviewed trades); previously had no scheduled runner.
            subprocess.Popen(
                [str(PROJECT_ROOT / ".venv/bin/python"),
                 str(PROJECT_ROOT / "scripts/trade_thesis_review_engine.py"), "--apply", "--json"],
                cwd=str(PROJECT_ROOT),
                stdout=open(str(PROJECT_ROOT / "logs/trade_thesis_review_engine_auto.log"), "a"),
                stderr=subprocess.STDOUT,
            )
            # Outcome analytics: builds R-multiple, MFE/MAE, plan adherence stats
            subprocess.Popen(
                [str(PROJECT_ROOT / ".venv/bin/python"),
                 str(PROJECT_ROOT / "scripts/paper_outcome_analytics.py"), "--since", "7", "--apply"],
                cwd=str(PROJECT_ROOT),
                stdout=open(str(PROJECT_ROOT / "logs/paper_outcome_analytics_auto.log"), "a"),
                stderr=subprocess.STDOUT,
            )
            log.info(f"Triggered post-close processors for {len(closed_trades)} closed trade(s)")
        except Exception as e:
            log.warning(f"Post-close processor trigger failed: {e}")

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
