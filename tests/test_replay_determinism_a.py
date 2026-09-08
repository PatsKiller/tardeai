"""Lane A replay determinism — mint → replay → collide, byte-identical ids."""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT)]

from scripts.lib.persistent_wake_interfaces import (  # noqa: E402
    mint_commitment_id,
    mint_receipt_id,
    mint_view_id,
    mint_wake_id,
)
from scripts.lib.persistent_wake_schedule import ScheduleContract  # noqa: E402

NOW = datetime(2026, 9, 7, 19, 0, tzinfo=timezone.utc)
SG = "97172f54-916c-5960-aa73-f16321f1cf3e"


def test_wake_id_mint_replay_collide():
    slot = ScheduleContract("cio", "scheduled_persistent_review").slot_for(NOW)
    a = mint_wake_id("cio", "scheduled_persistent_review", slot, SG)
    b = mint_wake_id("cio", "scheduled_persistent_review", slot, SG)
    assert a == b
    assert a != mint_wake_id("hermes", "scheduled_persistent_review", slot, SG)
    assert a != mint_wake_id("cio", "other", slot, SG)


def test_commitment_and_receipt_ids_stable():
    slot = ScheduleContract("cio", "scheduled_persistent_review").slot_for(NOW)
    wid = mint_wake_id("cio", "scheduled_persistent_review", slot, SG)
    claim = "memory_digest:abc remains salient"
    c1 = mint_commitment_id(wid, SG, "MEMORY_SALIENCE", claim)
    c2 = mint_commitment_id(wid, SG, "MEMORY_SALIENCE", claim)
    assert c1 == c2
    r1 = mint_receipt_id("cio", "memory_fact", "f1", "wake_memory_load")
    r2 = mint_receipt_id("cio", "memory_fact", "f1", "wake_memory_load")
    assert r1 == r2
    v1 = mint_view_id("cio", SG, wid)
    assert v1 == mint_view_id("cio", SG, wid)
