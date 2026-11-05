"""Anthropic Messages/Batch transport with injected HTTP and credit authorization.

Provider output and keys never enter the authorization journal. HTTP errors are
reported by stable codes, not by echoing vendor bodies, headers or prompt text.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from functools import wraps
from decimal import Decimal
import json
import os
import re
from pathlib import Path
import time
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .anthropic_credit import CreditBook, CreditDenied, amount


ROOT = Path(__file__).resolve().parents[2]
POLICY_REL = "config/anthropic_credit_policy.json"


class AnthropicError(RuntimeError):
    def __init__(self, code: str, *, status: int | None = None,
                 request_sent: bool = False, possibly_billable: bool = False):
        self.code = code
        self.http_status = status
        self.auth_failure = code == "AUTH_FAILURE"
        self.request_sent = request_sent
        self.possibly_billable = possibly_billable
        super().__init__("ANTHROPIC_" + code)


def load_policy(root: Path = ROOT) -> dict[str, Any]:
    policy = json.loads((Path(root) / POLICY_REL).read_text(encoding="utf-8"))
    registry = json.loads((Path(root) / "config/llm_model_registry.json").read_text(encoding="utf-8"))
    provider = registry["providers"]["anthropic"]
    policy["provider_enabled"] = provider.get("enabled") is True and not provider.get("kill_switch")
    return policy


def _count(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("invalid token count")
    return value


def price_usage(usage: dict[str, Any], prices: dict[str, Any], *, batch: bool = False) -> Decimal:
    """Price actual token classes; base input excludes cache reads and writes."""
    uncached, output = _count(usage["input_tokens"]), _count(usage["output_tokens"])
    read = _count(usage.get("cache_read_input_tokens", 0))
    created = _count(usage.get("cache_creation_input_tokens", 0))
    creation = usage.get("cache_creation") or {}
    five = _count(creation.get("ephemeral_5m_input_tokens", created))
    hour = _count(creation.get("ephemeral_1h_input_tokens", 0))
    if five + hour != created:
        raise ValueError("inconsistent cache creation usage")
    rates = prices
    if uncached + read + created > int(prices.get("long_context_threshold", 2**63 - 1)):
        rates = prices["long_context"]
    values = {"input": uncached, "output": output, "cache_read": read,
              "cache_write_5m": five, "cache_write_1h": hour}
    cost = sum((Decimal(n) * amount(rates[k]) for k, n in values.items()), Decimal(0)) / Decimal(1_000_000)
    return cost * amount(prices["batch_multiplier"]) if batch else cost


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # In particular never forward the API key to a redirect destination.
        return None


def _http(method: str, path: str, payload: dict | None, *, key: str, timeout: float) -> tuple[int, dict, dict]:
    # Fixed first-party origin. A provider body/redirect cannot select another host.
    data = json.dumps(payload).encode() if payload is not None else None
    request = Request("https://api.anthropic.com" + path, data=data, method=method,
                      headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                               "content-type": "application/json"})
    try:
        with build_opener(_NoRedirect()).open(request, timeout=timeout) as response:
            if not response.geturl().startswith("https://api.anthropic.com/"):
                raise AnthropicError("INVALID_ORIGIN", request_sent=True)
            raw = response.read(8_000_001)
            if len(raw) > 8_000_000:
                raise AnthropicError("RESPONSE_TOO_LARGE", request_sent=True, possibly_billable=True)
            body = {"results": [json.loads(line) for line in raw.splitlines() if line.strip()]} if path.endswith("/results") else json.loads(raw)
            return response.status, body, dict(response.headers)
    except HTTPError as exc:
        try:
            body = json.loads(exc.read(8192))
        except (ValueError, OSError):
            body = {}
        return exc.code, body, dict(exc.headers)
    except (URLError, TimeoutError, OSError) as exc:
        raise AnthropicError("TIMEOUT", request_sent=True, possibly_billable=True) from exc


def _failure(status: int, body: dict) -> str:
    if status == 429:
        return "RATE_LIMITED"
    if status == 529:
        return "OVERLOADED"
    error = body.get("error")
    error = error if isinstance(error, dict) else {}
    kind = str(error.get("type") or "").lower()
    message = str(error.get("message") or "").lower()
    if status == 402 or kind in {"billing_error", "insufficient_credit", "insufficient_quota"}:
        return "BILLING_ERROR"
    if status == 400 and ("credit balance" in message or "insufficient credits" in message):
        return "BILLING_ERROR"
    if status in (401, 403):
        return "AUTH_FAILURE"
    return "OVERLOADED" if status >= 500 or kind == "overloaded_error" else "INVALID_RESPONSE"


def _credit_refusals(method: Callable) -> Callable:
    """Keep journal/configuration refusals on the provider fallback contract."""
    @wraps(method)
    def call(*args, **kwargs):
        try:
            return method(*args, **kwargs)
        except CreditDenied as exc:
            raise AnthropicError(exc.reason) from exc
    return call


def _governance_code(exc: RuntimeError) -> str:
    code = getattr(exc, "reason", None) or str(exc).split(":", 1)[0].strip()
    return code if isinstance(code, str) and re.fullmatch(r"[A-Z][A-Z0-9_]*", code) else "GOVERNANCE_UNAVAILABLE"


def _reasoning_settings(model: str, thinking: str, policy: Mapping[str, Any]) -> dict[str, Any]:
    """Apply the current per-model controls in the verified policy snapshot.

    Opus 5.5 always uses adaptive thinking; ordinary calls use low effort.
    Haiku permits disabled thinking, and Sonnet uses between_tools for ordinary
    calls. Explicit THINK tiers use adaptive thinking with high effort.
    """
    enabled = thinking == "enabled"
    mode = "adaptive" if enabled or model == "claude-opus-5-5" else (
        "between_tools" if model == "claude-sonnet-5-5" else "disabled")
    settings = {"thinking": {"type": mode}, "output_config": {"effort": "high" if enabled else "low"}}
    try:
        configured = policy.get("thinking_controls", {}).get(model, {}).get("enabled" if enabled else "disabled")
        if configured is not None:
            if (not isinstance(configured, dict) or not isinstance(configured.get("output_config"), dict)
                    or not (isinstance(configured.get("thinking"), dict)
                            or ("thinking" in configured and configured["thinking"] is None))):
                raise AnthropicError("CREDIT_CONFIGURATION_INVALID")
            settings = deepcopy(configured)
        if model == "claude-opus-5-5":
            settings["thinking"] = {"type": "adaptive"}
        if settings.get("thinking") is None:
            # Always-on thinking (Fable 5.1): the parameter is omitted entirely;
            # any explicit disabled/budget configuration is a 400.
            settings.pop("thinking", None)
        return settings
    except (AttributeError, KeyError, TypeError) as exc:
        raise AnthropicError("CREDIT_CONFIGURATION_INVALID") from exc


class AnthropicTransport:
    def __init__(self, *, book: CreditBook, env: Mapping[str, str] | None = None,
                 request: Callable = _http, now: Callable = lambda: datetime.now(timezone.utc),
                 sleep: Callable = time.sleep, monotonic: Callable = time.monotonic,
                 record_usage: Callable | None = None, reserve_process: Callable | None = None,
                 settle_process: Callable | None = None, allowed_models: set[str] | None = None,
                 record_attempt: Callable | None = None):
        self.book, self.policy = book, book.policy
        self.env = {"ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY", "")} if env is None else env
        self.request, self.now, self.sleep, self.monotonic = request, now, sleep, monotonic
        self.record_usage, self.reserve_process = record_usage, reserve_process
        self.settle_process = settle_process
        self.allowed_models = allowed_models
        self.record_attempt = record_attempt

    def _unknown_attempt(self, payload: dict | None, code: str) -> None:
        model = (payload or {}).get("model")
        if not model:
            model = (((payload or {}).get("requests") or [{}])[0].get("params") or {}).get("model")
        try:
            recorded = self.record_attempt is not None and self.record_attempt(str(model or "unknown"), code) is True
        except Exception:
            recorded = False
        if not recorded:
            self.book.record_failure("accounting_unavailable", now=self.now())

    def _meter_usage(self, model: str, usage: dict, actual: Decimal, provider_id: str | None) -> None:
        try:
            recorded = self.record_usage is not None and self.record_usage(model, usage, actual, provider_id) is True
        except Exception:
            recorded = False
        if not recorded:
            self.book.record_failure("accounting_unavailable", now=self.now())
            raise AnthropicError("ACCOUNTING_UNAVAILABLE", request_sent=True, possibly_billable=True)

    def _send(self, method: str, path: str, payload: dict | None, *, deadline: float) -> tuple[dict, bool]:
        key = str(self.env.get("ANTHROPIC_API_KEY") or "").strip()
        if not key:
            raise AnthropicError("NOT_CONFIGURED")
        retry = self.policy.get("retry") or {}
        attempts = max(1, int(retry.get("max_attempts", 2)))
        ambiguous = False
        for number in range(attempts):
            remaining = deadline - self.monotonic()
            if remaining <= 0:
                raise AnthropicError("TIMEOUT", possibly_billable=ambiguous, request_sent=ambiguous)
            try:
                status, body, headers = self.request(method, path, payload, key=key, timeout=remaining)
            except AnthropicError as exc:
                self.book.record_failure("timeout" if exc.code == "TIMEOUT" else "invalid_response", now=self.now())
                billable = method == "POST" and path in {"/v1/messages", "/v1/messages/batches"}
                current_ambiguous = billable and exc.possibly_billable
                if current_ambiguous:
                    self._unknown_attempt(payload, exc.code)
                exc.possibly_billable = ambiguous or current_ambiguous
                exc.attempt_recorded = exc.possibly_billable
                raise
            except Exception as exc:
                # A malformed/aborted provider response can follow billable work.
                self.book.record_failure("invalid_response", now=self.now())
                billable = method == "POST" and path in {"/v1/messages", "/v1/messages/batches"}
                if billable:
                    self._unknown_attempt(payload, "INVALID_RESPONSE")
                failure = AnthropicError("INVALID_RESPONSE", request_sent=True, possibly_billable=billable)
                failure.attempt_recorded = billable
                raise failure from exc
            if not isinstance(body, dict) and not 200 <= status < 300:
                body = {}
            if not isinstance(body, dict):
                billable = method == "POST" and path in {"/v1/messages", "/v1/messages/batches"}
                if billable:
                    self._unknown_attempt(payload, "INVALID_RESPONSE")
                self.book.record_failure("invalid_response", now=self.now())
                failure = AnthropicError("INVALID_RESPONSE", request_sent=True, possibly_billable=billable)
                failure.attempt_recorded = billable
                raise failure
            if 200 <= status < 300:
                return body, ambiguous
            code = _failure(status, body)
            # 529 / overloaded_error and 429 are refused before generation: not billed,
            # so the hold is released. Other 5xx stay ambiguous (possibly billed).
            error = body.get("error")
            error = error if isinstance(error, dict) else {}
            overloaded = status == 529 or str(error.get("type") or "").lower() == "overloaded_error"
            if path in {"/v1/messages", "/v1/messages/batches"} and method == "POST" and status >= 500 and not overloaded:
                ambiguous = True
                self._unknown_attempt(payload, code)
            if code in {"BILLING_ERROR", "AUTH_FAILURE", "RATE_LIMITED", "OVERLOADED"}:
                self.book.record_failure(code.lower(), now=self.now())
            if code in {"RATE_LIMITED", "OVERLOADED"} and number + 1 < attempts:
                try:
                    delay = float(headers.get("retry-after", 0))
                except (AttributeError, TypeError, ValueError):
                    delay = 0
                delay = max(0, delay)
                if delay <= float(retry.get("max_delay_seconds", 2)) and delay < deadline - self.monotonic():
                    self.sleep(delay)
                    continue
            failure = AnthropicError(code, status=status, request_sent=True, possibly_billable=ambiguous)
            failure.attempt_recorded = ambiguous
            raise failure
        raise AnthropicError("INVALID_RESPONSE")

    def _prices(self, model: str) -> dict[str, Any]:
        if self.allowed_models is not None and model not in self.allowed_models:
            raise AnthropicError("MODEL_DISABLED")
        prices = (self.policy.get("pricing") or {}).get(model)
        if not prices:
            raise AnthropicError("PRICE_UNKNOWN")
        return prices

    def _tier(self, model: str) -> str:
        return next((tier for tier, value in self.policy.get("models", {}).items() if value == model), "standard")

    def _payload(self, messages: list[dict], model: str, max_tokens: int, thinking: str,
                 tools: list[dict] | None = None) -> dict[str, Any]:
        system, conversation = [], []
        for message in messages:
            role, content = message.get("role"), message.get("content")
            if not isinstance(content, str):
                raise AnthropicError("UNSUPPORTED_CONTENT")
            if role in {"system", "developer"}:
                system.append({"type": "text", "text": content})
            elif role in {"user", "assistant"}:
                conversation.append({"role": role, "content": content})
            else:
                raise AnthropicError("UNSUPPORTED_CONTENT")
        if not conversation:
            raise AnthropicError("EMPTY_MESSAGES")
        payload: dict[str, Any] = {"model": model, "max_tokens": max(1, int(max_tokens)), "messages": conversation}
        if system:
            system[-1]["cache_control"] = {"type": "ephemeral"}
            payload["system"] = system
        payload.update(_reasoning_settings(model, thinking, self.policy))
        if tools:
            # Server tools (e.g. Anthropic-hosted web_search) execute on Anthropic's side; the
            # response carries their result blocks. Only processes named in the credit policy's
            # tools_processes may reach this path (see generate()).
            payload["tools"] = list(tools)
        return payload

    @_credit_refusals
    def generate(self, messages: list[dict], model: str | None, *, max_tokens: int = 2048,
                 client_request_id: str, thinking: str = "disabled", tools: list | None = None,
                 deadline_s: float = 90, process_id: str = "unregistered", process_cap: Decimal | None = None,
                 cost_ceiling_usd: Decimal | None = None, credit_tier: str | None = None,
                 max_input_tokens: int | None = None, **_kwargs: Any) -> dict[str, Any]:
        if not self.env.get("ANTHROPIC_API_KEY"):
            raise AnthropicError("NOT_CONFIGURED")
        if self.record_usage is None or self.reserve_process is None or self.record_attempt is None:
            raise AnthropicError("GOVERNANCE_UNAVAILABLE")
        tools = list(tools or [])
        # Tools stay refused by default. The credit policy may name the only processes allowed a
        # tool-bearing call (2026-11-01: cio_ask_web_search for the hosted web_search tool); an
        # unreadable or absent list keeps every other process refused.
        if tools and process_id not in set(self.policy.get("tools_processes") or []):
            raise AnthropicError("TOOLS_UNSUPPORTED")
        model = str(model or "")
        premium = {self.policy.get("models", {}).get("premium")} - {None}
        if model in premium and process_id not in set(self.policy.get("premium_tier_processes") or []):
            # The premium model is approved for named processes only.
            raise AnthropicError("MODEL_DISABLED")
        if (credit_tier or self._tier(model)) == "highest" and _kwargs.get("operator_confirmed") is not True:
            raise AnthropicError("OPERATOR_CONFIRMATION_REQUIRED")
        if credit_tier and self.policy["models"].get(credit_tier) != model:
            raise AnthropicError("TIER_MODEL_MISMATCH")
        prices = self._prices(model)
        payload = self._payload(messages, model, max_tokens, thinking, tools=tools)
        deadline = self.monotonic() + max(0, float(deadline_s))
        try:
            status = self.book.snapshot(now=self.now())["status"]
        except CreditDenied as exc:
            raise AnthropicError(exc.reason) from exc
        if status != "OK":
            raise AnthropicError(status)
        token_payload = {k: v for k, v in payload.items() if k not in {"max_tokens", "output_config"}}
        count_response, _ = self._send("POST", "/v1/messages/count_tokens", token_payload, deadline=deadline)
        counted = _count(count_response["input_tokens"])
        if max_input_tokens is not None and counted > int(max_input_tokens):
            raise AnthropicError("INPUT_LIMIT_EXCEEDED")
        # Text byte length is a conservative additional bound; include configured
        # provider framing margin. All retries are reserved before generation.
        bounded_input = max(counted, len(json.dumps(payload, ensure_ascii=False).encode()))
        bounded_input += int(self.policy.get("input_framing_margin_tokens", 4096))
        maximum = {"input_tokens": 0, "output_tokens": max_tokens,
                   "cache_creation_input_tokens": bounded_input}
        per_attempt = price_usage(maximum, prices)
        projected = per_attempt * max(1, int(self.policy.get("retry", {}).get("max_attempts", 2)))
        if cost_ceiling_usd is not None and projected > amount(cost_ceiling_usd):
            raise AnthropicError("CALL_COST_CEILING")
        try:
            self.book.reserve(client_request_id, process_id, projected, tier=credit_tier or self._tier(model),
                              process_cap=process_cap, now=self.now())
        except CreditDenied as exc:
            raise AnthropicError(exc.reason) from exc
        result_received = request_started = False
        try:
            if self.reserve_process is not None:
                try:
                    self.reserve_process(projected, model)
                except AnthropicError:
                    raise
                except (CreditDenied, RuntimeError) as exc:
                    # DB backstop / process-cap / persistence refusal: nothing was sent;
                    # a typed refusal lets every caller fall through to a free lane.
                    raise AnthropicError(_governance_code(exc)) from exc
            request_started = True
            body, ambiguous = self._send("POST", "/v1/messages", payload, deadline=deadline)
            result_received = True
            if body.get("model") != model:
                raise AnthropicError("MODEL_MISMATCH", request_sent=True, possibly_billable=True)
            usage = body.get("usage")
            if not isinstance(usage, dict):
                raise AnthropicError("USAGE_UNKNOWN", request_sent=True, possibly_billable=True)
            actual = price_usage(usage, prices)
            self._meter_usage(model, usage, actual, body.get("id"))
            try:
                self.book.settle(client_request_id, None if ambiguous else actual, now=self.now())
            except CreditDenied as exc:
                # Over-reservation is booked at the real amount and pauses the book for
                # a bounded cooldown; the paid-for answer is still returned.
                if exc.reason != "CREDIT_OVER_RESERVATION":
                    failure = AnthropicError(exc.reason, request_sent=True, possibly_billable=True)
                    failure.attempt_recorded = True
                    raise failure from exc
            if self.settle_process is not None:
                self.settle_process(None if ambiguous else actual)
            prompt_total = usage["input_tokens"] + usage.get("cache_read_input_tokens", 0) + usage.get("cache_creation_input_tokens", 0)
            text = "".join(block.get("text", "") for block in body.get("content", [])
                           if block.get("type") == "text")
            if not text.strip() and body.get("stop_reason") in {"max_tokens", "refusal"}:
                # Settled above (the credit was spent); the answer is unusable, so the
                # caller falls through to the next lane.
                invalid = AnthropicError("OUTPUT_INVALID", request_sent=True, possibly_billable=False)
                invalid.attempt_recorded = True  # usage already recorded and settled
                raise invalid
            return {"id": body.get("id"), "model": model,
                    "choices": [{"message": {"role": "assistant", "content": text}, "finish_reason": body.get("stop_reason")}],
                    "usage": {"prompt_tokens": prompt_total, "completion_tokens": usage["output_tokens"],
                              "total_tokens": prompt_total + usage["output_tokens"],
                              "prompt_cache_hit_tokens": usage.get("cache_read_input_tokens", 0),
                              "prompt_cache_miss_tokens": usage["input_tokens"], "anthropic_usage": usage},
                    "_tradeai": {"provider": "anthropic", "requested_model_id": model, "returned_model": model,
                                 "estimated_cost_usd": None if ambiguous else float(actual),
                                 "cost_basis": "provider_usage_x_registry_snapshot",
                                 "credit_usage_unknown": ambiguous, "request_sent": True,
                                 "provider_request_id": body.get("id"), "funding_source": "anthropic_promotional_credit",
                                 # Raw provider blocks: a server tool's results (web_search_tool_result)
                                 # and citations are not representable in choices[].message.content.
                                 # Additive; every existing caller ignores it.
                                 "content_blocks": body.get("content")}}
        except BaseException as exc:
            actual = None if (result_received or getattr(exc, "possibly_billable", False)
                              or (request_started and not isinstance(exc, AnthropicError))) else Decimal(0)
            if actual is None and not getattr(exc, "attempt_recorded", False):
                self._unknown_attempt(payload, getattr(exc, "code", "INTERRUPTED"))
            self.book.settle(client_request_id, actual, now=self.now())
            if self.settle_process is not None:
                self.settle_process(actual)
            raise

    @_credit_refusals
    def submit_batch(self, messages: list[dict], model: str, *, client_request_id: str,
                     process_id: str, caller_allows_async: bool = False, max_tokens: int = 2048,
                     credit_tier: str = "bulk", max_input_tokens: int,
                     process_cap: Decimal, deadline_s: float = 90, effort: str | None = None) -> dict:
        """One explicitly asynchronous governed request; never changes a sync caller's contract.

        The caller retains its native reservation and polls this identity later. Pending
        authorization persists across worker restarts/expiry; no prompt/output is journaled.
        Multiple such requests can be coordinated by an asynchronous caller without letting
        a batch bypass the native per-request count or per-process authorizations.
        """
        if caller_allows_async is not True:
            raise AnthropicError("ASYNC_CALLER_REQUIRED")
        if not self.env.get("ANTHROPIC_API_KEY"):
            raise AnthropicError("NOT_CONFIGURED")
        if self.record_usage is None or self.reserve_process is None or self.record_attempt is None:
            raise AnthropicError("GOVERNANCE_UNAVAILABLE")
        batch_tiers = set(self.policy.get("batch_tiers") or ("bulk", "standard"))
        if credit_tier not in batch_tiers or self.policy["models"].get(credit_tier) != model:
            raise AnthropicError("BATCH_TIER_UNSUPPORTED")
        if effort is not None and effort not in {"low", "medium", "high"}:
            raise AnthropicError("BATCH_EFFORT_UNSUPPORTED")
        status=self.book.snapshot(now=self.now())["status"]
        if status!="OK":
            raise AnthropicError(status)
        prices=self._prices(model)
        payload=self._payload(messages,model,max_tokens,"disabled")
        if effort is not None:  # explicit per-caller effort (e.g. prospectus Watch: medium); thinking stays as configured
            payload["output_config"]=dict(payload.get("output_config") or {},effort=effort)
        deadline=self.monotonic()+deadline_s
        count,_=self._send("POST","/v1/messages/count_tokens",{k:v for k,v in payload.items() if k not in {"max_tokens","output_config"}},deadline=deadline)
        if _count(count["input_tokens"]) > max_input_tokens:
            raise AnthropicError("INPUT_LIMIT_EXCEEDED")
        bounded=max(count["input_tokens"],len(json.dumps(payload,ensure_ascii=False).encode()))+int(self.policy["input_framing_margin_tokens"])
        projected=price_usage({"input_tokens":0,"cache_creation_input_tokens":bounded,"output_tokens":max_tokens},prices,batch=True)
        projected*=int(self.policy["retry"]["max_attempts"])
        try:
            self.book.reserve(client_request_id,process_id,projected,tier=credit_tier,now=self.now(),process_cap=process_cap)
        except CreditDenied as exc:
            raise AnthropicError(exc.reason) from exc
        sent=result_received=False
        try:
            try:
                self.reserve_process(projected,model)
            except AnthropicError:
                raise
            except (CreditDenied, RuntimeError) as exc:
                raise AnthropicError(_governance_code(exc)) from exc
            custom=self.book._key(client_request_id)
            sent=True
            result,ambiguous=self._send("POST","/v1/messages/batches",{"requests":[{"custom_id":custom,"params":payload}]},deadline=deadline)
            result_received=True
            batch_id=result.get("id","")
            if not re.fullmatch(r"msgbatch_[A-Za-z0-9_-]+",batch_id):
                raise AnthropicError("INVALID_BATCH_ID",request_sent=True,possibly_billable=True)
            with self.book._locked():
                rows=self.book._read()
                self.book._append(rows,"batch",self.now(),request=custom,batch_id=batch_id,
                                  model=model,process_id=process_id,ambiguous=ambiguous)
            return {"batch_id":batch_id,"client_request_id":client_request_id,"status":"PENDING",
                    "provider":"anthropic","promotional_hold_usd":str(projected)}
        except BaseException as exc:
            actual = None if (result_received or getattr(exc, "possibly_billable", False)
                              or (sent and not isinstance(exc, AnthropicError))) else Decimal(0)
            if actual is None and not getattr(exc, "attempt_recorded", False):
                self._unknown_attempt(payload, getattr(exc, "code", "INTERRUPTED"))
            self.book.settle(client_request_id,actual,now=self.now())
            if self.settle_process is not None:
                self.settle_process(actual)
            raise

    @_credit_refusals
    def collect_batch(self, batch_id: str, *, client_request_id: str, process_id: str,
                      deadline_s: float = 90) -> dict:
        """Poll/read an admitted batch. Pending/unknown results retain the entire hold."""
        if not re.fullmatch(r"msgbatch_[A-Za-z0-9_-]+",batch_id):
            raise AnthropicError("INVALID_BATCH_ID")
        if self.record_usage is None or self.reserve_process is None or self.record_attempt is None:
            raise AnthropicError("GOVERNANCE_UNAVAILABLE")
        try:
            with self.book._locked():
                rows=self.book._read()
                admitted=[r for r in self.book._own(rows) if r["event"]=="batch" and r.get("request")==self.book._key(client_request_id)
                          and r.get("batch_id")==batch_id and r.get("process_id")==process_id]
                prior=self.book._requests(rows).get(self.book._key(client_request_id)) or {}
                collection=[r for r in self.book._own(rows) if r["event"] in {"batch_collection_started", "batch_collected"}
                            and r.get("request")==self.book._key(client_request_id)]
        except CreditDenied as exc:
            raise AnthropicError(exc.reason) from exc
        if len(admitted)!=1:
            raise AnthropicError("BATCH_NOT_ADMITTED")
        entry=admitted[0]
        if prior.get("status")=="settled" or (collection and collection[-1]["event"]=="batch_collected"):
            return {"batch_id":batch_id,"status":"ALREADY_COLLECTED",
                    "cost_usd":collection[-1]["actual"] if collection and collection[-1]["event"]=="batch_collected" else prior.get("actual"),
                    "requires_native_output_validation":True}
        if collection:
            raise AnthropicError("BATCH_COLLECTION_UNCERTAIN", request_sent=True, possibly_billable=True)
        deadline=self.monotonic()+deadline_s
        state,_=self._send("GET","/v1/messages/batches/"+batch_id,None,deadline=deadline)
        if state.get("processing_status")!="ended":
            return {"batch_id":batch_id,"status":"PENDING"}
        result,_=self._send("GET","/v1/messages/batches/"+batch_id+"/results",None,deadline=deadline)
        matching=[r for r in result.get("results",[]) if r.get("custom_id")==entry["request"]]
        if len(matching)!=1 or matching[0].get("result",{}).get("type")!="succeeded":
            raise AnthropicError("BATCH_RESULT_UNAVAILABLE",request_sent=True,possibly_billable=True)
        body=matching[0]["result"]["message"]
        if body.get("model")!=entry["model"]:
            raise AnthropicError("MODEL_MISMATCH",request_sent=True,possibly_billable=True)
        usage=body["usage"]
        cost=price_usage(usage,self._prices(entry["model"]),batch=True)
        # Persist the collection claim before the external ledger write. Concurrent
        # collectors and a restart after an uncertain write never emit a second row.
        # An interrupted claim retains its total hold and requires reconciliation.
        with self.book._locked():
            rows=self.book._read()
            collection=[r for r in self.book._own(rows) if r["event"] in {"batch_collection_started", "batch_collected"}
                        and r.get("request")==entry["request"]]
            prior=self.book._requests(rows).get(entry["request"]) or {}
            if prior.get("status")=="settled" or (collection and collection[-1]["event"]=="batch_collected"):
                return {"batch_id":batch_id,"status":"ALREADY_COLLECTED",
                        "cost_usd":collection[-1]["actual"] if collection and collection[-1]["event"]=="batch_collected" else prior.get("actual"),
                        "requires_native_output_validation":True}
            if collection:
                raise AnthropicError("BATCH_COLLECTION_UNCERTAIN", request_sent=True, possibly_billable=True)
            self.book._append(rows,"batch_collection_started",self.now(),request=entry["request"],batch_id=batch_id)
        self._meter_usage(entry["model"],dict(usage,batch=True),cost,body.get("id"))
        try:
            self.book.settle(client_request_id,None if entry["ambiguous"] else cost,now=self.now())
        except CreditDenied as exc:
            if exc.reason!="CREDIT_OVER_RESERVATION":
                raise AnthropicError(exc.reason,request_sent=True,possibly_billable=True) from exc
        with self.book._locked():
            self.book._append(self.book._read(),"batch_collected",self.now(),request=entry["request"],
                              batch_id=batch_id,actual=str(cost))
        if self.settle_process is not None:
            self.settle_process(None if entry["ambiguous"] else cost)
        return {"batch_id":batch_id,"status":"SUCCEEDED","message":body,"cost_usd":str(cost),
                "requires_native_output_validation":True}
