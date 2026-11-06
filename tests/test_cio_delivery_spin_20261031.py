"""tradeai-cio-delivery spun a CPU core and delivered nothing (2026-10-31 stuck sweep).

Causes: list_notifications re-read the whole outbox once per stream; the default limit=50 was applied before the
advisory hold, hiding every older note; expire() was called without its required reason, the TypeError was
swallowed, so nothing ever expired. Hermetic: temp outbox, fake adapter, no network.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest

from scripts.lib import cio_notification_delivery as d
from scripts.lib.cio_notification_outbox import NotificationOutbox


class _Adapter:
    is_live = False

    def __init__(self):
        self.sent = []

    def send(self, notif):
        self.sent.append(notif["notification_id"])
        return {"delivered": True, "message_id": "1"}


def _enqueue(ob, nid, cls, created, expires):
    body = f"body {nid}"
    return ob.enqueue(
        {
            "notification_id": nid,
            "channel_targets": ["telegram"],
            "message_class": cls,
            "subject": nid,
            "body": body,
            "body_hash": hashlib.sha256(body.encode()).hexdigest(),
            "created_at": created.isoformat(),
            "expires_at": expires.isoformat(),
        },
        actor_id="test",
    )


@pytest.fixture()
def outbox(tmp_path, monkeypatch):
    cfg = tmp_path / "cio_delivery.json"
    cfg.write_text(json.dumps({"max_expiries_per_run": 200}))
    monkeypatch.setattr(d, "_DELIVERY_CONFIG", cfg)
    return NotificationOutbox(tmp_path / "outbox.jsonl")


def _worker(ob, monkeypatch, hold=True):
    monkeypatch.setattr("scripts.lib.advice_digest.hold", lambda key: hold, raising=False)
    w = d.CIONotificationDeliveryWorker.__new__(d.CIONotificationDeliveryWorker)
    w.outbox, w.adapter, w.mode = ob, _Adapter(), "test"
    return w


def test_list_notifications_reads_the_log_once(outbox, monkeypatch):
    now = datetime.now(timezone.utc)
    for i in range(30):
        _enqueue(outbox, f"n{i}", "advisory", now, now + timedelta(hours=1))
    reads = {"n": 0}
    real = outbox._iter_all_events

    def counted():
        reads["n"] += 1
        yield from real()

    monkeypatch.setattr(outbox, "_iter_all_events", counted)
    monkeypatch.setattr(outbox, "_get_stream_events", lambda sid: pytest.fail("per-stream re-read"))
    got = outbox.list_notifications(status="PENDING", limit=None)
    assert len(got) == 30 and reads["n"] == 1


def test_older_checkin_is_not_hidden_by_held_advisories(outbox, monkeypatch):
    now = datetime.now(timezone.utc)
    _enqueue(outbox, "old-checkin", "checkin", now - timedelta(hours=2), now + timedelta(hours=5))
    for i in range(60):  # newer held advisory notes, more than the old default limit of 50
        _enqueue(outbox, f"adv{i}", "advisory", now - timedelta(minutes=60 - i), now + timedelta(hours=5))
    w = _worker(outbox, monkeypatch)
    out = w.poll_and_deliver(max_deliveries=5)
    assert w.adapter.sent == ["old-checkin"] and out["delivered_count"] == 1


def test_overdue_notes_expire_with_a_reason_every_class(outbox, monkeypatch):
    now = datetime.now(timezone.utc)
    _enqueue(outbox, "stale-adv", "advisory", now - timedelta(days=3), now - timedelta(days=2))
    _enqueue(outbox, "stale-chk", "checkin", now - timedelta(days=3), now - timedelta(days=2))
    w = _worker(outbox, monkeypatch)
    out = w.poll_and_deliver(max_deliveries=5)
    assert out["expired_count"] == 2 and w.adapter.sent == []
    assert outbox.get_notification("stale-adv")["current_status"] == "EXPIRED"
    assert outbox.get_notification("stale-chk")["current_status"] == "EXPIRED"


def test_expiry_cap_comes_from_config(outbox, monkeypatch, tmp_path):
    cfg = tmp_path / "cap.json"
    cfg.write_text(json.dumps({"max_expiries_per_run": 1}))
    monkeypatch.setattr(d, "_DELIVERY_CONFIG", cfg)
    now = datetime.now(timezone.utc)
    for i in range(3):
        _enqueue(outbox, f"s{i}", "advisory", now - timedelta(days=3), now - timedelta(days=2))
    assert _worker(outbox, monkeypatch).poll_and_deliver()["expired_count"] == 1


def test_last_event_reads_the_tail(outbox):
    now = datetime.now(timezone.utc)
    for i in range(5):
        _enqueue(outbox, f"t{i}", "advisory", now, now + timedelta(hours=1))
    last = outbox._get_last_event()
    lines = [ln for ln in outbox.event_store_path.read_text().splitlines() if ln.strip()]
    assert last == json.loads(lines[-1])
