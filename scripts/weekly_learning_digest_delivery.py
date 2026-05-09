#!/usr/bin/env python3
"""weekly_learning_digest_delivery.py — Send digest via Telegram.

Usage:
    .venv/bin/python scripts/weekly_learning_digest_delivery.py --latest --dry-run --json
    .venv/bin/python scripts/weekly_learning_digest_delivery.py --digest-id ID --send --json
"""
import argparse, json, os, sys, uuid
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

def _uid(): return f"DEL_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"

def _get_conn():
    from session13_db import get_conn
    return get_conn()


def get_latest_digest(conn, digest_id=None):
    cur = conn.cursor()
    if digest_id:
        cur.execute("SELECT digest_id, period_start, period_end, holdings_value, paper_trades_closed, win_rate, low_sample_size, top_lessons, human_review_items, status FROM weekly_learning_digests WHERE digest_id=%s", [digest_id])
    else:
        cur.execute("SELECT digest_id, period_start, period_end, holdings_value, paper_trades_closed, win_rate, low_sample_size, top_lessons, human_review_items, status FROM weekly_learning_digests ORDER BY created_at DESC LIMIT 1")
    row = cur.fetchone()
    if not row:
        return None
    return {
        "digest_id": row[0], "period_start": str(row[1]), "period_end": str(row[2]),
        "holdings": float(row[3]) if row[3] else 0, "closed_trades": row[4],
        "win_rate": float(row[5]) if row[5] else 0, "low_sample": row[6],
        "lessons": row[7] or [], "review_items": row[8] or [], "status": row[9],
    }


def format_telegram(digest):
    lines = [
        "Weekly Learning Digest",
        f"Period: {digest['period_start']} — {digest['period_end']}",
        f"Safety: PAPER / BLOCKED",
        f"Holdings: ${digest['holdings']:,.0f}",
        f"Closed trades: {digest['closed_trades']}",
        f"Win rate: {digest['win_rate']:.0%}" if digest['win_rate'] else "Win rate: N/A",
    ]
    if digest["low_sample"]:
        lines.append("LOW SAMPLE SIZE — do not act on findings")

    lessons = digest.get("lessons", [])
    if lessons:
        lines.append("\nTop Lessons:")
        for l in lessons[:3]:
            lines.append(f"  - {str(l)[:80]}")

    items = digest.get("review_items", [])
    if items:
        lines.append(f"\nPending reviews: {len(items)}")

    return "\n".join(lines)


def send_telegram(message, dry_run=True):
    if dry_run:
        return {"status": "dry_run", "message_length": len(message)}
    try:
        from telegram_alert import send_telegram as _send
        ok = _send(message)
        return {"status": "sent" if ok else "failed"}
    except Exception as e:
        return {"status": "failed", "error": str(e)}


def record_delivery(conn, digest_id, channel, status, dry_run=True):
    if dry_run:
        return
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO learning_digest_delivery_log (delivery_id, digest_id, channel, status, sent_at)
        VALUES (%s, %s, %s, %s, now())
    """, [_uid(), digest_id, channel, status])
    if status == "sent":
        cur.execute("UPDATE weekly_learning_digests SET delivered_telegram=true WHERE digest_id=%s", [digest_id])
    conn.commit()


def main():
    parser = argparse.ArgumentParser(description="Weekly Learning Digest Delivery")
    parser.add_argument("--digest-id")
    parser.add_argument("--latest", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--send", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    dry_run = not args.send
    conn = _get_conn()
    try:
        digest = get_latest_digest(conn, args.digest_id)
        if not digest:
            out = {"status": "no_digest", "message": "No digest found. Generate one first."}
            print(json.dumps(out, indent=2) if args.json else out["message"])
            return

        msg = format_telegram(digest)
        result = send_telegram(msg, dry_run=dry_run)

        if not dry_run:
            record_delivery(conn, digest["digest_id"], "telegram", result["status"])

        out = {
            "mode": "dry_run" if dry_run else "send",
            "digest_id": digest["digest_id"],
            "delivery_status": result["status"],
            "message_preview": msg[:200],
        }
        if args.json:
            print(json.dumps(out, indent=2, default=str))
        else:
            print(f"Delivery: {result['status']} ({out['mode']})")
            if dry_run:
                print(f"\nPreview:\n{msg}")
    finally:
        conn.close()

if __name__ == "__main__":
    main()
