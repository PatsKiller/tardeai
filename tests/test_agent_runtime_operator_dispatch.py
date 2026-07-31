"""Operator dispatch HTTP tests."""
from __future__ import annotations

from pathlib import Path

import pytest

from agent_runtime.operator_dispatch_http import dispatch_post

ROOT = Path(__file__).resolve().parents[1]


def test_dispatch_blocked_without_operator_auth():
    status, body = dispatch_post({"agent_id": "sentinel"}, root=ROOT, env={})
    assert status == 403
    assert "OPERATOR_AUTH" in body["detail"] or "dispatch not wired" in body["detail"]


def test_dispatch_unknown_agent(tmp_path):
    enable = tmp_path / "agent_runtime_enabled"
    enable.write_text("")
    env = {
        "AGENT_RUNTIME_OPERATOR_AUTH": "1",
        "AGENT_RUNTIME_QUEUE_MODULE": "agent_runtime_dispatch_boot",
        "AGENT_RUNTIME_DISPATCH_DSN": "postgresql://writer@/lab",
        "AGENT_RUNTIME_PROVIDER_MODULE": "agent_runtime.providers.lab_watch_provider",
        "AGENT_RUNTIME_ENABLED_FILE": str(enable),
    }
    status, body = dispatch_post({"agent_id": "not_an_agent"}, root=ROOT, env=env)
    assert status == 404
