"""Route a lane prompt through the governed model bridge (127.0.0.1:8766).

The bridge holds the provider credential. This module does not. A caller that
still uses llm_lane.generate in-process does not qualify as an n8n llm-class
lane (AGENTS.md §23.18). Default stays off so a test or a cron line that has
not been switched does not call the bridge.
"""
from __future__ import annotations

import os
from typing import Any, Optional

from .governed_process_routes import route_for_process

VIA_ENV = "TRADEAI_LLM_VIA_BRIDGE"
#: The one process an allowlist ``llm_route: {process_id}`` binds (scripts/n8n_run_executor.py LLM_PROCESS_ENV).
PROCESS_ENV = "TRADEAI_LLM_PROCESS_ID"
#: The declared process SET an allowlist ``llm_route: {process_ids: [...]}`` binds (2026-10-15): a compound lane whose
#: steps call more than one registered process (e.g. run-research-intelligence-overnight: topic_ingestion,
#: ri_narrative_enrich, topic_research_synthesizer). Comma-separated; a call for any other process is refused.
PROCESS_SET_ENV = "TRADEAI_LLM_PROCESS_IDS"
#: The prefix every refusal raised by ``require_text_via_bridge`` carries (llm_lane.generate raises the same text).
REFUSED = "BRIDGE_ROUTE_REFUSED"


class BridgeRouteRefused(RuntimeError):
    """The governed bridge refused or was unreachable. Never a cue to call a provider in-process."""


def bridge_enabled() -> bool:
    return os.environ.get(VIA_ENV, "off").strip().lower() in {"1", "on", "bridge"}


def bound_processes() -> Optional[frozenset[str]]:
    """The process ids the executor bound for this run, or None when it bound none (a manual run)."""
    single = os.environ.get(PROCESS_ENV)
    if single is not None:
        return frozenset({single})
    raw = os.environ.get(PROCESS_SET_ENV)
    if raw is None:
        return None
    return frozenset(p.strip() for p in raw.split(",") if p.strip())


def process_admitted(process_id: str) -> bool:
    """True when ``process_id`` has a governed route and is inside what the executor bound (when it bound any)."""
    bound = bound_processes()
    if bound is not None and process_id not in bound:
        return False
    return route_for_process(process_id) is not None


def _call_bridge(messages: list[dict[str, str]], *, process_id: str, timeout_s: float,
                 max_tokens: int = 2048) -> dict[str, Any]:
    route = route_for_process(process_id)
    if route is None:
        return {"error": {"code": "PROCESS_ROUTE_NOT_REGISTERED"}, "governance_pass": False}
    from .n8n_model_job import bridge_governed_call
    return bridge_governed_call(
        messages,
        process_id=process_id,
        timeout_s=timeout_s,
        task_type=route[1],
        caller=route[0],
        max_tokens=max_tokens,
    )


def text_via_bridge(process_id: str, prompt: str, *, timeout_s: float = 60.0,
                    max_tokens: Optional[int] = None) -> Optional[str]:
    """Return the bridge text, or None when the bridge refuses or is unreachable.

    None is not a silent fallback to a provider. The caller decides. ``max_tokens`` (default: the transport's
    2048) is a request; the bridge still clamps it to the registry row's max_output_tokens.
    """
    if not process_admitted(process_id):
        return None
    kw: dict[str, Any] = {"process_id": process_id, "timeout_s": timeout_s}
    if max_tokens is not None:
        kw["max_tokens"] = int(max_tokens)
    result = _call_bridge([{"role": "user", "content": prompt}], **kw)
    if not isinstance(result, dict) or result.get("error"):
        return None
    governance = result.get("_tradeai")
    if not isinstance(governance, dict):
        return None
    if governance.get("governance_pass") is not True or governance.get("process_id") != process_id:
        return None
    if not governance.get("reservation_id") and governance.get("mock") is not True:
        return None
    try:
        content = result["choices"][0]["message"]["content"]
        return content if isinstance(content, str) else None
    except (KeyError, IndexError, TypeError):
        return None


def require_text_via_bridge(process_id: str, prompt: str, *, timeout_s: float = 60.0,
                            max_tokens: Optional[int] = None) -> str:
    """``text_via_bridge`` for a caller that treats "no answer" as a failure: the text, or BridgeRouteRefused.

    The refusal is raised, never swallowed into a fallback: a lane on the bridge path that catches it records the
    row as failed (no output), it does not try a provider client, another lane or a local model."""
    text = text_via_bridge(process_id, prompt, timeout_s=timeout_s, max_tokens=max_tokens)
    if text is None or not str(text).strip():
        raise BridgeRouteRefused(f"{REFUSED}: governed bridge returned no text for process {process_id}")
    return str(text)
