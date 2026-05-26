#!/usr/bin/env python3
"""report_strategy_config_drift.py — Compare YAML config hashes with DB metadata.

Read-only. No DB sync. No YAML mutation.

Usage:
    .venv/bin/python scripts/report_strategy_config_drift.py --verbose
"""
import argparse, json, sys
from datetime import datetime, timezone
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
    p = argparse.ArgumentParser(description="Strategy config drift report (read-only)")
    p.add_argument("--output-json", type=str)
    p.add_argument("--output-md", type=str)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    # Load YAML configs
    try:
        from strategy_config_loader import load_all_strategy_configs
        yaml_configs = load_all_strategy_configs()
    except Exception:
        yaml_configs = {}

    yaml_hashes = {sid: cfg.get("_config_hash") for sid, cfg in yaml_configs.items()}
    yaml_ids = set(yaml_configs.keys())

    # Get DB strategy registry if exists
    db_strategies = {}
    try:
        rows = _db_query("SELECT strategy_type, config_hash, status FROM strategy_registry") or []
        db_strategies = {r["strategy_type"]: r for r in rows}
    except Exception:
        pass

    db_ids = set(db_strategies.keys())

    # Get proposal config hashes
    proposal_hashes = _db_query("""
        SELECT DISTINCT strategy_id, strategy_config_hash
        FROM paper_trade_proposals
        WHERE strategy_config_hash IS NOT NULL
    """) or []
    ph_map = {r["strategy_id"]: r["strategy_config_hash"] for r in proposal_hashes}

    # Compare
    strategies = []
    for sid in sorted(yaml_ids | db_ids):
        yaml_hash = yaml_hashes.get(sid)
        db_hash = db_strategies.get(sid, {}).get("config_hash")
        prop_hash = ph_map.get(sid)

        in_yaml = sid in yaml_ids
        in_db = sid in db_ids
        in_proposals = sid in ph_map

        # Drift detection
        yaml_db_match = yaml_hash == db_hash if yaml_hash and db_hash else None
        yaml_prop_match = yaml_hash == prop_hash if yaml_hash and prop_hash else None

        drift = "synced"
        if not in_yaml and in_db:
            drift = "db_only"
        elif in_yaml and not in_db:
            drift = "yaml_only"
        elif yaml_db_match is False:
            drift = "yaml_db_drift"
        elif yaml_prop_match is False:
            drift = "yaml_proposal_drift"

        strategies.append({
            "strategy_id": sid,
            "in_yaml": in_yaml,
            "in_db": in_db,
            "in_proposals": in_proposals,
            "yaml_hash": yaml_hash,
            "db_hash": db_hash,
            "proposal_hash": prop_hash,
            "drift_status": drift,
            "db_status": db_strategies.get(sid, {}).get("status"),
        })

    synced = len([s for s in strategies if s["drift_status"] == "synced"])
    drifted = len([s for s in strategies if s["drift_status"] in ("yaml_db_drift", "yaml_proposal_drift")])
    yaml_only = len([s for s in strategies if s["drift_status"] == "yaml_only"])
    db_only = len([s for s in strategies if s["drift_status"] == "db_only"])

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "yaml_count": len(yaml_ids),
        "db_count": len(db_ids),
        "synced": synced,
        "drifted": drifted,
        "yaml_only": yaml_only,
        "db_only": db_only,
        "strategies": strategies,
        "sync_recommendation": "Run strategy_config_loader.py --sync-db to update DB from YAML" if drifted > 0 else "No action needed",
    }

    if args.verbose:
        print(f"Strategy Config Drift — {len(yaml_ids)} YAML, {len(db_ids)} DB, {synced} synced, {drifted} drifted")
        for s in strategies:
            if s["drift_status"] != "synced":
                print(f"  {s['strategy_id']}: {s['drift_status']}")

    if args.output_json:
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
    if args.output_md:
        md = [f"# Strategy Config Drift Report",
              f"\nYAML: {len(yaml_ids)} | DB: {len(db_ids)} | Synced: {synced} | Drifted: {drifted}\n"]
        md.append("| Strategy | YAML | DB | Drift |")
        md.append("|----------|------|-----|-------|")
        for s in strategies:
            md.append(f"| {s['strategy_id']} | {'Y' if s['in_yaml'] else '-'} | {'Y' if s['in_db'] else '-'} | {s['drift_status']} |")
        Path(args.output_md).write_text("\n".join(md))


if __name__ == "__main__":
    main()
