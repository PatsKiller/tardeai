"""Controls for P8 — the material-change corroboration pilot, SHADOW only.

The pilot's claim is narrow: a goal closes because a predicate over evidence is
satisfied, and when the evidence cannot be obtained it says so rather than
closing. Each control below must go RED if its guarantee is removed.

Offline by construction: no database, no network, no provider. The corroboration
function is injected, so these tests exercise the real decision logic without
reaching material_change_detector's Postgres queries.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.cio_goals import (  # noqa: E402
    TERMINATION_OUTCOMES,
    VERDICT_SATISFIED,
    VERDICT_UNEVALUABLE,
    VERDICT_UNSATISFIED,
    evaluate_predicate,
)
from scripts.lib.goal_pilot_material_change import (  # noqa: E402
    OUTCOME_ASK_OPERATOR,
    OUTCOME_BOUNDED_IGNORANCE,
    OUTCOME_BUDGET_EXHAUSTED,
    OUTCOME_SUFFICIENT,
    PILOT_EVALUATOR,
    PILOT_TERMS,
    TERM_AGREES,
    TERM_INDEPENDENT_PRESENT,
    assemble_facts,
    build_predicate,
    classify_outcome,
    pilot_cost,
    run_pilot,
)

GOAL = "11111111-2222-3333-4444-555555555555"
CHANGE = {"change_guid": "c0ffee00-0000-4000-8000-000000000001",
          "subject_guid": "5ub1ec70-0000-4000-8000-000000000002",
          "symbol": "NOC", "change_pct": -2.44}


class FakeTiered:
    """Stands in for TieredValidationResult — only the read fields matter."""

    def __init__(self, *, state="RECONCILED", release_allowed=True, blind=(),
                 paid_calls=0, critic_calls=2, cost_usd=0.0):
        self.state = state
        self.deterministic_release_allowed = release_allowed
        self.blind_lanes = tuple(blind)
        self.paid_calls = paid_calls
        self.critic_calls = critic_calls
        self.cost_usd = cost_usd


def _agrees_ok(observed, independent):
    return True, "corroborated"


def _agrees_disagree(observed, independent):
    return False, f"disagree_{observed}_vs_{independent}"


def _agrees_none(observed, independent):
    return False, "no_independent_source"


def _all_good(**over):
    kw = dict(goal_id=GOAL, independent=-2.40, tiered=FakeTiered(),
              calibrated=True, falsifier_ok=True,
              checkpoint={"due_at": "2026-09-23T00:00:00Z"}, second_lap=True,
              agrees_fn=_agrees_ok)
    kw.update(over)
    return run_pilot(CHANGE, **kw)


# ── the evaluator must be one cio_goals actually implements ──────────────────

def test_the_pilot_evaluator_is_implemented_not_invented():
    """A misspelled evaluator makes every predicate permanently UNEVALUABLE."""
    from scripts.lib.cio_goals import KNOWN_EVALUATORS
    assert PILOT_EVALUATOR in KNOWN_EVALUATORS


def test_every_outcome_the_pilot_can_emit_is_a_declared_termination_outcome():
    for outcome in (OUTCOME_SUFFICIENT, OUTCOME_BOUNDED_IGNORANCE,
                    OUTCOME_BUDGET_EXHAUSTED, OUTCOME_ASK_OPERATOR):
        assert outcome in TERMINATION_OUTCOMES


# ── identity: no sixth ID scheme ─────────────────────────────────────────────

def test_predicate_identity_is_rooted_in_the_goal_id():
    p = build_predicate(goal_id=GOAL)
    assert p["predicate_identity"].startswith(f"{GOAL}:v1:")


def test_restating_the_same_predicate_keeps_its_identity():
    assert build_predicate(goal_id=GOAL)["predicate_hash"] == \
        build_predicate(goal_id=GOAL)["predicate_hash"]


# ── THE headline control: missing source is unknowable, not false ────────────

def test_no_independent_source_is_omitted_not_set_false():
    """Omission => UNEVALUABLE. False would assert 'we checked and it disagreed'."""
    facts, unobtainable = assemble_facts(CHANGE, independent=None,
                                         tiered=FakeTiered(), calibrated=True,
                                         falsifier_ok=True,
                                         checkpoint={"due_at": "2026-09-23T00:00:00Z"},
                                         second_lap=True, agrees_fn=_agrees_none)
    assert TERM_INDEPENDENT_PRESENT not in facts
    assert TERM_AGREES not in facts
    assert unobtainable[TERM_INDEPENDENT_PRESENT] == "no_independent_source"


def test_missing_independent_source_terminates_bounded_ignorance_never_achieved():
    row = _all_good(independent=None, agrees_fn=_agrees_none)
    assert row["verdict"]["verdict"] == VERDICT_UNEVALUABLE
    assert row["outcome"] == OUTCOME_BOUNDED_IGNORANCE
    assert row["achieved"] is False


def test_a_corrupted_price_fails_honestly_rather_than_silently_passing():
    """The NOC case: observed -77% against an independent -2.44%."""
    row = _all_good(independent=-77.0, agrees_fn=_agrees_disagree)
    assert row["verdict"]["verdict"] == VERDICT_UNSATISFIED
    assert row["achieved"] is False
    assert row["outcome"] != OUTCOME_SUFFICIENT


# ── the one path to achieved ─────────────────────────────────────────────────

def test_all_nine_terms_true_is_the_only_route_to_sufficient():
    row = _all_good()
    assert row["verdict"]["verdict"] == VERDICT_SATISFIED
    assert row["outcome"] == OUTCOME_SUFFICIENT
    assert row["achieved"] is True


@pytest.mark.parametrize("term", list(PILOT_TERMS))
def test_removing_any_single_term_prevents_achieved(term):
    """Nine conditions means nine — none is decorative."""
    p = build_predicate(goal_id=GOAL)
    facts, _ = assemble_facts(CHANGE, independent=-2.40, tiered=FakeTiered(),
                              calibrated=True, falsifier_ok=True,
                              checkpoint={"due_at": "2026-09-23T00:00:00Z"},
                              second_lap=True, agrees_fn=_agrees_ok)
    facts[term] = False
    assert evaluate_predicate(p, facts)["verdict"] == VERDICT_UNSATISFIED


def test_an_unbound_checkpoint_blocks_achievement():
    row = _all_good(checkpoint=None)
    assert row["achieved"] is False


def test_a_vacuous_falsifier_blocks_achievement():
    row = _all_good(falsifier_ok=False)
    assert row["verdict"]["verdict"] == VERDICT_UNSATISFIED
    assert row["achieved"] is False


def test_an_uncalibrated_validator_blocks_achievement():
    row = _all_good(calibrated=False)
    assert row["achieved"] is False


def test_a_blind_lane_makes_the_validator_uncalibrated():
    facts, _ = assemble_facts(CHANGE, independent=-2.40,
                              tiered=FakeTiered(blind=("grok",)),
                              falsifier_ok=True,
                              checkpoint={"due_at": "2026-09-23T00:00:00Z"},
                              second_lap=True, agrees_fn=_agrees_ok)
    assert facts["validator_calibrated"] is False


def test_a_tier0_block_prevents_achievement_and_costs_nothing():
    t = FakeTiered(state="BLOCK_DETERMINISTIC", release_allowed=False,
                   critic_calls=0, paid_calls=0)
    row = _all_good(tiered=t)
    assert row["achieved"] is False
    assert row["cost"]["paid_calls"] == 0
    assert row["cost"]["critic_calls"] == 0


def test_a_disagreement_is_not_a_reconciliation():
    row = _all_good(tiered=FakeTiered(state="DISAGREEMENT"))
    assert row["achieved"] is False


# ── budget and cost ──────────────────────────────────────────────────────────

def test_budget_exhaustion_wins_over_every_other_outcome():
    row = _all_good(budget_exhausted=True)
    assert row["outcome"] == OUTCOME_BUDGET_EXHAUSTED


def test_the_pilot_spends_nothing():
    """The plan's pass condition: paid_calls == 0 for the whole pilot."""
    rows = [_all_good(), _all_good(independent=None, agrees_fn=_agrees_none),
            _all_good(tiered=FakeTiered(state="DISAGREEMENT"))]
    cost = pilot_cost(rows)
    assert cost["laps"] == 3
    assert cost["paid_calls"] == 0
    assert cost["cost_usd"] == 0.0


def test_cost_is_read_from_the_validator_not_asserted():
    """A constant 0 would hide a real spend; the receipt must reflect reality."""
    row = _all_good(tiered=FakeTiered(paid_calls=2, cost_usd=0.0051))
    assert row["cost"]["paid_calls"] == 2
    assert pilot_cost([row])["paid_calls"] == 2


# ── classification edges ─────────────────────────────────────────────────────

def test_unevaluable_with_an_obtainable_gap_asks_the_operator():
    """Not every unknown is bounded ignorance — only genuinely unobtainable ones."""
    verdict = {"verdict": VERDICT_UNEVALUABLE, "reason": "missing_facts:tier0_deterministic_pass"}
    assert classify_outcome(verdict, unobtainable={}) == OUTCOME_ASK_OPERATOR


def test_shadow_mode_is_declared_on_every_row():
    assert _all_good()["mode"] == "SHADOW"
    assert _all_good()["authority"] == "READ_ONLY_ADVISORY"
