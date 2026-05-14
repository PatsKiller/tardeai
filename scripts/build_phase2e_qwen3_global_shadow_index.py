#!/usr/bin/env python3
"""build_phase2e_qwen3_global_shadow_index.py — Backfill qwen3 shadow embeddings.

Reads production content_embeddings (read-only), embeds with qwen3-embedding:8b,
writes to content_embeddings_qwen3_shadow. Does NOT alter production table.

Usage:
    .venv/bin/python scripts/build_phase2e_qwen3_global_shadow_index.py \
        --apply --source-table content_embeddings \
        --target-table content_embeddings_qwen3_shadow \
        --model qwen3-embedding:8b --batch-size 25 --max-runtime-min 180 --resume --verbose
"""
import argparse, hashlib, json, sys, time, urllib.request, urllib.error
from datetime import datetime
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
OLLAMA_URL = "http://localhost:11434"

# Source type priority for indexing order
SOURCE_PRIORITY = [
    "trade_outcome", "decision_outcome", "cio_decision", "agent_synthesis",
    "fused_signal", "agent_result", "trade_review", "sec_form4",
    "news", "youtube", "social_post", "fred_series", "research_finding",
    "brave_cache",
]

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

def embed_text(text, model):
    data = json.dumps({"model": model, "prompt": text[:2000]}).encode()
    req = urllib.request.Request(f"{OLLAMA_URL}/api/embeddings", data=data,
        headers={"Content-Type": "application/json"})
    start = time.monotonic()
    with urllib.request.urlopen(req, timeout=120) as resp:
        result = json.loads(resp.read())
    lat = round((time.monotonic() - start) * 1000, 1)
    return result.get("embedding", []), lat

def log(msg):
    print(f"{datetime.now().strftime('%H:%M:%S')} [phase2e-build] {msg}", flush=True)

def unload_restore():
    log("Unloading qwen3-embedding:8b...")
    try:
        urllib.request.urlopen(urllib.request.Request(f"{OLLAMA_URL}/api/generate",
            data=json.dumps({"model": "qwen3-embedding:8b", "keep_alive": 0, "prompt": ""}).encode(),
            headers={"Content-Type": "application/json"}), timeout=15)
    except Exception: pass
    time.sleep(3)
    log("Restoring nomic-embed-text...")
    try:
        urllib.request.urlopen(urllib.request.Request(f"{OLLAMA_URL}/api/embeddings",
            data=json.dumps({"model": "nomic-embed-text", "prompt": "restore"}).encode(),
            headers={"Content-Type": "application/json"}), timeout=30)
    except Exception: pass
    log("Restoring qwen3:14b...")
    try:
        urllib.request.urlopen(urllib.request.Request(f"{OLLAMA_URL}/api/generate",
            data=json.dumps({"model": "qwen3:14b", "prompt": "test", "options": {"num_predict": 1}}).encode(),
            headers={"Content-Type": "application/json"}), timeout=120)
    except Exception: pass

def main():
    p = argparse.ArgumentParser(description="Build Phase 2E qwen3 global shadow index")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    p.add_argument("--source-table", default="content_embeddings")
    p.add_argument("--target-table", default="content_embeddings_qwen3_shadow")
    p.add_argument("--model", default="qwen3-embedding:8b")
    p.add_argument("--batch-size", type=int, default=25)
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--max-runtime-min", type=int, default=180)
    p.add_argument("--resume", action="store_true")
    p.add_argument("--source-types", default=None)
    p.add_argument("--json-output", default=None)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    log("Phase 2E — Build qwen3 global shadow embedding index")
    log(f"Source: {args.source_table} | Target: {args.target_table} | Model: {args.model}")
    log(f"Batch: {args.batch_size} | Max runtime: {args.max_runtime_min}m | Resume: {args.resume}")
    log("Production content_embeddings will NOT be altered.")

    conn = get_conn()
    cur = conn.cursor()

    # Counts
    cur.execute(f"SELECT COUNT(*) FROM {args.source_table}")
    src_total = cur.fetchone()[0]
    cur.execute(f"SELECT COUNT(*) FROM {args.target_table}")
    tgt_before = cur.fetchone()[0]
    log(f"Source rows: {src_total} | Target before: {tgt_before}")

    # Get already-indexed keys for resume
    existing = set()
    if args.resume:
        cur.execute(f"SELECT source_type, source_id FROM {args.target_table} WHERE embedding_model=%s",
                    (args.model,))
        existing = set((r[0], r[1]) for r in cur.fetchall())
        log(f"Resume: {len(existing)} already indexed")

    # Build source list in priority order
    type_filter = ""
    if args.source_types:
        types = [t.strip() for t in args.source_types.split(",")]
        ph = ",".join(["%s"] * len(types))
        type_filter = f"AND source_type IN ({ph})"

    # Fetch by priority order
    all_sources = []
    for st in SOURCE_PRIORITY:
        cur.execute(f"""SELECT id, source_type, source_id, title, created_at
                        FROM {args.source_table}
                        WHERE source_type = %s {type_filter}
                        ORDER BY created_at DESC""",
                    [st] + ([t.strip() for t in args.source_types.split(",")] if args.source_types else []))
        all_sources.extend(cur.fetchall())

    # Also catch any source types not in priority list
    cur.execute(f"""SELECT DISTINCT source_type FROM {args.source_table}""")
    all_types = set(r[0] for r in cur.fetchall())
    missing_types = all_types - set(SOURCE_PRIORITY)
    for st in sorted(missing_types):
        cur.execute(f"""SELECT id, source_type, source_id, title, created_at
                        FROM {args.source_table} WHERE source_type = %s
                        ORDER BY created_at DESC""", [st])
        all_sources.extend(cur.fetchall())

    cols = ["id", "source_type", "source_id", "title", "created_at"]
    sources = [dict(zip(cols, r)) for r in all_sources]
    log(f"Total source candidates: {len(sources)}")

    # Filter out already indexed
    pending = [s for s in sources if (s["source_type"], s["source_id"]) not in existing]
    if args.limit > 0:
        pending = pending[:args.limit]
    log(f"Pending after resume filter: {len(pending)}")

    # Source mix
    type_dist = {}
    for s in pending:
        type_dist[s["source_type"]] = type_dist.get(s["source_type"], 0) + 1
    log(f"Pending by type: {type_dist}")

    if args.dry_run:
        log("=== DRY RUN ===")
        log(f"Would embed {len(pending)} documents with {args.model}")
        log(f"Estimated time: ~{len(pending) * 0.3:.0f}s ({len(pending)} docs x ~300ms)")
        log(f"Target table: {args.target_table}")
        log("No production data would be modified.")
        log("=== DRY RUN COMPLETE ===")
        conn.close()
        return

    if not pending:
        log("All docs already indexed. Shadow index is complete.")
        conn.close()
        return

    # Process
    total = len(pending)
    success = 0
    failed = 0
    skipped_no_title = 0
    latencies = []
    start_time = time.monotonic()
    budget_sec = args.max_runtime_min * 60

    for i, doc in enumerate(pending):
        elapsed = time.monotonic() - start_time
        if elapsed >= budget_sec:
            log(f"Max runtime reached ({args.max_runtime_min}m). Stopping cleanly.")
            break

        title = (doc.get("title") or "")[:300].strip()
        if not title:
            skipped_no_title += 1
            continue

        content_hash = hashlib.sha256(title.encode()).hexdigest()[:16]

        try:
            embedding, lat = embed_text(title, model=args.model)
            if not embedding:
                failed += 1
                continue

            cur.execute(f"""
                INSERT INTO {args.target_table}
                    (source_type, source_id, title, content_preview, content_hash,
                     embedding, embedding_model, embedding_dim, embedding_latency_ms,
                     source_created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (source_type, source_id, embedding_model) DO NOTHING
            """, (doc["source_type"], doc["source_id"], title, title[:200],
                  content_hash, json.dumps(embedding), args.model, len(embedding),
                  lat, doc.get("created_at")))
            conn.commit()
            success += 1
            latencies.append(lat)

        except Exception as e:
            conn.rollback()
            failed += 1
            if args.verbose:
                log(f"  ERROR: {doc['source_type']}:{doc['source_id']}: {e}")

        if (i + 1) % args.batch_size == 0:
            processed = i + 1
            avg_lat = sum(latencies[-args.batch_size:]) / max(len(latencies[-args.batch_size:]), 1)
            rate = processed / max(elapsed, 1)
            eta = (total - processed) / rate if rate > 0 else 0
            log(f"Progress: {processed}/{total} ({processed*100//total}%) | "
                f"ok={success} fail={failed} | avg_lat={avg_lat:.0f}ms | ETA={eta:.0f}s")

    elapsed_total = round(time.monotonic() - start_time, 1)
    avg_latency = round(sum(latencies) / max(len(latencies), 1), 1)

    cur.execute(f"SELECT COUNT(*) FROM {args.target_table}")
    final_count = cur.fetchone()[0]

    coverage_pct = round(100 * final_count / max(src_total, 1), 1)

    log("=" * 60)
    log("Phase 2E Shadow Build Summary")
    log("=" * 60)
    log(f"Source rows:        {src_total}")
    log(f"Target before:      {tgt_before}")
    log(f"Pending:            {total}")
    log(f"Success:            {success}")
    log(f"Failed:             {failed}")
    log(f"Skipped (no title): {skipped_no_title}")
    log(f"Avg latency:        {avg_latency}ms")
    log(f"Total time:         {elapsed_total}s ({elapsed_total/60:.1f}m)")
    log(f"Final shadow count: {final_count}")
    log(f"Coverage:           {coverage_pct}%")
    log(f"Complete:           {'YES' if final_count >= src_total else 'NO — rerun with --resume'}")
    log("=" * 60)

    summary = {
        "timestamp": datetime.now().isoformat(), "model": args.model,
        "source_total": src_total, "target_before": tgt_before,
        "pending": total, "success": success, "failed": failed,
        "skipped_no_title": skipped_no_title, "avg_latency_ms": avg_latency,
        "total_time_s": elapsed_total, "final_shadow_count": final_count,
        "coverage_pct": coverage_pct,
        "source_distribution": type_dist, "production_changed": False,
    }
    if args.json_output:
        Path(args.json_output).write_text(json.dumps(summary, indent=2, default=str))
        log(f"JSON summary: {args.json_output}")

    conn.close()
    unload_restore()
    log("Done.")

if __name__ == "__main__":
    main()
