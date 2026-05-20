#!/usr/bin/env python3
"""build_closed_trade_digest.py — Build a daily closed-trade digest message.

Loads closed trades, builds postmortems and daily summary, formats a digest message.
Read-only. No trades, no orders.
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))

from db_adapter import _get_conn
from closed_trade_postmortem_model import build_postmortem, build_daily_summary


def _load_closed_trades(conn, date_filter):
    """Load closed trades, optionally filtered by date."""
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


def build_digest_message(summary, date_str):
    """Format the digest message from a daily summary."""
    if summary["closed_today_count"] == 0:
        return f"Closed Trade Review -- {date_str}\nNo closed trades today."

    best = summary.get("best_trade") or {}
    worst = summary.get("worst_trade") or {}
    top_lesson = summary.get("top_lesson", "No lesson")[:120]
    top_action = summary.get("top_action_item", "No action needed")

    # Build action items from trades needing review
    review_items = summary.get("trades_needing_review", [])
    actions = []
    if top_action and top_action != "No action needed":
        actions.append(top_action[:80])
    for item in review_items[:2]:
        action_text = f"{item.get('symbol', '?')}: {item.get('action', 'review')}"
        actions.append(action_text[:80])
    while len(actions) < 3:
        actions.append("No additional action")

    msg = (
        f"Closed Trade Review -- {date_str}\n"
        f"Closed: {summary['closed_today_count']} | {summary.get('win_loss_summary', 'N/A')}\n"
        f"P&L: ${summary['total_realized_pnl']} | Avg R: {summary['daily_avg_r']}R\n"
        f"\n"
        f"Best: {best.get('symbol', '?')} ({best.get('reason', '?')})\n"
        f"Review: {worst.get('symbol', '?')} ({worst.get('reason', '?')})\n"
        f"\n"
        f"Lesson: {top_lesson}\n"
        f"\n"
        f"Actions:\n"
        f"1. {actions[0]}\n"
        f"2. {actions[1]}\n"
        f"3. {actions[2]}\n"
        f"\n"
        f"Dashboard: Paper Journal"
    )
    return msg


def run(args):
    conn = _get_conn()
    if conn is None:
        print("[ERROR] No database connection available.")
        return {"status": "error", "reason": "no_db_connection"}

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d") if args.date == "today" else args.date
    trades = _load_closed_trades(conn, args.date)

    if not trades:
        print("[INFO] No closed trades found.")
        return {"status": "ok", "closed_count": 0, "message": ""}

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

    mode_label = "DRY-RUN" if not args.apply else "APPLY"
    print(f"[{mode_label}] Digest built: {summary['closed_today_count']} trades")
    print(f"\n{message}\n")

    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mode": mode_label.lower().replace("-", "_"),
        "date": date_str,
        "closed_count": summary["closed_today_count"],
        "total_pnl": summary["total_realized_pnl"],
        "avg_r": summary["daily_avg_r"],
        "wins": summary["wins"],
        "losses": summary["losses"],
        "message": message,
        "summary": summary,
    }

    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        print(json.dumps(report, indent=2, default=str))
    if args.output_md:
        print(f"\n## Closed Trade Digest")
        print(f"- Date: {date_str}")
        print(f"- Closed: {summary['closed_today_count']}")
        print(f"- P&L: ${summary['total_realized_pnl']}")
        print(f"```\n{message}\n```")

    return report


def main():
    parser = argparse.ArgumentParser(description="Build closed trade digest message")
    parser.add_argument("--date", default="today", help="Date filter (default: today)")
    parser.add_argument("--format", default="telegram", help="Output format (default: telegram)")
    parser.add_argument("--dry-run", dest="apply", action="store_false", default=False,
                        help="Preview only (default)")
    parser.add_argument("--apply", dest="apply", action="store_true", help="Build and save")
    parser.add_argument("--output-json", type=str, help="Output JSON path")
    parser.add_argument("--output-md", type=str, help="Output Markdown path")
    parser.add_argument("--verbose", action="store_true", help="Verbose output")
    args = parser.parse_args()
    return run(args)


if __name__ == "__main__":
    main()
