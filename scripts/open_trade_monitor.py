#!/usr/bin/env python3
"""open_trade_monitor.py — Monitor open paper trades for alerts.

Runs every 15 minutes during market hours.
Checks: near-stop, near-target, stale, extended profit, negative news,
volume fade, Alpaca sync status.

Usage:
    .venv/bin/python scripts/open_trade_monitor.py --dry-run
    .venv/bin/python scripts/open_trade_monitor.py --once
    .venv/bin/python scripts/open_trade_monitor.py --no-telegram

PAPER ONLY — does not touch live trades.
"""
import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

# 2026-08-31: this was a module-level `from session13_db import get_conn`, so
# importing this module required psycopg2 -- and the deterministic CI subset
# runs WITHOUT a database. The repo supports JSON-only mode by design
# (AGENTS.md §18), and a notification module should not need a live DB merely
# to be imported. Deferred to first use; the single call site is run_monitor().
def get_conn(*args, **kwargs):
    from session13_db import get_conn as _get_conn
    return _get_conn(*args, **kwargs)

log = logging.getLogger("open_trade_monitor")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")


def _alpaca_base_url():
    """Get Alpaca base URL from ALPACA_MODE. Defaults to paper."""
    mode = os.getenv('ALPACA_MODE', 'paper').lower()
    if mode == 'paper':
        return 'https://paper-api.alpaca.markets'
    raise RuntimeError(f"BLOCKED: ALPACA_MODE={mode} — only paper mode allowed in open_trade_monitor")


ALPACA_BASE = _alpaca_base_url()

# Time stop: max hold days per strategy (None = no time stop)
# Intraday strategies use market close (3:45 PM ET), not day count
INTRADAY_STRATEGIES = {'momentum_scalp', 'gap_and_go'}
MAX_HOLD_DAYS = {
    'swing_breakout': 21, 'swing_trade': 21,
    'earnings_catalyst': 7, 'speculative_growth': 21,
    'sector_rotation': 56, 'defense_thesis': 56,
    'core_growth_compounder': None, 'core_index': None,
    'income_add': None, 'dividend_growth_compounder': None,
    'high_yield_income_bdc': None, 'covered_call_income': None,
    'bond_income': None, 'cash_or_stable': None,
    'recovery_watch': None, 'reit_income': None,
    'international_dividend': None, 'tax_loss_harvest': None,
}

NEGATIVE_KEYWORDS = [
    'offering', 'dilution', 'SEC investigation', 'halt', 'lawsuit',
    'downgrade', 'bankruptcy', 'going concern', 'withdraws guidance',
    'secondary offering', 'shelf registration', 'class action',
]

# Gap 9 fix: Critical news triggers auto-close, not just alert
CRITICAL_NEWS_KEYWORDS = [
    'sec halt', 'trading halt', 'bankruptcy', 'going concern',
    'sec investigation', 'fraud', 'class action', 'delisted',
]

DEDUP_MINUTES = 30


def get_open_trades(conn):
    cur = conn.cursor()
    cur.execute("""
        SELECT id, symbol, strategy_id, entry_price, entry_time, shares,
               stop_loss, target_1, dollar_risk, account,
               current_price, unrealized_pnl, r_multiple,
               monitored_at, last_alert_at, stale_flag,
               planned_stop
        FROM paper_trades
        WHERE status = 'open'
        ORDER BY entry_time DESC
    """)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def get_current_price(conn, symbol):
    """Get current price with staleness check. Falls back to Alpaca quote if stale."""
    cur = conn.cursor()
    cur.execute("""
        SELECT price, scanned_at FROM trade_ai_scans
        WHERE symbol = %s ORDER BY scanned_at DESC LIMIT 1
    """, [symbol])
    row = cur.fetchone()
    if row and row[0]:
        price, scanned_at = float(row[0]), row[1]
        # Check freshness — reject if older than 5 minutes
        if scanned_at:
            age_sec = (datetime.now(timezone.utc) - scanned_at.replace(tzinfo=timezone.utc)
                       if scanned_at.tzinfo is None else
                       datetime.now(timezone.utc) - scanned_at).total_seconds()
            if age_sec <= 300:
                return price
            log.warning(f"[{symbol}] Scan price is {age_sec/60:.0f}min old — trying Alpaca quote")
    # Fallback: Alpaca latest trade
    try:
        import os, requests
        _key = os.getenv('ALPACA_API_KEY', '')
        _sec = os.getenv('ALPACA_SECRET_KEY', '')
        if _key:
            r = requests.get(f'https://data.alpaca.markets/v2/stocks/{symbol}/trades/latest',
                             headers={'APCA-API-KEY-ID': _key, 'APCA-API-SECRET-KEY': _sec}, timeout=5)
            if r.status_code == 200:
                p = float(r.json().get('trade', {}).get('p', 0))
                if p > 0:
                    return p
    except Exception as _e:
        log.warning(f"[{symbol}] Alpaca quote fallback failed: {_e}")
    # Last resort: return scan price even if stale
    return float(row[0]) if row and row[0] else None


def check_negative_news(conn, symbol, since):
    cur = conn.cursor()
    cur.execute("""
        SELECT title FROM news_articles
        WHERE symbol = %s AND published_at > %s
        ORDER BY published_at DESC LIMIT 10
    """, [symbol, since])
    headlines = [r[0] for r in cur.fetchall() if r[0]]
    negatives = []
    for h in headlines:
        h_lower = h.lower()
        for kw in NEGATIVE_KEYWORDS:
            if kw.lower() in h_lower:
                negatives.append(h[:120])
                break
    return negatives


def _stop_warning_notify_decision(conn, trade_id, symbol, pct_consumed):
    """Should this STOP_WARNING reach the operator, or is it a repeat?

    A4, 2026-08-31. AES #825 produced 40 alerts over four trading days -- 83% of
    every row in open_trade_alerts -- because `already_alerted` keys on
    (trade_id, alert_type) with a 30-minute window against a 3-minute evaluation
    cadence. That is not a dedupe window; it is a repeat-every-30-minutes
    instruction, for as long as the trade stays in the band.

    Three acknowledgement mechanisms already exist and this producer read none of
    them: `stop_snooze` and `stop_decisions` HOLD_OVERRIDE are both honoured by
    portfolio_stops.py, and open_trade_alerts.acknowledged has never been written
    in 864 rows. The operator's own Hold button wrote to a table nobody consulted.

    Returns (should_notify, reason).
    """
    # 1. Operator acknowledgements -- the same queries portfolio_stops.py uses.
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM stop_snooze WHERE symbol = %s AND snoozed_until > NOW() LIMIT 1",
                    [symbol])
        if cur.fetchone():
            return False, "operator snoozed this symbol"
        cur.execute("""
            SELECT 1 FROM stop_decisions
            WHERE symbol = %s AND decision = 'HOLD_OVERRIDE'
              AND created_at > NOW() - INTERVAL '96 hours' LIMIT 1
        """, [symbol])
        if cur.fetchone():
            return False, "operator chose HOLD_OVERRIDE"
        cur.execute("""
            SELECT 1 FROM open_trade_alerts
            WHERE paper_trade_id = %s AND alert_type = 'STOP_WARNING'
              AND acknowledged IS TRUE LIMIT 1
        """, [trade_id])
        if cur.fetchone():
            return False, "operator acknowledged this warning"
    except Exception as e:
        # Loud, not swallowed: an acknowledgement we cannot read must not be
        # silently treated as absent, but it must also not stop the monitor.
        log.error("stop-warning acknowledgement lookup failed for %s: %s", symbol, e)

    # 2. Transitions notify; unchanged conditions do not.
    try:
        from lib.alert_condition_state import observe
    except ImportError:
        try:
            from scripts.lib.alert_condition_state import observe
        except ImportError as e:
            log.error("alert_condition_state unavailable, falling back to send: %s", e)
            return True, "state machine unavailable"
    band = "warn_band"
    result = observe(f"stop_warning:{trade_id}", band, alertable=True,
                     extra={"symbol": symbol, "pct_consumed": round(pct_consumed, 1)})
    action = result.get("action")
    if result.get("notify"):
        return True, f"state {action}"
    return False, f"state {action} — unchanged since last notification"



def record_send_receipt(conn, alert_id, receipt):
    """Persist what actually happened to a notification.

    B5. open_trade_alerts.sent_telegram was 0 of 864 rows -- the column existed
    and nothing ever wrote it. Without a receipt there is no way to answer "did
    the operator get this?", which is why the 25 repeats could not be traced to a
    producer and why a 98-day delivery outage went unnoticed.

    Best-effort and non-fatal: failing to record a receipt must never stop the
    monitor, but it must be loud, because a silent receipt failure recreates the
    blindness this fixes.
    """
    if not alert_id or not isinstance(receipt, dict):
        return
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE open_trade_alerts SET sent_telegram = %s WHERE id = %s",
            [bool(receipt.get("ok")), alert_id])
    except Exception as e:
        log.error("could not record send receipt for alert %s: %s", alert_id, e)


def already_alerted(conn, trade_id, alert_type):
    cur = conn.cursor()
    cur.execute("""
        SELECT 1 FROM open_trade_alerts
        WHERE paper_trade_id = %s AND alert_type = %s
        AND created_at > NOW() - INTERVAL '%s minutes'
        LIMIT 1
    """, [trade_id, alert_type, DEDUP_MINUTES])
    return cur.fetchone() is not None


def insert_alert(conn, trade_id, symbol, strategy_id, alert_type, severity, title, message, data=None):
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO open_trade_alerts
            (paper_trade_id, symbol, strategy_id, alert_type, severity, title, message, data)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
    """, [trade_id, symbol, strategy_id, alert_type, severity, title, message,
          json.dumps(data) if data else None])
    return cur.fetchone()[0]


def insert_curation_event(conn, trade_id, symbol, strategy_id, agent, event_type, summary, payload=None):
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO agent_curation_events
            (paper_trade_id, symbol, strategy_id, agent_name, event_type, event_summary, payload)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """, [trade_id, symbol, strategy_id, agent, event_type, summary,
          json.dumps(payload) if payload else None])


def send_telegram(message, dry_run=False, no_telegram=False):
    if dry_run or no_telegram:
        log.info(f"[telegram-skip] {message[:100]}")
        return
    # 2026-08-31: this imported `telegram_bot`, a module that does not exist in any
    # tree. The bare `except Exception` caught the ImportError and logged it at
    # warning, so STOP_HIT_CLOSE / TIME_STOP_CLOSE / TRAILING_STOP / NEAR_TARGET
    # were undeliverable from 2026-05-25 to 2026-08-31 -- 581 identical failures,
    # one distinct cause, nobody paged. The operator received 40 copies of the
    # "monitoring" alert (a different sender, which works) and zero copies of
    # "your stop was hit and I closed the position".
    #
    # bypass_router=True is deliberate and measured, not convenience: the router's
    # own should_send_telegram() returns False for a stop-close body, so routing
    # this through the default path would replace a silent failure with a
    # different silent failure that looks fixed.
    try:
        from telegram_alert import send_telegram as _send
    except ImportError as e:
        log.error(
            "STOP-PATH NOTIFICATION UNDELIVERABLE - sender import failed: %s - "
            "message was: %s", e, message[:120])
        return
    if not _send(message, bypass_router=True):
        log.error("STOP-PATH NOTIFICATION NOT DELIVERED: %s", message[:120])
        return
    try:
        from lib.comms import CommunicationEvent, publish_communication
        publish_communication(CommunicationEvent(
            direction="OUTBOUND", event_type="alert", message_class="ops",
            producer="open_trade_monitor", subject_key="ops:open_trade",
            retention_class="operational", severity="urgent",
            sanitized_body=message[:500], short_summary=message[:120],
        ))
    except Exception:
        # ALARM-DELIVERY-DECLARED: shadow ledger best-effort; never blocks operator alert
        pass


def send_telegram_with_buttons(message, buttons, dry_run=False, no_telegram=False):
    """Send stop-path alert with inline keyboard via telegram_alert chokepoint.

    Rebuilds Telegram reply_markup from the buttons list and sends through
    send_telegram(..., reply_markup=...). No producer Bot API / token selection.
    """
    receipt = {"ok": False, "message_id": None, "error": None}
    if dry_run or no_telegram:
        log.info(f"[telegram-skip] {message[:100]} [+buttons]")
        receipt["error"] = "dry_run" if dry_run else "no_telegram"
        return receipt
    try:
        keyboard = None
        if buttons:
            keyboard = {
                "inline_keyboard": [
                    [{"text": str(text), "callback_data": str(cb)} for text, cb in row]
                    for row in buttons
                ]
            }
        from telegram_alert import send_telegram as _send
        ok = bool(_send(message, bypass_router=True, reply_markup=keyboard))
        receipt["ok"] = ok
        if not ok:
            receipt["error"] = "send_telegram_false"
            log.error("STOP-PATH BUTTON ALERT NOT DELIVERED: %s", message[:120])
        try:
            from lib.comms import CommunicationEvent, publish_communication
            publish_communication(CommunicationEvent(
                direction="OUTBOUND", event_type="alert", message_class="ops",
                producer="open_trade_monitor", subject_key="ops:open_trade",
                retention_class="operational", severity="urgent",
                sanitized_body=message[:500], short_summary=message[:120],
            ))
        except Exception:
            # ALARM-DELIVERY-DECLARED: shadow ledger best-effort; never blocks operator alert
            pass
    except Exception as e:
        log.error("send_telegram_with_buttons failed: %s", e)
        receipt["error"] = f"{type(e).__name__}: {e}"
    return receipt


def _log_risk_action(conn, trade_id, symbol, action_type, old_value, new_value, trigger_price, trigger_reason):
    """Log a risk management action to paper_trade_risk_actions."""
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO paper_trade_risk_actions
                (paper_trade_id, symbol, action_type, old_value, new_value, trigger_price, trigger_reason)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, [trade_id, symbol, action_type, old_value, new_value, trigger_price, trigger_reason])
    except Exception as e:
        log.warning(f"Failed to log risk action for {symbol}: {e}")


def _auto_close_position(conn, trade_id, symbol, price, reason, cur):
    """Close position on Alpaca and update DB."""
    try:
        import os, requests
        _key = os.getenv('ALPACA_API_KEY', '')
        _sec = os.getenv('ALPACA_SECRET_KEY', '')
        _headers = {'APCA-API-KEY-ID': _key, 'APCA-API-SECRET-KEY': _sec}
        requests.delete(f'{ALPACA_BASE}/v2/positions/{symbol}',
                        headers=_headers, timeout=10)
        # Determine verdict from actual P&L, not exit reason
        from trade_outcome_helpers import classify_verdict
        _entry = None
        _shares = 0
        _stop = None
        _dollar_risk = None
        _entry_time = None
        try:
            cur.execute("SELECT entry_price, shares, stop_loss, dollar_risk, entry_time, created_at FROM paper_trades WHERE id=%s", [trade_id])
            _r = cur.fetchone()
            if _r:
                _entry = float(_r[0]) if _r[0] else None
                _shares = int(_r[1]) if _r[1] else 0
                _stop = float(_r[2]) if _r[2] else None
                _dollar_risk = float(_r[3]) if _r[3] else None
                _entry_time = _r[4] or _r[5]
        except Exception:
            pass
        _pnl = round((price - _entry) * _shares, 2) if _entry and _shares else None
        _pnl_pct = round((price - _entry) / _entry * 100, 2) if _entry and _entry > 0 else None
        _verdict = classify_verdict(_pnl) if _pnl is not None else 'UNKNOWN'
        _r_mult = None
        if _pnl is not None and _dollar_risk and _dollar_risk > 0:
            _r_mult = round(_pnl / _dollar_risk, 3)
        elif _entry and _stop and abs(_entry - _stop) > 0:
            _r_mult = round((price - _entry) / abs(_entry - _stop), 3)
        _hold_min = None
        if _entry_time:
            try:
                from datetime import datetime as _dt, timezone as _tz
                _now = _dt.now(_tz.utc)
                _et = _entry_time.replace(tzinfo=_tz.utc) if _entry_time.tzinfo is None else _entry_time
                _hold_min = round((_now - _et).total_seconds() / 60, 1)
            except Exception:
                pass
        cur.execute("""UPDATE paper_trades SET status='closed', exit_price=%s,
            exit_reason=%s, closed_at=NOW(), exit_time=COALESCE(exit_time, NOW()), closed_via=%s,
            entry_time=COALESCE(entry_time, filled_at, created_at),
            outcome_verdict=%s, lifecycle_state='closed',
            pnl = COALESCE(%s, pnl),
            pnl_pct = COALESCE(%s, pnl_pct),
            r_multiple = COALESCE(%s, r_multiple),
            hold_time_min = COALESCE(%s, hold_time_min)
            WHERE id=%s""",
            [price, reason, f'auto_{reason}', _verdict, _pnl, _pnl_pct, _r_mult, _hold_min, trade_id])
        log.info(f"[{symbol}] Position auto-closed: reason={reason} at ${price:.2f}")
        # Trigger post-trade analysis pipeline
        try:
            from agent_curation_hooks import on_paper_trade_closed
            on_paper_trade_closed(conn, trade_id)
            log.info(f"[{symbol}] Post-trade analysis pipeline triggered")
        except Exception as _hook_err:
            log.warning(f"[{symbol}] Post-trade hooks failed (non-fatal): {_hook_err}")
    except Exception as e:
        log.error(f"[{symbol}] Auto-close failed: {e}")


def _update_stop_on_alpaca(conn, trade, new_stop):
    """Cancel existing stop order and place new one at updated price."""
    symbol = trade['symbol']
    try:
        import os, requests
        _key = os.getenv('ALPACA_API_KEY', '')
        _sec = os.getenv('ALPACA_SECRET_KEY', '')
        _headers = {'APCA-API-KEY-ID': _key, 'APCA-API-SECRET-KEY': _sec}
        # Get open orders for this symbol
        resp = requests.get(f'{ALPACA_BASE}/v2/orders?status=open&symbols={symbol}',
                            headers=_headers, timeout=10)
        orders = resp.json() if resp.ok else []
        # Cancel existing stop orders
        for o in orders:
            if o.get('type') == 'stop' and o.get('side') == 'sell':
                requests.delete(f'{ALPACA_BASE}/v2/orders/{o["id"]}',
                                headers=_headers, timeout=10)
                log.info(f"[{symbol}] Cancelled old stop order {o['id']}")
        # Place new stop
        shares = int(trade.get('shares', 0))
        if shares > 0:
            new_order = requests.post(f'{ALPACA_BASE}/v2/orders',
                headers=_headers, timeout=10,
                json={'symbol': symbol, 'qty': str(shares), 'side': 'sell',
                      'type': 'stop', 'stop_price': str(new_stop),
                      'time_in_force': 'gtc'})
            if new_order.ok:
                log.info(f"[{symbol}] New stop placed at ${new_stop:.2f}")
            else:
                log.error(f"[{symbol}] Failed to place new stop: {new_order.text}")
    except Exception as e:
        log.error(f"[{symbol}] Stop update failed: {e}")


def monitor_trade(conn, trade, dry_run=False, no_telegram=False):
    """Monitor a single open trade. Returns list of alerts generated."""
    alerts = []
    tid = trade['id']
    symbol = trade['symbol']
    sid = trade['strategy_id']
    entry = float(trade['entry_price'] or 0)
    stop = float(trade['stop_loss'] or 0)
    target = float(trade['target_1'] or 0)
    shares = int(trade['shares'] or 0)
    entry_time = trade['entry_time']

    if entry <= 0:
        return alerts

    # Get current price
    price = get_current_price(conn, symbol)
    if not price:
        return alerts

    # Update current price / unrealized PnL
    pnl = round((price - entry) * shares, 2)
    risk_per_share = abs(entry - stop) if stop else None
    r_mult = round(pnl / (risk_per_share * shares), 2) if risk_per_share and risk_per_share > 0 else None

    cur = conn.cursor()
    cur.execute("""
        UPDATE paper_trades SET current_price=%s, unrealized_pnl=%s,
               pnl=%s, r_multiple=%s, monitored_at=NOW(), updated_at=NOW()
        WHERE id=%s
    """, [price, pnl, pnl, r_mult, tid])

    now = datetime.now(timezone.utc)
    age_hours = (now - entry_time).total_seconds() / 3600 if entry_time else 0

    # ── STOP HIT: Auto-close if price breached stop ──
    if stop > 0 and price <= stop:
        msg = f"STOP HIT: {symbol} at ${price:.2f} breached stop ${stop:.2f} — auto-closing"
        log.critical(msg)
        insert_alert(conn, tid, symbol, sid, 'STOP_HIT_CLOSE', 'CRITICAL',
                     f'{symbol} stop hit', msg, {'price': price, 'stop': stop})
        _log_risk_action(conn, tid, symbol, 'stop_hit_close', stop, price, price,
                         f'Price ${price:.2f} breached stop ${stop:.2f}')
        if not dry_run:
            _auto_close_position(conn, tid, symbol, price, 'stop_hit', cur)
        send_telegram(f"🛑 {msg}", dry_run, no_telegram)
        alerts.append(('STOP_HIT_CLOSE', symbol))
        return alerts  # trade is closed, skip remaining checks

    # ── TARGET HIT: Auto-close if price reached target ──
    if target > 0 and price >= target:
        msg = f"TARGET HIT: {symbol} at ${price:.2f} reached target ${target:.2f} — auto-closing"
        log.info(msg)
        insert_alert(conn, tid, symbol, sid, 'TARGET_HIT_CLOSE', 'INFO',
                     f'{symbol} target hit', msg, {'price': price, 'target': target})
        _log_risk_action(conn, tid, symbol, 'target_hit_close', target, price, price,
                         f'Price ${price:.2f} reached target ${target:.2f}')
        if not dry_run:
            _auto_close_position(conn, tid, symbol, price, 'target_hit', cur)
        send_telegram(f"🎯 {msg}", dry_run, no_telegram)
        alerts.append(('TARGET_HIT_CLOSE', symbol))
        return alerts

    # ── TIME STOP: Auto-close if max hold exceeded ──
    # Dedup: skip if time_stop already attempted in last 30 min
    try:
        cur.execute("""SELECT COUNT(*) FROM paper_trade_risk_actions
            WHERE paper_trade_id=%s AND action_type='time_stop_close'
            AND created_at > NOW()-INTERVAL '30 minutes'""", [tid])
        if cur.fetchone()[0] > 0:
            pass  # skip — already attempted recently
        else:
            time_stop_fire = False
            time_stop_reason = ''
            if sid in INTRADAY_STRATEGIES and entry_time:
                # Intraday: close at 3:45 PM ET, not by day count
                try:
                    import zoneinfo
                    _et = datetime.now(zoneinfo.ZoneInfo('America/New_York'))
                    if _et.hour >= 15 and _et.minute >= 45:
                        time_stop_fire = True
                        time_stop_reason = f'time_stop_intraday_{_et.strftime("%H%M")}'
                except Exception:
                    pass
            elif entry_time:
                max_hold = MAX_HOLD_DAYS.get(sid)
                if max_hold is not None:
                    hold_days = (now - entry_time).total_seconds() / 86400
                    if hold_days >= max_hold:
                        time_stop_fire = True
                        time_stop_reason = f'time_stop_{max_hold}d'

            if time_stop_fire:
                hold_hours = (now - entry_time).total_seconds() / 3600 if entry_time else 0
                msg = (f"TIME STOP: {symbol} closed after {hold_hours:.0f}h "
                       f"({time_stop_reason} for {sid}). P&L: ${pnl:+.2f}")
                log.warning(msg)
                insert_alert(conn, tid, symbol, sid, 'TIME_STOP_CLOSE', 'CRITICAL',
                             f'{symbol} time stop', msg, {'reason': time_stop_reason, 'pnl': pnl})
                _log_risk_action(conn, tid, symbol, 'time_stop_close', stop, price, price, time_stop_reason)
                if not dry_run:
                    _auto_close_position(conn, tid, symbol, price, time_stop_reason, cur)
                send_telegram(f"\u23f0 {msg}", dry_run, no_telegram)
                alerts.append(('TIME_STOP_CLOSE', symbol))
                return alerts
    except Exception as _tse:
        log.warning(f"[{symbol}] Time stop check error: {_tse}")

    # ── TRAILING STOP: 4-tier R-multiple trailing ──
    # Use planned_stop or dollar_risk to recover initial 1R (stop_loss may have been moved)
    initial_stop = float(trade.get('planned_stop') or 0)
    if initial_stop <= 0:
        # Fallback: compute from dollar_risk if planned_stop unavailable
        dr = float(trade.get('dollar_risk') or 0)
        initial_stop = round(entry - (dr / shares), 2) if shares and dr > 0 else stop
    initial_risk = abs(entry - initial_stop) if initial_stop > 0 else (abs(entry - stop) if stop else 0)

    if r_mult is not None and r_mult >= 1.0 and initial_risk > 0 and entry > 0:
        # Determine tier-based stop
        if r_mult >= 3.0:
            new_stop = round(entry + initial_risk * 2.0, 2)
            tier_reason = f"R={r_mult:.1f} >= 3.0R — locking 2.0R profit"
        elif r_mult >= 2.0:
            new_stop = round(entry + initial_risk * 1.0, 2)
            tier_reason = f"R={r_mult:.1f} >= 2.0R — locking 1.0R profit"
        elif r_mult >= 1.5:
            new_stop = round(entry + initial_risk * 0.5, 2)
            tier_reason = f"R={r_mult:.1f} >= 1.5R — locking 0.5R profit"
        else:
            new_stop = round(entry, 2)
            tier_reason = f"R={r_mult:.1f} >= 1.0R — moving to breakeven"

        # Stops only move UP
        if new_stop > stop:
            msg = f"TRAILING STOP: {symbol} {tier_reason}, stop ${stop:.2f} → ${new_stop:.2f}"
            log.info(msg)
            _log_risk_action(conn, tid, symbol, 'trailing_stop_update', stop, new_stop, price,
                             tier_reason)
            cur.execute("UPDATE paper_trades SET stop_loss=%s WHERE id=%s", [new_stop, tid])
            try:
                from stop_change_audit import log_stop_change
                log_stop_change(conn, tid, symbol, stop, new_stop,
                                change_type='trailing_update', source='open_trade_monitor',
                                reason=tier_reason, strategy_id=trade.get('strategy_id'))
            except Exception:
                pass
            if not dry_run:
                _update_stop_on_alpaca(conn, trade, new_stop)
            locked = (new_stop - entry) * shares if new_stop > entry and shares else 0
            strategy = trade.get('strategy_id', '?')
            rich_msg = (
                f"\U0001f4c8 *TRAILING STOP MOVED*\n\n"
                f"*{symbol}* — `{strategy}`\n"
                f"Entry ${entry:.2f}  |  Now ${price:.2f}  |  R: {r_mult:.1f}\n"
                f"Stop: ${stop:.2f} \u2192 *${new_stop:.2f}*\n"
                f"Locked profit: ${locked:,.0f}\n\n"
                f"Trade `#{tid}`\n"
                f"_Automated — no action needed_"
            )
            send_telegram(rich_msg, dry_run, no_telegram)
            alerts.append(('TRAILING_STOP', symbol))
            stop = new_stop

    # ── Near Stop — graduated alerts with action buttons ──
    if stop > 0 and entry > stop:
        stop_dist = entry - stop
        pct_to_stop = ((price - stop) / price * 100) if price > 0 else 999
        pct_consumed = (entry - price) / stop_dist * 100 if stop_dist > 0 else 0

        # CRITICAL: within 25% of stop (75% of risk consumed)
        if price <= entry - 0.75 * stop_dist:
            if not already_alerted(conn, tid, 'NEAR_STOP'):
                pnl_now = (price - entry) * shares if shares else 0
                msg = (
                    f"🔴 *STOP PROXIMITY CRITICAL*\n\n"
                    f"*{symbol}* — `{sid}`\n"
                    f"Entry ${entry:.2f}  |  Now ${price:.2f}  |  Stop ${stop:.2f}\n"
                    f"Distance to stop: {pct_to_stop:.1f}% (${price - stop:.2f})\n"
                    f"P&L: ${pnl_now:+,.0f}  |  Risk consumed: {pct_consumed:.0f}%\n\n"
                    f"Trade `#{tid}` — *action required*"
                )
                alert_id = insert_alert(conn, tid, symbol, sid, 'NEAR_STOP', 'CRITICAL',
                                        f'{symbol} near stop', msg,
                                        {'price': price, 'stop': stop, 'entry': entry,
                                         'pct_to_stop': round(pct_to_stop, 2)})
                insert_curation_event(conn, tid, symbol, sid, 'Risk', 'OPEN_TRADE_ALERT',
                                      msg, {'alert_id': alert_id, 'type': 'NEAR_STOP'})
                buttons = [
                    [("🛑 Stop Out Now", f"stopout:{tid}"),
                     ("📉 Trail 5%", f"trail:{tid}:5")],
                    [("📉 Trail 8%", f"trail:{tid}:8"),
                     ("⏸ Hold", f"stophold:{tid}")],
                ]
                receipt = send_telegram_with_buttons(msg, buttons, dry_run, no_telegram)
                record_send_receipt(conn, alert_id, receipt)
                alerts.append(('NEAR_STOP', symbol))

        # WARNING: within 50% of stop (50% of risk consumed)
        elif price <= entry - 0.50 * stop_dist:
            if not already_alerted(conn, tid, 'STOP_WARNING'):
                pnl_now = (price - entry) * shares if shares else 0
                msg = (
                    f"⚠️ *STOP WARNING*\n\n"
                    f"*{symbol}* — `{sid}`\n"
                    f"Entry ${entry:.2f}  |  Now ${price:.2f}  |  Stop ${stop:.2f}\n"
                    f"Distance to stop: {pct_to_stop:.1f}% (${price - stop:.2f})\n"
                    f"P&L: ${pnl_now:+,.0f}  |  Risk consumed: {pct_consumed:.0f}%\n\n"
                    f"Trade `#{tid}` — monitoring"
                )
                warn_alert_id = insert_alert(
                    conn, tid, symbol, sid, 'STOP_WARNING', 'WARN',
                    f'{symbol} approaching stop', msg,
                    {'price': price, 'stop': stop, 'entry': entry,
                     'pct_to_stop': round(pct_to_stop, 2)})
                buttons = [
                    [("📉 Trail 5%", f"trail:{tid}:5"),
                     ("📉 Trail 8%", f"trail:{tid}:8"),
                     ("⏸ Hold", f"stophold:{tid}")],
                ]
                # The durable row above is always written. Only the operator
                # interrupt is gated -- the record and the notification are
                # different concerns, and conflating them is why the history is
                # 83% one trade's repeats.
                should, why = _stop_warning_notify_decision(conn, tid, symbol, pct_consumed)
                if should:
                    receipt = send_telegram_with_buttons(msg, buttons, dry_run, no_telegram)
                    record_send_receipt(conn, warn_alert_id, receipt)
                    alerts.append(('STOP_WARNING', symbol))
                else:
                    log.info("[stop-warning] %s suppressed: %s", symbol, why)

    # ── Near Target ──
    if target > 0 and entry < target:
        target_dist = target - entry
        if price >= entry + 0.80 * target_dist:
            if not already_alerted(conn, tid, 'NEAR_TARGET'):
                msg = f"NEAR TARGET: {symbol} at ${price:.2f} (target ${target:.2f}, entry ${entry:.2f})"
                alert_id = insert_alert(conn, tid, symbol, sid, 'NEAR_TARGET', 'INFO',
                                        f'{symbol} near target', msg,
                                        {'price': price, 'target': target})
                insert_curation_event(conn, tid, symbol, sid, 'Risk', 'OPEN_TRADE_ALERT',
                                      msg, {'alert_id': alert_id, 'type': 'NEAR_TARGET'})
                send_telegram(f"🟢 {msg}", dry_run, no_telegram)
                alerts.append(('NEAR_TARGET', symbol))

    # ── Stale Trade ──
    if age_hours > 3 and r_mult is not None and abs(r_mult) < 0.5:
        if not already_alerted(conn, tid, 'STALE_TRADE'):
            msg = f"STALE: {symbol} open {age_hours:.1f}h, R={r_mult:.2f}, P&L=${pnl:.2f}"
            insert_alert(conn, tid, symbol, sid, 'STALE_TRADE', 'WARN',
                         f'{symbol} stale', msg,
                         {'age_hours': age_hours, 'r_multiple': r_mult})
            cur.execute("UPDATE paper_trades SET stale_flag=true WHERE id=%s", [tid])
            send_telegram(f"⚠️ {msg}", dry_run, no_telegram)
            alerts.append(('STALE_TRADE', symbol))

    # ── Extended Profit ──
    if r_mult is not None and r_mult >= 1.5:
        if not already_alerted(conn, tid, 'EXTENDED_PROFIT'):
            msg = f"EXTENDED PROFIT: {symbol} at {r_mult:.1f}R (+${pnl:.2f})"
            insert_alert(conn, tid, symbol, sid, 'EXTENDED_PROFIT', 'INFO',
                         f'{symbol} extended', msg,
                         {'r_multiple': r_mult, 'pnl': pnl})
            send_telegram(f"🟢 {msg}", dry_run, no_telegram)
            alerts.append(('EXTENDED_PROFIT', symbol))

    # ── Negative News (Gap 9 fix: auto-close on critical news) ──
    if entry_time:
        neg_headlines = check_negative_news(conn, symbol, entry_time)
        if neg_headlines:
            # Check for CRITICAL news that warrants auto-close
            critical_hits = [h for h in neg_headlines
                             if any(kw in h.lower() for kw in CRITICAL_NEWS_KEYWORDS)]
            if critical_hits and not dry_run:
                msg = f"CRITICAL NEWS AUTO-CLOSE: {symbol}: {critical_hits[0]}"
                log.critical(msg)
                insert_alert(conn, tid, symbol, sid, 'CRITICAL_NEWS_CLOSE', 'CRITICAL',
                             f'{symbol} auto-closed on critical news', msg,
                             {'headlines': critical_hits[:3], 'auto_closed': True})
                insert_curation_event(conn, tid, symbol, sid, 'Risk', 'AUTO_CLOSE_CRITICAL_NEWS',
                                      msg, {'headlines': critical_hits[:3]})
                # Auto-close the position on Alpaca
                try:
                    import os, requests
                    _key = os.getenv('ALPACA_API_KEY', '')
                    _sec = os.getenv('ALPACA_SECRET_KEY', '')
                    _headers = {'APCA-API-KEY-ID': _key, 'APCA-API-SECRET-KEY': _sec}
                    requests.delete(f'{ALPACA_BASE}/v2/positions/{symbol}',
                                    headers=_headers, timeout=10)
                    # Compute PnL and hold time for critical news close
                    _news_pnl = round((price - entry) * shares, 2) if entry and shares else None
                    _news_pnl_pct = round((price - entry) / entry * 100, 2) if entry and entry > 0 else None
                    _news_r = None
                    if _news_pnl is not None and dollar_risk and dollar_risk > 0:
                        _news_r = round(_news_pnl / dollar_risk, 3)
                    elif entry and stop and abs(entry - stop) > 0:
                        _news_r = round((price - entry) / abs(entry - stop), 3)
                    _news_hold = None
                    if entry_time:
                        try:
                            from datetime import datetime as _ndt, timezone as _ntz
                            _news_hold = round((_ndt.now(_ntz.utc) - (entry_time.replace(tzinfo=_ntz.utc) if entry_time.tzinfo is None else entry_time)).total_seconds() / 60, 1)
                        except Exception: pass
                    _news_verdict = 'LOSS' if _news_pnl is not None and _news_pnl < 0 else ('WIN' if _news_pnl and _news_pnl > 0 else 'LOSS')
                    cur.execute("""UPDATE paper_trades SET status='closed', lifecycle_state='closed',
                        exit_price=%s,
                        exit_reason=%s, closed_at=NOW(), exit_time=COALESCE(exit_time, NOW()),
                        entry_time=COALESCE(entry_time, filled_at, created_at),
                        closed_via='auto_close_critical_news',
                        outcome_verdict=%s, notes=COALESCE(notes,'')||%s,
                        pnl = COALESCE(%s, pnl),
                        pnl_pct = COALESCE(%s, pnl_pct),
                        r_multiple = COALESCE(%s, r_multiple),
                        hold_time_min = COALESCE(%s, hold_time_min)
                        WHERE id=%s""",
                        [price, f'critical_news: {critical_hits[0][:100]}',
                         _news_verdict, f' | Auto-closed on critical news: {critical_hits[0][:100]}',
                         _news_pnl, _news_pnl_pct, _news_r, _news_hold, tid])
                    log.info(f"[{symbol}] Position auto-closed on critical news")
                    try:
                        from agent_curation_hooks import on_paper_trade_closed
                        on_paper_trade_closed(conn, tid)
                    except Exception: pass
                except Exception as _ce:
                    log.error(f"[{symbol}] Auto-close failed: {_ce}")
                send_telegram(f"🛑 {msg}", dry_run, no_telegram)
                alerts.append(('CRITICAL_NEWS_CLOSE', symbol))
            elif not already_alerted(conn, tid, 'NEGATIVE_NEWS'):
                msg = f"NEGATIVE NEWS for {symbol}: {neg_headlines[0]}"
                insert_alert(conn, tid, symbol, sid, 'NEGATIVE_NEWS', 'WARN',
                             f'{symbol} negative news', msg,
                             {'headlines': neg_headlines[:3]})
                insert_curation_event(conn, tid, symbol, sid, 'Maria', 'OPEN_TRADE_ALERT',
                                      msg, {'headlines': neg_headlines[:3]})
                send_telegram(f"⚠️ {msg}", dry_run, no_telegram)
                alerts.append(('NEGATIVE_NEWS', symbol))

    # Update last_alert_at if we generated alerts
    if alerts:
        cur.execute("UPDATE paper_trades SET last_alert_at=NOW() WHERE id=%s", [tid])

    return alerts


def run_monitor(dry_run=False, no_telegram=False):
    """Run full monitor cycle on all open paper trades."""
    conn = get_conn()
    try:
        trades = get_open_trades(conn)
        log.info(f"Monitoring {len(trades)} open paper trades")

        all_alerts = []
        for trade in trades:
            try:
                alerts = monitor_trade(conn, trade, dry_run, no_telegram)
                all_alerts.extend(alerts)
            except Exception as e:
                log.error(f"Error monitoring {trade.get('symbol')}: {e}")

        if not dry_run:
            conn.commit()

        # Summary
        critical = sum(1 for a in all_alerts if a[0] in ('NEAR_STOP', 'STOP_HIT_CLOSE', 'CRITICAL_NEWS_CLOSE'))
        warn = sum(1 for a in all_alerts if a[0] in ('STALE_TRADE', 'NEGATIVE_NEWS', 'TRAILING_STOP'))
        info = sum(1 for a in all_alerts if a[0] in ('NEAR_TARGET', 'EXTENDED_PROFIT', 'TARGET_HIT_CLOSE'))

        log.info(f"Monitor complete: {len(trades)} trades, "
                 f"{len(all_alerts)} alerts ({critical} critical, {warn} warn, {info} info)")

        return {
            'trades_monitored': len(trades),
            'alerts': len(all_alerts),
            'critical': critical,
            'warn': warn,
            'info': info,
            'alert_details': all_alerts,
        }
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Open trade monitor")
    parser.add_argument("--dry-run", action="store_true", help="Don't write to DB or send alerts")
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    parser.add_argument("--no-telegram", action="store_true", help="Skip Telegram notifications")
    args = parser.parse_args()

    result = run_monitor(dry_run=args.dry_run, no_telegram=args.no_telegram)
    print(json.dumps(result, indent=2))
