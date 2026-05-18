#!/usr/bin/env python3
"""migrate_b1c_bucket2.py — Bucket 2 migration validation and DB sync.

Default: dry-run. Requires --apply for DB sync.
Does NOT change strategy activation or create trades.

Usage:
    .venv/bin/python scripts/migrate_b1c_bucket2.py --dry-run --verbose
    .venv/bin/python scripts/migrate_b1c_bucket2.py --apply --verbose
"""
import argparse, json, sys
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))

UNSAFE_PATTERNS = [".env", "cookie", "credential", "secret", "token", "password", "api_key"]


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
    p = argparse.ArgumentParser(description="Bucket 2 migration (default: dry-run)")
    p.add_argument("--dry-run", action="store_true", default=True)
    p.add_argument("--apply", action="store_true")
    p.add_argument("--output-json", type=str)
    p.add_argument("--output-md", type=str)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    if args.apply:
        args.dry_run = False

    # Load YAML configs
    try:
        from strategy_config_loader import load_all_strategy_configs
        configs = load_all_strategy_configs()
    except Exception:
        configs = {}

    yaml_ids = set(configs.keys()) - {"recommendation_schema", "strategy_schema", "shared_risk_rules"}

    # Check DB state
    db_strategies = _db_query("SELECT strategy_type, config_hash FROM strategy_registry") or []
    db_ids = {r["strategy_type"] for r in db_strategies}

    missing_in_db = sorted(yaml_ids - db_ids)
    stale_in_db = sorted(db_ids - yaml_ids)

    # Check freshness configs
    freshness_issues = []
    for sid, cfg in configs.items():
        if sid in ("recommendation_schema", "strategy_schema", "shared_risk_rules"):
            continue
        fresh = cfg.get("freshness", {})
        if not fresh:
            freshness_issues.append({"strategy_id": sid, "issue": "no freshness block"})
        elif not fresh.get("bucket"):
            freshness_issues.append({"strategy_id": sid, "issue": "no bucket defined"})

    # Watchpool state
    watchpool = _db_query("SELECT strategy_id, current_status, count(*) as c FROM strategy_watchpool GROUP BY strategy_id, current_status") or []

    # Safety checks
    blockers = []
    if any(any(pat in str(cfg).lower() for pat in UNSAFE_PATTERNS) for cfg in configs.values()):
        blockers.append("Unsafe pattern found in configs")

    actions = []
    if missing_in_db:
        actions.append({
            "action": "sync_missing_strategies_to_db",
            "count": len(missing_in_db),
            "strategies": missing_in_db,
            "method": "strategy_config_loader.py --sync-db",
        })

    sync_applied = False
    if not args.dry_run and missing_in_db and not blockers:
        # Run DB sync
        import subprocess
        try:
            r = subprocess.run(
                [str(PROJ / ".venv/bin/python"), str(PROJ / "scripts/strategy_config_loader.py"), "--sync-db"],
                capture_output=True, text=True, cwd=str(PROJ), timeout=30
            )
            sync_applied = r.returncode == 0
            if args.verbose:
                print(f"  DB sync: {'OK' if sync_applied else 'FAILED'}")
                if r.stdout.strip():
                    print(f"    {r.stdout.strip()[:200]}")
        except Exception as e:
            if args.verbose:
                print(f"  DB sync failed: {e}")

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "dry_run" if args.dry_run else "apply",
        "yaml_strategies": len(yaml_ids),
        "db_strategies": len(db_ids),
        "missing_in_db": missing_in_db,
        "stale_in_db": stale_in_db,
        "freshness_issues": freshness_issues,
        "watchpool_state": [{k: v for k, v in w.items()} for w in watchpool],
        "blockers": blockers,
        "actions": actions,
        "sync_applied": sync_applied,
        "rollback": "Run strategy_config_loader.py --sync-db to re-sync from YAML" if sync_applied else None,
    }

    if args.verbose:
        print(f"Bucket 2 Migration {'DRY RUN' if args.dry_run else 'APPLY'}")
        print(f"  YAML: {len(yaml_ids)}, DB: {len(db_ids)}")
        if missing_in_db:
            print(f"  Missing in DB: {missing_in_db}")
        if stale_in_db:
            print(f"  Stale in DB: {stale_in_db}")
        if freshness_issues:
            print(f"  Freshness issues: {len(freshness_issues)}")
        if blockers:
            print(f"  BLOCKERS: {blockers}")
        print(f"  Watchpool: {len(watchpool)} groups")
        if sync_applied:
            print(f"  DB sync: APPLIED")

    if args.output_json:
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
    if args.output_md:
        md = [f"# Bucket 2 Migration {'DRY RUN' if args.dry_run else 'APPLIED'}",
              f"\nYAML: {len(yaml_ids)} | DB: {len(db_ids)} | Missing: {len(missing_in_db)} | Blockers: {len(blockers)}"]
        if missing_in_db:
            md.append(f"\n## Missing in DB\n{', '.join(missing_in_db)}")
        if sync_applied:
            md.append("\n## DB Sync: APPLIED")
        Path(args.output_md).write_text("\n".join(md))


if __name__ == "__main__":
    main()
