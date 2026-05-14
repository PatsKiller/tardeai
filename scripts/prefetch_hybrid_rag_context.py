#!/usr/bin/env python3
"""prefetch_hybrid_rag_context.py — Stage A: Build and persist hybrid RAG context.

Loads qwen3-embedding:8b + nomic-embed-text, builds hybrid context for selected
deep overnight jobs, persists results to a JSON cache file, then unloads
qwen3-embedding:8b. gemma3-overnight must NOT be resident during this stage.

PILOT ONLY. Read-only from embedding tables. No production changes.

Usage:
    .venv/bin/python scripts/prefetch_hybrid_rag_context.py \
        --limit 20 \
        --job-types strategy_classification,manual_journal_review \
        --output data/hybrid_rag_prefetch_cache.json \
        --json
"""
import argparse
import json
import logging
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))

OLLAMA_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

log = logging.getLogger("prefetch-hybrid")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")


def _get_conn():
    import psycopg2
    env_vars = {}
    for line in (PROJ / ".env").read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env_vars[k.strip()] = v.strip()
    return psycopg2.connect(
        host=env_vars.get("DB_HOST", "localhost"),
        dbname=env_vars.get("DB_NAME", "trade_ai"),
        user=env_vars.get("DB_USER", "trade_ai"),
        password=env_vars.get("DB_PASSWORD", ""),
    )


def _ollama_ps():
    """Get currently loaded models."""
    try:
        req = urllib.request.Request(f"{OLLAMA_URL}/api/ps")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        return [m.get("name", "") for m in data.get("models", [])]
    except Exception:
        return []


def _unload_model(model):
    """Unload a model from Ollama."""
    log.info(f"Unloading {model}...")
    try:
        urllib.request.urlopen(urllib.request.Request(
            f"{OLLAMA_URL}/api/generate",
            data=json.dumps({"model": model, "keep_alive": 0, "prompt": ""}).encode(),
            headers={"Content-Type": "application/json"}), timeout=15)
    except Exception as e:
        log.warning(f"  Unload warning: {e}")
    time.sleep(2)


def _load_model(model, prompt="test"):
    """Warm-load a model into Ollama."""
    log.info(f"Loading {model}...")
    try:
        if "embed" in model:
            urllib.request.urlopen(urllib.request.Request(
                f"{OLLAMA_URL}/api/embeddings",
                data=json.dumps({"model": model, "prompt": prompt}).encode(),
                headers={"Content-Type": "application/json"}), timeout=60)
        else:
            urllib.request.urlopen(urllib.request.Request(
                f"{OLLAMA_URL}/api/generate",
                data=json.dumps({"model": model, "prompt": prompt, "options": {"num_predict": 1}}).encode(),
                headers={"Content-Type": "application/json"}), timeout=60)
        log.info(f"  {model} loaded")
    except Exception as e:
        log.warning(f"  Load warning: {e}")


def _verify_no_gemma():
    """Verify gemma3-overnight is NOT resident."""
    loaded = _ollama_ps()
    for m in loaded:
        if "gemma" in m.lower():
            log.error(f"ABORT: {m} is resident — Stage A requires no gemma co-residency")
            return False
    return True


def get_pending_jobs(conn, job_types, limit):
    """Get pending jobs from deep overnight queue."""
    cur = conn.cursor()
    types = [t.strip() for t in job_types.split(",")]
    placeholders = ",".join(["%s"] * len(types))
    cur.execute(f"""
        SELECT id, job_type, symbol, trade_id, journal_id,
               priority_tier, priority_score, reason_codes,
               last_qwen_summary, metadata_json
        FROM deep_overnight_llm_queue
        WHERE status = 'pending' AND job_type IN ({placeholders})
        ORDER BY priority_score DESC, queued_at ASC
        LIMIT %s
    """, types + [limit])
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def main():
    parser = argparse.ArgumentParser(description="Stage A: Prefetch hybrid RAG context")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--job-types", required=True, help="Comma-separated job types")
    parser.add_argument("--output", default="data/hybrid_rag_prefetch_cache.json")
    parser.add_argument("--final-k", type=int, default=10)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    log.info("=" * 60)
    log.info("STAGE A — Hybrid RAG Context Prefetch")
    log.info("=" * 60)

    # Safety: verify no gemma resident
    if not _verify_no_gemma():
        log.error("Cannot proceed — unload gemma3-overnight first")
        sys.exit(1)

    # Unload qwen3:14b to make room for qwen3-embedding:8b
    loaded = _ollama_ps()
    unloaded_models = []
    for m in loaded:
        if "qwen3:14b" in m or "qwen3:latest" in m:
            _unload_model(m)
            unloaded_models.append(m)

    # Load qwen3-embedding:8b (nomic-embed-text should already be resident)
    _load_model("qwen3-embedding:8b", prompt="test embedding")

    # Verify both embedding models are available
    loaded_after = _ollama_ps()
    log.info(f"Models after setup: {loaded_after}")

    conn = _get_conn()
    jobs = get_pending_jobs(conn, args.job_types, args.limit)
    log.info(f"Found {len(jobs)} pending jobs")

    if args.dry_run:
        log.info("DRY RUN — would prefetch context for these jobs:")
        for j in jobs:
            log.info(f"  #{j['id']}: {j['job_type']} {j.get('symbol', '?')}")
        _unload_model("qwen3-embedding:8b")
        for m in unloaded_models:
            _load_model(m)
        conn.close()
        return

    # Prefetch hybrid context for each job
    from hybrid_rag_context_adapter import get_hybrid_context

    cache = {"stage": "A", "timestamp": datetime.now(timezone.utc).isoformat(),
             "jobs": {}, "metrics": {"total": 0, "success": 0, "failed": 0}}
    start = time.monotonic()

    for i, job in enumerate(jobs, 1):
        jid = str(job["id"])
        symbol = job.get("symbol") or ""
        query = f"{symbol} {job['job_type']}"
        log.info(f"[{i}/{len(jobs)}] Prefetching #{jid}: {job['job_type']} {symbol}")

        try:
            result = get_hybrid_context(
                query=query, symbol=symbol if symbol else None,
                workflow=job["job_type"], final_k=args.final_k)

            cache["jobs"][jid] = {
                "job_id": job["id"],
                "job_type": job["job_type"],
                "symbol": symbol,
                "context_text": result.get("final_context_text", ""),
                "metrics": result.get("metrics", {}),
                "warnings": result.get("warnings", []),
                "result_count": len(result.get("results", [])),
            }
            m = result.get("metrics", {})
            log.info(f"  sources={m.get('source_type_count',0)} "
                     f"nomic={m.get('nomic_only_count',0)} "
                     f"qwen3={m.get('qwen3_only_count',0)} "
                     f"consensus={m.get('consensus_count',0)} "
                     f"lat={m.get('total_latency_ms',0):.0f}ms "
                     f"fallback={m.get('fallback_used',False)}")
            cache["metrics"]["success"] += 1
        except Exception as e:
            log.error(f"  FAILED: {e}")
            cache["jobs"][jid] = {
                "job_id": job["id"], "job_type": job["job_type"],
                "symbol": symbol, "context_text": "", "error": str(e)}
            cache["metrics"]["failed"] += 1

        cache["metrics"]["total"] += 1

    elapsed = round(time.monotonic() - start, 1)
    cache["metrics"]["elapsed_seconds"] = elapsed
    cache["metrics"]["avg_latency_ms"] = round(
        sum(j.get("metrics", {}).get("total_latency_ms", 0)
            for j in cache["jobs"].values() if isinstance(j.get("metrics"), dict))
        / max(cache["metrics"]["success"], 1), 1)

    # Write cache
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(cache, indent=2, default=str))
    log.info(f"Cache written: {args.output} ({cache['metrics']['success']}/{cache['metrics']['total']} jobs)")

    conn.close()

    # Stage A cleanup: unload qwen3-embedding, restore qwen3:14b
    log.info("Stage A cleanup...")
    _unload_model("qwen3-embedding:8b")
    for m in unloaded_models:
        _load_model(m)

    log.info(f"Final models: {_ollama_ps()}")
    log.info(f"Stage A complete in {elapsed}s")

    if args.json:
        print(json.dumps(cache["metrics"], indent=2, default=str))


if __name__ == "__main__":
    main()
