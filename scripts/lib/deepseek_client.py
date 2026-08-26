"""Canonical DeepSeek V4 provider client.

Uses only exact model IDs verified by live GET /v1/models:
  deepseek-v4-flash, deepseek-v4-pro

Never silently falls back to Gemma/Grok/ChatGPT/cached prose.
Never prints API keys.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

import requests

from lib.llm_model_registry import (
    EXACT_DEEPSEEK_MODELS,
    estimate_usd_cost,
    get_deepseek_api_key,
    reject_legacy_model_id,
    resolve_logical_policy,
)

# Typed error classes (string codes for JSON envelopes)
AUTH_MISSING = "AUTH_MISSING"
AUTH_INVALID = "AUTH_INVALID"
MODEL_NOT_FOUND = "MODEL_NOT_FOUND"
RATE_LIMITED = "RATE_LIMITED"
TIMEOUT = "TIMEOUT"
PROVIDER_5XX = "PROVIDER_5XX"
NETWORK_ERROR = "NETWORK_ERROR"
EMPTY_CONTENT = "EMPTY_CONTENT"
JSON_INVALID = "JSON_INVALID"
OUTPUT_TRUNCATED = "OUTPUT_TRUNCATED"
POLICY_BLOCKED = "POLICY_BLOCKED"
COST_CAP_EXCEEDED = "COST_CAP_EXCEEDED"
LEGACY_MODEL_REJECTED = "LEGACY_MODEL_REJECTED"
MISMATCHED_RETURNED_MODEL = "MISMATCHED_RETURNED_MODEL"


class DeepSeekError(Exception):
    def __init__(self, code: str, message: str, *, http_status: int | None = None, details: dict | None = None):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.http_status = http_status
        self.details = details or {}

    def as_dict(self) -> dict[str, Any]:
        return {
            "error_class": self.code,
            "error_message": self.message,
            "http_status": self.http_status,
            "details": self.details,
        }


@dataclass
class DeepSeekResponse:
    ok: bool
    requested_policy: str | None
    executed_policy: str | None
    requested_model_id: str | None
    returned_model: str | None
    thinking: str | None
    reasoning_effort: str | None
    content: str | None
    reasoning_content: str | None
    tool_calls: list | None
    finish_reason: str | None
    usage: dict = field(default_factory=dict)
    estimated_cost_usd: float | None = None
    cost_basis: str | None = None
    request_id: str | None = None
    latency_ms: int | None = None
    http_status: int | None = None
    retry_count: int = 0
    error_class: str | None = None
    error_message: str | None = None
    truncated: bool = False  # finish_reason=length — partial but billable content
    fallback_used: bool = False
    fallback_reason: str | None = None
    raw_response_hash: str | None = None
    client_request_id: str | None = None
    # Billing semantics: set only after the HTTP POST is handed to the network stack
    request_sent: bool = False
    possibly_billable: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _classify_http(status: int) -> str:
    if status in (401, 403):
        return AUTH_INVALID
    if status == 404:
        return MODEL_NOT_FOUND
    if status == 429:
        return RATE_LIMITED
    if status >= 500:
        return PROVIDER_5XX
    return f"HTTP_{status}"


def list_models(*, timeout: float = 15.0) -> dict[str, Any]:
    key, env_name, legacy = get_deepseek_api_key()
    if not key:
        raise DeepSeekError(
            AUTH_MISSING,
            "DeepSeek API key not configured (canonical env deepseek_tradeai; "
            "optional compatibility alias DEEPSEEK_API_KEY)",
        )
    # used_compatibility_alias: True when DEEPSEEK_API_KEY was used because canonical absent
    dep = bool(legacy)
    base = "https://api.deepseek.com"
    t0 = time.time()
    try:
        r = requests.get(
            f"{base}/v1/models",
            headers={"Authorization": f"Bearer {key}", "User-Agent": "tradeai-deepseek-client/1.0"},
            timeout=timeout,
        )
    except requests.Timeout as e:
        raise DeepSeekError(TIMEOUT, "models list timeout") from e
    except requests.RequestException as e:
        raise DeepSeekError(NETWORK_ERROR, type(e).__name__) from e
    if r.status_code != 200:
        raise DeepSeekError(_classify_http(r.status_code), f"models list HTTP {r.status_code}", http_status=r.status_code)
    data = r.json()
    ids = sorted({(i.get("id") or "") for i in (data.get("data") or []) if i.get("id")})
    return {
        "ok": True,
        "model_ids": ids,
        "http_status": r.status_code,
        "latency_ms": int((time.time() - t0) * 1000),
        "request_id": r.headers.get("x-request-id"),
        # Name of env var used for auth (never the secret value). Prefer not to
        # surface this to browsers — service health should stay generic.
        "auth_env_name": env_name,
        "used_compatibility_auth_env": dep,
        "has_v4_flash": "deepseek-v4-flash" in ids,
        "has_v4_pro": "deepseek-v4-pro" in ids,
        "configured": True,
        "provider": "deepseek",
    }


def _emit_chat_event(
    *,
    outcome: str,
    model_id: str | None,
    request_id: str | None,
    client_rid: str | None,
    raw_key: str | None,
    usage: dict | None = None,
    request_sent: bool = False,
    possibly_billable: bool = False,
    error_class: str | None = None,
    source_service: str | None = None,
    source_process: str | None = None,
    source_lane: str | None = None,
    agent: str | None = None,
    run_id: str | None = None,
    reservation_id: str | None = None,
    environment: str | None = None,
) -> None:
    """Fail-soft FinOps emit. Never invents tokens/USD. Never raises."""
    try:
        try:
            from scripts.lib.provider_cost.emit import (
                OUTCOME_ATTEMPT,
                OUTCOME_PRE_SEND,
                OUTCOME_SUCCESS,
                emit_cost_event,
            )
        except ImportError:
            from lib.provider_cost.emit import (  # type: ignore
                OUTCOME_ATTEMPT,
                OUTCOME_PRE_SEND,
                OUTCOME_SUCCESS,
                emit_cost_event,
            )
        usage = usage or {}
        pt = usage.get("prompt_tokens")
        ct = usage.get("completion_tokens")
        hit = usage.get("prompt_cache_hit_tokens") or usage.get("cache_hit_tokens")
        miss = usage.get("prompt_cache_miss_tokens") or usage.get("cache_miss_tokens")
        if outcome == OUTCOME_SUCCESS:
            pt = int(pt or 0)
            ct = int(ct or 0)
            hit = int(hit or 0)
        emit_cost_event(
            provider="deepseek",
            model=str(model_id or ""),
            outcome=outcome,
            request_id=request_id,
            client_request_id=client_rid,
            prompt_tokens=pt,
            completion_tokens=ct,
            cache_hit_tokens=hit,
            cache_miss_tokens=miss,
            raw_key=raw_key,
            request_sent=request_sent,
            possibly_billable=possibly_billable,
            error_class=error_class,
            source_service=source_service,
            source_process=source_process,
            source_lane=source_lane,
            agent=agent,
            run_id=run_id,
            reservation_id=reservation_id,
            environment=environment,
            evidence_refs=["deepseek_client.chat"],
        )
        _ = (OUTCOME_ATTEMPT, OUTCOME_PRE_SEND, OUTCOME_SUCCESS)
    except Exception:
        return


def chat(
    *,
    policy: str | None = None,
    model_id: str | None = None,
    prompt: str,
    thinking: str | None = None,
    reasoning_effort: str | None = None,
    response_json: bool = False,
    max_tokens: int = 1024,
    timeout: float = 90.0,
    operator_confirmed: bool = False,
    messages: list[dict] | None = None,
    temperature: float | None = 0.3,
    source_service: str | None = None,
    source_process: str | None = None,
    source_lane: str | None = None,
    agent: str | None = None,
    run_id: str | None = None,
    reservation_id: str | None = None,
    environment: str | None = None,
) -> DeepSeekResponse:
    """Execute one chat completion with exact model + full provenance."""
    client_rid = str(uuid.uuid4())
    binding = None
    requested_policy = None
    executed_policy = None

    if policy:
        binding = resolve_logical_policy(policy, operator_confirmed=operator_confirmed)
        requested_policy = binding["requested_policy"]
        executed_policy = binding["requested_policy"]
        model_id = binding["model_id"]
        thinking = binding["thinking"]
        reasoning_effort = binding.get("reasoning_effort")
        base = binding["base_url"]
    else:
        if not model_id:
            raise DeepSeekError(POLICY_BLOCKED, "policy or model_id required")
        reject_legacy_model_id(model_id)
        if model_id not in EXACT_DEEPSEEK_MODELS:
            raise DeepSeekError(MODEL_NOT_FOUND, f"model not allowed: {model_id}")
        base = "https://api.deepseek.com"
        thinking = thinking or "disabled"

    reject_legacy_model_id(model_id)  # type: ignore[arg-type]

    key, env_name, legacy = get_deepseek_api_key()
    if not key:
        _emit_chat_event(
            outcome="pre_send_failure",
            model_id=model_id,
            request_id=None,
            client_rid=client_rid,
            raw_key=None,
            request_sent=False,
            possibly_billable=False,
            error_class=AUTH_MISSING,
            source_service=source_service,
            source_process=source_process,
            source_lane=source_lane,
            agent=agent,
            run_id=run_id,
            reservation_id=reservation_id,
            environment=environment,
        )
        return DeepSeekResponse(
            ok=False,
            requested_policy=requested_policy,
            executed_policy=None,
            requested_model_id=model_id,
            returned_model=None,
            thinking=thinking,
            reasoning_effort=reasoning_effort,
            content=None,
            reasoning_content=None,
            tool_calls=None,
            finish_reason=None,
            error_class=AUTH_MISSING,
            error_message="DeepSeek API key not configured (canonical env: deepseek_tradeai)",
            client_request_id=client_rid,
        )

    if messages:
        msgs = messages
    else:
        msgs = [{"role": "user", "content": prompt}]
    body: dict[str, Any] = {
        "model": model_id,
        "messages": msgs,
        "max_tokens": max_tokens,
    }
    thinking_on = (thinking or "").lower() in ("enabled", "on", "true", "1")
    if thinking_on:
        body["thinking"] = {"type": "enabled"}
        if reasoning_effort:
            body["reasoning_effort"] = reasoning_effort
        # omit temperature/top_p in thinking mode per contract
    else:
        body["thinking"] = {"type": "disabled"}
        if temperature is not None:
            body["temperature"] = temperature
    if response_json:
        body["response_format"] = {"type": "json_object"}

    t0 = time.time()
    request_sent = False
    try:
        r = requests.post(
            f"{base.rstrip('/')}/v1/chat/completions",
            json=body,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "User-Agent": "tradeai-deepseek-client/1.0",
                "X-TradeAI-Request-Id": client_rid,
            },
            timeout=timeout,
        )
        # POST returned (any HTTP status) — network handoff completed
        request_sent = True
    except requests.Timeout:
        # Timeout after send attempt — treat as possibly billable
        _emit_chat_event(
            outcome="possibly_billable_attempt",
            model_id=model_id,
            request_id=None,
            client_rid=client_rid,
            raw_key=key,
            request_sent=True,
            possibly_billable=True,
            error_class=TIMEOUT,
            source_service=source_service,
            source_process=source_process,
            source_lane=source_lane,
            agent=agent,
            run_id=run_id,
            reservation_id=reservation_id,
            environment=environment,
        )
        return DeepSeekResponse(
            ok=False,
            requested_policy=requested_policy,
            executed_policy=executed_policy,
            requested_model_id=model_id,
            returned_model=None,
            thinking=thinking,
            reasoning_effort=reasoning_effort,
            content=None,
            reasoning_content=None,
            tool_calls=None,
            finish_reason=None,
            latency_ms=int((time.time() - t0) * 1000),
            error_class=TIMEOUT,
            error_message="request timeout",
            client_request_id=client_rid,
            request_sent=True,
            possibly_billable=True,
        )
    except requests.RequestException as e:
        # May or may not have left the host; treat as possibly billable conservatively
        _emit_chat_event(
            outcome="possibly_billable_attempt",
            model_id=model_id,
            request_id=None,
            client_rid=client_rid,
            raw_key=key,
            request_sent=True,
            possibly_billable=True,
            error_class=NETWORK_ERROR,
            source_service=source_service,
            source_process=source_process,
            source_lane=source_lane,
            agent=agent,
            run_id=run_id,
            reservation_id=reservation_id,
            environment=environment,
        )
        return DeepSeekResponse(
            ok=False,
            requested_policy=requested_policy,
            executed_policy=executed_policy,
            requested_model_id=model_id,
            returned_model=None,
            thinking=thinking,
            reasoning_effort=reasoning_effort,
            content=None,
            reasoning_content=None,
            tool_calls=None,
            finish_reason=None,
            latency_ms=int((time.time() - t0) * 1000),
            error_class=NETWORK_ERROR,
            error_message=type(e).__name__,
            client_request_id=client_rid,
            request_sent=True,
            possibly_billable=True,
        )

    latency = int((time.time() - t0) * 1000)
    req_id = r.headers.get("x-request-id")
    if r.status_code != 200:
        _emit_chat_event(
            outcome="possibly_billable_attempt",
            model_id=model_id,
            request_id=req_id,
            client_rid=client_rid,
            raw_key=key,
            request_sent=True,
            possibly_billable=True,
            error_class=_classify_http(r.status_code),
            source_service=source_service,
            source_process=source_process,
            source_lane=source_lane,
            agent=agent,
            run_id=run_id,
            reservation_id=reservation_id,
            environment=environment,
        )
        return DeepSeekResponse(
            ok=False,
            requested_policy=requested_policy,
            executed_policy=executed_policy,
            requested_model_id=model_id,
            returned_model=None,
            thinking=thinking,
            reasoning_effort=reasoning_effort,
            content=None,
            reasoning_content=None,
            tool_calls=None,
            finish_reason=None,
            latency_ms=latency,
            http_status=r.status_code,
            request_id=req_id,
            error_class=_classify_http(r.status_code),
            error_message=f"HTTP {r.status_code}",
            client_request_id=client_rid,
            request_sent=True,
            possibly_billable=True,
        )

    try:
        payload = r.json()
    except Exception:
        _emit_chat_event(
            outcome="possibly_billable_attempt",
            model_id=model_id,
            request_id=req_id,
            client_rid=client_rid,
            raw_key=key,
            request_sent=True,
            possibly_billable=True,
            error_class=JSON_INVALID,
            source_service=source_service,
            source_process=source_process,
            source_lane=source_lane,
            agent=agent,
            run_id=run_id,
            reservation_id=reservation_id,
            environment=environment,
        )
        return DeepSeekResponse(
            ok=False,
            requested_policy=requested_policy,
            executed_policy=executed_policy,
            requested_model_id=model_id,
            returned_model=None,
            thinking=thinking,
            reasoning_effort=reasoning_effort,
            content=None,
            reasoning_content=None,
            tool_calls=None,
            finish_reason=None,
            latency_ms=latency,
            http_status=r.status_code,
            request_id=req_id,
            error_class=JSON_INVALID,
            error_message="response body not JSON",
            client_request_id=client_rid,
            request_sent=True,
            possibly_billable=True,
        )

    choice = (payload.get("choices") or [{}])[0]
    msg = choice.get("message") or {}
    content = msg.get("content")
    reasoning_content = msg.get("reasoning_content")
    finish = choice.get("finish_reason")
    returned = payload.get("model")
    usage = payload.get("usage") or {}

    import hashlib
    raw_hash = hashlib.sha256(r.content).hexdigest()[:24]

    if returned and returned != model_id:
        # Provider silent remap (e.g. legacy ids) — treat as hard failure for exact-ID contract
        _emit_chat_event(
            outcome="possibly_billable_attempt",
            model_id=model_id,
            request_id=req_id,
            client_rid=client_rid,
            raw_key=key,
            usage=usage,
            request_sent=True,
            possibly_billable=True,
            error_class=MISMATCHED_RETURNED_MODEL,
            source_service=source_service,
            source_process=source_process,
            source_lane=source_lane,
            agent=agent,
            run_id=run_id,
            reservation_id=reservation_id,
            environment=environment,
        )
        return DeepSeekResponse(
            ok=False,
            requested_policy=requested_policy,
            executed_policy=executed_policy,
            requested_model_id=model_id,
            returned_model=returned,
            thinking=thinking,
            reasoning_effort=reasoning_effort,
            content=content if isinstance(content, str) else None,
            reasoning_content=reasoning_content if isinstance(reasoning_content, str) else None,
            tool_calls=msg.get("tool_calls"),
            finish_reason=finish,
            usage=usage,
            latency_ms=latency,
            http_status=r.status_code,
            request_id=req_id,
            error_class=MISMATCHED_RETURNED_MODEL,
            error_message=f"requested {model_id} returned {returned}",
            raw_response_hash=raw_hash,
            client_request_id=client_rid,
            request_sent=True,
            possibly_billable=True,
        )

    truncated = finish == "length"
    if truncated:
        err = OUTPUT_TRUNCATED  # partial content remains usable (ok=True)
    elif not (content or reasoning_content or msg.get("tool_calls")):
        err = EMPTY_CONTENT
    else:
        err = None

    cost = estimate_usd_cost(
        model_id=model_id,  # type: ignore[arg-type]
        prompt_tokens=usage.get("prompt_tokens"),
        completion_tokens=usage.get("completion_tokens"),
        cache_hit_tokens=(usage.get("prompt_cache_hit_tokens") or usage.get("cache_hit_tokens")),
        cache_miss_tokens=(usage.get("prompt_cache_miss_tokens") or usage.get("cache_miss_tokens")),
    )

    _emit_chat_event(
        outcome="success",
        model_id=model_id,
        request_id=req_id,
        client_rid=client_rid,
        raw_key=key,
        usage=usage,
        request_sent=True,
        possibly_billable=True,
        source_service=source_service,
        source_process=source_process,
        source_lane=source_lane,
        agent=agent,
        run_id=run_id,
        reservation_id=reservation_id,
        environment=environment,
    )

    return DeepSeekResponse(
        ok=err is None or err == OUTPUT_TRUNCATED,
        requested_policy=requested_policy,
        executed_policy=executed_policy if err is None else executed_policy,
        requested_model_id=model_id,
        returned_model=returned,
        thinking=thinking,
        reasoning_effort=reasoning_effort,
        content=content if isinstance(content, str) else None,
        reasoning_content=reasoning_content if isinstance(reasoning_content, str) else None,
        tool_calls=msg.get("tool_calls"),
        finish_reason=finish,
        usage=usage,
        estimated_cost_usd=cost.get("estimated_cost_usd"),
        cost_basis=cost.get("cost_basis"),
        request_id=req_id,
        latency_ms=latency,
        http_status=r.status_code,
        error_class=err,
        error_message=None if err is None else err,
        truncated=truncated,
        raw_response_hash=raw_hash,
        client_request_id=client_rid,
        request_sent=True,
        possibly_billable=True,
    )


def parse_strict_json(content: str | None) -> dict[str, Any]:
    """Strict JSON parse — no prose stripping, no regex extraction."""
    if content is None or not str(content).strip():
        raise DeepSeekError(EMPTY_CONTENT, "empty content for JSON parse")
    text = str(content).strip()
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as e:
        raise DeepSeekError(JSON_INVALID, f"JSON decode failed: {e}") from e
    if not isinstance(obj, dict):
        raise DeepSeekError(JSON_INVALID, "JSON root must be an object")
    return obj


def continue_with_tool_results(
    *,
    policy: str,
    prior_messages: list[dict],
    assistant_message: dict,
    tool_results: list[dict],
    operator_confirmed: bool = False,
    timeout: float = 90.0,
    max_tokens: int = 2048,
) -> DeepSeekResponse:
    """Continue a thinking-mode tool loop preserving assistant reasoning_content.

    assistant_message must include role=assistant and any reasoning_content/tool_calls
    returned by the provider. tool_results are role=tool messages.
    """
    msgs = list(prior_messages)
    # Preserve reasoning_content and tool_calls exactly
    asst = {
        "role": "assistant",
        "content": assistant_message.get("content"),
    }
    if "reasoning_content" in assistant_message:
        asst["reasoning_content"] = assistant_message.get("reasoning_content")
    if assistant_message.get("tool_calls") is not None:
        asst["tool_calls"] = assistant_message.get("tool_calls")
    msgs.append(asst)
    for tr in tool_results:
        msgs.append(tr)
    return chat(
        policy=policy,
        prompt="",  # unused when messages provided
        messages=msgs,
        operator_confirmed=operator_confirmed,
        timeout=timeout,
        max_tokens=max_tokens,
    )
