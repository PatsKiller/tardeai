#!/usr/bin/env python3
"""report_route_mismatch_human_review.py — Review SP-2B route mismatches.

Read-only. No reassignment. Human-review-only recommendations.

Usage:
    .venv/bin/python scripts/report_route_mismatch_human_review.py --verbose
"""
import argparse, json, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))


def _db_query(sql, params=None, fetch="all"):
    try:
        from db_adapter import _get_conn
        conn = _get_conn()
        if not conn: return [] if fetch == "all" else None
        cur = conn.cursor()
        cur.execute(sql, params or [])
        if fetch == "one":
            row = cur.fetchone()
            return dict(zip([d[0] for d in cur.description], row)) if row else None
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
        conn.close()
        return [dict(zip(cols, r)) for r in rows]
    except Exception:
        return [] if fetch == "all" else None


def main():
    p = argparse.ArgumentParser(description="Route mismatch human review (read-only)")
    p.add_argument("--since-days", type=int, default=30)
    p.add_argument("--output-json", type=str)
    p.add_argument("--output-md", type=str)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    since = datetime.now(timezone.utc) - timedelta(days=args.since_days)

    mismatches = _db_query("""
        SELECT ptp.id, ptp.symbol, ptp.strategy_id as original_strategy,
               ptp.status, ptp.catalyst_verified,
               scan.sector, scan.industry, scan.price, scan.rvol, scan.gap_pct,
               top.strategy_id as router_top, top.match_score as router_score,
               orig.match_score as original_score
        FROM paper_trade_proposals ptp
        JOIN LATERAL (
            SELECT strategy_id, match_score FROM strategy_setup_matches
            WHERE proposal_id = ptp.id ORDER BY match_score DESC LIMIT 1
        ) top ON true
        LEFT JOIN LATERAL (
            SELECT match_score FROM strategy_setup_matches
            WHERE proposal_id = ptp.id AND strategy_id = ptp.strategy_id LIMIT 1
        ) orig ON true
        LEFT JOIN LATERAL (
            SELECT sector, industry, price, rvol, gap_pct
            FROM trade_ai_scans WHERE symbol = ptp.symbol
            ORDER BY scanned_at DESC LIMIT 1
        ) scan ON true
        WHERE ptp.created_at > %s AND top.strategy_id != ptp.strategy_id
        ORDER BY top.match_score - COALESCE(orig.match_score, 0) DESC
    """, [since]) or []

    results = []
    momentum_too_broad = 0
    for m in mismatches:
        router_top = m.get("router_top", "")
        original = m.get("original_strategy", "")
        router_score = m.get("router_score", 0) or 0
        orig_score = m.get("original_score", 0) or 0

        is_momentum_broad = router_top == "momentum_scalp" and original != "momentum_scalp"
        if is_momentum_broad:
            momentum_too_broad += 1

        if original == "screener":
            rec = "expire_proposal"
            confidence = "high"
        elif is_momentum_broad and orig_score >= 30:
            rec = "keep_original"
            confidence = "medium"
            reason = "momentum_scalp matches broadly; original strategy may be more specific"
        elif orig_score < 20 and router_score > 50:
            rec = "rebuild_proposal"
            confidence = "medium"
        else:
            rec = "needs_more_data"
            confidence = "low"

        results.append({
            "proposal_id": m["id"], "symbol": m["symbol"],
            "original_strategy": original, "router_top": router_top,
            "original_score": orig_score, "router_score": router_score,
            "score_gap": router_score - orig_score,
            "sector": m.get("sector"), "industry": m.get("industry"),
            "catalyst_verified": m.get("catalyst_verified"),
            "recommendation": rec, "confidence": confidence,
            "human_review_only": True,
        })

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_mismatches": len(mismatches),
        "momentum_too_broad_count": momentum_too_broad,
        "by_recommendation": {},
        "mismatches": results[:60],
    }
    for r in results:
        report["by_recommendation"][r["recommendation"]] = report["by_recommendation"].get(r["recommendation"], 0) + 1

    if args.verbose:
        print(f"Route Mismatch Review — {len(mismatches)} mismatches")
        print(f"  momentum_scalp too broad: {momentum_too_broad}")
        for rec, cnt in sorted(report["by_recommendation"].items()):
            print(f"  {rec}: {cnt}")
        for r in results[:10]:
            print(f"  {r['symbol']} orig={r['original_strategy']}({r['original_score']}) vs router={r['router_top']}({r['router_score']}) → {r['recommendation']}")

    if args.output_json:
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
    if args.output_md:
        md = [f"# Route Mismatch Human Review\n",
              f"Mismatches: {len(mismatches)} | momentum_scalp broad: {momentum_too_broad}\n",
              "| Symbol | Original | Score | Router Top | Score | Rec |",
              "|--------|----------|-------|------------|-------|-----|"]
        for r in results[:30]:
            md.append(f"| {r['symbol']} | {r['original_strategy']} | {r['original_score']} | {r['router_top']} | {r['router_score']} | {r['recommendation']} |")
        Path(args.output_md).write_text("\n".join(md))


if __name__ == "__main__":
    main()
