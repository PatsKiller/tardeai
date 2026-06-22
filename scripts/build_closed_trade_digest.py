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

# Exclude bookkeeping-only closes — not real round-trips for operator review
_DIGEST_EXCLUDE_SQL = """
  AND COALESCE(outcome_verdict, '') NOT IN ('PHANTOM', 'CANCELLED')
  AND COALESCE(close_reason, '') NOT LIKE 'phantom%'
  AND COALESCE(exit_reason, '') NOT IN (
      'phantom_no_alpaca_position',
      'revalidation_blocked_never_submitted',
      'broker_submit_blocked_never_filled',
      'auto_cancel_never_submitted',
      'auto_fix_never_filled'
  )
  AND NOT (COALESCE(broker_order_id, '') = '' AND COALESCE(exit_reason, '') LIKE 'phantom%')
"""


def _load_closed_trades(conn, date_filter):
    """Load closed trades, optionally filtered by date."""
    cur = conn.cursor()
    cur.execute("SELECT * FROM paper_trades WHERE status='closed' LIMIT 0")
    cols = [desc[0] for desc in cur.description]

    if date_filter == "today":
        cur.execute(
            f"""SELECT * FROM paper_trades WHERE status='closed' AND closed_at::date = CURRENT_DATE
               {_DIGEST_EXCLUDE_SQL}"""
        )
        rows = cur.fetchall()
        # No silent all-time fallback (2026-06-11): with zero closes today the digest used to report ALL
        # history as if it were today's review — honest empty beats misleading full.
        if not rows:
            return {"status": "ok", "closed_count": 0,
                    "message": "Closed Trade Review -- no trades closed today (nothing to review)."}
    else:
        cur.execute(f"""SELECT * FROM paper_trades WHERE status='closed'
               {_DIGEST_EXCLUDE_SQL}""")
        rows = cur.fetchall()

    return [dict(zip(cols, row)) for row in rows]


def build_digest_message(summary, date_str):
    """Format the digest message from a daily summary."""
    if summary["closed_today_count"] == 0:
        return f"Closed Trade Review -- {date_str}\nNo closed trades today."

    best = summary.get("best_trade") or {}
    worst = summary.get("worst_trade") or {}
    top_lesson = summary.get("top_lesson", "No lesson")[:150]
    top_action = summary.get("top_action_item", "")

    # Build real action items only (no padding)
    review_items = summary.get("trades_needing_review", [])
    actions = []
    if top_action and top_action not in ("No action needed", "No action needed — review P&L and confirm strategy confidence"):
        actions.append(top_action[:80])
    for item in review_items[:2]:
        act = item.get("action", "")
        if act and act != "No action needed":
            actions.append(f"{item.get('symbol', '?')}: {act[:60]}")

    lines = [
        f"Closed Trade Review -- {date_str}",
        f"Closed: {summary['closed_today_count']} | {summary.get('win_loss_summary', 'N/A')}",
        f"P&L: ${summary['total_realized_pnl']} | Avg R: {summary['daily_avg_r']}R",
        "",
        f"Best: {best.get('symbol', '?')} -- {best.get('reason', '?')}",
    ]

    # Only show review item if different from best
    if worst.get("symbol") != best.get("symbol") or worst.get("reason") != best.get("reason"):
        lines.append(f"Review: {worst.get('symbol', '?')} -- {worst.get('reason', '?')}")

    lines += ["", f"Lesson: {top_lesson}"]

    if actions:
        lines += ["", "Actions:"]
        for i, a in enumerate(actions[:3], 1):
            lines.append(f"{i}. {a}")

    lines += ["", "Review: Paper Journal"]

    return "\n".join(lines)


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
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
    if args.output_md:
        Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_md).write_text(f"# Closed Trade Digest\n\nDate: {date_str}\nClosed: {summary['closed_today_count']}\nP&L: ${summary['total_realized_pnl']}\n\n```\n{message}\n```\n")

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
