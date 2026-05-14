#!/usr/bin/env python3
"""create_phase2b_parallel_embedding_index.py — Create Phase 2B test table.
Does NOT alter production content_embeddings."""

import argparse
import sys
from datetime import datetime
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent


def get_db_connection():
    import psycopg2
    env_path = PROJ / ".env"
    env_vars = {}
    for line in env_path.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env_vars[k.strip()] = v.strip()
    return psycopg2.connect(
        host=env_vars.get("DB_HOST", "localhost"),
        dbname=env_vars.get("DB_NAME", "trade_ai"),
        user=env_vars.get("DB_USER", "trade_ai"),
        password=env_vars.get("DB_PASSWORD", ""),
    )


def log(msg):
    print(f"{datetime.now().strftime('%H:%M:%S')} [phase2b-create] {msg}", flush=True)


TABLE_DDL = """
CREATE TABLE IF NOT EXISTS content_embeddings_qwen3_test (
    id BIGSERIAL PRIMARY KEY,
    source_type TEXT NOT NULL,
    source_id BIGINT NOT NULL,
    title TEXT,
    content_preview TEXT,
    content_hash TEXT NOT NULL,
    embedding JSONB,
    embedding_model TEXT NOT NULL DEFAULT 'qwen3-embedding:8b',
    embedding_dim INTEGER NOT NULL DEFAULT 4096,
    embedding_latency_ms REAL,
    source_created_at TIMESTAMPTZ,
    indexed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(source_type, source_id, embedding_model)
);
"""

INDEX_DDL = [
    "CREATE INDEX IF NOT EXISTS idx_ceqt_source ON content_embeddings_qwen3_test(source_type, source_id);",
    "CREATE INDEX IF NOT EXISTS idx_ceqt_model ON content_embeddings_qwen3_test(embedding_model);",
]


def main():
    parser = argparse.ArgumentParser(description="Create Phase 2B parallel embedding test table")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true", help="Show SQL without executing")
    group.add_argument("--apply", action="store_true", help="Execute DDL against database")
    args = parser.parse_args()

    log("Phase 2B — Create parallel embedding test table")
    log("Target table: content_embeddings_qwen3_test")
    log("Production table content_embeddings will NOT be altered")

    if args.dry_run:
        log("=== DRY RUN — SQL that would be executed ===")
        print(TABLE_DDL)
        for idx in INDEX_DDL:
            print(idx)
        log("=== DRY RUN COMPLETE ===")
        return

    # --apply
    conn = get_db_connection()
    cur = conn.cursor()

    log("Creating table content_embeddings_qwen3_test...")
    cur.execute(TABLE_DDL)
    conn.commit()
    log("  Table created (or already exists)")

    for idx_sql in INDEX_DDL:
        idx_name = idx_sql.split("IF NOT EXISTS ")[1].split(" ON")[0]
        log(f"Creating index {idx_name}...")
        cur.execute(idx_sql)
        conn.commit()
        log(f"  Index {idx_name} created (or already exists)")

    # Verify
    cur.execute("""
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_name = 'content_embeddings_qwen3_test'
        ORDER BY ordinal_position
    """)
    cols = cur.fetchall()
    log(f"Verified table has {len(cols)} columns:")
    for col_name, col_type in cols:
        log(f"  {col_name}: {col_type}")

    cur.execute("SELECT COUNT(*) FROM content_embeddings_qwen3_test")
    count = cur.fetchone()[0]
    log(f"Current row count: {count}")

    cur.close()
    conn.close()
    log("Phase 2B table creation complete.")


if __name__ == "__main__":
    main()
