"""Independent CIO critic shadow tests — golden cases, shadow-only flags."""
from __future__ import annotations

from financial_senses.critic import (
    CRITIC_BEHAVIOR_INFLUENCE,
    CRITIC_SHADOW,
    RESULT_MATERIAL_OBJECTION,
    RESULT_NO_MATERIAL_OBJECTION,
    IndependentCriticProvider,
    review_decision,
)


def test_shadow_flags_are_fixed():
    assert CRITIC_SHADOW == 1
    assert CRITIC_BEHAVIOR_INFLUENCE == 0


def test_clean_decision_no_objection():
    review = review_decision({"identity_status": "RESOLVED", "facts": []}, {"action": "hold"})
    assert review.result == RESULT_NO_MATERIAL_OBJECTION


def test_stale_fact_is_objection():
    review = review_decision(
        {"facts": [{"key": "revenue", "freshness": "STALE"}]},
        {"action": "trim", "objective": "reduce concentration"},
    )
    assert review.result == RESULT_MATERIAL_OBJECTION
    assert any("stale" in r.lower() for r in review.freshness_risks)


def test_identity_ambiguity_is_objection():
    review = review_decision(
        {"identity_status": "AMBIGUOUS", "facts": []}, {"action": "trim", "objective": "x"}
    )
    assert review.result == RESULT_MATERIAL_OBJECTION
    assert review.identity_risks


def test_vintage_leak_is_objection():
    review = review_decision(
        {"vintage_leak": True, "facts": []}, {"action": "hold"}
    )
    assert review.result == RESULT_MATERIAL_OBJECTION
    assert any("vintage" in r.lower() for r in review.freshness_risks)


def test_trim_without_objective_missing_evidence():
    review = review_decision({"facts": []}, {"action": "trim"})
    assert review.result == RESULT_MATERIAL_OBJECTION
    assert any("objective" in m for m in review.missing_evidence)


def test_reentry_without_authority_missing_evidence():
    review = review_decision({"facts": []}, {"action": "reentry", "objective": "x"})
    assert any("authority" in m for m in review.missing_evidence)


def test_contradiction_is_objection():
    review = review_decision(
        {"contradictions": ["SEC filing contradicts thesis"], "facts": []}, {"action": "hold"}
    )
    assert review.result == RESULT_MATERIAL_OBJECTION
    assert review.counterevidence


def test_unmodeled_portfolio_effect_flagged():
    review = review_decision(
        {"unmodeled_coverage_pct": 50.0, "facts": []}, {"action": "hold"}
    )
    assert review.portfolio_effects


def test_critic_never_changes_live_state():
    p = IndependentCriticProvider()
    r = p.query(
        "critic.review",
        {"evidence": {"facts": [{"key": "x", "freshness": "STALE"}]}, "proposed_action": {"action": "trim"}},
    )
    assert r.data["shadow_only"] is True
    assert r.data["behavior_influence"] is False
    assert r.data["review"]["result"] == RESULT_MATERIAL_OBJECTION


def test_review_id_binds_evidence():
    action = {"action": "trim", "objective": "reduce concentration"}
    r1 = review_decision({"identity_status": "RESOLVED", "facts": [{"key": "a"}]}, action)
    r2 = review_decision({"identity_status": "RESOLVED", "facts": [{"key": "b"}]}, action)
    assert r1.critic_review_id != r2.critic_review_id
    assert r1.evidence_digest != r2.evidence_digest


def test_missing_identity_is_not_resolved():
    review = review_decision({"facts": []}, {"action": "hold"})
    assert review.identity_risks
    assert any("UNKNOWN" in r for r in review.identity_risks)
    assert review.result == RESULT_MATERIAL_OBJECTION


def test_unmodeled_portfolio_is_material_objection():
    review = review_decision(
        {"identity_status": "RESOLVED", "coverage_pct": 50.0, "facts": []},
        {"action": "hold"},
    )
    assert review.portfolio_effects
    assert review.result == RESULT_MATERIAL_OBJECTION


def test_small_unmodeled_below_threshold_not_material():
    review = review_decision(
        {"identity_status": "RESOLVED", "coverage_pct": 98.0, "facts": []},
        {"action": "hold"},
    )
    assert review.result == RESULT_NO_MATERIAL_OBJECTION


def test_material_action_no_evidence_not_no_objection():
    review = review_decision(
        {"identity_status": "RESOLVED", "facts": []},
        {"action": "trim", "objective": "reduce concentration"},
    )
    assert review.result == RESULT_MATERIAL_OBJECTION
    assert any("substantive evidence" in m for m in review.missing_evidence)
