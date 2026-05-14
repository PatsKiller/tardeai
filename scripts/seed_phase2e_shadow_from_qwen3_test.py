#!/usr/bin/env python3
"""seed_phase2e_shadow_from_qwen3_test.py — Copy qwen3 test embeddings to shadow table.
Does NOT alter production content_embeddings."""
import argparse, json, sys
from datetime import datetime
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

def main():
    p = argparse.ArgumentParser(description="Seed shadow from qwen3 test")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    p.add_argument("--source-table", default="content_embeddings_qwen3_test")
    p.add_argument("--target-table", default="content_embeddings_qwen3_shadow")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    conn = get_conn()
    cur = conn.cursor()

    limit_clause = f"LIMIT {args.limit}" if args.limit > 0 else ""
    cur.execute(f"SELECT COUNT(*) FROM {args.source_table}")
    src_count = cur.fetchone()[0]
    cur.execute(f"SELECT COUNT(*) FROM {args.target_table}")
    tgt_before = cur.fetchone()[0]

    print(f"Source: {args.source_table} ({src_count} rows)")
    print(f"Target: {args.target_table} ({tgt_before} rows before)")

    if args.dry_run:
        print(f"DRY RUN — would copy up to {src_count} rows (skipping duplicates)")
        conn.close()
        return

    cur.execute(f"""
        INSERT INTO {args.target_table}
            (source_type, source_id, title, content_preview, content_hash,
             embedding, embedding_model, embedding_dim, embedding_latency_ms,
             source_created_at, indexed_at)
        SELECT source_type, source_id, title, content_preview, content_hash,
               embedding, embedding_model, embedding_dim, embedding_latency_ms,
               source_created_at, indexed_at
        FROM {args.source_table}
        {limit_clause}
        ON CONFLICT (source_type, source_id, embedding_model) DO NOTHING
    """)
    copied = cur.rowcount
    conn.commit()

    cur.execute(f"SELECT COUNT(*) FROM {args.target_table}")
    tgt_after = cur.fetchone()[0]

    print(f"Copied: {copied}")
    print(f"Skipped (duplicate): {src_count - copied}")
    print(f"Target after: {tgt_after}")
    conn.close()

if __name__ == "__main__":
    main()
