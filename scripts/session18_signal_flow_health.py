#!/usr/bin/env python3
"""session18_signal_flow_health.py — Signal flow health monitor.

Detects when GO/A+ scans fail to become strategy_signals.

Usage:
    .venv/bin/python scripts/session18_signal_flow_health.py --today
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

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

log = logging.getLogger("signal_flow_health")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")


def get_conn():
    import psycopg2
    password = os.getenv("DB_PASSWORD")
    if not password:
        raise RuntimeError("DB_PASSWORD missing from .env")
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "trade_ai"),
        user=os.getenv("DB_USER", "trade_ai"),
        password=password,
    )


def check_health(conn):
    cur = conn.cursor()

    # GO/A+ count today
    cur.execute("""
        SELECT COUNT(DISTINCT symbol) FROM trade_ai_scans
        WHERE decision IN ('GO', 'A+')
        AND (scanned_at AT TIME ZONE 'America/New_York')::date =
            (NOW() AT TIME ZONE 'America/New_York')::date
    """)
    go_count = cur.fetchone()[0] or 0

    # strategy_signals count today
    cur.execute("""
        SELECT COUNT(DISTINCT symbol) FROM strategy_signals
        WHERE fired_at::date = CURRENT_DATE
        AND status IN ('active', 'pending', 'PENDING', 'ACTIVE')
    """)
    signal_count = cur.fetchone()[0] or 0

    if go_count == 0:
        status = "NO_GO_TODAY"
    elif signal_count == 0:
        status = "CRITICAL"
    elif signal_count < go_count * 0.5:
        status = "WARN"
    else:
        status = "OK"

    result = {
        "go_count": go_count,
        "signal_count": signal_count,
        "status": status,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }

    # Write audit
    try:
        cur.execute("""
            INSERT INTO signal_flow_audit
                (run_label, run_date, source_component,
                 go_count, strategy_signals_after, status, details)
            VALUES ('health_check', CURRENT_DATE, 'signal_flow_health',
                    %s, %s, %s, %s)
        """, [go_count, signal_count, status, json.dumps(result)])
        conn.commit()
    except Exception as e:
        log.warning(f"Audit write failed: {e}")
        try: conn.rollback()
        except: pass

    # Alert if critical
    if status == "CRITICAL":
        msg = f"CRITICAL: {go_count} GO/A+ scans but 0 strategy_signals. Strategy Desk is empty!"
        log.error(msg)
        try:
            # send_telegram, NOT send_alert -- `send_alert` has never existed in
            # telegram_alert.py, so this dedicated signal-flow alarm raised ImportError
            # into `except Exception: pass` and reported a CRITICAL to nobody, silently,
            # for the whole 24-day Strategy Desk outage.
            from telegram_alert import send_telegram
            if not send_telegram(msg):
                log.error("ALERT NOT DELIVERED (send_telegram returned False): %s", msg)
        except Exception as exc:
            # ALARM-DELIVERY-DECLARED: logs the exception type and message rather than
            # recording to a durable surface. This is the handler that swallowed an
            # ImportError for 24 days; naming the failure is the fix that mattered.
            # Durable recording (signal_flow_audit delivery column) is remaining debt,
            # tracked in the C3 baseline rather than silently accepted.
            log.error("ALERT NOT DELIVERED (%s: %s): %s", type(exc).__name__, exc, msg)
    elif status == "WARN":
        msg = f"WARNING: {go_count} GO/A+ scans but only {signal_count} strategy_signals."
        log.warning(msg)

    log.info(f"Signal flow health: {status} (GO={go_count}, signals={signal_count})")
    return result


def main():
    parser = argparse.ArgumentParser(description="Signal flow health monitor")
    parser.add_argument("--today", action="store_true")
    args = parser.parse_args()

    conn = get_conn()
    try:
        result = check_health(conn)
        print(json.dumps(result, indent=2))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
