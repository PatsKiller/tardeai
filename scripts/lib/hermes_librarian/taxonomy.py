"""Content-subject taxonomy — separate from retired 3-axis taxonomy.

Classifies content into a subject-based taxonomy (themes, sectors, catalysts,
risk factors, etc.) stored in taxonomy_categories under a new 'content_subject'
axis. Local gemma3:4b for classification (temp 0, constrained slugs, rule cues
first), efficacy-graded via hermes_tag_efficacy pattern.

The retired 3-axis taxonomy (category_content/sector/lifecycle) in taxonomy.py
is NOT touched — this module writes a separate axis into taxonomy_categories.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.request
from collections import Counter
from datetime import datetime, timezone, date
from pathlib import Path
from typing import Any

OLLAMA_URL = "http://localhost:11434"
OLLAMA_TIMEOUT = 120
TAXONOMY_MODEL = os.environ.get("HERMES_TAXONOMY_MODEL", "gemma3:4b")

ROOT = Path(__file__).resolve().parents[3]
TAXONOMY_AXIS = "content_subject"

# Canonical subject tags — loaded from config or default
DEFAULT_CONTENT_TAGS = [
    "earnings", "mergers_acquisitions", "product_launch", "regulatory",
    "macro_economic", "geopolitical", "sector_rotation", "interest_rates",
    "commodity_price", "supply_chain", "competitive_landscape", "technological",
    "esg", "sentiment_shift", "volatility_event", "credit_event",
    "currency_impact", "seasonal_pattern", "corporate_action", "industry_trend",
]


def _ollama_classify(text: str, tags: list[str]) -> list[str]:
    """Local gemma classification with constrained JSON output."""
    prompt = f"""Classify this content into the most relevant subject tags. Return ONLY a JSON list of matching tags.

Available tags: {json.dumps(tags)}

Content: {text[:3000]}

Output format: ["tag1", "tag2"]"""
    try:
        payload = json.dumps({
            "model": TAXONOMY_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": {"num_ctx": 4096, "num_predict": 200, "temperature": 0.0},
            "format": "json",
        }).encode()
        req = urllib.request.Request(f"{OLLAMA_URL}/api/chat",
                                     data=payload, headers={"Content-Type": "application/json"})
        resp = urllib.request.urlopen(req, timeout=OLLAMA_TIMEOUT)
        result = json.loads(resp.read())
        content = result.get("message", {}).get("content", "[]")
        # Parse: could be a list or a JSON object with a tags field
        parsed = json.loads(content)
        if isinstance(parsed, list):
            return [t for t in parsed if t in tags]
        if isinstance(parsed, dict):
            raw = parsed.get("tags", parsed.get("categories", []))
            return [t for t in raw if t in tags]
        return []
    except Exception:
        return []


def _keyword_classify(text: str, tags: list[str]) -> list[str]:
    """Fast keyword-heuristic fallback when Ollama is unavailable."""
    text_lower = text.lower()
    keyword_map = {
        "earnings": ["earnings", "eps", "revenue beat", "guidance", "quarterly result"],
        "mergers_acquisitions": ["merger", "acquisition", "takeover", "buyout", "m&a"],
        "product_launch": ["product launch", "new product", "released", "announced"],
        "regulatory": ["regulation", "regulator", "sec", "compliance", "antitrust"],
        "macro_economic": ["gdp", "inflation", "cpi", "ppi", "unemployment", "fed", "central bank"],
        "geopolitical": ["war", "sanction", "tariff", "trade war", "geopolitic"],
        "sector_rotation": ["sector rotation", "rotation", "cyclical", "defensive"],
        "interest_rates": ["interest rate", "rate hike", "rate cut", "yield curve", "bond yield"],
        "commodity_price": ["oil price", "gold price", "commodity", "crude"],
        "supply_chain": ["supply chain", "shortage", "bottleneck", "logistics"],
        "competitive_landscape": ["competitor", "market share", "moat", "disruption"],
        "technological": ["ai ", "machine learning", "blockchain", "quantum", "chip"],
        "sentiment_shift": ["sentiment", "sentiment shift", "bearish", "bullish turnaround"],
        "volatility_event": ["vix", "volatility", "crash", "sell-off", "selloff", "plunge"],
    }
    matched = Counter()
    for tag, cues in keyword_map.items():
        for cue in cues:
            if cue in text_lower:
                matched[tag] += 1
    # Return tags with at least 2 cue hits, or all with 1 hit if nothing else
    result = [t for t, c in matched.items() if c >= 2]
    if not result:
        result = [t for t, c in matched.most_common(3)]
    return result[:5]


def classify_content(text: str, symbol: str | None = None,
                     *, prefer_llm: bool = True) -> list[str]:
    """Classify text content into subject tags.

    Args:
        text: Content to classify
        symbol: Optional ticker symbol for context
        prefer_llm: Try Ollama first, fall back to keywords

    Returns:
        List of content_subject tag slugs
    """
    tags = DEFAULT_CONTENT_TAGS
    if not text or len(text.strip()) < 20:
        return []

    if prefer_llm:
        try:
            result = _ollama_classify(text, tags)
            if result:
                return result
        except Exception:
            pass

    return _keyword_classify(text, tags)


def backfill_content_tags(conn, *, batch: int = 200, dry_run: bool = False) -> dict:
    """Tag hermes_research_intelligence rows missing content_tags.

    Only touches rows without content_tags, processing in batches.
    """
    cur = conn.cursor()
    cur.execute("""
        SELECT id, topic, summary, thesis, symbol
        FROM hermes_research_intelligence
        WHERE content_tags IS NULL AND status != 'archived'
        ORDER BY created_at DESC
        LIMIT %s
    """, (batch,))
    rows = cur.fetchall()
    if not rows:
        cur.close()
        return {"tagged": 0, "note": "no rows to tag"}

    tagged = 0
    errors = 0
    for row_id, topic, summary, thesis, symbol in rows:
        text = " ".join(filter(None, [topic or "", summary or "", thesis or ""]))
        if len(text) < 20:
            continue
        try:
            tags = classify_content(text, symbol=symbol)
            if tags and not dry_run:
                cur.execute("""
                    UPDATE hermes_research_intelligence
                    SET content_tags = %s
                    WHERE id = %s
                """, (tags, row_id))
            tagged += 1
        except Exception as e:
            errors += 1
            if errors <= 3:
                print(f"    tag error (row {row_id}): {e}")

    if not dry_run:
        conn.commit()
    cur.close()
    return {"tagged": tagged, "errors": errors, "batch_size": len(rows)}


def content_tag_efficacy(cur) -> dict:
    """Per-tag efficacy: hit rate vs base rate per tag, sampled from
    hermes_outcome_ledger join. Mirrors hermes_tag_engine efficacy pattern."""
    cur.execute("""
        SELECT t.tag, COUNT(*) as n,
               COUNT(CASE WHEN l.realized_r > 0 THEN 1 END)::float / NULLIF(COUNT(*), 0) as hit_rate
        FROM hermes_research_intelligence hri,
             LATERAL unnest(coalesce(hri.content_tags, ARRAY[]::text[])) t(tag)
        LEFT JOIN hermes_outcome_ledger l ON l.symbol = hri.symbol
            AND l.created_at > hri.created_at - INTERVAL '30 days'
            AND l.created_at < hri.created_at + INTERVAL '60 days'
        WHERE hri.content_tags IS NOT NULL
        GROUP BY t.tag
        HAVING COUNT(*) >= 10
        ORDER BY hit_rate DESC
    """)
    return {r["tag"]: {"n": r["n"], "hit_rate": float(r["hit_rate"])}
            for r in [dict(row) for row in cur.fetchall()]}


def retire_tag(conn, tag: str, reason: str) -> bool:
    """Flag a content tag as retired (low efficacy). Marker stored in taxonomy_categories."""
    cur = conn.cursor()
    cur.execute("""
        UPDATE taxonomy_categories
        SET enabled = false, notes = COALESCE(notes, '') || ' | RETIRED: ' || %s
        WHERE axis = %s AND slug = %s
        RETURNING id
    """, (reason, TAXONOMY_AXIS, tag))
    result = cur.fetchone()
    conn.commit()
    cur.close()
    return result is not None
