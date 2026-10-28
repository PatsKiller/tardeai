"""Configured promotional routing and per-call funding context; no caller authority."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
from typing import Any

from .anthropic_credit import CreditBook, CreditDenied, amount
from .anthropic_transport import AnthropicTransport, load_policy


ROOT = Path(__file__).resolve().parents[2]
_CURRENT: ContextVar[Any] = ContextVar("anthropic_call_funding", default=None)


def anthropic_only(process_id: str, *, policy: dict | None = None) -> bool:
    """True for processes that must never leave the Anthropic credit lane."""
    policy = load_policy() if policy is None else policy
    return process_id in (policy.get("anthropic_only_processes") or {})


def eligible(process_id: str, cfg: dict[str, Any], *, policy: dict | None = None) -> bool:
    policy = load_policy() if policy is None else policy
    return bool(cfg.get("anthropic_first") is True
                and cfg.get("registered") is True and cfg.get("local_only") is not True
                and process_id not in policy.get("excluded_processes", {}))


def active(process_id: str, cfg: dict[str, Any], *, policy=None, env=None, now=None, root=None) -> bool:
    """Select the promotion only while it is usable; otherwise preserve the caller's original route.

    This is a read-only check. Reservation revalidates it atomically before dispatch.
    """
    try:
        policy = load_policy() if policy is None else policy
        if not eligible(process_id, cfg, policy=policy) or not credit_admitted(cfg):
            return False
        env = {"ANTHROPIC_API_KEY": bool(os.environ.get("ANTHROPIC_API_KEY"))} if env is None else env
        if policy.get("enabled") is not True or not policy.get("provider_enabled", True) or not env.get("ANTHROPIC_API_KEY"):
            return False
        return CreditBook(root or state_root(), policy).snapshot(now=now or datetime.now(timezone.utc))["status"] == "OK"
    except (OSError, RuntimeError, ValueError, TypeError, KeyError, AttributeError):
        return False


def credit_admitted(cfg: dict) -> bool:
    """Paid/promotional dispatch requires existing declared request and USD caps.

    A missing cap does not create paid authority and must not disable the caller's
    existing free-only route. Live DB cap overrides are resolved by the native gate.
    """
    try:
        return amount(cfg.get("daily_cost_cap_usd")) > 0 and int(cfg.get("daily_soft_cap")) > 0
    except (RuntimeError, ValueError, TypeError):
        return False


def tier_for(logical_policy: str, reasoning_tier: str = "standard", *, policy: dict | None = None, process_id: str | None = None) -> str:
    policy = load_policy() if policy is None else policy
    pinned = ((policy.get("process_tiers") or {}).get(process_id)
              or (policy.get("ops_process_tiers") or {}).get(process_id)) if process_id else None
    if pinned:
        # A declared per-process tier (e.g. prospectus long-form / premium) wins.
        return str(pinned)
    if str(logical_policy).upper() == "PRO_MAX":
        return "highest"
    if reasoning_tier == "high":
        return "high"
    if str(logical_policy).upper() == "FAST" and process_id in policy.get("bulk_processes", []):
        return "bulk"
    return policy["policy_tiers"][str(logical_policy).upper()]


def selected_policy(process_id: str, cfg: dict, resolution: dict, *, reasoning_tier: str | None = None, requested_policy: str | None = None) -> dict:
    root = json.loads((ROOT / "config/llm_routing_policy.json").read_text())
    row = root["policies"][root.get("default_policy_id", "default")]["processes"][process_id]
    name = str((row.get("primary") or {}).get("policy") or "FAST").upper()
    allowed = cfg.get("deepseek_allowed_policies") or []
    if requested_policy in allowed:
        name = requested_policy
    high = reasoning_tier == "high" or cfg.get("reasoning_tier") == "high"
    if high and "PRO_THINK" in allowed:
        name = "PRO_THINK"
    resolved = dict(resolution[name])
    tier = tier_for(name, "high" if high else "standard", process_id=process_id)
    policy = load_policy()
    resolved.update(provider="anthropic", model_id=policy["models"][tier], requested_policy=name,
                    credit_tier=tier, **{k: row[k] for k in ("cost_ceiling_usd", "latency_budget_ms", "health_gate") if k in row})
    resolved["routing_decision"] = {"policy_id": "default", "lane_chosen": "promotion",
                                     "provider": "anthropic", "requested_policy": name,
                                     "route_profile": "anthropic_promotional_first",
                                     "reason": "operator_promotional_credit", "health_snapshot": {"lanes": {}}}
    return resolved


def configured_plan(process_id: str, cfg: dict, selected: dict, *, enabled: set | frozenset,
                    model_for_provider, env=None, policy=None, now=None) -> list[dict]:
    policy = load_policy() if policy is None else policy
    env = {"ANTHROPIC_API_KEY": bool(os.environ.get("ANTHROPIC_API_KEY"))} if env is None else env
    logical = selected.get("requested_policy", "FAST")
    tier = selected.get("credit_tier") or tier_for(logical, process_id=process_id)
    now = now or datetime.now(timezone.utc)
    expiry = datetime.fromisoformat(policy["expires_at"].replace("Z", "+00:00"))
    plan = []
    for provider in policy["provider_order"]:
        skip = None
        if provider == "anthropic":
            model = policy["models"][tier]
            if policy.get("enabled") is not True or policy.get("provider_enabled", True) is not True:
                skip = "provider_disabled"
            elif not env.get("ANTHROPIC_API_KEY"):
                skip = "not_configured"
            elif now >= expiry:
                skip = "credit_expired"
            elif not credit_admitted(cfg):
                skip = "process_caps_not_admitted"
        else:
            model = model_for_provider(provider, logical)
            if process_id in (policy.get("anthropic_only_processes") or {}):
                # Operator rule: this job queues when the credit is unavailable; it never
                # falls to another (possibly paid) provider.
                skip = "anthropic_only_process"
            elif provider not in enabled:
                skip = "no_transport"
        # The promotional provider order is an overlay, not a permanent expansion of legacy lanes.
        plan.append({"lane": "promotion" if provider == "anthropic" else provider,
                     "provider": provider, "policy_name": logical, "model_id": model,
                     "thinking": selected.get("thinking", "disabled"),
                     "reasoning_effort": selected.get("reasoning_effort"), "credit_tier": tier, "skip": skip})
    return plan


def state_root() -> Path:
    # The real-layout proof's PROJECT_ROOT takes precedence over host discovery.
    supplied = os.environ.get("PROJECT_ROOT") or os.environ.get("TRADEAI_STATE_ROOT")
    if supplied:
        return Path(supplied)
    from .lane_registry import state_root as existing_state_root
    return existing_state_root()


class FundingContext:
    def __init__(self, process_id: str, cfg: dict, reservation_id: int, *, global_cap,
                 cost_ceiling: float | None, mode: str = "bridge"):
        self.process_id, self.cfg, self.reservation_id = process_id, cfg, reservation_id
        self.global_cap, self.cost_ceiling, self.mode = global_cap, cost_ceiling, mode
        self.credit_total = Decimal(0)
        self.paid_projection = Decimal(0)
        self.credit_unknown = False
        self.projected = Decimal(0)

    def reprice(self, credit: Decimal, paid: Decimal = Decimal(0)) -> None:
        from . import llm_consumption as lc
        total = credit + paid
        if self.cost_ceiling is not None and total > amount(self.cost_ceiling):
            raise RuntimeError("COST_CAP_EXCEEDED: call ceiling")
        funding = "mixed" if credit and paid else "paid" if paid else "anthropic_promotional_credit"
        lc.reprice_reservation(self.reservation_id, self.process_id, float(total),
                               process_config=self.cfg, global_cap=self.global_cap,
                               funding_source=funding, paid_component_usd=float(paid), credit_policy=load_policy())
        self.projected, self.paid_projection = total, paid

    def reserve_anthropic(self, projected: Decimal, _model: str) -> None:
        self.reprice(self.credit_total + projected)
        self.credit_total += projected
        self.credit_unknown = True

    def record_usage(self, model: str, usage: dict, actual: Decimal, provider_request_id: str | None) -> bool:
        from .provider_cost.emit import emit_cost_event
        event = emit_cost_event(
            provider="anthropic", model=model, process_id=self.process_id,
            request_id=provider_request_id, prompt_tokens=usage["input_tokens"],
            completion_tokens=usage["output_tokens"], cache_hit_tokens=usage.get("cache_read_input_tokens", 0),
            cache_miss_tokens=usage["input_tokens"],
            cache_creation_input_tokens=usage.get("cache_creation_input_tokens", 0),
            cache_creation_1h_tokens=(usage.get("cache_creation") or {}).get("ephemeral_1h_input_tokens", 0),
            batch=usage.get("batch") is True,
            request_sent=True, possibly_billable=False,
            source_process=self.process_id, source_service="anthropic_transport",
            reservation_id=str(self.reservation_id), path=state_root() / "data/runtime/provider_cost/events.jsonl")
        return bool(event)

    def record_attempt(self, model: str, code: str) -> bool:
        from .provider_cost.emit import emit_cost_event, OUTCOME_ATTEMPT
        return bool(emit_cost_event(provider="anthropic", model=model, outcome=OUTCOME_ATTEMPT,
            source_service="anthropic_transport", source_process=self.process_id,
            process_id=self.process_id, reservation_id=str(self.reservation_id),
            request_sent=True, possibly_billable=True, error_class=code,
            path=state_root() / "data/runtime/provider_cost/events.jsonl"))

    def finish_anthropic(self, actual: Decimal | None) -> None:
        if actual is not None:
            self.credit_total, self.credit_unknown = actual, False

    def failure_cost(self, *, paid_billable: bool) -> tuple[Decimal, Decimal]:
        """Settle confirmed/uncertain credit plus only a dispatched, possibly-billable paid attempt.

        The last authorization projection may have been released after 429/529 or refused before send.
        """
        paid = self.paid_projection if paid_billable else Decimal(0)
        return self.credit_total + paid, paid

    @staticmethod
    def record_fallback(reason: str) -> None:
        try:
            CreditBook(state_root(), load_policy()).record_fallback(reason, now=datetime.now(timezone.utc))
        except (OSError, RuntimeError, ValueError, TypeError, KeyError, AttributeError):
            pass  # Corrupt/unavailable credit must not prevent a governed free fallback.

    def authorize_candidate(self, candidate: dict) -> None:
        if candidate["provider"] == "anthropic":
            return
        paid = Decimal(0)
        if candidate["provider"] == "deepseek":
            from . import consumption_run_manual as crm
            from . import llm_consumption as lc
            worst = crm.projected_max_cost_usd(model_id=candidate["model_id"],
                                               max_input_tokens=self.cfg.get("max_input_tokens") or 32000,
                                               max_output_tokens=self.cfg.get("max_output_tokens") or 2048)
            paid = amount(lc.calibrated_projected_usd(self.process_id, worst)["projected_usd"])
        self.reprice(self.credit_total, paid)


@contextmanager
def funding_context(context: FundingContext):
    token = _CURRENT.set(context)
    try:
        yield context
    finally:
        _CURRENT.reset(token)


def current_funding() -> FundingContext | None:
    return _CURRENT.get()


def transport() -> AnthropicTransport:
    context = current_funding()
    if context is None:
        from .anthropic_transport import AnthropicError
        raise AnthropicError("GOVERNANCE_UNAVAILABLE")
    from .anthropic_transport import AnthropicError
    try:
        provider = json.loads((ROOT / "config/llm_model_registry.json").read_text())["providers"]["anthropic"]
        if provider.get("kill_switch") or provider.get("enabled") is not True:
            raise AnthropicError("PROVIDER_DISABLED")
        allowed_models = {row["model_id"] for row in provider["models"].values() if row.get("enabled") is True}
        book = CreditBook(state_root(), load_policy())
    except AnthropicError:
        raise
    except (CreditDenied, OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise AnthropicError(getattr(exc, "reason", "CREDIT_UNAVAILABLE")) from exc
    return AnthropicTransport(book=book, allowed_models=allowed_models,
                              reserve_process=context.reserve_anthropic,
                              record_usage=context.record_usage, record_attempt=context.record_attempt,
                              settle_process=context.finish_anthropic)


def generate_in_process(prompt: str, *, process_id: str, cfg: dict, options: dict):
    """Re-enter the native gate for each configured candidate; no manual/memory bypass."""
    from . import llm_consumption as lc
    from .anthropic_transport import AnthropicError
    from .bridge_oauth_transport import TransportError
    import time
    requested = options.pop("requested_policy", None)
    selected = selected_policy(process_id, cfg, {
        name: {"thinking": "enabled" if "THINK" in name or name == "PRO_MAX" else "disabled"}
        for name in ("FAST", "FAST_THINK", "PRO", "PRO_THINK", "PRO_MAX")
    }, requested_policy=requested)
    plan = configured_plan(process_id, cfg, selected, enabled={"anthropic", "grok", "chatgpt", "deepseek"},
                           model_for_provider=lambda provider, name: None)
    started, receipts = time.monotonic(), []
    last = None
    for candidate in plan:
        if candidate.get("skip"):
            receipts.append({"provider": candidate["provider"], "outcome": candidate["skip"]})
            continue
        remaining = float(options.get("timeout", 90)) - (time.monotonic() - started)
        if remaining <= 0:
            raise AnthropicError("DEADLINE_EXCEEDED")
        provider = candidate["provider"]
        call = dict(options, timeout=remaining, _anthropic_route=True, return_provenance=True)
        call["lane"] = candidate["policy_name"].lower() if provider == "deepseek" else provider
        call["policy"] = candidate["policy_name"] if provider == "deepseek" else None
        call["model"] = candidate["model_id"]
        call["metadata"] = dict(options.get("metadata") or {}, credit_tier=candidate["credit_tier"],
                                requested_policy=candidate["policy_name"])
        try:
            text, provenance = lc.gate_and_generate(prompt, process_id=process_id, **call)
            if not str(text or "").strip():
                raise AnthropicError("EMPTY_OUTPUT")
            if options.get("response_json") or options.get("output_schema_id"):
                try:
                    json.loads(text)
                except (ValueError, TypeError) as exc:
                    raise AnthropicError("OUTPUT_INVALID") from exc
            provenance.update(provider=provider, route_receipts=receipts + [{"provider": provider, "outcome": "ok"}],
                              fallback_used=bool(receipts))
            return (text, provenance) if options.get("return_provenance") else text
        except lc.ManualRequired:
            raise
        except (AnthropicError, TransportError) as exc:
            if getattr(exc, "code", "") in {"INPUT_LIMIT_EXCEEDED", "GOVERNANCE_UNAVAILABLE"}:
                raise
            if provider == "anthropic":
                FundingContext.record_fallback(getattr(exc, "code", "PROVIDER_UNAVAILABLE"))
            last = exc
            receipts.append({"provider": provider, "outcome": getattr(exc, "code", "provider_failure")})
        except RuntimeError as exc:
            if provider == "anthropic" and (isinstance(exc, CreditDenied) or str(exc).startswith((
                    "CREDIT_", "COST_CAP_EXCEEDED", "COST_CEILING_EXCEEDED", "COST_CONFIGURATION_INVALID",
                    "COST_PERSISTENCE_UNAVAILABLE", "ANTHROPIC_"))):
                code = getattr(exc, "reason", None) or str(exc).split(":", 1)[0]
                FundingContext.record_fallback(code)
                last = exc
                receipts.append({"provider": provider, "outcome": code})
                continue
            # Only the named OAuth-unavailable condition is a provider refusal.
            # Registration, memory, output and paid authority refusals remain terminal.
            if provider in {"grok", "chatgpt"} and "OAuth lane unavailable" in str(exc):
                last = exc
                receipts.append({"provider": provider, "outcome": "not_available"})
                continue
            raise
    raise last or AnthropicError("NO_ROUTE_AVAILABLE")
