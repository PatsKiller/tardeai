"""Route a lane prompt through the governed model bridge (127.0.0.1:8766).

The bridge holds the provider credential. This module does not. A caller that
still uses llm_lane.generate in-process does not qualify as an n8n llm-class
lane (AGENTS.md §23.18). Default stays off so a test or a cron line that has
not been switched does not call the bridge.
"""
from __future__ import annotations

import os
from typing import Any, Optional

VIA_ENV = "TRADEAI_LLM_VIA_BRIDGE"


def bridge_enabled() -> bool:
    return os.environ.get(VIA_ENV, "off").strip().lower() in {"1", "on", "bridge"}


def _call_bridge(messages: list[dict[str, str]], *, process_id: str, timeout_s: float) -> dict[str, Any]:
    try:
        from lib.n8n_model_job import bridge_governed_call
    except ImportError:
        from scripts.lib.n8n_model_job import bridge_governed_call
    return bridge_governed_call(
        messages,
        process_id=process_id,
        timeout_s=timeout_s,
        task_type="model_job",
    )


def text_via_bridge(process_id: str, prompt: str, *, timeout_s: float = 60.0) -> Optional[str]:
    """Return the bridge text, or None when the bridge refuses or is unreachable.

    None is not a silent fallback to a provider. The caller decides.
    """
    result = _call_bridge(
        [{"role": "user", "content": prompt}],
        process_id=process_id,
        timeout_s=timeout_s,
    )
    if result.get("error") or result.get("governance_pass") is False:
        return None
    try:
        return str(result["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError):
        return None
