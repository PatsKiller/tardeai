#!/usr/bin/env python3
"""send_closed_trade_digest.py — Send the closed-trade digest via Telegram.

Modes:
  --dry-run   (default) Build message, classify, report what would happen.
  --send-test Prepend [TEST], send via send_telegram(bypass_router=True).
  --send      Send only if classify_alert returns P1_DIGEST.

Logs delivery to closed_trade_digest_log. No trades, no orders.
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
from dotenv import load_dotenv
load_dotenv(PROJ / ".env")

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))

from db_adapter import _get_conn
from build_closed_trade_digest import run as build_digest_run, build_digest_message
from closed_trade_postmortem_model import build_postmortem, build_daily_summary
from telegram_alert_router import classify_alert, should_send_telegram
from telegram_alert import send_telegram


def _load_closed_trades(conn, date_filter):
    """Load closed trades."""
    cur = conn.cursor()
    cur.execute("SELECT * FROM paper_trades WHERE status='closed' LIMIT 0")
    cols = [desc[0] for desc in cur.description]

    if date_filter == "today":
        cur.execute(
            "SELECT * FROM paper_trades WHERE status='closed' AND closed_at::date = CURRENT_DATE"
        )
        rows = cur.fetchall()
        if not rows:
            cur.execute("SELECT * FROM paper_trades WHERE status='closed'")
            rows = cur.fetchall()
    else:
        cur.execute("SELECT * FROM paper_trades WHERE status='closed'")
        rows = cur.fetchall()

    return [dict(zip(cols, row)) for row in rows]


def _log_delivery(conn, digest_date, route_level, closed_count, action_count,
                  lessons_count, delivery_status, test_mode, message_preview):
    """Log delivery to closed_trade_digest_log."""
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO closed_trade_digest_log (
                digest_date, sent_at, route_level, closed_count,
                action_count, lessons_count, delivery_status,
                test_mode, message_preview
            ) VALUES (%s, NOW(), %s, %s, %s, %s, %s, %s, %s)
        """, (
            digest_date, route_level, closed_count,
            action_count, lessons_count, delivery_status,
            test_mode, message_preview[:500] if message_preview else None,
        ))
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"  [WARN] Failed to log delivery: {e}")


def run(args):
    conn = _get_conn()
    if conn is None:
        print("[ERROR] No database connection available.")
        return {"status": "error", "reason": "no_db_connection"}

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d") if args.date == "today" else args.date

    # Build the digest
    trades = _load_closed_trades(conn, args.date)
    if not trades:
        print("[INFO] No closed trades found.")
        return {"status": "ok", "closed_count": 0}

    postmortems = []
    for trade in trades:
        try:
            pm = build_postmortem(trade)
            postmortems.append(pm)
        except Exception as e:
            if args.verbose:
                print(f"  [WARN] Skipping trade {trade.get('id')}: {e}")

    summary = build_daily_summary(postmortems)
    message = build_digest_message(summary, date_str)

    # Classify
    route_level = classify_alert(message)
    would_send = should_send_telegram(message)
    action_count = len(summary.get("trades_needing_review", []))
    lessons_count = len(postmortems)

    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "date": date_str,
        "closed_count": summary["closed_today_count"],
        "route_level": route_level,
        "would_send": would_send,
        "action_count": action_count,
        "lessons_count": lessons_count,
    }

    if args.mode == "dry_run":
        print(f"[DRY-RUN] Digest ready: {summary['closed_today_count']} trades")
        print(f"  Route level: {route_level}")
        print(f"  Would send: {would_send}")
        print(f"\n{message}\n")
        report["delivery_status"] = "dry_run"

    elif args.mode == "send_test":
        test_message = f"[TEST] {message}"
        print(f"[SEND-TEST] Sending test digest...")
        try:
            ok = send_telegram(test_message, bypass_router=True)
            status = "sent_test" if ok else "failed_test"
            print(f"  Result: {status}")
            report["delivery_status"] = status
            _log_delivery(conn, date_str, route_level, summary["closed_today_count"],
                          action_count, lessons_count, status, True, test_message)
        except Exception as e:
            print(f"  [ERROR] Send failed: {e}")
            report["delivery_status"] = "error"
            _log_delivery(conn, date_str, route_level, summary["closed_today_count"],
                          action_count, lessons_count, "error", True, message)

    elif args.mode == "send":
        if route_level == "P1_DIGEST":
            print(f"[SEND] Sending live digest (route={route_level})...")
            try:
                ok = send_telegram(message)
                status = "sent" if ok else "failed"
                print(f"  Result: {status}")
                report["delivery_status"] = status
                _log_delivery(conn, date_str, route_level, summary["closed_today_count"],
                              action_count, lessons_count, status, False, message)
            except Exception as e:
                print(f"  [ERROR] Send failed: {e}")
                report["delivery_status"] = "error"
                _log_delivery(conn, date_str, route_level, summary["closed_today_count"],
                              action_count, lessons_count, "error", False, message)
        else:
            print(f"[SKIP] Route level is {route_level}, not P1_DIGEST. Not sending.")
            report["delivery_status"] = "skipped_route"
            _log_delivery(conn, date_str, route_level, summary["closed_today_count"],
                          action_count, lessons_count, "skipped_route", False, message)

    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        print(json.dumps(report, indent=2, default=str))
    if args.output_md:
        print(f"\n## Closed Trade Digest Delivery")
        print(f"- Date: {date_str}")
        print(f"- Mode: {args.mode}")
        print(f"- Route: {route_level}")
        print(f"- Status: {report.get('delivery_status', 'n/a')}")

    return report


def main():
    parser = argparse.ArgumentParser(description="Send closed trade digest via Telegram")
    parser.add_argument("--date", default="today", help="Date filter (default: today)")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--dry-run", dest="mode", action="store_const", const="dry_run",
                       help="Preview only (default)")
    group.add_argument("--send-test", dest="mode", action="store_const", const="send_test",
                       help="Send test message with [TEST] prefix")
    group.add_argument("--send", dest="mode", action="store_const", const="send",
                       help="Send live digest if P1_DIGEST")
    parser.set_defaults(mode="dry_run")
    parser.add_argument("--output-json", type=str, help="Output JSON path")
    parser.add_argument("--output-md", type=str, help="Output Markdown path")
    parser.add_argument("--verbose", action="store_true", help="Verbose output")
    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
