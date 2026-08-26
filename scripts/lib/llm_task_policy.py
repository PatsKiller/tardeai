"""Local model policy: pinned nomic embeddings only.

No local generative model is permitted for math, judgment, research, prose, or
fallback. Math is deterministic Python. Environment flags cannot re-enable a
generative path. READ_ONLY_ADVISORY.
"""
from __future__ import annotations

from typing import Iterable, Optional

KIND_MATH = "math"
KIND_JUDGMENT = "judgment"
KIND_EMBED = "embed"

NOMIC_EMBED = "nomic-embed-text"

POLICY_LOCAL_GENERATIVE_FORBIDDEN = "POLICY_LOCAL_GENERATIVE_FORBIDDEN (embeddings-only)"
POLICY_LOCAL_JUDGMENT_FORBIDDEN = POLICY_LOCAL_GENERATIVE_FORBIDDEN

# Exact task ids treated as numeric / scoring work — local LLM allowed.
_MATH_EXACT = frozenset({
    "math",
    "numeric",
    "arithmetic",
    "calculation",
    "calc",
    "score_calc",
    "token_count",
    "stats",
    "numeric_score",
    "rank_score",
    "embedding_similarity",
})
_MATH_PREFIXES = ("math_", "numeric_")

_EMBED_EXACT = frozenset({
    "embed",
    "embedding",
    "embeddings",
    "nomic-embed",
    "nomic-embed-text",
    "rag_embed",
    "vectorize",
})
_EMBED_PREFIXES = ("embed_",)

# Documented judgment examples (anything not math/embed is judgment).
_JUDGMENT_EXAMPLES = frozenset({
    "agent_narrative",
    "agent_debate",
    "cio_synthesis",
    "catalyst_classification",
    "sentiment",
    "code_generation",
    "fast_summary",
    "research",
    "thesis",
    "default",
})


def _norm(task: str | None) -> str:
    return str(task or "").strip().lower()


def classify_task(task: str) -> str:
    """Return ``math`` | ``judgment`` | ``embed``."""
    t = _norm(task)
    if not t:
        return KIND_JUDGMENT
    if t in _EMBED_EXACT or t.startswith(_EMBED_PREFIXES):
        return KIND_EMBED
    if t in _MATH_EXACT or t.startswith(_MATH_PREFIXES):
        return KIND_MATH
    return KIND_JUDGMENT


def local_judgment_allowed() -> bool:
    """Local generative judgment cannot be enabled by runtime flags."""
    return False


def is_nomic_embed(model: str | None) -> bool:
    return NOMIC_EMBED in str(model or "").strip().lower()


def _embed_model(local_model: str | None = None) -> str:
    if local_model:
        return str(local_model).strip()
    return NOMIC_EMBED


def allow_local_llm(task: str, *, local_model: str | None = None) -> bool:
    """True only for embeddings using the pinned nomic model contract."""
    kind = classify_task(task)
    if kind == KIND_EMBED:
        return is_nomic_embed(_embed_model(local_model))
    return False


def filter_local_providers(
    task: str,
    providers: Iterable[str],
    *,
    local_model: str | None = None,
) -> tuple[list[str], Optional[str]]:
    """Drop ``local`` from a provider chain when policy forbids it.

    Returns (filtered_providers, skip_reason_or_none).
    Does not touch deepseek-flash / grok / claude / openai entries.
    """
    chain = [str(p) for p in providers]
    if "local" not in chain:
        return chain, None
    if allow_local_llm(task, local_model=local_model):
        return chain, None
    skipped = [p for p in chain if p != "local"]
    return skipped, f"local: {POLICY_LOCAL_GENERATIVE_FORBIDDEN}"
