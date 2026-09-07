#!/usr/bin/env python3
"""Lane B replay determinism — mint → replay → collide (CampaignInterfaces@v1 §9)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.campaign_interfaces_b import (  # noqa: E402
    mint_communication_event_id,
    mint_receipt_id,
    mint_thread_id,
)
from scripts.lib.comms.agent_contracts import (  # noqa: E402
    emit_consumption_receipt,
    reset_agent_contracts_memory,
)


@pytest.fixture(autouse=True)
def _no_db(monkeypatch):
    monkeypatch.setattr("scripts.lib.comms.agent_contracts._db_conn", lambda: None)
    reset_agent_contracts_memory()
    yield
    reset_agent_contracts_memory()


def test_comm_event_id_mint_replay_collide():
    a = mint_communication_event_id("telegram", "chat:1", "msg:9", "2026-09-07T00:00:00Z")
    b = mint_communication_event_id("telegram", "chat:1", "msg:9", "2026-09-07T00:00:00Z")
    c = mint_communication_event_id("telegram", "chat:1", "msg:10", "2026-09-07T00:00:00Z")
    assert a == b
    assert a != c


def test_thread_id_mint_replay_collide():
    a = mint_thread_id("guid-a", "telegram", "evt-root")
    b = mint_thread_id("guid-a", "telegram", "evt-root")
    c = mint_thread_id("guid-b", "telegram", "evt-root")
    assert a == b
    assert a != c


def test_receipt_id_mint_replay_collide():
    a = mint_receipt_id("cio", "comm_event", "evt_1", "intake")
    b = mint_receipt_id("cio", "comm_event", "evt_1", "intake")
    c = mint_receipt_id("cio", "comm_event", "evt_2", "intake")
    assert a == b
    assert a != c
    assert a.startswith("acr_")

    r1 = emit_consumption_receipt(
        "cio",
        event_id="evt_replay_1",
        purpose="intake",
        provenance={"producer": "test"},
    )
    r2 = emit_consumption_receipt(
        "cio",
        event_id="evt_replay_1",
        purpose="intake",
        provenance={"producer": "test"},
    )
    assert r1.receipt_id == r2.receipt_id
    assert r1.receipt_id == mint_receipt_id("cio", "comm_event", "evt_replay_1", "intake")
