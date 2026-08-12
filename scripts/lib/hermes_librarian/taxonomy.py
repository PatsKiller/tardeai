"""Content-subject taxonomy — RETIRED 2026-08-12.

This module's write path (`content_tags` on `hermes_research_intelligence`,
`content_subject` axis in `taxonomy_categories`) was never scheduled and had
zero consumers repo-wide. It is superseded by `strategy_tags`
(`scripts/hermes_tag_engine.py`), which is the single canonical tag axis.

See docs/TAXONOMY_AUTHORITATIVE_CONTRACT.md.

`classify_content` / `_keyword_classify` / `_ollama_classify` are retained
harmlessly (no DB writes) for potential reuse. All DB-writing functions are
now no-ops that return a "retired" status.
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
    """RETIRED — content_subject taxonomy superseded by strategy_tags.

    Returns a "retired" status and performs no DB writes. Kept for CLI/schedule
    compatibility so any existing `--scope taxonomy` invocation degrades safely.
    """
    return {"status": "retired",
            "note": "content_subject taxonomy retired 2026-08-12; strategy_tags is canonical"} 


def content_tag_efficacy(cur) -> dict:
    """RETIRED — no consumer for content_subject efficacy. Returns empty dict."""
    return {}


def retire_tag(conn, tag: str, reason: str) -> bool:
    """RETIRED — content_subject axis never seeded; no-op."""
    return False
