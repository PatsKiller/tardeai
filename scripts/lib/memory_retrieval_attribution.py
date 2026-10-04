"""Who a memory retrieval was performed for, when the caller genuinely knows.

aif_memory_retrievals.jsonl carried no agent, so /v3/agents could only say
memory retrieval was NOT_EXPOSED for every agent (186,311 unattributed rows on
2026-10-03). A caller that holds an identity wraps its retrieval in
``retrieval_attribution(...)``; the durable provider stamps those fields onto
the receipt it already writes. Nothing is inferred or backfilled: a field is
recorded only when a caller passed a non-empty value. Operator-approved
2026-10-03 (additive, never backfilled).
"""
from __future__ import annotations

import contextlib
import contextvars
import sys
from typing import Any, Iterator

FIELDS = ("agent_id", "wake_id", "trace_id", "decision_id")

# One variable per process, even if this file is imported under two module names
# (``memory_retrieval_attribution`` via intelligence_client._lib and
# ``scripts.lib.memory_retrieval_attribution``): two copies would each hold their
# own ContextVar and the writer would never see what the caller set.
_ANCHOR = "_tradeai_memory_retrieval_attribution"
_CURRENT: contextvars.ContextVar[dict[str, str]] = getattr(sys, _ANCHOR, None) or contextvars.ContextVar(
    "memory_retrieval_attribution", default={}
)
setattr(sys, _ANCHOR, _CURRENT)


def clean(fields: dict[str, Any] | None) -> dict[str, str]:
    """Only the known fields, only non-empty string values."""
    out: dict[str, str] = {}
    for key in FIELDS:
        value = (fields or {}).get(key)
        text = str(value).strip() if value is not None else ""
        if text and text.lower() not in {"none", "null"}:
            out[key] = text
    return out


@contextlib.contextmanager
def retrieval_attribution(**fields: Any) -> Iterator[dict[str, str]]:
    """Attribute retrievals made inside this block. Nests: inner values add to outer ones."""
    merged = {**_CURRENT.get(), **clean(fields)}
    token = _CURRENT.set(merged)
    try:
        yield merged
    finally:
        _CURRENT.reset(token)


def current() -> dict[str, str]:
    return dict(_CURRENT.get())
