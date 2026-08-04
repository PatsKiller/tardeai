"""Knowledge graph builder — co-occurrence edges, alias management, query expansion.

Builds entity_cooccurrence edges from content_entity_links, manages alias
resolution, and prunes stale edges. Used by RAG retrieval for query expansion
and by the librarian for entity-aware curation.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).resolve().parents[3]


def refresh_cooccurrence(conn, *, window_days: int = 30, min_weight: int = 2,
                          dry_run: bool = False) -> dict:
    """Build entity co-occurrence edges from content_entity_links.

    Two entities co-occur if they appear in the same source row (same source_type
    + source_id) within the window. Edges are additive (weight increments on re-sighting).

    Args:
        conn: DB connection
        window_days: Lookback window for edges
        min_weight: Minimum co-occurrence count to create an edge
        dry_run: If True, only compute stats, don't write

    Returns:
        dict with edge_count, entity_count, pruned_count
    """
    cur = conn.cursor()

    # Count co-occurrences within the window
    cur.execute("""
        WITH windowed AS (
            SELECT content_type, content_id, entity_value, entity_type
            FROM content_entity_links
            WHERE created_at > NOW() - INTERVAL '%s days'
              AND entity_value IS NOT NULL
        )
        SELECT a.entity_value, a.entity_type, b.entity_value, b.entity_type,
               COUNT(*) as weight
        FROM windowed a
        JOIN windowed b
          ON a.content_type = b.content_type AND a.content_id = b.content_id
         AND a.entity_value < b.entity_value
        GROUP BY 1, 2, 3, 4
        HAVING COUNT(*) >= %s
        ORDER BY weight DESC
    """, (window_days, min_weight))
    pairs = [(ea, ta, eb, tb, w) for ea, ta, eb, tb, w in cur.fetchall()]

    if not pairs:
        cur.close()
        return {"edge_count": 0, "entity_count": 0, "pruned": 0}

    if dry_run:
        cur.close()
        return {"edge_count": len(pairs), "entity_count": 0, "pruned": 0,
                "mode": "dry_run", "top_edges": [
                    {"a": ea, "b": eb, "weight": w} for ea, ta, eb, tb, w in pairs[:5]
                ]}

    # Upsert edges
    upserted = 0
    for ea, ta, eb, tb, w in pairs:
        cur.execute("""
            INSERT INTO hermes_entity_cooccurrence
                (entity_a, entity_b, entity_type_a, entity_type_b, weight, window_days, last_seen)
            VALUES (%s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (entity_a, entity_b)
            DO UPDATE SET weight = EXCLUDED.weight, last_seen = NOW()
        """, (ea, eb, ta, tb, w, window_days))
        upserted += 1

    conn.commit()
    cur.close()

    return {"edge_count": upserted, "entity_count": 0, "pruned": 0,
            "top_edges": [{"a": ea, "b": eb, "weight": w}
                          for ea, ta, eb, tb, w in pairs[:5]]}


def merge_alias(conn, canonical: str, alias: str, entity_type: str) -> dict:
    """Register an alias → canonical mapping. Used when the same entity appears
    under multiple names (e.g., 'NVDA' / 'NVIDIA', 'Fed' / 'Federal Reserve')."""
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO hermes_entity_alias_map (canonical_value, entity_type, aliases)
        VALUES (%s, %s, ARRAY[%s])
        ON CONFLICT (canonical_value)
        DO UPDATE SET aliases = (
            SELECT array_agg(DISTINCT a) FROM unnest(
                hermes_entity_alias_map.aliases || ARRAY[%s]
            ) a
        ), updated_at = NOW()
        RETURNING canonical_value
    """, (canonical, entity_type, alias, alias))
    result = cur.fetchone()
    conn.commit()
    cur.close()
    return {"canonical": canonical, "alias_added": alias,
            "existed": result is not None}


def prune_stale_edges(conn, *, stale_days: int = 90, dry_run: bool = False) -> int:
    """Remove edges not sighted within stale_days."""
    cur = conn.cursor()
    cur.execute("""
        SELECT COUNT(*) FROM hermes_entity_cooccurrence
        WHERE last_seen < NOW() - INTERVAL '%s days'
    """, (stale_days,))
    stale = cur.fetchone()[0]
    if stale > 0 and not dry_run:
        cur.execute("""
            DELETE FROM hermes_entity_cooccurrence
            WHERE last_seen < NOW() - INTERVAL '%s days'
        """, (stale_days,))
        conn.commit()
    cur.close()
    return stale


def expand_entities(query: str, conn=None) -> list[str]:
    """Given a query string, return related entities via alias map + one-hop co-occurrence.

    Example: expand_entities("NVDA") → ["NVIDIA", "semiconductors", "AI", "AMD", "SMH"]

    Args:
        query: Entity name or symbol to expand
        conn: Optional DB connection (if None, returns empty list)

    Returns:
        List of related entity names
    """
    if conn is None:
        return []

    cur = conn.cursor()
    entities = []

    # 1. Alias lookup
    cur.execute("""
        SELECT aliases FROM hermes_entity_alias_map
        WHERE canonical_value = %s
        UNION
        SELECT ARRAY[canonical_value] FROM hermes_entity_alias_map
        WHERE %s = ANY(aliases)
    """, (query, query))
    for row in cur.fetchall():
        entities.extend(row[0])

    # 2. One-hop co-occurrence edges
    cur.execute("""
        SELECT CASE WHEN entity_a = %s THEN entity_b ELSE entity_a END as neighbor,
               MAX(weight) as w
        FROM hermes_entity_cooccurrence
        WHERE entity_a = %s OR entity_b = %s
        GROUP BY 1
        ORDER BY w DESC
        LIMIT 10
    """, (query, query, query))
    for neighbor, w in cur.fetchall():
        if neighbor not in entities:
            entities.append(neighbor)

    cur.close()
    return list({e for e in entities if e and e != query})
