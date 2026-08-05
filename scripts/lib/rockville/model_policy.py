"""Server-authoritative Rockville model policies.

Frontend may display policy + provenance; must not duplicate routing rules.
Exact model IDs only — deepseek-v4 / deepseek-chat / deepseek-reasoner rejected.
"""
from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]
POLICY_PATH = PROJECT_ROOT / "config" / "rockville" / "ROCKVILLE_WATCH_CIO_MODEL_POLICY.json"

EXACT_FLASH = "deepseek-v4-flash"
EXACT_PRO = "deepseek-v4-pro"
EXACT_MODELS = frozenset({EXACT_FLASH, EXACT_PRO})

FORBIDDEN_MODELS = frozenset({
    "deepseek-v4",
    "deepseek-chat",
    "deepseek-reasoner",
    "deepseek",
    "deepseek-flash",
    "fast",
    "pro",
    "pro_think",
    "pro_max",
})

FORBIDDEN_FALLBACK_PROVIDERS = frozenset({
    "gemma", "ollama", "local", "grok", "xai", "chatgpt", "openai", "anthropic",
})


class PolicyId(str, Enum):
    WATCH_FAST = "WATCH_FAST"
    WATCH_FAST_THINK = "WATCH_FAST_THINK"
    CIO_DAILY_PRO = "CIO_DAILY_PRO"
    CIO_DEEP_REVIEW = "CIO_DEEP_REVIEW"


_CACHE: dict[str, Any] | None = None


def load_policy_file() -> dict[str, Any]:
    global _CACHE
    if _CACHE is None:
        _CACHE = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    return _CACHE


def get_policy(policy_id: str | PolicyId) -> dict[str, Any]:
    pid = policy_id.value if isinstance(policy_id, PolicyId) else str(policy_id)
    pol = load_policy_file()["policies"].get(pid)
    if not pol:
        raise KeyError(f"unknown Rockville policy: {pid}")
    out = dict(pol)
    out["policy_id"] = pid
    out["policy_version"] = load_policy_file()["policy_version"]
    return out


def validate_exact_model(model_id: str | None) -> str:
    """Reject ambiguous/legacy IDs. Returns canonical exact model."""
    mid = (model_id or "").strip().lower()
    if not mid:
        raise ValueError("MODEL_NOT_FOUND: empty model id")
    if mid in FORBIDDEN_MODELS or mid not in EXACT_MODELS:
        # map known exacts with case
        if mid in {EXACT_FLASH, EXACT_PRO}:
            return mid
        raise ValueError(
            f"MODEL_NOT_FOUND: ambiguous or forbidden model id {model_id!r}; "
            f"allowed exact: {sorted(EXACT_MODELS)}"
        )
    return mid


def resolve_policy(policy_id: str | PolicyId) -> dict[str, Any]:
    """Return resolved policy with exact model validated."""
    pol = get_policy(policy_id)
    model = validate_exact_model(pol.get("model"))
    pol["model"] = model
    if pol["provider"] != "deepseek":
        raise ValueError("AUTH_INVALID: Rockville scope allows deepseek only")
    return pol


def assert_no_silent_fallback(provider: str | None, model: str | None) -> None:
    p = (provider or "").strip().lower()
    if p in FORBIDDEN_FALLBACK_PROVIDERS:
        raise RuntimeError(
            f"no_silent_fallback: provider {provider!r} is forbidden in Rockville scope"
        )
    validate_exact_model(model)


def feature_flags() -> dict[str, bool]:
    flags = load_policy_file().get("feature_flags") or {}
    # Allow runtime override file
    override = PROJECT_ROOT / "data" / "runtime" / "rockville" / "feature_flags.json"
    if override.exists():
        try:
            flags = {**flags, **json.loads(override.read_text(encoding="utf-8"))}
        except Exception:
            pass
    return {k: bool(v) for k, v in flags.items()}
