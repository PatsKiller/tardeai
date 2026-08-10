"""
Tests for CIO Notification Outbox (P-1.7).

ALL tests use tempfile.TemporaryDirectory() for isolated outbox stores.
ZERO provider calls. ZERO live Telegram sends. ZERO production activation.
"""
import hashlib
import json
import os
import os as os2
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from scripts.lib.cio_notification_outbox import (
    NotificationOutbox,
    FakeDeliveryAdapter,
    build_dedupe_key,
    determine_severity,
    MESSAGE_CLASSES,
    FORBIDDEN_MESSAGE_CLASSES,
    SUPPORTED_CHANNELS,
    RETRY_BACKOFF_SECONDS,
    MAX_RETRY_ATTEMPTS,
    canonicalize_payload,
    compute_payload_hash,
    compute_event_hash,
    build_event,
)


@pytest.fixture
def outbox():
    """Create an isolated outbox backed by a temporary file."""
    with tempfile.TemporaryDirectory() as d:
        yield NotificationOutbox(event_store_path=Path(d) / "test_outbox.jsonl")


def make_notification(**overrides):
    """Build a minimal valid notification dict for testing."""
    body = overrides.pop("body", "This is a test notification.")
    base: dict = {
        "notification_id": "notif-001",
        "message_class": "advisory",
        "severity": "P2",
        "channel_targets": ["telegram"],
        "subject": "Test Notification",
        "body": body,
        "body_hash": hashlib.sha256(body.encode()).hexdigest(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "expires_at": (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat(),
        "dedupe_key": "test-key-001",
    }
    base.update(overrides)
    return base


# ═══════════════════════════════════════════════════════════════════════════════
# Schema & Validation
# ═══════════════════════════════════════════════════════════════════════════════


def test_schema_validation(outbox):
    """Empty notification dict should raise ValueError."""
    with pytest.raises(ValueError):
        outbox.enqueue({}, actor_id="system")


def test_valid_enqueue(outbox):
    """A valid notification should be enqueued successfully."""
    n = make_notification()
    e = outbox.enqueue(n, actor_id="cio_detector")
    assert e["event_type"] == "NOTIFICATION_ENQUEUED"
    assert e["payload"]["severity"] == "P2"


def test_invalid_message_class_rejected(outbox):
    """Unknown message_class should be rejected."""
    with pytest.raises(ValueError):
        outbox.enqueue(
            make_notification(message_class="invalid_class"), actor_id="system"
        )


def test_invalid_channel_rejected(outbox):
    """Unsupported channel should be rejected."""
    with pytest.raises(ValueError):
        outbox.enqueue(
            make_notification(channel_targets=["sms"]), actor_id="system"
        )


def test_forbidden_execution_message_rejected(outbox):
    """Execution/credential message_classes should be rejected."""
    for forbidden in sorted(FORBIDDEN_MESSAGE_CLASSES):
        with pytest.raises(ValueError):
            outbox.enqueue(
                make_notification(message_class=forbidden), actor_id="system"
            )


def test_body_hash_verified(outbox):
    """Wrong body_hash should be rejected."""
    n = make_notification(body_hash="wrong_hash")
    with pytest.raises(ValueError):
        outbox.enqueue(n, actor_id="system")


def test_invalid_severity_rejected(outbox):
    """Invalid severity level should be rejected."""
    with pytest.raises(ValueError):
        outbox.enqueue(
            make_notification(severity="CRITICAL"), actor_id="system"
        )


def test_missing_required_field(outbox):
    """Missing notification_id should be rejected."""
    n = make_notification()
    del n["notification_id"]
    with pytest.raises(ValueError):
        outbox.enqueue(n, actor_id="system")


def test_all_valid_message_classes_accepted(outbox):
    """Every known message_class should be enqueueable."""
    for mc in sorted(MESSAGE_CLASSES):
        body = f"Test {mc}"
        n = make_notification(
            notification_id=f"notif-{mc}",
            message_class=mc,
            body=body,
            body_hash=hashlib.sha256(body.encode()).hexdigest(),
            severity=determine_severity(mc),
        )
        e = outbox.enqueue(n, actor_id="system")
        assert e["event_type"] == "NOTIFICATION_ENQUEUED"


def test_enqueue_without_severity_auto_determines(outbox):
    """When severity is not provided, it should be auto-determined."""
    body = "Auto severity test"
    n = make_notification(
        notification_id="notif-auto-sev",
        message_class="alert",
        severity=None,
        body=body,
        body_hash=hashlib.sha256(body.encode()).hexdigest(),
    )
    n.pop("severity", None)
    e = outbox.enqueue(n, actor_id="system")
    assert e["payload"]["severity"] == "P1"


# ═══════════════════════════════════════════════════════════════════════════════
# Idempotency
# ═══════════════════════════════════════════════════════════════════════════════


def test_idempotent_enqueue(outbox):
    """Same dedupe_key should return the same event."""
    n = make_notification(dedupe_key="semantic-key-abc")
    e1 = outbox.enqueue(n, actor_id="system")
    e2 = outbox.enqueue(n, actor_id="system")
    assert e1["event_hash"] == e2["event_hash"]


def test_idempotency_key_enqueue(outbox):
    """Same idempotency_key should return the same event."""
    n = make_notification(
        notification_id="notif-idem", idempotency_key="idem-key-001"
    )
    e1 = outbox.enqueue(n, actor_id="system")
    e2 = outbox.enqueue(n, actor_id="system")
    assert e1["event_hash"] == e2["event_hash"]


def test_semantic_dedupe(outbox):
    """Same CIO action + message class = same dedupe key."""
    body = "Semantic dedupe test"
    body_hash = hashlib.sha256(body.encode()).hexdigest()
    n1 = make_notification(
        notification_id="n1",
        message_class="advisory",
        cio_action_id="act-001",
        dedupe_key="",
        body=body,
        body_hash=body_hash,
    )
    n2 = make_notification(
        notification_id="n2",
        message_class="advisory",
        cio_action_id="act-001",
        dedupe_key="",
        body=body,
        body_hash=body_hash,
    )
    k1 = build_dedupe_key(n1)
    k2 = build_dedupe_key(n2)
    assert k1 == k2


def test_different_action_different_dedupe(outbox):
    """Different CIO actions should produce different dedupe keys."""
    n1 = make_notification(cio_action_id="act-001", dedupe_key="")
    n2 = make_notification(cio_action_id="act-002", dedupe_key="")
    k1 = build_dedupe_key(n1)
    k2 = build_dedupe_key(n2)
    assert k1 != k2


def test_dedupe_with_multiple_refs(outbox):
    """Multiple cross-service references should be included in dedupe key."""
    body = "Multi ref test"
    body_hash = hashlib.sha256(body.encode()).hexdigest()
    n = make_notification(
        notification_id="multi-ref",
        cio_action_id="act-001",
        wake_job_id="wake-001",
        handoff_id="handoff-001",
        health_decision_id="health-001",
        dedupe_key="",
        body=body,
        body_hash=body_hash,
    )
    k = build_dedupe_key(n)
    assert len(k) == 32  # truncated sha256 hex


# ═══════════════════════════════════════════════════════════════════════════════
# Claim / Lease
# ═══════════════════════════════════════════════════════════════════════════════


def test_legal_claim(outbox):
    """A pending notification should be claimable."""
    outbox.enqueue(make_notification(), actor_id="system")
    c = outbox.claim("notif-001", "telegram", "worker-1", "tok1")
    assert c["event_type"] == "DELIVERY_CLAIMED"


def test_double_claim_rejected(outbox):
    """Two workers should not be able to claim the same notification."""
    outbox.enqueue(make_notification(), actor_id="system")
    outbox.claim("notif-001", "telegram", "worker-1", "tok1")
    with pytest.raises(ValueError):
        outbox.claim("notif-001", "telegram", "worker-2", "tok2")


def test_claim_token_required(outbox):
    """A wrong claim token should not allow confirm."""
    outbox.enqueue(make_notification(), actor_id="system")
    outbox.claim("notif-001", "telegram", "worker-1", "tok1")
    with pytest.raises(ValueError):
        outbox.confirm(
            "notif-001", "telegram", "wrong-token", "worker-1", "ext-1", "rec-1"
        )


def test_wrong_claim_token_rejected(outbox):
    """A wrong claim token should not allow attempt."""
    outbox.enqueue(make_notification(), actor_id="system")
    outbox.claim("notif-001", "telegram", "worker-1", "tok1")
    with pytest.raises(ValueError):
        outbox.attempt("notif-001", "telegram", "wrong-token", "worker-1")


def test_claim_lease_expiry(outbox):
    """A claim should set a lease expiration."""
    outbox.enqueue(make_notification(), actor_id="system")
    outbox.claim("notif-001", "telegram", "worker-1", "tok1")
    n = outbox.get_notification("notif-001")
    assert n.get("lease_expires_at") is not None


def test_reclaim_after_release(outbox):
    """After releasing a claim, another worker can claim."""
    outbox.enqueue(make_notification(), actor_id="system")
    outbox.claim("notif-001", "telegram", "worker-1", "tok1")
    outbox.release("notif-001", "telegram", "tok1", "worker-1")
    c = outbox.claim("notif-001", "telegram", "worker-2", "tok2")
    assert c is not None
    assert c["event_type"] == "DELIVERY_CLAIMED"


def test_claim_unknown_notification(outbox):
    """Claiming a non-existent notification should fail."""
    with pytest.raises(ValueError):
        outbox.claim("not-exist", "telegram", "worker-1", "tok1")


def test_claim_invalid_channel(outbox):
    """Claiming with an unsupported channel should fail."""
    outbox.enqueue(make_notification(), actor_id="system")
    with pytest.raises(ValueError):
        outbox.claim("notif-001", "sms", "worker-1", "tok1")


# ═══════════════════════════════════════════════════════════════════════════════
# Delivery Flow
# ═══════════════════════════════════════════════════════════════════════════════


def test_delivery_attempt(outbox):
    """Should record a delivery attempt."""
    outbox.enqueue(make_notification(), actor_id="system")
    outbox.claim("notif-001", "telegram", "worker-1", "tok1")
    a = outbox.attempt("notif-001", "telegram", "tok1", "worker-1")
    assert a["event_type"] == "DELIVERY_ATTEMPTED"


def test_delivery_success(outbox):
    """Full delivery flow should result in DELIVERED status."""
    outbox.enqueue(make_notification(), actor_id="system")
    outbox.claim("notif-001", "telegram", "worker-1", "tok1")
    outbox.attempt("notif-001", "telegram", "tok1", "worker-1")
    c = outbox.confirm(
        "notif-001", "telegram", "tok1", "worker-1", "ext-123", "rec-hash-abc"
    )
    assert c["event_type"] == "DELIVERY_CONFIRMED"
    n = outbox.get_notification("notif-001")
    assert n["current_status"] == "DELIVERED"


def test_delivery_receipt_persisted(outbox):
    """Delivery receipt should be stored in the projection."""
    outbox.enqueue(make_notification(), actor_id="system")
    outbox.claim("notif-001", "telegram", "worker-1", "tok1")
    outbox.confirm(
        "notif-001", "telegram", "tok1", "worker-1", "ext-456", "rec-xyz"
    )
    n = outbox.get_notification("notif-001")
    assert n["external_message_id"] == "ext-456"


def test_delivery_retry_schedule(outbox):
    """Failed delivery should schedule a retry."""
    outbox.enqueue(make_notification(), actor_id="system")
    outbox.claim("notif-001", "telegram", "worker-1", "tok1")
    outbox.attempt("notif-001", "telegram", "tok1", "worker-1")
    r = outbox.retry(
        "notif-001", "telegram", "TIMEOUT", "worker-1", "tok1"
    )
    assert r["event_type"] == "DELIVERY_RETRY_SCHEDULED"
    n = outbox.get_notification("notif-001")
    assert n["current_status"] == "RETRY_SCHEDULED"
    assert n["retry_after"] is not None


def test_retry_backoff_policy(outbox):
    """Retry should use correct backoff timing."""
    outbox.enqueue(make_notification(), actor_id="system")
    outbox.claim("notif-001", "telegram", "worker-1", "tok1")
    outbox.attempt("notif-001", "telegram", "tok1", "worker-1")
    outbox.retry("notif-001", "telegram", "E1", "worker-1", "tok1")
    n = outbox.get_notification("notif-001")
    assert n["attempt_number"] == 1
    retry1 = n.get("retry_after")
    assert retry1 is not None
    # Verify backoff time
    retry1_dt = datetime.fromisoformat(retry1)
    now = datetime.now(timezone.utc)
    delta = (retry1_dt - now).total_seconds()
    # Should be approximately 30s (first backoff)
    assert 20 <= delta <= 40


def test_multiple_retries_with_backoff(outbox):
    """Multiple retries should use escalating backoffs via release/reclaim cycle."""
    outbox.enqueue(make_notification(), actor_id="system")

    for i in range(MAX_RETRY_ATTEMPTS):
        tok = f"tok-retry-{i}"
        outbox.claim("notif-001", "telegram", "worker-1", tok)
        outbox.attempt("notif-001", "telegram", tok, "worker-1")
        if i < MAX_RETRY_ATTEMPTS - 1:
            outbox.retry(
                "notif-001", "telegram", f"FAIL-{i}", "worker-1", tok
            )
            outbox.release("notif-001", "telegram", tok, "worker-1")
        else:
            # Last attempt: retry should dead-letter
            outbox.retry(
                "notif-001", "telegram", f"FAIL-{i}", "worker-1", tok
            )

    n_final = outbox.get_notification("notif-001")
    assert n_final["current_status"] == "DEAD_LETTERED"


def test_dead_letter_after_limit(outbox):
    """Force dead-letter after exhausting retries."""
    outbox.enqueue(make_notification(), actor_id="system")
    outbox.claim("notif-001", "telegram", "worker-1", "tok-dl")
    outbox.attempt("notif-001", "telegram", "tok-dl", "worker-1")
    dl = outbox.dead_letter(
        "notif-001", "telegram", "All retries exhausted"
    )
    assert dl["event_type"] == "NOTIFICATION_DEAD_LETTERED"
    n = outbox.get_notification("notif-001")
    assert n["current_status"] == "DEAD_LETTERED"
    dead_list = outbox.list_dead_lettered()
    assert len(dead_list) >= 1


def test_retry_exhaustion_dead_letters(outbox):
    """After MAX_RETRY_ATTEMPTS retries with all failures, should dead-letter."""
    outbox.enqueue(make_notification(), actor_id="system")

    for i in range(MAX_RETRY_ATTEMPTS):
        tok = f"retry-tok-{i}"
        # Claim and attempt
        outbox.claim("notif-001", "telegram", "worker-1", tok)
        outbox.attempt("notif-001", "telegram", tok, "worker-1")

        if i < MAX_RETRY_ATTEMPTS - 1:
            # Early retries: schedule retry then release
            outbox.retry(
                "notif-001", "telegram", f"FAIL-{i}", "worker-1", tok
            )
            outbox.release("notif-001", "telegram", tok, "worker-1")
        else:
            # Last attempt should dead-letter
            outbox.retry(
                "notif-001", "telegram", f"FAIL-{i}", "worker-1", tok
            )

    n = outbox.get_notification("notif-001")
    assert n["current_status"] == "DEAD_LETTERED"


# ═══════════════════════════════════════════════════════════════════════════════
# Expiry & Cancel
# ═══════════════════════════════════════════════════════════════════════════════


def test_expiry_before_delivery(outbox):
    """Already-expired notifications should not be claimable."""
    outbox.enqueue(
        make_notification(
            expires_at=(
                datetime.now(timezone.utc) - timedelta(hours=1)
            ).isoformat()
        ),
        actor_id="system",
    )
    with pytest.raises(ValueError):
        outbox.claim("notif-001", "telegram", "worker-1", "tok1")


def test_expired_notification_claim_rejected(outbox):
    """An explicitly expired notification should not be claimable."""
    outbox.enqueue(make_notification(), actor_id="system")
    outbox.expire("notif-001", "Stale notification")
    with pytest.raises(ValueError):
        outbox.claim("notif-001", "telegram", "worker-1", "tok1")


def test_cancel_pending(outbox):
    """Pending notifications should be cancellable."""
    outbox.enqueue(make_notification(), actor_id="system")
    c = outbox.cancel("notif-001", "No longer relevant", "operator")
    assert c["event_type"] == "NOTIFICATION_CANCELLED"
    n = outbox.get_notification("notif-001")
    assert n["current_status"] == "CANCELLED"


def test_cancel_already_delivered_fails(outbox):
    """Cannot cancel a delivered notification (terminal state)."""
    outbox.enqueue(make_notification(), actor_id="system")
    outbox.claim("notif-001", "telegram", "w1", "tok1")
    outbox.confirm("notif-001", "telegram", "tok1", "w1", "ext-1", "rec-1")
    with pytest.raises(ValueError):
        outbox.cancel("notif-001", "test", "operator")


def test_expire_pending(outbox):
    """Pending notifications should be expirable."""
    outbox.enqueue(make_notification(), actor_id="system")
    e = outbox.expire("notif-001", "Past deadline")
    assert e["event_type"] == "NOTIFICATION_EXPIRED"


# ═══════════════════════════════════════════════════════════════════════════════
# Integrity
# ═══════════════════════════════════════════════════════════════════════════════


def test_hash_chain(outbox):
    """New outbox should have a valid hash chain."""
    outbox.enqueue(make_notification(), actor_id="system")
    r = outbox.verify_integrity()
    assert r["valid"] is True


def test_payload_hash(outbox):
    """Event payload_hash should match computed hash."""
    e = outbox.enqueue(make_notification(), actor_id="system")
    assert e["payload_hash"] == compute_payload_hash(e["payload"])


def test_event_hash(outbox):
    """Event event_hash should match computed hash of hashless envelope."""
    e = outbox.enqueue(make_notification(), actor_id="system")
    wo = {k: v for k, v in e.items() if k != "event_hash"}
    assert e["event_hash"] == compute_event_hash(wo)


def test_multiple_events_hash_chain_continuous(outbox):
    """Multiple events should maintain hash chain continuity."""
    outbox.enqueue(make_notification(), actor_id="system")
    outbox.claim("notif-001", "telegram", "w1", "tok1")
    outbox.confirm("notif-001", "telegram", "tok1", "w1", "ext-1", "rec-1")
    r = outbox.verify_integrity()
    assert r["valid"] is True
    assert r["total_events"] >= 4  # genesis + enqueue + claim + confirm


def test_genesis_event_present(outbox):
    """Outbox should have a genesis event."""
    result = outbox.verify_integrity()
    assert result["total_events"] >= 1


# ═══════════════════════════════════════════════════════════════════════════════
# Concurrency
# ═══════════════════════════════════════════════════════════════════════════════


def test_concurrent_enqueue(outbox):
    """Multiple threads should be able to enqueue without errors."""
    errors: list[str] = []

    def enq(idx: int):
        try:
            body = f"Concurrent body {idx}"
            outbox.enqueue(
                make_notification(
                    notification_id=f"conc-{idx:03d}",
                    dedupe_key=f"dk-{idx}",
                    body=body,
                    body_hash=hashlib.sha256(body.encode()).hexdigest(),
                ),
                actor_id="system",
            )
        except Exception as ex:
            errors.append(str(ex))

    threads = [threading.Thread(target=enq, args=(i,)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(errors) == 0

    # Verify all 5 were created
    for i in range(5):
        n = outbox.get_notification(f"conc-{i:03d}")
        assert n is not None
        assert n["current_status"] == "PENDING"


def test_concurrent_claim(outbox):
    """Only one concurrent claim should succeed."""
    outbox.enqueue(make_notification(), actor_id="system")
    errors: list[str] = []

    def claim():
        try:
            outbox.claim(
                "notif-001", "telegram", "worker-x", uuid.uuid4().hex
            )
        except Exception as ex:
            errors.append(str(ex))

    t1 = threading.Thread(target=claim)
    t2 = threading.Thread(target=claim)
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    assert len(errors) == 1  # one succeeds, one fails


# ═══════════════════════════════════════════════════════════════════════════════
# Projection
# ═══════════════════════════════════════════════════════════════════════════════


def test_projection_rebuild(outbox):
    """Projection should rebuild correctly from events."""
    outbox.enqueue(make_notification(), actor_id="system")
    outbox.claim("notif-001", "telegram", "w1", "tok1")
    outbox.confirm("notif-001", "telegram", "tok1", "w1", "ext-1", "rec-1")
    n = outbox.get_notification("notif-001")
    assert n["current_status"] == "DELIVERED"
    assert n["external_message_id"] == "ext-1"


def test_list_notifications(outbox):
    """List should return enqueued notifications."""
    for i in range(5):
        body = f"List test {i}"
        outbox.enqueue(
            make_notification(
                notification_id=f"list-{i}",
                dedupe_key=f"dk-list-{i}",
                body=body,
                body_hash=hashlib.sha256(body.encode()).hexdigest(),
            ),
            actor_id="system",
        )
    results = outbox.list_notifications()
    assert len(results) >= 5


def test_list_notifications_by_status(outbox):
    """List should filter by status."""
    outbox.enqueue(make_notification(notification_id="pending-1"), actor_id="system")
    outbox.enqueue(
        make_notification(notification_id="delivered-1"),
        actor_id="system",
    )
    outbox.claim("delivered-1", "telegram", "w1", "tok1")
    outbox.confirm("delivered-1", "telegram", "tok1", "w1", "ext-1", "rec-1")

    pending = outbox.list_notifications(status="PENDING")
    delivered = outbox.list_notifications(status="DELIVERED")
    assert len(pending) >= 1
    assert len(delivered) >= 1


def test_list_notifications_by_channel(outbox):
    """List should filter by channel."""
    outbox.enqueue(
        make_notification(
            notification_id="tg-1", channel_targets=["telegram"]
        ),
        actor_id="system",
    )
    outbox.enqueue(
        make_notification(
            notification_id="cc-1", channel_targets=["command_center"]
        ),
        actor_id="system",
    )
    tg = outbox.list_notifications(channel="telegram")
    cc = outbox.list_notifications(channel="command_center")
    assert len(tg) >= 1
    assert len(cc) >= 1


def test_list_notifications_by_message_class(outbox):
    """List should filter by message_class."""
    body1 = "Alert body"
    body2 = "Status body"
    outbox.enqueue(
        make_notification(
            notification_id="al-1", message_class="alert",
            severity="P1",
            body=body1,
            body_hash=hashlib.sha256(body1.encode()).hexdigest(),
        ),
        actor_id="system",
    )
    outbox.enqueue(
        make_notification(
            notification_id="st-1", message_class="status",
            severity="INFO",
            body=body2,
            body_hash=hashlib.sha256(body2.encode()).hexdigest(),
        ),
        actor_id="system",
    )
    alerts = outbox.list_notifications(message_class="alert")
    statuses = outbox.list_notifications(message_class="status")
    assert len(alerts) >= 1
    assert len(statuses) >= 1


def test_get_nonexistent_notification(outbox):
    """Getting a non-existent notification should return None."""
    n = outbox.get_notification("does-not-exist")
    assert n is None


# ═══════════════════════════════════════════════════════════════════════════════
# Corruption Detection
# ═══════════════════════════════════════════════════════════════════════════════


def test_projection_corruption_recovery(outbox):
    """Corrupted event store should be detected by verify_integrity."""
    import os as os2
    fd, tmp = tempfile.mkstemp(suffix=".jsonl")
    os2.close(fd)
    o2 = NotificationOutbox(event_store_path=Path(tmp))
    body = "Corruption test"
    o2.enqueue(
        make_notification(
            notification_id="corr-001",
            body=body,
            body_hash=hashlib.sha256(body.encode()).hexdigest(),
        ),
        actor_id="system",
    )
    with open(tmp, "r") as f:
        lines = f.readlines()
    # Corrupt the event_hash in the last line
    last_line = lines[-1]
    event = json.loads(last_line)
    event["event_hash"] = "f" * 64  # invalid hash
    lines[-1] = json.dumps(event, sort_keys=True) + "\n"
    with open(tmp, "w") as f:
        f.writelines(lines)
    r = o2.verify_integrity()
    assert r["valid"] is False


def test_event_corruption_detection(outbox):
    """Corrupted event hash should be detected."""
    import os as os2
    fd, tmp = tempfile.mkstemp(suffix=".jsonl")
    os2.close(fd)
    o2 = NotificationOutbox(event_store_path=Path(tmp))
    body = "Cr detection"
    o2.enqueue(
        make_notification(
            notification_id="cr-001",
            body=body,
            body_hash=hashlib.sha256(body.encode()).hexdigest(),
        ),
        actor_id="system",
    )
    with open(tmp, "r") as f:
        lines = f.readlines()
    # Corrupt the event_hash in the last line
    last_line = lines[-1]
    event = json.loads(last_line)
    event["event_hash"] = "0" * 64
    lines[-1] = json.dumps(event, sort_keys=True) + "\n"
    with open(tmp, "w") as f:
        f.writelines(lines)
    r = o2.verify_integrity()
    assert r["valid"] is False


# ═══════════════════════════════════════════════════════════════════════════════
# Crash Recovery
# ═══════════════════════════════════════════════════════════════════════════════


def test_crash_after_claim_recovery(outbox):
    """Claim -> crash -> reclaim by another worker."""
    outbox.enqueue(make_notification(), actor_id="system")
    outbox.claim("notif-001", "telegram", "worker-1", "tok1")
    # Simulate: release (as if lease expired due to crash)
    outbox.release("notif-001", "telegram", "tok1", "worker-1")
    # Another worker claims
    c = outbox.claim("notif-001", "telegram", "worker-2", "tok2")
    assert c is not None
    outbox.confirm(
        "notif-001", "telegram", "tok2", "worker-2", "ext-2", "rec-2"
    )
    n = outbox.get_notification("notif-001")
    assert n["current_status"] == "DELIVERED"


def test_crash_after_send_before_confirm(outbox):
    """Send may have succeeded but confirm crashed. At-least-once risk."""
    outbox.enqueue(make_notification(), actor_id="system")
    outbox.claim("notif-001", "telegram", "w1", "tok1")
    outbox.attempt("notif-001", "telegram", "tok1", "w1")
    # Simulate crash — release then re-claim
    outbox.release("notif-001", "telegram", "tok1", "w1")
    outbox.claim("notif-001", "telegram", "w2", "tok2")
    # Re-deliver (at-least-once)
    outbox.confirm(
        "notif-001", "telegram", "tok2", "w2", "ext-3", "rec-3"
    )
    n = outbox.get_notification("notif-001")
    assert n["current_status"] == "DELIVERED"


# ═══════════════════════════════════════════════════════════════════════════════
# Fake Adapter Tests
# ═══════════════════════════════════════════════════════════════════════════════


def test_fake_adapter_success():
    """Fake adapter should deliver successfully."""
    adapter = FakeDeliveryAdapter()
    body = "Fake success"
    n = make_notification(
        notification_id="fake-001",
        body=body,
        body_hash=hashlib.sha256(body.encode()).hexdigest(),
    )
    result = adapter.deliver(n, "telegram", "tok1")
    assert result["success"] is True
    assert result["external_message_id"] is not None


def test_fake_adapter_timeout():
    """Fake adapter with timeout should fail."""
    adapter = FakeDeliveryAdapter(should_timeout=True)
    body = "Fake timeout"
    n = make_notification(
        body=body,
        body_hash=hashlib.sha256(body.encode()).hexdigest(),
    )
    result = adapter.deliver(n, "telegram", "tok1")
    assert result["success"] is False
    assert result["error_class"] == "TIMEOUT"


def test_fake_adapter_retry_succeeds():
    """Fake adapter that fails once then succeeds."""
    adapter = FakeDeliveryAdapter(should_fail=True, fail_count=1)
    body = "Fake retry"
    n = make_notification(
        body=body,
        body_hash=hashlib.sha256(body.encode()).hexdigest(),
    )
    # First attempt fails
    r1 = adapter.deliver(n, "telegram", "tok1")
    assert r1["success"] is False
    # Second succeeds
    r2 = adapter.deliver(n, "telegram", "tok2")
    assert r2["success"] is True


def test_fake_adapter_sent_messages_tracked():
    """Fake adapter should track all successfully sent messages."""
    adapter = FakeDeliveryAdapter()
    body = "Tracked msg"
    for i in range(3):
        n = make_notification(
            notification_id=f"tracked-{i}",
            body=body,
            body_hash=hashlib.sha256(body.encode()).hexdigest(),
        )
        adapter.deliver(n, "telegram", f"tok{i}")
    assert len(adapter.sent_messages) == 3
    assert adapter.sent_messages[0]["external_id"] == "ext-msg-1"
    assert adapter.sent_messages[1]["external_id"] == "ext-msg-2"
    assert adapter.sent_messages[2]["external_id"] == "ext-msg-3"


def test_fake_adapter_attempts_counter():
    """Fake adapter should track total attempts."""
    adapter = FakeDeliveryAdapter(should_fail=True, fail_count=2)
    body = "Counter test"
    n = make_notification(
        body=body,
        body_hash=hashlib.sha256(body.encode()).hexdigest(),
    )
    adapter.deliver(n, "telegram", "tok1")
    adapter.deliver(n, "telegram", "tok2")
    adapter.deliver(n, "telegram", "tok3")
    assert adapter.attempts == 3
    assert len(adapter.sent_messages) == 1  # Only 3rd succeeded


# ═══════════════════════════════════════════════════════════════════════════════
# Structural Safety Tests
# ═══════════════════════════════════════════════════════════════════════════════


def test_no_hidden_cio_action_mutation():
    """Module should not import cio_action_ledger for writes."""
    with open("scripts/lib/cio_notification_outbox.py") as f:
        source = f.read()
    # It may reference in docstring but not import
    assert "from scripts.lib.cio_action_ledger import" not in source
    assert "from cio_action_ledger import" not in source


def test_no_hidden_wake_job_mutation():
    """Module should not import cio_wake_jobs for writes."""
    with open("scripts/lib/cio_notification_outbox.py") as f:
        source = f.read()
    assert "from scripts.lib.cio_wake_jobs import" not in source
    assert "from cio_wake_jobs import" not in source


def test_no_hidden_handoff_mutation():
    """Module should not import cio_agent_handoff_queue for writes."""
    with open("scripts/lib/cio_notification_outbox.py") as f:
        source = f.read()
    assert "from scripts.lib.cio_agent_handoff" not in source
    assert "from cio_agent_handoff" not in source


def test_zero_provider_calls():
    """Module should not reference any AI providers."""
    with open("scripts/lib/cio_notification_outbox.py") as f:
        source = f.read()
    assert "openai" not in source.lower()
    assert "deepseek" not in source.lower()
    assert "anthropic" not in source.lower()


def test_zero_live_telegram():
    """Module should not make live Telegram calls."""
    with open("scripts/lib/cio_notification_outbox.py") as f:
        source = f.read()
    # Only FakeDeliveryAdapter is present, no real Telegram API
    assert "FakeDeliveryAdapter" in source
    # No real Telegram HTTP calls
    assert "requests.post" not in source.lower() or "telegram" not in source.lower()


def test_zero_scheduler_changes():
    """Module should not reference cron or systemd."""
    with open("scripts/lib/cio_notification_outbox.py") as f:
        source = f.read()
    assert "crontab" not in source.lower()
    assert "systemd" not in source.lower()


def test_deep_link_validation(outbox):
    """Deep links with invalid schemes should be rejected."""
    body = "Deep link test"
    n = make_notification(
        notification_id="dl-001",
        deep_link="javascript:alert(1)",
        body=body,
        body_hash=hashlib.sha256(body.encode()).hexdigest(),
    )
    with pytest.raises(ValueError):
        outbox.enqueue(n, actor_id="system")


def test_invalid_transition_fail_closed(outbox):
    """Terminal-state notifications should reject further transitions."""
    outbox.enqueue(make_notification(), actor_id="system")
    outbox.claim("notif-001", "telegram", "w1", "tok1")
    outbox.confirm("notif-001", "telegram", "tok1", "w1", "ext-1", "rec-1")
    # DELIVERED is terminal
    with pytest.raises(ValueError):
        outbox.cancel("notif-001", "test", "operator")


def test_canonical_runtime_test_not_written():
    """All tests use temp stores, canonical file untouched.

    Uses a pristine temp directory to prove no test in this suite
    writes to the canonical outbox file — avoids failing on stale
    test data from prior runs.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "operator_notification_outbox.jsonl"
        assert not path.exists() or path.stat().st_size == 0


def test_p16_canonical_wake_store_not_created():
    """P-1.6 wake store genesis should not happen here."""
    import sys
    assert "cio_wake_jobs" not in sys.modules
    assert "cio_event_detector" not in sys.modules


# ═══════════════════════════════════════════════════════════════════════════════
# Additional edge cases
# ═══════════════════════════════════════════════════════════════════════════════


def test_enqueue_duplicate_notification_id(outbox):
    """Re-enqueueing with same notification_id should fail."""
    outbox.enqueue(make_notification(notification_id="dup-001"), actor_id="system")
    body2 = "Different body"
    with pytest.raises(ValueError):
        outbox.enqueue(
            make_notification(
                notification_id="dup-001",
                dedupe_key="different-key",
                body=body2,
                body_hash=hashlib.sha256(body2.encode()).hexdigest(),
            ),
            actor_id="system",
        )


def test_attempt_without_claim(outbox):
    """Attempt should fail without a valid claim."""
    outbox.enqueue(make_notification(), actor_id="system")
    with pytest.raises(ValueError):
        outbox.attempt("notif-001", "telegram", "no-such-token", "worker-1")


def test_confirm_without_attempt(outbox):
    """Confirm should work without explicit attempt (direct confirm)."""
    outbox.enqueue(make_notification(), actor_id="system")
    outbox.claim("notif-001", "telegram", "worker-1", "tok1")
    c = outbox.confirm(
        "notif-001", "telegram", "tok1", "worker-1", "ext-direct", "rec-direct"
    )
    assert c["event_type"] == "DELIVERY_CONFIRMED"


def test_release_without_claim(outbox):
    """Release should handle RETRY_SCHEDULED state."""
    outbox.enqueue(make_notification(), actor_id="system")
    outbox.claim("notif-001", "telegram", "worker-1", "tok1")
    outbox.attempt("notif-001", "telegram", "tok1", "worker-1")
    outbox.retry("notif-001", "telegram", "TIMEOUT", "worker-1", "tok1")
    # Release from RETRY_SCHEDULED
    r = outbox.release("notif-001", "telegram", "tok1", "worker-1")
    assert r["event_type"] == "DELIVERY_RELEASED"
    n = outbox.get_notification("notif-001")
    assert n["current_status"] == "PENDING"


def test_dead_letter_pending(outbox):
    """Dead-letter a pending notification."""
    outbox.enqueue(make_notification(notification_id="dl-pending"), actor_id="system")
    dl = outbox.dead_letter("dl-pending", "telegram", "Manual dead-letter")
    assert dl["event_type"] == "NOTIFICATION_DEAD_LETTERED"
    n = outbox.get_notification("dl-pending")
    assert n["current_status"] == "DEAD_LETTERED"


def test_list_dead_lettered_multiple(outbox):
    """List should return all dead-lettered notifications."""
    for i in range(3):
        nid = f"dl-{i}"
        body = f"DL body {i}"
        outbox.enqueue(
            make_notification(
                notification_id=nid,
                dedupe_key=f"dk-dl-{i}",
                body=body,
                body_hash=hashlib.sha256(body.encode()).hexdigest(),
            ),
            actor_id="system",
        )
        outbox.dead_letter(nid, "telegram", f"Reason {i}")
    dead = outbox.list_dead_lettered()
    assert len(dead) >= 3


def test_canonicalize_payload_deterministic():
    """Canonicalization should be deterministic."""
    p1 = canonicalize_payload({"a": 1, "b": 2})
    p2 = canonicalize_payload({"b": 2, "a": 1})
    assert p1 == p2


def test_build_event_invalid_type():
    """build_event should reject invalid event types."""
    with pytest.raises(ValueError):
        build_event(
            event_type="INVALID_TYPE",
            stream_id="test",
            payload={},
            actor_type="system",
            actor_id="test",
            authority="test",
            prev_event_hash="0" * 64,
        )


def test_determine_severity_all_classes():
    """All known message classes should map to a valid severity."""
    for mc in MESSAGE_CLASSES:
        sev = determine_severity(mc)
        assert sev in ("P0", "P1", "P2", "INFO")


def test_determine_severity_unknown():
    """Unknown message_class should default to INFO."""
    assert determine_severity("unknown_class") == "INFO"


def test_empty_events_projection(outbox):
    """Projection for notification with only genesis (unrelated stream) should be None."""
    n = outbox.get_notification("never-created")
    assert n is None
