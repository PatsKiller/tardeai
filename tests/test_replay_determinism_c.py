"""Lane C replay determinism — mint → replay → collide."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.lib.campaign_interfaces_c import (
    mint_research_object_id,
    mint_consumption_receipt_id,
)
from scripts.lib.research_object import build_research_object
from scripts.lib.brave_router import reserve
from scripts.lib.search_budget import refund


CLOCK = lambda: datetime(2026, 9, 7, 16, 0, tzinfo=timezone.utc)


def test_research_object_id_replay_identical():
    kwargs = dict(
        source_url="https://www.reuters.com/markets/v-replay",
        title="t",
        body="b",
        primary_symbol="V",
        primary_subject_guid="guid-v",
        published_at="2026-09-07T00:00:00Z",
        clock=CLOCK,
        producer="test",
        source_sha="fixture",
    )
    a = build_research_object(**kwargs)
    b = build_research_object(**kwargs)
    assert a.research_id == b.research_id
    assert a.content_hash == b.content_hash
    assert a.idempotency_key == a.research_id


def test_receipt_id_replay_identical():
    a = mint_consumption_receipt_id("agent", "research_object", "rid-1", "wake_research")
    b = mint_consumption_receipt_id("agent", "research_object", "rid-1", "wake_research")
    assert a == b


def test_reservation_idempotency_collision(tmp_path):
    (tmp_path / "data" / "runtime").mkdir(parents=True)
    r1 = reserve(
        caller="t", purpose="p", idempotency_key="same-key",
        clock=CLOCK, root=tmp_path,
    )
    r2 = reserve(
        caller="t", purpose="p", idempotency_key="same-key",
        clock=CLOCK, root=tmp_path,
    )
    assert r1.reservation_id == r2.reservation_id
    assert r1.state == r2.state == "RESERVED"
