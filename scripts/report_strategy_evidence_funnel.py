#!/usr/bin/env python3
"""report_strategy_evidence_funnel.py — Strategy proof funnel: proposal→close.

Read-only. No mutations. No strategy activation. No order submission.

Usage:
    .venv/bin/python scripts/report_strategy_evidence_funnel.py --verbose
"""
import argparse, json, sys
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))
from strategy_proof_policy import classify_strategy_proof_status, summarize_strategy_blockers, A5_END_DATE


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
    p = argparse.ArgumentParser(description="Strategy evidence funnel (read-only)")
    p.add_argument("--since-days", type=int, default=30)
    p.add_argument("--output-json", type=str)
    p.add_argument("--output-md", type=str)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    conn = get_conn()
    cur = conn.cursor()
    now = datetime.now(timezone.utc)
    a5_complete = now.strftime("%Y-%m-%d") >= A5_END_DATE

    # Proposals by strategy
    cur.execute("""
        SELECT strategy_id,
            COUNT(*) as proposal_count,
            COUNT(*) FILTER (WHERE status IN ('APPROVED','APPROVED_FOR_PAPER_TEST')) as approved_count,
            COUNT(*) FILTER (WHERE paper_trade_id IS NOT NULL) as linked_to_trade
        FROM paper_trade_proposals
        WHERE created_at > NOW() - INTERVAL '%s days'
        GROUP BY strategy_id ORDER BY proposal_count DESC
    """, [args.since_days])
    proposal_data = {r["strategy_id"]: r for r in cur.fetchall()}

    # Approval audit blocks
    cur.execute("""
        SELECT symbol, approval_status, COUNT(*) as c
        FROM paper_proposal_approval_audit
        WHERE created_at > NOW() - INTERVAL '%s days'
        GROUP BY symbol, approval_status
    """, [args.since_days])
    # We need by strategy — join via proposal
    audit_blocks = {}

    # Lifecycle outcomes by strategy
    cur.execute("""
        SELECT strategy_name,
            COUNT(*) as total,
            COUNT(*) FILTER (WHERE status='closed') as closed_count,
            COUNT(*) FILTER (WHERE status='open') as open_count,
            COUNT(*) FILTER (WHERE status='cancelled') as cancelled_count,
            COUNT(*) FILTER (WHERE outcome_label IN ('win','target_hit')) as win_count,
            COUNT(*) FILTER (WHERE outcome_label IN ('loss','stopped')) as loss_count,
            ROUND(AVG(r_multiple) FILTER (WHERE status='closed' AND r_multiple IS NOT NULL)::numeric, 3) as avg_r,
            ROUND(SUM(COALESCE(pnl,0)) FILTER (WHERE status='closed')::numeric, 2) as total_pnl,
            ROUND(COUNT(*) FILTER (WHERE proposal_id IS NOT NULL)::numeric / NULLIF(COUNT(*),0), 2) as linkage_rate
        FROM paper_trade_lifecycle_outcomes
        WHERE created_at > NOW() - INTERVAL '%s days'
        GROUP BY strategy_name ORDER BY closed_count DESC
    """, [args.since_days])
    outcome_data = {r["strategy_name"]: r for r in cur.fetchall()}

    # Paper trades by strategy
    cur.execute("""
        SELECT strategy_id, COUNT(*) as paper_trade_count
        FROM paper_trades WHERE created_at > NOW() - INTERVAL '%s days'
        GROUP BY strategy_id
    """, [args.since_days])
    trade_data = {r["strategy_id"]: r["paper_trade_count"] for r in cur.fetchall()}

    conn.close()

    # Merge into funnel
    all_strategies = sorted(set(list(proposal_data.keys()) + list(outcome_data.keys()) + list(trade_data.keys())))
    results = []

    for sid in all_strategies:
        pd = proposal_data.get(sid, {})
        od = outcome_data.get(sid, {})
        proposals = pd.get("proposal_count", 0)
        closed = od.get("closed_count", 0)
        linkage = float(od.get("linkage_rate", 0) or 0)

        metrics = {"proposal_count": proposals, "closed_count": closed, "lifecycle_linkage_rate": linkage}
        proof = classify_strategy_proof_status(metrics, a5_complete)
        blockers = summarize_strategy_blockers(metrics, a5_complete)

        entry = {
            "strategy_id": sid,
            "proposal_count": proposals,
            "approved_count": pd.get("approved_count", 0),
            "paper_trade_count": trade_data.get(sid, 0),
            "closed_count": closed,
            "open_count": od.get("open_count", 0),
            "cancelled_count": od.get("cancelled_count", 0),
            "win_count": od.get("win_count", 0),
            "loss_count": od.get("loss_count", 0),
            "avg_r_multiple": float(od["avg_r"]) if od.get("avg_r") else None,
            "total_pnl": float(od["total_pnl"]) if od.get("total_pnl") else None,
            "lifecycle_linkage_rate": linkage,
            "proof_status": proof["proof_status"],
            "sample_quality": proof["sample_quality"],
            "decision_allowed": proof["decision_allowed"],
            "recommendation_status": "human_review_only",
            "blockers": blockers,
        }
        # Hide performance if insufficient
        if closed < 5:
            entry["avg_r_multiple"] = None
            entry["total_pnl"] = None
        results.append(entry)

    if args.verbose:
        print(f"Strategy Evidence Funnel (A-5 complete: {a5_complete})")
        for r in results:
            icon = {"blocked_a5_incomplete": "!", "insufficient": "x", "observing": "~",
                    "preliminary": "?", "review_ready": "*", "decision_ready": "+"}.get(r["proof_status"], "?")
            print(f"  [{icon}] {r['strategy_id']:30s} prop={r['proposal_count']:3d} "
                  f"closed={r['closed_count']:2d} [{r['proof_status']}]")

    report = {"generated_at": now.isoformat(), "a5_complete": a5_complete,
              "since_days": args.since_days, "strategy_count": len(results),
              "strategies": results}
    if args.output_json:
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
    if args.output_md:
        md = [f"# Strategy Evidence Funnel", f"\nA-5: {'complete' if a5_complete else 'incomplete'}", "",
              "| Strategy | Proposals | Closed | Status | Blockers |",
              "|----------|-----------|--------|--------|----------|"]
        for r in results:
            md.append(f"| {r['strategy_id']} | {r['proposal_count']} | {r['closed_count']} | {r['proof_status']} | {'; '.join(r['blockers'][:2])} |")
        Path(args.output_md).write_text("\n".join(md))


if __name__ == "__main__":
    main()
