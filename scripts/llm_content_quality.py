"""llm_content_quality.py — fail-closed prose checks for Home AI briefing cache.

Used by llm_intelligence_enrichment before upsert into llm_intelligence_cache so
corrupt local-LLM output (known gemma **## spam, truncated markdown, empty shells)
never becomes the operator-facing Morning Synthesis / Portfolio Risk body.

Pure functions — no DB, no network. Unit-testable.
"""
from __future__ import annotations

import re

# Patterns observed on Home 2026-07-26: repeated ". **##. **##" from a failed
# gemma3 generation that still passed a non-empty check and was cached.
_CORRUPT_MARKERS = (
    "**##",
    ". **##",
    "##. **",
    "###.",
)

_MIN_CHARS = 40
_MIN_ALPHA_RATIO = 0.40


def is_valid_prose(text: str | None, *, min_chars: int = _MIN_CHARS) -> bool:
    """Return True only when text looks like operator-usable flowing prose."""
    if not text or not isinstance(text, str):
        return False
    s = text.strip()
    if len(s) < min_chars:
        return False
    for marker in _CORRUPT_MARKERS:
        if s.count(marker) >= 2:
            return False
    # Heavy markdown-heading spam with almost no words
    if len(re.findall(r"#{2,}", s)) >= 8 and len(s) < 400:
        return False
    alpha = sum(1 for c in s if c.isalpha())
    if alpha < len(s) * _MIN_ALPHA_RATIO:
        return False
    # Reject pure JSON / code fences dumped as the body
    if s.startswith("{") and s.endswith("}") and "content" in s[:80]:
        return False
    if s.startswith("```") and s.count("```") >= 2 and alpha < 80:
        return False
    return True


def extract_prose(value) -> str:
    """Normalize cache shapes: raw string, or {content|summary|text}."""
    if value is None:
        return ""
    if isinstance(value, dict):
        for k in ("content", "summary", "text", "body"):
            v = value.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        return ""
    if isinstance(value, str):
        s = value.strip()
        if s.startswith("{") and "content" in s[:120]:
            try:
                import json
                obj = json.loads(s)
                return extract_prose(obj)
            except Exception:
                return s
        return s
    return str(value).strip()


def quality_report(text: str | None) -> dict:
    """Debug helper for operators / tests."""
    prose = extract_prose(text)
    return {
        "ok": is_valid_prose(prose),
        "chars": len(prose),
        "alpha_ratio": (sum(1 for c in prose if c.isalpha()) / len(prose)) if prose else 0.0,
        "corrupt_marker_hits": sum(prose.count(m) for m in _CORRUPT_MARKERS),
        "preview": prose[:120],
    }
