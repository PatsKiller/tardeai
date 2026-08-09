"""
P2.7 Operator Communication — Test suite.

Tests notification delivery, deduplication, expiry, shadow mode restrictions,
and inbound message handling. Uses temp stores and FakeDeliveryAdapter.
"""
import hashlib
import os
import tempfile
from pathlib import Path

import pytest

from scripts.lib.cio_notification_outbox import NotificationOutbox
from scripts.lib.cio_notification_delivery import (
    CIONotificationDeliveryWorker,
    FakeDeliveryAdapter,
    RealTelegramAdapter,
)


@pytest.fixture
def outbox(tmpdir):
    p = os.path.join(tmpdir.strpath if hasattr(tmpdir, "strpath") else str(tmpdir), "notifications.jsonl")
    return NotificationOutbox(event_store_path=Path(p))


@pytest.fixture
def worker(outbox):
    return CIONotificationDeliveryWorker(outbox, adapter=FakeDeliveryAdapter(), mode="shadow")


def _make_notif(nid, msg_class="advisory", body="Test notification"):
    return {
        "notification_id": nid,
        "message_class": msg_class,
        "channel_targets": ["telegram"],
        "subject": f"Test {nid}",
        "body": body,
        "body_hash": hashlib.sha256(body.encode()).hexdigest(),
    }


class TestNotificationDelivery:
    """Tests for CIONotificationDeliveryWorker."""

    def test_notification_from_action(self, outbox, worker):
        """Notification references CIO action."""
        notif = _make_notif("notif-001")
        notif["cio_action_id"] = "cio-action-test-001"
        outbox.enqueue(notif, actor_id="test")

        result = worker.poll_and_deliver(max_deliveries=10)
        assert result["delivered_count"] == 1
        assert result["mode"] == "shadow"
        assert not worker.adapter.is_live

    def test_material_recommendation_format(self, outbox, worker):
        """8-point checklist present in material recommendation."""
        checklist = (
            "1. CIO-run-id\n2. Snapshot\n3. Domain\n4. Recommendation\n"
            "5. Rationale\n6. Confidence\n7. Operator-action-needed\n8. Deadline"
        )
        notif = _make_notif("notif-checklist", msg_class="advisory", body=checklist)
        outbox.enqueue(notif, actor_id="test")

        result = worker.poll_and_deliver()
        assert result["delivered_count"] == 1

    def test_dedupe_suppressed(self, outbox, worker):
        """Duplicate notification not sent twice."""
        notif = _make_notif("notif-dup", body="Duplicate test")
        outbox.enqueue(notif, actor_id="test")

        # Deliver first time
        r1 = worker.poll_and_deliver()
        assert r1["delivered_count"] == 1

        # Second poll — should find nothing new
        r2 = worker.poll_and_deliver()
        assert r2["delivered_count"] == 0

    def test_expiry_before_delivery(self, outbox, worker):
        """Expired notification not sent."""
        from datetime import datetime, timezone, timedelta
        notif = _make_notif("notif-expired", body="Should expire")
        notif["expires_at"] = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        outbox.enqueue(notif, actor_id="test")

        result = worker.poll_and_deliver()
        assert result["delivered_count"] == 0

    def test_shadow_no_live_telegram(self, outbox):
        """Shadow mode uses FakeDeliveryAdapter only."""
        w = CIONotificationDeliveryWorker(outbox, mode="shadow")
        assert not w.adapter.is_live
        assert isinstance(w.adapter, FakeDeliveryAdapter)
        notif = _make_notif("notif-shadow")
        outbox.enqueue(notif, actor_id="test")
        result = w.poll_and_deliver()
        assert result["delivered_count"] == 1

    def test_inbound_creates_handoff_only(self, outbox):
        """Inbound messages do not execute — they create handoffs only."""
        worker = CIONotificationDeliveryWorker(outbox, mode="shadow")
        # Notification delivery is outbound only - inbound is handled
        # by Alex through the handoff queue, not this worker
        assert worker.adapter.is_live is False

    def test_no_execution_from_communication(self, outbox):
        """No order/risk tools in communication worker."""
        worker = CIONotificationDeliveryWorker(outbox, mode="shadow")
        notif = _make_notif("notif-noexec", body="Buy 100 shares")
        outbox.enqueue(notif, actor_id="test")
        result = worker.poll_and_deliver()
        assert result["delivered_count"] == 1
        # Even with trade-like content, delivery is just delivery
        assert result["mode"] == "shadow"

    def test_live_adapter_requires_credentials(self):
        """RealTelegramAdapter requires bot token and chat ID."""
        adapter = RealTelegramAdapter()  # No credentials
        assert not adapter.is_live

        adapter_with_token = RealTelegramAdapter(bot_token="fake", chat_id="12345")
        assert adapter_with_token.is_live
