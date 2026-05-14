#!/usr/bin/env python3
"""hybrid_rag_context_adapter.py — Phase 2C pilot-only hybrid RAG context for deep overnight jobs.

Queries both production nomic embeddings and qwen3 parallel test index,
merges/deduplicates results, and returns labeled context for prompt injection.

PILOT ONLY. Not for market-hours, real-time, or broker/execution use.
Read-only from both embedding tables. No writes to production embeddings.

Usage (standalone test):
    .venv/bin/python scripts/hybrid_rag_context_adapter.py --query "AAPL strategy" --symbol AAPL --json
"""
import argparse
import json
import logging
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
OLLAMA_URL = "http://localhost:11434"

log = logging.getLogger("hybrid_rag_adapter")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")

NOMIC_MODEL = "nomic-embed-text"
QWEN3_MODEL = "qwen3-embedding:8b"
BASELINE_TABLE = "content_embeddings"
CANDIDATE_TABLE = "content_embeddings_qwen3_test"

SOURCE_BOOSTS = {
    "trade_outcome": 1.35, "decision_outcome": 1.30, "research_finding": 1.25,
    "agent_synthesis": 1.20, "cio_decision": 1.15, "fused_signal": 1.10,
    "agent_result": 1.05, "news": 1.0, "youtube": 1.0, "social_post": 0.95,
    "sec_form4": 1.10, "fred_series": 0.90,
}

SOURCE_LABELS = {
    "news": "News", "youtube": "YouTube", "social_post": "Social",
    "sec_form4": "SEC Form 4", "fred_series": "FRED Macro",
    "agent_result": "Agent Memory", "agent_synthesis": "Synthesis",
    "cio_decision": "CIO Decision", "fused_signal": "Fused Signal",
    "decision_outcome": "Outcome", "research_finding": "Research",
    "trade_outcome": "Trade Outcome", "trade_review": "Trade Review",
}


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


def _embed(text, model):
    """Get embedding vector from Ollama."""
    data = json.dumps({"model": model, "prompt": text[:2000]}).encode()
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/embeddings", data=data,
        headers={"Content-Type": "application/json"})
    start = time.monotonic()
    with urllib.request.urlopen(req, timeout=60) as resp:
        result = json.loads(resp.read())
    latency = round((time.monotonic() - start) * 1000, 1)
    return result.get("embedding", []), latency


def _cosine(a, b):
    """Cosine similarity between two vectors."""
    import numpy as np
    va, vb = np.array(a, dtype=float), np.array(b, dtype=float)
    d = np.linalg.norm(va) * np.linalg.norm(vb)
    return float(np.dot(va, vb) / d) if d > 0 else 0.0


def _fetch_candidates(conn, table, query_vec, symbol=None, allowed_sources=None, fetch_limit=150):
    """Fetch embedding candidates from a table."""
    import psycopg2.extras
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    conditions = ["created_at > NOW() - INTERVAL '365 days'"]
    params = []
    if symbol:
        conditions.append("title ILIKE %s")
        params.append(f"%{symbol}%")
    if allowed_sources:
        placeholders = ",".join(["%s"] * len(allowed_sources))
        conditions.append(f"source_type IN ({placeholders})")
        params.extend(allowed_sources)
    where = " AND ".join(conditions) if conditions else "TRUE"
    cur.execute(f"""
        SELECT id, source_type, source_id, title, embedding, created_at
        FROM {table}
        WHERE {where}
        ORDER BY created_at DESC LIMIT %s
    """, params + [fetch_limit])
    rows = cur.fetchall()
    cur.close()
    return rows


def _score_and_rank(candidates, query_vec, source_boosts=True):
    """Score candidates by cosine similarity with boosts."""
    scored = []
    for c in candidates:
        raw = c.get("embedding")
        if not raw:
            continue
        vec = raw if isinstance(raw, list) else json.loads(raw) if isinstance(raw, str) else None
        if not vec:
            continue
        sim = _cosine(query_vec, vec)
        age_days = (datetime.now(timezone.utc) - c["created_at"].replace(tzinfo=timezone.utc)).days if c.get("created_at") else 0
        recency = max(0.5, 1.0 - (age_days // 30) * 0.10)
        sb = SOURCE_BOOSTS.get(c["source_type"], 1.0) if source_boosts else 1.0
        c["score"] = round(sim * recency * sb, 4)
        c["raw_sim"] = round(sim, 4)
        scored.append(c)
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored


def _unload_qwen3_embedding():
    """Unload qwen3-embedding:8b to free VRAM."""
    try:
        urllib.request.urlopen(urllib.request.Request(
            f"{OLLAMA_URL}/api/generate",
            data=json.dumps({"model": QWEN3_MODEL, "keep_alive": 0, "prompt": ""}).encode(),
            headers={"Content-Type": "application/json"}), timeout=15)
    except Exception:
        pass


def get_hybrid_context(
    query,
    symbol=None,
    workflow="unknown",
    final_k=10,
    top_k_baseline=10,
    top_k_candidate=10,
    allowed_source_types=None,
    dry_run=False,
):
    """Get hybrid RAG context from both nomic and qwen3 embedding tables.

    Returns dict with mode, results, metrics, and formatted context text.
    Falls back to nomic-only if qwen3 unavailable.
    """
    start_total = time.monotonic()
    warnings = []
    fallback_used = False
    conn = _get_conn()

    try:
        # Step 1: Embed query with nomic
        nomic_vec, nomic_lat = _embed(query, NOMIC_MODEL)
        if not nomic_vec:
            return {"mode": "HYBRID_PILOT", "error": "nomic embedding failed", "results": []}

        # Step 2: Fetch + score nomic candidates
        nomic_start = time.monotonic()
        nomic_raw = _fetch_candidates(conn, BASELINE_TABLE, nomic_vec, symbol, allowed_source_types)
        nomic_scored = _score_and_rank(nomic_raw, nomic_vec)[:top_k_baseline]
        nomic_lat_total = round((time.monotonic() - nomic_start) * 1000, 1)

        # Step 3: Try qwen3 candidates
        qwen3_scored = []
        qwen3_lat_total = 0
        try:
            qwen3_vec, qwen3_lat = _embed(query, QWEN3_MODEL)
            if qwen3_vec:
                qwen3_start = time.monotonic()
                qwen3_raw = _fetch_candidates(conn, CANDIDATE_TABLE, qwen3_vec, symbol, allowed_source_types)
                qwen3_scored = _score_and_rank(qwen3_raw, qwen3_vec)[:top_k_candidate]
                qwen3_lat_total = round((time.monotonic() - qwen3_start) * 1000, 1)
            else:
                warnings.append("qwen3 embedding returned empty vector")
                fallback_used = True
        except Exception as e:
            warnings.append(f"qwen3 retrieval failed: {str(e)[:100]}")
            fallback_used = True

        # Step 4: Merge and deduplicate
        merge_start = time.monotonic()
        seen_keys = set()
        merged = []

        # Track which model found each result
        nomic_ids = {(r["source_type"], r["source_id"]) for r in nomic_scored}
        qwen3_ids = {(r["source_type"], r["source_id"]) for r in qwen3_scored}
        consensus_ids = nomic_ids & qwen3_ids

        for r in nomic_scored:
            key = (r["source_type"], r["source_id"])
            if key not in seen_keys:
                seen_keys.add(key)
                r["model_source"] = "both" if key in consensus_ids else "nomic"
                if key in consensus_ids:
                    r["score"] = round(r["score"] * 1.15, 4)  # consensus boost
                merged.append(r)

        for r in qwen3_scored:
            key = (r["source_type"], r["source_id"])
            if key not in seen_keys:
                seen_keys.add(key)
                r["model_source"] = "qwen3"
                merged.append(r)

        merged.sort(key=lambda x: x["score"], reverse=True)
        final = merged[:final_k]
        merge_lat = round((time.monotonic() - merge_start) * 1000, 1)

        # Step 5: Format context text
        context_lines = ["--- HYBRID RAG PILOT CONTEXT (offline/deep use only) ---"]
        for i, r in enumerate(final, 1):
            label = SOURCE_LABELS.get(r["source_type"], r["source_type"])
            model_tag = f"[{r['model_source']}]"
            date = r["created_at"].strftime("%Y-%m-%d") if r.get("created_at") else "?"
            title = (r.get("title") or "")[:120]
            context_lines.append(f"{i}. {model_tag} {label}: {title} ({date}, score={r['score']})")
        context_lines.append("--- END HYBRID RAG CONTEXT ---")
        context_text = "\n".join(context_lines)

        total_lat = round((time.monotonic() - start_total) * 1000, 1)

        # Count model sources
        source_types_seen = set(r["source_type"] for r in final)
        consensus_count = sum(1 for r in final if r.get("model_source") == "both")
        nomic_only = sum(1 for r in final if r.get("model_source") == "nomic")
        qwen3_only = sum(1 for r in final if r.get("model_source") == "qwen3")

        # Unload qwen3-embedding if it was loaded
        if not fallback_used:
            _unload_qwen3_embedding()

        result = {
            "mode": "HYBRID_PILOT",
            "query": query,
            "symbol": symbol,
            "workflow": workflow,
            "final_context_text": context_text,
            "results": [{
                "source_type": r["source_type"],
                "source_label": SOURCE_LABELS.get(r["source_type"], r["source_type"]),
                "title": (r.get("title") or "")[:120],
                "score": r["score"],
                "model_source": r.get("model_source", "unknown"),
                "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
            } for r in final],
            "metrics": {
                "baseline_latency_ms": nomic_lat_total,
                "candidate_latency_ms": qwen3_lat_total,
                "merge_latency_ms": merge_lat,
                "total_latency_ms": total_lat,
                "source_type_count": len(source_types_seen),
                "candidate_result_count": len(qwen3_scored),
                "baseline_result_count": len(nomic_scored),
                "consensus_count": consensus_count,
                "nomic_only_count": nomic_only,
                "qwen3_only_count": qwen3_only,
                "fallback_used": fallback_used,
            },
            "warnings": warnings,
        }

        if dry_run:
            result["dry_run"] = True

        return result

    except Exception as e:
        return {"mode": "HYBRID_PILOT", "error": str(e), "results": [], "warnings": [str(e)],
                "metrics": {"fallback_used": True}}
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="Phase 2C hybrid RAG context adapter (pilot)")
    parser.add_argument("--query", required=True, help="Query text")
    parser.add_argument("--symbol", default=None, help="Symbol filter")
    parser.add_argument("--workflow", default="manual_test", help="Workflow name")
    parser.add_argument("--final-k", type=int, default=10)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    result = get_hybrid_context(
        query=args.query, symbol=args.symbol, workflow=args.workflow,
        final_k=args.final_k, dry_run=args.dry_run)

    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print(result.get("final_context_text", "No context"))
        m = result.get("metrics", {})
        print(f"\n[Metrics] total={m.get('total_latency_ms')}ms sources={m.get('source_type_count')} "
              f"nomic={m.get('nomic_only_count')} qwen3={m.get('qwen3_only_count')} "
              f"consensus={m.get('consensus_count')} fallback={m.get('fallback_used')}")


if __name__ == "__main__":
    main()
