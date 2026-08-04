"""Freshness monitor — per-source SLA, stale flagging, embedding staleness detection.

Reads state_freshness_history for source-level freshness, checks for
embedding staleness (source row updated after embed created), and flags
stale content for re-processing.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def freshness_report(conn) -> dict:
    """Per-source freshness summary from state_freshness_history.

    Returns:
        dict with stale_sources, fresh_sources, and per-producer details.
    """
    cur = conn.cursor()
    result = {"stale": [], "fresh": [], "errors": []}

    try:
        cur.execute("""
            SELECT source_script, MAX(age_hours) as max_age,
                   AVG(age_hours)::numeric(6,1) as avg_age,
                   COUNT(*) as file_count, MAX(checked_at)::text as last_check
            FROM state_freshness_history
            GROUP BY source_script
            ORDER BY max_age DESC
            LIMIT 15
        """)
        for source_script, max_age, avg_age, count, last_check in cur.fetchall():
            entry = {
                "producer": source_script,
                "max_age_h": float(max_age) if max_age is not None else None,
                "avg_age_h": float(avg_age) if avg_age is not None else None,
                "file_count": count,
                "last_check": last_check,
            }
            if max_age and float(max_age) > 48:
                entry["status"] = "STALE"
                result["stale"].append(entry)
            else:
                entry["status"] = "OK"
                result["fresh"].append(entry)
    except Exception as e:
        result["errors"].append(f"freshness query failed: {e}")

    cur.close()
    return result


def flag_stale(conn, *, dry_run: bool = False) -> dict:
    """Flag hermes_research_intelligence rows with stale freshness_date (>30d)."""
    cur = conn.cursor()
    cur.execute("""
        SELECT COUNT(*) FROM hermes_research_intelligence
        WHERE freshness_date < CURRENT_DATE - INTERVAL '30 days'
          AND status NOT IN ('archived', 'rejected')
    """)
    stale = cur.fetchone()[0]

    flagged = 0
    if stale > 0 and not dry_run:
        cur.execute("""
            UPDATE hermes_research_intelligence
            SET status = 'archived',
                tags = array_append(coalesce(tags, ARRAY[]::text[]), 'stale_freshness')
            WHERE freshness_date < CURRENT_DATE - INTERVAL '30 days'
              AND status NOT IN ('archived', 'rejected')
        """)
        flagged = cur.rowcount
        conn.commit()

    cur.close()
    return {"stale_found": stale, "flagged": flagged, "mode": "dry-run" if dry_run else "apply"}


def reembed_stale(conn, *, dry_run: bool = False) -> dict:
    """Detect embeddings where the source row was updated after embed was created.

    Enqueues affected rows back into hermes_embedding_queue.
    """
    cur = conn.cursor()

    # Check for news_articles created after their embedding was indexed
    cur.execute("""
        SELECT DISTINCT ce.source_type, ce.source_id::int
        FROM content_embeddings ce
        JOIN news_articles na ON na.id = ce.source_id::int AND ce.source_type = 'news'
        WHERE na.created_at > ce.created_at
        LIMIT 50
    """)
    pairs = [(st, sid) for st, sid in cur.fetchall()]

    enqueued = 0
    for source_type, source_id in pairs:
        if not dry_run:
            cur.execute("""
                INSERT INTO hermes_embedding_queue
                    (source_type, source_id, source_title, embedding_status, priority)
                SELECT %s, %s, COALESCE(na.title, ''), 'pending', 5
                FROM news_articles na WHERE na.id = %s
                ON CONFLICT (source_type, source_id)
                DO UPDATE SET embedding_status = 'pending', priority = 5
            """, (source_type, source_id, source_id))
        enqueued += 1

    if not dry_run:
        conn.commit()
    cur.close()
    return {"stale_embeddings_found": len(pairs), "enqueued": enqueued,
            "mode": "dry-run" if dry_run else "apply"}
