"""R2: truncated trailing JSONL must not wedge enqueue (ENOSPC mid-write)."""
from __future__ import annotations

import json
from pathlib import Path

from scripts.lib.cio_wake_jobs import CIOWakeJobStore


def test_quarantine_corrupt_trailing_events(tmp_path: Path) -> None:
    path = tmp_path / "cio_wake_jobs.jsonl"
    store = CIOWakeJobStore(event_store_path=path)
    # Append one good event via public API, then corrupt the tail manually.
    store.enqueue(
        {
            "wake_job_id": "wake_test_1",
            "trigger_type": "EVENT_BUS",
            "trigger_ref": "ev1",
            "trigger_hash": "h1",
            "reason_codes": ["EVENT_BUS"],
            "required_domains": ["portfolio"],
            "wake_intent": "NEW_RUN",
            "idempotency_key": "wake_test_1",
            "context": {"target_agent": "alex"},
        },
        actor_id="test",
        actor_type="system",
        authority="READ_ONLY_ADVISORY",
    )
    with path.open("a", encoding="utf-8") as fh:
        fh.write('{"actor_id": "truncated", "wake_job_id": "wake_goal_goal_f')

    result = store.quarantine_corrupt_trailing_events()
    assert result["removed"] >= 1
    last = store._get_last_event()
    assert last is not None
    assert last.get("stream_id") == "wake_test_1" or last.get("payload", {}).get("wake_job_id") == "wake_test_1"
    # Enqueue of a second job must succeed after repair.
    store.enqueue(
        {
            "wake_job_id": "wake_test_2",
            "trigger_type": "EVENT_BUS",
            "trigger_ref": "ev2",
            "trigger_hash": "h2",
            "reason_codes": ["EVENT_BUS"],
            "required_domains": ["portfolio"],
            "wake_intent": "NEW_RUN",
            "idempotency_key": "wake_test_2",
            "context": {"target_agent": "alex"},
        },
        actor_id="test",
        actor_type="system",
        authority="READ_ONLY_ADVISORY",
    )
    assert store.get_wake_job("wake_test_2") is not None
