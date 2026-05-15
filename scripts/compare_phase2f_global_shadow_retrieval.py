#!/usr/bin/env python3
"""compare_phase2f_global_shadow_retrieval.py — Compare nomic vs qwen3-shadow
vs hybrid retrieval across the full 100-query Phase 2F global shadow query set.
Read-only against production. No routing changes."""

import argparse
import json
import re
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
OLLAMA_URL = "http://localhost:11434"

# ---------------------------------------------------------------------------
# Utility functions (self-contained, adapted from compare_phase2b)
# ---------------------------------------------------------------------------

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
    data = json.dumps({"model": model, "prompt": text[:2000]}).encode()
    start = time.monotonic()
    for attempt in range(3):
        try:
            req = urllib.request.Request(
                f"{OLLAMA_URL}/api/embeddings",
                data=data,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=180) as resp:
                result = json.loads(resp.read())
            latency = round((time.monotonic() - start) * 1000, 1)
            return result.get("embedding", []), latency
        except Exception as e:
            if attempt < 2:
                log(f"  embed retry {attempt+1} for {model}: {e}")
                time.sleep(3)
            else:
                log(f"  embed FAILED for {model}: {e}")
                return [], 0.0
    return [], 0.0


def cosine_sim(a, b):
    if not a or not b:
        return 0.0
    import numpy as np
    a, b = np.array(a, dtype=np.float32), np.array(b, dtype=np.float32)
    if len(a) != len(b):
        return 0.0
    norm = np.linalg.norm(a) * np.linalg.norm(b)
    return float(np.dot(a, b) / norm) if norm > 0 else 0.0


def log(msg):
    print(f"{datetime.now().strftime('%H:%M:%S')} [phase2f-compare] {msg}", flush=True)


# ---------------------------------------------------------------------------
# Query parsing
# ---------------------------------------------------------------------------

def parse_queries_from_md(filepath):
    """Parse numbered queries from a markdown file.
    Matches lines like '1. Some query text' or '42. Another query'."""
    queries = []
    pattern = re.compile(r"^\s*(\d+)\.\s+(.+)$")
    with open(filepath, "r") as f:
        for line in f:
            m = pattern.match(line)
            if m:
                queries.append(m.group(2).strip())
    return queries


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def search_table(conn, table, query_vec, top_k=10, fetch_limit=500):
    """Fetch embeddings from table, compute cosine sim in Python, return top-k.
    Tries indexed_at first, falls back to created_at for production tables."""
    cur = conn.cursor()

    # Determine ordering column
    cur.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = %s AND column_name IN ('indexed_at', 'created_at')
        ORDER BY ordinal_position
    """, (table,))
    cols_available = [r[0] for r in cur.fetchall()]
    order_col = "indexed_at" if "indexed_at" in cols_available else "created_at"

    cur.execute(f"""
        SELECT source_type, source_id, title, embedding
        FROM {table}
        WHERE embedding IS NOT NULL
        ORDER BY {order_col} DESC
        LIMIT %s
    """, (fetch_limit,))
    col_names = [d[0] for d in cur.description]
    rows = [dict(zip(col_names, r)) for r in cur.fetchall()]
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


# ---------------------------------------------------------------------------
# Hybrid merge
# ---------------------------------------------------------------------------

def hybrid_merge(nomic_results, qwen3_results, final_k=10, boost=1.15):
    """Merge nomic and qwen3 results with deduplication and consensus boost.
    - Deduplicate by (source_type, source_id).
    - Items found by both models get score boosted by `boost` factor.
    - Tag each item with model source: nomic / qwen3 / both.
    - Return top final_k by score."""

    seen = {}  # key -> merged item
    nomic_keys = set()
    qwen3_keys = set()

    for item in nomic_results:
        key = (item["source_type"], item["source_id"])
        nomic_keys.add(key)
        if key not in seen or item["score"] > seen[key]["score"]:
            seen[key] = {**item, "model_source": "nomic"}

    for item in qwen3_results:
        key = (item["source_type"], item["source_id"])
        qwen3_keys.add(key)
        if key in seen:
            # Consensus: keep the higher score and boost
            best_score = max(seen[key]["score"], item["score"])
            seen[key]["score"] = round(best_score * boost, 4)
            seen[key]["model_source"] = "both"
        else:
            seen[key] = {**item, "model_source": "qwen3"}

    merged = sorted(seen.values(), key=lambda x: -x["score"])
    consensus_count = len(nomic_keys & qwen3_keys)

    return merged[:final_k], consensus_count


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def compute_overlap(results_a, results_b, k):
    """Jaccard overlap of top-k results by (source_type, source_id)."""
    keys_a = set((r["source_type"], r["source_id"]) for r in results_a[:k])
    keys_b = set((r["source_type"], r["source_id"]) for r in results_b[:k])
    if not keys_a and not keys_b:
        return 1.0
    if not keys_a or not keys_b:
        return 0.0
    return len(keys_a & keys_b) / len(keys_a | keys_b)


def source_diversity(results):
    """Count distinct source_type values in results."""
    return len(set(r["source_type"] for r in results)) if results else 0


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

def unload_qwen3_restore_nomic():
    """Unload qwen3-embedding and restore nomic-embed-text."""
    log("Unloading qwen3-embedding model...")
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


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def generate_markdown_report(report):
    agg = report["aggregate"]
    lines = []
    lines.append("# Phase 2F Global Shadow Retrieval Comparison")
    lines.append("")
    lines.append(f"**Date:** {report['timestamp']}")
    lines.append(f"**Production model:** {report['production_model']} (table: {report['production_table']}, {report['production_doc_count']} docs)")
    lines.append(f"**Shadow model:** {report['shadow_model']} (table: {report['shadow_table']}, {report['shadow_doc_count']} docs)")
    lines.append(f"**Queries:** {report['query_count']} | **Top-K:** {report['top_k']} | **Final-K (hybrid):** {report['final_k']}")
    lines.append(f"**Hybrid enabled:** {report['hybrid_enabled']}")
    lines.append("")
    lines.append("## Aggregate Metrics")
    lines.append("")
    lines.append("| Metric | Nomic | Qwen3 | Hybrid | Delta (qwen3-nomic) |")
    lines.append("|--------|-------|-------|--------|---------------------|")
    lines.append(f"| Avg Similarity | {agg['nomic_avg_similarity']:.4f} | {agg['qwen3_avg_similarity']:.4f} | {agg.get('hybrid_avg_similarity', '--')} | {agg['similarity_delta']:+.4f} |")
    lines.append(f"| Avg Diversity | {agg['nomic_avg_diversity']:.2f} | {agg['qwen3_avg_diversity']:.2f} | {agg.get('hybrid_avg_diversity', '--')} | {agg['diversity_delta']:+.2f} |")
    lines.append(f"| Avg Latency (ms) | {agg['nomic_avg_latency_ms']:.0f} | {agg['qwen3_avg_latency_ms']:.0f} | -- | {agg['latency_delta']:+.0f} |")
    lines.append(f"| Avg Overlap (top-{report['top_k']}) | {agg['avg_overlap']:.4f} | -- | -- | -- |")
    lines.append(f"| Consensus Rate | {agg['consensus_rate']:.4f} | -- | -- | -- |")
    lines.append(f"| Empty Rate (nomic) | {agg['nomic_empty_rate']:.4f} | -- | -- | -- |")
    lines.append(f"| Empty Rate (qwen3) | {agg['qwen3_empty_rate']:.4f} | -- | -- | -- |")
    lines.append("")
    lines.append("### Method Winner Counts")
    lines.append("")
    winners = agg["method_winner_counts"]
    lines.append(f"- **Nomic wins (higher avg sim):** {winners.get('nomic', 0)}")
    lines.append(f"- **Qwen3 wins:** {winners.get('qwen3', 0)}")
    lines.append(f"- **Tie:** {winners.get('tie', 0)}")
    if report["hybrid_enabled"]:
        lines.append(f"- **Hybrid wins (vs best single):** {winners.get('hybrid', 0)}")
    lines.append("")
    lines.append(f"## Verdict: **{report['verdict']}**")
    lines.append("")

    verdict_notes = {
        "QWEN3_BETTER": "Qwen3 shadow model shows higher retrieval quality. Consider promoting shadow to production.",
        "NOMIC_BETTER": "Nomic production model retains better retrieval quality. Keep current configuration.",
        "HYBRID_RECOMMENDED": "Models retrieve substantially different documents with comparable quality. Hybrid merge captures broader relevant content.",
        "INCONCLUSIVE": "No clear winner. Differences are within noise margin. Extend testing or refine query set.",
    }
    lines.append(verdict_notes.get(report["verdict"], ""))
    lines.append("")

    # Per-query details (first 15)
    lines.append("## Per-Query Details (first 15)")
    lines.append("")
    for i, qr in enumerate(report["query_results"][:15]):
        lines.append(f"### Q{i+1}: {qr['query']}")
        lines.append("")
        lines.append(f"- Overlap: {qr['overlap']:.2f} | Consensus items: {qr.get('consensus_count', 0)}")
        lines.append(f"- Nomic avg sim: {qr['nomic_avg_sim']:.4f} | Qwen3 avg sim: {qr['qwen3_avg_sim']:.4f}")
        lines.append(f"- Nomic diversity: {qr['nomic_diversity']} | Qwen3 diversity: {qr['qwen3_diversity']}")
        lines.append(f"- Nomic latency: {qr['nomic_latency_ms']:.0f}ms | Qwen3 latency: {qr['qwen3_latency_ms']:.0f}ms")
        lines.append(f"- Model source tags: {qr.get('model_source_summary', {})}")
        lines.append("")
        lines.append("**Nomic top-3:**")
        for j, r in enumerate(qr.get("nomic_results", [])[:3]):
            lines.append(f"  {j+1}. [{r['source_type']}:{r['source_id']}] score={r['score']:.4f} -- {r['title']}")
        lines.append("")
        lines.append("**Qwen3 top-3:**")
        for j, r in enumerate(qr.get("qwen3_results", [])[:3]):
            lines.append(f"  {j+1}. [{r['source_type']}:{r['source_id']}] score={r['score']:.4f} -- {r['title']}")
        if qr.get("hybrid_results"):
            lines.append("")
            lines.append("**Hybrid top-3:**")
            for j, r in enumerate(qr["hybrid_results"][:3]):
                tag = r.get("model_source", "?")
                lines.append(f"  {j+1}. [{r['source_type']}:{r['source_id']}] score={r['score']:.4f} ({tag}) -- {r['title']}")
        lines.append("")

    lines.append("---")
    lines.append("*Generated by compare_phase2f_global_shadow_retrieval.py*")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Phase 2F: Compare nomic vs qwen3-shadow vs hybrid retrieval"
    )
    parser.add_argument(
        "--queries-file",
        default=str(PROJ / "docs/llm_fleet/phase2_embedding_ab/v4_1_phase2f_global_shadow_query_set.md"),
        help="Path to markdown file with numbered queries",
    )
    parser.add_argument("--production-table", default="content_embeddings",
                        help="Production embedding table (nomic)")
    parser.add_argument("--shadow-table", default="content_embeddings_qwen3_shadow",
                        help="Shadow embedding table (qwen3)")
    parser.add_argument("--production-model", default="nomic-embed-text",
                        help="Production embedding model")
    parser.add_argument("--shadow-model", default="qwen3-embedding:8b",
                        help="Shadow embedding model")
    parser.add_argument("--top-k", type=int, default=10,
                        help="Number of results per model per query")
    parser.add_argument("--final-k", type=int, default=10,
                        help="Number of results in hybrid merge output")
    parser.add_argument("--hybrid", action="store_true",
                        help="Enable hybrid merge comparison")
    parser.add_argument("--limit-queries", type=int, default=0,
                        help="Limit to first N queries (0 = all)")
    parser.add_argument("--output-json", default=None,
                        help="Path for JSON report output")
    parser.add_argument("--output-md", default=None,
                        help="Path for Markdown report output")
    parser.add_argument("--verbose", action="store_true",
                        help="Print per-query details")
    args = parser.parse_args()

    # Parse queries
    queries = parse_queries_from_md(args.queries_file)
    if not queries:
        log(f"ERROR: No queries parsed from {args.queries_file}")
        sys.exit(1)
    if args.limit_queries > 0:
        queries = queries[:args.limit_queries]

    log("Phase 2F -- Global Shadow Retrieval Comparison")
    log(f"Production: {args.production_model} (table: {args.production_table})")
    log(f"Shadow:     {args.shadow_model} (table: {args.shadow_table})")
    log(f"Top-K: {args.top_k} | Final-K: {args.final_k} | Hybrid: {args.hybrid}")
    log(f"Queries loaded: {len(queries)}")
    log("Read-only. No routing changes.")

    conn = get_db_connection()

    # Verify tables
    cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*) FROM {args.production_table} WHERE embedding IS NOT NULL")
    prod_count = cur.fetchone()[0]
    log(f"Production table has {prod_count} rows with embeddings")

    cur.execute(f"SELECT COUNT(*) FROM {args.shadow_table} WHERE embedding IS NOT NULL")
    shadow_count = cur.fetchone()[0]
    log(f"Shadow table has {shadow_count} rows with embeddings")
    cur.close()

    if shadow_count == 0:
        log("ABORT: Shadow table is empty. Run the shadow index build first.")
        conn.close()
        sys.exit(1)

    # Per-query tracking
    query_results = []
    nomic_latencies = []
    qwen3_latencies = []
    overlaps = []
    nomic_diversities = []
    qwen3_diversities = []
    hybrid_diversities = []
    nomic_avg_sims = []
    qwen3_avg_sims = []
    hybrid_avg_sims = []
    nomic_empty = 0
    qwen3_empty = 0
    consensus_counts = []
    winner_counts = {"nomic": 0, "qwen3": 0, "tie": 0, "hybrid": 0}

    total = len(queries)
    run_start = time.monotonic()

    for i, query in enumerate(queries):
      try:
        # Embed with production model (nomic)
        n_vec, n_lat = embed_text(query, args.production_model)
        nomic_latencies.append(n_lat)

        # Embed with shadow model (qwen3)
        q_vec, q_lat = embed_text(query, args.shadow_model)
        qwen3_latencies.append(q_lat)

        # Search production table with nomic embeddings
        if n_vec:
            n_results = search_table(conn, args.production_table, n_vec,
                                     top_k=args.top_k, fetch_limit=max(prod_count, 500))
        else:
            n_results = []
            nomic_empty += 1

        # Search shadow table with qwen3 embeddings
        if q_vec:
            q_results = search_table(conn, args.shadow_table, q_vec,
                                     top_k=args.top_k, fetch_limit=max(shadow_count, 500))
        else:
            q_results = []
            qwen3_empty += 1

        # Overlap
        overlap = compute_overlap(n_results, q_results, args.top_k)
        overlaps.append(overlap)

        # Diversity
        n_div = source_diversity(n_results)
        q_div = source_diversity(q_results)
        nomic_diversities.append(n_div)
        qwen3_diversities.append(q_div)

        # Avg similarity
        n_avg_sim = sum(r["score"] for r in n_results) / max(len(n_results), 1)
        q_avg_sim = sum(r["score"] for r in q_results) / max(len(q_results), 1)
        nomic_avg_sims.append(n_avg_sim)
        qwen3_avg_sims.append(q_avg_sim)

        # Winner for this query
        if n_avg_sim > q_avg_sim + 0.005:
            winner_counts["nomic"] += 1
        elif q_avg_sim > n_avg_sim + 0.005:
            winner_counts["qwen3"] += 1
        else:
            winner_counts["tie"] += 1

        # Hybrid merge
        h_results = []
        h_div = 0
        h_avg_sim = 0.0
        consensus_count = 0
        model_source_summary = {}
        if args.hybrid:
            h_results, consensus_count = hybrid_merge(n_results, q_results,
                                                       final_k=args.final_k)
            h_div = source_diversity(h_results)
            h_avg_sim = sum(r["score"] for r in h_results) / max(len(h_results), 1)
            hybrid_diversities.append(h_div)
            hybrid_avg_sims.append(h_avg_sim)

            # Check if hybrid beats best single model
            best_single = max(n_avg_sim, q_avg_sim)
            if h_avg_sim > best_single + 0.005:
                winner_counts["hybrid"] += 1

            # Model source tag counts
            for r in h_results:
                tag = r.get("model_source", "unknown")
                model_source_summary[tag] = model_source_summary.get(tag, 0) + 1

        consensus_counts.append(consensus_count)

        qr = {
            "query": query,
            "nomic_latency_ms": n_lat,
            "qwen3_latency_ms": q_lat,
            "nomic_results": n_results[:5],
            "qwen3_results": q_results[:5],
            "hybrid_results": h_results[:5] if args.hybrid else [],
            "overlap": round(overlap, 4),
            "nomic_avg_sim": round(n_avg_sim, 4),
            "qwen3_avg_sim": round(q_avg_sim, 4),
            "hybrid_avg_sim": round(h_avg_sim, 4) if args.hybrid else None,
            "nomic_diversity": n_div,
            "qwen3_diversity": q_div,
            "hybrid_diversity": h_div if args.hybrid else None,
            "consensus_count": consensus_count,
            "model_source_summary": model_source_summary,
            "nomic_empty": len(n_results) == 0,
            "qwen3_empty": len(q_results) == 0,
        }
        query_results.append(qr)

        if args.verbose:
            log(f"  Q{i+1:03d}: overlap={overlap:.2f} "
                f"n_sim={n_avg_sim:.3f} q_sim={q_avg_sim:.3f} "
                f"n_div={n_div} q_div={q_div} "
                f"n_lat={n_lat:.0f}ms q_lat={q_lat:.0f}ms"
                f"{f' consensus={consensus_count}' if args.hybrid else ''}")

        # Progress log every 10 queries
        if (i + 1) % 10 == 0:
            elapsed = time.monotonic() - run_start
            rate = (i + 1) / elapsed if elapsed > 0 else 0
            eta = (total - i - 1) / rate if rate > 0 else 0
            log(f"Progress: {i+1}/{total} queries "
                f"({elapsed:.0f}s elapsed, ~{eta:.0f}s remaining)")

      except Exception as e:
        log(f"  Q{i+1:03d} FAILED: {e}")
        query_results.append({"query": query, "error": str(e)})

    conn.close()

    # Aggregate metrics
    def safe_avg(lst):
        return sum(lst) / max(len(lst), 1)

    avg_nomic_sim = safe_avg(nomic_avg_sims)
    avg_qwen3_sim = safe_avg(qwen3_avg_sims)
    avg_nomic_div = safe_avg(nomic_diversities)
    avg_qwen3_div = safe_avg(qwen3_diversities)
    avg_nomic_lat = safe_avg(nomic_latencies)
    avg_qwen3_lat = safe_avg(qwen3_latencies)
    avg_overlap = safe_avg(overlaps)
    avg_consensus = safe_avg(consensus_counts)

    agg = {
        "nomic_avg_similarity": round(avg_nomic_sim, 4),
        "qwen3_avg_similarity": round(avg_qwen3_sim, 4),
        "similarity_delta": round(avg_qwen3_sim - avg_nomic_sim, 4),
        "nomic_avg_diversity": round(avg_nomic_div, 2),
        "qwen3_avg_diversity": round(avg_qwen3_div, 2),
        "diversity_delta": round(avg_qwen3_div - avg_nomic_div, 2),
        "nomic_avg_latency_ms": round(avg_nomic_lat, 1),
        "qwen3_avg_latency_ms": round(avg_qwen3_lat, 1),
        "latency_delta": round(avg_qwen3_lat - avg_nomic_lat, 1),
        "avg_overlap": round(avg_overlap, 4),
        "consensus_rate": round(avg_consensus / max(args.top_k, 1), 4),
        "nomic_empty_rate": round(nomic_empty / max(total, 1), 4),
        "qwen3_empty_rate": round(qwen3_empty / max(total, 1), 4),
        "method_winner_counts": winner_counts,
    }

    if args.hybrid and hybrid_avg_sims:
        agg["hybrid_avg_similarity"] = round(safe_avg(hybrid_avg_sims), 4)
        agg["hybrid_avg_diversity"] = round(safe_avg(hybrid_diversities), 2)

    # Verdict
    sim_adv = avg_qwen3_sim - avg_nomic_sim
    if avg_qwen3_sim > avg_nomic_sim + 0.02 and avg_qwen3_div >= avg_nomic_div:
        verdict = "QWEN3_BETTER"
    elif avg_nomic_sim > avg_qwen3_sim + 0.02 and avg_nomic_div >= avg_qwen3_div:
        verdict = "NOMIC_BETTER"
    elif abs(sim_adv) < 0.02 and avg_overlap < 0.5:
        verdict = "HYBRID_RECOMMENDED"
    else:
        verdict = "INCONCLUSIVE"

    total_elapsed = time.monotonic() - run_start

    log("=" * 60)
    log("Phase 2F Global Shadow Retrieval Summary")
    log("=" * 60)
    log(f"Queries tested:          {total}")
    log(f"Total elapsed:           {total_elapsed:.0f}s")
    log(f"Avg overlap (top-{args.top_k}):    {avg_overlap:.3f}")
    log(f"Nomic avg similarity:    {avg_nomic_sim:.4f}")
    log(f"Qwen3 avg similarity:    {avg_qwen3_sim:.4f}")
    log(f"Similarity delta:        {sim_adv:+.4f}")
    log(f"Nomic avg latency:       {avg_nomic_lat:.0f}ms")
    log(f"Qwen3 avg latency:       {avg_qwen3_lat:.0f}ms")
    log(f"Nomic avg diversity:     {avg_nomic_div:.1f}")
    log(f"Qwen3 avg diversity:     {avg_qwen3_div:.1f}")
    log(f"Consensus rate:          {agg['consensus_rate']:.3f}")
    log(f"Nomic empty:             {nomic_empty}/{total}")
    log(f"Qwen3 empty:             {qwen3_empty}/{total}")
    log(f"Winners — nomic: {winner_counts['nomic']} | qwen3: {winner_counts['qwen3']} | tie: {winner_counts['tie']}")
    if args.hybrid:
        log(f"Hybrid avg similarity:   {agg.get('hybrid_avg_similarity', '--')}")
        log(f"Hybrid avg diversity:    {agg.get('hybrid_avg_diversity', '--')}")
        log(f"Hybrid wins (vs best):   {winner_counts['hybrid']}")
    log(f"Verdict:                 {verdict}")
    log("=" * 60)

    report = {
        "timestamp": datetime.now().isoformat(),
        "production_model": args.production_model,
        "shadow_model": args.shadow_model,
        "production_table": args.production_table,
        "shadow_table": args.shadow_table,
        "production_doc_count": prod_count,
        "shadow_doc_count": shadow_count,
        "query_count": total,
        "top_k": args.top_k,
        "final_k": args.final_k,
        "hybrid_enabled": args.hybrid,
        "total_elapsed_s": round(total_elapsed, 1),
        "aggregate": agg,
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

    # Cleanup: unload shadow model, restore production
    unload_qwen3_restore_nomic()
    log("Done.")


if __name__ == "__main__":
    main()
