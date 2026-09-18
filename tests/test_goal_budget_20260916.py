"""Controls for P3 — a CUMULATIVE per-goal budget that cannot fail open.

Before P3 every budget in the agent runtime was PER INVOCATION and reset every
lap: ``BudgetPolicy(max_model_calls=3, deadline_seconds=360)``, checked inside
``MvlRuntime.reason`` against counters that start at zero on each run. A goal
that lapped two hundred times passed two hundred budget checks and accumulated
nothing, so no number on disk could ever answer "what has this goal cost", and
nothing could refuse a goal for having cost too much.

Three guarantees are pinned here, each of which must go RED if removed:

  1. **Fail closed.** Corrupt ``goal_budget.json`` to ``{`` and the next
     producer run enqueues ZERO laps and writes a BUDGET_UNAVAILABLE receipt;
     restore it and the same laps resume. An unreadable ledger is never rebuilt
     as a fresh zero counter — the documented reason ``search_budget`` was
     rewritten.
  2. **Cumulative.** Five laps of one goal, and ``cost_usd`` is monotonically
     non-decreasing and survives the lap boundary.
  3. **An agent cannot raise its own budget.** Not through a tool
     (``SELF_GOVERNANCE_TOKENS``), not through its environment (an env override
     may only LOWER), not by omitting the predicate version, and not from inside
     the runtime (which does not import the module at all).

Offline: temp roots, fixtures, an in-memory intake store. No database, no
network, no provider, no model call.
"""
from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from agent_runtime import trigger_producer as tp  # noqa: E402
from agent_runtime.agents.base import (  # noqa: E402
    SELF_GOVERNANCE_TOKENS,
    assert_no_self_governance,
)
from agent_runtime.trigger_intake import (  # noqa: E402
    InMemoryTriggerIntakeStore,
    TriggerCandidate,
)
from agent_runtime.trigger_sources import AdapterResult, SourceProbe, SourceState  # noqa: E402
from scripts.lib import goal_budget as gb  # noqa: E402

GOAL = "goal_0123456789ab"
PV = "predicate@v1"
SOURCE = "watch:artifacts"
CURSOR_KEY = "generated_at"
CURSOR_NEW = "2026-09-16T12:00:00+00:00"


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """An isolated state root: ledger, receipts and operator policy all under it."""
    (tmp_path / "data" / "runtime").mkdir(parents=True, exist_ok=True)
    return tmp_path


def _policy(root: Path, **caps) -> None:
    """Write the operator-owned ceilings (the only way a cap ever goes UP)."""
    p = gb.policy_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(caps), encoding="utf-8")


def _candidate(dedup: str, *, goal_id: str | None = GOAL,
               predicate_version: str | None = PV) -> TriggerCandidate:
    payload: dict = {"n": dedup}
    if goal_id is not None:
        payload["goal_id"] = goal_id
    if predicate_version is not None:
        payload["predicate_version"] = predicate_version
    return TriggerCandidate(
        agent_id="sentinel", trigger_kind="WATCH_ARTIFACT_CHANGED", dedup_key=dedup,
        job_type="watch_ticket_review", payload=payload,
        source_ref=f"{SOURCE}:{dedup}", source_hash="a" * 64,
        source_timestamp="2026-09-16T11:00:00+00:00",
    )


def _run(monkeypatch, store, candidates, root: Path):
    probe = SourceProbe(source_id=SOURCE, state=SourceState.READY, detail="")
    result = AdapterResult(SOURCE, probe, tuple(candidates),
                           ((SOURCE, CURSOR_KEY, CURSOR_NEW),))
    monkeypatch.setattr(tp, "run_adapter", lambda sid, cv: result)
    return tp.produce_once(store, sources=[SOURCE], budget_root=root)


# ── 1. fail closed ─────────────────────────────────────────────────────────


def test_ledger_path_is_the_declared_runtime_path(root: Path):
    assert gb.budget_path(root) == root / "data" / "runtime" / "goal_budget.json"
    assert gb.budget_path().as_posix().endswith("data/runtime/goal_budget.json")


def test_a_corrupt_ledger_denies_status_check_and_consume(root: Path):
    gb.budget_path(root).write_text("{", encoding="utf-8")

    with pytest.raises(gb.BudgetUnavailable):
        gb.status(GOAL, PV, root=root)

    v = gb.check(GOAL, PV, root=root)
    assert v["allowed"] is False
    assert "BUDGET_UNAVAILABLE" in v["reason"]
    assert v.get("fail_open") is False

    c = gb.try_consume_lap(GOAL, PV, root=root)
    assert c["allowed"] is False
    assert "BUDGET_UNAVAILABLE" in c["reason"]


def test_a_missing_ledger_is_not_a_corrupt_one(root: Path):
    """The distinction the whole module rests on: absent means zero laps so far,
    illegible means unknown, and only one of those may proceed."""
    assert not gb.budget_path(root).exists()
    assert gb.check(GOAL, PV, root=root)["allowed"] is True


def test_an_unreadable_ledger_is_never_rebuilt_as_a_zero_counter(root: Path):
    """The exact fail-open write that forced the search_budget rewrite."""
    gb.try_consume_lap(GOAL, PV, root=root)
    gb.budget_path(root).write_text("{", encoding="utf-8")

    assert gb.try_consume_lap(GOAL, PV, root=root)["allowed"] is False
    assert gb.record_spend(GOAL, PV, cost_usd=1.0, root=root) is False

    assert gb.budget_path(root).read_text(encoding="utf-8") == "{", \
        "a writer rebuilt the corrupt ledger — an unbudgeted lap is now reachable"


def test_a_corrupt_ledger_enqueues_zero_laps_and_writes_a_receipt(monkeypatch, root: Path):
    """P3's headline control: the budget fails closed at the producer."""
    gb.budget_path(root).write_text("{", encoding="utf-8")
    store = InMemoryTriggerIntakeStore()

    payload = _run(monkeypatch, store, [_candidate("lap-1"), _candidate("lap-2")], root)

    assert payload["enqueued"] == 0, "an illegible budget still authorised laps"
    assert payload["budget_unavailable"] == 2
    assert int(store.queue_stats("sentinel").get("queued") or 0) == 0

    receipts = gb.denial_receipts(root=root)
    assert receipts, "no BUDGET_UNAVAILABLE receipt — the refusal left no evidence"
    assert all(r["schema"] == gb.RECEIPT_SCHEMA for r in receipts)
    assert any("BUDGET_UNAVAILABLE" in r["reason"] for r in receipts)
    assert all(r["goal_id"] == GOAL for r in receipts)


def test_restoring_the_ledger_lets_the_same_laps_resume(monkeypatch, root: Path):
    """Fail-closed is only correct if it is also recoverable: the held cursor is
    what makes the refused rows come back rather than being skipped forever."""
    gb.budget_path(root).write_text("{", encoding="utf-8")
    store = InMemoryTriggerIntakeStore()
    before = store.get_cursor(SOURCE, CURSOR_KEY)

    blocked = _run(monkeypatch, store, [_candidate("lap-1")], root)
    assert blocked["enqueued"] == 0
    assert SOURCE in blocked["cursors_held"]
    assert store.get_cursor(SOURCE, CURSOR_KEY) == before, \
        "cursor advanced past a lap refused for an unknown budget — never re-offered"

    gb.budget_path(root).unlink()           # restore: a legible (empty) ledger

    resumed = _run(monkeypatch, store, [_candidate("lap-1")], root)
    assert resumed["enqueued"] == 1, "laps did not resume once the budget was readable"
    assert resumed["budget_unavailable"] == 0
    assert store.get_cursor(SOURCE, CURSOR_KEY) == CURSOR_NEW


def test_an_exhausted_budget_denies_without_wedging_the_source(monkeypatch, root: Path):
    """Exhaustion is terminal, not transient — so it must NOT hold the cursor,
    or one spent goal would block every other candidate behind it forever."""
    _policy(root, max_laps=1)
    store = InMemoryTriggerIntakeStore()

    first = _run(monkeypatch, store, [_candidate("lap-1")], root)
    assert first["enqueued"] == 1

    second = _run(monkeypatch, store, [_candidate("lap-2")], root)
    assert second["enqueued"] == 0
    assert second["budget_denied"] == 1
    assert second["cursors_held"] == []
    assert any(r["reason"] == "LAP_BUDGET_EXHAUSTED" for r in gb.denial_receipts(root=root))


def test_a_candidate_with_no_goal_is_enqueued_unbudgeted(monkeypatch, root: Path):
    """P3 bounds GOALS. Refusing every non-goal trigger because a goal ledger is
    illegible would be an outage caused by one file."""
    gb.budget_path(root).write_text("{", encoding="utf-8")
    store = InMemoryTriggerIntakeStore()

    payload = _run(monkeypatch, store, [_candidate("plain", goal_id=None)], root)

    assert payload["enqueued"] == 1
    assert payload["budget_unavailable"] == 0


# ── 2. cumulative across laps ──────────────────────────────────────────────


def test_five_laps_accumulate_and_cost_never_decreases(root: Path):
    """The P3 verification row: 5 laps of one goal, cost_usd monotonic."""
    _policy(root, max_cost_usd=5.0, max_paid_calls=10)
    seen: list[float] = []

    for lap in range(5):
        v = gb.try_consume_lap(GOAL, PV, root=root)
        assert v["allowed"] is True, f"lap {lap} refused: {v['reason']}"
        gb.record_spend(GOAL, PV, cost_usd=0.01, paid_calls=1, model_calls=2, root=root)
        seen.append(gb.status(GOAL, PV, root=root)["cost_usd"])

    assert seen == sorted(seen), f"cost_usd decreased across laps: {seen}"
    assert all(b >= a for a, b in zip(seen, seen[1:]))

    st = gb.status(GOAL, PV, root=root)
    assert st["laps"] == 5
    assert st["cost_usd"] == pytest.approx(0.05)
    assert st["paid_calls"] == 5
    assert st["model_calls"] == 10


def test_the_counters_survive_the_lap_that_wrote_them(root: Path):
    """The defect P3 exists to fix: a per-invocation budget resets, so nothing
    accumulates. These counters are read back from disk, not from memory."""
    _policy(root, max_cost_usd=5.0, max_paid_calls=10)
    gb.try_consume_lap(GOAL, PV, root=root)
    gb.record_spend(GOAL, PV, cost_usd=0.03, paid_calls=1, model_calls=3, root=root)

    doc = json.loads(gb.budget_path(root).read_text(encoding="utf-8"))
    bucket = doc["goals"][GOAL][PV]
    assert bucket["cost_usd"] == pytest.approx(0.03)
    assert bucket["model_calls"] == 3, \
        "model_calls reset with the lap — this is the per-invocation budget again"


def test_spend_is_keyed_by_goal_and_predicate_version(root: Path):
    """Two goals, and the same goal under two predicate versions, are three
    separate allowances — one must never spend another's."""
    _policy(root, max_cost_usd=5.0, max_paid_calls=10)
    gb.record_spend(GOAL, PV, cost_usd=0.05, root=root)
    gb.record_spend(GOAL, "predicate@v2", cost_usd=0.01, root=root)
    gb.record_spend("goal_other", PV, cost_usd=0.02, root=root)

    assert gb.status(GOAL, PV, root=root)["cost_usd"] == pytest.approx(0.05)
    assert gb.status(GOAL, "predicate@v2", root=root)["cost_usd"] == pytest.approx(0.01)
    assert gb.status("goal_other", PV, root=root)["cost_usd"] == pytest.approx(0.02)


def test_the_ledger_is_monotonic_by_construction(root: Path):
    """No refund(), and negative spend is refused rather than clamped. The mirror
    of search_budget.refund is absent on purpose: a rate can be handed back, a
    cumulative history cannot go down and stay true."""
    assert not hasattr(gb, "refund")
    with pytest.raises(ValueError):
        gb.record_spend(GOAL, PV, cost_usd=-0.01, root=root)
    with pytest.raises(ValueError):
        gb.record_spend(GOAL, PV, paid_calls=-1, root=root)


def test_a_refused_lap_does_not_inflate_the_spend_counters(root: Path):
    _policy(root, max_laps=1)
    gb.try_consume_lap(GOAL, PV, root=root)
    gb.record_spend(GOAL, PV, cost_usd=0.0, model_calls=1, root=root)

    denied = gb.try_consume_lap(GOAL, PV, root=root)
    assert denied["allowed"] is False

    st = gb.status(GOAL, PV, root=root)
    assert st["laps"] == 1
    assert st["model_calls"] == 1


def test_the_first_cent_stops_a_goal_that_no_operator_has_funded(root: Path):
    """Default ceilings are zero for money. A FREE lap against a 0.00 ceiling is
    allowed (the comparison is > not >=); the first real spend ends the goal.
    This is what makes the pilot's 'paid_calls: 0' structural."""
    assert gb.DEFAULT_LIMITS["max_cost_usd"] == 0.0
    assert gb.DEFAULT_LIMITS["max_paid_calls"] == 0

    assert gb.try_consume_lap(GOAL, PV, root=root)["allowed"] is True
    gb.record_spend(GOAL, PV, cost_usd=0.01, paid_calls=1, root=root)

    v = gb.try_consume_lap(GOAL, PV, root=root)
    assert v["allowed"] is False
    assert v["reason"] in {"PAID_CALL_BUDGET_EXHAUSTED", "COST_BUDGET_EXHAUSTED"}


# ── 3. an agent cannot raise its own budget ────────────────────────────────


def _spec_allowing(tool: str):
    from agent_runtime.agents.definitions import FLEET

    base = FLEET["sentinel"]
    definition = dataclasses.replace(
        base.definition, allowed_tools=tuple(base.definition.allowed_tools) + (tool,))
    return dataclasses.replace(base, definition=definition)


@pytest.mark.parametrize("tool", [
    "goal_budget.set", "goal_budget.write", "goal_budget.try_consume_lap",
    "goal_budget.record_spend", "lib.goal_budget", "budget.set", "enqueue_self",
])
def test_no_agent_may_hold_a_tool_that_touches_a_budget(tool: str):
    """SELF_GOVERNANCE_TOKENS is the existing deny surface; the goal ledger joins
    it whole rather than by verb, because even READING a remaining allowance lets
    an agent shape its laps around the ceiling."""
    assert "goal_budget" in SELF_GOVERNANCE_TOKENS
    with pytest.raises(ValueError, match="self-governance"):
        assert_no_self_governance(_spec_allowing(tool))


def test_the_whole_shipped_fleet_still_passes_the_deny_surface():
    """Adding a token must not retroactively invalidate a live agent."""
    from agent_runtime.agents.base import assert_fleet_separation
    from agent_runtime.agents.definitions import FLEET

    assert_fleet_separation(FLEET)


def test_an_env_override_may_lower_a_cap_but_never_raise_it(root: Path):
    """A cap read from the caller's environment is not a control: measured
    2026-09-16, 67 LLM processes, 28 capped, $17.80/day against a $2.00 ceiling,
    with 9 of 460 crontab lines setting it. Lowering is safe; raising would let
    an agent's own environment extend its budget."""
    _policy(root, max_laps=10, max_cost_usd=1.0)

    raised = gb.limits(env={"GOAL_BUDGET_MAX_LAPS": "9999",
                            "GOAL_BUDGET_MAX_COST_USD": "999.0"}, root=root)
    assert raised["max_laps"] == 10
    assert raised["max_cost_usd"] == pytest.approx(1.0)

    lowered = gb.limits(env={"GOAL_BUDGET_MAX_LAPS": "2"}, root=root)
    assert lowered["max_laps"] == 2


def test_an_env_override_cannot_raise_the_cap_that_actually_refuses_a_lap(root: Path):
    """The override must be inert on the enforcement path, not just in limits()."""
    _policy(root, max_laps=1)
    env = {"GOAL_BUDGET_MAX_LAPS": "9999"}

    assert gb.try_consume_lap(GOAL, PV, root=root, env=env)["allowed"] is True
    second = gb.try_consume_lap(GOAL, PV, root=root, env=env)
    assert second["allowed"] is False
    assert second["reason"] == "LAP_BUDGET_EXHAUSTED"


def test_omitting_the_predicate_version_does_not_buy_a_fresh_allowance(monkeypatch, root: Path):
    """Defaulting a missing version would mean a fresh budget bucket is obtainable
    by leaving a key out of a payload."""
    store = InMemoryTriggerIntakeStore()
    payload = _run(monkeypatch, store, [_candidate("lap-1", predicate_version=None)], root)

    assert payload["enqueued"] == 0
    assert payload["budget_denied"] == 1
    assert any(r["reason"] == "PREDICATE_VERSION_MISSING" for r in gb.denial_receipts(root=root))


def test_enforcement_is_not_reachable_from_inside_the_runtime():
    """The structural guarantee: MvlRuntime runs AS the agent, so the budget must
    not be reachable there. The charge happens at enqueue, in the producer,
    before the runtime ever sees the job."""
    runtime_src = (ROOT / "scripts" / "agent_runtime" / "runtime.py").read_text(encoding="utf-8")
    assert "goal_budget" not in runtime_src, \
        "MvlRuntime can reach the goal budget — an agent could extend its own"

    producer_src = (ROOT / "scripts" / "agent_runtime" / "trigger_producer.py").read_text(
        encoding="utf-8")
    assert "goal_budget" in producer_src
    assert "gate_candidate" in producer_src


def test_the_budget_is_charged_before_the_row_exists(monkeypatch, root: Path):
    """A lap denied at enqueue must leave nothing for a runner to lease — the
    point of enforcing here rather than after the job is picked up."""
    _policy(root, max_laps=0)
    store = InMemoryTriggerIntakeStore()

    payload = _run(monkeypatch, store, [_candidate("lap-1")], root)

    assert payload["enqueued"] == 0
    assert store.lease("sentinel", limit=10, lease_owner="t") == []


# ── 5. a lap that was never admitted costs nothing ─────────────────────────


def test_a_duplicate_enqueue_does_not_consume_a_lap(monkeypatch, root: Path):
    """Measured live 2026-09-18, and it exhausted three real goals.

    ``gate_candidate`` charges BEFORE ``store.enqueue`` — deliberately, so a lap
    can never be enqueued unbudgeted. But intake refuses a repeat as DUPLICATE,
    and the charge was not returned. Three goals were each billed 12 laps in 22
    minutes while exactly ONE lap per goal reached the ledger: 33 of 36 charges
    bought nothing, and all three then hit LAP_BUDGET_EXHAUSTED, which is
    terminal until an operator or a predicate bump reopens the goal.

    The whole allowance was spent on no-ops. A refused enqueue did no work and
    must not be billed — the principle this module already states for denials.
    """
    _policy(root, max_laps=5)
    store = InMemoryTriggerIntakeStore()

    first = _run(monkeypatch, store, [_candidate("dup-1")], root)
    assert first["enqueued"] == 1
    assert gb.status(GOAL, PV, root=root)["laps"] == 1

    second = _run(monkeypatch, store, [_candidate("dup-1")], root)
    assert second["enqueued"] == 0
    assert second["duplicates"] == 1
    assert gb.status(GOAL, PV, root=root)["laps"] == 1, (
        "a duplicate enqueue burned a lap of the goal's cumulative allowance"
    )


def test_an_admitted_lap_is_still_charged_exactly_once(monkeypatch, root: Path):
    """Negative control for the refund.

    Without this, the control above could be satisfied by never charging at all,
    which would leave laps unbudgeted — the defect the budget exists to prevent.
    """
    _policy(root, max_laps=5)
    store = InMemoryTriggerIntakeStore()

    _run(monkeypatch, store, [_candidate("uniq-1")], root)
    _run(monkeypatch, store, [_candidate("uniq-2")], root)

    assert gb.status(GOAL, PV, root=root)["laps"] == 2, (
        "two admitted laps must cost exactly two"
    )


def test_a_refund_floors_at_zero(root: Path):
    """A refund must never mint allowance that was never charged."""
    _policy(root, max_laps=5)
    out = gb.refund_lap(GOAL, PV, root=root)
    assert out["refunded"] is True
    assert out["laps_after"] == 0
    assert gb.status(GOAL, PV, root=root)["laps"] == 0


def test_refunding_a_candidate_that_names_no_goal_is_a_no_op(root: Path):
    """It was never charged, so there is nothing to give back."""
    out = gb.refund_candidate({"n": "not-a-goal"}, root=root)
    assert out["refunded"] is False
    assert out["reason"] == gb.NOT_GOAL_SCOPED
    assert not gb.budget_path(root).exists(), "a no-op refund wrote a ledger"
