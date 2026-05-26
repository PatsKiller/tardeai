#!/usr/bin/env python3
"""report_invalid_strategy_assignments.py — Find proposals with invalid strategy_id.

Read-only. No reassignment. No mutation.

Usage:
    .venv/bin/python scripts/report_invalid_strategy_assignments.py --verbose
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
    p = argparse.ArgumentParser(description="Invalid strategy assignment report (read-only)")
    p.add_argument("--since-days", type=int, default=30)
    p.add_argument("--output-json", type=str)
    p.add_argument("--output-md", type=str)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    since = datetime.now(timezone.utc) - timedelta(days=args.since_days)

    # Load valid YAML strategy IDs
    try:
        from strategy_config_loader import load_all_strategy_configs
        valid_ids = set(load_all_strategy_configs().keys())
    except Exception:
        valid_ids = set()

    # Get proposals with potentially invalid strategy_id
    proposals = _db_query("""
        SELECT id, symbol, strategy_id, primary_strategy_id, setup_stack,
               status, created_at, proposed_by
        FROM paper_trade_proposals
        WHERE created_at > %s
        ORDER BY created_at DESC
    """, [since]) or []

    invalid = []
    for pr in proposals:
        sid = pr.get("strategy_id") or ""
        if sid not in valid_ids:
            # Check setup_stack for alternatives
            ss = pr.get("setup_stack")
            if isinstance(ss, str):
                try: ss = json.loads(ss)
                except: ss = None
            alternatives = []
            if ss:
                alternatives = [m.get("strategy_id") for m in ss if m.get("strategy_id") in valid_ids]

            recommendation = "manual_review"
            if sid == "screener":
                recommendation = "rebuild_proposal_or_expire" if not alternatives else "review_alternatives"
            elif not sid:
                recommendation = "rebuild_proposal"

            invalid.append({
                "proposal_id": pr["id"],
                "symbol": pr["symbol"],
                "invalid_strategy_id": sid,
                "status": pr.get("status"),
                "proposed_by": pr.get("proposed_by"),
                "created_at": str(pr.get("created_at")),
                "valid_alternatives": alternatives[:5],
                "recommendation": recommendation,
            })

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "valid_yaml_strategies": sorted(valid_ids),
        "total_proposals": len(proposals),
        "invalid_count": len(invalid),
        "invalid_strategy_ids": list(set(i["invalid_strategy_id"] for i in invalid)),
        "invalid_proposals": invalid,
    }

    if args.verbose:
        print(f"Invalid Strategy Assignments — {len(invalid)}/{len(proposals)} proposals")
        for i in invalid:
            print(f"  {i['symbol']} (id={i['proposal_id']}): strategy_id='{i['invalid_strategy_id']}' → {i['recommendation']}")
            if i["valid_alternatives"]:
                print(f"    Alternatives from setup_stack: {i['valid_alternatives']}")

    if args.output_json:
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
    if args.output_md:
        md = [f"# Invalid Strategy Assignments", f"\n{len(invalid)}/{len(proposals)} proposals have invalid strategy_id\n"]
        md.append("| Symbol | ID | Invalid Strategy | Status | Recommendation |")
        md.append("|--------|----|-----------------|--------|---------------|")
        for i in invalid:
            md.append(f"| {i['symbol']} | {i['proposal_id']} | {i['invalid_strategy_id']} | {i['status']} | {i['recommendation']} |")
        Path(args.output_md).write_text("\n".join(md))


if __name__ == "__main__":
    main()
