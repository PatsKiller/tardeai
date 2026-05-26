#!/usr/bin/env python3
"""report_strategy_sample_size_governance.py — Prevent premature strategy conclusions.

Read-only. No strategy activation changes. No auto-apply.

Usage:
    .venv/bin/python scripts/report_strategy_sample_size_governance.py --verbose
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
    p = argparse.ArgumentParser(description="Strategy sample-size governance (read-only)")
    p.add_argument("--since-days", type=int, default=30)
    p.add_argument("--min-closed-trades", type=int, default=20)
    p.add_argument("--output-json", type=str)
    p.add_argument("--output-md", type=str)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    conn = get_conn()
    cur = conn.cursor()

    a5_end = "2026-05-22"
    a5_complete = datetime.now(timezone.utc).strftime("%Y-%m-%d") >= a5_end

    cur.execute("""
        SELECT strategy_name,
            COUNT(*) FILTER (WHERE status='closed') as closed,
            COUNT(*) FILTER (WHERE status='open') as open,
            COUNT(*) as total,
            ROUND(AVG(r_multiple) FILTER (WHERE status='closed' AND r_multiple IS NOT NULL)::numeric, 3) as avg_r
        FROM paper_trade_lifecycle_outcomes
        WHERE created_at > NOW() - INTERVAL '%s days'
        GROUP BY strategy_name ORDER BY closed DESC
    """, [args.since_days])
    strategies = cur.fetchall()
    conn.close()

    results = []
    for s in strategies:
        closed = s["closed"]
        readiness = "insufficient" if closed < 5 else "observing" if closed < args.min_closed_trades else ("decision_ready" if a5_complete else "review_ready")
        blocked = not a5_complete or closed < args.min_closed_trades
        reason = []
        if not a5_complete:
            reason.append("A-5 incomplete")
        if closed < args.min_closed_trades:
            reason.append(f"only {closed}/{args.min_closed_trades} closed trades")
        results.append({
            "strategy": s["strategy_name"], "closed": closed, "open": s["open"], "total": s["total"],
            "avg_r": float(s["avg_r"]) if s["avg_r"] else None,
            "readiness": readiness, "conclusion_blocked": blocked,
            "reason": "; ".join(reason) if reason else "sufficient",
        })

    if args.verbose:
        print(f"Strategy Sample Governance (A-5 complete: {a5_complete})")
        for r in results:
            icon = "✗" if r["conclusion_blocked"] else "✓"
            print(f"  {icon} {r['strategy']:30s} closed={r['closed']} [{r['readiness']}] {r['reason']}")

    report = {"generated_at": datetime.now(timezone.utc).isoformat(), "a5_complete": a5_complete,
              "min_closed_trades": args.min_closed_trades, "strategies": results}
    if args.output_json:
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
    if args.output_md:
        md = [f"# Strategy Sample Governance", f"\nA-5: {'complete' if a5_complete else 'in progress'} | Min trades: {args.min_closed_trades}", "",
              "| Strategy | Closed | Readiness | Blocked | Reason |", "|----------|--------|-----------|---------|--------|"]
        for r in results:
            md.append(f"| {r['strategy']} | {r['closed']} | {r['readiness']} | {'YES' if r['conclusion_blocked'] else 'no'} | {r['reason']} |")
        Path(args.output_md).write_text("\n".join(md))


if __name__ == "__main__":
    main()
