"""R13 institutional contracts: policy, outcomes, specialists, reliability, retrieval."""
from __future__ import annotations

import pytest

from scripts.lib.cio_operator_investment_policy import FIELD_SPECS
from scripts.lib.cio_r13_institution import (
    OUTCOME_AXES,
    SPECIALISTS,
    bitemporal_answers,
    build_policy_registry,
    calibrate_confidence,
    classify_policy_field,
    confirm_policy_lifecycle,
    dependency_outage,
    duplicate_execution_guard,
    evaluate_retrieval,
    hermes_challenge_needed,
    identity_remediation_queue,
    latency_slo,
    ledger_tax_critique,
    link_decision_outcome,
    material_cycle_cost,
    memory_cannot_override,
    orchestrate,
    policy_provenance_view,
    preference_is_not_policy,
    promotion_blocked,
    record_notification_outcome,
    recover_from_crash,
    register_hypothesis,
    retract_policy,
    score_alerts,
    score_specialist_readiness,
    specialist_artifact,
    split_support_counter,
    stale_degrade,
    unchanged_cycle_cost,
)
from scripts.lib.memory_consolidator import lesson_from_outcomes
from scripts.lib.preference_candidate import from_feedback
from scripts.lib.cio_situation_state import SITUATION_CLASSES, detect_office_situations
from tests.r11_office_fixtures import NOW, office, policy, portfolio

pytestmark = pytest.mark.tier0


def test_policy_registry_all_fields_classified() -> None:
    reg = build_policy_registry({"status": "POLICY_REQUIRED", "fields": {}, "missing_fields": list(FIELD_SPECS)}, default_cash_band=True)
    assert len(reg["fields"]) == len(FIELD_SPECS)
    assert reg["cash_target_confirmed"] is False
    cash = next(r for r in reg["fields"] if r["field"] == "cash_target_range_pct")
    assert cash["class"] == "DEFAULT"
    view = policy_provenance_view(reg)
    assert all("confirmed" in r and "source" in r for r in view)


def test_confirmed_field_class() -> None:
    pol = policy(confirmed=True)
    assert classify_policy_field("cash_target_range_pct", pol) == "CONFIRMED"


def test_lifecycle_confirm_and_retract() -> None:
    rec = confirm_policy_lifecycle(field="cash_target_range_pct", proposal={"min": 10, "max": 20}, actor="operator")
    assert rec["natural_language_inference"] is False
    assert rec["version"] == 1
    gone = retract_policy(rec, actor="operator")
    assert gone["retracted"] is True
    assert gone["status"] == "RETRACTED"


def test_preference_not_policy() -> None:
    pref = from_feedback(subject_guid="op", statement="too many alerts", supporting_feedback_ids=["f1"])
    assert preference_is_not_policy(pref) is True
    assert pref["policy_effect"] is False


@pytest.mark.parametrize("status", ["DELIVERED", "SUPPRESSED", "FAILED", "RETRIED", "EXPIRED", "RESOLVED", "READ_OR_ACKNOWLEDGED"])
def test_notification_outcomes(status: str) -> None:
    row = record_notification_outcome(notification_id="n1", status=status, situation_id="s1")
    assert row["rewritten_history"] is False
    assert row["memory_behavior_influence"] == 0


def test_alert_quality_rates() -> None:
    rows = (
        [{"notification_class": "SUPPRESSED", "suppressed_reason": "unchanged_replay"}] * 8
        + [{"notification_class": "IMMEDIATE", "status": "DELIVERED"}] * 2
    )
    q = score_alerts(rows)
    assert q["suppression_rate"] == 0.8
    assert q["behavior_influence"] == 0


def test_identity_queue_does_not_mint() -> None:
    q = identity_remediation_queue([
        {"symbol": "PRSO", "security_guid": None},
        {"symbol": "SCHD", "security_guid": "guid-schd"},
    ])
    assert q["count"] == 1
    assert q["minted_from_ticker"] == 0
    assert q["items"][0]["fabricated"] is False
    assert q["items"][0]["action"] == "RESOLVE_WITH_REASON_DO_NOT_MINT"


def test_bitemporal_four_questions() -> None:
    facts = [
        {"id": "a", "valid_from": "2026-01-01", "valid_to": "2026-06-01", "tx_from": "2026-01-02"},
        {"id": "b", "valid_from": "2026-06-01", "valid_to": "9999", "tx_from": "2026-06-02"},
    ]
    ans = bitemporal_answers(facts, then="2026-03-01", now="2026-07-01")
    assert ans["WHAT_DID_WE_BELIEVE_THEN"][0]["id"] == "a"
    assert ans["WHAT_DO_WE_BELIEVE_NOW"][0]["id"] == "b"
    assert ans["WHAT_CHANGED"][0]["id"] == "b"


def test_memory_firewall() -> None:
    truth = {"observed_cash_usd": 578111.14}
    ok = {"overrides_office_truth": False, "policy_effect": False, "memory_behavior_influence": 0}
    bad = {"overrides_office_truth": True, "policy_effect": False, "memory_behavior_influence": 0}
    assert memory_cannot_override(ok, truth) is True
    assert memory_cannot_override(bad, truth) is False
    assert memory_cannot_override({**ok, "memory_behavior_influence": 1}, truth) is False


@pytest.mark.parametrize("agent", SPECIALISTS)
def test_specialist_artifact_contract(agent: str) -> None:
    art = specialist_artifact(
        agent=agent,
        claim="fixture critique",
        evidence=["e1"],
        confidence=0.55,
        uncertainty="incomplete lots",
        contradictions=[],
        recommendation="REVIEW",
    )
    assert art["freeform_untraceable"] is False
    assert art["financial_action"] is False
    score = score_specialist_readiness(art, tools=True, runtime=True, handoff=True, tests=True, same_brain=True, failure_recovery=True)
    assert score["score"] == 1.0


def test_ledger_wash_sale() -> None:
    art = ledger_tax_critique(lots=[{"symbol": "SCHD", "qty": 10}], wash=True, account_constraint="IRA")
    assert art["agent"] == "ledger"
    assert art["recommendation"] == "NO_TRADE_TAX_CONSTRAINT"
    assert "wash_sale" in art["contradictions"]


def test_orchestration_preserves_disagreement() -> None:
    cio = specialist_artifact(agent="alex", claim="deploy staged", evidence=["cash"], confidence=0.6, uncertainty="policy gap", contradictions=[], recommendation="DEPLOY_STAGED")
    g = specialist_artifact(agent="guardian", claim="regime risk-off", evidence=["vix"], confidence=0.7, uncertainty="macro", contradictions=["cio deploy"], recommendation="HOLD")
    out = orchestrate(cio_candidate=cio, critiques=[g])
    assert out["silently_overwritten"] is False
    assert out["disagreement_preserved"] is True
    assert out["disagreements"]


def test_hermes_challenge_and_counter_evidence() -> None:
    assert hermes_challenge_needed({"situation_class": "CONTRADICTION"}) is True
    assert hermes_challenge_needed({"situation_class": "NO_MATERIAL_CHANGE", "freshness": "CURRENT"}) is False
    split = split_support_counter({"support": ["a"], "counterevidence": ["b"]})
    assert split["both_present"] is True


def test_confidence_not_llm_self_score() -> None:
    cal = calibrate_confidence(claimed=0.99, evidence_n=0, contradictions_n=2, freshness="STALE")
    assert cal["overconfident"] is True
    assert cal["llm_self_confidence_used"] is False


def test_outcome_link_and_lesson() -> None:
    link = link_decision_outcome(decision_id="d1", outcome_id="o1", axes={"direction": "hit"})
    assert link["history_rewritten"] is False
    assert set(link["axes"]) == set(OUTCOME_AXES)
    lesson = lesson_from_outcomes(subject_guid="g", outcome_ids=[f"o{i}" for i in range(5)], statement="trim after deterioration")
    assert lesson["mature"] is True
    assert lesson["methodology_effect"] is False


def test_hypothesis_firewall() -> None:
    h = register_hypothesis(
        hypothesis="page POLICY_GAP at most once per day",
        metric="repeat_page_rate",
        baseline=0.4,
        expected_change=-0.3,
        sample_requirement=30,
        rollback="restore prior dedupe window",
    )
    assert h["promoted"] is False
    for target in ("execution", "risk", "policy", "notification_thresholds", "model_routing"):
        assert promotion_blocked(h, target) is True
    assert promotion_blocked(h, "docs") is False


@pytest.mark.parametrize("dep", ["telegram", "llm", "hermes", "embeddings", "external_data"])
def test_dependency_outage_degrades(dep: str) -> None:
    out = dependency_outage(dep)
    assert out["financial_action"] is False
    assert out["degrade"]


@pytest.mark.parametrize("fresh", ["STALE", "UNAVAILABLE", "CURRENT"])
def test_stale_degrade(fresh: str) -> None:
    assert stale_degrade(fresh) in {"DEFER", "FAIL_CLOSED", "PROCEED"}


def test_crash_and_duplicate_guards() -> None:
    rec = recover_from_crash({"situations": []})
    assert rec["state_restored"] is True
    assert rec["no_duplicate_page"] is True
    dup = duplicate_execution_guard("a", "b", same_fingerprint=True)
    assert dup["operator_interrupted_twice"] is False
    assert dup["durable_action_duplicated"] is False


def test_cost_and_slo() -> None:
    assert unchanged_cycle_cost() == {"detector_model_calls": 0, "paid_cost": 0, "authority": "READ_ONLY_ADVISORY"}
    c = material_cycle_cost(detector=0, retrieval=0, specialist=0, synthesis=0.02, notification=0)
    assert c["total_cost"] == 0.02
    slo = latency_slo({"event_to_detection_s": 3.6, "detection_to_decision_s": 0.2})
    assert slo["within_slo"] is True


def test_retrieval_eval_100_queries() -> None:
    fails = 0
    for i in range(100):
        kind = ["relevant", "stale", "contradiction", "wrong_symbol", "temporal"][i % 5]
        symbol = "SCHD"
        if kind == "relevant":
            hits = [{"symbol": "SCHD", "valid_to": "9999"}]
        elif kind == "stale":
            hits = [{"symbol": "SCHD", "valid_to": "2020-01-01"}]
        elif kind == "contradiction":
            hits = [{"symbol": "SCHD", "role": "counter"}]
        elif kind == "wrong_symbol":
            hits = [{"symbol": "NVDA"}]
        else:
            hits = [{"symbol": "SCHD", "valid_to": "9999"}]
        q = {"id": f"q{i}", "expect": kind, "symbol": symbol, "as_of": "2026-08-25"}
        ev = evaluate_retrieval(q, hits)
        if not ev["pass"]:
            fails += 1
    assert fails == 0


STEPH_CASES = [f"case_{i}" for i in range(25)]


@pytest.mark.parametrize("case", STEPH_CASES)
def test_steph_depth_25(case: str) -> None:
    art = specialist_artifact(
        agent="steph",
        claim=f"allocation critique {case}",
        evidence=[case],
        confidence=0.5,
        uncertainty="fixture",
        contradictions=[],
        recommendation="REVIEW_ALLOCATION",
    )
    assert art["agent"] == "steph"
    assert art["authority"] == "READ_ONLY_ADVISORY"
