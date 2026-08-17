"""llm_lane.py — unified LLM lanes: Grok OAuth (xAI proxy :8645), ChatGPT OAuth (codex proxy :8646),
DeepSeek V4 (paid API: exact models deepseek-v4-flash / deepseek-v4-pro), or local gemma.

DeepSeek:
  - Exact provider model IDs only (verified via /v1/models).
  - Logical policies: FAST, FAST_THINK, PRO, PRO_THINK, PRO_MAX (see config/llm_model_registry.json).
  - Legacy IDs deepseek-chat / deepseek-reasoner are REJECTED (provider silently remaps them to Flash).
  - No silent fallback to Gemma when DeepSeek is requested.

Grok/ChatGPT remain free OAuth via local proxies. Pass process_id for consumption gating.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

_GROK_URL = os.environ.get("HERMES_XAI_PROXY_URL", "http://127.0.0.1:8645/v1/chat/completions")
_CHATGPT_URL = os.environ.get("CHATGPT_PROXY_URL", "http://127.0.0.1:8646").rstrip("/")

# Legacy lane names still accepted as *logical* aliases → registry policies.
# They must NOT map to deepseek-chat / deepseek-reasoner model IDs.
_DEEPSEEK_LANES = frozenset({
    "deepseek-flash",
    "deepseek-v4-flash",
    "deepseek-v4-pro",
    "fast",
    "fast_think",
    "pro",
    "pro_think",
    "pro_max",
})
# Ambiguous legacy — accepted only to raise a typed error (never route)
_AMBIGUOUS_DEEPSEEK = frozenset({"deepseek-v4", "deepseek_v4"})


def _deepseek_model_available(model_id: str) -> bool:
    """Independent probe for one exact V4 model id.

    Does a direct API connectivity check (GET /v1/models with a 4s timeout)
    rather than relying solely on the consumption_run_manual TTL cache — which
    can stay stale for 60 seconds after a transient network blip. Falls back
    to the readiness-rows cache only when the direct probe also fails.
    """
    # Fast path: direct connectivity probe (bypasses TTL cache)
    try:
        from lib.llm_model_registry import get_deepseek_api_key
        key, _env, _leg = get_deepseek_api_key()
        if not key:
            return False
        import requests as _requests
        r = _requests.get(
            "https://api.deepseek.com/v1/models",
            headers={"Authorization": f"Bearer {key}", "User-Agent": "tradeai-lane-check/1.0"},
            timeout=4,
        )
        if r.status_code == 200:
            data = r.json()
            ids = {i.get("id") for i in (data.get("data") or []) if i.get("id")}
            # model_id is e.g. "deepseek-v4-flash"; the probe returns that exact id
            return model_id in ids
    except Exception:
        pass

    # Slow path: fall back to the cached readiness rows (may be stale)
    try:
        from lib.consumption_run_manual import deepseek_readiness_rows
        if model_id == "deepseek-v4-flash":
            row = next((r for r in deepseek_readiness_rows() if r["lane"] == "deepseek-flash"), None)
        else:
            row = next((r for r in deepseek_readiness_rows() if r["lane"] == "deepseek-v4-pro"), None)
        return bool(row and row.get("ready"))
    except Exception:
        return False


def available(lane):
    """Return True only when the lane can actually serve requests.

    Unknown lanes return False (never available=True for unknown).
    Flash and Pro readiness are independent.
    """
    lane = (lane or "").lower().strip()
    if not lane:
        return False
    if lane == "local":
        try:
            import requests
            return bool(requests.get("http://127.0.0.1:11434/api/tags", timeout=4).ok)
        except Exception:
            return False
    if lane in ("grok", "chatgpt"):
        try:
            from lib.oauth_lane_status import lane_available
            return lane_available(lane)
        except Exception:
            try:
                import requests
                if lane == "grok":
                    h = requests.get(_GROK_URL.replace("/v1/chat/completions", "/health"), timeout=5).json()
                    return bool(h.get("authenticated")) and not h.get("token_expired")
                h = requests.get(_CHATGPT_URL + "/health", timeout=5).json()
                return bool(h.get("authenticated")) and not h.get("token_expired")
            except Exception:
                return False
    if lane in _AMBIGUOUS_DEEPSEEK:
        return False  # never available=True for ambiguous alias
    if lane in ("deepseek-flash", "deepseek-v4-flash", "fast", "fast_think"):
        return _deepseek_model_available("deepseek-v4-flash")
    if lane in ("deepseek-v4-pro", "pro", "pro_think", "pro_max"):
        return _deepseek_model_available("deepseek-v4-pro")
    if lane in _DEEPSEEK_LANES:
        return False
    # Unknown lane — never report available
    return False


def _resolve_deepseek_policy(lane: str, model: str | None) -> str:
    from lib.llm_model_registry import RegistryError, resolve_lane_alias, reject_legacy_model_id

    if model:
        reject_legacy_model_id(model)
        if model == "deepseek-v4-flash":
            return "FAST"
        if model == "deepseek-v4-pro":
            return "PRO"  # exact model without think request → PRO non-thinking
        raise RegistryError(f"unsupported explicit model override: {model!r}")
    pol = resolve_lane_alias(lane)  # may raise AmbiguousLegacyLane
    if not pol:
        raise RegistryError(f"not a DeepSeek lane: {lane!r}")
    return pol


def _deepseek_generate(
    prompt,
    *,
    lane: str,
    model: str | None,
    timeout: float,
    operator_confirmed: bool = False,
    response_json: bool = False,
    max_tokens: int = 2048,
    process_id: str | None = None,
):
    """Call exact DeepSeek V4 models via canonical client. Raises on failure — no Gemma fallback."""
    from lib.deepseek_client import DeepSeekError, chat
    from lib.llm_model_registry import RegistryError

    try:
        from lib.provider_cost.context import cost_attribution
    except Exception:  # pragma: no cover — fail-soft if FinOps module absent
        from contextlib import contextmanager as _cm

        @_cm
        def cost_attribution(**_kw):
            yield {}

    try:
        policy = _resolve_deepseek_policy(lane, model)
        # max_tokens must be the process-capped effective limit from the caller
        mt = max(1, int(max_tokens or 2048))
        with cost_attribution(
            source_service="llm_lane",
            source_lane=str(lane),
            source_process=process_id,
        ):
            resp = chat(
                policy=policy,
                prompt=prompt,
                timeout=timeout,
                operator_confirmed=operator_confirmed,
                response_json=response_json,
                max_tokens=mt,
                source_service="llm_lane",
                source_lane=str(lane),
                source_process=process_id,
            )
    except (RegistryError, DeepSeekError) as e:
        code = getattr(e, "code", "POLICY_BLOCKED")
        raise RuntimeError(f"{code}: {e}") from e

    if not resp.ok or (not resp.content and not resp.truncated):
        err = RuntimeError(
            f"{resp.error_class or 'DEEPSEEK_FAILED'}: "
            f"policy={resp.requested_policy} model={resp.requested_model_id} "
            f"returned={resp.returned_model} {resp.error_message or ''}".strip()
        )
        # Propagate billable-attempt flags for reservation settle
        err.request_sent = bool(getattr(resp, "request_sent", False))  # type: ignore[attr-defined]
        err.possibly_billable = bool(getattr(resp, "possibly_billable", False))  # type: ignore[attr-defined]
        err.estimated_cost_usd = getattr(resp, "estimated_cost_usd", None)  # type: ignore[attr-defined]
        raise err
    # provenance dict for callers that inspect usage via consumption logger
    usage = dict(resp.usage or {})
    usage["_tradeai"] = {
        "requested_policy": resp.requested_policy,
        "executed_policy": resp.executed_policy,
        "requested_model_id": resp.requested_model_id,
        "returned_model": resp.returned_model,
        "thinking": resp.thinking,
        "reasoning_effort": resp.reasoning_effort,
        "request_id": resp.request_id,
        "client_request_id": resp.client_request_id,
        "latency_ms": resp.latency_ms,
        "estimated_cost_usd": resp.estimated_cost_usd,
        "cost_basis": resp.cost_basis,
        "finish_reason": resp.finish_reason,
        "raw_response_hash": resp.raw_response_hash,
        "fallback_used": resp.fallback_used,
        "request_sent": bool(getattr(resp, "request_sent", False)),
        "possibly_billable": bool(getattr(resp, "possibly_billable", False)),
    }
    return resp.content, usage, resp


def generate(
    prompt,
    lane="grok",
    timeout=90,
    model=None,
    *,
    process_id=None,
    task_summary=None,
    manual_trigger=False,
    metadata=None,
    _skip_consumption=False,
    operator_confirmed=False,
    response_json=False,
    return_provenance=False,
    max_tokens: int = 2048,
):
    """Generate text. When process_id is set, routes through consumption gate (Automated/Manual).

    DeepSeek failures raise RuntimeError — they never fall through to local Gemma.
    If return_provenance=True, returns (text, provenance_dict) for DeepSeek paths.
    max_tokens is honored for DeepSeek provider calls (process-capped by gate_and_generate).
    """
    lane_l = (lane or "grok").lower().strip()

    if lane_l in _AMBIGUOUS_DEEPSEEK:
        raise RuntimeError(
            "AMBIGUOUS_LEGACY_LANE: 'deepseek-v4' is not exact. "
            "Use FAST/FAST_THINK/PRO/PRO_THINK/PRO_MAX or deepseek-v4-flash / deepseek-v4-pro."
        )

    deepseek_requested = lane_l in _DEEPSEEK_LANES

    if process_id and not _skip_consumption and (
        lane_l in ("grok", "chatgpt") or deepseek_requested
    ):
        from lib.llm_consumption import gate_and_generate
        return gate_and_generate(
            prompt, lane=lane_l, process_id=process_id, task_summary=task_summary,
            manual_trigger=manual_trigger, timeout=timeout, model=model, metadata=metadata,
            operator_confirmed=operator_confirmed,
            response_json=response_json,
            max_tokens=max_tokens,
        )

    # ── DeepSeek lanes (paid API key, exact V4 models) ──
    if deepseek_requested:
        text, usage, resp = _deepseek_generate(
            prompt,
            lane=lane_l,
            model=model,
            timeout=timeout,
            operator_confirmed=operator_confirmed or bool((metadata or {}).get("operator_cost_confirmed")),
            response_json=response_json,
            max_tokens=max_tokens,
            process_id=process_id,
        )
        provenance = {
            "usage": {k: v for k, v in usage.items() if k != "_tradeai"},
            "_tradeai": usage.get("_tradeai") or {},
        }
        if process_id and not _skip_consumption:
            try:
                from lib.llm_consumption import log_call
                ta = provenance["_tradeai"]
                log_call(
                    lane=lane_l,
                    process_id=process_id,
                    task_summary=task_summary or prompt[:160],
                    trigger_mode="manual" if manual_trigger else "automated",
                    success=True,
                    model_name=resp.returned_model or resp.requested_model_id,
                    prompt=prompt,
                    response=text,
                    tokens_in=usage.get("prompt_tokens"),
                    tokens_out=usage.get("completion_tokens"),
                    estimated_cost_usd=ta.get("estimated_cost_usd"),
                    cost_basis=ta.get("cost_basis"),
                    requested_policy=ta.get("requested_policy"),
                    executed_policy=ta.get("executed_policy"),
                    requested_model_id=ta.get("requested_model_id"),
                    returned_model=ta.get("returned_model"),
                    thinking=ta.get("thinking"),
                    reasoning_effort=ta.get("reasoning_effort"),
                    provider_request_id=ta.get("request_id"),
                    metadata={**(metadata or {}), **ta},
                )
            except Exception:
                pass
        if return_provenance:
            return text, provenance
        return text

    if lane_l == "grok":
        import requests
        r = requests.post(_GROK_URL, json={"model": model or "grok-3-mini",
                                           "messages": [{"role": "user", "content": prompt}], "temperature": 0.3},
                          timeout=timeout)
        r.raise_for_status()
        body = r.json()
        if process_id and not _skip_consumption:
            try:
                from lib.llm_consumption import log_call
                text = body["choices"][0]["message"]["content"]
                usage = body.get("usage") or {}
                log_call(lane="grok", process_id=process_id, task_summary=task_summary or prompt[:160],
                         trigger_mode="automated", success=True, model_name=model or "grok-3-mini",
                         prompt=prompt, response=text,
                         tokens_in=usage.get("prompt_tokens"), tokens_out=usage.get("completion_tokens"))
            except Exception:
                pass
        return body["choices"][0]["message"]["content"]
    if lane_l == "chatgpt":
        import requests
        r = requests.post(_CHATGPT_URL + "/v1/chat/completions",
                          json={"model": model or "gpt-5.4", "messages": [{"role": "user", "content": prompt}]},
                          timeout=timeout)
        if r.status_code == 401:
            raise RuntimeError("AUTH_EXPIRED: " + (r.json().get("error", {}) or {}).get("message", "ChatGPT session ended"))
        r.raise_for_status()
        body = r.json()
        if process_id and not _skip_consumption:
            try:
                from lib.llm_consumption import log_call
                text = body["choices"][0]["message"]["content"]
                usage = body.get("usage") or {}
                log_call(lane="chatgpt", process_id=process_id, task_summary=task_summary or prompt[:160],
                         trigger_mode="automated", success=True, model_name=model or "gpt-5.4",
                         prompt=prompt, response=text,
                         tokens_in=usage.get("prompt_tokens"), tokens_out=usage.get("completion_tokens"))
            except Exception:
                pass
        return body["choices"][0]["message"]["content"]

    if lane_l == "local":
        import local_llm
        return local_llm.generate(prompt, timeout=timeout)

    # Unknown lane — fail closed (do NOT fall through to Gemma while claiming another provider)
    raise RuntimeError(
        f"UNKNOWN_LANE: lane={lane!r} is not registered; "
        "refusing silent local-Gemma fallback"
    )
