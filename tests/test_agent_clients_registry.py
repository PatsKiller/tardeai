"""AgentClientsRegistry@v1 validation and unknown-client fail-closed."""
from __future__ import annotations

from pathlib import Path

from scripts.lib.agent_clients_registry import (
    get_client,
    load_registry,
    mutating_allowed,
    validate_registry,
)

ROOT = Path(__file__).resolve().parents[1]


def test_registry_loads_and_validates():
    reg = load_registry(ROOT / "config" / "agent_clients.yaml")
    errs = validate_registry(reg, schema_path=ROOT / "config" / "agent_clients.schema.json")
    assert errs == [], errs
    ids = {c["agent_id"] for c in reg["clients"]}
    for need in ("codex", "claude_code", "cursor", "github_copilot", "grok", "bill", "quad_code"):
        assert need in ids


def test_unknown_client_fail_closed():
    c = get_client("totally_unknown_agent_xyz")
    assert c.get("unknown") is True
    assert c["enforcement_level"] == "ADVISORY"
    assert mutating_allowed("totally_unknown_agent_xyz") is False


def test_mechanical_clients_can_mutate_flag():
    assert mutating_allowed("grok") is True
    assert mutating_allowed("github_copilot") is False  # ADVISORY until IDE hook proven
