#!/usr/bin/env python3
"""create_phase2e_qwen3_shadow_index.py — Create qwen3 global shadow embedding table.
Does NOT alter production content_embeddings."""
import argparse, sys
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent

def get_conn():
    import psycopg2
    env = {}
    for line in (PROJ / ".env").read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return psycopg2.connect(host=env.get("DB_HOST", "localhost"),
        dbname=env.get("DB_NAME", "trade_ai"), user=env.get("DB_USER", "trade_ai"),
        password=env.get("DB_PASSWORD", ""))

SCHEMA = """
CREATE TABLE IF NOT EXISTS {table} (
    id                   BIGSERIAL PRIMARY KEY,
    source_type          TEXT NOT NULL,
    source_id            BIGINT NOT NULL,
    title                TEXT,
    content_preview      TEXT,
    content_hash         TEXT NOT NULL,
    embedding            JSONB,
    embedding_model      TEXT NOT NULL DEFAULT 'qwen3-embedding:8b',
    embedding_dim        INTEGER NOT NULL DEFAULT 4096,
    embedding_latency_ms REAL,
    source_created_at    TIMESTAMPTZ,
    indexed_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(source_type, source_id, embedding_model)
);
CREATE INDEX IF NOT EXISTS idx_{short}_source ON {table}(source_type, source_id);
CREATE INDEX IF NOT EXISTS idx_{short}_model ON {table}(embedding_model);
CREATE INDEX IF NOT EXISTS idx_{short}_type ON {table}(source_type);
CREATE INDEX IF NOT EXISTS idx_{short}_indexed ON {table}(indexed_at);
"""

def main():
    p = argparse.ArgumentParser(description="Create Phase 2E qwen3 shadow table")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    p.add_argument("--table", default="content_embeddings_qwen3_shadow")
    args = p.parse_args()

    short = args.table.replace("content_embeddings_", "ce_")
    sql = SCHEMA.format(table=args.table, short=short)

    if args.dry_run:
        print(f"DRY RUN — would execute:\n{sql}")
        return

    conn = get_conn()
    cur = conn.cursor()
    cur.execute(sql)
    conn.commit()
    cur.execute(f"SELECT COUNT(*) FROM {args.table}")
    print(f"Table {args.table} ready. Current rows: {cur.fetchone()[0]}")
    conn.close()

if __name__ == "__main__":
    main()
