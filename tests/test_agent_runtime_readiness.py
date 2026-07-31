"""Read-only readiness endpoint tests."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from agent_runtime.read_http import AGENT_RUNTIME_READINESS_PATH, dispatch
from agent_runtime.readiness import readiness_payload

ROOT = Path(__file__).resolve().parents[1]


def test_readiness_payload_no_secrets():
    payload = readiness_payload(ROOT, env={})
    assert payload["read_only"] is True
    assert payload["authority"]["mutation"] is False
    wiring = payload["wiring"]
    assert wiring["read_api"]["state"] == "GATE_OFF"
    assert wiring["dispatch"]["state"] == "MISSING_OPERATOR_AUTH"
    assert "agents" in payload
    assert payload["fleet_summary"]["total_agents"] >= 16
    body = str(payload)
    assert "postgresql://" not in body
    assert "password" not in body.lower()


def test_readiness_dispatch_operable_flags():
    payload = readiness_payload(ROOT, env={})
    by_id = {row["agent_id"]: row for row in payload["agents"]}
    assert by_id["sentinel"]["dispatch_operable"] is True
    assert by_id["darwin"]["dispatch_operable"] is True
    assert by_id["maria"]["dispatch_operable"] is True


def test_readiness_dispatch_wired_when_env_complete(tmp_path, monkeypatch):
    enable = tmp_path / "agent_runtime_enabled"
    enable.write_text("")
    env = {
        "AGENT_RUNTIME_READ_API": "1",
        "AGENT_RUNTIME_READ_DSN": "postgresql://reader@/lab",
        "AGENT_RUNTIME_OPERATOR_AUTH": "1",
        "AGENT_RUNTIME_QUEUE_MODULE": "agent_runtime_dispatch_boot",
        "AGENT_RUNTIME_DISPATCH_DSN": "postgresql://writer@/lab",
        "AGENT_RUNTIME_PROVIDER_MODULE": "agent_runtime.providers.lab_watch_provider",
        "AGENT_RUNTIME_ENABLED_FILE": str(enable),
    }
    payload = readiness_payload(ROOT, env=env, reader=object())
    assert payload["wiring"]["read_api"]["state"] == "CONNECTED"
    assert payload["wiring"]["dispatch"]["state"] == "WIRED"


def test_readiness_http_get_only():
    status, body = dispatch(None, "POST", AGENT_RUNTIME_READINESS_PATH)
    assert status == 405
    assert body["read_only"] is True


def test_readiness_http_returns_200_without_reader():
    status, body = dispatch(None, "GET", AGENT_RUNTIME_READINESS_PATH)
    assert status == 200
    assert body["contract"] == "agent-runtime-readiness-v1"
    assert isinstance(body["agents"], list)
