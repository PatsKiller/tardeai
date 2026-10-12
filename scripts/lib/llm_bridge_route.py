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


def bridge_enabled() -> bool:
    return os.environ.get(VIA_ENV, "off").strip().lower() in {"1", "on", "bridge"}


def _call_bridge(messages: list[dict[str, str]], *, process_id: str, timeout_s: float) -> dict[str, Any]:
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
    )


def text_via_bridge(process_id: str, prompt: str, *, timeout_s: float = 60.0) -> Optional[str]:
    """Return the bridge text, or None when the bridge refuses or is unreachable.

    None is not a silent fallback to a provider. The caller decides.
    """
    bound = os.environ.get("TRADEAI_LLM_PROCESS_ID")
    if (bound is not None and bound != process_id) or route_for_process(process_id) is None:
        return None
    result = _call_bridge(
        [{"role": "user", "content": prompt}],
        process_id=process_id,
        timeout_s=timeout_s,
    )
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
