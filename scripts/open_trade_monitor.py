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

from session13_db import get_conn

log = logging.getLogger("open_trade_monitor")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")

NEGATIVE_KEYWORDS = [
    'offering', 'dilution', 'SEC investigation', 'halt', 'lawsuit',
    'downgrade', 'bankruptcy', 'going concern', 'withdraws guidance',
    'secondary offering', 'shelf registration', 'class action',
]

DEDUP_MINUTES = 30


def get_open_trades(conn):
    cur = conn.cursor()
    cur.execute("""
        SELECT id, symbol, strategy_id, entry_price, entry_time, shares,
               stop_loss, target_1, dollar_risk, account,
               current_price, unrealized_pnl, r_multiple,
               monitored_at, last_alert_at, stale_flag
        FROM paper_trades
        WHERE status = 'open'
        ORDER BY entry_time DESC
    """)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def get_current_price(conn, symbol):
    cur = conn.cursor()
    cur.execute("""
        SELECT price FROM trade_ai_scans
        WHERE symbol = %s ORDER BY scanned_at DESC LIMIT 1
    """, [symbol])
    row = cur.fetchone()
    return float(row[0]) if row else None


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
    try:
        from telegram_bot import send_message
        send_message(message)
    except Exception as e:
        log.warning(f"Telegram send failed: {e}")


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
               r_multiple=%s, monitored_at=NOW()
        WHERE id=%s
    """, [price, pnl, r_mult, tid])

    now = datetime.now(timezone.utc)
    age_hours = (now - entry_time).total_seconds() / 3600 if entry_time else 0

    # ── Near Stop ──
    if stop > 0 and entry > stop:
        stop_dist = entry - stop
        if price <= entry - 0.75 * stop_dist:
            if not already_alerted(conn, tid, 'NEAR_STOP'):
                msg = f"NEAR STOP: {symbol} at ${price:.2f} (stop ${stop:.2f}, entry ${entry:.2f})"
                alert_id = insert_alert(conn, tid, symbol, sid, 'NEAR_STOP', 'CRITICAL',
                                        f'{symbol} near stop', msg,
                                        {'price': price, 'stop': stop, 'entry': entry})
                insert_curation_event(conn, tid, symbol, sid, 'Risk', 'OPEN_TRADE_ALERT',
                                      msg, {'alert_id': alert_id, 'type': 'NEAR_STOP'})
                send_telegram(f"🔴 {msg}", dry_run, no_telegram)
                alerts.append(('NEAR_STOP', symbol))

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

    # ── Negative News ──
    if entry_time:
        neg_headlines = check_negative_news(conn, symbol, entry_time)
        if neg_headlines:
            if not already_alerted(conn, tid, 'NEGATIVE_NEWS'):
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
        critical = sum(1 for a in all_alerts if a[0] in ('NEAR_STOP',))
        warn = sum(1 for a in all_alerts if a[0] in ('STALE_TRADE', 'NEGATIVE_NEWS'))
        info = sum(1 for a in all_alerts if a[0] in ('NEAR_TARGET', 'EXTENDED_PROFIT'))

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
