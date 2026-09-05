#!/usr/bin/env python3
"""Unit tests for ChannelDelivery@v1 ledger (Phase 3)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.comms.client import (  # noqa: E402
    publish_communication,
    reset_memory_store,
)
from scripts.lib.comms.delivery import (  # noqa: E402
    DeliveryGateError,
    attach_delivery_reservation,
    memory_delivery_snapshot,
    record_chunk,
    reset_memory_deliveries,
    reserve_delivery,
    settle_delivery,
)
from scripts.lib.comms.event import CommunicationEvent  # noqa: E402


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv("COMMS_GATEWAY_MODE", raising=False)
    # Same defect as tests/test_communications_portal.py: these assert the
    # in-memory ledger, every call site is
    # `conn = _db_conn(); if conn is not None: <db> else: <memory>`, and on a box
    # where localhost Postgres answers the DB branch wins — the assertions fail
    # AND the run writes into the production trade_ai database. Matches
    # tests/test_comms_channel_adapters.py:34-36.
    monkeypatch.setattr("scripts.lib.comms.client._db_conn", lambda: None)
    monkeypatch.setattr("scripts.lib.comms.delivery._db_conn", lambda: None)
    # subject_memory carries its own _db_conn, and attach_event_to_subject
    # INSERTs into communication_thread_membership. Stubbing only client+delivery
    # leaves that path live: this file's own comment says "force no DB even when
    # localhost has one", and it was still writing 11 rows per run.
    monkeypatch.setattr("scripts.lib.comms.subject_memory._db_conn", lambda: None)
    reset_memory_store()
    reset_memory_deliveries()
    yield
    reset_memory_store()
    reset_memory_deliveries()


def _publish_outbound(*, channels: list[str] | None = None) -> str:
    ev = CommunicationEvent(
        direction="OUTBOUND",
        event_type="health",
        message_class="operator_alert",
        producer="ops.watchdog",
        subject_key="system:watchdog",
        retention_class="ops_7d",
        sanitized_body="watchdog ok",
        channels=channels if channels is not None else ["telegram"],
    )
    result = publish_communication(ev)
    assert result.ok is True
    assert result.event_id
    return result.event_id


def test_reserve_settle_sent_with_provider_message_id():
    event_id = _publish_outbound()
    # publish already reserved; settle that stub (or reserve explicitly)
    stubs = memory_delivery_snapshot()
    assert len(stubs) == 1
    delivery_id = next(iter(stubs))
    settled = settle_delivery(
        delivery_id,
        status="SENT",
        provider_message_id="tg-msg-42",
        provider_coordinates={"chat_id": "1", "message_id": "42"},
    )
    assert settled.status == "SENT"
    assert settled.provider_message_id == "tg-msg-42"
    assert settled.sent_at is not None
    assert settled.completed_at is not None
    assert settled.persisted == "memory"


def test_fail_closed_without_event_id():
    with pytest.raises(DeliveryGateError):
        reserve_delivery(event_id=None, channel="telegram")
    with pytest.raises(DeliveryGateError):
        reserve_delivery(event_id="  ", channel="telegram")
    with pytest.raises(DeliveryGateError):
        reserve_delivery(event_id="", channel="telegram")


def test_idempotent_reservation():
    event_id = _publish_outbound()
    # publish created one; attach again must collide
    first = attach_delivery_reservation(event_id, "telegram")
    second = attach_delivery_reservation(event_id, "telegram")
    third = reserve_delivery(event_id=event_id, channel="telegram", attempt_id="1")
    assert first.delivery_id == second.delivery_id == third.delivery_id
    assert second.duplicate is True
    assert third.duplicate is True
    assert len(memory_delivery_snapshot()) == 1

    # Distinct attempt_id is a new reservation
    retry = reserve_delivery(event_id=event_id, channel="telegram", attempt_id="2")
    assert retry.delivery_id != first.delivery_id
    assert retry.duplicate is False
    assert len(memory_delivery_snapshot()) == 2


def test_memory_fallback_works():
    # No DB in unit path → memory
    d = reserve_delivery(event_id="evt_test_memory", channel="telegram")
    assert d.persisted == "memory"
    assert d.status == "RESERVED"
    assert d.delivery_id and d.delivery_id.startswith("dlv_")
    assert d.idempotency_key and d.idempotency_key.startswith("didem_")
    assert d.adapter_version == "telegram@v1"
    snap = memory_delivery_snapshot()
    assert d.delivery_id in snap
    assert snap[d.delivery_id]["event_id"] == "evt_test_memory"


def test_status_transitions():
    d = reserve_delivery(event_id="evt_transitions", channel="telegram")
    assert d.status == "RESERVED"

    sending = settle_delivery(d.delivery_id, status="SENDING")
    assert sending.status == "SENDING"

    sent = settle_delivery(d.delivery_id, status="SENT", provider_message_id="m1")
    assert sent.status == "SENT"
    assert sent.provider_message_id == "m1"

    delivered = settle_delivery(d.delivery_id, status="DELIVERED")
    assert delivered.status == "DELIVERED"

    ack = settle_delivery(d.delivery_id, status="ACKNOWLEDGED")
    assert ack.status == "ACKNOWLEDGED"

    # Illegal: ACKNOWLEDGED → SENT
    with pytest.raises(DeliveryGateError) as ei:
        settle_delivery(d.delivery_id, status="SENT")
    assert "status_transition_illegal" in str(ei.value)

    # Failure path
    d2 = reserve_delivery(event_id="evt_fail", channel="telegram")
    failed = settle_delivery(
        d2.delivery_id,
        status="FAILED",
        error_taxonomy="provider.timeout",
    )
    assert failed.status == "FAILED"
    assert failed.error_taxonomy == "provider.timeout"
    assert failed.completed_at is not None

    # Retry may reopen FAILED → RESERVED
    reopened = settle_delivery(d2.delivery_id, status="RESERVED")
    assert reopened.status == "RESERVED"


def test_record_chunk():
    d = reserve_delivery(event_id="evt_chunk", channel="telegram")
    c0 = record_chunk(
        d.delivery_id,
        part_sequence=0,
        provider_message_id="m-part-0",
    )
    assert c0.part_sequence == 0
    assert c0.chunk_count >= 1
    assert c0.provider_message_id == "m-part-0"

    c1 = record_chunk(
        d.delivery_id,
        part_sequence=1,
        provider_message_id="m-part-1",
        provider_coordinates={"message_id": "m-part-1"},
    )
    assert c1.part_sequence == 1
    assert c1.chunk_count >= 2
    assert len(c1.chunks) == 2


def test_publish_auto_reserves_delivery_stubs():
    ev = CommunicationEvent(
        direction="OUTBOUND",
        event_type="health",
        message_class="operator_alert",
        producer="ops.watchdog",
        subject_key="system:watchdog",
        retention_class="ops_7d",
        sanitized_body="ok",
        channels=["telegram", "slack"],
    )
    result = publish_communication(ev)
    assert result.ok is True
    assert result.delivery_owned is False
    assert len(result.delivery_ids) == 2
    snap = memory_delivery_snapshot()
    assert len(snap) == 2
    channels = {row["channel"] for row in snap.values()}
    assert channels == {"telegram", "slack"}
    assert all(row["status"] == "RESERVED" for row in snap.values())
    assert all(row["event_id"] == result.event_id for row in snap.values())


def test_inbound_publish_skips_delivery_when_no_channels():
    ev = CommunicationEvent(
        direction="INBOUND",
        event_type="telegram_command",
        message_class="operator_command",
        producer="telegram_command_handler",
        subject_key="chat:1:cmd:status",
        retention_class="inbound_7d",
        sanitized_body="/status",
        channels=[],
    )
    result = publish_communication(ev)
    assert result.ok is True
    assert result.delivery_ids == []
    assert memory_delivery_snapshot() == {}
