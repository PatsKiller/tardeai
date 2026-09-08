"""Lane G — gateway settlement proofs (isolated transport only)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

import scripts.lib.comms.mode as mode_mod  # noqa: E402
from scripts.lib.agent_gateway_adapter import AgentOutboundRequest  # noqa: E402
from scripts.lib.comms.client import reset_memory_store  # noqa: E402
from scripts.lib.comms.delivery import reset_memory_deliveries  # noqa: E402
from scripts.lib.gateway_settlement import (  # noqa: E402
    deliver_agent_outbound,
    reset_settlement_index,
    transport_invoke_count,
)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv("COMMS_GATEWAY_MODE", raising=False)
    monkeypatch.delenv("COMMS_GATEWAY_CANARY_CLASSES", raising=False)
    monkeypatch.delenv("COMMS_GATEWAY_CANARY_CHATS", raising=False)
    mode_mod._cache["mode"] = None
    mode_mod._cache["why"] = None
    monkeypatch.setattr("scripts.lib.comms.client._db_conn", lambda: None)
    monkeypatch.setattr("scripts.lib.comms.delivery._db_conn", lambda: None)
    reset_memory_store()
    reset_memory_deliveries()
    reset_settlement_index()
    yield
    reset_memory_store()
    reset_memory_deliveries()
    reset_settlement_index()
    mode_mod._cache["mode"] = None
    mode_mod._cache["why"] = None


def _req(**kwargs) -> AgentOutboundRequest:
    base = dict(
        agent_id="cio",
        subject_guid="b60bb80f-62f5-58b7-b3aa-3ed4ca29bede",
        body="Agent decided: changed_question on research:46057.",
        message_class="ops",
        wake_id="wake-settlement-001",
        commitment_id="commit-settlement-001",
        authoritative_sources=[{"kind": "research_object", "id": "research:46057"}],
        command_center_path="/v3/cio",
        chat_ids=["8797974247"],
        source_sha="54639ff5aaae0e3f56e6e0a327a7c99c06c5d466",
    )
    base.update(kwargs)
    return AgentOutboundRequest(**base)


def _fake_transport_factory(pmid: str = "tg-msg-42"):
    calls: list[dict] = []

    def transport(**kwargs):
        calls.append(dict(kwargs))
        # Never include credentials
        assert "token" not in kwargs
        assert "BOT" not in str(kwargs)
        return {
            "ok": True,
            "provider_message_id": pmid,
            "provider_coordinates": {"channel": "telegram", "message_ids": [pmid]},
        }

    transport.calls = calls  # type: ignore[attr-defined]
    return transport


def test_reserve_before_transport_when_not_delivering(monkeypatch):
    monkeypatch.setenv("COMMS_GATEWAY_MODE", "CANARY")
    monkeypatch.setenv("COMMS_GATEWAY_CANARY_CLASSES", "ops")
    mode_mod._cache["mode"] = None
    r = deliver_agent_outbound(_req(), deliver=False)
    assert r.ok
    assert r.delivery_owner == "gateway"
    assert r.delivery_id
    assert r.event_id
    assert r.thread_id and r.correlation_id and r.subject_guid
    assert r.provider_settlement_state == "UNSETTLED"
    assert r.delivered is False
    assert r.transport_invoked is False
    assert r.command_center_url and r.command_center_url.startswith("https://")


def test_canary_deliver_settles_with_provider_id(monkeypatch):
    monkeypatch.setenv("COMMS_GATEWAY_MODE", "CANARY")
    monkeypatch.setenv("COMMS_GATEWAY_CANARY_CLASSES", "ops")
    monkeypatch.setenv("COMMS_GATEWAY_CANARY_CHATS", "8797974247")
    mode_mod._cache["mode"] = None
    txn = _fake_transport_factory("tg-ack-99")
    r = deliver_agent_outbound(_req(), deliver=True, transport=txn)
    assert r.ok
    assert r.delivered is True
    assert r.provider_message_id == "tg-ack-99"
    assert r.provider_settlement_state == "SETTLED"
    assert r.delivery_owner == "gateway"
    assert r.transport_invoked is True
    assert len(txn.calls) == 1


def test_idempotent_retry_no_duplicate_provider_send(monkeypatch):
    """replay / duplicate: second call must not invoke transport again."""
    monkeypatch.setenv("COMMS_GATEWAY_MODE", "CANARY")
    monkeypatch.setenv("COMMS_GATEWAY_CANARY_CLASSES", "ops")
    mode_mod._cache["mode"] = None
    txn = _fake_transport_factory("tg-idem-1")
    req = _req()
    a = deliver_agent_outbound(req, deliver=True, transport=txn)
    b = deliver_agent_outbound(req, deliver=True, transport=txn)
    assert a.ok and b.ok
    assert a.event_id == b.event_id
    assert a.provider_message_id == b.provider_message_id
    assert b.duplicate is True
    assert b.transport_invoked is False
    assert transport_invoke_count(a.event_id) == 1
    assert len(txn.calls) == 1


def test_legacy_outside_allowlist_no_transport(monkeypatch):
    monkeypatch.setenv("COMMS_GATEWAY_MODE", "CANARY")
    monkeypatch.setenv("COMMS_GATEWAY_CANARY_CLASSES", "ops")
    mode_mod._cache["mode"] = None
    txn = _fake_transport_factory()
    # "research" is a valid class that is outside the ops CANARY allowlist and
    # does not require protected_facts (unlike "approval").
    r = deliver_agent_outbound(_req(message_class="research"), deliver=True, transport=txn)
    assert r.ok
    assert r.delivery_owner == "legacy"
    assert "not_in_canary_allowlist" in (r.ownership_reason or "")
    assert r.provider_settlement_state == "UNKNOWN_LEGACY"
    assert r.transport_invoked is False
    assert txn.calls == []


def test_deliver_true_without_transport_fails_closed(monkeypatch):
    monkeypatch.setenv("COMMS_GATEWAY_MODE", "CANARY")
    monkeypatch.setenv("COMMS_GATEWAY_CANARY_CLASSES", "ops")
    mode_mod._cache["mode"] = None
    r = deliver_agent_outbound(_req(), deliver=True, transport=None)
    assert r.ok is False
    assert any("missing_transport" in e for e in r.errors)
    assert r.delivery_id  # reserved before the fail


def test_transport_failure_marks_failed(monkeypatch):
    monkeypatch.setenv("COMMS_GATEWAY_MODE", "CANARY")
    monkeypatch.setenv("COMMS_GATEWAY_CANARY_CLASSES", "ops")
    mode_mod._cache["mode"] = None

    def bad(**kwargs):
        return {"ok": False, "error": "provider_rejected"}

    r = deliver_agent_outbound(_req(), deliver=True, transport=bad)
    assert r.ok is False
    assert r.provider_settlement_state == "FAILED"
    assert "provider_rejected" in r.errors


def test_missing_provider_message_id_fails_closed(monkeypatch):
    monkeypatch.setenv("COMMS_GATEWAY_MODE", "CANARY")
    monkeypatch.setenv("COMMS_GATEWAY_CANARY_CLASSES", "ops")
    mode_mod._cache["mode"] = None

    def no_pmid(**kwargs):
        return {"ok": True, "provider_message_id": None}

    r = deliver_agent_outbound(_req(), deliver=True, transport=no_pmid)
    assert r.ok is False
    assert "missing_provider_message_id" in r.errors


def test_fixture_not_organic_negative_control(monkeypatch):
    """fixture_not_organic: fake transport must never be mistaken for live send."""
    monkeypatch.setenv("COMMS_GATEWAY_MODE", "CANARY")
    monkeypatch.setenv("COMMS_GATEWAY_CANARY_CLASSES", "ops")
    mode_mod._cache["mode"] = None
    txn = _fake_transport_factory("fixture-pmid")
    r = deliver_agent_outbound(_req(), deliver=True, transport=txn)
    assert r.ok
    # Explicit: this path is fixture-isolated — no bot token env required.
    assert "TELEGRAM_BOT_TOKEN" not in str(txn.calls)


def test_off_state_never_invokes_transport(monkeypatch):
    monkeypatch.setenv("COMMS_GATEWAY_MODE", "OFF")
    mode_mod._cache["mode"] = None
    txn = _fake_transport_factory()
    r = deliver_agent_outbound(_req(), deliver=True, transport=txn)
    assert r.ok
    assert r.delivery_owner == "legacy"
    assert txn.calls == []
