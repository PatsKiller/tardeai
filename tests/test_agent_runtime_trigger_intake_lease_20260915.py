"""The governed trigger queue is leased, worked and settled — 2026-09-15.

The producer has written agentic_runtime.trigger_intake since July; nothing ever leased it.
Every row therefore aged past stale_input_seconds and each agent's queue sat at
max_queue_depth (64), which stopped the producer from enqueueing anything new. These tests
pin the two properties that make leasing honest:

  * a leased row carries its REAL source timestamp into the dispatcher, so genuinely old
    evidence is refused as stale instead of being restamped "now" to slip past the gate;
  * a row is only acked COMPLETED with the run id the processor actually minted — never an
    invented one. With no run id the lease is left to expire and the row is retried.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from agent_runtime.trigger_intake import (  # noqa: E402
    InMemoryTriggerIntakeStore,
    TriggerCandidate,
)

import agent_runtime_live_providers as lp  # noqa: E402


def _candidate(agent: str, dedup: str, source_ts: str) -> TriggerCandidate:
    return TriggerCandidate(
        agent_id=agent,
        trigger_kind="WATCH_DECISION",
        dedup_key=dedup,
        job_type="watch_decision_review",
        payload={"symbol": "WMT", "dedup": dedup},
        source_ref=f"watchlist_items:{dedup}",
        source_hash="h" * 16,
        source_timestamp=source_ts,
    )


def _store_with(rows):
    store = InMemoryTriggerIntakeStore()
    for dedup, ts in rows:
        assert store.enqueue(_candidate("darwin", dedup, ts)).name == "ENQUEUED"
    return store


def _iso(**delta) -> str:
    return (datetime.now(timezone.utc) - timedelta(**delta)).isoformat()


def test_leased_job_carries_the_rows_real_source_timestamp():
    """A runner must not restamp old evidence as fresh to get it past the staleness gate."""
    old = _iso(days=30)
    store = _store_with([("wmt-old", old)])
    jobs, _ack = lp.job_source_with_acks("darwin", 1, store=store)
    assert len(jobs) == 1
    assert jobs[0].enqueued_at == old, "leased job must carry the row's own source timestamp"
    assert jobs[0].job_type == "watch_decision_review"
    assert jobs[0].trigger_kind == "WATCH_DECISION"


def test_stale_result_settles_the_row_as_refused_stale():
    store = _store_with([("wmt-old", _iso(days=30))])
    jobs, ack = lp.job_source_with_acks("darwin", 1, store=store)
    from agent_runtime.agents.dispatcher import JobOutcome, JobResult

    summary = ack([JobResult(jobs[0].input_hash, JobOutcome.REFUSED_STALE, "input older than stale_input_seconds")])
    assert summary["acked"] == 1
    row = next(iter(store._rows.values()))
    assert row["state"] == "REFUSED_STALE"
    assert "stale" in str(row["last_outcome"]).lower()


def test_completed_row_is_acked_with_the_run_id_the_processor_minted():
    store = _store_with([("wmt-fresh", _iso(seconds=30))])
    jobs, ack = lp.job_source_with_acks("darwin", 1, store=store)
    from agent_runtime.agents.dispatcher import JobOutcome, JobResult

    lp._RUN_IDS[jobs[0].input_hash] = "darwin-abc123def456"
    summary = ack([JobResult(jobs[0].input_hash, JobOutcome.COMPLETED, "processed")])
    assert summary["acked"] == 1
    row = next(iter(store._rows.values()))
    assert row["state"] == "COMPLETED"
    assert row["last_run_id"] == "darwin-abc123def456", "must record the real run id"


def test_completed_without_a_run_id_is_never_acked_with_an_invented_one():
    store = _store_with([("wmt-fresh", _iso(seconds=30))])
    jobs, ack = lp.job_source_with_acks("darwin", 1, store=store)
    from agent_runtime.agents.dispatcher import JobOutcome, JobResult

    lp._RUN_IDS.clear()  # processor never published a run id for this job
    summary = ack([JobResult(jobs[0].input_hash, JobOutcome.COMPLETED, "processed")])
    assert summary["acked"] == 0
    row = next(iter(store._rows.values()))
    assert row["state"] == "LEASED", "row stays leased and is retried, not falsely completed"
    assert row["last_run_id"] is None


def test_capacity_refusal_leaves_the_row_for_the_next_batch():
    store = _store_with([("a", _iso(seconds=30)), ("b", _iso(seconds=20))])
    jobs, ack = lp.job_source_with_acks("darwin", 2, store=store)
    from agent_runtime.agents.dispatcher import JobOutcome, JobResult

    ack([JobResult(jobs[0].input_hash, JobOutcome.REFUSED_CAPACITY, "batch concurrency cap reached")])
    states = sorted(r["state"] for r in store._rows.values())
    assert states == ["LEASED", "LEASED"], "capacity refusals requeue via lease expiry, never terminal"


def test_dispatch_boot_prefers_the_acking_source():
    """The boot path must hand batch results back so leased rows get settled."""
    src = (ROOT / "scripts" / "agent_runtime_dispatch_boot.py").read_text()
    assert "job_source_with_acks" in src
    assert 'summary["intake"] = ack(results)' in src
