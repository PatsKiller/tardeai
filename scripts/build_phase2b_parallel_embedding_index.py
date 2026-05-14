#!/usr/bin/env python3
"""build_phase2b_parallel_embedding_index.py — Build Phase 2B qwen3 test embeddings.
Does NOT alter production content_embeddings."""

import argparse
import hashlib
import json
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent

OLLAMA_URL = "http://localhost:11434"


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


def embed_text(text, model="nomic-embed-text"):
    import urllib.request, json, time
    data = json.dumps({"model": model, "prompt": text[:2000]}).encode()
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/embeddings",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    start = time.monotonic()
    with urllib.request.urlopen(req, timeout=120) as resp:
        result = json.loads(resp.read())
    latency = round((time.monotonic() - start) * 1000, 1)
    return result.get("embedding", []), latency


def log(msg):
    print(f"{datetime.now().strftime('%H:%M:%S')} [phase2b-build] {msg}", flush=True)


# Per-source caps for balanced 5,000-doc mix.
# Proportional to production importance, not just row count.
SOURCE_CAPS = {
    "agent_result":     1500,
    "fused_signal":      900,
    "news":              600,
    "decision_outcome":  500,
    "agent_synthesis":   400,
    "cio_decision":      400,
    "youtube":           250,
    "social_post":       200,
    "sec_form4":         100,
    "trade_review":       50,
    "trade_outcome":      50,
    "fred_series":        28,
    "brave_cache":        10,
}

SOURCE_QUERY_PER_TYPE = """
SELECT ce.id, ce.source_type, ce.source_id, ce.title, ce.created_at
FROM content_embeddings ce
WHERE ce.source_type = %s
ORDER BY ce.created_at DESC
LIMIT %s
"""

# Fallback: simple LIMIT query (original behavior)
SOURCE_QUERY = """
SELECT ce.id, ce.source_type, ce.source_id, ce.title, ce.created_at
FROM content_embeddings ce
WHERE ce.source_type NOT IN ('test')
ORDER BY ce.created_at DESC
LIMIT %s
"""


def unload_candidate_restore_nomic():
    """Unload qwen3-embedding and restore nomic-embed-text."""
    log("Unloading qwen3-embedding:8b...")
    try:
        urllib.request.urlopen(urllib.request.Request(
            f"{OLLAMA_URL}/api/generate",
            data=json.dumps({"model": "qwen3-embedding:8b", "keep_alive": 0, "prompt": ""}).encode(),
            headers={"Content-Type": "application/json"}), timeout=15)
    except Exception as e:
        log(f"  Unload warning (non-fatal): {e}")
    time.sleep(3)
    log("Restoring nomic-embed-text...")
    try:
        urllib.request.urlopen(urllib.request.Request(
            f"{OLLAMA_URL}/api/embeddings",
            data=json.dumps({"model": "nomic-embed-text", "prompt": "restore"}).encode(),
            headers={"Content-Type": "application/json"}), timeout=30)
        log("  nomic-embed-text restored")
    except Exception as e:
        log(f"  Restore warning (non-fatal): {e}")


def main():
    parser = argparse.ArgumentParser(description="Build Phase 2B qwen3 test embeddings")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true", help="Show plan without executing")
    group.add_argument("--apply", action="store_true", help="Build embeddings")
    parser.add_argument("--limit-docs", type=int, default=1000, help="Max docs to process")
    parser.add_argument("--batch-size", type=int, default=25, help="Batch size for inserts")
    parser.add_argument("--table", default="content_embeddings_qwen3_test", help="Target table")
    parser.add_argument("--model", default="qwen3-embedding:8b", help="Embedding model")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--json-output", default=None, help="Write JSON summary to file")
    args = parser.parse_args()

    target_table = args.table
    target_model = args.model
    log("Phase 2B — Build parallel embedding test index")
    log(f"Model: {target_model} | Table: {target_table} | Limit: {args.limit_docs} | Batch: {args.batch_size}")
    log("NOTE: Using title field (up to 300 chars) as embedding source.")
    log("      Full-text recovery from source tables would be better in production.")
    log("Production content_embeddings will NOT be altered.")

    conn = get_db_connection()
    cur = conn.cursor()

    # Check test table exists
    cur.execute("""
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_name = %s
        )
    """, (target_table,))
    if not cur.fetchone()[0]:
        log(f"ABORT: Test table {target_table} does not exist.")
        log("Run: scripts/create_phase2b_parallel_embedding_index.py --apply")
        sys.exit(1)

    # Get source docs with balanced per-source sampling
    log(f"Fetching up to {args.limit_docs} source docs from production (balanced)...")
    source_docs = []
    if args.limit_docs >= 2000:
        # Balanced sampling: pull per-source caps, scaled to target
        scale = args.limit_docs / 5000.0
        for src_type, cap in SOURCE_CAPS.items():
            scaled_cap = max(1, int(cap * scale))
            cur.execute(SOURCE_QUERY_PER_TYPE, (src_type, scaled_cap))
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
            source_docs.extend(rows)
            if rows and args.verbose:
                log(f"  {src_type}: {len(rows)} docs (cap {scaled_cap})")
        # Fill remaining capacity from agent_result (largest source)
        remaining = args.limit_docs - len(source_docs)
        if remaining > 0:
            fetched_ids = {d["id"] for d in source_docs}
            cur.execute("""SELECT ce.id, ce.source_type, ce.source_id, ce.title, ce.created_at
                           FROM content_embeddings ce WHERE ce.source_type = 'agent_result'
                           ORDER BY ce.created_at DESC LIMIT %s""", (remaining + 500,))
            cols = [d[0] for d in cur.description]
            for row in cur.fetchall():
                d = dict(zip(cols, row))
                if d["id"] not in fetched_ids and len(source_docs) < args.limit_docs:
                    source_docs.append(d)
                    fetched_ids.add(d["id"])
    else:
        cur.execute(SOURCE_QUERY, (args.limit_docs,))
        cols = [d[0] for d in cur.description]
        source_docs = [dict(zip(cols, row)) for row in cur.fetchall()]
    log(f"Fetched {len(source_docs)} source documents")

    if not source_docs:
        log("No source documents found. Nothing to do.")
        conn.close()
        return

    # Source type distribution
    type_dist = {}
    for d in source_docs:
        st = d["source_type"]
        type_dist[st] = type_dist.get(st, 0) + 1
    log(f"Source types: {type_dist}")

    # Filter out docs already in test table
    source_keys = [(d["source_type"], d["source_id"]) for d in source_docs]
    cur.execute(f"""
        SELECT source_type, source_id
        FROM {target_table}
        WHERE embedding_model = %s
    """, (target_model,))
    existing = set((r[0], r[1]) for r in cur.fetchall())
    pending = [d for d in source_docs if (d["source_type"], d["source_id"]) not in existing]
    skipped_existing = len(source_docs) - len(pending)
    log(f"Already indexed: {skipped_existing} | Pending: {len(pending)}")

    if args.dry_run:
        log("=== DRY RUN ===")
        log(f"Would embed {len(pending)} documents with {target_model}")
        log(f"Estimated time: ~{len(pending) * 0.3:.0f}s ({len(pending)} docs x ~300ms)")
        log(f"Target table: {target_table}")
        log("No production data would be modified.")
        log("=== DRY RUN COMPLETE ===")
        conn.close()
        return

    if not pending:
        log("All docs already indexed. Nothing to do.")
        conn.close()
        return

    # Process in batches
    total = len(pending)
    success = 0
    failed = 0
    skipped_no_title = 0
    latencies = []
    batch_num = 0
    start_time = time.monotonic()

    for batch_start in range(0, total, args.batch_size):
        batch_num += 1
        batch = pending[batch_start:batch_start + args.batch_size]
        batch_success = 0
        batch_failed = 0

        for doc in batch:
            title = (doc.get("title") or "")[:300].strip()
            if not title:
                skipped_no_title += 1
                continue

            content_hash = hashlib.sha256(title.encode()).hexdigest()[:16]

            try:
                embedding, latency_ms = embed_text(title, model=target_model)
                if not embedding:
                    batch_failed += 1
                    failed += 1
                    if args.verbose:
                        log(f"  FAIL: empty embedding for {doc['source_type']}:{doc['source_id']}")
                    continue

                cur.execute(f"""
                    INSERT INTO {target_table}
                        (source_type, source_id, title, content_preview, content_hash,
                         embedding, embedding_model, embedding_dim, embedding_latency_ms,
                         source_created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (source_type, source_id, embedding_model) DO NOTHING
                """, (
                    doc["source_type"],
                    doc["source_id"],
                    title,
                    title[:200],
                    content_hash,
                    json.dumps(embedding),
                    target_model,
                    len(embedding),
                    latency_ms,
                    doc.get("created_at"),
                ))
                conn.commit()
                batch_success += 1
                success += 1
                latencies.append(latency_ms)

            except Exception as e:
                conn.rollback()
                batch_failed += 1
                failed += 1
                if args.verbose:
                    log(f"  ERROR: {doc['source_type']}:{doc['source_id']}: {e}")

        processed = batch_start + len(batch)
        avg_lat = sum(latencies[-len(batch):]) / max(len(latencies[-len(batch):]), 1)
        elapsed = time.monotonic() - start_time
        rate = processed / elapsed if elapsed > 0 else 0
        eta = (total - processed) / rate if rate > 0 else 0
        log(f"Batch {batch_num}: {batch_success} ok, {batch_failed} fail | "
            f"Progress: {processed}/{total} ({processed*100//total}%) | "
            f"Avg latency: {avg_lat:.0f}ms | ETA: {eta:.0f}s")

    elapsed_total = round(time.monotonic() - start_time, 1)
    avg_latency = round(sum(latencies) / max(len(latencies), 1), 1)

    # Final count
    cur.execute(f"SELECT COUNT(*) FROM {target_table}")
    final_count = cur.fetchone()[0]

    log("=" * 60)
    log("Phase 2B Build Summary")
    log("=" * 60)
    log(f"Total source docs:   {len(source_docs)}")
    log(f"Already indexed:     {skipped_existing}")
    log(f"Pending:             {total}")
    log(f"Success:             {success}")
    log(f"Failed:              {failed}")
    log(f"Skipped (no title):  {skipped_no_title}")
    log(f"Avg latency:         {avg_latency}ms")
    log(f"Total time:          {elapsed_total}s")
    log(f"Final table count:   {final_count}")
    log("=" * 60)

    summary = {
        "timestamp": datetime.now().isoformat(),
        "model": "qwen3-embedding:8b",
        "source_docs": len(source_docs),
        "already_indexed": skipped_existing,
        "pending": total,
        "success": success,
        "failed": failed,
        "skipped_no_title": skipped_no_title,
        "avg_latency_ms": avg_latency,
        "total_time_s": elapsed_total,
        "final_table_count": final_count,
        "source_distribution": type_dist,
        "production_changed": False,
    }

    if args.json_output:
        Path(args.json_output).write_text(json.dumps(summary, indent=2, default=str))
        log(f"JSON summary written to {args.json_output}")

    cur.close()
    conn.close()

    # Unload candidate, restore nomic
    unload_candidate_restore_nomic()
    log("Done.")


if __name__ == "__main__":
    main()
