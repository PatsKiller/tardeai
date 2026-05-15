#!/usr/bin/env python3
"""report_phase6_approval_audit.py — Summarize paper proposal approval audit trail.

Usage:
    .venv/bin/python scripts/report_phase6_approval_audit.py --since-days 7 --verbose
    .venv/bin/python scripts/report_phase6_approval_audit.py --proposal-id 123
    .venv/bin/python scripts/report_phase6_approval_audit.py --output-json results.json --output-md report.md
"""
import argparse, json, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent


def get_conn():
    import psycopg2
    env = {}
    for line in (PROJ / ".env").read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return psycopg2.connect(host=env.get("DB_HOST", "localhost"), dbname=env.get("DB_NAME", "trade_ai"),
                            user=env.get("DB_USER", "trade_ai"), password=env.get("DB_PASSWORD", ""))


def main():
    p = argparse.ArgumentParser(description="Summarize approval audit trail")
    p.add_argument("--since-days", type=int, default=7)
    p.add_argument("--proposal-id", type=int)
    p.add_argument("--symbol", type=str)
    p.add_argument("--status", type=str)
    p.add_argument("--limit", type=int, default=100)
    p.add_argument("--output-json", type=str)
    p.add_argument("--output-md", type=str)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    conn = get_conn()
    cur = conn.cursor()

    # Build query
    conditions = [f"created_at >= NOW() - INTERVAL '{args.since_days} days'"]
    params = []
    if args.proposal_id:
        conditions.append("proposal_id = %s")
        params.append(args.proposal_id)
    if args.symbol:
        conditions.append("symbol = %s")
        params.append(args.symbol)
    if args.status:
        conditions.append("approval_status = %s")
        params.append(args.status)

    where = " AND ".join(conditions)

    # Summary counts
    cur.execute(f"""
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE approval_status = 'approved_paper_submitted') AS approved,
            COUNT(*) FILTER (WHERE approval_status LIKE 'blocked%%') AS blocked,
            COUNT(*) FILTER (WHERE approval_status = 'blocked_session') AS blocked_session,
            COUNT(*) FILTER (WHERE approval_status = 'blocked_market_revalidation') AS blocked_reval,
            COUNT(*) FILTER (WHERE approval_status = 'blocked_risk_gate') AS blocked_risk,
            COUNT(*) FILTER (WHERE approval_status = 'error_fail_closed') AS errors,
            ROUND(AVG(quote_age_minutes)::numeric, 1) AS avg_quote_age,
            ROUND(AVG(spread_pct)::numeric, 2) AS avg_spread,
            ROUND(AVG(CASE WHEN rr_at_approval > 0 THEN rr_at_approval END)::numeric, 2) AS avg_rr,
            COUNT(DISTINCT symbol) AS unique_symbols
        FROM paper_proposal_approval_audit WHERE {where}
    """, params)
    cols = [d[0] for d in cur.description]
    row = cur.fetchone()
    summary = dict(zip(cols, row)) if row else {}

    # Top block reasons
    cur.execute(f"""
        SELECT block_reason, COUNT(*) AS cnt
        FROM paper_proposal_approval_audit WHERE {where} AND block_reason IS NOT NULL
        GROUP BY block_reason ORDER BY cnt DESC LIMIT 10
    """, params)
    block_reasons = [{"reason": r[0], "count": r[1]} for r in cur.fetchall()]

    # Recent attempts
    cur.execute(f"""
        SELECT id, created_at, proposal_id, symbol, approval_status, block_reason,
               live_price, rr_at_approval, spread_pct, gate_sequence,
               passed_session_gate, passed_market_revalidation, passed_risk_gate,
               paper_trade_created, alpaca_submitted, alpaca_mode
        FROM paper_proposal_approval_audit WHERE {where}
        ORDER BY created_at DESC LIMIT %s
    """, params + [args.limit])
    recent_cols = [d[0] for d in cur.description]
    recent = [dict(zip(recent_cols, r)) for r in cur.fetchall()]

    # Safety check
    cur.execute(f"""
        SELECT COUNT(*) FILTER (WHERE alpaca_mode != 'paper' OR alpaca_mode IS NULL) AS non_paper,
               COUNT(*) FILTER (WHERE live_trading_enabled = TRUE) AS live_enabled
        FROM paper_proposal_approval_audit WHERE {where}
    """, params)
    safety_row = cur.fetchone()
    safety = {"non_paper_mode_count": safety_row[0], "live_trading_enabled_count": safety_row[1]}

    conn.close()

    report = {
        "date": datetime.now().isoformat(),
        "since_days": args.since_days,
        "summary": summary,
        "top_block_reasons": block_reasons,
        "safety": safety,
        "recent_count": len(recent),
        "recent": recent,
    }

    if args.verbose:
        print(f"Approval Audit Summary (last {args.since_days} days)")
        print("=" * 50)
        for k, v in summary.items():
            print(f"  {k}: {v}")
        if block_reasons:
            print(f"\nTop block reasons:")
            for br in block_reasons:
                print(f"  {br['count']}x — {br['reason'][:80]}")
        print(f"\nSafety: {safety}")
        if recent:
            print(f"\nRecent {len(recent)} attempts:")
            for r in recent[:10]:
                print(f"  #{r['id']} [{r['approval_status']}] {r['symbol']} "
                      f"gates={r['gate_sequence']} price={r['live_price']}")

    if args.output_json:
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
        if args.verbose:
            print(f"\nJSON: {args.output_json}")

    if args.output_md:
        md = [
            f"# Approval Audit Summary — Last {args.since_days} Days",
            f"\n**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            f"\n## Counts\n",
            f"| Metric | Value |",
            f"|--------|-------|",
        ]
        for k, v in summary.items():
            md.append(f"| {k} | {v} |")
        if block_reasons:
            md.extend([f"\n## Top Block Reasons\n", "| Reason | Count |", "|--------|-------|"])
            for br in block_reasons:
                md.append(f"| {br['reason'][:60]} | {br['count']} |")
        md.extend([f"\n## Safety\n", f"- Non-paper mode: {safety['non_paper_mode_count']}",
                   f"- Live trading enabled: {safety['live_trading_enabled_count']}"])
        Path(args.output_md).write_text("\n".join(md))
        if args.verbose:
            print(f"MD: {args.output_md}")


if __name__ == "__main__":
    main()
