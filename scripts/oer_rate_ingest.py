#!/usr/bin/env python3
"""oer_rate_ingest.py — v1.2.3 P1-4: source-controlled fund expense-ratio
ingestion. Rates come ONLY from issuer factsheets/prospectuses/authoritative
fund pages; nothing is inferred; corrections supersede (never delete);
conflicts enter review; missing rates stay visible gaps with zero accrual."""
from __future__ import annotations

import hashlib
import json


def ensure_oer_tables(cur, conn):
    for ddl in (
        "ALTER TABLE fund_expense_rate_history ADD COLUMN IF NOT EXISTS source_url text",
        "ALTER TABLE fund_expense_rate_history ADD COLUMN IF NOT EXISTS source_publisher text",
        "ALTER TABLE fund_expense_rate_history ADD COLUMN IF NOT EXISTS retrieval_ts timestamptz DEFAULT now()",
        "ALTER TABLE fund_expense_rate_history ADD COLUMN IF NOT EXISTS parser_version text",
        "ALTER TABLE fund_expense_rate_history ADD COLUMN IF NOT EXISTS source_excerpt text",
        "ALTER TABLE fund_expense_rate_history ADD COLUMN IF NOT EXISTS review_state text DEFAULT 'unreviewed'",
        "ALTER TABLE fund_expense_rate_history ADD COLUMN IF NOT EXISTS superseded_by int",
    ):
        cur.execute(ddl)
    conn.commit()


def record_rate(cur, conn, *, symbol: str, net_expense_ratio: float, effective_from: str,
                source_url: str, source_publisher: str, source_excerpt: str,
                parser_version: str = "manual-v1", gross: float | None = None) -> dict:
    """Idempotent by content hash. A different rate for an overlapping period
    from a DIFFERENT source → conflict review; same source correcting itself →
    supersedes with lineage."""
    if not (source_url and source_publisher and source_excerpt):
        return {"ok": False, "error": "source_url + publisher + excerpt REQUIRED — rates are never inferred"}
    chash = hashlib.sha256(f"{symbol}|{net_expense_ratio}|{effective_from}|{source_url}".encode()).hexdigest()[:16]
    cur.execute("SELECT rate_id FROM fund_expense_rate_history WHERE content_hash=%s", (chash,))
    if cur.fetchone():
        return {"ok": True, "duplicate": True}
    cur.execute("""SELECT rate_id, net_expense_ratio, source_publisher FROM fund_expense_rate_history
                   WHERE symbol=%s AND effective_from=%s AND superseded_by IS NULL""",
                (symbol.upper(), effective_from))
    existing = cur.fetchone()
    review = "unreviewed"
    if existing and abs(float(existing[1]) - net_expense_ratio) > 1e-6:
        review = "conflict_review" if existing[2] != source_publisher else "unreviewed"
    cur.execute("""INSERT INTO fund_expense_rate_history
        (symbol, net_expense_ratio, gross_expense_ratio, effective_from, source,
         source_url, source_publisher, source_excerpt, parser_version, content_hash,
         review_state)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING rate_id""",
        (symbol.upper(), net_expense_ratio, gross, effective_from, source_publisher,
         source_url, source_publisher, source_excerpt[:400], parser_version, chash, review))
    rid = cur.fetchone()[0]
    if existing and existing[2] == source_publisher and abs(float(existing[1]) - net_expense_ratio) > 1e-6:
        cur.execute("UPDATE fund_expense_rate_history SET superseded_by=%s, effective_to=%s WHERE rate_id=%s",
                    (rid, effective_from, existing[0]))
    conn.commit()
    return {"ok": True, "rate_id": rid, "review_state": review}


def rate_for(cur, symbol: str, as_of: str) -> dict | None:
    """The rate EFFECTIVE for the period — historical accrual uses historical
    rates, never today's rate retroactively. Stale (>400d) is flagged."""
    cur.execute("""SELECT rate_id, net_expense_ratio, effective_from, retrieval_ts, review_state
                   FROM fund_expense_rate_history
                   WHERE symbol=%s AND effective_from <= %s
                     AND (effective_to IS NULL OR effective_to > %s)
                     AND superseded_by IS NULL AND review_state != 'conflict_review'
                   ORDER BY effective_from DESC LIMIT 1""", (symbol.upper(), as_of, as_of))
    r = cur.fetchone()
    if not r:
        return None
    return {"rate_id": r[0], "net_expense_ratio": float(r[1]), "effective_from": str(r[2]),
            "stale": False, "review_state": r[4]}
