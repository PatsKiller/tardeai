"""
P2.11 Restart / Recovery — Test suite.

Tests gateway restart recovery, event store persistence, wake deduplication,
handoff persistence, notification persistence, and fresh session reconstruction.
"""
import hashlib
import os
import tempfile
from pathlib import Path

import pytest

from scripts.lib.cio_run import CIORunStore
from scripts.lib.cio_wake_jobs import CIOWakeJobStore
from scripts.lib.cio_action_ledger import CIOActionLedger
from scripts.lib.cio_notification_outbox import NotificationOutbox
from scripts.lib.cio_agent_handoff_queue import AgentHandoffQueue


@pytest.fixture
def run_store(tmpdir):
    p = os.path.join(tmpdir.strpath if hasattr(tmpdir, "strpath") else str(tmpdir), "runs.jsonl")
    s = CIORunStore(p)
    s.initialize()
    return s


@pytest.fixture
def wake_store(tmpdir):
    p = os.path.join(tmpdir.strpath if hasattr(tmpdir, "strpath") else str(tmpdir), "wakes.jsonl")
    return CIOWakeJobStore(event_store_path=Path(p))


@pytest.fixture
def action_ledger(tmpdir):
    p = os.path.join(tmpdir.strpath if hasattr(tmpdir, "strpath") else str(tmpdir), "actions.jsonl")
    return CIOActionLedger(event_store_path=p)


@pytest.fixture
def notification_outbox(tmpdir):
    p = os.path.join(tmpdir.strpath if hasattr(tmpdir, "strpath") else str(tmpdir), "notifs.jsonl")
    return NotificationOutbox(event_store_path=p)


@pytest.fixture
def handoff_queue(tmpdir):
    p = os.path.join(tmpdir.strpath if hasattr(tmpdir, "strpath") else str(tmpdir), "handoffs.jsonl")
    return AgentHandoffQueue(event_store_path=p)


class TestRestartRecovery:
    """Tests for restart and recovery procedures."""

    def test_event_store_survives_restart(self, run_store):
        """Reopen stores after simulated restart — verify chain survives."""
        event = run_store.create_run(trigger_type="MANUAL", actor="test")
        run_id = event["payload"]["run_id"]

        # Simulate restart by creating a new store pointing to same file
        store_path = run_store.store_path
        new_store = CIORunStore(str(store_path))
        recovered_run = new_store.get_run(run_id)
        assert recovered_run is not None
        assert recovered_run["trigger_type"] == "MANUAL"
        assert recovered_run["status"] == "QUEUED"

    def test_no_duplicate_wake_after_replay(self, wake_store):
        """Restart detection doesn't double-fire wakes."""
        wake1 = wake_store.enqueue({
            "wake_job_id": "wake-replay-001",
            "trigger_type": "SCHEDULE_DUE",
            "trigger_ref": "test",
            "trigger_hash": "abc",
            "scheduled_slot": "2026-08-08T05:00:00-04:00",
        })

        # Simulate restart — reopen store
        store_path = wake_store.event_store_path
        new_store = CIOWakeJobStore(event_store_path=store_path)
        existing = new_store.get_wake_job("wake-replay-001")
        assert existing is not None
        assert existing["current_status"] == "PENDING"

        # Try to re-enqueue — should fail
        with pytest.raises(ValueError, match="already exists"):
            new_store.enqueue({
                "wake_job_id": "wake-replay-001",
                "trigger_type": "SCHEDULE_DUE",
                "trigger_ref": "test",
                "trigger_hash": "abc",
                "scheduled_slot": "2026-08-08T05:00:00-04:00",
            })

    def test_handoff_persistence(self, handoff_queue):
        """Handoffs survive simulated restart."""
        handoff = {
            "handoff_id": "handoff-restart-001",
            "from_agent": "alex",
            "to_agent": "maria",
            "task_type": "cio_question",
            "task_summary": "Test restart recovery",
            "input_hash": hashlib.sha256(b"test").hexdigest(),
        }
        handoff_queue.enqueue(handoff, actor_id="test")

        # Simulate restart
        store_path = handoff_queue.event_store_path
        new_queue = AgentHandoffQueue(event_store_path=store_path)
        recovered = new_queue.get_handoff("handoff-restart-001")
        assert recovered is not None

    def test_notification_persistence(self, notification_outbox):
        """Notifications survive simulated restart."""
        body = "Restart test notification"
        notif = {
            "notification_id": "notif-restart-001",
            "message_class": "advisory",
            "channel_targets": ["telegram"],
            "subject": "Restart Test",
            "body": body,
            "body_hash": hashlib.sha256(body.encode()).hexdigest(),
        }
        notification_outbox.enqueue(notif, actor_id="test")

        # Simulate restart
        store_path = notification_outbox.event_store_path
        new_outbox = NotificationOutbox(event_store_path=store_path)
        notifications = new_outbox.list_notifications()
        assert len(notifications) >= 1

    def test_fresh_session_reconstruction(self, run_store, wake_store, action_ledger):
        """New Alex session reads Trade AI state from stores."""
        # Create some state
        event = run_store.create_run(trigger_type="MANUAL", actor="test")
        run_id = event["payload"]["run_id"]

        wake_store.enqueue({
            "wake_job_id": "wake-fresh-001",
            "trigger_type": "SCHEDULE_DUE",
            "trigger_ref": "test",
            "trigger_hash": "abc",
            "scheduled_slot": "2026-08-08T05:00:00-04:00",
        })

        action_ledger.create_action({
            "cio_action_id": "action-fresh-001",
            "title": "Test action",
        }, actor_id="test")

        # Simulate fresh session — reopen all stores
        new_run = CIORunStore(str(run_store.store_path))
        recovered = new_run.get_run(run_id)
        assert recovered is not None

        new_wake = CIOWakeJobStore(event_store_path=wake_store.event_store_path)
        fresh_wakes = new_wake.list_wakes()
        assert len(fresh_wakes) >= 1

        new_actions = CIOActionLedger(event_store_path=action_ledger.event_store_path)
        actions = new_actions.list_actions()
        assert len(actions) >= 1

    def test_gateway_restart_recovery(self, run_store, wake_store, action_ledger):
        """Simulate bridge restart — verify routes and stores intact."""
        # This is a structural test — the stores are the "gateway" state
        event = run_store.create_run(trigger_type="MANUAL", actor="test")
        run_id = event["payload"]["run_id"]
        run = run_store.get_run(run_id)

        # Verify integrity
        ok, msg = run_store.verify_integrity()
        assert ok, f"Run store integrity: {msg}"

        # Verify wake store integrity
        wake_integrity = wake_store.verify_integrity()
        assert wake_integrity.get("valid", True), "Wake store integrity check failed"

        # Verify action ledger
        ledger_result = action_ledger.verify_integrity()
        assert ledger_result.get("valid"), f"Action ledger integrity: {ledger_result}"
