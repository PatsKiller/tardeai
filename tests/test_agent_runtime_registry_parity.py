"""Regression guards: operations/MVL JSON must stay aligned with definitions.py."""
from __future__ import annotations

import os
from pathlib import Path

from agent_runtime.agents.definitions import fleet
from agent_runtime.operations import fleet_alerts_payload, operations_payload
from agent_runtime.read_http import AGENT_RUNTIME_FLEET_ALERTS_PATH, dispatch
from agent_runtime.registry import load_registry

ROOT = Path(__file__).resolve().parents[1]
FLEET_IDS = set(fleet().keys())


def _fleet_row(payload: dict, agent_id: str) -> dict:
    for row in payload["agents"]:
        if row["agent_id"] == agent_id:
            return row
    raise KeyError(agent_id)


def test_operations_budget_and_job_types_match_definitions():
    payload = operations_payload(ROOT, reader=None)
    assert payload["read_only"] is True
    assert "critic_lanes_enabled" in payload
    for agent_id, spec in fleet().items():
        row = _fleet_row(payload, agent_id)
        assert row["allowed_job_types"] == list(spec.definition.allowed_job_types)
        assert row["budget"]["max_model_calls"] == spec.definition.budget.max_model_calls
        assert row["budget"]["max_tool_calls"] == spec.definition.budget.max_tool_calls
        assert row["budget"]["max_cost_usd"] == spec.definition.budget.max_cost_usd
        assert row["budget"]["deadline_seconds"] == spec.definition.budget.deadline_seconds
        assert row["reviewer_agent_id"] == spec.reviewer_agent_id
        assert row["scorer_agent_id"] == spec.scorer_agent_id
        assert row["allowed_tools"] == list(spec.definition.allowed_tools)
        assert row["denied_tools"] == list(spec.definition.denied_tools)


def test_mvl_json_budget_and_denied_tools_match_definitions():
    registry = load_registry(ROOT / "config" / "agent_runtime_mvl.json")
    assert FLEET_IDS <= set(registry)
    for agent_id, spec in fleet().items():
        entry = registry[agent_id]
        assert entry.budget.max_model_calls == spec.definition.budget.max_model_calls
        assert entry.budget.max_tool_calls == spec.definition.budget.max_tool_calls
        assert entry.budget.deadline_seconds == spec.definition.budget.deadline_seconds
        assert tuple(entry.denied_tools) == tuple(spec.definition.denied_tools)


def test_critic_lanes_flag_reflects_env(monkeypatch):
    monkeypatch.delenv("AGENT_RUNTIME_CRITIC_LANES", raising=False)
    off = operations_payload(ROOT, reader=None)
    assert off["critic_lanes_enabled"] is False
    monkeypatch.setenv("AGENT_RUNTIME_CRITIC_LANES", "1")
    on = operations_payload(ROOT, reader=None)
    assert on["critic_lanes_enabled"] is True


def test_fleet_alerts_http_get():
    status, body = dispatch(None, "GET", AGENT_RUNTIME_FLEET_ALERTS_PATH)
    assert status == 200
    assert body["read_only"] is True
    assert isinstance(body["alerts"], list)


def test_fleet_alerts_payload_shape(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    state_file = state_dir / "fleet_alert_bridge.json"
    state_file.write_text(
        '{"recent_alerts":[{"artifact_id":"a1","agent_id":"iris","artifact_type":"knowledge_review","severity":"high","alerted_at":"2026-07-31T12:00:00+00:00","summary":"test"}]}',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "agent_runtime.operations.Path.home",
        lambda: tmp_path,
    )
    # fleet_alerts_payload uses Path.home() / ".local/state/tradeai/fleet_alert_bridge.json"
    bridge_dir = tmp_path / ".local" / "state" / "tradeai"
    bridge_dir.mkdir(parents=True)
    (bridge_dir / "fleet_alert_bridge.json").write_text(state_file.read_text(), encoding="utf-8")
    payload = fleet_alerts_payload(limit=5)
    assert payload["count"] == 1
    assert payload["alerts"][0]["artifact_id"] == "a1"
