"""One num_ctx rule for direct Ollama callers (refresh of PR #165).

Why it matters (07-04 and 07-23 incidents): gemma3:12b must stay at num_ctx 4096 on the Arc B50 —
larger contexts split Vulkan→CPU and emit pad garbage — and any request whose num_ctx differs from
the resident runner's forces a full reload, which queue-wedges every other Ollama caller behind it
(07-23: a 27m49s hung request, 180s escalation read timeouts). Callers used to hard-code 512, 4096,
8192 and 16384 for the same models.

Rule (already used by trade_close_llm_analyzer and trade_strategy_classifier): 12b/27b → 4096;
every other model → OLLAMA_NUM_CTX (default 8192).
"""

from __future__ import annotations

import os
from typing import Optional

SMALL_GPU_CTX = 4096
_LARGE_MODEL_MARKERS = ("12b", "27b")


def canonical_num_ctx(model: Optional[str]) -> int:
    name = str(model or "").lower()
    if any(marker in name for marker in _LARGE_MODEL_MARKERS):
        return SMALL_GPU_CTX
    raw = str(os.environ.get("OLLAMA_NUM_CTX") or "").strip()
    try:
        return int(raw) if raw else 8192
    except ValueError:
        return 8192


def resident_num_ctx(model: str, *, ps_models: Optional[list] = None) -> Optional[int]:
    """Context length of the already-loaded runner for ``model`` (from /api/ps), or None."""
    for m in ps_models or []:
        if m.get("name") == model or m.get("model") == model:
            try:
                return int(m.get("context_length")) if m.get("context_length") else None
            except (TypeError, ValueError):
                return None
    return None


__all__ = ["SMALL_GPU_CTX", "canonical_num_ctx", "resident_num_ctx"]
