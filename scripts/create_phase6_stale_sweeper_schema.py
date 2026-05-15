#!/usr/bin/env python3
"""create_phase6_stale_sweeper_schema.py — Create stale sweep audit table.

Additive only. Does not alter existing tables.

Usage:
    .venv/bin/python scripts/create_phase6_stale_sweeper_schema.py --dry-run
    .venv/bin/python scripts/create_phase6_stale_sweeper_schema.py --apply
"""
import argparse, sys
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS paper_proposal_stale_sweep_audit (
    id                      BIGSERIAL PRIMARY KEY,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    sweep_run_id            TEXT NOT NULL,
    proposal_table          TEXT NOT NULL DEFAULT 'paper_trade_proposals',
    proposal_id             INTEGER NOT NULL,
    symbol                  TEXT,
    previous_status         TEXT,
    new_status              TEXT,
    stale_reason            TEXT NOT NULL,
    age_minutes             INTEGER,
    age_hours               NUMERIC,
    strategy_type           TEXT,
    created_at_source       TIMESTAMPTZ,
    threshold_minutes       INTEGER,
    dry_run                 BOOLEAN NOT NULL DEFAULT true,
    changed                 BOOLEAN NOT NULL DEFAULT false,
    error_json              JSONB NOT NULL DEFAULT '{}'::jsonb,
    proposal_snapshot_json  JSONB NOT NULL DEFAULT '{}'::jsonb,
    metadata_json           JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_ppssa_created ON paper_proposal_stale_sweep_audit (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ppssa_run ON paper_proposal_stale_sweep_audit (sweep_run_id);
CREATE INDEX IF NOT EXISTS idx_ppssa_proposal ON paper_proposal_stale_sweep_audit (proposal_id);
CREATE INDEX IF NOT EXISTS idx_ppssa_symbol ON paper_proposal_stale_sweep_audit (symbol);
CREATE INDEX IF NOT EXISTS idx_ppssa_dry_run ON paper_proposal_stale_sweep_audit (dry_run);
CREATE INDEX IF NOT EXISTS idx_ppssa_changed ON paper_proposal_stale_sweep_audit (changed);
CREATE INDEX IF NOT EXISTS idx_ppssa_reason ON paper_proposal_stale_sweep_audit (stale_reason);
"""


def get_conn():
    import psycopg2
    env = {}
    for line in (PROJ / ".env").read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return psycopg2.connect(host=env.get("DB_HOST", "localhost"), dbname=env.get("DB_NAME", "trade_ai"),
                            user=env.get("DB_USER", "trade_ai"), password=env.get("DB_PASSWORD", ""))


def main():
    p = argparse.ArgumentParser()
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    args = p.parse_args()

    if args.dry_run:
        print("DRY RUN — SQL:\n" + SCHEMA_SQL)
        return

    conn = get_conn()
    cur = conn.cursor()
    cur.execute(SCHEMA_SQL)
    conn.commit()
    cur.execute("SELECT COUNT(*) FROM paper_proposal_stale_sweep_audit")
    print(f"Schema applied. paper_proposal_stale_sweep_audit: {cur.fetchone()[0]} rows")
    conn.close()


if __name__ == "__main__":
    main()
