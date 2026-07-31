"""Trigger intake queue persistence tests."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agent_runtime.trigger_intake import (  # noqa: E402
    EnqueueOutcome,
    InMemoryTriggerIntakeStore,
    TriggerCandidate,
    intake_row_to_job_request,
)

_NOW = datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc)


def _clock():
    return _NOW


def _candidate(**overrides):
    base = {
        "agent_id": "sentinel",
        "trigger_kind": "WATCH_ARTIFACT_CHANGED",
        "dedup_key": "watch:1",
        "job_type": "watch_ticket_review",
        "payload": {"packet_id": "p1", "symbol": "LAB"},
        "source_ref": "watch:artifacts:p1",
        "source_hash": "a" * 64,
        "source_timestamp": _NOW.isoformat(),
    }
    base.update(overrides)
    return TriggerCandidate(**base)


def test_enqueue_duplicate_is_idempotent():
    store = InMemoryTriggerIntakeStore(clock=_clock)
    first = store.enqueue(_candidate())
    second = store.enqueue(_candidate(dedup_key="watch:1"))
    assert first == EnqueueOutcome.ENQUEUED
    assert second == EnqueueOutcome.DUPLICATE
    assert store.queue_stats("sentinel")["queued"] == 1


def test_lease_and_ack_completed():
    store = InMemoryTriggerIntakeStore(clock=_clock)
    store.enqueue(_candidate())
    rows = store.lease("sentinel", limit=1, lease_owner="drain-1")
    assert len(rows) == 1
    job = intake_row_to_job_request(rows[0])
    assert job.intake_id == rows[0].intake_id
    assert job.payload is not None
    store.ack_completed(rows[0].intake_id, run_id="run_abc")
    stats = store.queue_stats("sentinel")
    assert stats["queued"] == 0
    assert stats["completed"] == 1


def test_expired_lease_returns_to_queue():
    store = InMemoryTriggerIntakeStore(clock=_clock)
    store.enqueue(_candidate(dedup_key="watch:2"))
    rows = store.lease("sentinel", limit=1, lease_owner="drain-1", lease_seconds=1)
    assert rows
    store._clock = lambda: _NOW + timedelta(seconds=5)
    assert store.return_expired_leases() == 1
    assert store.queue_stats("sentinel")["queued"] == 1


def test_no_cross_agent_dequeue():
    store = InMemoryTriggerIntakeStore(clock=_clock)
    store.enqueue(_candidate(agent_id="sentinel", dedup_key="s1"))
    store.enqueue(
        _candidate(
            agent_id="darwin",
            dedup_key="d1",
            job_type="artifact_scoring",
            trigger_kind="SCHEDULED_SWEEP",
        )
    )
    darwin_rows = store.lease("darwin", limit=5, lease_owner="drain")
    assert len(darwin_rows) == 1
    assert darwin_rows[0].agent_id == "darwin"
    assert store.queue_stats("sentinel")["queued"] == 1


def test_ack_refused_stale_and_failed():
    store = InMemoryTriggerIntakeStore(clock=_clock)
    store.enqueue(_candidate(dedup_key="stale-1"))
    row = store.lease("sentinel", limit=1, lease_owner="drain")[0]
    store.ack_refused_stale(row.intake_id, detail="too old")
    assert store.queue_stats("sentinel")["refused_stale"] == 1
    store.enqueue(_candidate(dedup_key="fail-1"))
    row2 = store.lease("sentinel", limit=1, lease_owner="drain")[0]
    store.ack_failed(row2.intake_id, detail="model unavailable")
    assert store.queue_stats("sentinel")["failed"] == 1


def test_cursor_roundtrip():
    store = InMemoryTriggerIntakeStore(clock=_clock)
    assert store.get_cursor("watch:artifacts", "generated_at") is None
    store.set_cursor("watch:artifacts", "generated_at", _NOW.isoformat(), agent_id="sentinel")
    assert store.get_cursor("watch:artifacts", "generated_at") == _NOW.isoformat()
