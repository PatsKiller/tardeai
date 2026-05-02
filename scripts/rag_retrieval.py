"""rag_retrieval.py — Universal RAG Retrieval Engine for Trade AI v12.

Covers all intelligence source types. Used by all agents.
Falls back to keyword search if Ollama unavailable.
"""
import logging
import json
import numpy as np
import requests
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

logger = logging.getLogger(__name__)
OLLAMA_URL = "http://localhost:11434/api/embeddings"
EMBED_MODEL = "nomic-embed-text"

SOURCE_LABELS = {
    "news": "News", "youtube": "YouTube", "social_post": "Social",
    "sec_form4": "SEC Form 4", "fred_series": "FRED Macro",
    "agent_result": "Agent Memory", "agent_synthesis": "Synthesis",
    "cio_decision": "CIO Decision", "fused_signal": "Fused Signal",
    "decision_outcome": "Outcome",
}

SOURCE_BOOSTS = {
    "decision_outcome": 1.3, "agent_synthesis": 1.2, "cio_decision": 1.15,
    "fused_signal": 1.1, "agent_result": 1.05,
}


def _get_conn():
    import psycopg2, psycopg2.extras
    pw = ""
    for line in (PROJECT_ROOT / ".env").read_text().splitlines():
        if line.startswith("DB_PASSWORD="): pw = line.split("=", 1)[1].strip()
    conn = psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)
    return conn


def embed_text(text):
    try:
        r = requests.post(OLLAMA_URL, json={"model": EMBED_MODEL, "prompt": text[:2000]}, timeout=30)
        r.raise_for_status()
        return r.json().get("embedding")
    except Exception as e:
        logger.warning(f"Embed failed: {e}")
        return None


def cosine_sim(a, b):
    try:
        va, vb = np.array(a, dtype=float), np.array(b, dtype=float)
        d = np.linalg.norm(va) * np.linalg.norm(vb)
        return float(np.dot(va, vb) / d) if d > 0 else 0.0
    except Exception:
        return 0.0


def get_rag_context(symbol, agent_name=None, strategy_focus=None,
                    query_text=None, limit=7, source_types=None, conn=None):
    """Retrieve most relevant prior intelligence for a symbol."""
    close_conn = conn is None
    if close_conn:
        conn = _get_conn()
    import psycopg2.extras
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        if not query_text:
            query_text = f"{symbol} {strategy_focus or ''} investment retirement income"

        query_vec = embed_text(query_text)
        if query_vec is None:
            return _keyword_fallback(symbol, limit, cur)

        # Get candidate embeddings that mention this symbol (strict symbol match in title)
        cur.execute("""
            SELECT id, source_type, source_id, title, embedding, created_at
            FROM content_embeddings
            WHERE title ILIKE %s
              AND created_at > NOW() - INTERVAL '365 days'
            ORDER BY created_at DESC LIMIT 200
        """, (f"%{symbol}%",))
        candidates = cur.fetchall()

        if not candidates:
            return _keyword_fallback(symbol, limit, cur)

        scored = []
        for c in candidates:
            raw_vec = c.get("embedding")
            if not raw_vec:
                continue
            vec = raw_vec if isinstance(raw_vec, list) else json.loads(raw_vec) if isinstance(raw_vec, str) else list(raw_vec.values()) if isinstance(raw_vec, dict) else None
            if not vec:
                continue

            sim = cosine_sim(query_vec, vec)
            age_days = (datetime.now(timezone.utc) - c["created_at"].replace(tzinfo=timezone.utc)).days if c.get("created_at") else 0
            recency = max(0.5, 1.0 - (age_days // 30) * 0.10)
            sb = SOURCE_BOOSTS.get(c["source_type"], 1.0)
            c["rag_score"] = round(sim * recency * sb, 4)
            scored.append(c)

        scored.sort(key=lambda x: x["rag_score"], reverse=True)
        return [{
            "source_type": r["source_type"],
            "source_label": SOURCE_LABELS.get(r["source_type"], r["source_type"]),
            "source_id": r["source_id"],
            "title": (r.get("title") or "")[:100],
            "rag_score": r["rag_score"],
            "indexed_at": r["created_at"].isoformat() if r.get("created_at") else None,
        } for r in scored[:limit]]

    except Exception as e:
        logger.error(f"RAG failed for {symbol}: {e}")
        return []
    finally:
        cur.close()
        if close_conn:
            conn.close()


def _keyword_fallback(symbol, limit, cur):
    """Keyword fallback when Ollama unavailable."""
    results = []
    queries = [
        ("news", "SELECT id, title, quality_score, created_at FROM news_articles WHERE symbol=%s ORDER BY created_at DESC LIMIT %s", (symbol, limit)),
        ("agent_result", "SELECT id, agent||': '||COALESCE(recommendation,''), CAST(confidence*100 AS INT), created_at FROM watchlist_agent_results WHERE symbol=%s ORDER BY created_at DESC LIMIT %s", (symbol, limit)),
        ("cio_decision", "SELECT decision_id, symbol||' CIO: '||COALESCE(action,''), CAST(confidence_raw*100 AS INT), created_at FROM cio_decisions WHERE symbol=%s ORDER BY created_at DESC LIMIT %s", (symbol, limit)),
    ]
    for src, sql, params in queries:
        try:
            cur.execute(sql, params)
            for r in cur.fetchall():
                results.append({
                    "source_type": src, "source_label": SOURCE_LABELS.get(src, src),
                    "source_id": r[0], "title": str(r[1] or "")[:100],
                    "rag_score": (r[2] or 50) / 100.0,
                    "indexed_at": r[3].isoformat() if r[3] else None,
                })
        except Exception:
            pass
    results.sort(key=lambda x: x["rag_score"], reverse=True)
    return results[:limit]


def format_rag_context_for_prompt(rag_results, symbol=""):
    """Format RAG results as a compact block for agent prompt injection."""
    if not rag_results:
        return ""
    lines = [f"=== Prior Intelligence{' for ' + symbol if symbol else ''} ==="]
    for i, r in enumerate(rag_results, 1):
        date_str = (r.get("indexed_at") or "")[:10]
        lines.append(f"{i}. {r['source_label']} | {r['title']} | score:{r['rag_score']:.2f} | {date_str}")
    lines.append("=== End Prior Intelligence ===")
    return "\n".join(lines)
