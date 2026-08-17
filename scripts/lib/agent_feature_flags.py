"""agent_feature_flags.py — canonical feature flags + activation scope (Phase 12).

READ_ONLY_ADVISORY. This is the single source of truth for how the Agent
Intelligence Foundation turns its capabilities *on*. Every flag defaults to its
most conservative value (0 / "null") and is read from the environment so a
release can be staged without a code change:

  AGENT_CONTEXT_ENVELOPE      — ContextEnvelope@v1 enrichment      (default 0)
  AGENT_RUN_TRACE             — AgentRunTrace@v1 JSONL lineage     (default 0)
  MCP_READ_ONLY_GATEWAY       — read-only MCP context path         (default 0)
  MEMORY_PROVIDER             — "null" | "local" | "mem0"          (default "null")
  MEMORY_SHADOW               — record memory, never influence     (default 0)
  MEMORY_BEHAVIOR_INFLUENCE   — memory may shape advisory context  (default 0)
  LANGGRAPH_WORKER_PILOT      — LangGraph durable-workflow pilot   (default 0)

Activation is *advisory-context only*. This module documents — and can enforce
via `activation_scope_check()` — the ONLY effects that may ever be switched on,
and the effects that are structurally forbidden. It never grants broker/order/
stop/2FA/risk-policy authority, never authorizes MCP writes, LangGraph broker
authority, or learning auto-promotion.

No network, no secrets, no side effects. Deterministic only.
"""
from __future__ import annotations

import os
from typing import Any, Optional

# ── Conservative defaults ──────────────────────────────────────────────────

DEFAULT_AGENT_CONTEXT_ENVELOPE = 0
DEFAULT_AGENT_RUN_TRACE = 0
DEFAULT_MCP_READ_ONLY_GATEWAY = 0
DEFAULT_MEMORY_PROVIDER = "null"
DEFAULT_MEMORY_SHADOW = 0
DEFAULT_MEMORY_BEHAVIOR_INFLUENCE = 0
DEFAULT_LANGGRAPH_WORKER_PILOT = 0

#: Every environment-driven integer/boolean flag, in canonical order.
INT_FLAG_NAMES: tuple[str, ...] = (
    "AGENT_CONTEXT_ENVELOPE",
    "AGENT_RUN_TRACE",
    "MCP_READ_ONLY_GATEWAY",
    "MEMORY_SHADOW",
    "MEMORY_BEHAVIOR_INFLUENCE",
    "LANGGRAPH_WORKER_PILOT",
)

#: The only memory-provider values this program accepts. Anything else fails
#: closed to "null" so a typo can never silently select a live backend.
ALLOWED_MEMORY_PROVIDERS = frozenset({"mem0", "local", "null"})

#: Canonical conservative config. This is both the default and the rollback set:
#: every capability off, memory provider null.
DEFAULT_FLAGS: dict[str, Any] = {
    "AGENT_CONTEXT_ENVELOPE": DEFAULT_AGENT_CONTEXT_ENVELOPE,
    "AGENT_RUN_TRACE": DEFAULT_AGENT_RUN_TRACE,
    "MCP_READ_ONLY_GATEWAY": DEFAULT_MCP_READ_ONLY_GATEWAY,
    "MEMORY_PROVIDER": DEFAULT_MEMORY_PROVIDER,
    "MEMORY_SHADOW": DEFAULT_MEMORY_SHADOW,
    "MEMORY_BEHAVIOR_INFLUENCE": DEFAULT_MEMORY_BEHAVIOR_INFLUENCE,
    "LANGGRAPH_WORKER_PILOT": DEFAULT_LANGGRAPH_WORKER_PILOT,
}

_TRUTHY = frozenset({"1", "true", "t", "yes", "y", "on"})
_FALSY = frozenset({"0", "false", "f", "no", "n", "off", ""})


def _coerce_int_flag(value: Any) -> int:
    """Coerce a flag value to a conservative 0/1 integer.

    Accepts bools, ints, floats, and common string spellings; any value that is
    not unambiguously truthy fails closed to 0.
    """
    if value is None:
        return 0
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, (int, float)):
        return 1 if value else 0
    s = str(value).strip().lower()
    if s in _TRUTHY:
        return 1
    if s in _FALSY:
        return 0
    try:
        return 1 if int(float(s)) else 0
    except (TypeError, ValueError):
        return 0


def _coerce_provider(value: Any) -> str:
    """Normalize MEMORY_PROVIDER; anything outside the allowlist fails to null."""
    if value is None:
        return "null"
    s = str(value).strip().lower()
    if s not in ALLOWED_MEMORY_PROVIDERS:
        return "null"
    return s


def load_feature_flags(env: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Read the canonical flags from ``env`` (or ``os.environ``) with fallback.

    Integer/boolean flags are coerced to 0/1. ``MEMORY_PROVIDER`` is validated
    against the allowlist and any invalid value falls back to ``"null"``. The
    input ``env`` mapping is never mutated.
    """
    src: Any = os.environ if env is None else env

    flags: dict[str, Any] = {}
    for name in INT_FLAG_NAMES:
        raw = src.get(name) if hasattr(src, "get") else None
        if raw is None:
            flags[name] = DEFAULT_FLAGS[name]
        else:
            flags[name] = _coerce_int_flag(raw)

    raw_provider = src.get("MEMORY_PROVIDER") if hasattr(src, "get") else None
    if raw_provider is None:
        flags["MEMORY_PROVIDER"] = DEFAULT_FLAGS["MEMORY_PROVIDER"]
    else:
        flags["MEMORY_PROVIDER"] = _coerce_provider(raw_provider)

    return flags


def rollback_flags() -> dict[str, Any]:
    """Return the conservative rollback config.

    Turns off every behavior-affecting capability (memory behavior influence,
    read-only MCP gateway, memory provider, LangGraph pilot) and leaves
    observability-only flags at their conservative default. This config MUST NOT
    break core CIO decisions: with memory influence off and the provider null,
    the advisory path degrades to its pre-activation behavior.
    """
    return dict(DEFAULT_FLAGS)


def behavior_influence_active(flags: dict[str, Any]) -> bool:
    """True only when memory may shape advisory context.

    Requires both ``MEMORY_BEHAVIOR_INFLUENCE == 1`` and a real provider
    (``MEMORY_PROVIDER != "null"``). A null provider, a missing flag, or a
    non-``1`` value all fail closed to ``False``.
    """
    if not isinstance(flags, dict):
        return False
    influence = _coerce_int_flag(flags.get("MEMORY_BEHAVIOR_INFLUENCE"))
    provider = _coerce_provider(flags.get("MEMORY_PROVIDER"))
    return influence == 1 and provider != "null"


# ── Activation scope — what controlled activation may and may not do ───────

#: The ONLY effects controlled read-only activation is allowed to switch on,
#: and the effects it structurally forbids. This is the contract behind
#: `activation_scope_check`; anything not listed here fails closed to denied.
ALLOWED_ACTIVATION_SCOPE: dict[str, dict[str, str]] = {
    "allowed": {
        "memory informs wording": (
            "memory shapes phrasing/context of a recommendation; canonical truth "
            "and the action itself are unchanged"
        ),
        "memory informs context": (
            "memory contributes non-authoritative background; office_truth stays canonical"
        ),
        "memory informs suppression": (
            "memory helps suppress unchanged recommendations that were already reviewed"
        ),
        "memory informs specialist questions": (
            "memory suggests which specialists to consult; it never changes their authority"
        ),
        "mcp read data informs analysis": (
            "read-only MCP data informs analysis; no write path is ever opened"
        ),
        "follow-up scheduler creates revisit": (
            "a follow-up scheduler schedules an advisory revisit; it never mutates policy"
        ),
        "trace captures lineage": (
            "AgentRunTrace records wake/decision lineage for auditability"
        ),
    },
    "denied": {
        "memory changes holdings": "memory may never change holdings",
        "memory changes cash": "memory may never change cash balances",
        "memory changes risk policy": "memory may never change risk policy",
        "memory creates an order": "memory may never create an order",
        "mcp write": "MCP writes are never authorized",
        "langgraph broker authority": "LangGraph is never granted broker authority",
        "learning auto-promotes strategy": "learning may propose, never auto-promote a strategy",
    },
}


def activation_scope_check(action: str) -> tuple[bool, str]:
    """Classify an intended activation effect as allowed or denied.

    Returns ``(True, description)`` when ``action`` is one of the explicitly
    allowed advisory-context effects, ``(False, description)`` when it is
    explicitly forbidden, and ``(False, "unknown")`` — fail-closed — for
    anything unrecognized. Matching is case-insensitive and whitespace-tolerant.
    """
    key = " ".join(str(action).strip().lower().split())
    allowed = ALLOWED_ACTIVATION_SCOPE["allowed"]
    denied = ALLOWED_ACTIVATION_SCOPE["denied"]
    if key in allowed:
        return True, allowed[key]
    if key in denied:
        return False, denied[key]
    return False, "unknown effect — fail closed (READ_ONLY_ADVISORY)"
