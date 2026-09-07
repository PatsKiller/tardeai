#!/usr/bin/env python3
"""Lane B public same-subject history interface (comms_memory)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import scripts.lib.comms.mode as mode_mod  # noqa: E402
from scripts.lib.comms.client import publish_communication, reset_memory_store  # noqa: E402
from scripts.lib.comms.event import CommunicationEvent  # noqa: E402
from scripts.lib.comms.subject_memory import (  # noqa: E402
    attach_event_to_subject,
    reset_subject_memory,
)
from scripts.lib.comms_memory import (  # noqa: E402
    already_said,
    normalized_hash,
    retrieve_same_subject_history,
)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv("COMMS_GATEWAY_MODE", raising=False)
    mode_mod._cache["mode"] = None
    mode_mod._cache["why"] = None
    monkeypatch.setattr("scripts.lib.comms.client._db_conn", lambda: None)
    monkeypatch.setattr("scripts.lib.comms.delivery._db_conn", lambda: None)
    monkeypatch.setattr("scripts.lib.comms.subject_memory._db_conn", lambda: None)
    reset_memory_store()
    reset_subject_memory()
    yield
    reset_memory_store()
    reset_subject_memory()


def _publish(
    subject_key: str,
    body: str,
    *,
    eligible: str = "eligible",
    observation_version: str = "1",
) -> str:
    ev = CommunicationEvent(
        direction="OUTBOUND",
        event_type="operator_message",
        message_class="ops",
        producer="test",
        subject_key=subject_key,
        retention_class="operational_30d",
        sanitized_body=body,
        short_summary=body[:80],
        knowledge_eligibility=eligible,
        channels=["telegram"],
        provenance={"producer": "test"},
        observation_version=observation_version,
    )
    pub = publish_communication(ev)
    assert pub.ok and pub.event_id
    attach_event_to_subject(pub.event_id, subject_key, channel="telegram")
    return pub.event_id


def test_retrieve_same_subject_history_and_supply_record():
    a = _publish("sym:NOC", "NOC up 5%", observation_version="1")
    b = _publish("sym:NOC", "NOC filing noted", observation_version="2")
    supply = retrieve_same_subject_history("sym:NOC", eligible_only=False, limit=10)
    assert supply.hit_count >= 2
    assert a in supply.event_ids and b in supply.event_ids
    d = supply.to_dict()
    assert d["hit_count"] == supply.hit_count
    assert set(d["event_ids"]) == set(supply.event_ids)


def test_excludes_unrelated_subject_history():
    _publish("sym:NOC", "about NOC")
    other = _publish("sym:AAPL", "about AAPL")
    supply = retrieve_same_subject_history("sym:NOC", eligible_only=False)
    assert other not in supply.event_ids
    assert all(e.get("subject_key") == "sym:NOC" for e in supply.events)


def test_normalized_hash_buckets_precision_keeps_magnitude():
    assert normalized_hash("NOC up 12.5%") == normalized_hash("NOC up 12.53%")
    assert normalized_hash("NOC up 5%") != normalized_hash("NOC up 90%")


def test_already_said_detects_repeat():
    _publish("sym:NOC", "NOC up 5%")
    is_repeat, evidence = already_said("sym:NOC", "NOC up 5.0%")
    assert is_repeat is True
    assert evidence["prior_event_id"]
