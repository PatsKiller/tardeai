"""Server-routed Ask research roles with observed provider identity and cost evidence.

This adapter never chooses credentials or calls a provider directly. Configuration
must register each role before it can run; missing or changed routes fail closed.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
from typing import Any, Callable, Mapping
import uuid
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[2]
MANUAL_PROCESS = "cio_ask_deep_research"
SCHEDULED_PROCESS = "cio_ask_reanswer"
CRITIQUE_PROCESSES = {
    "deepseek": "cio_ask_critique_deepseek",
    "grok": "cio_ask_critique_grok",
    "chatgpt": "cio_ask_critique_chatgpt",
}
TASK_ROUTES = {SCHEDULED_PROCESS: SCHEDULED_PROCESS, **{p: p for p in CRITIQUE_PROCESSES.values()}}


class ProviderRefused(RuntimeError):
    def __init__(self, code: str, *, evidence: dict[str, Any] | None = None):
        self.code = code
        self.evidence = evidence or {"actual_cost_usd": 0.0, "cost_usage_known": True, "request_sent": False}
        super().__init__(code)


@dataclass(frozen=True)
class ProviderResult:
    text: str
    evidence: dict[str, Any]


def _money(value: Any) -> Decimal | None:
    try:
        result = Decimal(str(value))
    except (ValueError, TypeError, InvalidOperation):
        return None
    return result if result.is_finite() and result >= 0 else None


def primary_process(process_id: str | None, *, manual_trigger: bool) -> str:
    selected = process_id or (MANUAL_PROCESS if manual_trigger else SCHEDULED_PROCESS)
    if selected not in {MANUAL_PROCESS, SCHEDULED_PROCESS}:
        raise ProviderRefused("ASK_PRIMARY_PROCESS_NOT_ALLOWED")
    if selected == SCHEDULED_PROCESS and manual_trigger:
        raise ProviderRefused("SCHEDULED_MANUAL_TRIGGER_FORBIDDEN")
    if selected == MANUAL_PROCESS and not manual_trigger:
        raise ProviderRefused("MANUAL_TRIGGER_REQUIRED")
    return selected


def _configuration(process_id: str, provider: str, root: Path) -> str | None:
    """Verify the server-owned route, before any HTTP or provider call."""
    try:
        registry = json.loads((root / "config/llm_process_registry.json").read_text())
        cfg = next((r for r in registry["processes"] if r["id"] == process_id), None)
        if cfg is None:
            raise ProviderRefused("PROCESS_NOT_REGISTERED")
        if process_id != MANUAL_PROCESS and cfg.get("default_mode") != "automated":
            raise ProviderRefused("SCHEDULED_PROCESS_NOT_AUTOMATED")
        if (_money(cfg.get("daily_cost_cap_usd")) or 0) <= 0 or int(cfg.get("daily_soft_cap") or 0) <= 0:
            raise ProviderRefused("COST_CONFIGURATION_INVALID")
        policy = json.loads((root / "config/llm_routing_policy.json").read_text())
        row = policy["policies"][policy.get("default_policy_id", "default")]["processes"][process_id]
        if provider == "anthropic":
            credit = json.loads((root / "config/anthropic_credit_policy.json").read_text())
            if cfg.get("anthropic_first") is not True or process_id in credit.get("excluded_processes", {}):
                raise ProviderRefused("ASK_PRIMARY_ROUTE_NOT_ANTHROPIC")
            model = str(credit["models"]["standard"])
            if not model.startswith("claude-opus-"):
                raise ProviderRefused("ASK_PRIMARY_MODEL_NOT_OPUS")
            return model
        # Independent critics must never enter the promotional overlay or walk
        # another provider's route. Merely checking the returned label is too late.
        if cfg.get("anthropic_first") is True or row.get("transport_failover") is True:
            raise ProviderRefused("CRITIQUE_ROUTE_NOT_PINNED")
        if (row.get("primary") or {}).get("provider") != provider:
            raise ProviderRefused("CRITIQUE_ROUTE_NOT_PINNED")
        if provider not in set(cfg.get("allowed_lanes") or []) and provider != "deepseek":
            raise ProviderRefused("CRITIQUE_ROUTE_NOT_PINNED")
        if provider == "deepseek":
            # Read the immutable model binding without importing the registry's
            # optional pricing/consumption capability graph into this lane.
            models = json.loads((root / "config/llm_model_registry.json").read_text())
            binding = models["logical_policies"][str(row["primary"].get("policy") or "FAST")]
            model = models["providers"]["deepseek"]["models"][binding["model"]]["model_id"]
            if binding["provider"] != "deepseek" or not isinstance(model, str) or not model:
                raise ProviderRefused("CRITIQUE_ROUTE_NOT_PINNED")
            return model
        return None  # OAuth reports its actual served model in the response.
    except ProviderRefused:
        raise
    except (OSError, ValueError, KeyError, TypeError, AttributeError, StopIteration) as exc:
        raise ProviderRefused("ASK_ROUTE_CONFIGURATION_UNAVAILABLE") from exc


def _response_evidence(response: Mapping[str, Any], *, process_id: str, request_id: str) -> dict[str, Any]:
    meta = response.get("_tradeai") or {}
    provider = str(meta.get("provider") or "")
    raw_cost = meta.get("cost_estimate")
    actual = _money(raw_cost)
    error = response.get("error") if isinstance(response.get("error"), Mapping) else {}
    receipts = meta.get("route_receipts") or error.get("route_receipts") or []
    ambiguous = any(
        r.get("possibly_billable") is True
        and r.get("cost_basis") in {"possibly_billable_unknown", "possibly_billable_attempt"}
        for r in receipts
        if isinstance(r, dict)
    )
    ambiguous = ambiguous or meta.get("credit_usage_unknown") is True
    # A pinned OAuth subscription has no metered USD component. A mixed/paid
    # fallback cannot qualify for this zero-cost observation.
    free = provider in {"grok", "chatgpt"} and meta.get("cost_basis") == "free_oauth_unmetered"
    if free and not ambiguous:
        actual = Decimal(0)
    return {
        "provider": provider or None,
        "model": response.get("model"),
        "process_id": meta.get("process_id") or process_id,
        "request_id": meta.get("request_id") or request_id,
        "provider_request_id": meta.get("provider_request_id"),
        "reservation_id": meta.get("reservation_id")
        or error.get("reservation_id")
        or (response.get("routing_decision") or {}).get("reservation_id"),
        "mock": meta.get("mock"),
        "governance_pass": meta.get("governance_pass"),
        "actual_cost_usd": float(actual) if actual is not None else None,
        "cost_usage_known": actual is not None and not ambiguous,
        "request_sent": True,
        "route_receipts": receipts,
    }


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _native_bridge_call(
    messages: list[dict],
    *,
    process_id: str,
    caller: str,
    task_type: str,
    request_id: str,
    timeout_s: float,
    max_tokens: int,
    manual_trigger: bool,
    budget: dict | None,
) -> dict:
    """Small native client; fixed loopback origin, no credentials/provider imports.

    The authenticated server mapping chooses the process/provider. This client
    never sends process/model choices or widens server-owned budgets.
    """
    from .governed_process_routes import MANUAL_TRIGGER_HEADER, OPERATOR_INTENT_PROCESS_IDS
    from .intelligence_context import current_context_id

    if process_id in OPERATOR_INTENT_PROCESS_IDS and manual_trigger is not True:
        return {"error": {"code": "MANUAL_TRIGGER_REQUIRED"}}
    headers = {"Content-Type": "application/json", "X-TradeAI-Agent": caller, "X-TradeAI-Task-Type": task_type}
    if manual_trigger and process_id in OPERATOR_INTENT_PROCESS_IDS:
        headers[MANUAL_TRIGGER_HEADER] = "1"
    context = current_context_id()
    if context is not None:
        if (
            not isinstance(context, str)
            or not 0 < len(context) <= 256
            or any(ord(c) < 33 or ord(c) > 126 for c in context)
        ):
            return {"error": {"code": "MEMORY_CONTEXT_INVALID"}}
        headers["X-TradeAI-Context-Id"] = context
    payload = {
        "model": "tradeai_governed",
        "messages": messages,
        "request_id": request_id,
        "response_format": {"type": "json_object"},
        "max_tokens": max_tokens,
    }
    if budget is not None:
        payload["budget"] = budget
    request = Request(
        "http://127.0.0.1:8766/v1/chat/completions", data=json.dumps(payload).encode(), headers=headers, method="POST"
    )
    try:
        with build_opener(_NoRedirect()).open(request, timeout=timeout_s) as reply:
            return json.loads(reply.read(4_000_001).decode())
    except HTTPError as exc:
        try:
            return json.loads(exc.read(4_000_001).decode())
        except (ValueError, OSError):
            return {"error": {"code": "PROVIDER_HTTP_ERROR"}}
    except (URLError, TimeoutError, OSError):
        return {"error": {"code": "PROVIDER_TIMEOUT"}}


def call_role(
    prompt: str,
    *,
    role: str,
    process_id: str,
    manual_trigger: bool,
    ceiling_usd: float,
    max_tokens: int = 1500,
    root: Path = ROOT,
    bridge_call: Callable[..., dict] | None = None,
    request_id: str | None = None,
) -> ProviderResult:
    if role not in {"primary", *CRITIQUE_PROCESSES}:
        raise ProviderRefused("ASK_ROLE_NOT_ALLOWED")
    if role == "primary":
        process_id = primary_process(process_id, manual_trigger=manual_trigger)
        provider = "anthropic"
    else:
        provider = role
        if process_id != CRITIQUE_PROCESSES[provider]:
            raise ProviderRefused("CRITIQUE_PROCESS_NOT_ALLOWED")
        if manual_trigger:
            raise ProviderRefused("CRITIQUE_MANUAL_TRIGGER_FORBIDDEN")
    cap = _money(ceiling_usd)
    if cap is None or (cap <= 0 and provider not in {"grok", "chatgpt"}):
        raise ProviderRefused("PER_QUESTION_CAP_EXCEEDED")
    single = os.environ.get("TRADEAI_LLM_PROCESS_ID")
    multiple = os.environ.get("TRADEAI_LLM_PROCESS_IDS")
    bound = (
        {single}
        if single is not None
        else ({p.strip() for p in multiple.split(",") if p.strip()} if multiple is not None else None)
    )
    if bound is not None and process_id not in bound:
        raise ProviderRefused("PROCESS_ROUTE_NOT_BOUND")
    expected_model = _configuration(process_id, provider, Path(root))
    from .governed_process_routes import route_for_process

    route = route_for_process(process_id)
    if route is None:
        raise ProviderRefused("PROCESS_ROUTE_NOT_REGISTERED")
    if bridge_call is None:
        bridge_call = _native_bridge_call
    rid = request_id or "ask-role-" + uuid.uuid4().hex
    instructions = (
        "You are the primary CIO researcher. "
        if role == "primary"
        else "You are an independent "
        + provider
        + " critic. Challenge unsupported assumptions; preserve disagreement. "
    )
    try:
        response = bridge_call(
            [{"role": "user", "content": instructions + prompt}],
            process_id=process_id,
            caller=route[0],
            task_type=route[1],
            request_id=rid,
            timeout_s=90,
            max_tokens=max_tokens,
            manual_trigger=manual_trigger,
            budget={"cost_ceiling_usd": float(cap)} if cap > 0 else None,
        )
    except Exception as exc:
        raise ProviderRefused(
            "BRIDGE_RESPONSE_UNKNOWN",
            evidence={
                "provider": provider,
                "process_id": process_id,
                "request_id": rid,
                "actual_cost_usd": None,
                "cost_usage_known": False,
                "request_sent": True,
            },
        ) from exc
    if not isinstance(response, Mapping):
        raise ProviderRefused(
            "BRIDGE_RESPONSE_UNKNOWN",
            evidence={"actual_cost_usd": None, "cost_usage_known": False, "request_sent": True},
        )
    evidence = _response_evidence(response, process_id=process_id, request_id=rid)
    if response.get("error"):
        error = response["error"]
        code = str(error.get("code") or "BRIDGE_REFUSED")
        billed = _money(error.get("billed_cost_estimate"))
        if billed is not None:
            evidence.update(actual_cost_usd=float(billed), cost_usage_known=True)
        elif not evidence["route_receipts"] and code in {
            "PROCESS_NOT_REGISTERED",
            "POLICY_NOT_ALLOWED",
            "COST_CAP_EXCEEDED",
            "COST_CEILING_EXCEEDED",
            "COST_CONFIGURATION_INVALID",
            "MANUAL_TRIGGER_REQUIRED",
            "GOVERNANCE_UNAVAILABLE",
            "PROCESS_ROUTE_NOT_REGISTERED",
            "BRIDGE_BUSY",
            "EGRESS_POLICY_UNAVAILABLE",
            "MEMORY_CONTEXT_INVALID",
        }:
            evidence.update(actual_cost_usd=0.0, cost_usage_known=True, request_sent=False)
        raise ProviderRefused(code, evidence=evidence)
    meta = response.get("_tradeai") or {}
    if (
        meta.get("governance_pass") is not True
        or meta.get("mock") is not False
        or meta.get("process_id") != process_id
        or meta.get("request_id") != rid
        or not meta.get("reservation_id")
        or evidence["provider"] != provider
        or not isinstance(evidence["model"], str)
        or not evidence["model"]
        or (expected_model is not None and evidence["model"] != expected_model)
    ):
        raise ProviderRefused("PROVIDER_IDENTITY_NOT_PROVEN", evidence=evidence)
    try:
        text = response["choices"][0]["message"]["content"]
        if not isinstance(text, str) or not text.strip():
            raise ValueError("empty")
    except (KeyError, TypeError, IndexError, ValueError) as exc:
        raise ProviderRefused("OUTPUT_INVALID", evidence=evidence) from exc
    return ProviderResult(text=text, evidence=evidence)
