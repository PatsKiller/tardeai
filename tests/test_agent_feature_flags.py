"""Phase 12 — Controlled read-only activation: feature flags unit tests.

No broker, no network. Deterministic only.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import pytest  # noqa: E402

from scripts.lib.agent_feature_flags import (  # noqa: E402
    ALLOWED_ACTIVATION_SCOPE,
    ALLOWED_MEMORY_PROVIDERS,
    DEFAULT_FLAGS,
    activation_scope_check,
    behavior_influence_active,
    load_feature_flags,
    rollback_flags,
)


# ── Conservative defaults ──────────────────────────────────────────────────


def test_defaults_are_conservative():
    """The invariant is 'conservative', which is not the same as 'zero'.

    Until 2026-09-17 this test asserted every flag defaulted to 0 and called
    that conservative. For two of them the reverse was true:

      * MEMORY_ADVERSARIAL_SCAN=0 means the jailbreak / instruction-override
        scan records `shadow_reject` and admits the record anyway
        (agent_memory_admission.py:112-120). Off is the PERMISSIVE setting.
    MCP_READ_ONLY_GATEWAY is NOT such a case and stays 0: that flag opens the
    read-only MCP context path rather than guarding an existing one, so ON
    grants agents a capability they otherwise do not have. Conservative there
    really is 0, and activation is the operator's call (AGENTS.md section 17).

    So a blanket zero-check was guarding the wrong thing for one flag, and the
    right thing for the rest. What must stay off is anything that lets
    remembered text SHAPE ADVICE, opens a new capability path, or introduces a
    second workflow system of record. Those are asserted below and are the
    assertions that matter.
    """
    flags = load_feature_flags({})

    # Safety and observability controls: ON is the conservative direction.
    assert flags["MEMORY_ADVERSARIAL_SCAN"] == 1, "adversarial scan must enforce, not shadow"
    assert flags["AGENT_RUN_TRACE"] == 1
    assert flags["AGENT_DECISION_PAYLOAD"] == 1
    assert flags["AGENT_CONTEXT_ENVELOPE"] == 1

    # The rails. These are the reason this test exists.
    # AI_WORK_POLICY.md section 27 forbids MEMORY_BEHAVIOR_INFLUENCE other than 0.
    assert flags["MEMORY_BEHAVIOR_INFLUENCE"] == 0, "memory must never shape advice by default"
    assert flags["MEMORY_SHADOW"] == 0, "shadow is staged via env, not defaulted on"
    assert flags["MEMORY_PROVIDER"] == "null", "no memory backend by default"
    assert flags["MCP_READ_ONLY_GATEWAY"] == 0, "opens a capability path; operator activates"
    assert flags["LANGGRAPH_WORKER_PILOT"] == 0, "no second workflow system of record"


def test_defaults_match_default_flags_constant():
    assert load_feature_flags({}) == DEFAULT_FLAGS
    assert DEFAULT_FLAGS["MEMORY_PROVIDER"] == "null"


def test_load_feature_flags_does_not_mutate_env():
    env = {"MEMORY_BEHAVIOR_INFLUENCE": "1"}
    load_feature_flags(env)
    assert env == {"MEMORY_BEHAVIOR_INFLUENCE": "1"}


# ── Environment override: ints and booleans ────────────────────────────────


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1", 1),
        ("0", 0),
        ("true", 1),
        ("false", 0),
        ("TRUE", 1),
        ("yes", 1),
        ("no", 0),
        ("on", 1),
        ("off", 0),
        (1, 1),
        (0, 0),
        (True, 1),
        (False, 0),
    ],
)
def test_env_override_parses_ints_and_booleans(raw, expected):
    flags = load_feature_flags({"MEMORY_BEHAVIOR_INFLUENCE": raw})
    assert flags["MEMORY_BEHAVIOR_INFLUENCE"] == expected


def test_env_override_all_integer_flags():
    env = {
        "AGENT_CONTEXT_ENVELOPE": "true",
        "AGENT_RUN_TRACE": "1",
        "AGENT_DECISION_PAYLOAD": "1",
        "MCP_READ_ONLY_GATEWAY": "on",
        "MEMORY_SHADOW": "yes",
        "MEMORY_BEHAVIOR_INFLUENCE": "1",
        "MEMORY_ADVERSARIAL_SCAN": "1",
        "LANGGRAPH_WORKER_PILOT": "true",
    }
    flags = load_feature_flags(env)
    assert flags["AGENT_CONTEXT_ENVELOPE"] == 1
    assert flags["AGENT_RUN_TRACE"] == 1
    assert flags["AGENT_DECISION_PAYLOAD"] == 1
    assert flags["MCP_READ_ONLY_GATEWAY"] == 1
    assert flags["MEMORY_SHADOW"] == 1
    assert flags["MEMORY_BEHAVIOR_INFLUENCE"] == 1
    assert flags["MEMORY_ADVERSARIAL_SCAN"] == 1
    assert flags["LANGGRAPH_WORKER_PILOT"] == 1


# ── MEMORY_PROVIDER validation ─────────────────────────────────────────────


def test_invalid_memory_provider_falls_back_to_null():
    assert load_feature_flags({"MEMORY_PROVIDER": "redis"})["MEMORY_PROVIDER"] == "null"
    assert load_feature_flags({"MEMORY_PROVIDER": "Mem0Cloud"})["MEMORY_PROVIDER"] == "null"
    assert load_feature_flags({"MEMORY_PROVIDER": ""})["MEMORY_PROVIDER"] == "null"


def test_valid_memory_provider_accepted():
    assert load_feature_flags({"MEMORY_PROVIDER": "mem0"})["MEMORY_PROVIDER"] == "mem0"
    assert load_feature_flags({"MEMORY_PROVIDER": "local"})["MEMORY_PROVIDER"] == "local"
    assert load_feature_flags({"MEMORY_PROVIDER": "null"})["MEMORY_PROVIDER"] == "null"
    assert load_feature_flags({"MEMORY_PROVIDER": "LOCAL"})["MEMORY_PROVIDER"] == "local"
    assert load_feature_flags({"MEMORY_PROVIDER": "durable"})["MEMORY_PROVIDER"] == "durable"


def test_allowed_memory_providers_constant():
    assert ALLOWED_MEMORY_PROVIDERS == frozenset({"mem0", "local", "null", "durable"})


# ── rollback_flags ─────────────────────────────────────────────────────────


def test_rollback_flags_conservative():
    rb = rollback_flags()
    assert rb["MEMORY_BEHAVIOR_INFLUENCE"] == 0
    assert rb["MCP_READ_ONLY_GATEWAY"] == 0
    assert rb["MEMORY_PROVIDER"] == "null"
    assert rb["LANGGRAPH_WORKER_PILOT"] == 0


def test_rollback_flags_fully_conservative():
    assert rollback_flags() == DEFAULT_FLAGS


# ── behavior_influence_active ──────────────────────────────────────────────


def test_behavior_influence_inactive_when_influence_zero():
    assert behavior_influence_active({"MEMORY_BEHAVIOR_INFLUENCE": 0, "MEMORY_PROVIDER": "local"}) is False


def test_behavior_influence_inactive_when_provider_null():
    assert behavior_influence_active({"MEMORY_BEHAVIOR_INFLUENCE": 1, "MEMORY_PROVIDER": "null"}) is False


def test_behavior_influence_active_only_when_both_satisfied():
    assert behavior_influence_active({"MEMORY_BEHAVIOR_INFLUENCE": 1, "MEMORY_PROVIDER": "local"}) is True
    assert behavior_influence_active({"MEMORY_BEHAVIOR_INFLUENCE": 1, "MEMORY_PROVIDER": "mem0"}) is True


def test_behavior_influence_active_missing_flags_fail_closed():
    assert behavior_influence_active({}) is False
    assert behavior_influence_active({"MEMORY_BEHAVIOR_INFLUENCE": 1}) is False
    assert behavior_influence_active("not a dict") is False


# ── activation_scope_check ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    "action",
    [
        "memory changes holdings",
        "memory creates an order",
        "MCP write",
        "LangGraph broker authority",
        "learning auto-promotes strategy",
    ],
)
def test_activation_scope_denies_forbidden_effects(action):
    ok, reason = activation_scope_check(action)
    assert ok is False
    assert reason


@pytest.mark.parametrize(
    "action",
    [
        "memory informs wording",
        "memory informs suppression",
        "follow-up scheduler creates revisit",
    ],
)
def test_activation_scope_allows_advisory_effects(action):
    ok, reason = activation_scope_check(action)
    assert ok is True
    assert reason


def test_activation_scope_unknown_fails_closed():
    ok, reason = activation_scope_check("memory places a trade")
    assert ok is False
    assert "unknown" in reason.lower()


def test_activation_scope_is_case_and_whitespace_tolerant():
    ok, _ = activation_scope_check("  Memory Informs Wording  ")
    assert ok is True
    ok2, _ = activation_scope_check("MCP   WRITE")
    assert ok2 is False


def test_allowed_activation_scope_documents_both_sides():
    assert "memory informs wording" in ALLOWED_ACTIVATION_SCOPE["allowed"]
    assert "memory changes holdings" in ALLOWED_ACTIVATION_SCOPE["denied"]
    assert "mcp write" in ALLOWED_ACTIVATION_SCOPE["denied"]
