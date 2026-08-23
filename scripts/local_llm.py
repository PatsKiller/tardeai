"""Compatibility facade for callers that historically imported ``local_llm``.

Local generative inference is retired. ``generate`` uses the governed DeepSeek
Flash lane only; functions that explicitly request local generation fail closed.
The module name remains temporarily so existing advisory jobs can migrate without
restoring hidden Ollama chat capability.
"""
from __future__ import annotations

import os
from contextlib import contextmanager

FALLBACK_DEEPSEEK = os.getenv("LLM_FALLBACK_DEEPSEEK", "deepseek-v4-flash").strip()
FALLBACK_DEEPSEEK_PRO = os.getenv("LLM_FALLBACK_DEEPSEEK_PRO", "deepseek-v4-pro").strip()
FALLBACK_OPENAI = os.getenv("LLM_FALLBACK_OPENAI", "gpt-4o-mini").strip()
FALLBACK_ANTHROPIC = os.getenv("LLM_FALLBACK_ANTHROPIC", "claude-sonnet-4-6").strip()

OLLAMA_MODEL = "LOCAL_GENERATIVE_RETIRED"
OLLAMA_MODEL_FAST = OLLAMA_MODEL
OLLAMA_URL = "LOCAL_GENERATIVE_ENDPOINT_RETIRED"
DISABLED_MODELS = {"*"}
SAFE_MODEL = OLLAMA_MODEL
model_used: str | None = None


class LocalGenerativeForbidden(RuntimeError):
    pass


class _RetiredGate:
    def acquire(self, *args, **kwargs) -> bool:
        return False

    def release(self) -> None:
        return None


_gate = _RetiredGate()


def _resolve_model(requested: str) -> tuple[str, bool]:
    return OLLAMA_MODEL, True


def _get_loaded_models() -> list[str]:
    return []


def _try_ollama(*args, **kwargs):
    raise LocalGenerativeForbidden("POLICY_LOCAL_GENERATIVE_FORBIDDEN")


def warmup_ollama(*args, **kwargs) -> bool:
    """Compatibility function. A generative warmup is never attempted."""
    return False


def _try_deepseek(prompt: str, timeout: int = 120) -> str | None:
    try:
        from llm_lane import available, generate as lane_generate
        if not available("deepseek-flash"):
            return None
        try:
            from lib.provider_cost.context import cost_attribution
        except Exception:
            @contextmanager
            def cost_attribution(**_kwargs):
                yield {}
        with cost_attribution(
            source_service="local_llm_compat.cloud",
            source_process="local_llm_compat",
            source_lane="deepseek-flash",
        ):
            result = lane_generate(
                prompt,
                lane="deepseek-flash",
                timeout=timeout,
                process_id="local_llm_compat",
            )
        return result.strip() if result and result.strip() else None
    except Exception:
        return None


def _try_openai(prompt: str) -> str | None:
    """Legacy name; use the governed router instead of direct provider access."""
    return _try_deepseek(prompt)


def _try_anthropic(prompt: str) -> str | None:
    """Legacy name; use the governed router instead of direct provider access."""
    return _try_deepseek(prompt)


def generate(
    prompt: str,
    timeout: int = 300,
    fallback: bool = True,
    fast: bool = True,
    caller: str = "",
    process_type: str = "STANDARD",
) -> str:
    """Generate through the governed cloud lane only.

    ``fast`` is retained for signature compatibility. ``fallback=False`` meant
    local-only to historical callers and therefore now fails closed.
    """
    del fast, caller, process_type
    global model_used
    model_used = None
    if not fallback:
        return ""
    result = _try_deepseek(prompt, timeout=min(timeout, 120))
    if result:
        model_used = FALLBACK_DEEPSEEK
        return result
    return ""


def generate_local_only(
    prompt: str,
    *,
    system: str = "",
    timeout_s: int | None = None,
) -> dict:
    del prompt, system, timeout_s
    return {
        "ok": False,
        "error": "POLICY_LOCAL_GENERATIVE_FORBIDDEN",
        "provider_family": "LOCAL_GENERATIVE_RETIRED",
    }
