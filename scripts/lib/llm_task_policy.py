"""Local-LLM task policy: math (and local nomic embed) only.

Operator 2026-08-21: unless the task is math/numeric, do not use local LLM
(gemma/qwen/ollama) for judgment / research / prose.

Live default local is gemma3:4b. Installed: gemma3:4b / 12b / 27b /
gemma3-overnight, qwen3:8b. qwen3:1.7b is NOT installed.
US overnight judgment = ChatGPT OAuth (overnight_llm_policy).
DeepSeek Flash :8766 is the metered research lane.

Flags (judgment local — default OFF):
  RESEARCH_ALLOW_LOCAL_LLM=1
  LLM_ALLOW_LOCAL_JUDGMENT=1   (rollback)

READ_ONLY_ADVISORY. Does not call providers. Does not flip influence.
"""
from __future__ import annotations

import os
from typing import Iterable, Optional

KIND_MATH = "math"
KIND_JUDGMENT = "judgment"
KIND_EMBED = "embed"

NOMIC_EMBED = "nomic-embed-text"

POLICY_LOCAL_JUDGMENT_FORBIDDEN = (
    "POLICY_LOCAL_JUDGMENT_FORBIDDEN "
    "(math-only unless LLM_ALLOW_LOCAL_JUDGMENT=1 or RESEARCH_ALLOW_LOCAL_LLM=1)"
)

TRUTHY = frozenset({"1", "true", "yes", "on"})

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


def _flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in TRUTHY


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
    """True only when an operator rollback flag is set."""
    return _flag("RESEARCH_ALLOW_LOCAL_LLM") or _flag("LLM_ALLOW_LOCAL_JUDGMENT")


def is_nomic_embed(model: str | None) -> bool:
    return NOMIC_EMBED in str(model or "").strip().lower()


def _embed_model(local_model: str | None = None) -> str:
    if local_model:
        return str(local_model).strip()
    env = os.getenv("LLM_EMBEDDING", "").strip()
    if env:
        return env
    return NOMIC_EMBED


def allow_local_llm(task: str, *, local_model: str | None = None) -> bool:
    """True only for math, or embed when the local model is nomic-embed-text.

    Judgment requires RESEARCH_ALLOW_LOCAL_LLM=1 or LLM_ALLOW_LOCAL_JUDGMENT=1.
    """
    kind = classify_task(task)
    if kind == KIND_MATH:
        return True
    if kind == KIND_EMBED:
        return is_nomic_embed(_embed_model(local_model))
    return local_judgment_allowed()


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
    return skipped, f"local: {POLICY_LOCAL_JUDGMENT_FORBIDDEN}"
