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


# ── goals:laps — the producer-side caller that never existed ────────────────
#
# Measured 2026-09-17: `enqueue_goal_lap` had ZERO production callers, the lap
# ledger did not exist on disk, and `lap_error`/`goal_touch` appear 0 times in
# the goal log — so `append_lap` was never once reached and every one of 34,912
# wakes was a cold start. These controls cover the adapter that closes that gap.

from agent_runtime import trigger_sources as ts  # noqa: E402
from agent_runtime.agents.definitions import FLEET  # noqa: E402
from lib import goal_generation as gg  # noqa: E402
from lib.cio_goals import CIOGoalStore  # noqa: E402


def _goal_store(tmp_path):
    return CIOGoalStore(
        event_path=tmp_path / "cio_goals.jsonl",
        projection_path=tmp_path / "cio_goals_projection.json",
        cursor_path=tmp_path / "cio_goal_event_cursors.json",
    )


def _arm(monkeypatch, tmp_path, store):
    """Point the adapter at a throwaway store. Nothing touches production."""
    monkeypatch.setenv("AGENT_RUNTIME_GOAL_LAPS", "1")
    monkeypatch.setattr(
        ts, "_goal_lap_modules", lambda: (gg, lambda **kw: store, lambda: str(tmp_path))
    )


def test_goal_laps_are_inert_until_the_operator_arms_them(monkeypatch):
    """Registering an adapter adds it to DEFAULT_SOURCES and the producer timer
    is already live, so an ungated adapter would change an armed lane the moment
    it deployed. Unarmed it must produce nothing and say so."""
    monkeypatch.delenv("AGENT_RUNTIME_GOAL_LAPS", raising=False)
    result = ts._goal_lap_adapter(None)
    assert result.probe.state == ts.SourceState.NOT_CONFIGURED
    assert result.candidates == ()
    assert "operator-armed" in result.probe.detail


def test_armed_goal_laps_yield_one_candidate_per_open_goal(monkeypatch, tmp_path):
    """THE property: a goal with no lap yet must produce exactly one lap."""
    store = _goal_store(tmp_path)
    store.create_goal(owner_agent="alex", title="A", success_criteria="need one")
    store.create_goal(owner_agent="steph", title="B", success_criteria="need two")
    _arm(monkeypatch, tmp_path, store)

    result = ts._goal_lap_adapter(None)
    assert result.probe.state == ts.SourceState.READY
    assert len(result.candidates) == 2
    keys = {c.dedup_key for c in result.candidates}
    assert len(keys) == 2, "two goals must not share one generation key"
    assert all(k.startswith("goal:") for k in keys)
    assert result.cursor_updates == (), "a goal generation is not a forward cursor"


def test_a_goal_owned_outside_the_fleet_is_named_not_silently_dropped(
    monkeypatch, tmp_path
):
    """`hermes` is a legal goal owner (VALID_OWNERS) but is NOT in FLEET and has
    no alias, so a hermes-owned goal can never be leased by anyone.

    `produce_once` drops a non-FLEET candidate with a bare `continue` and no
    counter — the same silence that let orphan timers fire 896 times a day doing
    nothing. The adapter must refuse it AND say whose goal it refused.
    """
    assert "hermes" not in FLEET, "control assumes hermes is outside the fleet"
    store = _goal_store(tmp_path)
    store.create_goal(owner_agent="hermes", title="unleasable", success_criteria="x")
    _arm(monkeypatch, tmp_path, store)

    result = ts._goal_lap_adapter(None)
    assert result.candidates == (), "queued work nobody can lease is worse than none"
    assert "not in FLEET" in result.probe.detail
    assert "hermes" in result.probe.detail, "a silent skip leaves no receipt"


def test_the_guardian_alias_resolves_onto_a_fleet_agent(monkeypatch, tmp_path):
    """guardian -> risk_agent. AGENT_ALIASES is applied only in run_once, not in
    intake or dispatch, so without resolving it here the live guardian-owned goal
    would enqueue for an agent that does not exist."""
    store = _goal_store(tmp_path)
    store.create_goal(owner_agent="guardian", title="G", success_criteria="y")
    _arm(monkeypatch, tmp_path, store)

    result = ts._goal_lap_adapter(None)
    assert len(result.candidates) == 1
    assert result.candidates[0].agent_id == "risk_agent"
    assert result.candidates[0].agent_id in FLEET
