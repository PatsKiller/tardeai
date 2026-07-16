#!/usr/bin/env python3
"""Reports Desk v1 (WS-F): deterministic Intelligence Highlights for weekly/monthly
reports — the June-7 audit gap (Hermes fed zero reports; morning bundle was wired
2026-07-16, this covers the weekly cadence; monthly flagged — shared builder).

Pure SQL pull, zero LLM: the period's top Hermes research items (promoted/reviewed,
QA-clean confidence floor) + exit-intelligence advisories for held names.
"""
from __future__ import annotations


def _rows(cur):
    """Rows as dicts whether the cursor is tuple-based or RealDictCursor."""
    cols = [c[0] for c in cur.description]
    out = []
    for r in cur.fetchall():
        out.append(dict(r) if isinstance(r, dict) else dict(zip(cols, r)))
    return out


def fetch_intel_highlights(cur, days: int = 7, limit: int = 8) -> dict:
    """cur: psycopg2 cursor (tuple or dict row factory).
    Returns {research: [...], exit_advisories: [...]}."""
    cur.execute("""
        SELECT symbol, topic, left(coalesce(summary,''), 220) AS summary,
               research_type, confidence_score, created_at::date AS d
        FROM hermes_research_intelligence
        WHERE status IN ('promoted','reviewed')
          AND coalesce(confidence_score, 0) >= 0.6
          AND created_at > now() - (%s || ' days')::interval
          AND research_type NOT IN ('research_backlog','backlog_resolution')
        ORDER BY confidence_score DESC NULLS LAST, created_at DESC
        LIMIT %s""", (days, limit))
    research = _rows(cur)

    cur.execute("""
        SELECT symbol, topic, left(coalesce(summary,''), 220) AS summary,
               confidence_score, created_at::date AS d
        FROM hermes_research_intelligence
        WHERE research_type = 'exit_intelligence'
          AND created_at > now() - (%s || ' days')::interval
        ORDER BY created_at DESC LIMIT %s""", (days, limit))
    exits = _rows(cur)
    return {"research": research, "exit_advisories": exits}
