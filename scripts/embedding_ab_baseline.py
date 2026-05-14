#!/usr/bin/env python3
"""embedding_ab_baseline.py — Phase 2A embedding A/B comparison tool.

Compares production nomic-embed-text against candidate qwen3-embedding:8b
using a safe, isolated retrieval benchmark. Does NOT overwrite production
embeddings, change production retrieval, or modify cron/.env.

Usage:
    .venv/bin/python scripts/embedding_ab_baseline.py --dry-run
    .venv/bin/python scripts/embedding_ab_baseline.py --no-candidate-ok
    .venv/bin/python scripts/embedding_ab_baseline.py --json --output results.json

Does NOT touch broker, holdings, execution, or trading behavior.
"""

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))

OLLAMA_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

# Default queries from docs/v4_1_phase2_embedding_ab_queries.md
DEFAULT_QUERIES = [
    "Show current portfolio composition and allocation",
    "What are the largest positions by market value?",
    "Find recent analysis for AVAV",
    "What is the current watchlist thesis for RKLB?",
    "Find recovery watch evidence for TDG",
    "What changed in RTX after stop-out?",
    "Show recent closed trades with bad exits",
    "Find failed breakout trades in the journal",
    "What patterns exist in automated journal entries?",
    "Show journal evidence for early exits",
    "Find latest journal review for manual trades",
    "Show journal entries mentioning stop placement",
    "Show risk synthesis evidence for unprotected positions",
    "Find portfolio concentration risk warnings",
    "Why did BLBD become a proposal?",
    "Find prior reasoning for swing trade proposals",
    "Show recent RAG curation approvals",
    "Find defense sector rotation evidence",
    "Show recent catalyst news for LMT",
    "Show prior CIO HOLD decisions with correct outcomes",
    "What fused signals exist for SCHD?",
    "Find strong convergent signals across agents",
    "Show insider or Form 4 evidence for defense stocks",
    "Find YouTube transcript intelligence for dividend investing",
    "Find strategy classifications with low confidence",
    "Show positions flagged for reclassification",
    "Find deep overnight results about risk management",
    "Show gemma3 analysis of recovery watch symbols",
    "Find agent intelligence rules for income strategies",
    "Find examples where MFE was high but realized profit was low",
    "Show covered call candidates that need review",
    "Find covered call scoring evidence for V",
    "Find stop-triggered analysis for defense positions",
    "Show recovery watch evidence for IRDM",
    "Show Maria research findings for growth stocks",
    "Show paper trades that hit targets",
    "Find recent insider buying activity",
    "Show YouTube evidence about market conditions",
    "Find RAG content rejected with reasons",
    "Find CIO recommendations that were wrong",
]


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
    print(f"{datetime.now().strftime('%H:%M:%S')} [ab-baseline] {msg}", flush=True)


def embed_text(text, model="nomic-embed-text"):
    """Get embedding from Ollama. Returns (vector, latency_ms) or (None, 0)."""
    try:
        start = time.monotonic()
        data = json.dumps({"model": model, "prompt": text[:2000]}).encode()
        req = urllib.request.Request(
            f"{OLLAMA_URL}/api/embeddings",
            data=data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read())
        latency = round((time.monotonic() - start) * 1000, 1)
        vec = result.get("embedding", [])
        return vec, latency
    except Exception as e:
        return None, 0


def cosine_sim(a, b):
    """Compute cosine similarity between two vectors."""
    if not a or not b or len(a) != len(b):
        return 0.0
    try:
        import numpy as np
        a, b = np.array(a), np.array(b)
        norm = np.linalg.norm(a) * np.linalg.norm(b)
        return float(np.dot(a, b) / norm) if norm > 0 else 0.0
    except Exception:
        return 0.0


def check_model_available(model):
    """Check if a model is available in Ollama."""
    try:
        req = urllib.request.Request(f"{OLLAMA_URL}/api/tags")
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        for m in data.get("models", []):
            if model in m.get("name", ""):
                return True
        return False
    except Exception:
        return False


def get_sample_docs(conn, limit=500, source_types=None):
    """Get a sample of documents from content_embeddings."""
    cur = conn.cursor()
    type_filter = ""
    params = [limit]
    if source_types:
        placeholders = ",".join(["%s"] * len(source_types))
        type_filter = f"AND source_type IN ({placeholders})"
        params = list(source_types) + [limit]

    cur.execute(f"""
        SELECT id, source_type, source_id, title, embedding
        FROM content_embeddings
        WHERE embedding IS NOT NULL
        {type_filter}
        ORDER BY created_at DESC
        LIMIT %s
    """, params)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def run_retrieval_test(query, docs, query_vec, top_k=5):
    """Run a retrieval test: compute cosine sim against all docs, return top-k."""
    if not query_vec:
        return []
    scored = []
    for doc in docs:
        emb = doc.get("embedding")
        if not emb:
            continue
        if isinstance(emb, str):
            try:
                emb = json.loads(emb)
            except Exception:
                continue
        elif isinstance(emb, dict):
            emb = emb.get("embedding", [])
        sim = cosine_sim(query_vec, emb)
        scored.append({"id": doc["id"], "source_type": doc["source_type"],
                       "title": (doc.get("title") or "")[:80], "score": round(sim, 4)})
    scored.sort(key=lambda x: -x["score"])
    return scored[:top_k]


def main():
    parser = argparse.ArgumentParser(description="Phase 2A embedding A/B baseline")
    parser.add_argument("--baseline-model", default="nomic-embed-text")
    parser.add_argument("--candidate-model", default="qwen3-embedding:8b")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--sample-size", type=int, default=500)
    parser.add_argument("--limit-docs", type=int, default=1000)
    parser.add_argument("--output", default=None)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--no-candidate-ok", action="store_true",
                        help="Continue even if candidate model is not installed")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--source-types", default=None,
                        help="Comma-separated source types to include")
    args = parser.parse_args()

    log(f"Phase 2A Embedding A/B Baseline")
    log(f"Baseline: {args.baseline_model}")
    log(f"Candidate: {args.candidate_model}")
    log(f"Sample size: {args.sample_size}, Doc limit: {args.limit_docs}")

    # Check models
    baseline_ok = check_model_available(args.baseline_model)
    candidate_ok = check_model_available(args.candidate_model)

    log(f"Baseline available: {baseline_ok}")
    log(f"Candidate available: {candidate_ok}")

    if not baseline_ok:
        log("ABORT: Baseline model not available")
        sys.exit(1)

    if not candidate_ok:
        if args.no_candidate_ok:
            log("WARN: Candidate not installed — running baseline-only mode")
        else:
            log("ABORT: Candidate not installed. Use --no-candidate-ok to continue")
            sys.exit(1)

    if args.dry_run:
        log("=== DRY RUN ===")
        log(f"Would test {len(DEFAULT_QUERIES)} queries against {args.sample_size} docs")
        log(f"Baseline: {args.baseline_model} ({'available' if baseline_ok else 'MISSING'})")
        log(f"Candidate: {args.candidate_model} ({'available' if candidate_ok else 'NOT INSTALLED'})")
        if not candidate_ok:
            log("Operator must approve: ollama pull qwen3-embedding:8b")
        log("No production embeddings would be changed")
        log("=== DRY RUN COMPLETE ===")

        if args.output:
            result = {
                "dry_run": True,
                "baseline_model": args.baseline_model,
                "candidate_model": args.candidate_model,
                "baseline_available": baseline_ok,
                "candidate_available": candidate_ok,
                "query_count": len(DEFAULT_QUERIES),
                "sample_size": args.sample_size,
                "production_changed": False,
            }
            Path(args.output).write_text(json.dumps(result, indent=2))
            log(f"Dry-run results written to {args.output}")
        return

    # Get document sample
    conn = get_db_connection()
    source_types = args.source_types.split(",") if args.source_types else None
    docs = get_sample_docs(conn, limit=args.limit_docs, source_types=source_types)
    log(f"Loaded {len(docs)} documents from content_embeddings")

    # Source type distribution
    type_dist = {}
    for d in docs:
        st = d.get("source_type", "unknown")
        type_dist[st] = type_dist.get(st, 0) + 1
    log(f"Source types: {type_dist}")

    queries = DEFAULT_QUERIES[:args.sample_size] if args.sample_size < len(DEFAULT_QUERIES) else DEFAULT_QUERIES

    # Run baseline
    log(f"Running baseline ({args.baseline_model}) on {len(queries)} queries...")
    baseline_results = []
    baseline_latencies = []
    baseline_empty = 0

    for i, q in enumerate(queries):
        vec, lat = embed_text(q, args.baseline_model)
        baseline_latencies.append(lat)
        if not vec:
            baseline_empty += 1
            baseline_results.append({"query": q, "top5": [], "latency_ms": 0})
            continue
        top5 = run_retrieval_test(q, docs, vec, top_k=5)
        baseline_results.append({"query": q, "top5": top5, "latency_ms": lat})
        if args.verbose and (i + 1) % 10 == 0:
            log(f"  Baseline: {i+1}/{len(queries)} done")

    baseline_dim = len(embed_text("test", args.baseline_model)[0] or [])
    log(f"Baseline: dim={baseline_dim}, avg_latency={sum(baseline_latencies)/max(len(baseline_latencies),1):.0f}ms, empty={baseline_empty}")

    # Run candidate if available
    candidate_results = []
    candidate_latencies = []
    candidate_empty = 0
    candidate_dim = 0

    if candidate_ok:
        log(f"Running candidate ({args.candidate_model}) on {len(queries)} queries...")
        for i, q in enumerate(queries):
            vec, lat = embed_text(q, args.candidate_model)
            candidate_latencies.append(lat)
            if not vec:
                candidate_empty += 1
                candidate_results.append({"query": q, "top5": [], "latency_ms": 0})
                continue
            # For candidate, we need candidate-embedded docs too
            # Since we only have nomic embeddings in DB, we can only compare
            # embedding characteristics, not retrieval against candidate index
            candidate_results.append({"query": q, "embedding_dim": len(vec), "latency_ms": lat})
            if args.verbose and (i + 1) % 10 == 0:
                log(f"  Candidate: {i+1}/{len(queries)} done")
        candidate_dim = len(embed_text("test", args.candidate_model)[0] or [])
        log(f"Candidate: dim={candidate_dim}, avg_latency={sum(candidate_latencies)/max(len(candidate_latencies),1):.0f}ms, empty={candidate_empty}")

    # Compute metrics
    baseline_avg_lat = sum(baseline_latencies) / max(len(baseline_latencies), 1)
    candidate_avg_lat = sum(candidate_latencies) / max(len(candidate_latencies), 1) if candidate_latencies else 0

    # Top-5 source diversity for baseline
    source_types_in_top5 = set()
    for r in baseline_results:
        for hit in r.get("top5", []):
            source_types_in_top5.add(hit.get("source_type"))

    result = {
        "timestamp": datetime.now().isoformat(),
        "production_changed": False,
        "rag_routing_changed": False,
        "baseline": {
            "model": args.baseline_model,
            "available": baseline_ok,
            "dimensions": baseline_dim,
            "query_count": len(queries),
            "avg_latency_ms": round(baseline_avg_lat, 1),
            "empty_results": baseline_empty,
            "source_diversity": len(source_types_in_top5),
            "doc_count": len(docs),
        },
        "candidate": {
            "model": args.candidate_model,
            "available": candidate_ok,
            "dimensions": candidate_dim,
            "query_count": len(queries) if candidate_ok else 0,
            "avg_latency_ms": round(candidate_avg_lat, 1) if candidate_ok else None,
            "empty_results": candidate_empty if candidate_ok else None,
            "tested": candidate_ok,
        },
        "comparison": {
            "candidate_tested": candidate_ok,
            "verdict": "NOT_TESTED" if not candidate_ok else "INCONCLUSIVE",
            "note": "Candidate not installed — operator must approve pull" if not candidate_ok else
                    "Candidate embeddings tested but no candidate index exists for retrieval comparison",
            "phase2b_recommended": candidate_ok,
        },
        "source_distribution": type_dist,
        "baseline_results": baseline_results if args.verbose else [],
    }

    # Write output
    if args.output:
        Path(args.output).write_text(json.dumps(result, indent=2, default=str))
        log(f"Results written to {args.output}")

    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        # Human-readable summary
        print(f"\n{'='*60}")
        print(f"Phase 2A Embedding A/B Baseline Report")
        print(f"{'='*60}")
        print(f"Date: {result['timestamp']}")
        print(f"Production changed: {result['production_changed']}")
        print(f"RAG routing changed: {result['rag_routing_changed']}")
        print(f"\nBaseline: {args.baseline_model}")
        print(f"  Dimensions: {baseline_dim}")
        print(f"  Avg latency: {baseline_avg_lat:.0f}ms")
        print(f"  Empty results: {baseline_empty}/{len(queries)}")
        print(f"  Source diversity: {len(source_types_in_top5)} types in top-5")
        print(f"  Docs sampled: {len(docs)}")
        print(f"\nCandidate: {args.candidate_model}")
        if candidate_ok:
            print(f"  Dimensions: {candidate_dim}")
            print(f"  Avg latency: {candidate_avg_lat:.0f}ms")
            print(f"  Empty results: {candidate_empty}/{len(queries)}")
        else:
            print(f"  NOT INSTALLED — run: ollama pull {args.candidate_model}")
        print(f"\nVerdict: {result['comparison']['verdict']}")
        print(f"Note: {result['comparison']['note']}")
        print(f"Phase 2B recommended: {result['comparison']['phase2b_recommended']}")
        print(f"\nPhase 2D promotion: BLOCKED pending operator approval")
        print(f"{'='*60}")

    conn.close()


if __name__ == "__main__":
    main()
