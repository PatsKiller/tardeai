"""CIO Governed Model Bridge — OpenClaw → Trade AI governed LLM boundary.

P-1.2A: Local HTTP server implementing OpenAI-compatible /v1/chat/completions.
Server-side caller→process mapping, canonical governance (registration, model
policy resolution, reservation, cap enforcement, settlement, circuit breaker,
provenance). Mock provider only — no live DeepSeek calls.

P-1.2B: Added RealProvider for live DeepSeek calls through governance pipeline.
Switch with CIO_BRIDGE_MODE=canary env var.

Bind: 127.0.0.1 (never 0.0.0.0). Port: configurable (default 8766).
"""
from __future__ import annotations

import hashlib
import http.server
import json
import logging
import os
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

# ── Project root for imports ───────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
if str(_PROJECT_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))

log = logging.getLogger("tradeai.cio_bridge")

# ── Bind / port config ─────────────────────────────────────────────────
BIND_HOST = os.environ.get("CIO_BRIDGE_HOST", "127.0.0.1")
BIND_PORT = int(os.environ.get("CIO_BRIDGE_PORT", "8766"))

# ── Provider mode ──────────────────────────────────────────────────────
# "mock" (default) = MockProvider only, zero real calls (P-1.2A)
# "canary" = RealProvider for live DeepSeek calls (P-1.2B)
BIND_MODE = os.environ.get("CIO_BRIDGE_MODE", "mock")

# ── Pre-shared auth header ─────────────────────────────────────────────
AUTH_HEADER = "X-TradeAI-Agent"

# ── Server-side caller → process_id mapping (NEVER trust client) ──────
# Gate-B: All six financial professional agents registered.
CALLER_PROCESS_MAP: dict[str, str] = {
    "alex": "alex_cio_synthesis",
    "maria": "maria_research_critique",
    "steph": "steph_allocation_review",
    "guardian": "guardian_risk_critique",
    "ledger": "ledger_tax_critique",
    "morgan": "morgan_wealth_synthesis",
    "advisory_desk": "advisory_desk_opinion",
}

# Task-type overrides for multi-policy callers (server-side only).
CALLER_TASK_PROCESS_MAP: dict[str, dict[str, str]] = {
    "advisory_desk": {
        "advisory_opinion": "advisory_desk_opinion",
        "advisory_synthesis": "advisory_desk_synthesis",
    },
}

# ── Reservation failure codes → HTTP status ────────────────────────────
# reserve_projected_cost() raises RuntimeError("<MACHINE_CODE>: detail") for
# every governance outcome. Flattening those into RESERVATION_FAILED/500 is a
# defect, not a simplification: classify_failure() lists RESERVATION_FAILED
# under RETRYABLE_TRANSIENT, so a hard cap breach was returned to callers with
# a retry policy that says "retry this". On 2026-09-06 that cost 46,106 rows —
# the caller read HTTP 500, treated it as a transient provider fault, and burned
# its entire remaining queue marking rows FAILED_PROVIDER in a few minutes.
#
# The request-count cap is enforced ONLY inside reserve_projected_cost; the
# check_cost_cap() pre-flight above covers dollar caps alone. So without this
# map there is no path by which a count breach can be reported as anything but
# a server fault.
_RESERVATION_CODE_STATUS: dict[str, int] = {
    "COST_CAP_EXCEEDED": 429,            # -> NON_RETRYABLE_COST. Budget, not fault.
    "COST_CONFIGURATION_INVALID": 500,   # -> NON_RETRYABLE_COST by code.
    "COST_PERSISTENCE_UNAVAILABLE": 503, # -> RETRYABLE_TRANSIENT. A ledger blip.
}


# ── Server-side caller → authorized task_types ─────────────────────────
# Caller-supplied process_id/model_id are never trusted.
# Each caller's task_type → server-selected policy.
CALLER_TASK_POLICY_MAP: dict[str, dict[str, str]] = {
    "alex": {
        "cio_synthesis": "PRO",
        "cio_escalation": "PRO_THINK",
    },
    "maria": {
        "research_critique": "FAST",
        "catalyst_narrative": "FAST",
        "agent_narrative": "FAST",
    },
    "steph": {
        "allocation_review": "PRO",
        "wealth_review": "FAST",
    },
    "guardian": {
        "risk_critique": "FAST",
    },
    "ledger": {
        "tax_critique": "FAST",
    },
    "morgan": {
        "wealth_synthesis": "FAST",
        "goal_tracking": "FAST",
    },
    "advisory_desk": {
        "advisory_opinion": "FAST",
        "advisory_synthesis": "PRO",
    },
}

# ── Policy → model resolution (generalized for all governed agents) ─────
POLICY_RESOLUTION: dict[str, dict[str, Any]] = {
    "PRO": {
        "provider": "deepseek",
        "model_id": "deepseek-v4-pro",
        "thinking": "disabled",
        "display_name": "DeepSeek V4 Pro (governed)",
    },
    "PRO_THINK": {
        "provider": "deepseek",
        "model_id": "deepseek-v4-pro",
        "thinking": "enabled",
        "reasoning_effort": "high",
        "display_name": "DeepSeek V4 Pro Think (governed)",
        "requires_deterministic_escalation_reason": True,
    },
    "FAST": {
        "provider": "deepseek",
        "model_id": "deepseek-v4-flash",
        "thinking": "disabled",
        "display_name": "DeepSeek V4 Flash (governed)",
    },
    "FAST_THINK": {
        "provider": "deepseek",
        "model_id": "deepseek-v4-flash",
        "thinking": "enabled",
        "display_name": "DeepSeek V4 Flash Think (governed)",
    },
}

# ── Legacy model IDs that must be rejected ─────────────────────────────
LEGACY_MODEL_IDS = frozenset({
    "deepseek-chat",
    "deepseek-reasoner",
    "deepseek-v4",
})


# ── Circuit breaker (in-process, per-bridge instance) ──────────────────
_CIRCUIT: dict[str, Any] = {"errors": 0, "open_until": 0.0, "last_error": None}
CIRCUIT_ERROR_THRESHOLD = int(os.environ.get("CIO_BRIDGE_CIRCUIT_ERRORS", "8"))
CIRCUIT_COOLDOWN_SEC = int(os.environ.get("CIO_BRIDGE_CIRCUIT_COOLDOWN_SEC", "900"))


# ── Module-level global cap overrides ──────────────────────────────────
GLOBAL_DAILY_USD_CAP = os.environ.get("LLM_GLOBAL_DAILY_USD_CAP")


# ══════════════════════════════════════════════════════════════════════════
#  GOVERNANCE IMPORTS — lazy to avoid circular imports at module load
# ══════════════════════════════════════════════════════════════════════════

_governance_imports_ok: bool | None = None


def _ensure_governance_imports() -> bool:
    global _governance_imports_ok
    if _governance_imports_ok is not None:
        return _governance_imports_ok
    try:
        import lib.llm_consumption as lc_mod  # noqa: F401
        import lib.llm_model_registry as lmr  # noqa: F401
        import lib.consumption_run_manual as crm  # noqa: F401
        _governance_imports_ok = True
        return True
    except Exception as e:
        log.error("Governance imports failed: %s", e)
        _governance_imports_ok = False
        return False


# ══════════════════════════════════════════════════════════════════════════
#  CIRCUIT BREAKER
# ══════════════════════════════════════════════════════════════════════════

def circuit_open() -> bool:
    return time.time() < float(_CIRCUIT.get("open_until") or 0)


def _trip_circuit(err: str) -> None:
    _CIRCUIT["errors"] = int(_CIRCUIT.get("errors") or 0) + 1
    _CIRCUIT["last_error"] = (err or "")[:200]
    if int(_CIRCUIT["errors"]) >= CIRCUIT_ERROR_THRESHOLD:
        _CIRCUIT["open_until"] = time.time() + CIRCUIT_COOLDOWN_SEC
        log.error("CIO bridge circuit breaker OPEN until %s", _CIRCUIT["open_until"])


def _reset_circuit() -> None:
    _CIRCUIT["errors"] = 0
    _CIRCUIT["open_until"] = 0.0


# ══════════════════════════════════════════════════════════════════════════
#  IDENTITY RESOLUTION
# ══════════════════════════════════════════════════════════════════════════

def resolve_caller(caller: str | None, task_type: str | None = None) -> str | None:
    """Map caller (+ optional task_type) → process_id. Unknown callers → None.

    Client-supplied process_id is never trusted. Task type is advisory only
    when the caller has an entry in CALLER_TASK_PROCESS_MAP.
    """
    c = (caller or "").strip().lower()
    t = (task_type or "").strip().lower()
    task_map = CALLER_TASK_PROCESS_MAP.get(c) or {}
    if t and t in task_map:
        return task_map[t]
    return CALLER_PROCESS_MAP.get(c)


def resolve_model_policy(process_id: str, task_type: str = "") -> dict[str, Any] | None:
    """Look up model policy for a registered governance process.

    Returns dict with provider, model_id, thinking, display_name, requested_policy.
    Unknown process_id returns None → fail closed.
    """
    # Map process_id → default policy
    process_policy_map: dict[str, str] = {
        "alex_cio_synthesis": "PRO",
        "alex_cio_escalation": "PRO_THINK",
        "maria_research_critique": "FAST",
        "steph_allocation_review": "PRO",
        "guardian_risk_critique": "FAST",
        "ledger_tax_critique": "FAST",
        "morgan_wealth_synthesis": "FAST",
        "advisory_desk_opinion": "FAST",
        "advisory_desk_synthesis": "PRO",
    }
    policy_name = process_policy_map.get(process_id)
    if policy_name is None:
        return None  # Unknown process → fail closed
    base = POLICY_RESOLUTION.get(policy_name, POLICY_RESOLUTION["FAST"])
    out = dict(base)
    # Required for deepseek_allowed_policies check (defaults to PRO if missing).
    out["requested_policy"] = policy_name
    return out


# ══════════════════════════════════════════════════════════════════════════
#  PRIVACY / LOGGING
# ══════════════════════════════════════════════════════════════════════════

def hash_content(content: str) -> str:
    """SHA-256 hash of full prompt/response content for audit trail."""
    return hashlib.sha256((content or "").encode("utf-8", errors="replace")).hexdigest()[:32]


def sanitize_log_summary(messages: list[dict]) -> str:
    """Return a safe summary for logging — role counts, no raw content."""
    parts = []
    for m in (messages or []):
        role = str(m.get("role") or "unknown")
        content_len = len(str(m.get("content") or ""))
        has_tools = "tools" in m
        has_tool_calls = "tool_calls" in m
        extra = []
        if has_tools:
            extra.append("tools")
        if has_tool_calls:
            extra.append("tool_calls")
        suffix = f"({','.join(extra)})" if extra else ""
        parts.append(f"{role}:{content_len}chars{suffix}")
    return "; ".join(parts)


# ══════════════════════════════════════════════════════════════════════════
#  MOCK PROVIDER (P-1.2A only — zero real provider calls)
# ══════════════════════════════════════════════════════════════════════════

class MockProvider:
    """Returns valid OpenAI-compatible chat completion fixtures.

    Supports tool_calls, structured_output, and streaming.
    Never makes any network call.
    """

    _instance: MockProvider | None = None

    def __init__(self) -> None:
        self.call_count = 0
        self._lock = threading.Lock()

    @classmethod
    def instance(cls) -> MockProvider:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def generate(self, messages: list[dict], model_id: str,
                 tools: list[dict] | None = None,
                 tool_choice: str | None = None,
                 response_format: dict | None = None,
                 stream: bool = False,
                 max_tokens: int = 16384,
                 thinking: str = "disabled",
                 reasoning_effort: str | None = None) -> dict[str, Any]:
        with self._lock:
            self.call_count += 1

        # Check if client is requesting tool calls
        has_tools = bool(tools)
        tool_call_requested = has_tools and (tool_choice is None or tool_choice != "none")

        # Check if structured JSON requested
        has_json_schema = (
            response_format is not None
            and response_format.get("type") == "json_schema"
        )

        if tool_call_requested:
            content = None
            tool_calls = [{
                "id": f"mock_tool_call_{self.call_count}",
                "type": "function",
                "function": {
                    "name": (tools[0].get("function", {}).get("name") if tools
                             else "get_financial_data"),
                    "arguments": json.dumps({
                        "summary": "Governed mock tool response from CIO bridge",
                        "confidence": 0.95,
                        "source": "Trade AI canonical data",
                    }),
                },
            }]
            response_content = None
        elif has_json_schema:
            schema_name = response_format.get("json_schema", {}).get("name", "response")
            content = json.dumps({
                "analysis": f"Governed CIO bridge mock structured response for {schema_name}",
                "status": "ok",
                "model": model_id,
                "provider": "tradeai_governed_mock",
                "confidence": 0.92,
            })
            tool_calls = None
            response_content = content
        else:
            content = (
                f"[CIO Governed Bridge] Mock response for model={model_id}. "
                f"This is a governed, server-authorized response routed through "
                f"Trade AI's canonical LLM boundary. No live provider call was made."
            )
            tool_calls = None
            response_content = content

        return {
            "id": f"cio-bridge-mock-{uuid.uuid4().hex[:12]}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model_id,
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": response_content,
                    **(dict(tool_calls=tool_calls) if tool_calls else {}),
                },
                "finish_reason": "tool_calls" if tool_calls else "stop",
            }],
            "usage": {
                "prompt_tokens": 120,
                "completion_tokens": 80,
                "total_tokens": 200,
            },
            "_tradeai": {
                "mock": True,
                "bridge_version": "P-1.2A",
                "provider": "tradeai_governed_mock",
                "governance_pass": True,
            },
        }

    def generate_stream(self, messages: list[dict], model_id: str,
                        tools: list[dict] | None = None,
                        max_tokens: int = 16384) -> list[str]:
        """Return list of SSE-formatted strings for streaming simulation."""
        response = self.generate(messages, model_id, tools=tools, max_tokens=max_tokens,
                                 stream=False)
        content = response["choices"][0]["message"].get("content") or ""
        if content is None:
            content = ""

        chunks = []
        # Simulate streaming as chunks
        words = content.split()
        for i, word in enumerate(words):
            chunk = {
                "id": response["id"],
                "object": "chat.completion.chunk",
                "created": response["created"],
                "model": response["model"],
                "choices": [{
                    "index": 0,
                    "delta": {"content": word + " "},
                    "finish_reason": None,
                }],
            }
            chunks.append(f"data: {json.dumps(chunk)}\n\n")
        # Final chunk
        final = {
            "id": response["id"],
            "object": "chat.completion.chunk",
            "created": response["created"],
            "model": response["model"],
            "choices": [{
                "index": 0,
                "delta": {},
                "finish_reason": "stop",
            }],
            "usage": response["usage"],
        }
        chunks.append(f"data: {json.dumps(final)}\n\n")
        chunks.append("data: [DONE]\n\n")
        return chunks


# ══════════════════════════════════════════════════════════════════════════
#  REAL PROVIDER (P-1.2B canary — live DeepSeek calls through governance)
# ══════════════════════════════════════════════════════════════════════════

def _emit_bridge_cost(
    *,
    outcome: str,
    model: str | None,
    request_id: str | None = None,
    client_request_id: str | None = None,
    raw_key: str | None = None,
    usage: dict | None = None,
    request_sent: bool = False,
    possibly_billable: bool = False,
    error_class: str | None = None,
) -> None:
    """Direct-bypass emit. RealProvider does not call deepseek_client.chat (tools)."""
    try:
        from lib.provider_cost.emit import emit_cost_event
        usage = usage or {}
        emit_cost_event(
            provider="deepseek",
            model=str(model or ""),
            outcome=outcome,
            request_id=request_id,
            client_request_id=client_request_id,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            cache_hit_tokens=usage.get("prompt_cache_hit_tokens") or usage.get("cache_hit_tokens"),
            cache_miss_tokens=usage.get("prompt_cache_miss_tokens") or usage.get("cache_miss_tokens"),
            raw_key=raw_key,
            request_sent=request_sent,
            possibly_billable=possibly_billable,
            error_class=error_class,
            source_service="cio_governed_model_bridge",
            evidence_refs=["cio_governed_model_bridge.RealProvider"],
        )
    except Exception:
        return


class RealProvider:
    """Live DeepSeek V4 provider — governed, exact model, no fallback.

    Uses canonical deepseek_tradeai API key (never logs, never exposes).
    Own HTTP path because tools/tool_choice are not in deepseek_client.chat().
    Emits one ProviderCostEvent per attempt (does not also call chat()).
    """

    _instance: RealProvider | None = None

    def __init__(self) -> None:
        self.call_count = 0
        self._lock = threading.Lock()

    @classmethod
    def instance(cls) -> RealProvider:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def generate(self, messages: list[dict], model_id: str,
                 tools: list[dict] | None = None,
                 tool_choice: str | None = None,
                 response_format: dict | None = None,
                 stream: bool = False,
                 max_tokens: int = 16384,
                 temperature: float = 0.3,
                 thinking: str = "disabled",
                 reasoning_effort: str | None = None) -> dict[str, Any]:
        if stream:
            raise NotImplementedError("RealProvider does not support streaming in P-1.2B")

        with self._lock:
            self.call_count += 1

        # ── Import deepseek client ──────────────────────────────────────
        try:
            from scripts.lib.deepseek_client import chat as _ds_chat, DeepSeekError  # noqa: F811
            from lib.llm_model_registry import get_deepseek_api_key
        except Exception as e:
            log.error("RealProvider: cannot import deepseek_client: %s", e)
            raise RuntimeError(f"Cannot import deepseek_client: {e}") from e

        # ── Get API key (never log, never expose) ───────────────────────
        key, env_name, _legacy = get_deepseek_api_key()
        if not key:
            raise RuntimeError(
                f"DeepSeek API key not configured (canonical env: deepseek_tradeai). "
                f"RealProvider requires a configured key for live canary calls."
            )

        # ── Build request body ──────────────────────────────────────────
        import requests as _requests

        body: dict[str, Any] = {
            "model": model_id,
            "messages": messages,
            "max_tokens": max_tokens,
        }

        # deepseek-v4-* default to reasoning mode when `thinking` is omitted, which
        # returns the whole budget as reasoning_content and an EMPTY content — breaking
        # every non-think caller (advisory FAST/PRO, steph, guardian, ledger, morgan).
        # Respect the resolved policy exactly like deepseek_client.chat() does.
        thinking_on = (thinking or "disabled").lower() in ("enabled", "on", "true", "1")
        body["thinking"] = {"type": "enabled"} if thinking_on else {"type": "disabled"}
        if thinking_on and reasoning_effort:
            body["reasoning_effort"] = reasoning_effort

        if tools:
            body["tools"] = tools
            if tool_choice:
                body["tool_choice"] = tool_choice

        # Temperature only in non-thinking mode
        if temperature is not None and not thinking_on:
            body["temperature"] = temperature

        # Response format
        if response_format and response_format.get("type") == "json_object":
            body["response_format"] = {"type": "json_object"}

        # ── Make HTTP call ──────────────────────────────────────────────
        base = "https://api.deepseek.com"
        client_rid = uuid.uuid4().hex[:12]
        t0 = time.time()

        try:
            r = _requests.post(
                f"{base}/v1/chat/completions",
                json=body,
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                    "User-Agent": "tradeai-cio-bridge/1.0",
                    "X-TradeAI-Request-Id": client_rid,
                },
                timeout=90.0,
            )
        except _requests.Timeout:
            _emit_bridge_cost(
                outcome="possibly_billable_attempt",
                model=model_id,
                client_request_id=client_rid,
                raw_key=key,
                request_sent=True,
                possibly_billable=True,
                error_class="TIMEOUT",
            )
            err = RuntimeError("DeepSeek API timeout after 90s")
            err.request_sent = True  # type: ignore[attr-defined]
            err.possibly_billable = True  # type: ignore[attr-defined]
            raise err
        except _requests.RequestException as e:
            _emit_bridge_cost(
                outcome="possibly_billable_attempt",
                model=model_id,
                client_request_id=client_rid,
                raw_key=key,
                request_sent=True,
                possibly_billable=True,
                error_class="NETWORK_ERROR",
            )
            err = RuntimeError(f"DeepSeek API network error: {type(e).__name__}")
            err.request_sent = True  # type: ignore[attr-defined]
            err.possibly_billable = True  # type: ignore[attr-defined]
            raise err from e

        latency_ms = int((time.time() - t0) * 1000)
        provider_request_id = r.headers.get("x-request-id", client_rid)

        if r.status_code != 200:
            _emit_bridge_cost(
                outcome="possibly_billable_attempt",
                model=model_id,
                request_id=provider_request_id,
                client_request_id=client_rid,
                raw_key=key,
                request_sent=True,
                possibly_billable=True,
                error_class=f"HTTP_{r.status_code}",
            )
            err = RuntimeError(
                f"DeepSeek API returned HTTP {r.status_code}: "
                f"{r.text[:500]}"
            )
            err.request_sent = True  # type: ignore[attr-defined]
            err.possibly_billable = True  # type: ignore[attr-defined]
            raise err

        try:
            payload = r.json()
        except Exception:
            _emit_bridge_cost(
                outcome="possibly_billable_attempt",
                model=model_id,
                request_id=provider_request_id,
                client_request_id=client_rid,
                raw_key=key,
                request_sent=True,
                possibly_billable=True,
                error_class="JSON_INVALID",
            )
            err = RuntimeError("DeepSeek API returned non-JSON response")
            err.request_sent = True  # type: ignore[attr-defined]
            err.possibly_billable = True  # type: ignore[attr-defined]
            raise err

        returned_model = payload.get("model")
        if returned_model and returned_model != model_id:
            usage_mm = payload.get("usage") or {}
            _emit_bridge_cost(
                outcome="possibly_billable_attempt",
                model=model_id,
                request_id=provider_request_id,
                client_request_id=client_rid,
                raw_key=key,
                usage=usage_mm,
                request_sent=True,
                possibly_billable=True,
                error_class="MISMATCHED_RETURNED_MODEL",
            )
            err = RuntimeError(
                f"Model mismatch: requested {model_id}, returned {returned_model}"
            )
            err.request_sent = True  # type: ignore[attr-defined]
            err.possibly_billable = True  # type: ignore[attr-defined]
            raise err

        choice = (payload.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        finish_reason = choice.get("finish_reason")

        content = msg.get("content")
        # If the model still returned reasoning-only output (thinking ignored / budget
        # exhausted in reasoning), fall back to reasoning_content so the caller never
        # receives an empty answer.
        if not content:
            content = msg.get("reasoning_content") or msg.get("reasoning") or None

        usage = payload.get("usage") or {}
        import hashlib
        raw_hash = hashlib.sha256(r.content).hexdigest()[:24]
        _emit_bridge_cost(
            outcome="success",
            model=returned_model or model_id,
            request_id=provider_request_id,
            client_request_id=client_rid,
            raw_key=key,
            usage=usage,
            request_sent=True,
            possibly_billable=True,
        )

        return {
            "id": client_rid,
            "object": "chat.completion",
            "created": int(time.time()),
            "model": returned_model or model_id,
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": content,
                    **({"tool_calls": msg["tool_calls"]} if msg.get("tool_calls") else {}),
                },
                "finish_reason": finish_reason,
            }],
            "usage": usage,
            "_tradeai": {
                "real": True,
                "bridge_version": "P-1.2B",
                "provider": "deepseek",
                "governance_pass": True,
                "provider_request_id": provider_request_id,
                "latency_ms": latency_ms,
                "provenance_hash": raw_hash,
            },
        }


# ══════════════════════════════════════════════════════════════════════════
#  GOVERNANCE PIPELINE
# ══════════════════════════════════════════════════════════════════════════

def execute_governed_call(
    messages: list[dict],
    *,
    process_id: str,
    tools: list[dict] | None = None,
    tool_choice: str | None = None,
    response_format: dict | None = None,
    stream: bool = False,
    max_tokens: int = 16384,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Governed CIO model call pipeline — fail-closed, no silent fallback.

    Pipeline:
      1. Circuit breaker check
      2. Process registration check
      3. Model policy resolution (server-side, ignore client model)
      4. Policy allowlist check
      5. Global + per-process cap check
      6. Reservation
      7. Mock provider response (P-1.2A) — NO live provider
      8. Settlement
      9. Return provenance-rich response

    Returns dict suitable for HTTP JSON response (OpenAI-compatible format).
    On any governance failure, returns error dict with cost_estimate=0.0.
    """
    rid = request_id or uuid.uuid4().hex[:12]
    t0 = time.time()

    def _error(code: str, message: str, status: int = 400,
               **extra: Any) -> dict[str, Any]:
        if "retry" not in extra:
            from scripts.lib.cio_provider_retry_v1 import classify_failure

            extra["retry"] = classify_failure(code, http_status=status)
        return {
            "error": {
                "code": code,
                "message": message,
                "status": status,
                **extra,
            },
            "id": rid,
            "object": "chat.completion.error",
            "created": int(time.time()),
            "model": "tradeai_governed",
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "cost_estimate": 0.0,
            "governance_pass": False,
            "latency_ms": int((time.time() - t0) * 1000),
        }

    # ── Step 1: Circuit breaker ────────────────────────────────────────
    if circuit_open():
        return _error(
            "CIRCUIT_OPEN",
            f"CIO bridge circuit breaker open; cooldown until {_CIRCUIT['open_until']}",
            status=503,
            circuit_last_error=_CIRCUIT.get("last_error"),
        )

    # ── Step 2: Process registration ───────────────────────────────────
    if not _ensure_governance_imports():
        return _error(
            "GOVERNANCE_UNAVAILABLE",
            "CIO bridge cannot load governance modules",
            status=503,
        )
    import lib.llm_consumption as lc

    cfg = lc.get_process_config(process_id)
    if not cfg.get("registered"):
        return _error(
            "PROCESS_NOT_REGISTERED",
            f"Process '{process_id}' is not registered in llm_process_registry.json",
            status=404,
        )

    # ── Step 3: Model policy resolution (server-side) ──────────────────
    policy = resolve_model_policy(process_id)
    if policy is None:
        return _error("UNKNOWN_PROCESS", f"Process '{process_id}' not registered in governance bridge", status=400)
    model_id = policy["model_id"]

    # ── Step 4: Reject legacy model IDs ────────────────────────────────
    import lib.llm_model_registry as lmr
    try:
        lmr.reject_legacy_model_id(model_id)
    except lmr.RegistryError as e:
        return _error("LEGACY_MODEL_REJECTED", str(e), status=400)

    # Policy allowlist check from process config
    ds_pols = [str(x).upper() for x in (cfg.get("deepseek_allowed_policies") or [])]
    requested_policy = policy.get("requested_policy", "PRO")
    if ds_pols and requested_policy not in ds_pols:
        return _error(
            "POLICY_NOT_ALLOWED",
            f"Policy {requested_policy} not allowed for process {process_id}. "
            f"Allowed: {ds_pols}",
            status=403,
        )

    # ── Step 5: Cost cap checks ────────────────────────────────────────
    import lib.consumption_run_manual as crm

    # Validate caps exist
    try:
        crm.validate_paid_cap_config(cfg, require_global=True)
    except RuntimeError as e:
        return _error("COST_CONFIGURATION_INVALID", str(e), status=500)

    projected = crm.projected_max_cost_usd(
        model_id=model_id,
        max_input_tokens=cfg.get("max_input_tokens") or 32000,
        max_output_tokens=max_tokens,
    )

    try:
        gcap = float(GLOBAL_DAILY_USD_CAP) if GLOBAL_DAILY_USD_CAP not in (None, "") else None
    except (TypeError, ValueError):
        gcap = None

    cap_check = lc.check_cost_cap(process_id, projected_usd=projected, global_cap=gcap)
    if not cap_check.get("allow"):
        return _error(
            "COST_CAP_EXCEEDED",
            f"Cost cap would be exceeded: {cap_check}",
            status=429,
        )

    # ── Step 6: Reservation ────────────────────────────────────────────
    reservation_id: int | None = None
    try:
        reservation_id = lc.reserve_projected_cost(
            process_id, projected,
            model_id=model_id,
            process_config=cfg,
            global_cap=gcap,
            metadata={
                "bridge": "cio_governed",
                "request_id": rid,
                "policy": requested_policy,
            },
        )
    except RuntimeError as e:
        # Preserve the machine code the reservation raised rather than reporting
        # every governance outcome as a server fault.
        code, _, detail = str(e).partition(":")
        code = code.strip().upper()
        status = _RESERVATION_CODE_STATUS.get(code)
        if status is not None:
            log.warning("reservation refused for %s: %s (HTTP %d)", process_id, e, status)
            return _error(code, detail.strip() or str(e), status=status)
        # An unmapped RuntimeError is a genuine fault. Log the traceback: this
        # handler previously discarded it, which is why 2.7 MB of bridge log
        # held zero tracebacks while every request 500'd for 50 minutes.
        log.exception("reservation failed for %s: unmapped RuntimeError", process_id)
        return _error("RESERVATION_FAILED", str(e), status=500)
    except Exception as e:
        log.exception("reservation failed for %s", process_id)
        return _error("RESERVATION_FAILED", f"Unexpected reservation error: {type(e).__name__}",
                      status=500)

    # Real provider calls get a durable side-effect identity before dispatch.
    # Mock calls intentionally remain isolated from the production journal.
    provider_journal = None
    provider_semantic_key: str | None = None
    if BIND_MODE == "canary":
        from scripts.lib.cio_provider_retry_v1 import (
            ProviderRequestJournal,
            semantic_request_key,
        )

        provider_journal = ProviderRequestJournal()
        provider_semantic_key = semantic_request_key(
            request_id=rid,
            process_id=process_id,
            model_id=model_id,
        )
        journal_reservation = provider_journal.reserve(
            semantic_key=provider_semantic_key,
            request_id=rid,
            process_id=process_id,
            provider=str(policy["provider"]),
            model_id=model_id,
            task=str(requested_policy),
            projected_cost_usd=projected,
        )
        if not journal_reservation.get("allowed"):
            lc.settle_reservation(reservation_id, None, ok=False, billable_attempt=False)
            current = journal_reservation.get("current") or {}
            return _error(
                "PROVIDER_REQUEST_REPLAY_BLOCKED",
                "Provider request identity is already dispatched, ambiguous, completed, or exhausted",
                status=409,
                provider_request_state=current.get("state") or journal_reservation.get("reason"),
            )

    # ── Step 7: Provider (mock or real based on BIND_MODE) ──────────────
    if BIND_MODE == "canary":
        provider = RealProvider.instance()
        log.info("RealProvider selected for canary: model=%s policy=%s", model_id, requested_policy)
        assert provider_journal is not None and provider_semantic_key is not None
        provider_journal.record(provider_semantic_key, state="DISPATCHED")
    else:
        provider = MockProvider.instance()
    try:
        try:
            from lib.provider_cost.context import cost_attribution
        except Exception:
            from contextlib import contextmanager as _cm

            @_cm
            def cost_attribution(**_kw):
                yield {}
        with cost_attribution(
            source_service="cio_governed_model_bridge",
            source_process=process_id,
            source_lane=requested_policy,
            reservation_id=str(reservation_id) if reservation_id is not None else None,
            run_id=rid,
        ):
            response = provider.generate(
                messages, model_id,
                tools=tools,
                tool_choice=tool_choice,
                response_format=response_format,
                stream=False,
                max_tokens=max_tokens,
                thinking=policy.get("thinking", "disabled"),
                reasoning_effort=policy.get("reasoning_effort"),
            )
    except Exception as e:
        provider_name = "RealProvider" if BIND_MODE == "canary" else "MockProvider"
        _trip_circuit(f"provider_failure:{type(e).__name__}:{provider_name}")
        sent = bool(getattr(e, "possibly_billable", False) or getattr(e, "request_sent", False))
        lc.settle_reservation(reservation_id, None, ok=False, billable_attempt=sent)
        retry = None
        if provider_journal is not None and provider_semantic_key is not None:
            from scripts.lib.cio_provider_retry_v1 import classify_failure

            retry = classify_failure(type(e).__name__, request_sent=sent)
            journal_state = "AMBIGUOUS" if sent else (
                "RETRYABLE" if retry["retryable"] else "NON_RETRYABLE"
            )
            provider_journal.record(
                provider_semantic_key,
                state=journal_state,
                retry_disposition=retry["disposition"],
                error_class=type(e).__name__,
                request_sent=sent,
            )
        return _error(
            "PROVIDER_ERROR",
            f"{provider_name} failure: {type(e).__name__}",
            status=500,
            **({"retry": retry} if retry else {}),
        )

    # ── Step 8: Model mismatch check ───────────────────────────────────
    returned_model = response.get("model")
    if returned_model and returned_model != model_id:
        _trip_circuit(f"model_mismatch: expected {model_id}, got {returned_model}")
        lc.settle_reservation(reservation_id, None, ok=False, billable_attempt=False)
        if provider_journal is not None and provider_semantic_key is not None:
            from scripts.lib.cio_provider_retry_v1 import classify_failure

            retry = classify_failure("MODEL_MISMATCH")
            provider_journal.record(
                provider_semantic_key,
                state="NON_RETRYABLE",
                retry_disposition=retry["disposition"],
                error_class="MODEL_MISMATCH",
            )
        return _error(
            "MODEL_MISMATCH",
            f"Provider returned wrong model: expected {model_id}, got {returned_model}",
            status=502,
        )

    # ── Step 9: Settlement ─────────────────────────────────────────────
    usage = response.get("usage") or {}
    try:
        import lib.llm_model_registry as lmr2
        cost_est = lmr2.estimate_usd_cost(
            model_id=model_id,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
        )
        actual_cost = cost_est.get("estimated_cost_usd")
    except Exception:
        actual_cost = None

    try:
        lc.settle_reservation(
            reservation_id, actual_cost,
            ok=True,
            billable_attempt=True,
            projected_fallback=projected,
        )
    except Exception as e:
        _trip_circuit(f"settlement_failure:{type(e).__name__}")
        retry = None
        if provider_journal is not None and provider_semantic_key is not None:
            from scripts.lib.cio_provider_retry_v1 import classify_failure

            retry = classify_failure("SETTLEMENT_FAILED", request_sent=True)
            provider_journal.record(
                provider_semantic_key,
                state="AMBIGUOUS",
                retry_disposition=retry["disposition"],
                error_class=type(e).__name__,
                provider_succeeded=True,
            )
        return _error(
            "SETTLEMENT_FAILED",
            f"Settlement persistence failed: {type(e).__name__}",
            status=500,
            **({"retry": retry} if retry else {}),
        )

    if provider_journal is not None and provider_semantic_key is not None:
        provider_meta = response.get("_tradeai") or {}
        provider_journal.record(
            provider_semantic_key,
            state="COMPLETED",
            provider_request_id=provider_meta.get("provider_request_id"),
            usage={
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "total_tokens": usage.get("total_tokens"),
            },
            actual_cost_usd=actual_cost,
            result_hash=hashlib.sha256(
                json.dumps(response, sort_keys=True, default=str).encode("utf-8")
            ).hexdigest(),
        )

    _reset_circuit()

    # ── Step 10: Assemble response with provenance ─────────────────────
    latency_ms = int((time.time() - t0) * 1000)
    is_mock = BIND_MODE != "canary"
    response["id"] = rid
    response["model"] = model_id
    response["_tradeai"] = {
        **response.get("_tradeai", {}),
        "governance_pass": True,
        "bridge": "cio_governed",
        "bridge_version": "P-1.2B" if BIND_MODE == "canary" else "P-1.2A",
        "process_id": process_id,
        "requested_policy": requested_policy,
        "model_id": model_id,
        "provider": policy["provider"],
        "latency_ms": latency_ms,
        "request_id": rid,
        "reservation_id": reservation_id,
        "cost_estimate": actual_cost,
        "cost_basis": "provider_usage_x_registry_snapshot",
        "legacy_model_ids_rejected": True,
        "client_model_ignored": True,
        "mock": is_mock,
        "provider_request_journal": (
            {
                "schema": "ProviderRequestJournal@v1",
                "semantic_key": provider_semantic_key,
                "state": "COMPLETED",
            }
            if provider_semantic_key else None
        ),
    }

    # ── Step 11: Log (sanitized) — must run before return ──────────────
    try:
        lc.log_call(
            lane=requested_policy.lower(),
            process_id=process_id,
            task_summary=sanitize_log_summary(messages),
            trigger_mode="automated",
            success=True,
            model_name=model_id,
            prompt="[content hashed: " + hash_content(json.dumps(messages)) + "]",
            response="[content hashed: " + hash_content(json.dumps(response)) + "]",
            tokens_in=usage.get("prompt_tokens"),
            tokens_out=usage.get("completion_tokens"),
            duration_ms=latency_ms,
            estimated_cost_usd=actual_cost,
            cost_basis="provider_usage_x_registry_snapshot",
            requested_policy=requested_policy,
            requested_model_id=model_id,
            returned_model=returned_model,
            provider_request_id=rid,
            metadata={
                "governance": "cio_bridge_v1",
                "mock": is_mock,
                "bridge_version": "P-1.2B" if BIND_MODE == "canary" else "P-1.2A",
                "reservation_id": reservation_id,
                **{k: v for k, v in response.get("_tradeai", {}).items()
                   if k not in ("usage",)},
            },
        )
    except Exception:
        pass

    return response


# ══════════════════════════════════════════════════════════════════════════
#  HTTP HANDLER
# ══════════════════════════════════════════════════════════════════════════

class GovernedBridgeHandler(http.server.BaseHTTPRequestHandler):
    """OpenAI-compatible /v1/chat/completions handler."""

    server_version = "TradeAI-CIO-Bridge/P-1.2A"

    def log_message(self, fmt: str, *args: Any) -> None:
        """Override to use project logger with sanitization."""
        log.info("HTTP %s", fmt % args)

    def do_POST(self) -> None:
        if self.path != "/v1/chat/completions":
            self._send_error(404, "NOT_FOUND", "Only /v1/chat/completions is supported")
            return

        # Auth: require X-TradeAI-Agent header
        caller = self.headers.get(AUTH_HEADER)
        if not caller:
            self._send_error(401, "UNAUTHORIZED",
                             f"Missing {AUTH_HEADER} header")
            return

        task_type = self.headers.get("X-TradeAI-Task-Type") or ""
        process_id = resolve_caller(caller, task_type=task_type)
        if not process_id:
            self._send_error(401, "UNAUTHORIZED",
                             f"Unknown caller '{caller}' — not in server-side mapping")
            return

        # Read body
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            if content_length == 0:
                self._send_error(400, "BAD_REQUEST", "Empty body")
                return
            body = self.rfile.read(content_length)
            data = json.loads(body)
        except json.JSONDecodeError:
            self._send_error(400, "BAD_REQUEST", "Invalid JSON body")
            return
        except Exception:
            self._send_error(400, "BAD_REQUEST", "Cannot read request body")
            return

        messages = data.get("messages") or []
        if not messages:
            self._send_error(400, "BAD_REQUEST", "messages required")
            return

        # Client-supplied model is logged but IGNORED for resolution
        client_model = data.get("model")
        tools = data.get("tools")
        tool_choice = data.get("tool_choice")
        response_format = data.get("response_format")
        stream = bool(data.get("stream", False))
        max_tokens = int(data.get("max_tokens") or 16384)

        # Reject client-supplied legacy model IDs
        if client_model and client_model.strip().lower() in LEGACY_MODEL_IDS:
            self._send_error(400, "LEGACY_MODEL_REJECTED",
                             f"Legacy model {client_model!r} is rejected. "
                             f"Server resolves model independently.")
            return

        # Reject client arbitrary process/model injection
        client_process = data.get("process_id") or data.get("process")
        if client_process and str(client_process).strip().lower() != "alex_cio_synthesis":
            log.warning("Client attempted arbitrary process_id: %s", client_process)
            self._send_error(403, "PROCESS_ID_REJECTED",
                             "Client-supplied process_id is rejected. "
                             "Server resolves process from caller identity.")
            return

        # Execute governed call
        result = execute_governed_call(
            messages,
            process_id=process_id,
            tools=tools,
            tool_choice=tool_choice,
            response_format=response_format,
            stream=stream,
            max_tokens=max_tokens,
        )

        # Check for governance error
        if "error" in result:
            status = result["error"].get("status", 500)
            self._send_json(status, result)
            return

        # Streaming support
        if stream:
            self._send_stream(result, messages, process_id, tools, max_tokens)
        else:
            self._send_json(200, result)

    def _send_json(self, status: int, data: dict) -> None:
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-TradeAI-Governed", "cio_bridge_p1_2a")
        self.end_headers()
        self.wfile.write(body)

    def _send_error(self, status: int, code: str, message: str) -> None:
        result = {
            "error": {"code": code, "message": message, "status": status},
            "id": uuid.uuid4().hex[:12],
            "object": "chat.completion.error",
            "created": int(time.time()),
            "model": "tradeai_governed",
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "cost_estimate": 0.0,
            "governance_pass": False,
        }
        self._send_json(status, result)

    def _send_stream(self, result: dict, messages: list, process_id: str,
                     tools: list | None, max_tokens: int) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-TradeAI-Governed", f"cio_bridge_{'p1_2b' if BIND_MODE == 'canary' else 'p1_2a'}")
        self.end_headers()

        policy = resolve_model_policy(process_id)
        if policy is None:
            self.send_error(400, f"Unknown process: {process_id}")
            return
        model_id = policy["model_id"]
        provider = RealProvider.instance() if BIND_MODE == "canary" else MockProvider.instance()
        if BIND_MODE == "canary":
            try:
                response = provider.generate(messages, model_id, tools=tools, max_tokens=max_tokens, stream=False)
                content = response["choices"][0]["message"].get("content") or ""
                chunks = [
                    f"data: {json.dumps(response)}\n\n",
                    "data: [DONE]\n\n",
                ]
            except NotImplementedError:
                chunks = ["data: [DONE]\n\n"]
        else:
            chunks = provider.generate_stream(messages, model_id, tools=tools, max_tokens=max_tokens)
        for chunk in chunks:
            self.wfile.write(chunk.encode("utf-8"))
            self.wfile.flush()


# ══════════════════════════════════════════════════════════════════════════
#  SERVER LIFECYCLE
# ══════════════════════════════════════════════════════════════════════════

def start_server(host: str = BIND_HOST, port: int = BIND_PORT) -> http.server.HTTPServer:
    """Start the CIO governed bridge server (blocking)."""
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError(f"CIO bridge must bind to loopback only, got {host}")

    server = http.server.HTTPServer((host, port), GovernedBridgeHandler)
    log.info("CIO Governed Bridge starting on %s:%d", host, port)
    log.info("Caller map: %s", CALLER_PROCESS_MAP)
    log.info("Mode: %s", "REAL (canary)" if BIND_MODE == "canary" else "MOCK (P-1.2A)")
    return server


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    )
    version_label = "P-1.2B (canary)" if BIND_MODE == "canary" else "P-1.2A"
    provider_label = "REAL" if BIND_MODE == "canary" else "MOCK"
    log.info("CIO Governed Model Bridge %s", version_label)
    log.info("Bind: %s:%d | Auth: %s | Provider: %s", BIND_HOST, BIND_PORT, AUTH_HEADER, provider_label)

    server = start_server()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Shutting down CIO bridge")
        server.shutdown()


if __name__ == "__main__":
    main()
