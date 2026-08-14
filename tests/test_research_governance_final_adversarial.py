"""Research governance — FINAL R1 adversarial suite (PR-R1 remediation v2).

Every test maps to a hole the previous 127-test suite did NOT exercise: leaky
CPCV folds, spoofable promotion evidence, unverifiable result hashes, mutable OOS
payloads, contract-only acceptance loopholes, catalog self-definition, PBO
tie/approximation governance, and structured retrieval.

Fail-closed is the product: each case must FAIL (or reject) as specified.
No side effects: pure functions and in-memory stores only.
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from scripts.lib.research_governance import (  # noqa: E402
    acceptance,
    bootstrap_reality_check,
    cv,
    deflated_sharpe,
    pbo,
    promotion_gate,
    retrieval_contract,
    trial_registry,
)
from scripts.lib.research_governance.enums import GateState  # noqa: E402
from scripts.lib.research_governance.models import SampleTimingContract, validate_no_lookahead  # noqa: E402


# -- CPCV ---------------------------------------------------------------------

def test_cpcv_separated_test_groups_embargo_each_block():
    labels = [(i * 10, i * 10 + 1) for i in range(12)]
    parts = cv.combinatorial_purged_cv(12, labels, n_groups=4, n_test_groups=2, embargo=25)
    target = next(p for p in parts if set(p["test"]) == {0, 1, 2, 6, 7, 8})
    # group 1 (indices 3,4,5) sits after test block 0 -> 3 and 4 inside embargo.
    assert 3 not in target["train"], "sandwiched sample 3 leaked into training"
    assert 4 not in target["train"], "sandwiched sample 4 leaked into training"
    assert 5 in target["train"], "sample 5 is outside the embargo window (must stay)"
    # group 3 (indices 9,10,11) after test block 2 -> 9,10 inside embargo.
    assert 9 not in target["train"], "post-block-2 sample 9 leaked"
    assert 10 not in target["train"], "post-block-2 sample 10 leaked"
    assert 11 in target["train"], "sample 11 is outside the embargo window (must stay)"


def test_cpcv_n_samples_lt_n_groups_rejected():
    with pytest.raises(ValueError):
        cv.combinatorial_purged_cv(3, [(i, i + 1) for i in range(3)], n_groups=4, n_test_groups=1)


def test_cpcv_invalid_n_test_groups_rejected():
    labels = [(i, i + 1) for i in range(12)]
    with pytest.raises(ValueError):
        cv.combinatorial_purged_cv(12, labels, n_groups=4, n_test_groups=0)
    with pytest.raises(ValueError):
        cv.combinatorial_purged_cv(12, labels, n_groups=4, n_test_groups=4)


# -- Promotion fail-closed ----------------------------------------------------

def _base():
    return {
        "source_id": "s", "claim": "c", "page_or_section": "p", "scope": "us",
        "evidence_type": "EMPIRICAL_STRATEGY",
        "protocol_hash": "ph", "trial_family_id": "f", "family_frozen": True,
        "family_definition_hash": "fdh", "hypothesis_id": "h1",
        "code_sha": "c0", "dataset_hash": "d0",
        "in_sample_metric": 1.0, "in_sample_threshold": 0.0,
        "oos_supported": True, "oos_untouched": True,
        "multiple_testing": {
            "status": "OK", "method": "bonferroni", "alpha": 0.05,
            "family_id": "f", "family_definition_hash": "fdh",
            "trial_family_id": "f", "tested_hypothesis_id": "h1",
            "raw_pvalue": 0.001, "adjusted_pvalue": 0.004, "rejected": True,
            "complete_family": True,
        },
        "reality_check": {
            "status": "OK", "family_id": "f", "family_definition_hash": "fdh",
            "trial_family_id": "f", "bootstrap_pvalue": 0.01,
            "n_rules": 5, "n_observations": 100, "n_bootstrap": 1000,
            "bootstrap_method": "stationary", "mean_block_length": 5.0,
        },
        "robustness": {
            "sample_n": True, "benchmark": True, "subperiods": True, "regimes": True,
            "costs": True, "outlier_dependence": True, "lookahead_control": True,
            "survivorship_control": True, "limitations": True,
        },
        "evidence_grade": "A", "influence_class": "VALUATION_INPUT",
    }


def test_promotion_missing_oos_untouched_fails():
    assert promotion_gate.run_promotion_gate(dict(_base(), oos_untouched=None))["overall"] == GateState.FAIL.value


def test_promotion_oos_untouched_false_fails():
    assert promotion_gate.run_promotion_gate(dict(_base(), oos_untouched=False))["overall"] == GateState.FAIL.value


def test_promotion_multiple_testing_wrong_hypothesis_fails():
    mt = dict(_base()["multiple_testing"], tested_hypothesis_id="OTHER")
    assert promotion_gate.run_promotion_gate(dict(_base(), multiple_testing=mt))["overall"] == GateState.FAIL.value


def test_promotion_reality_check_wrong_family_hash_fails():
    rc = dict(_base()["reality_check"], family_definition_hash="WRONG")
    assert promotion_gate.run_promotion_gate(dict(_base(), reality_check=rc))["overall"] == GateState.FAIL.value


def test_promotion_empty_robustness_fails():
    assert promotion_gate.run_promotion_gate(dict(_base(), robustness={}))["overall"] == GateState.FAIL.value


def test_promotion_missing_sample_n_blocks_grade_a():
    rob = dict(_base()["robustness"], sample_n=False)
    assert promotion_gate.run_promotion_gate(dict(_base(), robustness=rob))["overall"] == GateState.FAIL.value


def test_promotion_policy_expired_fails():
    ctx = {
        "source_id": "s", "claim": "c", "page_or_section": "p", "scope": "us",
        "evidence_type": "POLICY_OR_REGULATORY", "evidence_grade": "B",
        "influence_class": "RISK_VETO", "authoritative_source": "IRS",
        "effective_date": "2026-01-01", "jurisdiction": "US",
        "verified_at": "2019-01-01", "current_as_of": "2026-08-01",
        "next_reverify_at": "2020-01-01",
    }
    assert promotion_gate.run_promotion_gate(ctx)["overall"] == GateState.FAIL.value


# -- Trial registry -----------------------------------------------------------

def test_family_definition_hash_required_for_confirmatory():
    reg = trial_registry.TrialRegistry()
    with pytest.raises(ValueError):
        reg.freeze_family("f", "h", protocol_hash="ph", planned_trials=[("a", "c1")],
                          confirmatory=True)


def test_supplied_result_hash_mismatch_rejected():
    reg = trial_registry.TrialRegistry()
    reg.freeze_family("f", "h", protocol_hash="ph", planned_trials=[("a", "c1")])
    with pytest.raises(ValueError):
        reg.record_trial("f", "a", config_hash="c1", result_payload={"x": 1}, result_hash="0" * 64)


def test_opaque_result_hash_without_artifact_rejected():
    reg = trial_registry.TrialRegistry()
    reg.freeze_family("f", "h", protocol_hash="ph", planned_trials=[("a", "c1")])
    with pytest.raises(ValueError):
        reg.record_trial("f", "a", config_hash="c1", result_hash="d" * 64)


def test_changed_oos_payload_rejected():
    reg = trial_registry.TrialRegistry()
    reg.freeze_family("f", "h", protocol_hash="ph", planned_trials=[("a", "c1")])
    reg.register_oos_window("f", "w", oos_generation=1, segment_start="2020")
    with pytest.raises(ValueError):
        reg.register_oos_window("f", "w", oos_generation=2, segment_start="2021")


def test_consumed_oos_segment_alias_blocked():
    reg = trial_registry.TrialRegistry()
    reg.freeze_family("f", "h", protocol_hash="ph", planned_trials=[("a", "c1")])
    reg.register_oos_window("f", "w1", oos_generation=1, segment_start="2020", segment_end="2021")
    reg.consume_oos_window("f", "w1")
    with pytest.raises(ValueError):
        reg.register_oos_window("f", "w2", oos_generation=1, segment_start="2020", segment_end="2021")


def test_selection_event_id_unique():
    reg = trial_registry.TrialRegistry()
    reg.freeze_family("f", "h", protocol_hash="ph", planned_trials=[("a", "c1"), ("b", "c2")])
    reg.record_trial("f", "a", config_hash="c1", result_payload={"x": 1})
    reg.record_trial("f", "b", config_hash="c2", result_payload={"x": 2})
    reg.record_selection("f", "a", True, selection_event_id="ev1")
    with pytest.raises(ValueError):
        reg.record_selection("f", "b", False, selection_event_id="ev1")


# -- PBO ----------------------------------------------------------------------

def test_pbo_tie_invariant_to_ordering():
    equal = [[0.01, 0.02, 0.01, 0.02, 0.01, 0.02, 0.01, 0.02],
             [0.01, 0.02, 0.01, 0.02, 0.01, 0.02, 0.01, 0.02],
             [0.01, 0.02, 0.01, 0.02, 0.01, 0.02, 0.01, 0.02]]
    a = pbo.cscv_probability_of_backtest_overfitting(equal, n_subsets=2)["pbo"]
    b = pbo.cscv_probability_of_backtest_overfitting(list(reversed(equal)), n_subsets=2)["pbo"]
    assert a == b


def test_pbo_default_full_enumeration():
    r = pbo.cscv_probability_of_backtest_overfitting(
        [[0.02 + ((t * 7 + c * 13) % 5 - 2) * 0.001 for t in range(16)] for c in range(3)],
        n_subsets=8)
    assert r["approx"] is False
    assert r["combinations_evaluated"] == r["total_combinations"] == 70


def test_pbo_approximation_is_explicit():
    r = pbo.cscv_probability_of_backtest_overfitting(
        [[0.02 + ((t * 7 + c * 13) % 5 - 2) * 0.001 for t in range(16)] for c in range(3)],
        n_subsets=8, max_combinations=10)
    assert r["approx"] is True
    assert r["sampling_method"] == "reservoir_subsample"
    assert r["approximation_limitations"]


# -- DSR ----------------------------------------------------------------------

def test_dsr_negative_denominator_unavailable():
    assert deflated_sharpe.psr(1.0, 0.0, 100, 3.0, 3.0)["status"] == "UNAVAILABLE"


# -- Reality Check ------------------------------------------------------------

def test_reality_check_block_length_lt_1_fails():
    rng = random.Random(0)
    alt = [[0.25 + rng.gauss(0, 1) for _ in range(100)] for _ in range(3)]
    assert bootstrap_reality_check.reality_check_pvalue(alt, n_bootstrap=100, mean_block_length=0.5)["status"] == "UNAVAILABLE"


def test_reality_check_confirmatory_requires_family():
    rng = random.Random(0)
    alt = [[0.25 + rng.gauss(0, 1) for _ in range(100)] for _ in range(3)]
    assert bootstrap_reality_check.reality_check_pvalue(alt, n_bootstrap=100, confirmatory=True)["status"] == "UNAVAILABLE"


# -- No-lookahead -------------------------------------------------------------

def test_feature_as_of_after_cutoff_is_lookahead():
    assert validate_no_lookahead(SampleTimingContract(
        feature_as_of="2026-08-15", decision_as_of="2026-08-14"))
    assert not validate_no_lookahead(SampleTimingContract(
        feature_as_of="2026-08-13", decision_as_of="2026-08-14"))


# -- Retrieval contract -------------------------------------------------------

def test_structured_research_query_validates():
    q = retrieval_contract.ResearchQuery(asset_class="equity", symbols=["SPY"])
    assert retrieval_contract.validate_research_query(q) == []
    assert retrieval_contract.validate_research_query(retrieval_contract.ResearchQuery()) != []
    assert hasattr(retrieval_contract, "ContradictionResult")


# -- Acceptance contract-only -------------------------------------------------

def test_contract_only_failure_blocks_r1():
    rep = acceptance.evaluate_profile(
        "R1_foundation",
        {"RGA-1": "PASS", "RGA-2": "PASS", "RGA-3": "PASS", "RGA-4": "PASS",
         "RGA-5": "PASS", "RGA-6": "PASS", "RGA-7": "PASS", "RGA-8": "PASS",
         "RGA-9": "PASS", "RGA-10": "PASS", "RGA-11": "FAIL", "RGA-12": "PASS",
         "RGA-13": "PASS", "RGA-14": "PASS", "RGA-15": "NOT_IN_SCOPE",
         "RGA-16": "NOT_IN_SCOPE"})
    assert rep["overall"] == GateState.FAIL.value
    assert "RGA-11" in rep["required_contract_fail"]


def test_r2_cannot_pass_before_it_exists():
    assert acceptance.run_acceptance("R2_mechanics")["overall"] == GateState.NOT_IMPLEMENTED.value
