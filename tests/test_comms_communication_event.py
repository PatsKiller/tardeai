#!/usr/bin/env python3
"""Unit tests for CommunicationEvent identity, idempotency, and fail-closed gates."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.comms.client import (  # noqa: E402
    publish_communication,
    reset_memory_store,
    memory_store_snapshot,
)
from scripts.lib.comms.event import CommunicationEvent, required_missing  # noqa: E402
from scripts.lib.comms.identity import idempotency_key_for, new_event_id  # noqa: E402
from scripts.lib.comms.mode import MODE_OFF, get_gateway_mode, mode_diagnostics  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_mem(monkeypatch):
    monkeypatch.delenv("COMMS_GATEWAY_MODE", raising=False)
    # Same defect as the other comms suites: this asserts the in-memory ledger,
    # and on a box where localhost Postgres answers the DB branch wins — the
    # assertions fail and the run writes to production.
    monkeypatch.setattr("scripts.lib.comms.client._db_conn", lambda: None)
    monkeypatch.setattr("scripts.lib.comms.subject_memory._db_conn", lambda: None)
    reset_memory_store()
    yield
    reset_memory_store()


def test_new_event_id_unique_and_string():
    a, b = new_event_id(), new_event_id()
    assert isinstance(a, str) and isinstance(b, str)
    assert a != b
    assert len(a) >= 32


def test_idempotency_key_stable():
    k1 = idempotency_key_for(
        producer="ops.health",
        event_type="pipeline_stale",
        subject_key="system:pipeline",
        intended_action="notify",
        entity_refs={"component": "pipeline"},
        observation_version="1",
    )
    k2 = idempotency_key_for(
        producer="ops.health",
        event_type="pipeline_stale",
        subject_key="system:pipeline",
        intended_action="notify",
        entity_refs={"component": "pipeline"},
        observation_version="1",
    )
    k3 = idempotency_key_for(
        producer="ops.health",
        event_type="pipeline_stale",
        subject_key="system:pipeline",
        intended_action="notify",
        entity_refs={"component": "pipeline"},
        observation_version="2",
    )
    assert k1 == k2
    assert k1 != k3
    assert k1.startswith("idem_")


def test_gateway_mode_defaults_off():
    assert get_gateway_mode(refresh=True) == MODE_OFF
    d = mode_diagnostics(refresh=True)
    assert d["mode"] == MODE_OFF
    assert d["delivery_owner"] == "legacy_or_none"


def test_fail_closed_missing_retention():
    ev = CommunicationEvent(
        direction="OUTBOUND",
        event_type="x",
        message_class="operator_alert",
        producer="test",
        subject_key="s",
        retention_class="",
    )
    assert "retention_class" in required_missing(ev)
    result = publish_communication(ev)
    assert result.ok is False
    assert any("retention_class" in e for e in result.errors)
    assert result.delivery_owned is False
    assert result.persisted == "none"


def test_fail_closed_approval_requires_protected_facts():
    ev = CommunicationEvent(
        direction="OUTBOUND",
        event_type="live_order_2fa_required",
        message_class="approval",
        producer="broker.approvals",
        subject_key="approval:order:1",
        retention_class="approval_ttl",
        channels=["telegram"],
    )
    missing = required_missing(ev)
    assert "protected_facts" in missing
    assert "authoritative_sources" in missing


def test_publish_mints_event_id_before_persist():
    ev = CommunicationEvent(
        direction="OUTBOUND",
        event_type="health",
        message_class="operator_alert",
        producer="ops.watchdog",
        subject_key="system:watchdog",
        retention_class="ops_7d",
        sanitized_body="watchdog ok",
        channels=["telegram"],
    )
    assert ev.event_id is None
    result = publish_communication(ev)
    assert result.ok is True
    assert result.event_id
    assert result.idempotency_key
    assert result.persisted == "memory"
    assert result.delivery_owned is False
    assert ev.event_id == result.event_id
    snap = memory_store_snapshot()
    assert result.event_id in snap


def test_publish_idempotent_duplicate():
    def make():
        return CommunicationEvent(
            direction="OUTBOUND",
            event_type="health",
            message_class="operator_alert",
            producer="ops.watchdog",
            subject_key="system:watchdog",
            retention_class="ops_7d",
            sanitized_body="watchdog ok",
            observation_version="v1",
            channels=["telegram"],
        )

    r1 = publish_communication(make())
    r2 = publish_communication(make())
    assert r1.ok and r2.ok
    assert r1.event_id == r2.event_id
    assert r2.duplicate is True
    assert len(memory_store_snapshot()) == 1


def test_publish_never_sets_delivery_owned(monkeypatch):
    monkeypatch.setenv("COMMS_GATEWAY_MODE", "ACTIVE")
    # Even if mode is ACTIVE, Phase 1 client must not claim delivery ownership.
    from scripts.lib.comms import mode as mode_mod

    mode_mod._cache["mode"] = None
    ev = CommunicationEvent(
        direction="OUTBOUND",
        event_type="health",
        message_class="operator_alert",
        producer="ops.watchdog",
        subject_key="system:watchdog",
        retention_class="ops_7d",
        channels=["telegram"],
        sanitized_body="x",
    )
    result = publish_communication(ev)
    assert result.ok is True
    assert result.gateway_mode == "ACTIVE"
    assert result.delivery_owned is False


def test_inbound_does_not_require_channels():
    ev = CommunicationEvent(
        direction="INBOUND",
        event_type="telegram_command",
        message_class="operator_command",
        producer="telegram_command_handler",
        subject_key="chat:123:cmd:status",
        retention_class="inbound_7d",
        sanitized_body="/status",
        channels=[],
    )
    assert "delivery_channels" not in required_missing(ev)
    result = publish_communication(ev)
    assert result.ok is True
