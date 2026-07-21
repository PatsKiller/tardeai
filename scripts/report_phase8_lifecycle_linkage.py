#!/usr/bin/env python3
"""report_phase8_lifecycle_linkage.py — Read-only lifecycle linkage report.

Reports how proposals flow through simulation, approval, trade, fill, close, outcome.
NO writes. NO mutations. NO orders.

Usage:
    .venv/bin/python scripts/report_phase8_lifecycle_linkage.py --verbose
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
    p = argparse.ArgumentParser(description="Phase 8A lifecycle linkage report (read-only)")
    p.add_argument("--since-days", type=int, default=30)
    p.add_argument("--limit", type=int, default=500)
    p.add_argument("--output-json", type=str)
    p.add_argument("--output-md", type=str)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    conn = get_conn()
    cur = conn.cursor()

    report = {"generated_at": datetime.now(timezone.utc).isoformat(), "linkage": {}}
    L = report["linkage"]

    cur.execute("SELECT COUNT(*) as c FROM paper_trade_proposals")
    L["total_proposals"] = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) as c FROM paper_trade_proposals WHERE paper_trade_id IS NOT NULL")
    L["proposals_linked_to_trade"] = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) as c FROM paper_proposal_approval_audit")
    L["approval_audit_rows"] = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) as c FROM paper_trades")
    L["total_trades"] = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) as c FROM paper_trades WHERE proposal_id IS NOT NULL")
    L["trades_with_proposal_id"] = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) as c FROM paper_trades WHERE broker='tradeai_automated'")
    L["trades_with_alpaca"] = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) as c FROM paper_trades WHERE status='open'")
    L["open_trades"] = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) as c FROM paper_trades WHERE status='closed'")
    L["closed_trades"] = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) as c FROM paper_trades WHERE status='closed' AND exit_reason IS NOT NULL")
    L["closed_with_exit_reason"] = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) as c FROM paper_trades WHERE status='closed' AND pnl IS NOT NULL")
    L["closed_with_pnl"] = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) as c FROM paper_trades WHERE status='closed' AND r_multiple IS NOT NULL")
    L["closed_with_r_multiple"] = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) as c FROM journal_trade_reviews")
    L["journal_reviews"] = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) as c FROM llm_feedback_observations")
    L["feedback_observations"] = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) as c FROM decision_outcomes")
    L["decision_outcomes"] = cur.fetchone()["c"]

    # Gaps
    L["proposals_without_trade"] = L["total_proposals"] - L["proposals_linked_to_trade"]
    L["trades_without_proposal"] = L["total_trades"] - L["trades_with_proposal_id"]
    L["closed_without_exit_reason"] = L["closed_trades"] - L["closed_with_exit_reason"]

    conn.close()

    if args.verbose:
        print("Phase 8A Lifecycle Linkage Report")
        print("=" * 50)
        for k, v in L.items():
            print(f"  {k}: {v}")

    if args.output_json:
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
    if args.output_md:
        md = ["# Phase 8A Lifecycle Linkage Report", "",
              "| Metric | Count |", "|--------|-------|"]
        for k, v in L.items():
            md.append(f"| {k} | {v} |")
        Path(args.output_md).write_text("\n".join(md))


if __name__ == "__main__":
    main()
