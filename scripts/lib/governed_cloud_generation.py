"""Cloud-only generation helper for scheduled advisory and research jobs.

The helper intentionally has no local lane. Callers either receive output from a
governed OAuth lane or a hard failure that their existing fail-closed handling
can record. It never falls through to Ollama.

Governed bridge (2026-10-15, n8n llm lanes; AGENTS.md §23.4/§23.18): when the n8n run executor binds a lane's
allowlist ``llm_route`` (TRADEAI_LLM_VIA_BRIDGE=1 + the bound process id or set), the call goes ONLY through the
governed bridge (lib.llm_bridge_route -> cio-governed-bridge, 127.0.0.1:8766) as ``process_id``: ONE request, the
bridge walks the registry row's route (n8n_oauth_first: grok -> chatgpt -> DeepSeek). ``lanes`` is ignored there and
``llm_lane`` is never imported. A refusal or an unreachable bridge raises CLOUD_GENERATION_FAILED_CLOSED with the
BRIDGE_ROUTE_REFUSED reason: no in-process provider, no second lane. The returned lane is ``"bridge"``. Without the
flag (every cron line) the in-process loop below is unchanged.
"""
from __future__ import annotations

from collections.abc import Iterable


DEFAULT_LANES = ("grok", "chatgpt")
#: The lane name returned for a governed-bridge answer (the bridge, not the caller, chose the provider).
BRIDGE_LANE = "bridge"
#: Read from the environment directly (the flag lib.llm_bridge_route.bridge_enabled reads), so a failed import with
#: the flag ON raises instead of falling through to the in-process provider loop.
VIA_BRIDGE_ENV = "TRADEAI_LLM_VIA_BRIDGE"


def via_bridge() -> bool:
    import os

    return os.environ.get(VIA_BRIDGE_ENV, "off").strip().lower() in {"1", "on", "bridge"}


def generate_cloud(
    prompt: str,
    *,
    process_id: str,
    task_summary: str,
    timeout: float = 90,
    lanes: Iterable[str] = DEFAULT_LANES,
    max_tokens: int = 2048,
    response_json: bool = False,
) -> tuple[str, str]:
    """Return ``(text, lane)`` from the first available governed cloud lane (or the governed bridge, see above)."""
    if via_bridge():
        from lib.llm_bridge_route import text_via_bridge

        text = text_via_bridge(process_id, prompt, timeout_s=float(timeout), max_tokens=max_tokens)
        if text is None or not str(text).strip():
            raise RuntimeError(
                f"CLOUD_GENERATION_FAILED_CLOSED: {process_id}: BRIDGE_ROUTE_REFUSED: governed bridge returned no text"
            )
        return str(text).strip(), BRIDGE_LANE
    import llm_lane

    errors: list[str] = []
    attempted = False
    for lane in lanes:
        lane_name = str(lane).strip().lower()
        if lane_name == "local":
            raise RuntimeError("POLICY_LOCAL_GENERATIVE_FORBIDDEN")
        if not llm_lane.available(lane_name):
            continue
        attempted = True
        try:
            text = llm_lane.generate(
                prompt,
                lane=lane_name,
                timeout=timeout,
                process_id=process_id,
                task_summary=task_summary,
                max_tokens=max_tokens,
                response_json=response_json,
            )
            if text and str(text).strip():
                return str(text).strip(), lane_name
            errors.append(f"{lane_name}:empty")
        except Exception as exc:
            errors.append(f"{lane_name}:{type(exc).__name__}:{str(exc)[:120]}")
    reason = "; ".join(errors) if attempted else "no governed cloud lane available"
    raise RuntimeError(f"CLOUD_GENERATION_FAILED_CLOSED: {process_id}: {reason}")
