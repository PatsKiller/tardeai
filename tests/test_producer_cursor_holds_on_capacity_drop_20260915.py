"""The producer must not advance a cursor past candidates it dropped — 2026-09-15.

Every adapter reads strictly forward (``WHERE <cursor_key> > cursor``); nothing ever looks back.
So when max_queue_depth forces a candidate to be dropped and the cursor still advances past its
source row, that row is never offered again.

Measured on 2026-09-15, minutes after the production read-only role brought the sources online:
10 producer runs produced 1,344 candidates and accepted 256. The queues were full of an August
backlog, so 1,088 candidates were dropped (watch:artifacts 640, outcomes:recommendations all 192,
watch:refresh_jobs 128, research:hermes 128) while the cursors advanced regardless.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from agent_runtime.trigger_intake import InMemoryTriggerIntakeStore, TriggerCandidate  # noqa: E402
from agent_runtime import trigger_producer as tp  # noqa: E402
from agent_runtime.trigger_sources import AdapterResult  # noqa: E402
from agent_runtime.trigger_sources import SourceProbe, SourceState  # noqa: E402


def _candidate(agent_id: str, dedup: str, ts: str) -> TriggerCandidate:
    return TriggerCandidate(
        agent_id=agent_id, trigger_kind="WATCH_ARTIFACT_CHANGED", dedup_key=dedup,
        job_type="watch_ticket_review", payload={"n": dedup},
        source_ref=f"watch:artifacts:{dedup}", source_hash="a" * 64, source_timestamp=ts,
    )


def _run(monkeypatch, store, candidates, cursor_new="2026-07-22T00:00:00+00:00"):
    probe = SourceProbe(source_id="watch:artifacts", state=SourceState.READY, detail="")
    result = AdapterResult("watch:artifacts", probe, tuple(candidates),
                           (("watch:artifacts", "generated_at", cursor_new),))
    monkeypatch.setattr(tp, "run_adapter", lambda sid, cv: result)
    return tp.produce_once(store, sources=["watch:artifacts"])


def test_cursor_is_held_when_capacity_forces_a_drop(monkeypatch):
    store = InMemoryTriggerIntakeStore()
    spec = tp.FLEET["sentinel"]
    # fill sentinel to max_queue_depth so the next candidate must be dropped
    for i in range(spec.max_queue_depth):
        store.enqueue(_candidate("sentinel", f"fill-{i}", "2026-07-20T00:00:00+00:00"))
    before = store.get_cursor("watch:artifacts", "generated_at")

    payload = _run(monkeypatch, store, [_candidate("sentinel", "new-1", "2026-07-21T00:00:00+00:00")])

    assert payload["dropped_for_capacity"] == 1
    assert "watch:artifacts" in payload["cursors_held"]
    assert store.get_cursor("watch:artifacts", "generated_at") == before, \
        "cursor advanced past a dropped candidate — that row can never be re-read"


def test_cursor_advances_when_everything_was_accepted(monkeypatch):
    store = InMemoryTriggerIntakeStore()
    payload = _run(monkeypatch, store, [_candidate("sentinel", "new-1", "2026-07-21T00:00:00+00:00")])
    assert payload["dropped_for_capacity"] == 0
    assert payload["cursors_held"] == []
    assert store.get_cursor("watch:artifacts", "generated_at") == "2026-07-22T00:00:00+00:00"


def test_duplicates_do_not_hold_the_cursor(monkeypatch):
    """A duplicate was already enqueued once, so the evidence is not lost — keep advancing."""
    store = InMemoryTriggerIntakeStore()
    store.enqueue(_candidate("sentinel", "dup-1", "2026-07-21T00:00:00+00:00"))
    payload = _run(monkeypatch, store, [_candidate("sentinel", "dup-1", "2026-07-21T00:00:00+00:00")])
    assert payload["duplicates"] == 1
    assert payload["dropped_for_capacity"] == 0
    assert payload["cursors_held"] == []
    assert store.get_cursor("watch:artifacts", "generated_at") == "2026-07-22T00:00:00+00:00"


def test_the_held_cursor_lets_the_next_run_re_offer_the_same_row(monkeypatch):
    """Holding is only useful if the row comes back once capacity frees."""
    store = InMemoryTriggerIntakeStore()
    spec = tp.FLEET["sentinel"]
    for i in range(spec.max_queue_depth):
        store.enqueue(_candidate("sentinel", f"fill-{i}", "2026-07-20T00:00:00+00:00"))
    _run(monkeypatch, store, [_candidate("sentinel", "new-1", "2026-07-21T00:00:00+00:00")])

    # drain the queue, then the identical candidate is offered again and now fits
    for row in store.lease("sentinel", limit=spec.max_queue_depth, lease_owner="t"):
        store.ack_completed(row.intake_id, run_id="r-1")
    payload = _run(monkeypatch, store, [_candidate("sentinel", "new-1", "2026-07-21T00:00:00+00:00")])
    assert payload["enqueued"] == 1
    assert payload["cursors_held"] == []
