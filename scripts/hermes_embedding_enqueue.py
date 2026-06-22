#!/usr/bin/env python3
"""Enqueue Hermes promoted research for RAG embedding.

Called by hermes_coordinator after auto-promote. Also usable as a one-shot backfill CLI.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


def _db_conn():
    import psycopg2
    pw = os.getenv("DB_PASSWORD", "")
    if not pw:
        for line in (PROJECT_ROOT / ".env").read_text().splitlines():
            if line.startswith("DB_PASSWORD="):
                pw = line.split("=", 1)[1].strip()
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        port=int(os.getenv("DB_PORT", "5432")),
        dbname=os.getenv("DB_NAME", "trade_ai"),
        user=os.getenv("DB_USER", "trade_ai"),
        password=pw,
    )


def _research_content(cur, research_id: int) -> tuple[str, str] | None:
    cur.execute(
        """SELECT topic, summary, thesis, symbol, research_type, hermes_agent_name
           FROM hermes_research_intelligence WHERE id=%s""",
        (research_id,),
    )
    row = cur.fetchone()
    if not row:
        return None
    topic, summary, thesis, symbol, rtype, agent = row
    title = (topic or f"Research #{research_id}")[:200]
    parts = [f"Symbol: {symbol}" if symbol else None, f"Type: {rtype}", f"Agent: {agent}",
             summary or "", thesis or ""]
    content = "\n".join(p for p in parts if p)[:8000]
    return title, content


def enqueue_research(cur, research_id: int, *, skip_existing: bool = True) -> bool:
    """Insert one row into hermes_embedding_queue. Returns True if enqueued."""
    if skip_existing:
        cur.execute(
            """SELECT 1 FROM hermes_embedding_queue WHERE source_research_id=%s
               AND embedding_status IN ('pending','processing','completed') LIMIT 1""",
            (research_id,),
        )
        if cur.fetchone():
            return False
        cur.execute(
            "SELECT 1 FROM content_embeddings WHERE source_type='hermes_research' AND source_id=%s LIMIT 1",
            (research_id,),
        )
        if cur.fetchone():
            return False

    payload = _research_content(cur, research_id)
    if not payload:
        return False
    title, content = payload
    cur.execute(
        """INSERT INTO hermes_embedding_queue
           (source, source_research_id, title, content, source_type_target, embedding_status)
           VALUES ('hermes', %s, %s, %s, 'hermes_research', 'pending')""",
        (research_id, title, content),
    )
    return True


def backfill_promoted(conn, *, limit: int = 500, dry_run: bool = False) -> int:
    """Enqueue promoted rows missing from queue and content_embeddings."""
    cur = conn.cursor()
    cur.execute(
        """SELECT h.id FROM hermes_research_intelligence h
           WHERE h.status='promoted'
             AND NOT EXISTS (
               SELECT 1 FROM hermes_embedding_queue q
               WHERE q.source_research_id=h.id AND q.embedding_status IN ('pending','processing','completed'))
             AND NOT EXISTS (
               SELECT 1 FROM content_embeddings ce
               WHERE ce.source_type='hermes_research' AND ce.source_id=h.id)
           ORDER BY h.id LIMIT %s""",
        (limit,),
    )
    ids = [r[0] for r in cur.fetchall()]
    enqueued = 0
    for rid in ids:
        if dry_run:
            enqueued += 1
            continue
        if enqueue_research(cur, rid, skip_existing=False):
            enqueued += 1
    if not dry_run:
        conn.commit()
    return enqueued


def main():
    parser = argparse.ArgumentParser(description="Enqueue Hermes research for RAG embedding")
    parser.add_argument("--backfill", action="store_true", help="Backfill all unembedded promoted rows")
    parser.add_argument("--research-id", type=int, help="Enqueue a single research id")
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    conn = _db_conn()
    try:
        if args.research_id:
            cur = conn.cursor()
            ok = enqueue_research(cur, args.research_id)
            if not args.dry_run:
                conn.commit()
            print(f"{'enqueued' if ok else 'skipped'} research_id={args.research_id}")
            return 0
        if args.backfill:
            n = backfill_promoted(conn, limit=args.limit, dry_run=args.dry_run)
            print(f"{'would enqueue' if args.dry_run else 'enqueued'} {n} promoted rows")
            return 0
        parser.print_help()
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())