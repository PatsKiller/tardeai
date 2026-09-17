"""A goal can have a SECOND lap, and the second lap can see the first — 2026-09-16.

Measured before this change, on the live ledger (`data/cio/cio_goals.jsonl`, 29 MB):

    GOAL_THESIS_UPDATED   29,774    shadow_run= 29,774 (100%)
                                    PROVIDER_BLOCKED 29,774 (100%)
                                    retrieval_n=0    29,774 (100%)
    GOAL_WAKE_RECORDED    34,809
    GOAL_STATUS_CHANGED        0
    one goal worked 11,457 times, 0 status changes, 0 findings

Four defects produced that, and each of them has a test here:

  (a) `trigger_intake.enqueue` dedups `ON CONFLICT (agent_id, trigger_kind,
      dedup_key) DO NOTHING`. The conflict target has NO state column, so a row
      in ANY terminal state blocks re-enqueue forever, and the key was the
      constant `goal:<goal_id>`. 29,653 duplicates against 1,759 enqueues.
  (b) `dispatcher._process_one` called `self.processor(job)` and DISCARDED the
      return value — the outcome, the goal touch and the retrieval count all
      died one frame above where they were computed.
  (c) `JobOutcome` had nine members and none of them meant "incomplete, continue".
  (d) the model was called at :252 and the goal was loaded at :262 — AFTER — so
      the prompt was built from retrieval rows alone. Every lap a cold start.

The fix is producer-side by necessity: `agentic_runtime.trigger_intake` has no
DDL in this repo (`migrations/agentic_runtime/` declares 0001_mvl's eight tables
and 0002_roles, and `tests/test_agent_runtime_migration_contract.py` asserts
exactly those eight), so amending the UNIQUE constraint would be a §7A/§17
operator-gated change to an authoritative store. The generation token moves the
guarantee into the key instead.

Remove any one guarantee and exactly one of these tests goes red.

    .venv/bin/python -m pytest tests/test_goal_loop_second_lap_20260916.py -q
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
# Match the import identity the runtime uses (scripts/ on path -> agent_runtime.*)
sys.path.insert(0, str(ROOT / "scripts"))

from agent_runtime.agents.definitions import FLEET  # noqa: E402
from agent_runtime.agents.dispatcher import (  # noqa: E402
    BoundedDispatcher,
    JobOutcome,
    JobRequest,
    JobResult,
    batch_summary,
)
from agent_runtime.trigger_intake import (  # noqa: E402
    EnqueueOutcome,
    InMemoryTriggerIntakeStore,
    intake_row_to_job_request,
)

import agent_runtime_live_providers as lp  # noqa: E402
from scripts.lib import goal_generation as gg  # noqa: E402
from scripts.lib.cio_goals import CIOGoalStore  # noqa: E402

AGENT = "alex"
FAR_FUTURE = "2999-01-01T00:00:00+00:00"

PROVIDER_BLOCKED = (
    "PROVIDER_BLOCKED: Financial agent must route through governed gateway. "
    "Direct provider calls removed in Gate-B."
)


# ── fakes ───────────────────────────────────────────────────────────────────


class _Model:
    """Records every prompt it is given; answers from a queue."""

    def __init__(self, responses, *, error=None, order=None):
        self._responses = list(responses)
        self._error = error
        self._order = order
        self.prompts: list[str] = []

    def __call__(self, run_id, request):
        if self._order is not None:
            self._order.append("model")
        self.prompts.append(
            "\n".join(str(m.get("content") or "") for m in request.get("messages") or [])
        )
        text = self._responses.pop(0) if self._responses else ""
        out = {"response": text, "provider": "test", "model": "fake"}
        if self._error:
            out["error"] = self._error
            out["response"] = ""
        return out


class _Retrieval:
    def __init__(self, rows=()):
        self._rows = list(rows)

    def __call__(self, run_id, query):
        return list(self._rows)


class _OrderedStore:
    """Passes everything through, recording WHEN the goal was read."""

    def __init__(self, inner, order):
        self._inner = inner
        self._order = order

    def get_goal(self, goal_id):
        self._order.append("goal")
        return self._inner.get_goal(goal_id)

    def __getattr__(self, name):
        return getattr(self._inner, name)


# ── fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def goals(tmp_path):
    return CIOGoalStore(
        event_path=tmp_path / "cio_goals.jsonl",
        projection_path=tmp_path / "cio_goals_projection.json",
        cursor_path=tmp_path / "cio_goal_event_cursors.json",
    )


@pytest.fixture
def laps(tmp_path):
    return tmp_path / "cio_goal_laps.jsonl"


@pytest.fixture
def goal(goals):
    return goals.create_goal(
        owner_agent=AGENT,
        title="Corroborate the SCHD distribution change",
        success_criteria="independent value from a different pipeline; corroborating publisher",
        linked_symbols=[],
    )


@pytest.fixture
def wired(monkeypatch, goals, laps, tmp_path):
    """Point the live provider at this test's stores. Nothing touches data/."""
    monkeypatch.setattr(lp, "_goal_store", lambda: goals)
    monkeypatch.setattr(lp, "GOAL_LAP_LEDGER_PATH", laps)
    monkeypatch.setattr(lp, "JOURNAL_ROOT", tmp_path / "journals")
    return goals


def _intake():
    return InMemoryTriggerIntakeStore()


def _rows(store, agent_id=AGENT):
    """Total intake rows for the agent, through the public stats API."""
    stats = store.queue_stats(agent_id)
    return sum(
        int(stats.get(k) or 0)
        for k in ("queued", "leased", "completed", "failed", "refused_stale")
    )


def _run_one_lap(store, goals, goal_id, processor):
    """Lease the goal's queued lap and run it through the processor."""
    leased = store.lease(AGENT, limit=1, lease_owner="test")
    assert leased, "a queued lap should be leasable"
    job = intake_row_to_job_request(leased[0])
    return job, processor(job)


def _thesis_events(goals):
    return [
        json.loads(line)
        for line in goals.event_path.read_text().splitlines()
        if line.strip() and json.loads(line).get("event_type") == "GOAL_THESIS_UPDATED"
    ]


def _wake_events(goals):
    return [
        json.loads(line)
        for line in goals.event_path.read_text().splitlines()
        if line.strip() and json.loads(line).get("event_type") == "GOAL_WAKE_RECORDED"
    ]


# ── (a) the generation token ────────────────────────────────────────────────


def test_the_key_is_no_longer_the_constant_that_burned_the_only_slot(goal, laps):
    """`goal:<id>` was the same string for every lap this goal would ever get."""
    gen = gg.generation_for_goal(goal, laps_path=laps)
    assert gen["dedup_key"] != f"goal:{goal['goal_id']}"
    assert gen["dedup_key"].startswith(f"goal:{goal['goal_id']}:v0:")
    assert gen["ledger_digest"] and len(gen["ledger_digest"]) == gg.DIGEST_CHARS
    assert gen["open_needs"] == [
        "corroborating publisher",
        "independent value from a different pipeline",
    ]


def test_one_goal_two_ticks_two_intake_rows_with_different_dedup_keys(
    wired, goals, goal, laps
):
    """THE property. Before: one row, forever, and 29,653 refused duplicates."""
    store = _intake()
    model = _Model(["Lap one: the house pipeline reports 0.7550 as of 2026-09-15."])
    processor = lp._make_agent_processor(AGENT, None, _Retrieval(), model)
    gid = goal["goal_id"]

    first, gen1 = gg.enqueue_goal_lap(store, goals.get_goal(gid), laps_path=laps)
    assert first == EnqueueOutcome.ENQUEUED
    _run_one_lap(store, goals, gid, processor)

    second, gen2 = gg.enqueue_goal_lap(store, goals.get_goal(gid), laps_path=laps)
    assert second == EnqueueOutcome.ENQUEUED
    assert gen1["dedup_key"] != gen2["dedup_key"]
    assert _rows(store) == 2


def test_an_unchanged_ledger_is_still_refused_and_writes_nothing(
    wired, goals, goal, laps
):
    """The negative receipt: dedup must keep doing its real job."""
    store = _intake()
    gid = goal["goal_id"]

    first, _ = gg.enqueue_goal_lap(store, goals.get_goal(gid), laps_path=laps)
    assert first == EnqueueOutcome.ENQUEUED
    before = _rows(store)

    second, _ = gg.enqueue_goal_lap(store, goals.get_goal(gid), laps_path=laps)
    assert second == EnqueueOutcome.DUPLICATE
    assert _rows(store) == before == 1


def test_a_lap_that_learned_nothing_earns_no_new_lap(wired, goals, goal, laps):
    """PROVIDER_BLOCKED with retrieval_n=0 is exactly the live case: 29,774 of them.

    It must not mint a generation. This is why the storm cannot recur.
    """
    store = _intake()
    model = _Model([""], error=PROVIDER_BLOCKED)
    processor = lp._make_agent_processor(AGENT, None, _Retrieval(), model)
    gid = goal["goal_id"]

    assert gg.enqueue_goal_lap(store, goals.get_goal(gid), laps_path=laps)[0] == (
        EnqueueOutcome.ENQUEUED
    )
    _, result = _run_one_lap(store, goals, gid, processor)
    assert result["model_error"].startswith("PROVIDER_BLOCKED")
    assert result["continuation"]["made_progress"] is False

    again, _ = gg.enqueue_goal_lap(store, goals.get_goal(gid), laps_path=laps)
    assert again == EnqueueOutcome.DUPLICATE
    assert _rows(store) == 1


def test_a_lap_that_repeats_itself_earns_no_new_lap(wired, goals, goal, laps):
    """Two laps, same conclusion: same content hash, same generation, refused."""
    store = _intake()
    same = "The house pipeline reports 0.7550; no second publisher found."
    model = _Model([same, same])
    processor = lp._make_agent_processor(AGENT, None, _Retrieval(), model)
    gid = goal["goal_id"]

    gg.enqueue_goal_lap(store, goals.get_goal(gid), laps_path=laps)
    _run_one_lap(store, goals, gid, processor)
    assert gg.enqueue_goal_lap(store, goals.get_goal(gid), laps_path=laps)[0] == (
        EnqueueOutcome.ENQUEUED
    )
    _run_one_lap(store, goals, gid, processor)

    third, _ = gg.enqueue_goal_lap(store, goals.get_goal(gid), laps_path=laps)
    assert third == EnqueueOutcome.DUPLICATE
    assert _rows(store) == 2


# ── (d) two artifacts, and the second prompt sees the first ─────────────────


def test_two_laps_write_two_artifacts_with_different_payload_hashes(
    wired, goals, goal, laps
):
    store = _intake()
    model = _Model(
        [
            "Lap one: house pipeline 0.7550 as of 2026-09-15.",
            "Lap two: Reuters confirms 0.7550, an independent publisher.",
        ]
    )
    processor = lp._make_agent_processor(AGENT, None, _Retrieval(), model)
    gid = goal["goal_id"]

    for _ in range(2):
        assert gg.enqueue_goal_lap(store, goals.get_goal(gid), laps_path=laps)[0] == (
            EnqueueOutcome.ENQUEUED
        )
        _run_one_lap(store, goals, gid, processor)

    recorded = gg.read_laps(gid, path=laps)
    assert len(recorded) == 2
    assert recorded[0]["payload_hash"] != recorded[1]["payload_hash"]
    assert recorded[0]["artifact_id"] != recorded[1]["artifact_id"]
    assert [r["lap"] for r in recorded] == [1, 2]


def test_the_second_prompt_contains_the_first_artifacts_finding(
    wired, goals, goal, laps
):
    """The agent finally sees its own prior work instead of starting cold."""
    store = _intake()
    first_finding = "Lap one: house pipeline 0.7550 as of 2026-09-15."
    model = _Model([first_finding, "Lap two: corroborated by Reuters."])
    processor = lp._make_agent_processor(AGENT, None, _Retrieval(), model)
    gid = goal["goal_id"]

    for _ in range(2):
        gg.enqueue_goal_lap(store, goals.get_goal(gid), laps_path=laps)
        _run_one_lap(store, goals, gid, processor)

    assert len(model.prompts) == 2
    assert first_finding not in model.prompts[0]
    assert first_finding in model.prompts[1]
    assert "PRIOR LAP" in model.prompts[1]


def test_the_prompt_carries_goal_predicate_and_need_ledger(wired, goals, goal, laps):
    store = _intake()
    model = _Model(["noted"])
    processor = lp._make_agent_processor(AGENT, None, _Retrieval(), model)
    gid = goal["goal_id"]

    gg.enqueue_goal_lap(store, goals.get_goal(gid), laps_path=laps)
    _run_one_lap(store, goals, gid, processor)

    prompt = model.prompts[0]
    assert "Corroborate the SCHD distribution change" in prompt   # the goal
    assert "PREDICATE (success criteria):" in prompt              # the predicate
    assert "NEED LEDGER:" in prompt                               # the ledger
    assert "corroborating publisher" in prompt                    # an OPEN need


def test_the_goal_is_loaded_before_the_model_is_called(
    monkeypatch, goals, goal, laps, tmp_path
):
    """The ordering defect itself: model at :252, goal at :262."""
    order: list[str] = []
    monkeypatch.setattr(lp, "_goal_store", lambda: _OrderedStore(goals, order))
    monkeypatch.setattr(lp, "GOAL_LAP_LEDGER_PATH", laps)
    monkeypatch.setattr(lp, "JOURNAL_ROOT", tmp_path / "journals")

    store = _intake()
    model = _Model(["noted"], order=order)
    processor = lp._make_agent_processor(AGENT, None, _Retrieval(), model)
    gid = goal["goal_id"]

    gg.enqueue_goal_lap(store, goals.get_goal(gid), laps_path=laps)
    _run_one_lap(store, goals, gid, processor)

    assert "goal" in order and "model" in order
    assert order.index("goal") < order.index("model")


# ── (b) + (c) the return channel and the new outcome ────────────────────────


def _dispatcher(processor, agent_id="sentinel", concurrency=8):
    return BoundedDispatcher(
        FLEET[agent_id],
        processor,
        max_concurrency=concurrency,
        should_cancel=lambda: False,
    )


def _job(dedup, agent_id="sentinel"):
    return JobRequest(
        agent_id=agent_id,
        job_type="goal_shadow_review",
        input_hash=f"h-{dedup}",
        enqueued_at=FAR_FUTURE,
        dedup_value=dedup,
    )


def test_the_dispatcher_no_longer_discards_the_processor_result():
    """dispatcher.py:166 called the processor and threw the answer away."""
    continuation = {"goal_id": "goal_x", "next_dedup_key": "goal:goal_x:v0:beef"}
    d = _dispatcher(lambda job: {"outcome": "incomplete", "detail": "1 need open",
                                 "continuation": continuation})
    [result] = d.process_batch([_job("a")])
    assert result.outcome == JobOutcome.INCOMPLETE
    assert result.detail == "1 need open"
    assert result.continuation == continuation


def test_an_incomplete_lap_is_a_success_on_the_circuit_breaker():
    """Counting continuation as failure would trip the breaker open on exactly
    the goals that are making progress. sentinel trips after 3."""
    d = _dispatcher(lambda job: {"outcome": "incomplete"})
    results = d.process_batch([_job(str(i)) for i in range(6)])
    assert [r.outcome for r in results] == [JobOutcome.INCOMPLETE] * 6
    assert JobOutcome.CIRCUIT_OPEN not in [r.outcome for r in results]
    assert d.breaker.is_open is False
    assert d.breaker.consecutive_failures == 0


def test_a_processor_that_returns_nothing_still_completes():
    """Every existing processor returns None or a mapping without an outcome."""
    d = _dispatcher(lambda job: None)
    [result] = d.process_batch([_job("a")])
    assert result.outcome == JobOutcome.COMPLETED
    assert result.continuation is None
    assert batch_summary([result])["outcomes"]["INCOMPLETE"] == 0


def test_batch_summary_counts_the_new_outcome():
    d = _dispatcher(lambda job: {"outcome": "incomplete"})
    summary = batch_summary(d.process_batch([_job("a"), _job("b")]))
    assert summary["outcomes"]["INCOMPLETE"] == 2
    assert summary["outcomes"]["FAILED"] == 0


# ── the intake row closes; the goal does not ───────────────────────────────


def test_incomplete_acks_the_row_completed_while_the_goal_stays_open(
    wired, goals, goal, laps
):
    """The lap really did finish. Holding the lease would wedge the queue for
    900s; failing the row would advance the breaker against a working goal."""
    store = _intake()
    model = _Model(["Lap one: house pipeline 0.7550."])
    processor = lp._make_agent_processor(AGENT, None, _Retrieval(), model)
    gid = goal["goal_id"]
    gg.enqueue_goal_lap(store, goals.get_goal(gid), laps_path=laps)

    jobs, ack = lp.job_source_with_acks(AGENT, 1, store=store)
    assert jobs, "the queued lap should be leased"
    result_payload = processor(jobs[0])
    assert result_payload["outcome"] == "incomplete"

    acked = ack([JobResult(jobs[0].input_hash, JobOutcome.INCOMPLETE, "lap done")])
    assert acked["acked"] == 1
    stats = store.queue_stats(AGENT)
    assert stats["completed"] == 1        # the ROW is settled
    assert stats["leased"] == 0           # no lease is held open
    assert stats["failed"] == 0           # and it was not a failure
    assert goals.get_goal(gid)["status"] == "open"   # the GOAL continues


def test_continuation_is_a_new_key_next_tick_not_a_held_lease(
    wired, goals, goal, laps
):
    store = _intake()
    model = _Model(["Lap one: house pipeline 0.7550."])
    processor = lp._make_agent_processor(AGENT, None, _Retrieval(), model)
    gid = goal["goal_id"]
    _, gen1 = gg.enqueue_goal_lap(store, goals.get_goal(gid), laps_path=laps)

    _, payload = _run_one_lap(store, goals, gid, processor)
    continuation = payload["continuation"]
    assert continuation["answered_dedup_key"] == gen1["dedup_key"]
    assert continuation["next_dedup_key"] != gen1["dedup_key"]
    assert continuation["made_progress"] is True

    outcome, gen2 = gg.enqueue_goal_lap(store, goals.get_goal(gid), laps_path=laps)
    assert outcome == EnqueueOutcome.ENQUEUED
    assert gen2["dedup_key"] == continuation["next_dedup_key"]


def test_a_declared_closure_closes_the_need_and_shrinks_the_ledger(
    wired, goals, goal, laps
):
    store = _intake()
    model = _Model(
        ["Reuters gives 0.7550 independently.\nCLOSED: corroborating publisher"]
    )
    processor = lp._make_agent_processor(AGENT, None, _Retrieval(), model)
    gid = goal["goal_id"]
    gg.enqueue_goal_lap(store, goals.get_goal(gid), laps_path=laps)

    _, payload = _run_one_lap(store, goals, gid, processor)
    assert payload["continuation"]["closed_needs"] == ["corroborating publisher"]
    assert payload["continuation"]["open_needs"] == [
        "independent value from a different pipeline"
    ]
    assert payload["outcome"] == "incomplete"   # one need still open


def test_a_need_cannot_be_closed_by_sounding_finished(wired, goals, goal, laps):
    """Closure is a declaration matched against the OPEN ledger, never a vibe."""
    store = _intake()
    model = _Model(["I am confident this goal is now fully satisfied. Done."])
    processor = lp._make_agent_processor(AGENT, None, _Retrieval(), model)
    gid = goal["goal_id"]
    gg.enqueue_goal_lap(store, goals.get_goal(gid), laps_path=laps)

    _, payload = _run_one_lap(store, goals, gid, processor)
    assert payload["continuation"]["closed_needs"] == []
    assert len(payload["continuation"]["open_needs"]) == 2


# ── (d) the thesis stops being a run id ────────────────────────────────────


def test_runtime_telemetry_is_never_written_into_the_thesis(wired, goals, goal, laps):
    """The source of all 29,774 contentless events."""
    store = _intake()
    model = _Model([""], error=PROVIDER_BLOCKED)
    processor = lp._make_agent_processor(AGENT, None, _Retrieval(), model)
    gid = goal["goal_id"]
    gg.enqueue_goal_lap(store, goals.get_goal(gid), laps_path=laps)

    _run_one_lap(store, goals, gid, processor)

    assert _thesis_events(goals) == []          # nothing contentless was written
    wakes = _wake_events(goals)
    assert len(wakes) == 1                      # the wake still records the lap
    assert "provider_error" in wakes[0]["payload"]["outcome"]
    assert goals.get_goal(gid)["thesis_summary"] == ""


def test_a_real_finding_still_reaches_the_thesis(wired, goals, goal, laps):
    store = _intake()
    finding = "House pipeline reports 0.7550 as of 2026-09-15; no second source yet."
    model = _Model([finding])
    processor = lp._make_agent_processor(AGENT, None, _Retrieval(), model)
    gid = goal["goal_id"]
    gg.enqueue_goal_lap(store, goals.get_goal(gid), laps_path=laps)

    _run_one_lap(store, goals, gid, processor)

    events = _thesis_events(goals)
    assert len(events) == 1
    summary = events[0]["payload"]["thesis_summary"]
    assert summary == finding
    assert "shadow_run=" not in summary
    assert "retrieval_n=" not in summary
    assert "PROVIDER_BLOCKED" not in summary


# ── the predicate axis of the generation key ────────────────────────────────


def test_a_predicate_bump_mints_a_new_generation(goals, goal, laps):
    """Measured live 2026-09-17, against the deployed tree.

    ``predicate_version()`` read ``goal["predicate_version"]`` — a TOP-LEVEL key
    the projection never writes. ``CIOGoalStore._apply_event`` nests the whole
    predicate under ``goal["predicate"]``, so goal_695a5dbe2401 keyed as ``v0``
    while its own stored identity was ``goal_695a5dbe2401:v1:cd0065040125a4cc``.

    The generation key is ``goal:{goal_id}:{predicate_version}:{ledger_digest}``.
    So setting a predicate left the key byte-identical, the next generation was
    refused as DUPLICATE, and "a new predicate restarts the goal" was inert —
    the machinery reported healthy while the guarantee did nothing.
    """
    gid = goal["goal_id"]
    before = gg.generation_for_goal(goals.get_goal(gid), laps_path=laps)
    assert gg.predicate_version(goals.get_goal(gid)) == "v0", "no predicate yet"

    goals.set_predicate(gid, evaluator="all_terms_true@v1", terms=["a", "b"], actor_id="t")
    bumped = goals.get_goal(gid)
    assert gg.predicate_version(bumped) == "v1", "the nested predicate_version must win"

    after = gg.generation_for_goal(bumped, laps_path=laps)
    assert after["dedup_key"] != before["dedup_key"], (
        "a predicate bump left the dedup key unchanged — the new generation "
        "would be refused DUPLICATE and the goal could never restart"
    )
    assert ":v1:" in after["dedup_key"]

    goals.set_predicate(gid, evaluator="all_terms_true@v1", terms=["a", "c"], actor_id="t")
    again = gg.generation_for_goal(goals.get_goal(gid), laps_path=laps)
    assert gg.predicate_version(goals.get_goal(gid)) == "v2"
    assert again["dedup_key"] != after["dedup_key"], "the second bump must also mint"


def test_a_flattened_top_level_version_is_still_honoured():
    """Back-compat: a caller passing a summary dict must not regress to v0."""
    assert gg.predicate_version({"predicate_version": "v3"}) == "v3"
    assert gg.predicate_version({"predicate_version": 3}) == "v3"
    assert gg.predicate_version({"predicate": {"predicate_version": 7}}) == "v7"
    assert gg.predicate_version({}) == "v0"
