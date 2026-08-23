"""Cloud-only generation helper for scheduled advisory and research jobs.

The helper intentionally has no local lane. Callers either receive output from a
governed OAuth lane or a hard failure that their existing fail-closed handling
can record. It never falls through to Ollama.
"""
from __future__ import annotations

from collections.abc import Iterable


DEFAULT_LANES = ("grok", "chatgpt")


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
    """Return ``(text, lane)`` from the first available governed cloud lane."""
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
