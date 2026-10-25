"""Process-current MemoryContext (Ring 2) — stdlib only, so light callers (n8n model jobs, bridges) can read the id
without importing intelligence_client and its storage dependencies (db_adapter → holdings → broker modules), which the
lane transitive-capability guard forbids (tests/test_lane_transitive_capabilities_20261015.py). intelligence_client
re-exports these exact objects; there is one ContextVar."""
from __future__ import annotations

import contextvars as _cv

_CURRENT_CTX: _cv.ContextVar[dict | None] = _cv.ContextVar("tradeai_intelligence_context", default=None)


def set_current_context(ctx: dict | None) -> None:
    """Make ``ctx`` the process-current MemoryContext so chokepoints the producer cannot pass a kwarg
    to (gate_and_generate via helpers, the :8766 bridge clients) still see its id (Ring 2, 01 §2).
    shadow_open sets it; shadow_commit clears it."""
    _CURRENT_CTX.set(ctx)


def current_context_id() -> str | None:
    c = _CURRENT_CTX.get()
    return c.get("context_id") if isinstance(c, dict) else None


def current_retrieval_receipt_id() -> str | None:
    c = _CURRENT_CTX.get()
    return c.get("retrieval_receipt") if isinstance(c, dict) else None
