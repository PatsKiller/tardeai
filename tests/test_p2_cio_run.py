"""
P2.3 CIO Run Orchestrator — Deterministic test suite.

All tests use temporary stores; zero provider calls, zero Telegram, zero scheduler.
Every test verifies lifecycle transitions, budget enforcement, and crash recovery.
"""
import json
import os
import tempfile
import time
from pathlib import Path

import pytest

from scripts.lib.cio_run import (
    CIORunStore,
    create_cio_run,
    build_event,
    compute_event_hash,
    compute_payload_hash,
    canonicalize_payload,
    GENESIS_PREV_HASH,
    DEFAULT_MAX_PROVIDER_CALLS,
    DEFAULT_MAX_COST_USD,
    DEFAULT_MAX_WALL_TIME_MINUTES,
    DEFAULT_MAX_SPECIALIST_CALLS,
    DEFAULT_MAX_HERMES_CHALLENGES,
    HARD_MAX_PROVIDER_CALLS,
    HARD_MAX_COST_USD,
    HARD_MAX_WALL_TIME_MINUTES,
    HARD_MAX_SPECIALIST_CALLS,
    HARD_MAX_HERMES_CHALLENGES,
    RUN_STATUSES,
    TERMINAL_STATUSES,
    STATE_TRANSITIONS,
    VALID_TRIGGER_TYPES,
    VALID_PRIORITIES,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def store():
    """Create a fresh CIORunStore with a temp file."""
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "cio_runs.jsonl")
        s = CIORunStore(p)
        s.initialize()
        yield s


@pytest.fixture
def created_run(store):
    """Create a basic run and return (store, run_id, event)."""
    event = store.create_run(trigger_type="MANUAL", trigger_ref="test", actor="test")
    run_id = event["payload"]["run_id"]
    return store, run_id


# ═══════════════════════════════════════════════════════════════════════════════
# Hashing and event building
# ═══════════════════════════════════════════════════════════════════════════════


def test_canonicalize_payload_deterministic():
    a = canonicalize_payload({"b": 1, "a": 2})
    b = canonicalize_payload({"a": 2, "b": 1})
    assert a == b


def test_payload_hash_deterministic():
    a = compute_payload_hash({"a": 1})
    b = compute_payload_hash({"a": 1})
    assert a == b
    assert len(a) == 64


def test_event_hash_chaining():
    h1 = compute_event_hash("id1", "CIO_RUN_CREATED", "2026-01-01T00:00:00", GENESIS_PREV_HASH, "abc123")
    h2 = compute_event_hash("id2", "CIO_RUN_STARTED", "2026-01-01T00:01:00", h1, "def456")
    assert h1 != h2
    assert len(h1) == 64
    assert len(h2) == 64


def test_build_event():
    e = build_event("CIO_RUN_CREATED", {"run_id": "test"}, GENESIS_PREV_HASH, actor="test")
    assert e["event_type"] == "CIO_RUN_CREATED"
    assert e["prev_event_hash"] == GENESIS_PREV_HASH
    assert "event_id" in e
    assert "event_hash" in e
    assert "payload_hash" in e
    assert e["actor"] == "test"


def test_build_event_invalid_type():
    with pytest.raises(ValueError, match="Invalid event type"):
        build_event("INVALID_TYPE", {}, GENESIS_PREV_HASH)


# ═══════════════════════════════════════════════════════════════════════════════
# Valid create
# ═══════════════════════════════════════════════════════════════════════════════


def test_valid_create(store):
    event = store.create_run(trigger_type="MANUAL", trigger_ref="test", actor="test")
    assert event["event_type"] == "CIO_RUN_CREATED"
    run_id = event["payload"]["run_id"]
    assert run_id

    run = store.get_run(run_id)
    assert run is not None
    assert run["status"] == "QUEUED"
    assert run["trigger_type"] == "MANUAL"
    assert run["trigger_ref"] == "test"
    assert run["priority"] == "NORMAL"


def test_create_with_all_params(store):
    event = store.create_run(
        trigger_type="SCHEDULED_DAILY",
        trigger_ref="daily_2026-08-08",
        case_id="case-001",
        priority="HIGH",
        required_domains=["portfolio", "risk"],
        input_hash="abc123",
        operator_profile_version=2,
        ips_version=1,
        parent_action_ids=["act-1"],
        parent_handoff_ids=["ho-1"],
        max_provider_calls=5,
        max_cost_usd=0.03,
        max_wall_time_minutes=15,
        max_specialist_calls=3,
        max_hermes_challenges=2,
        actor="test",
    )
    run = store.get_run(event["payload"]["run_id"])
    assert run is not None
    assert run["case_id"] == "case-001"
    assert run["trigger_type"] == "SCHEDULED_DAILY"
    assert run["priority"] == "HIGH"
    assert run["required_domains"] == ["portfolio", "risk"]
    assert run["input_hash"] == "abc123"
    assert run["operator_profile_version"] == 2
    assert run["ips_version"] == 1
    assert run["parent_action_ids"] == ["act-1"]
    assert run["parent_handoff_ids"] == ["ho-1"]
    assert run["budget"]["max_provider_calls"] == 5
    assert run["budget"]["max_cost_usd"] == 0.03
    assert run["budget"]["max_wall_time_minutes"] == 15
    assert run["budget"]["max_specialist_calls"] == 3
    assert run["budget"]["max_hermes_challenges"] == 2


def test_create_invalid_trigger_type(store):
    with pytest.raises(ValueError, match="Invalid trigger_type"):
        store.create_run(trigger_type="INVALID")


def test_create_invalid_priority(store):
    with pytest.raises(ValueError, match="Invalid priority"):
        store.create_run(trigger_type="MANUAL", priority="URGENT")


def test_create_clamps_budget(store):
    event = store.create_run(
        trigger_type="MANUAL",
        max_provider_calls=999,
        max_cost_usd=999.0,
        max_wall_time_minutes=999,
        max_specialist_calls=999,
        max_hermes_challenges=999,
    )
    run = store.get_run(event["payload"]["run_id"])
    assert run["budget"]["max_provider_calls"] == HARD_MAX_PROVIDER_CALLS
    assert run["budget"]["max_cost_usd"] == HARD_MAX_COST_USD
    assert run["budget"]["max_wall_time_minutes"] == HARD_MAX_WALL_TIME_MINUTES
    assert run["budget"]["max_specialist_calls"] == HARD_MAX_SPECIALIST_CALLS
    assert run["budget"]["max_hermes_challenges"] == HARD_MAX_HERMES_CHALLENGES


# ═══════════════════════════════════════════════════════════════════════════════
# Lifecycle transitions
# ═══════════════════════════════════════════════════════════════════════════════


def test_lifecycle_normal_path(store):
    """QUEUED -> HEALTH_CHECK -> EVIDENCE_BUILD -> CIO_SYNTHESIS -> ACTION_WRITE -> NOTIFICATION_ENQUEUE -> COMPLETED"""
    event = store.create_run(trigger_type="MANUAL", trigger_ref="test")
    run_id = event["payload"]["run_id"]

    # Start
    store.start(run_id)
    run = store.get_run(run_id)
    assert run["status"] == "HEALTH_CHECK"

    # Health check passes
    store.health_checked(run_id, "hd-001")
    run = store.get_run(run_id)
    assert run["status"] == "EVIDENCE_BUILD"

    # Evidence built (no specialists requested, goes straight to CIO_SYNTHESIS)
    store.evidence_built(run_id, "snap-001")
    run = store.get_run(run_id)
    assert run["status"] == "CIO_SYNTHESIS"

    # Synthesis complete
    store.transition(run_id, "ACTION_WRITE")
    run = store.get_run(run_id)
    assert run["status"] == "ACTION_WRITE"

    # Action written
    store.transition(run_id, "NOTIFICATION_ENQUEUE")
    run = store.get_run(run_id)
    assert run["status"] == "NOTIFICATION_ENQUEUE"

    # Complete
    store.complete(run_id, "artifact-001")
    run = store.get_run(run_id)
    assert run["status"] == "COMPLETED"
    assert run["completed_at"] is not None
    assert run["cio_artifact_id"] == "artifact-001"


def test_lifecycle_with_specialist(store):
    """QUEUED -> HEALTH_CHECK -> EVIDENCE_BUILD -> SPECIALIST_REVIEW -> CIO_SYNTHESIS"""
    event = store.create_run(trigger_type="MANUAL", trigger_ref="test")
    run_id = event["payload"]["run_id"]

    store.start(run_id)
    store.health_checked(run_id, "hd-001")

    # Request specialist (from EVIDENCE_BUILD state)
    store.record_specialist_request(run_id, "ho-001")
    run = store.get_run(run_id)
    assert run["status"] == "SPECIALIST_REVIEW"
    assert "ho-001" in run["specialist_requests"]

    # Complete specialist and move to synthesis
    store.transition(run_id, "CIO_SYNTHESIS")
    run = store.get_run(run_id)
    assert run["status"] == "CIO_SYNTHESIS"


def test_lifecycle_with_specialist(store):
    """QUEUED -> HEALTH_CHECK -> EVIDENCE_BUILD -> SPECIALIST_REVIEW -> CIO_SYNTHESIS"""
    event = store.create_run(trigger_type="MANUAL", trigger_ref="test")
    run_id = event["payload"]["run_id"]

    store.start(run_id)
    store.health_checked(run_id, "hd-001")

    # Request specialist (from EVIDENCE_BUILD state)
    store.record_specialist_request(run_id, "ho-001")
    run = store.get_run(run_id)
    assert run["status"] == "SPECIALIST_REVIEW"
    assert "ho-001" in run["specialist_requests"]


def test_lifecycle_with_hermes(store):
    """QUEUED -> HEALTH_CHECK -> EVIDENCE_BUILD -> SPECIALIST_REVIEW -> HERMES_CHALLENGE -> CIO_SYNTHESIS"""
    event = store.create_run(trigger_type="MANUAL", trigger_ref="test")
    run_id = event["payload"]["run_id"]

    store.start(run_id)
    store.health_checked(run_id, "hd-001")
    store.record_specialist_request(run_id, "ho-001")
    run = store.get_run(run_id)
    assert run["status"] == "SPECIALIST_REVIEW"

    # Hermes challenge from specialist review
    store.record_hermes_request(run_id, "ch-001")
    run = store.get_run(run_id)
    assert run["status"] == "HERMES_CHALLENGE"
    assert "ch-001" in run["hermes_challenge_ids"]


def test_lifecycle_block_and_unblock(store):
    event = store.create_run(trigger_type="MANUAL", trigger_ref="test")
    run_id = event["payload"]["run_id"]

    store.start(run_id)
    store.block(run_id, "health_block")
    run = store.get_run(run_id)
    assert run["status"] == "BLOCKED"
    assert run["failure_code"] == "health_block"

    store.unblock(run_id)
    run = store.get_run(run_id)
    assert run["status"] == "QUEUED"
    assert run["failure_code"] is None


def test_lifecycle_fail(store):
    event = store.create_run(trigger_type="MANUAL", trigger_ref="test")
    run_id = event["payload"]["run_id"]

    store.start(run_id)
    store.fail(run_id, "test_failure")
    run = store.get_run(run_id)
    assert run["status"] == "FAILED"
    assert run["failure_code"] == "test_failure"
    assert run["status"] in TERMINAL_STATUSES


def test_lifecycle_cancel(store):
    event = store.create_run(trigger_type="MANUAL", trigger_ref="test")
    run_id = event["payload"]["run_id"]

    store.cancel(run_id)
    run = store.get_run(run_id)
    assert run["status"] == "CANCELLED"
    assert run["status"] in TERMINAL_STATUSES


def test_invalid_transition_rejected(store):
    event = store.create_run(trigger_type="MANUAL", trigger_ref="test")
    run_id = event["payload"]["run_id"]

    # Cannot go QUEUED -> COMPLETED directly
    with pytest.raises(ValueError, match="Invalid transition"):
        store.complete(run_id)

    # Cannot go from terminal
    store.cancel(run_id)
    with pytest.raises(ValueError, match="Invalid transition"):
        store.start(run_id)


# ═══════════════════════════════════════════════════════════════════════════════
# Budget enforcement
# ═══════════════════════════════════════════════════════════════════════════════


def test_max_calls_exceeded(store):
    event = store.create_run(trigger_type="MANUAL", max_provider_calls=2)
    run_id = event["payload"]["run_id"]

    store.start(run_id)

    # Record 2 model calls
    store.record_model_call(run_id, "call-1", 0.001)
    store.record_model_call(run_id, "call-2", 0.001)

    # Third call should be rejected
    with pytest.raises(ValueError, match="BUDGET_EXCEEDED"):
        store.record_model_call(run_id, "call-3", 0.001)


def test_max_cost_exceeded(store):
    event = store.create_run(trigger_type="MANUAL", max_cost_usd=0.01)
    run_id = event["payload"]["run_id"]

    store.start(run_id)

    # Record calls that exceed cost budget
    store.record_model_call(run_id, "call-1", 0.006)
    store.record_model_call(run_id, "call-2", 0.005)

    # Should be exceeded now
    with pytest.raises(ValueError, match="BUDGET_EXCEEDED"):
        store.record_model_call(run_id, "call-3", 0.001)


def test_max_specialist_exceeded(store):
    """Test that specialist counter is enforced via budget when making direct transitions."""
    event = store.create_run(trigger_type="MANUAL", max_specialist_calls=1)
    run_id = event["payload"]["run_id"]

    store.start(run_id)
    store.health_checked(run_id, "hd-001")

    # First specialist request works
    store.record_specialist_request(run_id, "ho-1")

    # Second request fails due to budget
    with pytest.raises(ValueError, match="BUDGET_EXCEEDED"):
        store.record_specialist_request(run_id, "ho-2")


def test_max_hermes_exceeded(store):
    """Test that hermes counter is enforced via budget when making direct transitions."""
    event = store.create_run(trigger_type="MANUAL", max_hermes_challenges=1)
    run_id = event["payload"]["run_id"]

    store.start(run_id)
    store.health_checked(run_id, "hd-001")
    store.record_specialist_request(run_id, "ho-1")

    # First hermes request works
    store.record_hermes_request(run_id, "ch-1")

    # Second request fails due to budget
    with pytest.raises(ValueError, match="BUDGET_EXCEEDED"):
        store.record_hermes_request(run_id, "ch-2")


# ═══════════════════════════════════════════════════════════════════════════════
# Health block halts run
# ═══════════════════════════════════════════════════════════════════════════════


def test_health_block_halts_run(store):
    event = store.create_run(trigger_type="MANUAL")
    run_id = event["payload"]["run_id"]

    store.start(run_id)
    store.block(run_id, "health_critical")
    run = store.get_run(run_id)
    assert run["status"] == "BLOCKED"

    # Cannot proceed while blocked
    with pytest.raises(ValueError, match="Invalid transition"):
        store.health_checked(run_id, "hd-001")


# ═══════════════════════════════════════════════════════════════════════════════
# Specialist / Hermes integration
# ═══════════════════════════════════════════════════════════════════════════════


def test_specialist_integration(store):
    event = store.create_run(trigger_type="SPECIALIST_COMPLETION", trigger_ref="ho-external")
    run_id = event["payload"]["run_id"]

    store.start(run_id)
    store.health_checked(run_id, "hd-001")
    store.record_specialist_request(run_id, "ho-001")
    run = store.get_run(run_id)
    assert "ho-001" in run["specialist_requests"]


def test_hermes_integration(store):
    event = store.create_run(trigger_type="HERMES_RESOLVED", trigger_ref="ch-external")
    run_id = event["payload"]["run_id"]

    store.start(run_id)
    store.health_checked(run_id, "hd-001")
    store.record_specialist_request(run_id, "ho-001")
    store.record_hermes_request(run_id, "ch-001")
    run = store.get_run(run_id)
    assert "ch-001" in run["hermes_challenge_ids"]


# ═══════════════════════════════════════════════════════════════════════════════
# Action / notification integration
# ═══════════════════════════════════════════════════════════════════════════════


def test_action_integration(store):
    event = store.create_run(trigger_type="MANUAL")
    run_id = event["payload"]["run_id"]

    store.start(run_id)
    store.health_checked(run_id, "hd-001")
    store.evidence_built(run_id, "snap-001")
    store.transition(run_id, "ACTION_WRITE", action_id="act-001")
    run = store.get_run(run_id)
    assert run["status"] == "ACTION_WRITE"
    assert "act-001" in run["created_action_ids"]


def test_notification_integration(store):
    event = store.create_run(trigger_type="MANUAL")
    run_id = event["payload"]["run_id"]

    store.start(run_id)
    store.health_checked(run_id, "hd-001")
    store.evidence_built(run_id, "snap-001")
    store.transition(run_id, "ACTION_WRITE")
    store.transition(run_id, "NOTIFICATION_ENQUEUE", notification_id="notif-001")
    run = store.get_run(run_id)
    assert run["status"] == "NOTIFICATION_ENQUEUE"
    assert "notif-001" in run["notification_ids"]


# ═══════════════════════════════════════════════════════════════════════════════
# Idempotency
# ═══════════════════════════════════════════════════════════════════════════════


def test_idempotency(store):
    """Creating runs with different IDs should be independent."""
    e1 = store.create_run(trigger_type="MANUAL", trigger_ref="same-ref")
    e2 = store.create_run(trigger_type="MANUAL", trigger_ref="same-ref")
    assert e1["payload"]["run_id"] != e2["payload"]["run_id"]
    assert e1["payload"]["trigger_hash"] != e2["payload"]["trigger_hash"]


# ═══════════════════════════════════════════════════════════════════════════════
# Hash chain
# ═══════════════════════════════════════════════════════════════════════════════


def test_hash_chain(store):
    event = store.create_run(trigger_type="MANUAL")
    run_id = event["payload"]["run_id"]

    store.start(run_id)
    store.health_checked(run_id, "hd-001")
    store.evidence_built(run_id, "snap-001")
    store.complete(run_id, "art-001")

    ok, msg = store.verify_integrity()
    assert ok, msg


# ═══════════════════════════════════════════════════════════════════════════════
# Projection rebuild
# ═══════════════════════════════════════════════════════════════════════════════


def test_projection_rebuild(store):
    """Projection should rebuild correctly from raw events."""
    e1 = store.create_run(trigger_type="MANUAL", trigger_ref="r1")
    e2 = store.create_run(trigger_type="MANUAL", trigger_ref="r2")
    r1 = e1["payload"]["run_id"]
    r2 = e2["payload"]["run_id"]

    store.start(r1)
    store.health_checked(r1, "hd-001")
    store.evidence_built(r1, "snap-001")

    store.start(r2)
    store.health_checked(r2, "hd-002")

    # Rebuild both — r1 should be CIO_SYNTHESIS (no specialists requested)
    run1 = store.get_run(r1)
    run2 = store.get_run(r2)
    assert run1["status"] == "CIO_SYNTHESIS"
    assert run2["status"] == "EVIDENCE_BUILD"
    assert run1["trigger_ref"] == "r1"
    assert run2["trigger_ref"] == "r2"


# ═══════════════════════════════════════════════════════════════════════════════
# Crash recovery
# ═══════════════════════════════════════════════════════════════════════════════


def test_crash_recovery(store):
    """After a simulated crash, a new store reading the same file should recover."""
    # Create and advance a run
    event = store.create_run(trigger_type="MANUAL")
    run_id = event["payload"]["run_id"]
    store.start(run_id)
    store.health_checked(run_id, "hd-001")

    # "Crash" — create a new store pointing to the same file
    store2 = CIORunStore(str(store.store_path))
    run = store2.get_run(run_id)
    assert run is not None
    assert run["status"] == "EVIDENCE_BUILD"
    assert run["health_decision_id"] == "hd-001"

    # Continue from recovered state
    store2.evidence_built(run_id, "snap-002")
    run = store2.get_run(run_id)
    assert run["status"] == "CIO_SYNTHESIS"

    # Verify integrity
    ok, msg = store2.verify_integrity()
    assert ok, msg


# ═══════════════════════════════════════════════════════════════════════════════
# Concurrent runs
# ═══════════════════════════════════════════════════════════════════════════════


def test_concurrent_runs(store):
    """Multiple runs should be independent."""
    e1 = store.create_run(trigger_type="MANUAL", trigger_ref="r1")
    e2 = store.create_run(trigger_type="MANUAL", trigger_ref="r2")
    r1 = e1["payload"]["run_id"]
    r2 = e2["payload"]["run_id"]

    # Advance r1
    store.start(r1)
    store.health_checked(r1, "hd-001")
    store.evidence_built(r1, "snap-001")
    store.complete(r1, "art-001")

    # Advance r2 partially
    store.start(r2)
    store.health_checked(r2, "hd-002")

    # Check both
    run1 = store.get_run(r1)
    run2 = store.get_run(r2)
    assert run1["status"] == "COMPLETED"
    assert run2["status"] == "EVIDENCE_BUILD"


# ═══════════════════════════════════════════════════════════════════════════════
# List runs
# ═══════════════════════════════════════════════════════════════════════════════


def test_list_runs(store):
    store.create_run(trigger_type="MANUAL", trigger_ref="r1")
    store.create_run(trigger_type="MANUAL", trigger_ref="r2")
    store.create_run(trigger_type="MANUAL", trigger_ref="r3")

    runs = store.list_runs()
    assert len(runs) == 3


def test_list_runs_filtered(store):
    e1 = store.create_run(trigger_type="MANUAL", trigger_ref="r1")
    store.create_run(trigger_type="MANUAL", trigger_ref="r2")

    store.start(e1["payload"]["run_id"])

    queued = store.list_runs(status="QUEUED")
    health = store.list_runs(status="HEALTH_CHECK")
    assert len(queued) == 1
    assert len(health) == 1


# ═══════════════════════════════════════════════════════════════════════════════
# Edge cases
# ═══════════════════════════════════════════════════════════════════════════════


def test_get_nonexistent_run(store):
    run = store.get_run("nonexistent")
    assert run is None


def test_transition_nonexistent_run(store):
    with pytest.raises(ValueError, match="Run not found"):
        store.start("nonexistent")


def test_create_default_values(store):
    event = store.create_run(trigger_type="MANUAL")
    run = store.get_run(event["payload"]["run_id"])
    assert run["status"] == "QUEUED"
    assert run["priority"] == "NORMAL"
    assert run["required_domains"] == []
    assert run["parent_action_ids"] == []
    assert run["parent_handoff_ids"] == []
    assert run["counters"]["provider_calls"] == 0
    assert run["counters"]["cost_usd"] == 0.0


def test_complete_run_timestamp(store):
    event = store.create_run(trigger_type="MANUAL")
    run_id = event["payload"]["run_id"]

    store.start(run_id)
    store.health_checked(run_id, "hd-001")
    store.evidence_built(run_id, "snap-001")
    store.complete(run_id)

    run = store.get_run(run_id)
    assert run["completed_at"] is not None
    assert run["started_at"] is not None


def test_state_transitions_completeness():
    """Verify all defined statuses have transitions defined."""
    for status in RUN_STATUSES:
        if status not in TERMINAL_STATUSES:
            assert status in STATE_TRANSITIONS, f"Missing transitions for {status}"
            assert len(STATE_TRANSITIONS[status]) > 0, f"No transitions from {status}"


def test_trigger_types():
    """Verify all trigger types are valid."""
    for tt in VALID_TRIGGER_TYPES:
        # Just verify the constant exists and is a string
        assert isinstance(tt, str)
        assert len(tt) > 0
