#!/usr/bin/env python3
"""fix_strategy_registry_null_ids.py — backfill NULL/empty strategy_registry.strategy_id.

Convention everywhere in the codebase: strategy_id == strategy_type (the PK).
An older strategy_config_loader upsert omitted strategy_id, so YAML-synced
strategies landed with strategy_id NULL and the Strategy Weekly Review rendered
them as "None (UNVALIDATED)". These are real strategies, not orphans — the safe
fix is backfilling strategy_id = strategy_type, never deleting.

Safe: single UPDATE statement, no broker interaction, idempotent (no rows →
no-op). Every fixed row is appended to logs/strategy_registry_null_id_fix.jsonl.
Used as a health-agent auto-remediation (finding: strategy_registry_null_ids).

Usage:
    .venv/bin/python scripts/fix_strategy_registry_null_ids.py            # apply
    .venv/bin/python scripts/fix_strategy_registry_null_ids.py --dry-run  # preview
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except Exception:
    pass

AUDIT_LOG = PROJECT_ROOT / "logs" / "strategy_registry_null_id_fix.jsonl"


def _conn():
    import psycopg2
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "trade_ai"),
        user=os.getenv("DB_USER", "trade_ai"),
        password=os.getenv("DB_PASSWORD"),
    )


def run(dry_run: bool = False) -> dict:
    conn = _conn()
    try:
        cur = conn.cursor()
        if dry_run:
            cur.execute("""
                SELECT strategy_type FROM strategy_registry
                WHERE strategy_id IS NULL OR BTRIM(strategy_id) = ''
            """)
            fixed = [r[0] for r in cur.fetchall()]
        else:
            cur.execute("""
                UPDATE strategy_registry
                SET strategy_id = strategy_type, updated_at = NOW()
                WHERE strategy_id IS NULL OR BTRIM(strategy_id) = ''
                RETURNING strategy_type
            """)
            fixed = [r[0] for r in cur.fetchall()]
            conn.commit()
        result = {
            "at": datetime.now(timezone.utc).isoformat(),
            "dry_run": dry_run,
            "fixed_count": len(fixed),
            "strategy_types": sorted(fixed),
        }
        if fixed and not dry_run:
            AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
            with open(AUDIT_LOG, "a") as fh:
                fh.write(json.dumps(result) + "\n")
        return result
    finally:
        conn.close()


def main():
    ap = argparse.ArgumentParser(description="Backfill NULL strategy_registry.strategy_id")
    ap.add_argument("--dry-run", action="store_true", help="preview only, no DB writes")
    args = ap.parse_args()
    result = run(dry_run=args.dry_run)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
