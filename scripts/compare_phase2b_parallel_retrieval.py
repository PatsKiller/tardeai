#!/usr/bin/env python3
"""compare_phase2b_parallel_retrieval.py — Compare retrieval quality.
Read-only against production. No routing changes."""

import argparse
import json
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent

OLLAMA_URL = "http://localhost:11434"

# Same 40 queries from Phase 2A (embedding_ab_baseline.py)
QUERIES = [
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


def cosine_sim(a, b):
    if not a or not b:
        return 0.0
    import numpy as np
    a, b = np.array(a, dtype=np.float32), np.array(b, dtype=np.float32)
    norm = np.linalg.norm(a) * np.linalg.norm(b)
    return float(np.dot(a, b) / norm) if norm > 0 else 0.0


def log(msg):
    print(f"{datetime.now().strftime('%H:%M:%S')} [phase2b-compare] {msg}", flush=True)


def search_table(conn, table, query_vec, top_k=10, fetch_limit=200):
    """Fetch embeddings from table, compute cosine sim in Python, return top-k."""
    cur = conn.cursor()
    cur.execute(f"""
        SELECT source_type, source_id, title, embedding
        FROM {table}
        WHERE embedding IS NOT NULL
        ORDER BY indexed_at DESC
        LIMIT %s
    """, (fetch_limit,))
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    cur.close()

    scored = []
    for row in rows:
        emb = row.get("embedding")
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
        scored.append({
            "source_type": row["source_type"],
            "source_id": row["source_id"],
            "title": (row.get("title") or "")[:80],
            "score": round(sim, 4),
        })
    scored.sort(key=lambda x: -x["score"])
    return scored[:top_k]


def search_production_table(conn, table, query_vec, top_k=10, fetch_limit=200):
    """Fetch from production content_embeddings (uses created_at not indexed_at)."""
    cur = conn.cursor()
    cur.execute(f"""
        SELECT source_type, source_id, title, embedding
        FROM {table}
        WHERE embedding IS NOT NULL
        ORDER BY created_at DESC
        LIMIT %s
    """, (fetch_limit,))
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    cur.close()

    scored = []
    for row in rows:
        emb = row.get("embedding")
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
        scored.append({
            "source_type": row["source_type"],
            "source_id": row["source_id"],
            "title": (row.get("title") or "")[:80],
            "score": round(sim, 4),
        })
    scored.sort(key=lambda x: -x["score"])
    return scored[:top_k]


def compute_overlap(baseline_results, candidate_results, k):
    """Compute overlap of top-k results by (source_type, source_id)."""
    baseline_keys = set((r["source_type"], r["source_id"]) for r in baseline_results[:k])
    candidate_keys = set((r["source_type"], r["source_id"]) for r in candidate_results[:k])
    if not baseline_keys and not candidate_keys:
        return 1.0
    if not baseline_keys or not candidate_keys:
        return 0.0
    return len(baseline_keys & candidate_keys) / len(baseline_keys | candidate_keys)


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
    parser = argparse.ArgumentParser(description="Compare Phase 2B parallel retrieval quality")
    parser.add_argument("--baseline-model", default="nomic-embed-text")
    parser.add_argument("--candidate-model", default="qwen3-embedding:8b")
    parser.add_argument("--baseline-table", default="content_embeddings")
    parser.add_argument("--candidate-table", default="content_embeddings_qwen3_test")
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--output-json", default=None)
    parser.add_argument("--output-md", default=None)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    log("Phase 2B — Parallel Retrieval Quality Comparison")
    log(f"Baseline: {args.baseline_model} (table: {args.baseline_table})")
    log(f"Candidate: {args.candidate_model} (table: {args.candidate_table})")
    log(f"Top-K: {args.top_k} | Queries: {len(QUERIES)}")
    log("Read-only. No routing changes.")

    conn = get_db_connection()

    # Verify candidate table exists and has data
    cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*) FROM {args.candidate_table}")
    candidate_count = cur.fetchone()[0]
    log(f"Candidate table has {candidate_count} rows")
    if candidate_count == 0:
        log("ABORT: Candidate table is empty. Run build_phase2b_parallel_embedding_index.py first.")
        cur.close()
        conn.close()
        sys.exit(1)

    cur.execute(f"SELECT COUNT(*) FROM {args.baseline_table} WHERE embedding IS NOT NULL")
    baseline_count = cur.fetchone()[0]
    log(f"Baseline table has {baseline_count} rows with embeddings")
    cur.close()

    query_results = []
    baseline_latencies = []
    candidate_latencies = []
    overlap_5_scores = []
    overlap_10_scores = []
    baseline_avg_sims = []
    candidate_avg_sims = []
    baseline_diversities = []
    candidate_diversities = []
    baseline_empty = 0
    candidate_empty = 0

    for i, query in enumerate(QUERIES):
        # Embed with baseline model
        b_vec, b_lat = embed_text(query, args.baseline_model)
        baseline_latencies.append(b_lat)

        # Embed with candidate model
        c_vec, c_lat = embed_text(query, args.candidate_model)
        candidate_latencies.append(c_lat)

        # Search baseline table
        if b_vec:
            b_results = search_production_table(conn, args.baseline_table, b_vec, top_k=args.top_k, fetch_limit=200)
        else:
            b_results = []
            baseline_empty += 1

        # Search candidate table
        if c_vec:
            c_results = search_table(conn, args.candidate_table, c_vec, top_k=args.top_k, fetch_limit=candidate_count)
        else:
            c_results = []
            candidate_empty += 1

        # Metrics
        top5_overlap = compute_overlap(b_results, c_results, 5)
        top10_overlap = compute_overlap(b_results, c_results, min(args.top_k, 10))
        overlap_5_scores.append(top5_overlap)
        overlap_10_scores.append(top10_overlap)

        b_avg_sim = sum(r["score"] for r in b_results) / max(len(b_results), 1)
        c_avg_sim = sum(r["score"] for r in c_results) / max(len(c_results), 1)
        baseline_avg_sims.append(b_avg_sim)
        candidate_avg_sims.append(c_avg_sim)

        b_diversity = len(set(r["source_type"] for r in b_results))
        c_diversity = len(set(r["source_type"] for r in c_results))
        baseline_diversities.append(b_diversity)
        candidate_diversities.append(c_diversity)

        qr = {
            "query": query,
            "baseline_latency_ms": b_lat,
            "candidate_latency_ms": c_lat,
            "baseline_results": b_results[:5],
            "candidate_results": c_results[:5],
            "top5_overlap": round(top5_overlap, 4),
            "top10_overlap": round(top10_overlap, 4),
            "baseline_avg_sim": round(b_avg_sim, 4),
            "candidate_avg_sim": round(c_avg_sim, 4),
            "baseline_diversity": b_diversity,
            "candidate_diversity": c_diversity,
            "baseline_empty": len(b_results) == 0,
            "candidate_empty": len(c_results) == 0,
        }
        query_results.append(qr)

        if args.verbose:
            log(f"  Q{i+1:02d}: overlap5={top5_overlap:.2f} overlap10={top10_overlap:.2f} "
                f"b_sim={b_avg_sim:.3f} c_sim={c_avg_sim:.3f} "
                f"b_div={b_diversity} c_div={c_diversity} "
                f"b_lat={b_lat:.0f}ms c_lat={c_lat:.0f}ms")

    conn.close()

    # Aggregate metrics
    avg_overlap_5 = sum(overlap_5_scores) / max(len(overlap_5_scores), 1)
    avg_overlap_10 = sum(overlap_10_scores) / max(len(overlap_10_scores), 1)
    avg_b_sim = sum(baseline_avg_sims) / max(len(baseline_avg_sims), 1)
    avg_c_sim = sum(candidate_avg_sims) / max(len(candidate_avg_sims), 1)
    avg_b_lat = sum(baseline_latencies) / max(len(baseline_latencies), 1)
    avg_c_lat = sum(candidate_latencies) / max(len(candidate_latencies), 1)
    avg_b_div = sum(baseline_diversities) / max(len(baseline_diversities), 1)
    avg_c_div = sum(candidate_diversities) / max(len(candidate_diversities), 1)

    # Determine verdict
    sim_advantage = avg_c_sim - avg_b_sim
    div_advantage = avg_c_div - avg_b_div
    lat_ratio = avg_c_lat / max(avg_b_lat, 1)

    if avg_c_sim > avg_b_sim + 0.02 and avg_c_div >= avg_b_div:
        verdict = "QWEN3_BETTER"
    elif avg_b_sim > avg_c_sim + 0.02 and avg_b_div >= avg_c_div:
        verdict = "NOMIC_BETTER"
    elif abs(sim_advantage) < 0.02 and avg_overlap_5 < 0.5:
        verdict = "HYBRID_RECOMMENDED"
    else:
        verdict = "INCONCLUSIVE"

    log("=" * 60)
    log("Phase 2B Retrieval Comparison Summary")
    log("=" * 60)
    log(f"Queries tested:        {len(QUERIES)}")
    log(f"Avg top-5 overlap:     {avg_overlap_5:.3f}")
    log(f"Avg top-10 overlap:    {avg_overlap_10:.3f}")
    log(f"Baseline avg sim:      {avg_b_sim:.4f}")
    log(f"Candidate avg sim:     {avg_c_sim:.4f}")
    log(f"Baseline avg latency:  {avg_b_lat:.0f}ms")
    log(f"Candidate avg latency: {avg_c_lat:.0f}ms")
    log(f"Baseline avg diversity:{avg_b_div:.1f}")
    log(f"Candidate avg diversity:{avg_c_div:.1f}")
    log(f"Baseline empty:        {baseline_empty}/{len(QUERIES)}")
    log(f"Candidate empty:       {candidate_empty}/{len(QUERIES)}")
    log(f"Verdict:               {verdict}")
    log("=" * 60)

    report = {
        "timestamp": datetime.now().isoformat(),
        "baseline_model": args.baseline_model,
        "candidate_model": args.candidate_model,
        "baseline_table": args.baseline_table,
        "candidate_table": args.candidate_table,
        "baseline_doc_count": baseline_count,
        "candidate_doc_count": candidate_count,
        "query_count": len(QUERIES),
        "top_k": args.top_k,
        "aggregate": {
            "avg_top5_overlap": round(avg_overlap_5, 4),
            "avg_top10_overlap": round(avg_overlap_10, 4),
            "baseline_avg_similarity": round(avg_b_sim, 4),
            "candidate_avg_similarity": round(avg_c_sim, 4),
            "similarity_advantage": round(sim_advantage, 4),
            "baseline_avg_latency_ms": round(avg_b_lat, 1),
            "candidate_avg_latency_ms": round(avg_c_lat, 1),
            "latency_ratio": round(lat_ratio, 2),
            "baseline_avg_diversity": round(avg_b_div, 2),
            "candidate_avg_diversity": round(avg_c_div, 2),
            "baseline_empty_queries": baseline_empty,
            "candidate_empty_queries": candidate_empty,
        },
        "verdict": verdict,
        "production_changed": False,
        "routing_changed": False,
        "query_results": query_results,
    }

    if args.output_json:
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
        log(f"JSON report written to {args.output_json}")

    if args.output_md:
        md = generate_markdown_report(report)
        Path(args.output_md).write_text(md)
        log(f"Markdown report written to {args.output_md}")

    # Unload candidate, restore nomic
    unload_candidate_restore_nomic()
    log("Done.")


def generate_markdown_report(report):
    """Generate a markdown report from the comparison results."""
    agg = report["aggregate"]
    lines = []
    lines.append("# Phase 2B Parallel Retrieval Quality Comparison")
    lines.append("")
    lines.append(f"**Date:** {report['timestamp']}")
    lines.append(f"**Baseline:** {report['baseline_model']} (table: {report['baseline_table']}, {report['baseline_doc_count']} docs)")
    lines.append(f"**Candidate:** {report['candidate_model']} (table: {report['candidate_table']}, {report['candidate_doc_count']} docs)")
    lines.append(f"**Queries:** {report['query_count']} | **Top-K:** {report['top_k']}")
    lines.append(f"**Production changed:** {report['production_changed']} | **Routing changed:** {report['routing_changed']}")
    lines.append("")
    lines.append("## Aggregate Metrics")
    lines.append("")
    lines.append("| Metric | Baseline | Candidate | Delta |")
    lines.append("|--------|----------|-----------|-------|")
    lines.append(f"| Avg Similarity | {agg['baseline_avg_similarity']:.4f} | {agg['candidate_avg_similarity']:.4f} | {agg['similarity_advantage']:+.4f} |")
    lines.append(f"| Avg Latency (ms) | {agg['baseline_avg_latency_ms']:.0f} | {agg['candidate_avg_latency_ms']:.0f} | {agg['candidate_avg_latency_ms'] - agg['baseline_avg_latency_ms']:+.0f} |")
    lines.append(f"| Avg Diversity | {agg['baseline_avg_diversity']:.2f} | {agg['candidate_avg_diversity']:.2f} | {agg['candidate_avg_diversity'] - agg['baseline_avg_diversity']:+.2f} |")
    lines.append(f"| Avg Top-5 Overlap | {agg['avg_top5_overlap']:.4f} | -- | -- |")
    lines.append(f"| Avg Top-10 Overlap | {agg['avg_top10_overlap']:.4f} | -- | -- |")
    lines.append(f"| Empty Queries | {agg['baseline_empty_queries']} | {agg['candidate_empty_queries']} | -- |")
    lines.append("")
    lines.append(f"## Verdict: **{report['verdict']}**")
    lines.append("")

    verdict_notes = {
        "QWEN3_BETTER": "Qwen3 embedding model shows higher similarity scores and equal or better diversity. Consider promotion to production.",
        "NOMIC_BETTER": "Nomic embedding model retains better retrieval quality. Keep current production model.",
        "HYBRID_RECOMMENDED": "Models retrieve substantially different documents with similar quality. A hybrid approach may capture broader relevant content.",
        "INCONCLUSIVE": "No clear winner. Differences are within noise margin. Further testing with more queries or full-text embeddings recommended.",
    }
    lines.append(verdict_notes.get(report["verdict"], ""))
    lines.append("")

    # Per-query details for first 10
    lines.append("## Per-Query Results (first 10)")
    lines.append("")
    for i, qr in enumerate(report["query_results"][:10]):
        lines.append(f"### Q{i+1}: {qr['query']}")
        lines.append("")
        lines.append(f"- Top-5 overlap: {qr['top5_overlap']:.2f} | Top-10 overlap: {qr['top10_overlap']:.2f}")
        lines.append(f"- Baseline avg sim: {qr['baseline_avg_sim']:.4f} | Candidate avg sim: {qr['candidate_avg_sim']:.4f}")
        lines.append(f"- Baseline diversity: {qr['baseline_diversity']} | Candidate diversity: {qr['candidate_diversity']}")
        lines.append(f"- Baseline latency: {qr['baseline_latency_ms']:.0f}ms | Candidate latency: {qr['candidate_latency_ms']:.0f}ms")
        lines.append("")
        lines.append("**Baseline top-3:**")
        for j, r in enumerate(qr.get("baseline_results", [])[:3]):
            lines.append(f"  {j+1}. [{r['source_type']}:{r['source_id']}] score={r['score']:.4f} — {r['title']}")
        lines.append("")
        lines.append("**Candidate top-3:**")
        for j, r in enumerate(qr.get("candidate_results", [])[:3]):
            lines.append(f"  {j+1}. [{r['source_type']}:{r['source_id']}] score={r['score']:.4f} — {r['title']}")
        lines.append("")

    lines.append("---")
    lines.append("*Generated by compare_phase2b_parallel_retrieval.py*")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
