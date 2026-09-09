"""Lane G — gateway settlement proofs (isolated transport only)."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

import scripts.lib.comms.mode as mode_mod  # noqa: E402
from scripts.lib.agent_gateway_adapter import AgentOutboundRequest  # noqa: E402
from scripts.lib.comms.client import reset_memory_store  # noqa: E402
from scripts.lib.comms.delivery import reset_memory_deliveries  # noqa: E402
from scripts.lib.gateway_settlement import (  # noqa: E402
    SettlementError,
    assert_deliver_agent_outbound_runtime_caller,
    build_wake_outbound_handler,
    deliver_agent_outbound,
    reset_settlement_index,
    sanctioned_telegram_transport,
    transport_invoke_count,
    wake_gateway_outbound_enabled,
)
from scripts.lib.persistent_agent_wake import FEATURE_FLAG, run_scheduled_wake  # noqa: E402
from scripts.lib.wake_subject_selector import SubjectCandidate  # noqa: E402


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


def test_canary_chat_allowlist_blocks_outside_chats(monkeypatch):
    """Explicit CANARY chat allowlist: off-list chats fail closed, no transport."""
    monkeypatch.setenv("COMMS_GATEWAY_MODE", "CANARY")
    monkeypatch.setenv("COMMS_GATEWAY_CANARY_CLASSES", "ops")
    monkeypatch.setenv("COMMS_GATEWAY_CANARY_CHATS", "8797974247")
    mode_mod._cache["mode"] = None
    txn = _fake_transport_factory()
    r = deliver_agent_outbound(
        _req(chat_ids=["9999999999"]),
        deliver=True,
        transport=txn,
    )
    assert r.ok is False
    assert any("delivery_blocked_canary_chats" in e for e in r.errors)
    assert r.transport_invoked is False
    assert txn.calls == []
    assert r.delivery_id  # reserved before chat gate


# ── Runtime factory / wake reachability ─────────────────────────────────────

SG = "b60bb80f-62f5-58b7-b3aa-3ed4ca29bede"
RID = "research:46057"
NOW = datetime(2026, 9, 8, 16, 0, tzinfo=timezone.utc)
WAKE_ENV = {
    FEATURE_FLAG: "1",
    "PROVENANCE_PRODUCER": "test",
    "TRADEAI_SOURCE_SHA": "54639ff5aaae0e3f56e6e0a327a7c99c06c5d466",
}


def _mem_empty(tmp_path: Path) -> Path:
    p = tmp_path / "mem.jsonl"
    p.write_text("")
    return p


def _settled_wake(tmp_path: Path):
    state = tmp_path / "state"
    state.mkdir()
    sel = SubjectCandidate(
        subject_guid=SG,
        source="unconsumed_research",
        source_id=RID,
        observed_at=NOW.isoformat().replace("+00:00", "Z"),
    )
    return run_scheduled_wake(
        agent_id="cio",
        subject_guid=SG,
        state_root=state,
        memory_backend=_mem_empty(tmp_path),
        when=NOW,
        env=WAKE_ENV,
        selection=sel,
    )


def _canary_env(monkeypatch, *, outbound: str = "1", deliver: str = "1"):
    monkeypatch.setenv("COMMS_GATEWAY_MODE", "CANARY")
    monkeypatch.setenv("COMMS_GATEWAY_CANARY_CLASSES", "ops")
    monkeypatch.setenv("COMMS_GATEWAY_CANARY_CHATS", "8797974247")
    monkeypatch.setenv("PERSISTENT_WAKE_GATEWAY_OUTBOUND", outbound)
    monkeypatch.setenv("PERSISTENT_WAKE_GATEWAY_DELIVER", deliver)
    mode_mod._cache["mode"] = None


def test_settled_wake_handler_invokes_gateway_and_settles(tmp_path, monkeypatch):
    """E2E: qualifying SETTLED wake → handler → gateway-owned SETTLED delivery."""
    _canary_env(monkeypatch)
    wake_result = _settled_wake(tmp_path)
    assert wake_result["ok"]
    assert wake_result["wake"]["lifecycle_state"] == "SETTLED"
    assert (wake_result["wake"].get("decision_summary") or {}).get("act") is True

    txn = _fake_transport_factory("tg-wake-e2e-1")
    handler = build_wake_outbound_handler(
        env=dict(**WAKE_ENV, **{
            "COMMS_GATEWAY_MODE": "CANARY",
            "COMMS_GATEWAY_CANARY_CLASSES": "ops",
            "COMMS_GATEWAY_CANARY_CHATS": "8797974247",
            "PERSISTENT_WAKE_GATEWAY_OUTBOUND": "1",
            "PERSISTENT_WAKE_GATEWAY_DELIVER": "1",
        }),
        transport=txn,
        deliver=True,
    )
    # Mimic WakeEngine._outbound call site (SFR-G-002 / SFR-G-003).
    out = handler(wake=wake_result["wake"], receipts=wake_result["receipts"])
    assert out["ok"] is True
    assert out["delivered"] is True
    assert out["delivery_owner"] == "gateway"
    assert out["provider_settlement_state"] == "SETTLED"
    assert out["provider_message_id"] == "tg-wake-e2e-1"
    assert out["event_id"] and out["delivery_id"]
    assert len(txn.calls) == 1


def test_handler_missing_transport_cannot_report_success(tmp_path, monkeypatch):
    _canary_env(monkeypatch)
    wake_result = _settled_wake(tmp_path)
    # deliver=True but sanctioned transport has no TELEGRAM_BOT_TOKEN → fail closed.
    #
    # Set EMPTY, do not delete. telegram_alert._env() re-bootstraps from .env
    # whenever a key is ABSENT from os.environ, so monkeypatch.delenv() is
    # silently undone and the token reappears -- this test then exercised the
    # provider-failure path (`telegram_send_failed`) instead of the
    # authorization path it names, and failed on any host with a real .env.
    # An empty value stays present, so no re-bootstrap occurs and _token()
    # returns "" as intended.
    #
    # Worth noting beyond this test: clearing TELEGRAM_BOT_TOKEN from the
    # environment does NOT disable Telegram for the same reason.
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setenv("ENABLE_TELEGRAM", "true")
    handler = build_wake_outbound_handler(
        env={
            "PERSISTENT_WAKE_GATEWAY_OUTBOUND": "1",
            "PERSISTENT_WAKE_GATEWAY_DELIVER": "1",
            "COMMS_GATEWAY_MODE": "CANARY",
            "COMMS_GATEWAY_CANARY_CLASSES": "ops",
            "COMMS_GATEWAY_CANARY_CHATS": "8797974247",
        },
        transport=None,  # falls back to sanctioned_telegram_transport
        deliver=True,
    )
    out = handler(wake=wake_result["wake"], receipts=wake_result["receipts"])
    assert out["ok"] is False
    assert out.get("delivered") is False
    assert "missing_telegram_authorization" in str(out.get("error") or out.get("errors"))


def test_handler_duplicate_invocation_no_second_provider_send(tmp_path, monkeypatch):
    _canary_env(monkeypatch)
    wake_result = _settled_wake(tmp_path)
    txn = _fake_transport_factory("tg-dup-1")
    handler = build_wake_outbound_handler(transport=txn, deliver=True, env={
        "PERSISTENT_WAKE_GATEWAY_OUTBOUND": "1",
        "COMMS_GATEWAY_MODE": "CANARY",
        "COMMS_GATEWAY_CANARY_CLASSES": "ops",
        "COMMS_GATEWAY_CANARY_CHATS": "8797974247",
    })
    a = handler(wake=wake_result["wake"], receipts=wake_result["receipts"])
    b = handler(wake=wake_result["wake"], receipts=wake_result["receipts"])
    assert a["ok"] and b["ok"]
    assert a["provider_message_id"] == b["provider_message_id"] == "tg-dup-1"
    assert b.get("duplicate") is True
    assert b.get("transport_invoked") is False
    assert len(txn.calls) == 1


def test_handler_canary_off_produces_no_send(tmp_path, monkeypatch):
    monkeypatch.setenv("COMMS_GATEWAY_MODE", "OFF")
    monkeypatch.setenv("PERSISTENT_WAKE_GATEWAY_OUTBOUND", "1")
    mode_mod._cache["mode"] = None
    wake_result = _settled_wake(tmp_path)
    txn = _fake_transport_factory()
    handler = build_wake_outbound_handler(transport=txn, deliver=True, env={
        "PERSISTENT_WAKE_GATEWAY_OUTBOUND": "1",
        "COMMS_GATEWAY_MODE": "OFF",
    })
    out = handler(wake=wake_result["wake"], receipts=wake_result["receipts"])
    assert out["ok"] is False
    assert "gateway_mode_not_canary" in str(out.get("error"))
    assert txn.calls == []


def test_outbound_feature_flag_off_blocks_handler(tmp_path, monkeypatch):
    _canary_env(monkeypatch, outbound="0")
    assert wake_gateway_outbound_enabled({"PERSISTENT_WAKE_GATEWAY_OUTBOUND": "0"}) is False
    wake_result = _settled_wake(tmp_path)
    txn = _fake_transport_factory()
    handler = build_wake_outbound_handler(transport=txn, deliver=True, env={
        "PERSISTENT_WAKE_GATEWAY_OUTBOUND": "0",
        "COMMS_GATEWAY_MODE": "CANARY",
        "COMMS_GATEWAY_CANARY_CLASSES": "ops",
    })
    out = handler(wake=wake_result["wake"], receipts=wake_result["receipts"])
    assert out["ok"] is False
    assert out["error"] == "wake_gateway_outbound_disabled"
    assert txn.calls == []


def test_reachability_negative_control_runtime_caller_present():
    """Fails whenever deliver_agent_outbound has no non-test runtime caller."""
    callers = assert_deliver_agent_outbound_runtime_caller(scripts_root=str(ROOT / "scripts"))
    assert any(c.endswith("gateway_settlement.py") for c in callers)


def test_sanctioned_transport_reuses_raw_send_not_new_client(monkeypatch):
    calls = []

    def fake_raw(message, chat_ids=None, **kwargs):
        calls.append({"message": message, "chat_ids": chat_ids})
        return {"ok": True, "message_ids": ["m1"], "chat_ids": chat_ids or []}

    monkeypatch.setenv("ENABLE_TELEGRAM", "true")
    monkeypatch.setattr("scripts.telegram_alert._raw_send_telegram_result", fake_raw)
    monkeypatch.setattr("scripts.telegram_alert._token", lambda: "authorized")
    monkeypatch.setattr(
        "scripts.telegram_alert._env",
        lambda k, d="": "true" if k == "ENABLE_TELEGRAM" else d,
    )

    ack = sanctioned_telegram_transport(body="hello", chat_ids=["1"])
    assert ack["ok"] is True
    assert ack["provider_message_id"] == "m1"
    assert len(calls) == 1
    # Token must not appear in transport kwargs or ack payload.
    assert "TOKEN" not in json.dumps(ack)
    assert "token" not in calls[0]
