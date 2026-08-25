"""R16 institutional learning: outcomes, calibration, lookahead, firewall."""
from __future__ import annotations

import random
from pathlib import Path

import pytest

from scripts.lib.cio_institutional_learning import (
    DECISION_CLASSES,
    FEEDBACK_TAXONOMY,
    HORIZONS,
    MIN_LESSON_SAMPLES,
    PROMOTION_STAGES,
    QUALITY_AXES,
    append_outcome,
    bitemporal_view,
    build_outcome_observation,
    calibrate_confidence,
    classify_traceability,
    cost_of_learning,
    hypothesis_from_lesson,
    inventory_decisions,
    learning_may_not_override_truth,
    lesson_candidate_v2,
    normalize_feedback,
    notification_learning,
    preregister,
    promotion_advance,
    refuse_auto_routing,
    registries_must_not_change,
    reject_lookahead,
    schedule_outcome_checkpoint,
    score_quality_axes,
    shadow_experiment,
    similar_setup,
)
from scripts.lib.cio_model_learning import RoutingPromotionForbidden, snapshot_registries
from tests.r16_goldens import lookahead_goldens, outcome_goldens, specialist_model_goldens

pytestmark = pytest.mark.tier0
ROOT = Path(__file__).resolve().parents[1]
OUTCOMES = outcome_goldens()
LOOKAHEAD = lookahead_goldens()
SPEC = specialist_model_goldens()


def _decision(i: int, **extra) -> dict:
    rec = DECISION_CLASSES[i % len(DECISION_CLASSES)]
    row = {
        "decision_id": f"dec_{i:04d}",
        "subject_guid": f"sec-{i}",
        "created_at": "2026-06-01T00:00:00+00:00",
        "as_of": "2026-06-01T00:00:00+00:00",
        "recommendation": rec,
        "evidence_refs": ["e1"],
        "runtime_source_sha": "d72ecdd1",
        "confidence": 0.4 + (i % 6) * 0.1,
        "uncertainty": "incomplete filings",
    }
    row.update(extra)
    return row


def test_decision_classes_are_from_office_not_invented() -> None:
    for klass in ("HOLD", "TRIM", "EXIT", "RE_ENTER", "HOLD_CASH", "WAIT", "REVIEW"):
        assert klass in DECISION_CLASSES


@pytest.mark.parametrize("i", range(20))
def test_missing_id_is_unresolved(i: int) -> None:
    assert classify_traceability({"recommendation": "HOLD"}) == "UNRESOLVED"
    assert classify_traceability(_decision(i)) == "PARTIAL"  # optional fields missing
    full = _decision(i, portfolio_context_ref="p", policy_version="v1", ticker_research_state_version="t",
                     curation_version=0, symbol_thesis_version=1, counter_evidence_refs=["c"],
                     research_refs=["r"], specialist_artifact_refs=["s"], invalidation_criteria="x",
                     next_review_criteria="y", notification_disposition="SUPPRESSED", context_receipt="cr")
    assert classify_traceability(full) == "FULLY_TRACEABLE"


def test_inventory_does_not_fabricate_joins() -> None:
    rows = [_decision(i) for i in range(10)] + [{"recommendation": "HOLD"}]
    cov = inventory_decisions(rows)
    assert cov["fabricated_joins"] is False
    assert cov["counts"]["UNRESOLVED"] == 1
    assert cov["counts"]["PARTIAL"] == 10


@pytest.mark.parametrize("case", OUTCOMES, ids=[c["id"] for c in OUTCOMES])
def test_outcome_quality_goldens(case: dict) -> None:
    decision = _decision(int(case["id"].split("-")[1]), recommendation=case["recommendation"])
    obs = build_outcome_observation(
        decision_id=decision["decision_id"],
        subject_guid=decision["subject_guid"],
        horizon=case["horizon"],
        original_decision_state={"recommendation": case["recommendation"], "confidence": 0.7},
        realized_state={"price_up": case["pnl_up"]},
        source_refs=["holdings"],
        source_as_of="2026-07-01T00:00:00+00:00",
    )
    assert obs["history_rewritten"] is False
    assert obs["financial_action"] is False
    assert obs["horizon"] in HORIZONS
    q = score_quality_axes(
        pnl_up=case["pnl_up"],
        risk_warning_issued=case["risk_warning"],
        evidence_present=case["evidence"],
    )
    assert q["pnl_is_not_the_grade"] is True
    assert set(q["axes"]) == set(QUALITY_AXES)
    if case["risk_warning"] and case["pnl_up"]:
        assert q["risk_warning_valuable_if_price_up"] is True
    store: list = []
    decisions = [decision]
    first = append_outcome(store, obs, decisions)
    assert first["appended"] is True
    second = append_outcome(store, obs, decisions)
    assert second["duplicate"] is True
    assert decisions[0] == decision


def test_append_without_decision_fails() -> None:
    obs = build_outcome_observation(
        decision_id="missing", subject_guid="s", horizon="1_session",
        original_decision_state={}, realized_state={}, source_refs=[], source_as_of="2026-01-01T00:00:00+00:00",
    )
    assert append_outcome([], obs, [])["reason"] == "missing_decision"


@pytest.mark.parametrize("case", LOOKAHEAD, ids=[c["id"] for c in LOOKAHEAD])
def test_lookahead_firewall_goldens(case: dict) -> None:
    audit = reject_lookahead(case["context"], as_of=case["as_of"])
    assert audit["allowed"] is case["allow"]
    assert audit["zero_tolerated"] is True
    if not case["allow"]:
        assert audit["leaks"]


@pytest.mark.parametrize("case", SPEC, ids=[c["id"] for c in SPEC])
def test_specialist_not_scored_on_cio_agreement(case: dict) -> None:
    q = score_quality_axes(specialist_unique=case["unique_evidence"], pnl_up=case["agree_with_cio"])
    if case["unique_evidence"]:
        assert q["axes"]["specialist_contribution"] == "UNIQUE"
    else:
        assert q["axes"]["specialist_contribution"] != "UNIQUE"
    # Agreement with CIO is not the specialist score.
    assert q["pnl_is_not_the_grade"] is True
    assert case["score_on_agreement"] is False


def test_calibration_detects_overconfidence() -> None:
    rows = []
    for i in range(20):
        rows.append({"confidence": 0.9, "observed_quality": 0.2})
        rows.append({"confidence": 0.6, "observed_quality": 0.7})
        rows.append({"confidence": 0.2, "observed_quality": 0.5, "self_assessment": "I was perfect"})
    cal = calibrate_confidence(rows)
    assert cal["self_assessment_ignored"] is True
    assert cal["overconfidence"] is True
    assert cal["cohorts"]["low"]["n"] == 0  # self-assessment ignored


def test_lesson_one_sample_is_provisional() -> None:
    les = lesson_candidate_v2(
        scope="ticker", task_class="research_curation", statement="one trade",
        supporting_outcome_ids=["o1"], counterexamples=[], searched_counterexamples=True,
    )
    assert les["status"] == "PROVISIONAL"
    assert les["methodology_effect"] is False
    assert les["sample_size"] < MIN_LESSON_SAMPLES


def test_lesson_supported_requires_counterexample_search() -> None:
    ids = [f"o{i}" for i in range(6)]
    no_search = lesson_candidate_v2(scope="s", task_class="t", statement="x", supporting_outcome_ids=ids, counterexamples=[], searched_counterexamples=False)
    assert no_search["status"] == "PROVISIONAL"
    ok = lesson_candidate_v2(scope="s", task_class="t", statement="x", supporting_outcome_ids=ids, counterexamples=[], searched_counterexamples=True)
    assert ok["status"] == "SUPPORTED"


def test_hypothesis_preregister_and_shadow() -> None:
    les = lesson_candidate_v2(scope="s", task_class="contradiction_reconciliation", statement="think helps",
                             supporting_outcome_ids=[f"o{i}" for i in range(6)], counterexamples=[], searched_counterexamples=True)
    hyp = hypothesis_from_lesson(les, claim="FAST_THINK > FAST on contradiction", baseline="FAST", candidate="FAST_THINK", metric="quality", population="contradiction")
    frozen = preregister(hyp, primary_metric="quality", success_threshold=0.03, sample_count=30, cost_ceiling=0)
    assert frozen["preregistered"] is True
    control = [{"quality": 0.80} for _ in range(10)]
    cand = [{"quality": 0.90} for _ in range(10)]
    exp = shadow_experiment(control=control, candidate=cand, metric="quality", prereg=frozen)
    assert exp["finding"] == "positive"
    assert exp["operator_notified"] is False
    assert exp["trading"] is False
    neg = shadow_experiment(control=cand, candidate=control, metric="quality", prereg=frozen)
    assert neg["finding"] == "negative"


def test_promotion_cannot_self_approve() -> None:
    r = promotion_advance("REVIEW_READY", "OPERATOR_APPROVED", operator_authorized=False)
    assert r["ok"] is False
    assert r["reason"] == "PROMOTION_REQUIRES_SEPARATE_AUTHORITY"
    ok = promotion_advance("CANDIDATE", "SHADOW_TESTED")
    assert ok["ok"] is True
    rb = promotion_advance("REVIEW_READY", "REVERTED")
    assert rb["rollback"] is True


@pytest.mark.parametrize("raw,expect", [(x, x) for x in FEEDBACK_TAXONOMY] + [("ack", "USEFUL"), ("noise", "TOO_NOISY")])
def test_feedback_taxonomy(raw, expect) -> None:
    assert normalize_feedback(raw) == expect


def test_notification_learning_does_not_change_thresholds() -> None:
    rows = [{"label": "correct_suppression"}] * 5 + [{"label": "duplicate_page"}] * 2
    n = notification_learning(rows)
    assert n["thresholds_auto_changed"] is False
    assert n["counts"]["correct_suppression"] == 5


def test_checkpoint_idempotent() -> None:
    a = schedule_outcome_checkpoint("dec_1", "5_sessions")
    b = schedule_outcome_checkpoint("dec_1", "5_sessions", existing=[a["checkpoint_id"]])
    assert a["duplicate"] is False
    assert b["duplicate"] is True
    assert a["trading"] is False


def test_similar_setup_is_bounded() -> None:
    hist = [{"recommendation": "HOLD", "decision_id": f"d{i}", "outcome_id": f"o{i}"} for i in range(20)]
    out = similar_setup(current={"recommendation": "HOLD", "uncertainty": "regime"}, history=hist, limit=3)
    assert len(out["matches"]) == 3
    assert out["dumped_all_memory"] is False
    assert out["evidence_linked_only"] is True


def test_memory_cannot_override_truth() -> None:
    assert learning_may_not_override_truth({"memory_behavior_influence": 0}) is True
    assert learning_may_not_override_truth({"overrides_office_truth": True, "memory_behavior_influence": 0}) is False
    assert learning_may_not_override_truth({"memory_behavior_influence": 1}) is False


def test_bitemporal_and_cost() -> None:
    bt = bitemporal_view(believed_then="HOLD", knew_then="gap", outcome_then=None, available_later="10-K", know_now="still HOLD")
    assert bt["future_not_leaked_into_then"] is True
    cost = cost_of_learning(evaluations=100, experiments=10, deterministic=True)
    assert cost["total"] == 0
    assert cost["paid_models_used_to_inflate_n"] is False


def test_registries_immutable(tmp_path) -> None:
    before = snapshot_registries(ROOT)
    assert registries_must_not_change(ROOT, before)
    with pytest.raises(RoutingPromotionForbidden):
        refuse_auto_routing(tmp_path)


@pytest.mark.parametrize("seed", range(30))
def test_property_no_rewrite_no_auto_promote(seed: int) -> None:
    rng = random.Random(seed)
    d = _decision(seed)
    obs = build_outcome_observation(
        decision_id=d["decision_id"], subject_guid=d["subject_guid"],
        horizon=rng.choice(HORIZONS), original_decision_state={"r": d["recommendation"]},
        realized_state={"x": seed}, source_refs=["s"], source_as_of="2026-07-01T00:00:00+00:00",
    )
    store: list = []
    append_outcome(store, obs, [d])
    assert d["decision_id"] == f"dec_{seed:04d}"
    assert promotion_advance("REVIEW_READY", "PROMOTED")["ok"] is False


@pytest.mark.parametrize("kind", [
    "missing_decision", "duplicate_outcome", "future_leak", "single_sample_lesson",
    "no_counterexample_search", "promotion_without_auth", "registry_mutation",
    "memory_injection", "feedback_injection",
])
def test_faults(kind: str, tmp_path) -> None:
    if kind == "missing_decision":
        assert append_outcome([], build_outcome_observation(
            decision_id="x", subject_guid="s", horizon="1_session",
            original_decision_state={}, realized_state={}, source_refs=[], source_as_of="2026-01-01T00:00:00+00:00",
        ), [])["reason"] == "missing_decision"
    elif kind == "duplicate_outcome":
        d = _decision(1)
        obs = build_outcome_observation(decision_id=d["decision_id"], subject_guid="s", horizon="1_session",
                                        original_decision_state={}, realized_state={}, source_refs=[], source_as_of="2026-01-01T00:00:00+00:00")
        st: list = []
        append_outcome(st, obs, [d])
        assert append_outcome(st, obs, [d])["duplicate"] is True
    elif kind == "future_leak":
        assert reject_lookahead({"future_price": 1}, as_of="2026-01-01T00:00:00+00:00")["allowed"] is False
    elif kind == "single_sample_lesson":
        assert lesson_candidate_v2(scope="s", task_class="t", statement="x", supporting_outcome_ids=["o"], counterexamples=[], searched_counterexamples=True)["status"] == "PROVISIONAL"
    elif kind == "no_counterexample_search":
        assert lesson_candidate_v2(scope="s", task_class="t", statement="x", supporting_outcome_ids=[f"o{i}" for i in range(6)], counterexamples=[], searched_counterexamples=False)["status"] == "PROVISIONAL"
    elif kind == "promotion_without_auth":
        assert promotion_advance("REVIEW_READY", "OPERATOR_APPROVED")["ok"] is False
    elif kind == "registry_mutation":
        with pytest.raises(RoutingPromotionForbidden):
            refuse_auto_routing(tmp_path)
    elif kind == "memory_injection":
        assert learning_may_not_override_truth({"memory_behavior_influence": 1}) is False
    elif kind == "feedback_injection":
        assert normalize_feedback("DROP_TABLE") == "NOT_USEFUL"
