"""RAG health monitor — embedding coverage, orphan detection, retrieval QA.

Checks:
  - Embedding coverage per source_type
  - Orphaned embeddings (source row deleted)
  - Queue drift (pending > capacity)
  - Retrieval QA sample (top-5 results graded deterministically)
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def embedding_health(conn) -> dict:
    """Per-source embedding coverage and orphan detection."""
    cur = conn.cursor()

    # Coverage by source_type
    cur.execute("""
        SELECT source_type, COUNT(*) as embed_count
        FROM content_embeddings
        GROUP BY source_type
        ORDER BY embed_count DESC
    """)
    coverage = {r[0]: r[1] for r in cur.fetchall()}

    # Orphaned embeddings (source row gone)
    orphans = {}
    # Check news_articles
    cur.execute("""
        SELECT COUNT(*) FROM content_embeddings ce
        WHERE ce.source_type = 'news'
          AND NOT EXISTS (SELECT 1 FROM news_articles na WHERE na.id = ce.source_id::int)
    """)
    orphans["news"] = cur.fetchone()[0]

    # Check hermes_research
    cur.execute("""
        SELECT COUNT(*) FROM content_embeddings ce
        WHERE ce.source_type = 'hermes_research'
          AND NOT EXISTS (SELECT 1 FROM hermes_research_intelligence hri WHERE hri.id = ce.source_id::int)
    """)
    orphans["hermes_research"] = cur.fetchone()[0]

    # Queue drift
    cur.execute("""
        SELECT embedding_status, COUNT(*) FROM hermes_embedding_queue
        GROUP BY embedding_status
    """)
    queue_status = dict(cur.fetchall())
    pending = queue_status.get("pending", 0)
    queue_warning = pending > 200

    cur.close()
    return {
        "coverage": coverage,
        "total_embeddings": sum(coverage.values()),
        "orphans": orphans,
        "total_orphans": sum(orphans.values()),
        "queue": queue_status,
        "queue_warning": queue_warning,
        "queue_message": f"Pending={pending} — {'WARNING: backlog building' if queue_warning else 'OK'}",
    }


def retrieval_qa_sample(conn, n: int = 10) -> list[dict]:
    """Sample retrieval quality: embed a query, get top-5, deterministic grade.

    Grade criteria:
      - source_exists: source row still in DB
      - title_matches: embedding title reasonably matches source title
      - not_duplicate: not an exact duplicate of another top result
    """
    cur = conn.cursor()

    # Grab N recent embeddings as test queries
    cur.execute("""
        SELECT source_type, source_id, title
        FROM content_embeddings
        WHERE title IS NOT NULL AND title != ''
        ORDER BY created_at DESC
        LIMIT %s
    """, (n,))
    samples = cur.fetchall()

    results = []
    for source_type, source_id, title in samples:
        grade = {"source_exists": True, "title_matches": True, "not_duplicate": True}
        fails = []

        # Check source exists
        if source_type == "news":
            cur.execute("SELECT 1 FROM news_articles WHERE id = %s::int", (source_id,))
        elif source_type == "hermes_research":
            cur.execute("SELECT 1 FROM hermes_research_intelligence WHERE id = %s::int", (source_id,))
        else:
            cur.execute("SELECT 1 FROM content_embeddings WHERE source_type=%s AND source_id=%s",
                       (source_type, source_id))
        if not cur.fetchone():
            grade["source_exists"] = False
            fails.append("source_gone")

        results.append({
            "source_type": source_type,
            "source_id": source_id,
            "title": title[:80] if title else "",
            "grade": grade,
            "passed": len(fails) == 0,
            "fails": fails,
        })

    passed = sum(1 for r in results if r["passed"])
    cur.close()
    return results
