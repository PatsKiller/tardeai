"""Lane G — agent_gateway_adapter proofs (no network)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

import scripts.lib.comms.mode as mode_mod  # noqa: E402
from scripts.lib.agent_gateway_adapter import (  # noqa: E402
    AgentOutboundRequest,
    GatewayAdapterError,
    build_outbound_event,
    command_center_url_for,
    decide_ownership,
    format_agent_body,
)
from scripts.lib.comms.artifact import ALLOWED_HOST  # noqa: E402


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv("COMMS_GATEWAY_MODE", raising=False)
    monkeypatch.delenv("COMMS_GATEWAY_CANARY_CLASSES", raising=False)
    monkeypatch.delenv("COMMS_GATEWAY_CANARY_CHATS", raising=False)
    mode_mod._cache["mode"] = None
    mode_mod._cache["why"] = None
    yield
    mode_mod._cache["mode"] = None
    mode_mod._cache["why"] = None


def _req(**kwargs) -> AgentOutboundRequest:
    base = dict(
        agent_id="cio",
        subject_guid="b60bb80f-62f5-58b7-b3aa-3ed4ca29bede",
        body="Research question changed for subject.",
        message_class="ops",
        wake_id="wake-001",
        commitment_id="commit-001",
        authoritative_sources=[{"kind": "research_object", "id": "research:46057"}],
        command_center_path="/v3/cio",
        source_sha="54639ff5aaae0e3f56e6e0a327a7c99c06c5d466",
    )
    base.update(kwargs)
    return AgentOutboundRequest(**base)


def test_command_center_url_is_fully_qualified_v3():
    url = command_center_url_for("/v3/cio")
    assert url.startswith(f"https://{ALLOWED_HOST}/v3/")
    assert "localhost" not in url
    assert ":7777" not in url


def test_command_center_rejects_non_v3_path():
    with pytest.raises(GatewayAdapterError):
        command_center_url_for("/v2/cio")


def test_format_includes_cc_link_no_secrets():
    url = command_center_url_for("/v3/cio")
    text = format_agent_body("hello", command_center_url=url, wake_id="w1")
    assert url in text
    assert "wake_id: w1" in text
    assert "token" not in text.lower()
    assert "BOT" not in text


def test_build_event_mints_stable_ids(monkeypatch):
    monkeypatch.setenv("COMMS_GATEWAY_MODE", "CANARY")
    monkeypatch.setenv("COMMS_GATEWAY_CANARY_CLASSES", "ops")
    mode_mod._cache["mode"] = None
    ev, own = build_outbound_event(_req())
    assert ev.event_id and len(str(ev.event_id)) >= 8
    assert ev.thread_id
    assert ev.correlation_id
    assert ev.subject_guid == _req().subject_guid
    assert ev.command_center_url.startswith("https://")
    assert ev.authoritative_sources
    assert own.delivery_owner == "gateway"
    assert own.reason == "canary_allowlist_match"


def test_off_mode_routes_legacy(monkeypatch):
    monkeypatch.setenv("COMMS_GATEWAY_MODE", "OFF")
    mode_mod._cache["mode"] = None
    d = decide_ownership(message_class="ops")
    assert d.delivery_owner == "legacy"
    assert "mode_off" in d.reason


def test_canary_class_outside_allowlist_is_legacy(monkeypatch):
    monkeypatch.setenv("COMMS_GATEWAY_MODE", "CANARY")
    monkeypatch.setenv("COMMS_GATEWAY_CANARY_CLASSES", "ops")
    mode_mod._cache["mode"] = None
    d = decide_ownership(message_class="approval")
    assert d.delivery_owner == "legacy"
    assert "not_in_canary_allowlist" in d.reason


def test_fail_closed_missing_subject_guid():
    with pytest.raises(GatewayAdapterError, match="subject_guid"):
        build_outbound_event(_req(subject_guid=""))


def test_fail_closed_missing_authoritative_sources():
    with pytest.raises(GatewayAdapterError, match="authoritative_sources"):
        build_outbound_event(_req(authoritative_sources=[]))


def test_fail_closed_empty_body():
    with pytest.raises(GatewayAdapterError, match="body"):
        build_outbound_event(_req(body="  "))


def test_off_state_negative_control(monkeypatch):
    """off_state: gateway must not own delivery when mode is OFF."""
    monkeypatch.setenv("COMMS_GATEWAY_MODE", "OFF")
    mode_mod._cache["mode"] = None
    ev, own = build_outbound_event(_req())
    assert own.delivery_owner == "legacy"
    assert ev.delivery_owner == "legacy"
