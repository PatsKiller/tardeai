#!/usr/bin/env python3
"""llm_content_quality.py — Fail-closed quality gate for llm_intelligence_cache writes.

Home AI Intelligence Briefing (morning_synthesis / portfolio_risk) previously
accepted and displayed garbage such as repeated markdown fragments
(". **##. **##…"). Same pattern as watchlist failed-LLM narrative guard:
reject bad content so the last good cache row stays live.

Used by scripts/llm_intelligence_enrichment.py. Pure functions — no I/O.
"""
from __future__ import annotations

import re
from typing import Optional, Tuple

# Patterns that indicate truncated / failed local-LLM output rather than prose.
_GARBAGE_RES = [
    re.compile(r"(\*\*##\.?\s*){3,}"),           # . **##. **##. **##…
    re.compile(r"(##\s*){4,}"),                  # bare ## spam
    re.compile(r"^\s*[.\-_*#\s]{20,}$"),        # only punctuation/whitespace
    re.compile(r"(LLM error|Ollama (unavailable|timeout)|All LLM attempts failed)", re.I),
    re.compile(r"^(ready|ok|test)\s*$", re.I),
]

_MIN_CHARS = {
    "morning_synthesis": 80,
    "portfolio_risk": 80,
    "rebalance_suggestions": 60,
    "recovery_analysis": 60,
    "prospect_narratives": 20,
}

_MIN_ALPHA_RATIO = 0.45  # letters / total printable — catches "## ## ##"


def _alpha_ratio(text: str) -> float:
    if not text:
        return 0.0
    letters = sum(1 for c in text if c.isalpha())
    printable = sum(1 for c in text if not c.isspace())
    return (letters / printable) if printable else 0.0


def is_usable_llm_content(section: str, content: Optional[str]) -> Tuple[bool, str]:
    """Return (ok, reason). ok=False means do not overwrite the cache."""
    if content is None:
        return False, "empty"
    text = str(content).strip()
    if not text:
        return False, "empty"

    # prospect_narratives may be JSON — allow after basic length check
    min_len = _MIN_CHARS.get(section, 40)
    if len(text) < min_len:
        return False, f"too_short ({len(text)} < {min_len})"

    for rx in _GARBAGE_RES:
        if rx.search(text):
            return False, f"garbage_pattern:{rx.pattern[:40]}"

    if section != "prospect_narratives" and _alpha_ratio(text) < _MIN_ALPHA_RATIO:
        return False, f"low_alpha_ratio ({_alpha_ratio(text):.2f})"

    # Repeated token collapse (same 3–12 char token ≥ 8 times)
    toks = re.findall(r"[A-Za-z#*]{3,12}", text)
    if toks:
        from collections import Counter
        most, n = Counter(toks).most_common(1)[0]
        if n >= 8 and n / max(len(toks), 1) > 0.35:
            return False, f"token_spam:{most}x{n}"

    return True, "ok"


def strip_think_tags(text: str) -> str:
    """Remove residual model think blocks if any leak past /no_think."""
    if not text:
        return text
    text = re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.I)
    text = re.sub(r"</?think>", "", text, flags=re.I)
    return text.strip()
