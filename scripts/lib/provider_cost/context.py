"""Narrow attribution context for canonical ProviderCostEvent emission.

Wrappers that already call deepseek_client.chat must NOT emit a second event.
They set this context so the canonical client can stamp service/process/lane
attribution onto the single event.

Never stores raw API keys.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator, Optional

_ATTR: ContextVar[Optional[dict[str, Any]]] = ContextVar(
    "provider_cost_attribution", default=None
)

_ALLOWED = (
    "source_service",
    "source_process",
    "source_lane",
    "agent",
    "run_id",
    "reservation_id",
    "environment",
    "process_id",
)


def current_attribution() -> dict[str, Any]:
    raw = _ATTR.get()
    if not isinstance(raw, dict):
        return {}
    out: dict[str, Any] = {}
    for key in _ALLOWED:
        val = raw.get(key)
        if val is None or val == "":
            continue
        out[key] = val
    # process_id is an alias for source_process when the latter is unset.
    if "source_process" not in out and "process_id" in out:
        out["source_process"] = out["process_id"]
    return out


@contextmanager
def cost_attribution(**kwargs: Any) -> Iterator[dict[str, Any]]:
    """Merge caller attribution into the current context (inner wins)."""
    prev = dict(_ATTR.get() or {})
    incoming = {k: v for k, v in kwargs.items() if k in _ALLOWED and v is not None and v != ""}
    merged = {**prev, **incoming}
    token = _ATTR.set(merged)
    try:
        yield dict(merged)
    finally:
        _ATTR.reset(token)
