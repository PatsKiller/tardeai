from scripts.lib.thesis_decision_gate import apply_thesis_decision_gate


def _delta(classification: str):
    return {
        "delta_id": f"delta_{classification.lower()}",
        "classification": classification,
        "freshness": {"state": "CURRENT"},
    }


def test_invalidated_thesis_blocks_explicit_reentry_but_preserves_operator_record():
    out = apply_thesis_decision_gate(
        current_action="REENTER",
        governed_verdict="RE_ENTER",
        thesis_state="CURRENT",
        thesis_stance="HOLD",
        delta=_delta("INVALIDATES"),
    )
    assert out["effective_action"] == "AVOID"
    assert out["effective_governed_verdict"] is None
    assert out["operator_governed_verdict"] == "RE_ENTER"
    assert out["restricted"] is True
    assert "FRESH_THESIS_INVALIDATION_BLOCKS_REENTER" in out["reason_codes"]


def test_strengthened_thesis_cannot_independently_promote():
    out = apply_thesis_decision_gate(
        current_action="WAIT",
        governed_verdict=None,
        thesis_state="CURRENT",
        delta=_delta("STRENGTHENS"),
    )
    assert out["effective_action"] == "WAIT"
    assert out["effective_governed_verdict"] is None
    assert out["positive_delta_created_promotion"] is False


def test_conflict_fails_closed_and_weakening_only_demotes():
    conflict = apply_thesis_decision_gate(
        current_action="REENTER",
        governed_verdict="RE_ENTER",
        thesis_state="CONFLICTED",
        delta=_delta("CONFLICTED"),
    )
    assert conflict["effective_action"] == "WAIT"
    assert conflict["effective_governed_verdict"] is None

    weak = apply_thesis_decision_gate(
        current_action="REENTER",
        governed_verdict=None,
        thesis_state="CURRENT",
        delta=_delta("WEAKENS"),
    )
    assert weak["effective_action"] == "NEAR"
    assert weak["effective_governed_verdict"] is None


def test_incomplete_thesis_does_not_erase_non_invalidated_operator_verdict():
    out = apply_thesis_decision_gate(
        current_action="REENTER",
        governed_verdict="RE_ENTER",
        thesis_state="RESEARCH_REQUIRED",
        delta=_delta("INSUFFICIENT_DATA"),
    )
    assert out["effective_action"] == "REENTER"
    assert out["effective_governed_verdict"] == "RE_ENTER"
    assert out["operator_governed_verdict"] == "RE_ENTER"
