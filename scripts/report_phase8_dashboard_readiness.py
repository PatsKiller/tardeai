#!/usr/bin/env python3
"""report_phase8_dashboard_readiness.py — Phase 8C dashboard readiness report.

Read-only. No mutations. No order submission.

Usage:
    .venv/bin/python scripts/report_phase8_dashboard_readiness.py --verbose
"""
import argparse, json, sys
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent


def get_conn():
    import psycopg2, psycopg2.extras
    env = {}
    for line in (PROJ / ".env").read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return psycopg2.connect(host=env.get("DB_HOST", "localhost"), dbname=env.get("DB_NAME", "trade_ai"),
                            user=env.get("DB_USER", "trade_ai"), password=env.get("DB_PASSWORD", ""),
                            cursor_factory=psycopg2.extras.RealDictCursor)


def main():
    p = argparse.ArgumentParser(description="Phase 8C dashboard readiness (read-only)")
    p.add_argument("--since-days", type=int, default=30)
    p.add_argument("--limit", type=int, default=100)
    p.add_argument("--output-json", type=str)
    p.add_argument("--output-md", type=str)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    conn = get_conn()
    cur = conn.cursor()

    # Lifecycle summary
    cur.execute("SELECT COUNT(*) as total FROM paper_trade_lifecycle_outcomes")
    total = cur.fetchone()["total"]
    cur.execute("SELECT status, COUNT(*) as c FROM paper_trade_lifecycle_outcomes GROUP BY status")
    by_status = {r["status"]: r["c"] for r in cur.fetchall()}
    cur.execute("SELECT confidence, COUNT(*) as c FROM paper_trade_lifecycle_outcomes GROUP BY confidence")
    by_conf = {r["confidence"]: r["c"] for r in cur.fetchall()}
    cur.execute("SELECT COUNT(*) as c FROM paper_trade_lifecycle_outcomes WHERE requires_human_review=true")
    review_count = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) as c FROM paper_trade_lifecycle_outcomes WHERE mfe_pct IS NOT NULL")
    mfe_count = cur.fetchone()["c"]

    # Scorecards
    cur.execute("SELECT strategy_name, closed_count, win_rate, avg_r_multiple, total_pnl, sample_quality, recommendation, recommendation_status FROM paper_strategy_scorecards ORDER BY closed_count DESC")
    scorecards = cur.fetchall()

    # Review queue
    cur.execute("""SELECT symbol, strategy_name, paper_trade_id, proposal_id, outcome_label, confidence
        FROM paper_trade_lifecycle_outcomes WHERE requires_human_review=true ORDER BY created_at DESC LIMIT %s""", [args.limit])
    review_queue = cur.fetchall()

    # Gaps
    cur.execute("SELECT COUNT(*) as c FROM paper_trade_lifecycle_outcomes WHERE proposal_id IS NULL AND status='closed'")
    missing_proposal = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) as c FROM paper_trade_lifecycle_outcomes WHERE close_reason IS NULL AND status='closed'")
    missing_close_reason = cur.fetchone()["c"]

    conn.close()

    # A-5 status
    a5_end = "2026-05-22"
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    a5_complete = now_str >= a5_end
    scoring_status = "usable" if a5_complete and by_status.get("closed", 0) >= 20 else "preliminary" if by_status.get("closed", 0) >= 5 else "insufficient"

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "lifecycle_summary": {"total": total, "by_status": by_status, "by_confidence": by_conf,
                              "requires_human_review": review_count, "mfe_mae_coverage": mfe_count},
        "strategy_scorecards": [dict(s) for s in scorecards],
        "review_queue_count": len(review_queue),
        "lifecycle_gaps": {"missing_proposal_link": missing_proposal, "missing_close_reason": missing_close_reason},
        "a5_status": {"complete": a5_complete, "target_end": a5_end, "current_date": now_str},
        "scoring_status": scoring_status,
        "safety": {"strategy_activation_changed": False, "trades_created": False, "orders_submitted": False},
    }

    if args.verbose:
        print("Phase 8C Dashboard Readiness")
        print("=" * 50)
        print(f"  Outcomes: {total} (closed={by_status.get('closed',0)}, open={by_status.get('open',0)}, cancelled={by_status.get('cancelled',0)})")
        print(f"  Confidence: {by_conf}")
        print(f"  Pending review: {review_count}")
        print(f"  MFE/MAE coverage: {mfe_count}/{total}")
        print(f"  A-5 complete: {a5_complete} (target {a5_end})")
        print(f"  Scoring status: {scoring_status}")
        print(f"  Scorecards: {len(scorecards)}")
        for s in scorecards:
            print(f"    {s['strategy_name']:30s} closed={s['closed_count']} WR={s['win_rate']} R={s['avg_r_multiple']} [{s['sample_quality']}]")
        print(f"  Gaps: missing_proposal={missing_proposal}, missing_close_reason={missing_close_reason}")

    if args.output_json:
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
    if args.output_md:
        md = [f"# Phase 8C Dashboard Readiness", f"\n**Scoring:** {scoring_status} | **A-5:** {'complete' if a5_complete else 'in progress'}",
              f"\n## Lifecycle: {total} outcomes ({by_status.get('closed',0)} closed)",
              f"\n## Scorecards ({len(scorecards)} strategies)", "",
              "| Strategy | Closed | WR | Avg R | PnL | Quality |", "|----------|--------|-----|-------|-----|---------|"]
        for s in scorecards:
            md.append(f"| {s['strategy_name']} | {s['closed_count']} | {s['win_rate']} | {s['avg_r_multiple']} | {s['total_pnl']} | {s['sample_quality']} |")
        md.append(f"\n## Review Queue: {review_count} pending")
        Path(args.output_md).write_text("\n".join(md))


if __name__ == "__main__":
    main()
