#!/usr/bin/env python3
"""hybrid_rag_retrieval_pilot.py — Phase 2C Hybrid RAG Retrieval Pilot.

Queries BOTH production nomic embeddings (content_embeddings) and the Phase 2B
qwen3 test table (content_embeddings_qwen3_test), merges/dedupes results,
reranks with a hybrid scoring function, and reports quality.

Read-only against production. No routing changes.
"""

import argparse
import json
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
OLLAMA_URL = "http://localhost:11434"

# Source boosts from production rag_retrieval.py
SOURCE_BOOSTS = {
    'trade_outcome': 1.35,
    'decision_outcome': 1.30,
    'research_finding': 1.25,
    'agent_synthesis': 1.20,
    'cio_decision': 1.15,
    'fused_signal': 1.10,
    'agent_result': 1.05,
}

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


def embed_text(text, model):
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
    return result.get("embedding", []), round((time.monotonic() - start) * 1000, 1)


def cosine_sim(a, b):
    if not a or not b:
        return 0.0
    import numpy as np
    a, b = np.array(a, dtype=np.float32), np.array(b, dtype=np.float32)
    n = np.linalg.norm(a) * np.linalg.norm(b)
    return float(np.dot(a, b) / n) if n > 0 else 0.0


def log(msg):
    print(f"{datetime.now().strftime('%H:%M:%S')} [hybrid-pilot] {msg}", flush=True)


def fetch_nomic_candidates(conn, query_vec, fetch_limit=200):
    """Fetch from production content_embeddings, compute cosine sim."""
    cur = conn.cursor()
    cur.execute("""
        SELECT source_type, source_id, title, embedding, created_at
        FROM content_embeddings
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
        created_at = row.get("created_at")
        if created_at:
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            age_days = (datetime.now(timezone.utc) - created_at).days
        else:
            age_days = 0
        scored.append({
            "source_type": row["source_type"],
            "source_id": row["source_id"],
            "title": (row.get("title") or "")[:80],
            "raw_sim": round(sim, 6),
            "age_days": age_days,
            "retrieval_model": "nomic",
        })
    scored.sort(key=lambda x: -x["raw_sim"])
    return scored


def fetch_qwen3_candidates(conn, query_vec):
    """Fetch ALL from content_embeddings_qwen3_test, compute cosine sim."""
    cur = conn.cursor()
    cur.execute("""
        SELECT source_type, source_id, title, embedding, indexed_at
        FROM content_embeddings_qwen3_test
        WHERE embedding IS NOT NULL
    """)
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
        indexed_at = row.get("indexed_at")
        if indexed_at:
            if indexed_at.tzinfo is None:
                indexed_at = indexed_at.replace(tzinfo=timezone.utc)
            age_days = (datetime.now(timezone.utc) - indexed_at).days
        else:
            age_days = 0
        scored.append({
            "source_type": row["source_type"],
            "source_id": row["source_id"],
            "title": (row.get("title") or "")[:80],
            "raw_sim": round(sim, 6),
            "age_days": age_days,
            "retrieval_model": "qwen3",
        })
    scored.sort(key=lambda x: -x["raw_sim"])
    return scored


def merge_and_rerank(nomic_results, qwen3_results, top_k_baseline, top_k_candidate, final_k):
    """Merge, dedupe, apply hybrid scoring, return final-k results."""
    # Take top-k from each
    nomic_top = nomic_results[:top_k_baseline]
    qwen3_top = qwen3_results[:top_k_candidate]

    # Build lookup by (source_type, source_id)
    merged = {}
    for item in nomic_top:
        key = (item["source_type"], item["source_id"])
        merged[key] = dict(item)

    consensus_count = 0
    for item in qwen3_top:
        key = (item["source_type"], item["source_id"])
        if key in merged:
            # Found by both -- mark consensus
            merged[key]["retrieval_model"] = "both"
            merged[key]["consensus_boost"] = 0.05
            # Keep the higher raw_sim
            if item["raw_sim"] > merged[key]["raw_sim"]:
                merged[key]["raw_sim"] = item["raw_sim"]
                merged[key]["age_days"] = item["age_days"]
            consensus_count += 1
        else:
            entry = dict(item)
            entry["consensus_boost"] = 0.0
            merged[key] = entry

    # Mark nomic-only items with no consensus
    for key, item in merged.items():
        if "consensus_boost" not in item:
            item["consensus_boost"] = 0.0

    items = list(merged.values())
    if not items:
        return [], 0

    # Compute hybrid scores
    max_sim = max(it["raw_sim"] for it in items) if items else 1.0
    if max_sim <= 0:
        max_sim = 1.0

    seen_source_types = set()
    for item in items:
        normalized_sim = item["raw_sim"] / max_sim
        recency = max(0.5, 1.0 - item["age_days"] / 300.0)
        source_boost = (SOURCE_BOOSTS.get(item["source_type"], 1.0) - 1.0)  # delta above 1.0
        # Normalize source_boost to [0, 0.35] range -> scale to [0, 1]
        source_boost_norm = min(source_boost / 0.35, 1.0) if source_boost > 0 else 0.0

        # Diversity bonus
        if item["source_type"] not in seen_source_types:
            diversity_bonus = 0.05
        else:
            diversity_bonus = 0.0
        seen_source_types.add(item["source_type"])

        consensus = item["consensus_boost"]

        hybrid_score = (
            0.50 * normalized_sim
            + 0.15 * recency
            + 0.10 * source_boost_norm
            + 0.10 * diversity_bonus
            + 0.10 * consensus
            + 0.05 * 1.0  # base
        )

        item["hybrid_score"] = round(hybrid_score, 6)
        item["normalized_sim"] = round(normalized_sim, 4)
        item["recency"] = round(recency, 4)

    items.sort(key=lambda x: -x["hybrid_score"])
    return items[:final_k], consensus_count


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


def generate_markdown_report(report):
    """Generate markdown report from hybrid retrieval results."""
    agg = report["aggregate"]
    lines = []
    lines.append("# Phase 2C: Hybrid RAG Retrieval Pilot Report")
    lines.append("")
    lines.append(f"**Date:** {report['timestamp']}")
    lines.append(f"**Nomic table:** content_embeddings ({report['nomic_doc_count']} docs)")
    lines.append(f"**Qwen3 table:** content_embeddings_qwen3_test ({report['qwen3_doc_count']} docs)")
    lines.append(f"**Queries:** {report['query_count']} | **Top-K baseline:** {report['top_k_baseline']} | **Top-K candidate:** {report['top_k_candidate']} | **Final-K:** {report['final_k']}")
    lines.append(f"**Production changed:** False | **Routing changed:** False")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Summary Table")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Queries tested | {report['query_count']} |")
    lines.append(f"| Avg source diversity | {agg['avg_source_diversity']:.2f} |")
    lines.append(f"| Avg hybrid score | {agg['avg_hybrid_score']:.4f} |")
    lines.append(f"| Consensus items (both models) | {agg['consensus_count']} |")
    lines.append(f"| Nomic-only items | {agg['nomic_only_count']} |")
    lines.append(f"| Qwen3-only items | {agg['qwen3_only_count']} |")
    lines.append(f"| Both-model items | {agg['both_model_count']} |")
    lines.append(f"| Avg nomic embed latency | {agg['avg_nomic_latency_ms']:.0f}ms |")
    lines.append(f"| Avg qwen3 embed latency | {agg['avg_qwen3_latency_ms']:.0f}ms |")
    lines.append(f"| Avg hybrid total latency | {agg['avg_hybrid_latency_ms']:.0f}ms |")
    lines.append(f"| Empty result queries | {agg['empty_result_count']}/{report['query_count']} |")
    lines.append(f"| Empty result rate | {agg['empty_result_rate']:.1%} |")
    lines.append("")
    lines.append("### Model Source Distribution (across all final results)")
    lines.append("")
    lines.append("| Source | Count | Pct |")
    lines.append("|--------|-------|-----|")
    total_items = agg['nomic_only_count'] + agg['qwen3_only_count'] + agg['both_model_count']
    if total_items > 0:
        lines.append(f"| nomic-only | {agg['nomic_only_count']} | {agg['nomic_only_count']/total_items:.1%} |")
        lines.append(f"| qwen3-only | {agg['qwen3_only_count']} | {agg['qwen3_only_count']/total_items:.1%} |")
        lines.append(f"| both | {agg['both_model_count']} | {agg['both_model_count']/total_items:.1%} |")
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## Per-Query Results (first 10)")
    lines.append("")
    for i, qr in enumerate(report["query_results"][:10]):
        lines.append(f"### Q{i+1}: {qr['query']}")
        lines.append("")
        lines.append(f"- Source diversity: {qr['source_diversity']} unique types")
        lines.append(f"- Nomic latency: {qr['nomic_latency_ms']:.0f}ms | Qwen3 latency: {qr['qwen3_latency_ms']:.0f}ms")
        lines.append(f"- Consensus items: {qr['consensus_count']}")
        model_dist = qr.get("model_distribution", {})
        lines.append(f"- Model distribution: nomic={model_dist.get('nomic',0)} qwen3={model_dist.get('qwen3',0)} both={model_dist.get('both',0)}")
        lines.append("")
        lines.append("**Hybrid top-5:**")
        for j, r in enumerate(qr.get("hybrid_results", [])[:5]):
            lines.append(f"  {j+1}. [{r['source_type']}:{r['source_id']}] hybrid={r['hybrid_score']:.4f} sim={r['raw_sim']:.4f} model={r['retrieval_model']} — {r['title']}")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(f"## Verdict: **{report['verdict']}**")
    lines.append("")
    verdict_notes = {
        "HYBRID_USEFUL": "Hybrid retrieval surfaces unique content from both models with meaningful consensus overlap. The merged result set is richer than either model alone. Recommend proceeding to Phase 2D production routing.",
        "HYBRID_MARGINAL": "Hybrid retrieval shows some benefit but the improvement over nomic-only is modest. Consider targeted hybrid routing for specific query contexts (journal review, deep overnight) rather than blanket hybrid.",
        "HYBRID_NOT_RECOMMENDED": "Hybrid retrieval does not meaningfully improve over single-model retrieval. The overhead of dual embedding and merge is not justified. Recommend staying with nomic-only or evaluating a full qwen3 cutover instead.",
    }
    lines.append(verdict_notes.get(report["verdict"], ""))
    lines.append("")
    lines.append("---")
    lines.append("*Generated by hybrid_rag_retrieval_pilot.py*")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Phase 2C Hybrid RAG Retrieval Pilot")
    parser.add_argument("--output-json", default=None, help="Path for JSON results")
    parser.add_argument("--output-md", default=None, help="Path for Markdown report")
    parser.add_argument("--verbose", action="store_true", help="Print per-query detail")
    parser.add_argument("--top-k-baseline", type=int, default=10, help="Top-K from nomic")
    parser.add_argument("--top-k-candidate", type=int, default=10, help="Top-K from qwen3")
    parser.add_argument("--final-k", type=int, default=10, help="Final merged top-K")
    args = parser.parse_args()

    log("Phase 2C — Hybrid RAG Retrieval Pilot")
    log(f"Nomic table: content_embeddings | Qwen3 table: content_embeddings_qwen3_test")
    log(f"Top-K baseline: {args.top_k_baseline} | Top-K candidate: {args.top_k_candidate} | Final-K: {args.final_k}")
    log(f"Queries: {len(QUERIES)}")
    log("Read-only. No routing changes.")

    conn = get_db_connection()

    # Verify tables
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM content_embeddings WHERE embedding IS NOT NULL")
    nomic_count = cur.fetchone()[0]
    log(f"Nomic table: {nomic_count} rows with embeddings")

    cur.execute("SELECT COUNT(*) FROM content_embeddings_qwen3_test WHERE embedding IS NOT NULL")
    qwen3_count = cur.fetchone()[0]
    log(f"Qwen3 table: {qwen3_count} rows with embeddings")
    cur.close()

    if qwen3_count == 0:
        log("ABORT: Qwen3 test table is empty. Run build_phase2b_parallel_embedding_index.py first.")
        conn.close()
        sys.exit(1)

    # Metrics accumulators
    query_results = []
    nomic_latencies = []
    qwen3_latencies = []
    hybrid_latencies = []
    source_diversities = []
    total_consensus = 0
    total_nomic_only = 0
    total_qwen3_only = 0
    total_both = 0
    empty_count = 0

    for i, query in enumerate(QUERIES):
        q_start = time.monotonic()

        # Step 1: Embed with nomic
        nomic_vec, nomic_lat = embed_text(query, "nomic-embed-text")
        nomic_latencies.append(nomic_lat)

        # Step 2: Embed with qwen3
        qwen3_vec, qwen3_lat = embed_text(query, "qwen3-embedding:8b")
        qwen3_latencies.append(qwen3_lat)

        # Step 3: Fetch candidates
        if nomic_vec:
            nomic_candidates = fetch_nomic_candidates(conn, nomic_vec, fetch_limit=200)
        else:
            nomic_candidates = []

        if qwen3_vec:
            qwen3_candidates = fetch_qwen3_candidates(conn, qwen3_vec)
        else:
            qwen3_candidates = []

        # Step 4-6: Merge, dedupe, rerank
        hybrid_results, consensus = merge_and_rerank(
            nomic_candidates, qwen3_candidates,
            args.top_k_baseline, args.top_k_candidate, args.final_k
        )

        q_elapsed = round((time.monotonic() - q_start) * 1000, 1)
        hybrid_latencies.append(q_elapsed)

        # Step 7: Track metrics
        source_types_in_results = set(r["source_type"] for r in hybrid_results)
        diversity = len(source_types_in_results)
        source_diversities.append(diversity)
        total_consensus += consensus

        model_dist = {"nomic": 0, "qwen3": 0, "both": 0}
        for r in hybrid_results:
            model_dist[r["retrieval_model"]] += 1
        total_nomic_only += model_dist["nomic"]
        total_qwen3_only += model_dist["qwen3"]
        total_both += model_dist["both"]

        if not hybrid_results:
            empty_count += 1

        avg_hybrid = sum(r["hybrid_score"] for r in hybrid_results) / max(len(hybrid_results), 1)

        qr = {
            "query": query,
            "nomic_latency_ms": nomic_lat,
            "qwen3_latency_ms": qwen3_lat,
            "hybrid_latency_ms": q_elapsed,
            "source_diversity": diversity,
            "consensus_count": consensus,
            "model_distribution": model_dist,
            "avg_hybrid_score": round(avg_hybrid, 4),
            "hybrid_results": [
                {
                    "source_type": r["source_type"],
                    "source_id": r["source_id"],
                    "title": r["title"],
                    "raw_sim": r["raw_sim"],
                    "hybrid_score": r["hybrid_score"],
                    "retrieval_model": r["retrieval_model"],
                    "normalized_sim": r.get("normalized_sim", 0),
                    "recency": r.get("recency", 0),
                }
                for r in hybrid_results
            ],
            "empty": len(hybrid_results) == 0,
        }
        query_results.append(qr)

        if args.verbose:
            log(f"  Q{i+1:02d}: div={diversity} consensus={consensus} "
                f"nomic={model_dist['nomic']} qwen3={model_dist['qwen3']} both={model_dist['both']} "
                f"n_lat={nomic_lat:.0f}ms q_lat={qwen3_lat:.0f}ms total={q_elapsed:.0f}ms "
                f"avg_hybrid={avg_hybrid:.4f}")

    conn.close()

    # Aggregate metrics
    avg_diversity = sum(source_diversities) / max(len(source_diversities), 1)
    avg_nomic_lat = sum(nomic_latencies) / max(len(nomic_latencies), 1)
    avg_qwen3_lat = sum(qwen3_latencies) / max(len(qwen3_latencies), 1)
    avg_hybrid_lat = sum(hybrid_latencies) / max(len(hybrid_latencies), 1)
    all_hybrid_scores = [r["hybrid_score"] for qr in query_results for r in qr["hybrid_results"]]
    avg_hybrid_score = sum(all_hybrid_scores) / max(len(all_hybrid_scores), 1)
    empty_rate = empty_count / max(len(QUERIES), 1)

    # Verdict logic
    # HYBRID_USEFUL: meaningful consensus (>10% both) AND diversity improvement AND not too many empties
    both_pct = total_both / max(total_nomic_only + total_qwen3_only + total_both, 1)
    unique_from_qwen3_pct = total_qwen3_only / max(total_nomic_only + total_qwen3_only + total_both, 1)

    if both_pct >= 0.10 and unique_from_qwen3_pct >= 0.10 and avg_diversity >= 2.0 and empty_rate < 0.20:
        verdict = "HYBRID_USEFUL"
    elif unique_from_qwen3_pct >= 0.05 or both_pct >= 0.05:
        verdict = "HYBRID_MARGINAL"
    else:
        verdict = "HYBRID_NOT_RECOMMENDED"

    log("=" * 60)
    log("Phase 2C Hybrid Retrieval Pilot Summary")
    log("=" * 60)
    log(f"Queries tested:          {len(QUERIES)}")
    log(f"Avg source diversity:    {avg_diversity:.2f}")
    log(f"Avg hybrid score:        {avg_hybrid_score:.4f}")
    log(f"Consensus items (both):  {total_both}")
    log(f"Nomic-only items:        {total_nomic_only}")
    log(f"Qwen3-only items:        {total_qwen3_only}")
    log(f"Both-model items:        {total_both}")
    log(f"Avg nomic latency:       {avg_nomic_lat:.0f}ms")
    log(f"Avg qwen3 latency:       {avg_qwen3_lat:.0f}ms")
    log(f"Avg hybrid total latency:{avg_hybrid_lat:.0f}ms")
    log(f"Empty result queries:    {empty_count}/{len(QUERIES)}")
    log(f"Empty result rate:       {empty_rate:.1%}")
    log(f"Verdict:                 {verdict}")
    log("=" * 60)

    report = {
        "timestamp": datetime.now().isoformat(),
        "nomic_doc_count": nomic_count,
        "qwen3_doc_count": qwen3_count,
        "query_count": len(QUERIES),
        "top_k_baseline": args.top_k_baseline,
        "top_k_candidate": args.top_k_candidate,
        "final_k": args.final_k,
        "aggregate": {
            "avg_source_diversity": round(avg_diversity, 2),
            "avg_hybrid_score": round(avg_hybrid_score, 4),
            "consensus_count": total_consensus,
            "nomic_only_count": total_nomic_only,
            "qwen3_only_count": total_qwen3_only,
            "both_model_count": total_both,
            "avg_nomic_latency_ms": round(avg_nomic_lat, 1),
            "avg_qwen3_latency_ms": round(avg_qwen3_lat, 1),
            "avg_hybrid_latency_ms": round(avg_hybrid_lat, 1),
            "empty_result_count": empty_count,
            "empty_result_rate": round(empty_rate, 4),
        },
        "verdict": verdict,
        "production_changed": False,
        "routing_changed": False,
        "query_results": query_results,
    }

    if args.output_json:
        out_path = Path(args.output_json)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2, default=str))
        log(f"JSON report written to {args.output_json}")

    if args.output_md:
        md = generate_markdown_report(report)
        out_path = Path(args.output_md)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(md)
        log(f"Markdown report written to {args.output_md}")

    # Unload candidate, restore nomic
    unload_candidate_restore_nomic()
    log("Done.")


if __name__ == "__main__":
    main()
