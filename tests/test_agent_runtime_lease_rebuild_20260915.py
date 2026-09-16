"""Runners lease the governed trigger queue, and settle it honestly — 2026-09-15.

PostgresTriggerIntakeStore.lease had zero callers in the tree. The producer wrote
agentic_runtime.trigger_intake from July onward and nothing ever read it, so rows aged past
stale_input_seconds into REFUSED_STALE (argus 1,367, risk_agent 1,367, darwin 688) and each
agent's queue filled to max_queue_depth 64, which stopped the producer from enqueueing at all.

trigger_intake.intake_row_to_job_request was written for exactly this and could never run: it
passes intake_id= and payload= to a JobRequest that had neither field, so every call raised
TypeError. This rebuild adds the fields and uses that helper instead of a parallel conversion.

Two honesty properties are pinned here:
  * a leased job carries the row's REAL source_timestamp, so genuinely old evidence is refused
    as stale rather than restamped "now" to slip past the dispatcher's freshness gate;
  * a row is acked COMPLETED only with the run id the processor actually minted — with no run
    id the lease is left to expire and the job retries, never falsely recorded as done.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from agent_runtime.trigger_intake import (  # noqa: E402
    InMemoryTriggerIntakeStore,
    TriggerCandidate,
    intake_row_to_job_request,
)
from agent_runtime.agents.dispatcher import JobOutcome, JobRequest, JobResult  # noqa: E402

import agent_runtime_live_providers as lp  # noqa: E402


def _iso(**delta) -> str:
    return (datetime.now(timezone.utc) - timedelta(**delta)).isoformat()


def _candidate(dedup: str, ts: str, agent: str = "darwin") -> TriggerCandidate:
    return TriggerCandidate(
        agent_id=agent, trigger_kind="WATCH_ARTIFACT_CHANGED", dedup_key=dedup,
        job_type="watch_ticket_review", payload={"symbol": "WMT", "dedup": dedup},
        source_ref=f"watch:artifacts:{dedup}", source_hash="h" * 64, source_timestamp=ts,
    )


def _store(rows):
    s = InMemoryTriggerIntakeStore()
    for dedup, ts in rows:
        assert s.enqueue(_candidate(dedup, ts)).name == "ENQUEUED"
    return s


def test_the_existing_helper_now_constructs_a_job_request():
    """It passed intake_id= and payload= to a JobRequest that had neither — TypeError, 0 callers."""
    s = _store([("a", _iso(seconds=30))])
    row = s.lease("darwin", limit=1, lease_owner="t")[0]
    job = intake_row_to_job_request(row)
    assert isinstance(job, JobRequest)
    assert job.intake_id == row.intake_id
    assert job.payload == {"symbol": "WMT", "dedup": "a"}
    assert job.enqueued_at == row.source_timestamp


def test_leased_job_carries_the_rows_real_source_timestamp():
    old = _iso(days=30)
    jobs, _ = lp.job_source_with_acks("darwin", 1, store=_store([("old", old)]))
    assert jobs[0].enqueued_at == old, "a runner must not restamp old evidence as fresh"


def test_stale_result_settles_the_row():
    s = _store([("old", _iso(days=30))])
    jobs, ack = lp.job_source_with_acks("darwin", 1, store=s)
    summary = ack([JobResult(jobs[0].input_hash, JobOutcome.REFUSED_STALE, "input older than stale_input_seconds")])
    assert summary["acked"] == 1
    assert next(iter(s._rows.values()))["state"] == "REFUSED_STALE"


def test_completed_is_acked_with_the_run_id_the_processor_minted():
    s = _store([("fresh", _iso(seconds=30))])
    jobs, ack = lp.job_source_with_acks("darwin", 1, store=s)
    lp._RUN_IDS[jobs[0].input_hash] = "darwin-abc123def456"
    summary = ack([JobResult(jobs[0].input_hash, JobOutcome.COMPLETED, "processed")])
    assert summary["acked"] == 1
    row = next(iter(s._rows.values()))
    assert row["state"] == "COMPLETED"
    assert row["last_run_id"] == "darwin-abc123def456"


def test_completed_without_a_run_id_is_never_acked_with_an_invented_one():
    s = _store([("fresh", _iso(seconds=30))])
    jobs, ack = lp.job_source_with_acks("darwin", 1, store=s)
    lp._RUN_IDS.clear()
    summary = ack([JobResult(jobs[0].input_hash, JobOutcome.COMPLETED, "processed")])
    assert summary["acked"] == 0
    row = next(iter(s._rows.values()))
    assert row["state"] == "LEASED", "stays leased and retries, never falsely completed"
    assert row["last_run_id"] is None


def test_capacity_refusal_leaves_the_row_for_the_next_batch():
    s = _store([("a", _iso(seconds=30)), ("b", _iso(seconds=20))])
    jobs, ack = lp.job_source_with_acks("darwin", 2, store=s)
    ack([JobResult(jobs[0].input_hash, JobOutcome.REFUSED_CAPACITY, "batch concurrency cap reached")])
    assert sorted(r["state"] for r in s._rows.values()) == ["LEASED", "LEASED"]


def test_dispatch_boot_settles_the_batch():
    src = (ROOT / "scripts" / "agent_runtime_dispatch_boot.py").read_text()
    assert "job_source_with_acks" in src
    assert 'summary["intake"] = ack(results)' in src
