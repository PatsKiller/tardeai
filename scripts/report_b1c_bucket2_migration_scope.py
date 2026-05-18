#!/usr/bin/env python3
"""report_b1c_bucket2_migration_scope.py — Bucket 2 migration scope discovery.

Read-only. No mutation.

Usage:
    .venv/bin/python scripts/report_b1c_bucket2_migration_scope.py --verbose
"""
import argparse, json, sys
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))

BUCKET2_STRATEGIES = [
    "swing_breakout", "swing_trade", "earnings_post_momentum",
    "recovery_watch", "fib_retracement_bounce", "speculative_growth",
    "sector_rotation", "earnings_catalyst", "earnings_pre_buildup",
]


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
    p = argparse.ArgumentParser(description="Bucket 2 migration scope (read-only)")
    p.add_argument("--output-json", type=str)
    p.add_argument("--output-md", type=str)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    # Load YAML freshness configs
    try:
        from strategy_config_loader import load_all_strategy_configs
        configs = load_all_strategy_configs()
    except Exception:
        configs = {}

    strategies = []
    for sid in sorted(BUCKET2_STRATEGIES):
        cfg = configs.get(sid, {})
        fresh = cfg.get("freshness", {})
        strategies.append({
            "strategy_id": sid,
            "yaml_exists": sid in configs,
            "bucket": fresh.get("bucket"),
            "ttl_days": fresh.get("ttl_days"),
            "eval_cadence": fresh.get("eval_cadence"),
            "watchpool_enabled": fresh.get("watchpool", False),
            "rollback_to_legacy": fresh.get("rollback_to_legacy", False),
        })

    # DB state
    watchpool_count = _db_query("SELECT count(*) as c FROM strategy_watchpool", fetch="one")
    watchpool_rows = int((watchpool_count or {}).get("c", 0))

    watchpool_by_strategy = _db_query("""
        SELECT strategy_id, current_status, count(*) as c
        FROM strategy_watchpool
        GROUP BY strategy_id, current_status ORDER BY strategy_id
    """) or []

    # DB registry status
    db_strategies = _db_query("SELECT strategy_type, config_hash FROM strategy_registry") or []
    db_ids = {r["strategy_type"] for r in db_strategies}
    yaml_ids = set(configs.keys())
    missing_in_db = sorted(yaml_ids - db_ids - {"recommendation_schema", "strategy_schema", "shared_risk_rules"})

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "bucket2_strategies": strategies,
        "watchpool_total_rows": watchpool_rows,
        "watchpool_by_strategy": [{k: v for k, v in r.items()} for r in watchpool_by_strategy],
        "yaml_strategy_count": len(yaml_ids),
        "db_strategy_count": len(db_ids),
        "missing_in_db": missing_in_db,
        "migration_status": "operational" if watchpool_rows > 0 else "awaiting_first_entry",
        "references_daily_momentum_scalp": False,
        "references_live_execution": False,
    }

    if args.verbose:
        print(f"Bucket 2 Migration Scope — {len(strategies)} strategies")
        for s in strategies:
            wp = "WP" if s["watchpool_enabled"] else "--"
            rb = "ROLLBACK" if s["rollback_to_legacy"] else ""
            print(f"  {s['strategy_id']:30s} bucket={s['bucket'] or '?':10s} ttl={s['ttl_days'] or '?':>3}d [{wp}] {rb}")
        print(f"\n  Watchpool rows: {watchpool_rows}")
        for w in watchpool_by_strategy:
            print(f"    {w['strategy_id']}: {w['current_status']} ({w['c']})")
        if missing_in_db:
            print(f"\n  Missing in DB: {missing_in_db}")

    if args.output_json:
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
    if args.output_md:
        md = ["# Bucket 2 Migration Scope\n"]
        md.append("| Strategy | Bucket | TTL | Watchpool | Rollback |")
        md.append("|----------|--------|-----|-----------|----------|")
        for s in strategies:
            md.append(f"| {s['strategy_id']} | {s['bucket'] or '?'} | {s['ttl_days'] or '?'}d | {'Yes' if s['watchpool_enabled'] else 'No'} | {'Yes' if s['rollback_to_legacy'] else 'No'} |")
        md.append(f"\nWatchpool rows: {watchpool_rows}")
        if missing_in_db:
            md.append(f"\nMissing in DB: {', '.join(missing_in_db)}")
        Path(args.output_md).write_text("\n".join(md))


if __name__ == "__main__":
    main()
