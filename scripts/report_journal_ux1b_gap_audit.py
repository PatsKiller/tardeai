#!/usr/bin/env python3
"""report_journal_ux1b_gap_audit.py — Audit JOURNAL-UX-1 gaps for operator action dashboard.

Read-only. No trades. No orders.
"""
import argparse, json, sys
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))

from closed_trade_postmortem_model import build_postmortem

GENERIC_LESSONS = ["review", "check stop distance", "strategy followed"]


def main():
    p = argparse.ArgumentParser(description="JOURNAL-UX-1B gap audit (read-only)")
    p.add_argument("--date", type=str, default="today")
    p.add_argument("--output-json", type=str)
    p.add_argument("--output-md", type=str)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    from db_adapter import _get_conn
    conn = _get_conn()
    if not conn:
        print("ERROR: no DB connection")
        sys.exit(1)

    cur = conn.cursor()
    if args.date == "today":
        cur.execute("""SELECT * FROM paper_trades WHERE status='closed' ORDER BY closed_at DESC""")
    else:
        cur.execute("""SELECT * FROM paper_trades WHERE status='closed' AND closed_at::date = %s ORDER BY closed_at DESC""", [args.date])

    cols = [d[0] for d in cur.description]
    trades = [dict(zip(cols, r)) for r in cur.fetchall()]
    conn.close()

    postmortems = [build_postmortem(t) for t in trades]

    wins = [pm for pm in postmortems if pm["verdict"] == "WIN"]
    losses = [pm for pm in postmortems if pm["verdict"] == "LOSS"]
    total_pnl = sum(pm["pnl"] for pm in postmortems)
    avg_r = sum(pm["r_multiple"] for pm in postmortems) / max(len(postmortems), 1)

    best = max(postmortems, key=lambda x: x["pnl"]) if postmortems else None
    worst = min(postmortems, key=lambda x: x["pnl"]) if postmortems else None

    generic_count = sum(1 for pm in postmortems
                        if any(g in pm["one_line_lesson"].lower() for g in GENERIC_LESSONS)
                        or len(pm["one_line_lesson"]) < 20)
    missing_confidence = sum(1 for pm in postmortems if pm.get("strategy_confidence_impact") in (None, ""))
    missing_action = sum(1 for pm in postmortems if pm.get("operator_action") in (None, "", "no_action"))
    needs_review = sum(1 for pm in postmortems if pm["followup_required"])

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "date": args.date,
        "closed_trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "realized_pnl": round(total_pnl, 2),
        "avg_r": round(avg_r, 2),
        "best_trade": {"symbol": best["symbol"], "pnl": best["pnl"], "reason": best["exit_reason"]} if best else None,
        "worst_trade": {"symbol": worst["symbol"], "pnl": worst["pnl"], "reason": worst["exit_reason"]} if worst else None,
        "generic_lessons_count": generic_count,
        "specific_lessons_count": len(postmortems) - generic_count,
        "missing_operator_actions": missing_action,
        "missing_confidence_impact": missing_confidence,
        "needs_review_count": needs_review,
        "gaps": {
            "no_daily_summary_cards": True,
            "no_best_worst_trade_highlight": True,
            "no_action_queue": True,
            "no_mistake_classification": True,
            "no_rule_feedback": True,
            "generic_lessons": generic_count > 0,
            "no_confidence_delta_visible": True,
            "narrative_above_summary": True,
        },
    }

    if args.verbose:
        print(f"JOURNAL-UX-1B Gap Audit")
        print(f"  Closed: {len(trades)} | Wins: {len(wins)} | Losses: {len(losses)}")
        print(f"  P&L: ${total_pnl:.2f} | Avg R: {avg_r:.2f}")
        if best: print(f"  Best: {best['symbol']} ${best['pnl']:.2f}")
        if worst: print(f"  Worst: {worst['symbol']} ${worst['pnl']:.2f}")
        print(f"  Generic lessons: {generic_count}/{len(postmortems)}")
        print(f"  Missing actions: {missing_action}")
        print(f"  Needs review: {needs_review}")

    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
    if args.output_md:
        Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
        md = [
            "# JOURNAL-UX-1B Gap Audit\n",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Closed trades | {len(trades)} |",
            f"| Wins | {len(wins)} |",
            f"| Losses | {len(losses)} |",
            f"| Realized P&L | ${total_pnl:.2f} |",
            f"| Avg R | {avg_r:.2f} |",
            f"| Generic lessons | {generic_count} |",
            f"| Missing actions | {missing_action} |",
            f"| Needs review | {needs_review} |",
        ]
        Path(args.output_md).write_text("\n".join(md))


if __name__ == "__main__":
    main()
