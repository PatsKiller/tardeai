"""Canonical LLM model registry loader.

Logical policies (FAST, FAST_THINK, PRO, PRO_THINK, PRO_MAX) are separate from
exact provider model IDs. Unknown policies and legacy model IDs fail closed.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[2]
_REGISTRY_PATH = _ROOT / "config" / "llm_model_registry.json"

# Exact DeepSeek V4 IDs verified via live GET /v1/models on 2026-08-03
EXACT_DEEPSEEK_MODELS = frozenset({"deepseek-v4-flash", "deepseek-v4-pro"})
LEGACY_DEEPSEEK_MODELS = frozenset({"deepseek-chat", "deepseek-reasoner"})
LOGICAL_POLICIES = frozenset({"FAST", "FAST_THINK", "PRO", "PRO_THINK", "PRO_MAX"})


class RegistryError(ValueError):
    """Invalid registry content or unknown policy/model."""


@lru_cache(maxsize=1)
def load_registry(path: str | None = None) -> dict[str, Any]:
    p = Path(path) if path else _REGISTRY_PATH
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "providers" not in data or "logical_policies" not in data:
        raise RegistryError("llm_model_registry.json missing providers/logical_policies")
    return data


def clear_registry_cache() -> None:
    load_registry.cache_clear()


def resolve_logical_policy(policy: str, *, operator_confirmed: bool = False) -> dict[str, Any]:
    """Map logical policy → exact provider binding.

    Returns dict with keys:
      requested_policy, provider, model_key, model_id, thinking, reasoning_effort,
      requires_operator_cost_confirmation
    """
    pol = (policy or "").strip().upper()
    reg = load_registry()
    policies = reg.get("logical_policies") or {}
    if pol not in policies:
        raise RegistryError(f"unknown logical policy: {policy!r}")
    spec = policies[pol]
    provider_name = spec["provider"]
    model_key = spec["model"]
    provider = (reg.get("providers") or {}).get(provider_name) or {}
    if provider.get("kill_switch") or not provider.get("enabled", True):
        raise RegistryError(f"provider disabled: {provider_name}")
    model = (provider.get("models") or {}).get(model_key) or {}
    if not model.get("enabled", True):
        raise RegistryError(f"model disabled: {model_key}")
    model_id = model.get("model_id")
    if model_id not in EXACT_DEEPSEEK_MODELS:
        raise RegistryError(f"registry model_id not an exact verified V4 id: {model_id!r}")
    requires = bool(spec.get("requires_operator_cost_confirmation"))
    if requires and not operator_confirmed:
        raise RegistryError(f"policy {pol} requires operator cost confirmation")
    thinking = spec.get("thinking") or "disabled"
    effort = spec.get("reasoning_effort")
    if thinking == "enabled":
        allowed = set(model.get("allowed_reasoning_effort") or [])
        if effort and allowed and effort not in allowed:
            raise RegistryError(f"reasoning_effort {effort!r} not allowed for {model_id}")
    return {
        "requested_policy": pol,
        "provider": provider_name,
        "model_key": model_key,
        "model_id": model_id,
        "thinking": thinking,
        "reasoning_effort": effort if thinking == "enabled" else None,
        "requires_operator_cost_confirmation": requires,
        "base_url": provider.get("base_url") or "https://api.deepseek.com",
        "auth_env": provider.get("auth_env") or "DEEPSEEK_API_KEY",
        "legacy_auth_env": provider.get("legacy_auth_env") or "deepseek_tradeai",
        "display_name": model.get("display_name") or model_id,
        "pricing": model.get("pricing_snapshot_usd_per_million_tokens") or {},
        "pricing_effective_at": model.get("pricing_effective_at"),
        "max_output_tokens": model.get("max_output_tokens"),
    }


def resolve_lane_alias(lane: str) -> str | None:
    """Map legacy UI/API lane strings to logical policies. Returns None if not a DeepSeek lane."""
    lane = (lane or "").strip().lower()
    # Prefer exact logical policy names passed as lane
    if lane.upper() in LOGICAL_POLICIES:
        return lane.upper()
    reg = load_registry()
    aliases = ((reg.get("providers") or {}).get("deepseek") or {}).get("legacy_lane_aliases") or {}
    if lane in aliases:
        return str(aliases[lane]).upper()
    # New explicit lane names
    mapping = {
        "deepseek-v4-flash": "FAST",
        "deepseek-v4-pro": "PRO_THINK",
        "deepseek-flash": "FAST",
        "deepseek-v4": "PRO_THINK",  # historical ambiguous lane → Pro think (not legacy reasoner id)
    }
    return mapping.get(lane)


def reject_legacy_model_id(model_id: str) -> None:
    mid = (model_id or "").strip().lower()
    if mid in LEGACY_DEEPSEEK_MODELS:
        raise RegistryError(
            f"legacy DeepSeek model id rejected: {model_id!r}. "
            f"Use exact IDs only: {sorted(EXACT_DEEPSEEK_MODELS)}"
        )
    if mid and mid not in EXACT_DEEPSEEK_MODELS and mid.startswith("deepseek"):
        raise RegistryError(f"unknown DeepSeek model id: {model_id!r}")


def estimate_usd_cost(
    *,
    model_id: str,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    cache_hit_tokens: int | None = None,
    cache_miss_tokens: int | None = None,
) -> dict[str, Any]:
    """Estimate USD from registry price snapshot. Not billed actual unless provider-verified."""
    reject_legacy_model_id(model_id)
    reg = load_registry()
    pricing = None
    effective = None
    for prov in (reg.get("providers") or {}).values():
        for m in (prov.get("models") or {}).values():
            if m.get("model_id") == model_id:
                pricing = m.get("pricing_snapshot_usd_per_million_tokens") or {}
                effective = m.get("pricing_effective_at")
                break
        if pricing is not None:
            break
    if not pricing:
        return {
            "estimated_cost_usd": None,
            "cost_basis": "unavailable",
            "pricing_effective_at": None,
        }
    # Prefer explicit cache split; else treat all prompt as cache-miss
    hit = int(cache_hit_tokens or 0)
    miss = int(cache_miss_tokens if cache_miss_tokens is not None else (prompt_tokens or 0))
    out = int(completion_tokens or 0)
    usd = (
        hit / 1_000_000 * float(pricing.get("cache_hit_input") or 0)
        + miss / 1_000_000 * float(pricing.get("cache_miss_input") or 0)
        + out / 1_000_000 * float(pricing.get("output") or 0)
    )
    return {
        "estimated_cost_usd": round(usd, 8),
        "cost_basis": "provider_usage_x_registry_snapshot",
        "pricing_effective_at": effective,
        "tokens": {
            "cache_hit_input": hit,
            "cache_miss_input": miss,
            "output": out,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
        },
    }


def get_deepseek_api_key() -> tuple[str | None, str | None, bool]:
    """Return (key, env_name_used, used_legacy_name). Never logs the key."""
    reg = load_registry()
    ds = (reg.get("providers") or {}).get("deepseek") or {}
    primary = ds.get("auth_env") or "DEEPSEEK_API_KEY"
    legacy = ds.get("legacy_auth_env") or "deepseek_tradeai"
    if os.environ.get(primary, "").strip():
        return os.environ[primary].strip(), primary, False
    if os.environ.get(legacy, "").strip():
        return os.environ[legacy].strip(), legacy, True
    return None, None, False
