"""A repeated alert is a new communication, not the first one again. Offline (no DB).

2026-09-14: the idempotency key for a plain Telegram send was producer + event type + the first
48 characters + action. Every later alert that opened the same way collided with the first event
ever sent and inherited its delivery row. The 13:15 GO alerts that reached the operator stayed
SUPPRESSED from the 12:15 run; claude_escalation.log logged 14,163 illegal settles that day.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import telegram_alert  # noqa: E402
from scripts.lib.comms.adapters import from_plain_message  # noqa: E402

COVERS = []  # exercises the ledger identity of _best_effort_comms_publish, not a Telegram alarm

GO_1215 = "✅ GO ELMT — momentum scalp setup (screener)\nPrice $22.10 · RVOL 60.1x\nScan 0900"
GO_1315 = "✅ GO ELMT — momentum scalp setup (screener)\nPrice $23.13 · RVOL 79.7x\nScan 1000"


@pytest.fixture
def published(monkeypatch):
    events: list = []

    class _Pub:
        delivery_ids = ["d-1"]

    import scripts.lib.comms.client as client
    import scripts.lib.comms.delivery as delivery

    monkeypatch.setattr(client, "publish_communication", lambda ev, *a, **k: events.append(ev) or _Pub(), raising=False)
    monkeypatch.setattr(delivery, "settle_delivery", lambda *a, **k: None, raising=False)
    return events


def _key(event):
    return event.mint_identity().idempotency_key


def test_two_alerts_that_open_the_same_way_are_two_communications(published):
    telegram_alert._best_effort_comms_publish(GO_1215, message_class="operator_alert", delivered=False)
    telegram_alert._best_effort_comms_publish(GO_1315, message_class="operator_alert", delivered=True)
    assert len(published) == 2
    assert published[0].subject_key == published[1].subject_key  # grouping is unchanged
    assert _key(published[0]) != _key(published[1])


def test_the_observation_version_carries_the_body_hash_and_minute(published):
    telegram_alert._best_effort_comms_publish(GO_1315, message_class="operator_alert", delivered=True)
    version = published[0].observation_version
    assert version != "1" and "@" in version and len(version.split("@")[0]) == 16


def test_a_genuine_retry_of_the_same_text_in_the_same_minute_still_collides():
    a = from_plain_message(producer="p", body=GO_1315, subject_key="telegram:operator_alert:x")
    b = from_plain_message(producer="p", body=GO_1315, subject_key="telegram:operator_alert:x")
    a.observation_version = b.observation_version = "abcdef0123456789@20260914T1715"
    assert _key(a) == _key(b)


def test_without_the_version_the_old_collision_is_reproduced():
    a = from_plain_message(producer="p", body=GO_1215, subject_key="telegram:operator_alert:x")
    b = from_plain_message(producer="p", body=GO_1315, subject_key="telegram:operator_alert:x")
    assert _key(a) == _key(b)
