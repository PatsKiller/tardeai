"""Independent CIO critic shadow tests — golden cases, shadow-only flags."""
from __future__ import annotations

from financial_senses.critic import (
    CRITIC_BEHAVIOR_INFLUENCE,
    CRITIC_SHADOW,
    RESULT_DATA_UNAVAILABLE,
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


def test_coverage_pct_90_means_10_unmodeled():
    review = review_decision(
        {"identity_status": "RESOLVED", "coverage_pct": 90.0, "facts": []},
        {"action": "hold"},
    )
    assert any("10.00%" in e for e in review.portfolio_effects)
    assert not any("90.00%" in e for e in review.portfolio_effects)


def test_unmodeled_coverage_pct_10_not_inverted():
    review = review_decision(
        {"identity_status": "RESOLVED", "unmodeled_coverage_pct": 10.0, "facts": []},
        {"action": "hold"},
    )
    # unmodeled_coverage_pct is already the unmodeled fraction; it must NOT be
    # subtracted from 100 (which would report 90% unmodeled).
    assert any("10.00%" in e for e in review.portfolio_effects)
    assert not any("90.00%" in e for e in review.portfolio_effects)


def test_material_actions_missing_evidence_flagged():
    for action in ["ADD", "EXIT", "ROTATE", "RAISE_CASH", "RE_ENTER", "DEPLOY_CASH", "TRIM"]:
        review = review_decision(
            {"identity_status": "RESOLVED", "facts": []},
            {"action": action, "objective": "rebalance"},
        )
        assert any("substantive evidence" in m for m in review.missing_evidence), action
        assert review.result == RESULT_MATERIAL_OBJECTION, action


def test_non_material_actions_not_flagged_for_missing_evidence():
    for action in ["HOLD", "WAIT", "RESEARCH", "NO_ACTION", "DEFER"]:
        review = review_decision(
            {"identity_status": "RESOLVED", "facts": []},
            {"action": action},
        )
        assert not any("substantive evidence" in m for m in review.missing_evidence), action


def test_coverage_pct_above_100_is_data_unavailable():
    review = review_decision(
        {"identity_status": "RESOLVED", "coverage_pct": 150.0, "facts": []},
        {"action": "hold"},
    )
    assert review.result == RESULT_DATA_UNAVAILABLE
    assert any("coverage" in m for m in review.missing_evidence)


def test_coverage_pct_below_0_is_data_unavailable():
    review = review_decision(
        {"identity_status": "RESOLVED", "coverage_pct": -5.0, "facts": []},
        {"action": "hold"},
    )
    assert review.result == RESULT_DATA_UNAVAILABLE


def test_unmodeled_coverage_pct_above_100_is_data_unavailable():
    review = review_decision(
        {"identity_status": "RESOLVED", "unmodeled_coverage_pct": 150.0, "facts": []},
        {"action": "hold"},
    )
    assert review.result == RESULT_DATA_UNAVAILABLE


def test_coverage_pct_non_numeric_is_data_unavailable():
    review = review_decision(
        {"identity_status": "RESOLVED", "coverage_pct": "not-a-number", "facts": []},
        {"action": "hold"},
    )
    assert review.result == RESULT_DATA_UNAVAILABLE


def test_coverage_pct_100_means_zero_unmodeled_no_objection():
    review = review_decision(
        {"identity_status": "RESOLVED", "coverage_pct": 100.0, "facts": []},
        {"action": "hold"},
    )
    assert review.result == RESULT_NO_MATERIAL_OBJECTION
