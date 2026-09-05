#!/usr/bin/env python3
"""Unit tests for the inbound half of the Communications Gateway (Wave C).

Follows the pattern of tests/test_comms_delivery_ledger.py: the autouse fixture
stubs every comms `_db_conn` so the suite never touches production Postgres and
exercises the durable *file-backed* checkpoint/quarantine path under tmp_path.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.comms.client import (  # noqa: E402
    reset_memory_store,
)
from scripts.lib.comms.delivery import (  # noqa: E402
    reset_memory_deliveries,
)
from scripts.lib.comms.event import CommunicationEvent  # noqa: E402
from scripts.lib.comms.inbound import (  # noqa: E402
    DEFAULT_MESSAGE_CLASS,
    RETENTION_CLASS,
    InboundGateError,
    build_inbound_event,
    claim_update,
    commit_checkpoint,
    get_checkpoint_offset,
    is_update_already_processed,
    list_quarantined,
    quarantine_callback,
    reset_inbound_state,
)
from scripts.lib.comms.vocabulary import normalize_message_class  # noqa: E402


@pytest.fixture(autouse=True)
def _clean(monkeypatch, tmp_path):
    monkeypatch.delenv("COMMS_GATEWAY_MODE", raising=False)
    # Same defect as tests/test_comms_delivery_ledger.py: on a box where
    # localhost Postgres answers, the DB branch wins and the assertions fail AND
    # the run writes into production. Stub every comms _db_conn to force the
    # in-memory / file-backed path.
    monkeypatch.setattr("scripts.lib.comms.client._db_conn", lambda: None)
    monkeypatch.setattr("scripts.lib.comms.delivery._db_conn", lambda: None)
    monkeypatch.setattr("scripts.lib.comms.subject_memory._db_conn", lambda: None)
    monkeypatch.setattr("scripts.lib.comms.inbound._db_conn", lambda: None)
    # Point the durable file-backed checkpoint/quarantine at a fresh tmp dir.
    monkeypatch.setenv("COMMS_INBOUND_STATE_DIR", str(tmp_path))
    reset_inbound_state()
    reset_memory_store()
    reset_memory_deliveries()
    yield
    reset_inbound_state()
    reset_memory_store()
    reset_memory_deliveries()


# ── build_inbound_event ────────────────────────────────────────────────────────


def _message_update(**overrides) -> dict:
    update = {
        "update_id": 1001,
        "message": {
            "message_id": 77,
            "chat": {"id": 555},
            "from": {"id": 1, "first_name": "John"},
            "text": "/status",
        },
    }
    update.update(overrides)
    return update


def _callback_update(**overrides) -> dict:
    update = {
        "update_id": 2002,
        "callback_query": {
            "id": "cb-abc-123",
            "from": {"id": 1, "first_name": "John"},
            "message": {
                "message_id": 88,
                "chat": {"id": 555},
                "reply_to_message": {"message_id": 66},
            },
            "data": "ptapprove:42",
        },
    }
    update.update(overrides)
    return update


def test_build_inbound_event_message_shape():
    ev = build_inbound_event(_message_update())
    assert isinstance(ev, CommunicationEvent)
    assert ev.direction == "INBOUND"
    assert ev.event_type == "telegram_command"
    assert ev.message_class == "operator_command"
    assert ev.retention_class == RETENTION_CLASS == "inbound_7d"
    assert ev.producer == "telegram_inbound"
    assert ev.subject_key == "telegram:inbound:555:77"
    assert ev.event_id  # minted
    assert ev.idempotency_key
    coords = ev.provider_coordinates
    assert coords["chat_id"] == "555"
    assert coords["message_id"] == 77
    assert coords["update_id"] == 1001
    assert coords["callback_query_id"] is None
    assert "reply_to_message_id" in coords
    assert "bot_id" in coords


def test_build_inbound_event_callback_query_shape():
    ev = build_inbound_event(_callback_update())
    assert ev.direction == "INBOUND"
    assert ev.event_type == "callback_query"
    assert ev.subject_key == "telegram:inbound:555:88"
    coords = ev.provider_coordinates
    assert coords["callback_query_id"] == "cb-abc-123"
    assert coords["reply_to_message_id"] == 66
    assert coords["update_id"] == 2002
    assert coords["message_id"] == 88


def test_build_inbound_event_deterministic_subject_and_idempotency():
    a = build_inbound_event(_message_update())
    b = build_inbound_event(_message_update())
    assert a.subject_key == b.subject_key
    # idempotency key derives from the deterministic subject_key, so a replay
    # of the same update collides rather than minting a new logical event.
    assert a.idempotency_key == b.idempotency_key
    assert a.event_id != b.event_id  # distinct ids, same logical key


def test_build_inbound_event_normalizes_message_class():
    # Reuses normalize_message_class: alias collapses to canonical, unknown
    # passes through unchanged.
    ev = build_inbound_event(_message_update(message_class="health"))
    assert ev.message_class == "ops"
    assert normalize_message_class("health") == "ops"
    # Default stays canonical.
    assert build_inbound_event(_message_update()).message_class == "operator_command"
    assert normalize_message_class(DEFAULT_MESSAGE_CLASS) == "operator_command"


def test_build_inbound_event_rejects_empty_update():
    with pytest.raises(InboundGateError):
        build_inbound_event({"update_id": 5})


# ── checkpoint: claim / commit / replay denial ─────────────────────────────────


def test_claim_update_replay_denial():
    claim = claim_update(10)
    assert claim.already_processed is False
    assert claim.checkpoint_offset == 0

    commit_checkpoint(10)
    assert get_checkpoint_offset() == 10

    again = claim_update(10)
    assert again.already_processed is True
    assert is_update_already_processed(10) is True


def test_commit_checkpoint_atomicity_crash_before_commit_does_not_lose_update():
    # Claim an update, then "crash" before committing (no commit_checkpoint).
    assert claim_update(7).already_processed is False
    assert get_checkpoint_offset() == 0  # offset did NOT advance on claim

    # A fresh poll re-fetches update 7 because the offset never moved.
    assert claim_update(7).already_processed is False  # update is NOT lost

    # Only commit advances; after commit the replay is denied.
    new_offset = commit_checkpoint(7)
    assert new_offset == 7
    assert get_checkpoint_offset() == 7
    assert claim_update(7).already_processed is True
    assert is_update_already_processed(7) is True


def test_commit_checkpoint_is_monotonic():
    assert commit_checkpoint(5) == 5
    assert commit_checkpoint(3) == 5  # never moves backwards
    assert commit_checkpoint(9) == 9
    assert get_checkpoint_offset() == 9


def test_replay_denial_negative_control():
    # Negative control: before any processing the detector reads False.
    assert not is_update_already_processed(99)
    # Positive control: inject a known commit, confirm the detector flips.
    commit_checkpoint(99)
    assert is_update_already_processed(99)
    assert not is_update_already_processed(100)


def test_claim_update_requires_valid_id():
    with pytest.raises(InboundGateError):
        claim_update(None)
    with pytest.raises(InboundGateError):
        commit_checkpoint(-1)


# ── callback quarantine ────────────────────────────────────────────────────────


def test_quarantine_orphan_callback():
    coords = {
        "chat_id": "555",
        "message_id": 88,
        "callback_query_id": "cb-orphan",
        "update_id": 3003,
    }
    row = quarantine_callback("unresolved_callback:no_matching_proposal", coords, 3003)
    assert row["update_id"] == 3003
    assert row["reason"] == "unresolved_callback:no_matching_proposal"
    assert row["provider_coordinates"]["callback_query_id"] == "cb-orphan"
    assert row["resolved"] is False

    listed = list_quarantined()
    assert len(listed) == 1
    assert listed[0]["update_id"] == 3003


def test_quarantine_callback_idempotent_on_update_id():
    quarantine_callback("reason_a", {"callback_query_id": "cb-1"}, 42)
    again = quarantine_callback("reason_b", {"callback_query_id": "cb-1"}, 42)
    # Replay of the same update returns the existing row, not a second row.
    assert again["reason"] == "reason_a"
    assert len(list_quarantined()) == 1


def test_quarantine_requires_reason():
    with pytest.raises(InboundGateError):
        quarantine_callback("", {}, 10)
    with pytest.raises(InboundGateError):
        quarantine_callback(None, {}, 10)
