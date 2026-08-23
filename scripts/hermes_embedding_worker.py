"""
Hermes Embedding Worker — Trade AI v12

Reads from hermes_embedding_queue, embeds via nomic-embed-text (Ollama),
writes to content_embeddings with source_type='hermes_research'.

Usage:
    python scripts/hermes_embedding_worker.py [--dry-run|--apply] [--limit N]
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from datetime import datetime, timezone

PROJECT_ROOT = Path(__file__).resolve().parent.parent

EMBEDDING_MODEL = "nomic-embed-text"
EMBEDDING_DIM = 768
EMBED_TIMEOUT = 120  # increased from 30s to handle slow Ollama embed calls


def get_db_connection():
    env_path = PROJECT_ROOT / ".env"
    db_pass = None
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith("DB_PASSWORD="):
                db_pass = line.split("=", 1)[1]
    if not db_pass:
        print("ERROR: DB_PASSWORD not found", file=sys.stderr)
        sys.exit(1)
    import psycopg2
    return psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=db_pass)


def get_embedding(text):
    """Get a policy-validated nomic embedding. Retries transient failures."""
    from lib.ollama_embedding_policy import embed
    last_err = None
    for attempt in range(3):
        try:
            return embed(text, timeout_s=EMBED_TIMEOUT)
        except Exception as e:
            last_err = e
            if attempt < 2:
                time.sleep(1.5 * (attempt + 1))
    raise last_err


def main():
    parser = argparse.ArgumentParser(description="Hermes embedding worker")
    parser.add_argument("--apply", action="store_true", help="Commit embeddings (default: dry-run)")
    parser.add_argument("--limit", type=int, default=15, help="Max items to process (default: 15)")
    parser.add_argument("--retry-failed", action="store_true",
                        help="Include failed queue rows (pending first, then oldest failed)")
    parser.add_argument("--reset-failed", type=int, default=0, metavar="N",
                        help="Before processing, reset up to N failed rows back to pending")
    args = parser.parse_args()
    dry_run = not args.apply

    conn = get_db_connection()
    cur = conn.cursor()

    if args.reset_failed and args.reset_failed > 0 and not dry_run:
        cur.execute("""
            UPDATE hermes_embedding_queue
            SET embedding_status='pending', error_message=NULL, embedded_at=NULL
            WHERE id IN (
                SELECT id FROM hermes_embedding_queue
                WHERE embedding_status='failed'
                ORDER BY created_at ASC LIMIT %s
            )
        """, (args.reset_failed,))
        reset_n = cur.rowcount
        conn.commit()
        if reset_n:
            print(f"Reset {reset_n} failed queue rows → pending")

    status_clause = "q.embedding_status IN ('pending','failed')" if args.retry_failed else "q.embedding_status = 'pending'"
    order_clause = "CASE q.embedding_status WHEN 'pending' THEN 0 ELSE 1 END, q.created_at" if args.retry_failed else "q.created_at"

    # Read pending (and optionally failed) queue items
    cur.execute(f"""
        SELECT q.id, q.source_research_id, q.title, q.content, q.source_type_target
        FROM hermes_embedding_queue q
        WHERE {status_clause}
        ORDER BY {order_clause}
        LIMIT %s
    """, (args.limit,))
    items = cur.fetchall()

    if not items:
        print("No pending items in hermes_embedding_queue.")
        return

    print(f"{'[DRY-RUN]' if dry_run else '[APPLY]'} Processing {len(items)} queue items")

    for qid, research_id, title, content, source_type in items:
        print(f"\n  Queue {qid}: research_id={research_id}, title={title[:60]}...")

        # Generate embedding
        embed_text = f"{title}\n\n{content}"[:2000]  # cap for embedding model
        try:
            vec = get_embedding(embed_text)
            if not vec or len(vec) != EMBEDDING_DIM:
                print(f"    ERROR: embedding returned {len(vec) if vec else 0} dims (expected {EMBEDDING_DIM})")
                if not dry_run:
                    cur.execute("UPDATE hermes_embedding_queue SET embedding_status='failed', error_message=%s WHERE id=%s",
                                (f"Wrong dimension: {len(vec) if vec else 0}", qid))
                    conn.commit()
                continue
        except Exception as e:
            print(f"    ERROR: embedding failed: {e}")
            if not dry_run:
                cur.execute("UPDATE hermes_embedding_queue SET embedding_status='failed', error_message=%s WHERE id=%s",
                            (str(e)[:200], qid))
                conn.commit()
            continue

        print(f"    Embedding: {len(vec)} dims, first 3: [{vec[0]:.4f}, {vec[1]:.4f}, {vec[2]:.4f}]")

        # Compute TF-IDF keywords (simple version)
        words = embed_text.lower().split()
        from collections import Counter
        word_counts = Counter(w for w in words if len(w) > 3)
        top_keywords = [w for w, _ in word_counts.most_common(10)]

        if dry_run:
            print(f"    DRY-RUN: would insert into content_embeddings (source_type='{source_type}')")
            print(f"    Keywords: {top_keywords[:5]}")
            continue

        # Insert into content_embeddings
        cur.execute("""
            INSERT INTO content_embeddings (source_type, source_id, title, top_keywords, embedding, embedding_model, embedding_dim, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (source_type, source_id) DO UPDATE SET
                embedding = EXCLUDED.embedding, embedding_model = EXCLUDED.embedding_model,
                embedding_dim = EXCLUDED.embedding_dim, title = EXCLUDED.title
            RETURNING id
        """, (source_type, research_id, title[:200], top_keywords, json.dumps(vec), EMBEDDING_MODEL, EMBEDDING_DIM))
        embedded_id = cur.fetchone()[0]

        # Update queue status
        cur.execute("""
            UPDATE hermes_embedding_queue
            SET embedding_status = 'completed', embedded_id = %s, embedded_at = NOW()
            WHERE id = %s
        """, (embedded_id, qid))

        conn.commit()
        print(f"    COMMITTED: content_embeddings id={embedded_id}, queue updated")

    conn.close()
    print(f"\n{'DRY-RUN complete' if dry_run else 'APPLY complete'}")


if __name__ == "__main__":
    main()
