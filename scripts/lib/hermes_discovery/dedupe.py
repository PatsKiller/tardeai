"""Normalized-key builder + near-duplicate clustering for Hermes discovery candidates.

Pure functions — no DB access here. inbox.py wires these to the tables.
HARD RULE honored by design: operator-created candidates/directives are NEVER
auto-merged — every clustering entry point takes an `is_operator` flag that
blocks merging in BOTH directions (an operator row is never merged into a
cluster, and machine rows are never merged into an operator row).
"""
from __future__ import annotations

import re
from typing import Any, Iterable

# Small, deliberately conservative stopword list — enough to make
# "The AI datacenter buildout" and "AI datacenter buildout trend" collide
# without mangling finance-specific phrasing.
STOPWORDS = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in",
    "into", "is", "it", "its", "of", "on", "or", "over", "that", "the",
    "their", "this", "to", "trend", "was", "were", "will", "with",
})

_PUNCT_RE = re.compile(r"[^a-z0-9\s]+")
_WS_RE = re.compile(r"\s+")

# Token Jaccard threshold for two trend labels to be considered the same story.
NEAR_DUP_JACCARD = 0.6


def normalize_key(text: str) -> str:
    """Lowercase, strip punctuation and stopwords, collapse whitespace.

    Deterministic — the same label always yields the same key, which is what
    makes upsert_candidate idempotent across repeated discoveries.
    """
    lowered = (text or "").lower()
    lowered = _PUNCT_RE.sub(" ", lowered)
    parts = [t for t in _WS_RE.split(lowered) if t and t not in STOPWORDS]
    return " ".join(parts)


def tokenize(text: str) -> frozenset[str]:
    """Token set used for Jaccard similarity (normalized first)."""
    return frozenset(normalize_key(text).split())


def jaccard(a: Iterable[str], b: Iterable[str]) -> float:
    """Token-set Jaccard similarity in [0, 1]."""
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def find_near_duplicate(
    label: str,
    existing: list[dict[str, Any]],
    *,
    is_operator: bool = False,
    threshold: float = NEAR_DUP_JACCARD,
) -> dict[str, Any] | None:
    """Return the best near-duplicate row from `existing`, or None.

    `existing` rows need at least {"label": str} and may carry "is_operator".
    Operator protection (both directions):
      - is_operator=True  → never merged into anything (returns None).
      - rows with is_operator truthy are never returned as merge targets.
    """
    if is_operator:
        return None
    new_tokens = tokenize(label)
    if not new_tokens:
        return None
    best: dict[str, Any] | None = None
    best_sim = 0.0
    for row in existing:
        if row.get("is_operator"):
            continue  # never auto-merge with an operator-created row
        sim = jaccard(new_tokens, tokenize(str(row.get("label") or "")))
        if sim >= threshold and sim > best_sim:
            best, best_sim = row, sim
    if best is not None:
        best = dict(best)
        best["_similarity"] = round(best_sim, 4)
    return best
