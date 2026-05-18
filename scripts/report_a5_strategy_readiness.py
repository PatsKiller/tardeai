#!/usr/bin/env python3
"""report_a5_strategy_readiness.py — A-5 observation readiness summary.

Read-only. No strategy activation. No trade creation.

Usage:
    .venv/bin/python scripts/report_a5_strategy_readiness.py --since-date 2026-05-15 --verbose
"""
import argparse, json, sys
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))
from strategy_proof_policy import classify_strategy_proof_status, A5_END_DATE


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
    p = argparse.ArgumentParser(description="A-5 strategy readiness (read-only)")
    p.add_argument("--since-date", default="2026-05-15")
    p.add_argument("--output-json", type=str)
    p.add_argument("--output-md", type=str)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    conn = get_conn()
    cur = conn.cursor()
    now = datetime.now(timezone.utc)
    a5_complete = now.strftime("%Y-%m-%d") >= A5_END_DATE
    elapsed = (now - datetime.fromisoformat(f"{args.since_date}T00:00:00+00:00")).days

    cur.execute("SELECT COUNT(DISTINCT DATE(created_at)) as d FROM paper_trade_proposals WHERE created_at >= %s", [args.since_date])
    market_days = cur.fetchone()["d"]

    cur.execute("""
        SELECT strategy_id, COUNT(*) as proposals,
            COUNT(*) FILTER (WHERE paper_trade_id IS NOT NULL) as trades
        FROM paper_trade_proposals WHERE created_at >= %s
        GROUP BY strategy_id ORDER BY proposals DESC
    """, [args.since_date])
    by_strategy = cur.fetchall()

    cur.execute("""
        SELECT strategy_name, COUNT(*) FILTER (WHERE status='closed') as closed
        FROM paper_trade_lifecycle_outcomes WHERE created_at >= %s
        GROUP BY strategy_name
    """, [args.since_date])
    closed_by = {r["strategy_name"]: r["closed"] for r in cur.fetchall()}

    total_proposals = sum(s["proposals"] for s in by_strategy)
    conn.close()

    strategies = []
    for s in by_strategy:
        closed = closed_by.get(s["strategy_id"], 0)
        proof = classify_strategy_proof_status(
            {"proposal_count": s["proposals"], "closed_count": closed, "lifecycle_linkage_rate": 0.5}, a5_complete)
        strategies.append({
            "strategy_id": s["strategy_id"], "proposals": s["proposals"],
            "trades": s["trades"], "closed": closed,
            "proof_status": proof["proof_status"],
        })

    report = {
        "generated_at": now.isoformat(), "since_date": args.since_date,
        "elapsed_days": elapsed, "market_days": market_days,
        "a5_complete": a5_complete, "a5_end_date": A5_END_DATE,
        "total_proposals": total_proposals,
        "strategies_represented": len(by_strategy),
        "a5_final_review_ready": a5_complete and total_proposals >= 30,
        "strategies": strategies,
    }

    if args.verbose:
        print(f"A-5 Readiness (day {elapsed}, market days {market_days}, A-5 {'COMPLETE' if a5_complete else 'IN PROGRESS'})")
        print(f"  Proposals: {total_proposals}, Strategies: {len(by_strategy)}")
        for s in strategies:
            print(f"  {s['strategy_id']:30s} prop={s['proposals']:3d} closed={s['closed']:2d} [{s['proof_status']}]")
        print(f"  A-5 final review ready: {report['a5_final_review_ready']}")

    if args.output_json:
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
    if args.output_md:
        md = [f"# A-5 Strategy Readiness", f"\nDay {elapsed} | Market days {market_days} | A-5: {'complete' if a5_complete else 'in progress'}",
              f"\nProposals: {total_proposals} | Strategies: {len(by_strategy)}", "",
              "| Strategy | Proposals | Closed | Status |", "|----------|-----------|--------|--------|"]
        for s in strategies:
            md.append(f"| {s['strategy_id']} | {s['proposals']} | {s['closed']} | {s['proof_status']} |")
        Path(args.output_md).write_text("\n".join(md))


if __name__ == "__main__":
    main()
