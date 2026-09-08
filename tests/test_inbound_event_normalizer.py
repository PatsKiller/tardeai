#!/usr/bin/env python3
"""Lane I — inbound normalization / correlation / auth / dedupe proofs."""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.comms.client import reset_memory_store  # noqa: E402
from scripts.lib.comms.delivery import (  # noqa: E402
    ChannelDelivery,
    reset_memory_deliveries,
    reserve_delivery,
    settle_delivery,
)
from scripts.lib.comms.inbound import reset_inbound_state  # noqa: E402
from scripts.lib.comms.mode import _cache as _mode_cache  # noqa: E402
from scripts.lib.inbound_event_normalizer import (  # noqa: E402
    normalize_inbound_update,
    reset_normalizer_memory,
)


def _update(
    *,
    update_id: int = 1001,
    chat_id: int = 42,
    message_id: int = 77,
    user_id: int = 7,
    text: str = "ack",
    reply_to: int | None = None,
    date: int | None = None,
    callback: bool = False,
) -> dict:
    chat = {"id": chat_id, "type": "private"}
    frm = {"id": user_id, "is_bot": False, "first_name": "Op"}
    if callback:
        msg: dict = {"message_id": message_id, "chat": chat}
        if reply_to is not None:
            msg["reply_to_message"] = {"message_id": reply_to, "chat": chat}
        if date is not None:
            msg["date"] = date
        return {
            "update_id": update_id,
            "callback_query": {"id": "cb1", "from": frm, "data": text, "message": msg},
        }
    msg = {
        "message_id": message_id,
        "date": date if date is not None else int(time.time()),
        "chat": chat,
        "from": frm,
        "text": text,
    }
    if reply_to is not None:
        msg["reply_to_message"] = {"message_id": reply_to, "chat": chat}
    return {"update_id": update_id, "message": msg}


@pytest.fixture(autouse=True)
def _clean(monkeypatch, tmp_path):
    monkeypatch.delenv("COMMS_GATEWAY_MODE", raising=False)
    monkeypatch.delenv("COMMS_INBOUND_SENDER_ALLOWLIST", raising=False)
    monkeypatch.delenv("COMMS_GATEWAY_CANARY_CHATS", raising=False)
    monkeypatch.delenv("COMMS_INBOUND_STALE_SECONDS", raising=False)
    monkeypatch.setattr("scripts.lib.comms.client._db_conn", lambda: None)
    monkeypatch.setattr("scripts.lib.comms.delivery._db_conn", lambda: None)
    monkeypatch.setattr("scripts.lib.comms.inbound._db_conn", lambda: None)
    monkeypatch.setattr("scripts.lib.comms.agent_contracts._db_conn", lambda: None)
    monkeypatch.setenv("COMMS_INBOUND_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("COMMS_INBOUND_SENDER_ALLOWLIST", "7")
    _mode_cache["mode"] = None
    _mode_cache["why"] = None
    reset_inbound_state()
    reset_memory_store()
    reset_memory_deliveries()
    reset_normalizer_memory()
    yield
    reset_inbound_state()
    reset_memory_store()
    reset_memory_deliveries()
    reset_normalizer_memory()
    _mode_cache["mode"] = None


def test_normalize_preserves_provider_ids_and_mints_event_guid():
    r = normalize_inbound_update(_update())
    assert r.ok, r.reason
    assert r.event_id
    coords = r.event.provider_coordinates
    assert coords["update_id"] == 1001
    assert str(coords["message_id"]) == "77"
    assert str(coords["chat_id"]) == "42"
    assert r.published is True


def test_malformed_missing_update_id():
    u = _update()
    del u["update_id"]
    r = normalize_inbound_update(u)
    assert not r.ok
    assert r.reason.startswith("malformed")


def test_unauthorized_sender():
    r = normalize_inbound_update(_update(user_id=999))
    assert not r.ok
    assert "sender_not_allowlisted" in r.reason


def test_empty_sender_allowlist_fail_closed(monkeypatch):
    monkeypatch.delenv("COMMS_INBOUND_SENDER_ALLOWLIST", raising=False)
    r = normalize_inbound_update(_update())
    assert not r.ok
    assert "sender_allowlist_empty" in r.reason


def test_canary_scope_blocks_non_allowlisted_chat(monkeypatch):
    monkeypatch.setenv("COMMS_GATEWAY_MODE", "CANARY")
    monkeypatch.setenv("COMMS_GATEWAY_CANARY_CHATS", "100")
    _mode_cache["mode"] = None
    r = normalize_inbound_update(_update(chat_id=42))
    assert not r.ok
    assert "canary" in r.reason


def test_canary_scope_allows_listed_chat(monkeypatch):
    monkeypatch.setenv("COMMS_GATEWAY_MODE", "CANARY")
    monkeypatch.setenv("COMMS_GATEWAY_CANARY_CHATS", "42")
    _mode_cache["mode"] = None
    r = normalize_inbound_update(_update(chat_id=42))
    assert r.ok, r.reason


def test_duplicate_provider_retry_suppressed():
    u = _update(update_id=55, message_id=9)
    r1 = normalize_inbound_update(u)
    assert r1.ok
    r2 = normalize_inbound_update(u)
    assert not r2.ok
    assert r2.duplicate
    assert "duplicate" in r2.reason


def test_stale_update_rejected(monkeypatch):
    monkeypatch.setenv("COMMS_INBOUND_STALE_SECONDS", "60")
    r = normalize_inbound_update(_update(date=1_000_000_000))  # year 2001
    assert not r.ok
    assert r.reason.startswith("stale")


def test_reply_correlates_to_outbound_provider_message():
    # Seed an outbound settled delivery with provider message id 500.
    from scripts.lib.comms.adapters import from_plain_message
    from scripts.lib.comms.client import publish_communication

    outbound = from_plain_message(
        producer="test_outbound",
        body="hello",
        message_class="ops",
        subject_key="telegram:outbound:42:root",
    )
    outbound.provider_coordinates = {"chat_id": "42", "message_id": "500"}
    pub = publish_communication(outbound)
    assert pub.ok
    dlv = reserve_delivery(event_id=pub.event_id, channel="telegram")
    settle_delivery(
        dlv.delivery_id,
        status="SENT",
        provider_message_id="500",
    )

    inbound = _update(update_id=2002, message_id=88, reply_to=500)
    r = normalize_inbound_update(inbound)
    assert r.ok, r.reason
    assert r.correlation.get("correlated") is True
    assert r.event.reply_to_event_id == pub.event_id
    assert r.event.parent_event_id == pub.event_id


def test_uncorrelated_when_required():
    r = normalize_inbound_update(_update(reply_to=99999), require_correlation=True)
    assert not r.ok
    assert r.reason.startswith("uncorrelated")


def test_persistence_failure_when_publish_raises(monkeypatch):
    def _boom(_event):
        raise RuntimeError("disk full")

    monkeypatch.setattr(
        "scripts.lib.inbound_event_normalizer.publish_communication", _boom
    )
    r = normalize_inbound_update(_update(update_id=3003))
    assert not r.ok
    assert "persistence_failure" in r.reason


def test_callback_query_path_normalizes():
    r = normalize_inbound_update(_update(update_id=6001, message_id=66, callback=True, text="approve:1"))
    assert r.ok, r.reason
    assert r.event.event_type == "callback_query"
    assert r.event.provider_coordinates.get("callback_query_id") == "cb1"
