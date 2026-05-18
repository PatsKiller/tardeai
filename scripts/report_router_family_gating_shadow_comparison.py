#!/usr/bin/env python3
"""report_router_family_gating_shadow_comparison.py — Compare R-5 vs R-2 routing.

Read-only. No proposal mutation.

Usage:
    .venv/bin/python scripts/report_router_family_gating_shadow_comparison.py --verbose
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
    p = argparse.ArgumentParser(description="R-2 family gating shadow comparison (read-only)")
    p.add_argument("--since-days", type=int, default=30)
    p.add_argument("--output-json", type=str)
    p.add_argument("--output-md", type=str)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    since = datetime.now(timezone.utc) - timedelta(days=args.since_days)

    try:
        from strategy_config_loader import load_all_strategy_configs
        from multi_setup_router import route_symbol
        from strategy_family_gate_policy import classify_candidate_family
        configs = load_all_strategy_configs()
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    proposals = _db_query("""
        SELECT ptp.id, ptp.symbol, ptp.strategy_id,
               scan.price, scan.rvol, scan.float_m, scan.gap_pct, scan.change_pct,
               scan.catalyst, scan.catalyst_verified
        FROM paper_trade_proposals ptp
        LEFT JOIN LATERAL (
            SELECT * FROM trade_ai_scans WHERE symbol = ptp.symbol
            ORDER BY scanned_at DESC LIMIT 1
        ) scan ON true
        WHERE ptp.created_at > %s
        ORDER BY ptp.created_at DESC LIMIT 100
    """, [since]) or []

    results = []
    family_blocked_count = 0
    r2_top_counts = {}

    for pr in proposals:
        signal = {k: v for k, v in pr.items() if k not in ("id",)}
        if not signal.get("price"):
            continue

        r2 = route_symbol(pr["symbol"], signal, configs)
        cf = classify_candidate_family(signal)

        # Find top non-blocked match
        top = None
        for m in r2.get("setup_stack", []):
            if not m.get("is_blocked") and m.get("match_status") != "NO_MATCH":
                top = m
                break

        top_sid = top["strategy_id"] if top else None
        top_score = top["match_score"] if top else 0
        r2_top_counts[top_sid or "none"] = r2_top_counts.get(top_sid or "none", 0) + 1

        fb_count = len([m for m in r2.get("setup_stack", []) if m.get("family_gate_blocked")])
        family_blocked_count += fb_count

        results.append({
            "proposal_id": pr["id"], "symbol": pr["symbol"],
            "original_strategy": pr["strategy_id"],
            "candidate_family": cf["candidate_family"],
            "r2_top_strategy": top_sid, "r2_score": top_score,
            "family_blocked_strategies": fb_count,
        })

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_proposals": len(results),
        "total_family_blocked": family_blocked_count,
        "r2_top_distribution": dict(sorted(r2_top_counts.items(), key=lambda x: -x[1])),
        "scoring_model": "yaml_weighted_v1_family_gate_v1",
        "proposals": results[:60],
    }

    if args.verbose:
        print(f"R-2 Shadow Comparison — {len(results)} proposals, {family_blocked_count} family-blocked")
        print(f"\n  R-2 top distribution:")
        for s, c in sorted(r2_top_counts.items(), key=lambda x: -x[1])[:10]:
            print(f"    {s}: {c}")

    if args.output_json:
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
    if args.output_md:
        md = [f"# R-2 Family Gating Shadow Comparison\n",
              f"Proposals: {len(results)} | Family blocked: {family_blocked_count}\n",
              "## R-2 Top Distribution\n",
              "| Strategy | Count |", "|----------|-------|"]
        for s, c in sorted(r2_top_counts.items(), key=lambda x: -x[1]):
            md.append(f"| {s} | {c} |")
        Path(args.output_md).write_text("\n".join(md))


if __name__ == "__main__":
    main()
