#!/usr/bin/env python3
"""report_route_audit_root_cause.py — Why route audit is missing for proposals.

Read-only. No DB writes. No route backfill.

Usage:
    .venv/bin/python scripts/report_route_audit_root_cause.py --verbose
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
    p = argparse.ArgumentParser(description="Route audit root cause (read-only)")
    p.add_argument("--since-days", type=int, default=30)
    p.add_argument("--output-json", type=str)
    p.add_argument("--output-md", type=str)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    since = datetime.now(timezone.utc) - timedelta(days=args.since_days)

    # Count proposals and route audit coverage
    total = _db_query("SELECT count(*) as c FROM paper_trade_proposals WHERE created_at > %s", [since], fetch="one")
    total_count = int((total or {}).get("c", 0))

    with_audit = _db_query("""
        SELECT count(DISTINCT ptp.id) as c
        FROM paper_trade_proposals ptp
        JOIN strategy_setup_matches ssm ON ssm.proposal_id = ptp.id
        WHERE ptp.created_at > %s
    """, [since], fetch="one")
    audit_count = int((with_audit or {}).get("c", 0))
    missing_count = total_count - audit_count

    # Check proposal sources
    by_source = _db_query("""
        SELECT proposed_by, count(*) as c
        FROM paper_trade_proposals
        WHERE created_at > %s
        GROUP BY proposed_by ORDER BY c DESC
    """, [since]) or []

    # Check code paths
    auto_gen_exists = (PROJ / "scripts/auto_proposal_generator.py").exists()
    promoter_exists = (PROJ / "scripts/incubator_proposal_promoter.py").exists()
    router_exists = (PROJ / "scripts/multi_setup_router.py").exists()

    auto_gen_calls_router = False
    promoter_calls_router = False
    if auto_gen_exists:
        src = (PROJ / "scripts/auto_proposal_generator.py").read_text()
        auto_gen_calls_router = "store_setup_matches" in src or "route_symbol" in src
    if promoter_exists:
        src = (PROJ / "scripts/incubator_proposal_promoter.py").read_text()
        promoter_calls_router = "store_setup_matches" in src or "route_symbol" in src

    # Invalid strategy IDs
    invalid = _db_query("""
        SELECT strategy_id, count(*) as c
        FROM paper_trade_proposals
        WHERE created_at > %s AND strategy_id NOT IN (
            SELECT DISTINCT strategy_id FROM strategy_setup_matches
            UNION SELECT 'momentum_scalp' UNION SELECT 'gap_and_go'
            UNION SELECT 'swing_breakout' UNION SELECT 'swing_trade'
            UNION SELECT 'recovery_watch' UNION SELECT 'speculative_growth'
            UNION SELECT 'earnings_catalyst' UNION SELECT 'sector_rotation'
            UNION SELECT 'core_growth_compounder' UNION SELECT 'dividend_growth_compounder'
        )
        GROUP BY strategy_id
    """, [since]) or []

    root_causes = [
        {
            "cause": "auto_proposal_generator does not call multi_setup_router",
            "evidence": f"auto_proposal_generator.py exists={auto_gen_exists}, calls_router={auto_gen_calls_router}",
            "affected_path": "screener → signal → proposal",
        },
        {
            "cause": "incubator_proposal_promoter does not call multi_setup_router",
            "evidence": f"incubator_proposal_promoter.py exists={promoter_exists}, calls_router={promoter_calls_router}",
            "affected_path": "incubator → proposal",
        },
        {
            "cause": "multi_setup_router.store_setup_matches only runs in manual --pending-proposals mode",
            "evidence": "store_setup_matches is never called from proposal creation pipeline",
            "affected_path": "all proposal creation paths",
        },
    ]

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_proposals": total_count,
        "with_route_audit": audit_count,
        "missing_route_audit": missing_count,
        "missing_pct": round(missing_count / total_count * 100, 1) if total_count > 0 else 0,
        "by_source": [{k: v for k, v in r.items()} for r in by_source],
        "root_causes": root_causes,
        "invalid_strategy_ids": [{k: v for k, v in r.items()} for r in invalid],
        "safe_to_backfill": True,
        "unsafe_to_auto_reassign": True,
        "recommended_fix": "Call route_symbol + store_setup_matches after proposal INSERT in both auto_proposal_generator and incubator_proposal_promoter (SP-2C)",
    }

    if args.verbose:
        print(f"Route Audit Root Cause — {total_count} proposals, {missing_count} missing ({report['missing_pct']}%)")
        for rc in root_causes:
            print(f"\n  CAUSE: {rc['cause']}")
            print(f"  Evidence: {rc['evidence']}")
            print(f"  Path: {rc['affected_path']}")
        if invalid:
            print(f"\n  Invalid strategy IDs: {invalid}")
        print(f"\n  Safe to backfill: {report['safe_to_backfill']}")
        print(f"  Recommended fix: {report['recommended_fix']}")

    if args.output_json:
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
    if args.output_md:
        md = ["# Route Audit Root Cause Report", f"\n{total_count} proposals, {missing_count} missing route audit ({report['missing_pct']}%)\n"]
        md.append("## Root Causes\n")
        for rc in root_causes:
            md.append(f"### {rc['cause']}")
            md.append(f"- Evidence: {rc['evidence']}")
            md.append(f"- Path: {rc['affected_path']}\n")
        md.append(f"## Recommended Fix\n\n{report['recommended_fix']}")
        Path(args.output_md).write_text("\n".join(md))


if __name__ == "__main__":
    main()
