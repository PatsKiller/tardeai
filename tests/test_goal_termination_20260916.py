"""Controls for P7 — a goal stops for one of five named reasons, with proof.

Termination outcomes: sufficient | no_new_evidence | budget_exhausted |
bounded_ignorance | ask_operator. Only `sufficient` may claim achievement, and
only when the predicate was satisfied AND the validator that said so is
calibrated -- a validator that has never disagreed is not evidence.

Every `achieved` goal additionally needs a NON-VACUOUS falsifier (reusing the
repo's own `VACUOUS_FALSIFIERS` / `refuse_vacuous_falsifier`, which 343 live
commitments currently violate) and a checkpoint bound into the one outcome loop
that already works and refuses to fabricate, `resolve_due_checkpoints`.

Also here: `operator_ask` was capped globally at one question per day, so the
day's SECOND question was refused human escalation because an unrelated first
had taken the slot. The counter is now per goal.

Each control must go RED if the guarantee is removed. Offline: temp roots only.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import cio_goals as G  # noqa: E402
from scripts.lib import gap_resolver as gr  # noqa: E402
from scripts.lib.cortex_shadow_pipeline import VACUOUS_FALSIFIERS  # noqa: E402
from scripts.lib.outcome_resolution import due_checkpoints  # noqa: E402

REAL_FALSIFIER = "the reported change is absent from the next independent filing for this subject by 2026-10-16"
EVIDENCE = ["receipt:gap_resolution_receipts.jsonl#abc", "artifact:sha256:" + "a" * 64]


@pytest.fixture
def store(tmp_path):
    return G.CIOGoalStore(
        event_path=tmp_path / "goals.jsonl",
        projection_path=tmp_path / "proj.json",
        cursor_path=tmp_path / "cursors.json",
    )


@pytest.fixture
def goal(store):
    g = store.create_goal(owner_agent="alex", title="Material-change corroboration")
    store.set_predicate(g["goal_id"], evaluator="all_terms_true@v1", terms=["corroborated"])
    return g["goal_id"]


def _checkpoints(root: Path) -> list[dict]:
    path = root / "data/cio/outcome_checkpoints.jsonl"
    if not path.is_file():
        return []
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


# ── the five outcomes, and nothing else ──────────────────────────────────────


def test_the_five_termination_outcomes_are_exactly_these():
    assert set(G.TERMINATION_OUTCOMES) == {
        "sufficient", "no_new_evidence", "budget_exhausted", "bounded_ignorance", "ask_operator",
    }
    assert set(G.TERMINATION_STATUS) == set(G.TERMINATION_OUTCOMES)


def test_an_unnamed_outcome_never_closes_a_goal(store, goal, tmp_path):
    with pytest.raises(ValueError, match="unknown termination outcome"):
        store.terminate_goal(goal, outcome="probably_fine", evidence=EVIDENCE, checkpoint_root=tmp_path)
    assert store.get_goal(goal)["status"] == "open"


def test_only_sufficient_may_claim_achievement(store, tmp_path):
    """The other four stop the work WITHOUT claiming the question was answered."""
    assert G.TERMINATION_STATUS["sufficient"] == "achieved"
    for outcome in ("no_new_evidence", "budget_exhausted", "bounded_ignorance", "ask_operator"):
        assert G.TERMINATION_STATUS[outcome] != "achieved"
        g = store.create_goal(owner_agent="alex", title=f"goal for {outcome}")
        store.terminate_goal(g["goal_id"], outcome=outcome, evidence=EVIDENCE, checkpoint_root=tmp_path)
        assert store.get_goal(g["goal_id"])["status"] == "blocked"


def test_every_termination_needs_evidence(store, tmp_path):
    for outcome in G.TERMINATION_OUTCOMES:
        g = store.create_goal(owner_agent="alex", title=f"goal for {outcome}")
        with pytest.raises(ValueError, match="evidence is empty"):
            store.terminate_goal(
                g["goal_id"], outcome=outcome, evidence=[],
                falsifier=REAL_FALSIFIER, predicate_satisfied=True,
                validator_calibrated=True, checkpoint_root=tmp_path,
            )
        assert store.get_goal(g["goal_id"])["status"] == "open"


def test_the_termination_reason_is_recorded_on_the_event(store, goal, tmp_path):
    store.terminate_goal(goal, outcome="bounded_ignorance", evidence=EVIDENCE, checkpoint_root=tmp_path)
    events = [json.loads(l) for l in store.event_path.read_text().splitlines() if l.strip()]
    payload = [e for e in events if e["event_type"] == "GOAL_STATUS_CHANGED"][-1]["payload"]
    assert payload["termination"] == "bounded_ignorance"
    assert payload["evidence"] == EVIDENCE


# ── sufficient requires a satisfied predicate AND a calibrated validator ─────


def test_sufficient_requires_the_predicate_to_have_been_satisfied(store, goal, tmp_path):
    with pytest.raises(ValueError, match="predicate_satisfied"):
        store.terminate_goal(
            goal, outcome="sufficient", evidence=EVIDENCE, falsifier=REAL_FALSIFIER,
            predicate_satisfied=False, validator_calibrated=True, checkpoint_root=tmp_path,
        )
    assert store.get_goal(goal)["status"] == "open"


def test_sufficient_requires_a_calibrated_validator(store, goal, tmp_path):
    """A validator that has never disagreed cannot certify a victory."""
    with pytest.raises(ValueError, match="validator_calibrated"):
        store.terminate_goal(
            goal, outcome="sufficient", evidence=EVIDENCE, falsifier=REAL_FALSIFIER,
            predicate_satisfied=True, validator_calibrated=False, checkpoint_root=tmp_path,
        )
    assert store.get_goal(goal)["status"] == "open"


def test_sufficient_refuses_when_neither_is_asserted_at_all(store, goal, tmp_path):
    with pytest.raises(ValueError):
        store.terminate_goal(
            goal, outcome="sufficient", evidence=EVIDENCE,
            falsifier=REAL_FALSIFIER, checkpoint_root=tmp_path,
        )


def test_sufficient_with_both_asserted_achieves_the_goal(store, goal, tmp_path):
    store.terminate_goal(
        goal, outcome="sufficient", evidence=EVIDENCE, falsifier=REAL_FALSIFIER,
        predicate_satisfied=True, validator_calibrated=True, checkpoint_root=tmp_path,
    )
    assert store.get_goal(goal)["status"] == "achieved"


# ── an achieved goal is refutable, and will actually be re-checked ───────────


def test_achieved_refuses_the_repos_own_vacuous_falsifier(store, goal, tmp_path):
    vacuous = sorted(VACUOUS_FALSIFIERS)[0]
    with pytest.raises(ValueError, match="vacuous_falsifier"):
        store.terminate_goal(
            goal, outcome="sufficient", evidence=EVIDENCE, falsifier=vacuous,
            predicate_satisfied=True, validator_calibrated=True, checkpoint_root=tmp_path,
        )
    assert store.get_goal(goal)["status"] == "open"


def test_achieved_refuses_a_missing_falsifier(store, goal, tmp_path):
    with pytest.raises(ValueError, match="vacuous_falsifier"):
        store.terminate_goal(
            goal, outcome="sufficient", evidence=EVIDENCE, falsifier=None,
            predicate_satisfied=True, validator_calibrated=True, checkpoint_root=tmp_path,
        )


def test_a_non_achieving_termination_needs_no_falsifier(store, tmp_path):
    """Nothing was claimed, so there is nothing to refute."""
    g = store.create_goal(owner_agent="alex", title="ran out of budget")
    store.terminate_goal(g["goal_id"], outcome="budget_exhausted", evidence=EVIDENCE, checkpoint_root=tmp_path)
    assert store.get_goal(g["goal_id"])["status"] == "blocked"
    assert _checkpoints(tmp_path) == [], "only a CLAIM needs a re-check"


def test_achieved_binds_a_checkpoint_that_resolve_due_checkpoints_will_see(store, goal, tmp_path):
    store.terminate_goal(
        goal, outcome="sufficient", evidence=EVIDENCE, falsifier=REAL_FALSIFIER,
        predicate_satisfied=True, validator_calibrated=True, checkpoint_root=tmp_path,
    )
    rows = _checkpoints(tmp_path)
    assert len(rows) == 1, "an achieved goal with no bound re-check is a claim nobody will test"
    ck = rows[0]
    assert ck["schema"] == "OutcomeCheckpoint@v1"
    assert ck["status"] == "SCHEDULED"
    assert ck["goal_id"] == goal
    assert ck["falsifier"] == REAL_FALSIFIER
    assert ck["evidence"] == EVIDENCE
    assert ck["trading"] is False and ck["observational_only"] is True

    now = datetime.now(timezone.utc)
    due_at = datetime.fromisoformat(str(ck["due_at"]).replace("Z", "+00:00"))
    assert due_at > now, "the re-check must be in the FUTURE"

    # The real due-selection function from the real loop, not a copy of it.
    assert due_checkpoints(rows, now=now) == [], "not due yet"
    assert [r["checkpoint_id"] for r in due_checkpoints(rows, now=due_at + timedelta(minutes=1))] == [
        ck["checkpoint_id"]
    ], "the loop must pick it up once it comes due"


def test_the_checkpoint_id_derives_from_the_goal_id_and_mints_no_new_namespace(store, goal, tmp_path):
    from scripts.lib.cio_institutional_learning import _sha

    store.terminate_goal(
        goal, outcome="sufficient", evidence=EVIDENCE, falsifier=REAL_FALSIFIER,
        predicate_satisfied=True, validator_calibrated=True, checkpoint_root=tmp_path,
    )
    ck = _checkpoints(tmp_path)[0]
    assert ck["checkpoint_id"] == _sha({
        "decision_id": goal, "horizon": G.DEFAULT_CHECKPOINT_HORIZON,
    })[:20]
    assert ck["decision_id"] == goal


def test_the_close_event_names_the_checkpoint_it_bound(store, goal, tmp_path):
    store.terminate_goal(
        goal, outcome="sufficient", evidence=EVIDENCE, falsifier=REAL_FALSIFIER,
        predicate_satisfied=True, validator_calibrated=True, checkpoint_root=tmp_path,
    )
    events = [json.loads(l) for l in store.event_path.read_text().splitlines() if l.strip()]
    payload = [e for e in events if e["event_type"] == "GOAL_STATUS_CHANGED"][-1]["payload"]
    assert payload["checkpoint_id"] == _checkpoints(tmp_path)[0]["checkpoint_id"]
    assert payload["falsifier"] == REAL_FALSIFIER


# ── operator_ask is budgeted per goal, not once for the whole day ────────────

NOW = datetime(2026, 9, 16, 12, 0, 0, tzinfo=timezone.utc)
CHAIN = [{"vector": "operator_ask", "cost_class": "free", "max_per_day": 1, "expected_seconds": 7200}]


def _fake_ask(gap, entry, ctx):
    return gr.VectorResult(
        "queued", provider="operator", eta_seconds=int(entry.get("expected_seconds") or 7200),
        detail="fake: nothing sent", operator_question="which source should I use?",
    )


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    monkeypatch.setattr(gr, "_register_gap_on_spine", lambda gap: None)
    return gr.Context(
        now=lambda: NOW, receipts_path=tmp_path / "receipts.jsonl", live=False, env={},
    )


def _ask(ctx, *, goal_id: str) -> str:
    gap = gr.DataGap(
        domain="analyst_view", subject="WMT",
        question=f"analyst view for WMT ({goal_id or 'no goal'})", goal_id=goal_id,
    )
    res = gr.resolve(gap, chain=CHAIN, vectors={"operator_ask": _fake_ask}, ctx=ctx)
    return res.attempts[-1]["outcome"]


def test_a_second_question_about_the_SAME_goal_is_still_refused(ctx):
    """The cap's real job -- do not pester the operator about one thing."""
    assert _ask(ctx, goal_id="goal_695a5dbe2401") == "queued"
    assert _ask(ctx, goal_id="goal_695a5dbe2401") == "budget_denied"


def test_a_question_about_a_DIFFERENT_goal_gets_its_own_slot(ctx):
    """The measured defect: an unrelated first question consumed the only slot."""
    assert _ask(ctx, goal_id="goal_695a5dbe2401") == "queued"
    assert _ask(ctx, goal_id="goal_f2664540d8c1") == "queued"
    assert _ask(ctx, goal_id="goal_f1d5c0a993d0") == "queued"


def test_gaps_with_no_goal_share_one_slot_among_themselves(ctx):
    """The historic single slot survives, for the work that names no goal."""
    assert _ask(ctx, goal_id="") == "queued"
    assert _ask(ctx, goal_id="") == "budget_denied"


def test_a_goal_scoped_ask_does_not_consume_the_ungoaled_slot(ctx):
    """Otherwise the defect just moves: goal work starves the ungoaled bucket."""
    assert _ask(ctx, goal_id="goal_695a5dbe2401") == "queued"
    assert _ask(ctx, goal_id="") == "queued"


def test_an_ungoaled_ask_does_not_consume_a_goals_slot_either(ctx):
    assert _ask(ctx, goal_id="") == "queued"
    assert _ask(ctx, goal_id="goal_695a5dbe2401") == "queued"


def test_operator_ask_is_the_only_per_goal_budgeted_vector():
    assert gr.PER_GOAL_BUDGET_VECTORS == frozenset({"operator_ask"})


def test_attempts_today_scopes_by_goal():
    rows = [
        {"vector": "operator_ask", "started": "2026-09-16T09:00:00+00:00", "outcome": "queued", "goal_id": "g1"},
        {"vector": "operator_ask", "started": "2026-09-16T10:00:00+00:00", "outcome": "queued", "goal_id": "g2"},
        {"vector": "operator_ask", "started": "2026-09-15T10:00:00+00:00", "outcome": "queued", "goal_id": "g1"},
        {"vector": "operator_ask", "started": "2026-09-16T11:00:00+00:00", "outcome": "budget_denied", "goal_id": "g1"},
    ]
    assert gr.attempts_today("operator_ask", now=NOW, rows=rows) == 2          # global, refusals excluded
    assert gr.attempts_today("operator_ask", now=NOW, rows=rows, goal_id="g1") == 1
    assert gr.attempts_today("operator_ask", now=NOW, rows=rows, goal_id="g2") == 1
    assert gr.attempts_today("operator_ask", now=NOW, rows=rows, goal_id="g3") == 0


def test_the_receipt_carries_the_goal_id_so_the_count_is_possible_at_all(ctx, tmp_path):
    _ask(ctx, goal_id="goal_695a5dbe2401")
    rows = [json.loads(l) for l in (tmp_path / "receipts.jsonl").read_text().splitlines() if l.strip()]
    assert rows and rows[-1]["goal_id"] == "goal_695a5dbe2401"


def test_carrying_a_goal_id_does_not_change_the_gap_id():
    """No id may fork because a gap learned which goal it serves."""
    without = gr.DataGap(domain="analyst_view", subject="WMT", question="q")
    with_goal = gr.DataGap(domain="analyst_view", subject="WMT", question="q", goal_id="goal_695a5dbe2401")
    assert without.gap_id == with_goal.gap_id
