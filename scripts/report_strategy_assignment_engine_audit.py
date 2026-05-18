#!/usr/bin/env python3
"""report_strategy_assignment_engine_audit.py — Strategy assignment engine audit.

Read-only. No mutations.

Usage:
    .venv/bin/python scripts/report_strategy_assignment_engine_audit.py --verbose --since-days 30
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
        if not conn:
            return [] if fetch == "all" else None
        cur = conn.cursor()
        cur.execute(sql, params or [])
        if fetch == "one":
            row = cur.fetchone()
            if row:
                cols = [d[0] for d in cur.description]
                return dict(zip(cols, row))
            return None
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
        conn.close()
        return [dict(zip(cols, r)) for r in rows]
    except Exception:
        return [] if fetch == "all" else None


def main():
    p = argparse.ArgumentParser(description="Strategy assignment engine audit (read-only)")
    p.add_argument("--since-days", type=int, default=30)
    p.add_argument("--output-json", type=str)
    p.add_argument("--output-md", type=str)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    since = datetime.now(timezone.utc) - timedelta(days=args.since_days)

    # Get proposals
    proposals = _db_query("""
        SELECT id, symbol, strategy_id, primary_strategy_id, secondary_strategy_ids,
               setup_stack, strategy_config_hash, created_at
        FROM paper_trade_proposals
        WHERE created_at > %s
        ORDER BY created_at DESC
    """, [since]) or []

    # Get strategy YAML configs
    try:
        from strategy_config_loader import load_all_strategy_configs
        configs = load_all_strategy_configs()
    except Exception:
        configs = {}

    yaml_hashes = {sid: cfg.get("_config_hash") for sid, cfg in configs.items()}
    yaml_strategies = set(configs.keys())

    # Get setup matches
    match_counts = _db_query("""
        SELECT proposal_id, count(*) as match_count
        FROM strategy_setup_matches
        WHERE created_at > %s
        GROUP BY proposal_id
    """, [since]) or []
    mc_map = {r["proposal_id"]: r["match_count"] for r in match_counts}

    # Analyze each proposal
    with_primary = 0
    with_setup_stack = 0
    with_route_audit = 0
    missing_route_audit = 0
    yaml_missing = 0
    yaml_db_drift = 0
    strategies_used = set()
    strategies_never_used = set()

    proposal_details = []
    for pr in proposals:
        pid = pr["id"]
        sid = pr.get("strategy_id") or ""
        strategies_used.add(sid)

        has_primary = pr.get("primary_strategy_id") is not None
        if has_primary: with_primary += 1

        ss = pr.get("setup_stack")
        if isinstance(ss, str):
            try: ss = json.loads(ss)
            except: ss = None
        has_stack = ss is not None and len(ss or []) > 0
        if has_stack: with_setup_stack += 1

        has_matches = mc_map.get(pid, 0) > 0
        if has_matches or has_stack:
            with_route_audit += 1
        else:
            missing_route_audit += 1

        # YAML check
        has_yaml = sid in yaml_strategies
        if not has_yaml and sid:
            yaml_missing += 1

        # Hash sync
        stored_hash = pr.get("strategy_config_hash")
        yaml_hash = yaml_hashes.get(sid)
        synced = stored_hash and yaml_hash and stored_hash == yaml_hash
        if stored_hash and yaml_hash and not synced:
            yaml_db_drift += 1

        proposal_details.append({
            "proposal_id": pid,
            "symbol": pr.get("symbol"),
            "strategy_id": sid,
            "has_primary_strategy": has_primary,
            "has_setup_stack": has_stack,
            "has_route_audit": has_matches or has_stack,
            "has_yaml_config": has_yaml,
            "yaml_db_synced": synced,
            "match_count": mc_map.get(pid, 0),
        })

    # Strategies never selected
    strategies_never_used = yaml_strategies - strategies_used - {"recommendation_schema", "strategy_schema", "shared_risk_rules"}

    # Quality status
    if len(proposals) == 0:
        quality = "insufficient_evidence"
    elif missing_route_audit > len(proposals) * 0.5:
        quality = "missing_route_audit"
    elif yaml_db_drift > len(proposals) * 0.2:
        quality = "yaml_db_drift"
    elif missing_route_audit == 0 and yaml_missing == 0:
        quality = "healthy"
    else:
        quality = "partial"

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "since_days": args.since_days,
        "total_proposals": len(proposals),
        "with_primary_strategy": with_primary,
        "with_setup_stack": with_setup_stack,
        "with_route_audit": with_route_audit,
        "missing_route_audit": missing_route_audit,
        "yaml_config_missing": yaml_missing,
        "yaml_db_drift": yaml_db_drift,
        "strategies_used": sorted(strategies_used),
        "strategies_never_selected": sorted(strategies_never_used),
        "yaml_strategies_available": len(yaml_strategies),
        "assignment_quality_status": quality,
        "proposals": proposal_details[:50],
    }

    if args.verbose:
        print(f"Strategy Assignment Engine Audit — {len(proposals)} proposals (last {args.since_days}d)")
        print(f"  With primary strategy: {with_primary}/{len(proposals)}")
        print(f"  With setup_stack: {with_setup_stack}/{len(proposals)}")
        print(f"  With route audit: {with_route_audit}/{len(proposals)}")
        print(f"  Missing route audit: {missing_route_audit}/{len(proposals)}")
        print(f"  YAML missing: {yaml_missing}")
        print(f"  YAML/DB drift: {yaml_db_drift}")
        print(f"  Strategies used: {sorted(strategies_used)}")
        print(f"  Strategies never selected: {sorted(strategies_never_used)}")
        print(f"  Quality: {quality}")

    if args.output_json:
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
    if args.output_md:
        md = ["# Strategy Assignment Engine Audit", f"\nPeriod: last {args.since_days} days | {len(proposals)} proposals\n"]
        md.append(f"| Metric | Value |")
        md.append(f"|--------|-------|")
        md.append(f"| Total proposals | {len(proposals)} |")
        md.append(f"| With primary strategy | {with_primary} |")
        md.append(f"| With setup_stack | {with_setup_stack} |")
        md.append(f"| With route audit | {with_route_audit} |")
        md.append(f"| Missing route audit | {missing_route_audit} |")
        md.append(f"| YAML config missing | {yaml_missing} |")
        md.append(f"| YAML/DB drift | {yaml_db_drift} |")
        md.append(f"| Assignment quality | {quality} |")
        md.append(f"\n## Strategies Never Selected\n")
        for s in sorted(strategies_never_used):
            md.append(f"- {s}")
        Path(args.output_md).write_text("\n".join(md))


if __name__ == "__main__":
    main()
