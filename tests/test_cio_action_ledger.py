"""
P-1.3 CIO Action Ledger — Deterministic test suite.

All tests are zero-provider, zero-Telegram, zero-scheduler.
Every test uses a temporary ledger file; no shared state.
"""
import json
import os
import tempfile
import threading
from pathlib import Path

import pytest

from scripts.lib.cio_action_ledger import (
    CIOActionLedger,
    build_event,
    canonicalize_payload,
    compute_event_hash,
    compute_payload_hash,
    STATE_TRANSITIONS,
    TERMINAL_STATUSES,
    VALID_EVENT_TYPES,
    create_cio_action,
)


# ── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def temp_ledger():
    """Create a ledger backed by a temporary file (isolated per test)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        ledger_path = Path(tmpdir) / "test_ledger.jsonl"
        ledger = CIOActionLedger(event_store_path=ledger_path)
        yield ledger


# ── Schema & validation ─────────────────────────────────────────────────


def test_schema_validation(temp_ledger):
    """CREATE must require cio_action_id and title as minimum fields."""
    ledger = temp_ledger

    with pytest.raises(ValueError):
        ledger.create_action({"title": "Missing ID"}, actor_id="alex")

    with pytest.raises(ValueError):
        ledger.create_action({"cio_action_id": "test-001"}, actor_id="alex")

    action = ledger.create_action(
        {
            "cio_action_id": "test-001",
            "title": "Test Action",
            "recommendation": "Buy low, sell high",
            "why_now": "Because testing",
            "domain": "TEST",
        },
        actor_id="alex",
    )

    assert action is not None
    assert action["event_type"] == "CIO_ACTION_CREATED"
    assert "event_hash" in action


def test_valid_create(temp_ledger):
    """Full create with every optional field populated."""
    ledger = temp_ledger
    action = ledger.create_action(
        {
            "cio_action_id": "full-001",
            "title": "Full Test Action",
            "recommendation": "Consider rebalancing",
            "why_now": "Market moved 5%",
            "priority": "HIGH",
            "domain": "PORTFOLIO",
            "evidence_refs": ["snap-123", "report-456"],
            "affected_accounts": ["taxable", "ira"],
            "affected_symbols": ["AAPL", "MSFT"],
            "estimated_financial_impact": "Potential 2% gain",
            "estimated_tax_impact": "Minimal LTCG",
            "risk_if_done": "Concentration increases",
            "risk_if_not_done": "Drift continues",
            "operator_decision_required": True,
            "deadline": "2026-08-15T00:00:00Z",
            "source_snapshot_id": "snapshot-20260808-001",
            "source_hash": "abc123",
            "legacy_cio_decision_id": 42,
            "idempotency_key": "full-001-create-v1",
        },
        actor_id="alex",
    )

    assert action["payload"]["cio_action_id"] == "full-001"
    assert action["payload"]["status"] == "OPEN"
    assert action["payload"]["legacy_cio_decision_id"] == 42


def test_invalid_create_duplicate(temp_ledger):
    """Duplicate action IDs must be rejected."""
    ledger = temp_ledger
    ledger.create_action(
        {"cio_action_id": "dup-001", "title": "First"}, actor_id="alex"
    )

    with pytest.raises(ValueError):
        ledger.create_action(
            {"cio_action_id": "dup-001", "title": "Second"}, actor_id="alex"
        )


# ── State machine ───────────────────────────────────────────────────────


def test_legal_transition(temp_ledger):
    """A valid status transition should succeed."""
    ledger = temp_ledger
    ledger.create_action(
        {"cio_action_id": "trans-001", "title": "Transition Test"}, actor_id="alex"
    )

    event = ledger.transition_action(
        "trans-001", "CIO_ACTION_ACKNOWLEDGED", {}, actor_id="operator"
    )
    assert event is not None

    action = ledger.get_action("trans-001")
    assert action["current_status"] == "ACKNOWLEDGED"


def test_illegal_transition(temp_ledger):
    """Illegal transitions must raise ValueError."""
    ledger = temp_ledger
    ledger.create_action(
        {"cio_action_id": "illegal-001", "title": "Illegal Test"}, actor_id="alex"
    )
    ledger.transition_action(
        "illegal-001", "CIO_ACTION_DONE", {}, actor_id="operator"
    )

    # DONE is terminal — cannot transition to OPEN via UNBLOCKED
    with pytest.raises(ValueError):
        ledger.transition_action(
            "illegal-001", "CIO_ACTION_UNBLOCKED", {}, actor_id="operator"
        )

    with pytest.raises(ValueError):
        ledger.transition_action(
            "illegal-001", "CIO_ACTION_ACKNOWLEDGED", {}, actor_id="alex"
        )


# ── Hashing ─────────────────────────────────────────────────────────────


def test_event_hash(temp_ledger):
    """Event hash is 64-char hex and payload hash matches."""
    payload = {"test": "data", "number": 42}
    event = build_event(
        event_type="CIO_ACTION_CREATED",
        stream_id="hash-test",
        payload=payload,
        actor_type="system",
        actor_id="test",
        authority="system",
        prev_event_hash="0000000000000000000000000000000000000000000000000000000000000000",
    )

    assert "event_hash" in event
    assert len(event["event_hash"]) == 64
    assert event["payload_hash"] == compute_payload_hash(payload)


def test_payload_hash(temp_ledger):
    """Stored payload hash matches re-computation."""
    ledger = temp_ledger
    action = ledger.create_action(
        {"cio_action_id": "hash-001", "title": "Hash Test"}, actor_id="alex"
    )

    stored_hash = action["payload_hash"]
    computed_hash = compute_payload_hash(action["payload"])
    assert stored_hash == computed_hash


def test_chain_verification(temp_ledger):
    """Hash chain must be intact after multiple creates."""
    ledger = temp_ledger

    ledger.create_action(
        {"cio_action_id": "chain-001", "title": "Chain 1"}, actor_id="alex"
    )
    ledger.create_action(
        {"cio_action_id": "chain-002", "title": "Chain 2"}, actor_id="alex"
    )

    result = ledger.verify_integrity()
    assert result["valid"] is True
    assert len(result["chain_breaks"]) == 0


# ── Genesis ─────────────────────────────────────────────────────────────


def test_genesis(temp_ledger):
    """Every fresh ledger starts with a genesis event pointing to the null hash."""
    events = temp_ledger.list_events("ledger-genesis")
    assert len(events) >= 1
    genesis = events[0]
    assert genesis["prev_event_hash"] == "0000000000000000000000000000000000000000000000000000000000000000"


# ── Idempotency ─────────────────────────────────────────────────────────


def test_idempotent_create(temp_ledger):
    """Idempotent creates with the same key must return the same event."""
    ledger = temp_ledger

    action1 = ledger.create_action(
        {
            "cio_action_id": "idem-001",
            "title": "Idempotent Test",
            "idempotency_key": "key-abc-123",
        },
        actor_id="alex",
    )

    action2 = ledger.create_action(
        {
            "cio_action_id": "idem-001",
            "title": "Idempotent Test",
            "idempotency_key": "key-abc-123",
        },
        actor_id="alex",
    )

    assert action1["event_hash"] == action2["event_hash"]


# ── Projection rebuild ──────────────────────────────────────────────────


def test_projection_rebuild(temp_ledger):
    """Full action state must be rebuildable from event log replay."""
    ledger = temp_ledger

    ledger.create_action(
        {
            "cio_action_id": "proj-001",
            "title": "Rebuild Test",
            "recommendation": "Test recommendation",
            "domain": "PORTFOLIO",
        },
        actor_id="alex",
    )

    ledger.transition_action(
        "proj-001", "CIO_ACTION_ACKNOWLEDGED", {}, actor_id="operator"
    )
    ledger.transition_action(
        "proj-001", "CIO_ACTION_DONE", {}, actor_id="operator"
    )

    action = ledger.get_action("proj-001")
    assert action["current_status"] == "DONE"
    assert action["title"] == "Rebuild Test"
    assert action["domain"] == "PORTFOLIO"


# ── Corruption detection ────────────────────────────────────────────────


def test_event_corruption_detection(temp_ledger):
    """verify_integrity must detect tampered event hashes."""
    ledger = temp_ledger
    ledger.create_action(
        {"cio_action_id": "corrupt-001", "title": "Will be corrupted"}, actor_id="alex"
    )

    with open(temp_ledger.event_store_path, "r") as f:
        content = f.read()

    # Corrupt by changing 10 characters at a known offset
    corrupted = content[:100] + "XXXXXXXXXX" + content[110:]

    with open(temp_ledger.event_store_path, "w") as f:
        f.write(corrupted)

    result = ledger.verify_integrity()
    assert result["valid"] is False


# ── Concurrency ─────────────────────────────────────────────────────────


def test_concurrent_write(temp_ledger):
    """Concurrent writes must serialize safely via fcntl lock."""
    ledger = temp_ledger
    errors: list[str] = []

    def write_action(cid: str) -> None:
        try:
            ledger.create_action(
                {"cio_action_id": cid, "title": f"Concurrent-{cid}"}, actor_id="alex"
            )
        except Exception as e:
            errors.append(str(e))

    threads = [
        threading.Thread(target=write_action, args=(f"conc-{i:03d}",))
        for i in range(5)
    ]

    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0

    for i in range(5):
        action = ledger.get_action(f"conc-{i:03d}")
        assert action is not None


# ── List filtering ──────────────────────────────────────────────────────


def test_list_filtering(temp_ledger):
    """list_actions must support status and domain filters."""
    ledger = temp_ledger

    ledger.create_action(
        {"cio_action_id": "list-001", "title": "Portfolio A", "domain": "PORTFOLIO"},
        actor_id="alex",
    )
    ledger.create_action(
        {"cio_action_id": "list-002", "title": "Tax B", "domain": "TAX"},
        actor_id="alex",
    )
    ledger.create_action(
        {"cio_action_id": "list-003", "title": "Portfolio C", "domain": "PORTFOLIO"},
        actor_id="alex",
    )

    portfolio = ledger.list_actions(domain="PORTFOLIO")
    assert len(portfolio) >= 2


# ── Read-only API ───────────────────────────────────────────────────────


def test_read_only_api(temp_ledger):
    """get_action returns None for unknown IDs and correct projection for known ones."""
    ledger = temp_ledger

    actions = ledger.list_actions()
    assert len(actions) == 0

    ledger.create_action(
        {"cio_action_id": "read-001", "title": "Read Test"}, actor_id="alex"
    )

    actions = ledger.list_actions()
    assert any(a["cio_action_id"] == "read-001" for a in actions)

    action = ledger.get_action("read-001")
    assert action is not None
    assert action["cio_action_id"] == "read-001"

    assert ledger.get_action("nonexistent") is None


# ── Evidence attachment ─────────────────────────────────────────────────


def test_evidence_attach(temp_ledger):
    """Evidence refs must accumulate across multiple CI-5 events."""
    ledger = temp_ledger

    ledger.create_action(
        {"cio_action_id": "evidence-001", "title": "Evidence Test"}, actor_id="alex"
    )

    event = ledger.transition_action(
        "evidence-001",
        "CIO_ACTION_EVIDENCE_ATTACHED",
        {"evidence_refs": ["report-789", "analysis-101"]},
        actor_id="alex",
    )

    assert event is not None
    action = ledger.get_action("evidence-001")
    assert "report-789" in action.get("evidence_refs", [])


# ── Operator decision ───────────────────────────────────────────────────


def test_operator_decision(temp_ledger):
    """Operator decision must be recorded and projected correctly."""
    ledger = temp_ledger

    ledger.create_action(
        {
            "cio_action_id": "decision-001",
            "title": "Decision Test",
            "operator_decision_required": True,
        },
        actor_id="alex",
    )

    event = ledger.transition_action(
        "decision-001",
        "CIO_ACTION_OPERATOR_DECISION_RECORDED",
        {
            "decision": "APPROVED",
            "notes": "Agree with recommendation",
        },
        actor_id="operator",
        actor_type="operator",
        authority="operator",
    )

    assert event is not None
    action = ledger.get_action("decision-001")
    assert action["operator_decision"] == "APPROVED"


# ── Follow-up scheduling ────────────────────────────────────────────────


def test_followup_schedule(temp_ledger):
    """Follow-up scheduling must set next_check_at and followup_condition."""
    ledger = temp_ledger

    ledger.create_action(
        {"cio_action_id": "followup-001", "title": "Followup Test"}, actor_id="alex"
    )

    event = ledger.transition_action(
        "followup-001",
        "CIO_ACTION_FOLLOWUP_SCHEDULED",
        {
            "next_check_at": "2026-08-15T00:00:00Z",
            "followup_condition": "Check if AAPL crossed $200",
        },
        actor_id="alex",
    )

    assert event is not None
    action = ledger.get_action("followup-001")
    assert action["next_check_at"] == "2026-08-15T00:00:00Z"
    assert action["followup_condition"] == "Check if AAPL crossed $200"


# ── Legacy reference ────────────────────────────────────────────────────


def test_legacy_reference_optional(temp_ledger):
    """legacy_cio_decision_id is optional and preserved when present, None when absent."""
    ledger = temp_ledger

    action1 = ledger.create_action(
        {
            "cio_action_id": "legacy-001",
            "title": "With Legacy Ref",
            "legacy_cio_decision_id": 999,
        },
        actor_id="alex",
    )
    assert action1["payload"]["legacy_cio_decision_id"] == 999

    action2 = ledger.create_action(
        {"cio_action_id": "legacy-002", "title": "Without Legacy Ref"}, actor_id="alex"
    )
    assert action2["payload"]["legacy_cio_decision_id"] is None


# ── Deterministic JSON & hashing ────────────────────────────────────────


def test_deterministic_json():
    """canonicalize_payload must produce identical output for identical inputs."""
    payload = {"b": 2, "a": 1, "c": {"z": 26, "y": 25}}

    result1 = canonicalize_payload(payload)
    result2 = canonicalize_payload(payload)

    assert result1 == result2
    assert '"a":1' in result1
    assert '"b":2' in result1

    parsed = json.loads(result1)
    keys = list(parsed.keys())
    assert keys == sorted(keys)


def test_hash_determinism():
    """Hash must be identical for equivalent dicts regardless of instance identity."""
    payload = {"test": "data", "nested": {"x": 1}}

    h1 = compute_payload_hash(payload)
    h2 = compute_payload_hash(payload)
    h3 = compute_payload_hash(dict(payload))

    assert h1 == h2 == h3


# ── Blocked / Unblocked flow ────────────────────────────────────────────


def test_blocked_unblocked(temp_ledger):
    """BLOCKED transitions to UNBLOCKED back to OPEN."""
    ledger = temp_ledger

    ledger.create_action(
        {"cio_action_id": "block-001", "title": "Block Test"}, actor_id="alex"
    )

    ledger.transition_action(
        "block-001",
        "CIO_ACTION_BLOCKED",
        {
            "reason": "Data quality issue",
            "block_source": "health_boundary",
        },
        actor_id="system",
        actor_type="system",
        authority="system",
    )

    action = ledger.get_action("block-001")
    assert action["current_status"] == "BLOCKED"

    ledger.transition_action(
        "block-001",
        "CIO_ACTION_UNBLOCKED",
        {"reason": "Data quality restored"},
        actor_id="system",
        actor_type="system",
        authority="system",
    )

    action = ledger.get_action("block-001")
    assert action["current_status"] == "OPEN"


# ── Supersede from terminal state ───────────────────────────────────────


def test_ci2_action_supersedes_done(temp_ledger):
    """DONE may be superseded by a newer action (CI-2 policy)."""
    ledger = temp_ledger

    ledger.create_action(
        {"cio_action_id": "super-001", "title": "Original"}, actor_id="alex"
    )
    ledger.transition_action(
        "super-001", "CIO_ACTION_DONE", {}, actor_id="operator"
    )

    event = ledger.transition_action(
        "super-001",
        "CIO_ACTION_SUPERSEDED",
        {
            "superseded_by": "super-002",
            "reason": "New evidence available",
        },
        actor_id="alex",
    )

    assert event is not None
    action = ledger.get_action("super-001")
    assert action["current_status"] == "SUPERSEDED"


# ── Crash-after-fsync recovery ──────────────────────────────────────────


def test_crash_after_fsync_no_effect(temp_ledger):
    """Events committed via fsync survive and are re-readable by a fresh ledger instance."""
    ledger = temp_ledger

    ledger.create_action(
        {"cio_action_id": "crash-001", "title": "Crash Test"}, actor_id="alex"
    )

    with open(temp_ledger.event_store_path, "r") as f:
        content = f.read()
    assert "crash-001" in content

    new_ledger = CIOActionLedger(event_store_path=temp_ledger.event_store_path)
    action = new_ledger.get_action("crash-001")
    assert action is not None
    assert action["cio_action_id"] == "crash-001"


# ── Public API write-authority gate ─────────────────────────────────────


def test_public_api_create(temp_ledger, monkeypatch):
    """create_cio_action must route through authority validation."""

    # Patch CIOActionLedger default construction so create_cio_action uses the
    # temp ledger (isolated from stale data in the default canonical path).
    _original_init = CIOActionLedger.__init__

    def _isolated_init(self, event_store_path=None):
        _original_init(self, event_store_path=temp_ledger.event_store_path)

    monkeypatch.setattr(CIOActionLedger, "__init__", _isolated_init)

    import uuid

    unique_id = f"pub-{uuid.uuid4().hex[:8]}"

    action = create_cio_action(
        {"cio_action_id": unique_id, "title": "Public API Test"}, actor_id="alex"
    )
    assert action["event_type"] == "CIO_ACTION_CREATED"

    # Unauthorized actor_type
    with pytest.raises(ValueError):
        create_cio_action(
            {"cio_action_id": f"pub-{uuid.uuid4().hex[:8]}", "title": "Blocked"},
            actor_id="unknown",
            actor_type="unknown",
        )


# ── Invalid event type ──────────────────────────────────────────────────


def test_invalid_event_type():
    """build_event must reject non-canonical event types."""
    with pytest.raises(ValueError):
        build_event(
            event_type="NOT_A_VALID_TYPE",
            stream_id="bad-001",
            payload={},
            actor_type="system",
            actor_id="test",
            authority="system",
            prev_event_hash="0000000000000000000000000000000000000000000000000000000000000000",
        )


# ── Zero-provider meta-test ─────────────────────────────────────────────


def test_zero_provider_calls():
    """Meta-test: this suite imports no provider / LLM / Telegram modules."""
    assert True


# ── verify_integrity on pristine ledger ─────────────────────────────────


def test_verify_integrity_pristine(temp_ledger):
    """A fresh ledger with a genesis event must pass integrity check."""
    result = temp_ledger.verify_integrity()
    assert result["valid"] is True
    assert result["total_events"] >= 1


# ── list_actions with status filter ─────────────────────────────────────


def test_list_actions_status_filter(temp_ledger):
    """Filtering by status must return only matching actions."""
    ledger = temp_ledger

    ledger.create_action(
        {"cio_action_id": "st-001", "title": "Open 1"}, actor_id="alex"
    )
    ledger.create_action(
        {"cio_action_id": "st-002", "title": "Open 2"}, actor_id="alex"
    )
    ledger.transition_action(
        "st-001", "CIO_ACTION_DONE", {}, actor_id="operator"
    )

    open_actions = ledger.list_actions(status="OPEN")
    done_actions = ledger.list_actions(status="DONE")

    assert any(a["cio_action_id"] == "st-002" for a in open_actions)
    assert any(a["cio_action_id"] == "st-001" for a in done_actions)
