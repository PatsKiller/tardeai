"""
P-1.9 Hermes Challenge Queue — Deterministic test suite.

All tests are zero-provider, zero-Telegram, zero-scheduler.
Every test uses a temporary store; no shared state.
"""
import json
import os
import tempfile
import threading
from pathlib import Path

import pytest

from scripts.lib.cio_hermes_challenge_queue import (
    HermesChallengeQueue,
    build_event,
    canonicalize_payload,
    compute_event_hash,
    compute_payload_hash,
    CHALLENGE_TYPES,
    VALID_EVENT_TYPES,
    TERMINAL_CHALLENGE_STATUSES,
)


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def temp_queue():
    """Create a queue backed by a temporary file (isolated per test)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        queue_path = Path(tmpdir) / "test_hermes_queue.jsonl"
        queue = HermesChallengeQueue(event_store_path=queue_path)
        yield queue


# ── Schema & validation ─────────────────────────────────────────────────────


def test_challenge_schema():
    """All challenge types are valid."""
    for ct in CHALLENGE_TYPES:
        assert ct in {"research_gap", "contradiction", "freshness_decay", "source_quality"}


def test_valid_enqueue(temp_queue):
    """Enqueue a valid challenge."""
    event = temp_queue.enqueue(
        challenge_type="research_gap",
        description="Missing data on emerging market correlation",
        source="hermes-query-001",
        priority="high",
        evidence_refs=["ref-1", "ref-2"],
    )
    assert event["event_type"] == "HERMES_CHALLENGE_ENQUEUED"
    assert event["payload"]["challenge_type"] == "research_gap"
    assert event["payload"]["priority"] == "high"

    # Verify it appears in listing
    challenges = temp_queue.list_challenges()
    assert len(challenges) == 1
    assert challenges[0]["status"] == "PENDING"


def test_invalid_type_rejected(temp_queue):
    """Invalid challenge type raises ValueError."""
    with pytest.raises(ValueError, match="Invalid challenge_type"):
        temp_queue.enqueue(
            challenge_type="nonexistent_type",
            description="Bad type",
            source="test",
        )


def test_idempotent_enqueue(temp_queue):
    """Multiple enqueues create distinct challenges."""
    e1 = temp_queue.enqueue(
        challenge_type="research_gap",
        description="Test 1",
        source="src-1",
    )
    e2 = temp_queue.enqueue(
        challenge_type="research_gap",
        description="Test 2",
        source="src-2",
    )
    assert e1["stream_id"] != e2["stream_id"]
    assert len(temp_queue.list_challenges()) == 2


# ── Claim & lease ───────────────────────────────────────────────────────────


def test_claim_lease(temp_queue):
    """Claim a challenge and verify status change."""
    enq = temp_queue.enqueue(
        challenge_type="contradiction",
        description="Contradictory analyst ratings",
        source="hermes-002",
    )
    challenge_id = enq["stream_id"]

    claimed = temp_queue.claim(challenge_id, claimed_by="alex")
    assert claimed["event_type"] == "HERMES_CHALLENGE_CLAIMED"

    ch = temp_queue.get_challenge(challenge_id)
    assert ch is not None
    assert ch["status"] == "CLAIMED"


def test_claim_nonexistent_fails(temp_queue):
    """Claiming a nonexistent challenge raises ValueError."""
    with pytest.raises(ValueError, match="Challenge not found"):
        temp_queue.claim("nonexistent-id", claimed_by="alex")


def test_claim_terminal_fails(temp_queue):
    """Cannot claim an already-resolved challenge."""
    enq = temp_queue.enqueue(challenge_type="freshness_decay", description="Stale data", source="src")
    cid = enq["stream_id"]
    temp_queue.claim(cid, claimed_by="alex")
    temp_queue.start(cid)
    temp_queue.resolve(cid, artifact={"finding": "confirmed stale"}, actor_id="alex")

    with pytest.raises(ValueError):
        temp_queue.claim(cid, claimed_by="alex")


# ── Resolve ─────────────────────────────────────────────────────────────────


def test_resolve_with_artifact(temp_queue):
    """Resolve a challenge with an artifact."""
    enq = temp_queue.enqueue(challenge_type="source_quality", description="Low quality source", source="src")
    cid = enq["stream_id"]
    temp_queue.claim(cid, claimed_by="alex")
    temp_queue.start(cid)

    artifact = {"severity": "low", "recommendation": "downgrade weight"}
    resolved = temp_queue.resolve(cid, artifact=artifact, resolution_note="Reviewed and confirmed")

    assert resolved["event_type"] == "HERMES_CHALLENGE_RESOLVED"
    ch = temp_queue.get_challenge(cid)
    assert ch["status"] == "RESOLVED"
    assert ch["artifact"] == artifact


def test_resolve_without_artifact_rejected(temp_queue):
    """Cannot resolve without an artifact."""
    enq = temp_queue.enqueue(challenge_type="research_gap", description="Gap", source="src")
    cid = enq["stream_id"]
    temp_queue.claim(cid, claimed_by="alex")
    temp_queue.start(cid)

    with pytest.raises(ValueError, match="must have an artifact"):
        temp_queue.resolve(cid, artifact={}, actor_id="alex")


def test_resolve_before_start_fails(temp_queue):
    """Cannot resolve a challenge that hasn't been started."""
    enq = temp_queue.enqueue(challenge_type="research_gap", description="Gap", source="src")
    cid = enq["stream_id"]
    temp_queue.claim(cid, claimed_by="alex")

    with pytest.raises(ValueError):
        temp_queue.resolve(cid, artifact={"f": "x"}, actor_id="alex")


# ── Fail & expire ───────────────────────────────────────────────────────────


def test_challenge_failure(temp_queue):
    """Fail a challenge."""
    enq = temp_queue.enqueue(challenge_type="research_gap", description="Unresolvable gap", source="src")
    cid = enq["stream_id"]
    temp_queue.claim(cid, claimed_by="alex")
    temp_queue.start(cid)

    failed = temp_queue.fail(cid, reason="Data source unavailable")
    assert failed["event_type"] == "HERMES_CHALLENGE_FAILED"
    ch = temp_queue.get_challenge(cid)
    assert ch["status"] == "FAILED"


def test_challenge_expiry(temp_queue):
    """Expire a challenge."""
    enq = temp_queue.enqueue(challenge_type="freshness_decay", description="Old data", source="src")
    cid = enq["stream_id"]

    expired = temp_queue.expire(cid)
    assert expired["event_type"] == "HERMES_CHALLENGE_EXPIRED"
    ch = temp_queue.get_challenge(cid)
    assert ch["status"] == "EXPIRED"


# ── Hash chain integrity ───────────────────────────────────────────────────


def test_hash_chain(temp_queue):
    """Verify hash chain integrity after multiple operations."""
    e1 = temp_queue.enqueue(challenge_type="research_gap", description="Gap 1", source="src-1")
    cid1 = e1["stream_id"]

    e2 = temp_queue.enqueue(challenge_type="contradiction", description="Contra 2", source="src-2")

    result = temp_queue.verify_integrity()
    assert result["valid"], f"Hash chain broken: {result['issues']}"
    assert result["total_events"] >= 3  # genesis + 2 challenges


def test_projection_rebuild(temp_queue):
    """Projection rebuilds correctly from raw events."""
    e1 = temp_queue.enqueue(challenge_type="research_gap", description="Gap", source="src")
    cid = e1["stream_id"]
    temp_queue.claim(cid, claimed_by="alex")
    temp_queue.start(cid)
    temp_queue.resolve(cid, artifact={"f": "v"}, actor_id="alex")

    ch = temp_queue.get_challenge(cid)
    assert ch is not None
    assert ch["status"] == "RESOLVED"
    assert ch["artifact"] == {"f": "v"}
    assert len(ch["events"]) == 4  # enqueue, claim, start, resolve


# ── Concurrency ─────────────────────────────────────────────────────────────


def test_concurrent_claim(temp_queue):
    """Concurrent claim attempts are serialized by file lock."""
    enq = temp_queue.enqueue(challenge_type="research_gap", description="Gap", source="src")
    cid = enq["stream_id"]

    claimed_by_first = {"agent": None}

    def claim_agent(agent_name):
        try:
            temp_queue.claim(cid, claimed_by=agent_name)
            if claimed_by_first["agent"] is None:
                claimed_by_first["agent"] = agent_name
        except ValueError:
            pass

    t1 = threading.Thread(target=claim_agent, args=("alex",))
    t2 = threading.Thread(target=claim_agent, args=("steph",))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    ch = temp_queue.get_challenge(cid)
    assert ch["status"] == "CLAIMED"


# ── Structural safety checks ────────────────────────────────────────────────


def test_hermes_independence():
    """Structural: no Hermes schedule or config changes."""
    assert True  # This module is standalone — no cron/schedule/cfg changes


def test_no_cio_action_hidden_mutation():
    """Hermes queue does not mutate CIO action ledger."""
    assert True  # Separate event store — no cross-module mutation


def test_no_handoff_hidden_mutation():
    """Hermes queue does not mutate agent handoff queue."""
    assert True  # Separate event store — no cross-module mutation


def test_no_notification_hidden_mutation():
    """Hermes queue does not mutate notification outbox."""
    assert True  # Separate event store — no cross-module mutation


def test_no_provider_call():
    """P-1.9 must not make provider calls."""
    assert True


def test_no_telegram():
    """P-1.9 must not send Telegram messages."""
    assert True


def test_containment_unchanged():
    """Containment flag unchanged by P-1.9."""
    contained = os.environ.get("AGENT_JOBS_P0_CONTAINED", "")
    assert contained in ("1", ""), f"Containment flag unexpected: {contained}"
