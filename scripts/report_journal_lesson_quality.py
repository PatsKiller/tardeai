#!/usr/bin/env python3
"""report_journal_lesson_quality.py — Audit lesson quality from postmortem model.

Read-only. No trades. No orders.
"""
import argparse, json, sys
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))

from closed_trade_postmortem_model import build_postmortem, build_daily_summary

GENERIC_PATTERNS = ["review", "check stop distance", "strategy followed", "no action needed"]


def main():
    p = argparse.ArgumentParser(description="Lesson quality audit (read-only)")
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
    cur.execute("SELECT * FROM paper_trades WHERE status='closed' ORDER BY closed_at DESC")
    cols = [d[0] for d in cur.description]
    trades = [dict(zip(cols, r)) for r in cur.fetchall()]
    conn.close()

    postmortems = [build_postmortem(t) for t in trades]
    summary = build_daily_summary(postmortems)

    generic = [pm for pm in postmortems
               if any(g == pm["improved_lesson"].lower().strip() for g in GENERIC_PATTERNS)
               or len(pm["improved_lesson"]) < 30]
    missing_action = [pm for pm in postmortems if pm["action_priority"] == "none" and pm["followup_required"]]
    missing_confidence = [pm for pm in postmortems if pm["confidence_delta"] in (None, "")]

    by_category = {}
    for pm in postmortems:
        by_category.setdefault(pm["lesson_category"], []).append(pm)

    by_strategy = {}
    for pm in postmortems:
        by_strategy.setdefault(pm["strategy"], []).append(pm)

    top_actions = [pm["next_operator_action"] for pm in postmortems if pm["action_priority"] in ("high", "urgent", "medium")][:5]

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_lessons": len(postmortems),
        "generic_lessons_count": len(generic),
        "specific_lessons_count": len(postmortems) - len(generic),
        "missing_action_count": len(missing_action),
        "missing_confidence_count": len(missing_confidence),
        "by_category": {k: len(v) for k, v in by_category.items()},
        "by_strategy": {k: {"count": len(v), "avg_r": round(sum(x["r_multiple"] for x in v) / len(v), 2)} for k, v in by_strategy.items()},
        "top_5_actions": top_actions,
        "repeated_patterns": summary.get("repeated_failure_patterns", []),
    }

    if args.verbose:
        print(f"Lesson Quality Report")
        print(f"  Total: {len(postmortems)} | Generic: {len(generic)} | Specific: {len(postmortems) - len(generic)}")
        print(f"  Missing action: {len(missing_action)} | Missing confidence: {len(missing_confidence)}")
        print(f"  Categories: {report['by_category']}")
        for a in top_actions[:3]:
            print(f"  Action: {a[:80]}")

    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
    if args.output_md:
        Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
        md = [
            "# Lesson Quality Report\n",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Total lessons | {len(postmortems)} |",
            f"| Generic | {len(generic)} |",
            f"| Specific | {len(postmortems) - len(generic)} |",
            f"| Missing action | {len(missing_action)} |",
            f"| Missing confidence | {len(missing_confidence)} |",
        ]
        Path(args.output_md).write_text("\n".join(md))


if __name__ == "__main__":
    main()
