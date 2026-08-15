"""Research governance — registry-generated governed bundle fixtures (PR-R1).

Builds a fully valid, registry-generated Grade A/B empirical promotion bundle:
the frozen family, its trials, its OOS window, and the five governed statistical
results — all bound to ONE identity (hypothesis / protocol / trial family /
family definition / dataset / code).

This is the only sanctioned way to produce a ``PromotionEvidenceBundle`` that
satisfies the promotion gate: it goes through the trial registry (for the frozen
family, completeness, and OOS receipts) and through ``governed_result()`` (for
the governed statistical receipts). A caller cannot assemble the same bundle from
bare self-digested typed objects alone.

Pure/in-memory, no provider/broker/DB calls.
"""
from __future__ import annotations

from . import trial_registry
from .models import _stable_hash
from .receipts import PromotionEvidenceBundle, governed_result
from .results import (
    DSRResult,
    MethodApplicability,
    MethodRequirement,
    MultipleTestingResult,
    PBOResult,
    RealityCheckResult,
    RobustnessItem,
    RobustnessResult,
)

# Shared canonical identity for the whole research generation.
HYPOTHESIS_ID = "h1"
PROTOCOL_HASH = "ph"
TRIAL_FAMILY_ID = "f"
FAMILY_DEFINITION_HASH = "fdh"
DATASET_HASH = "d0"
CODE_SHA = "c0"
DATASET_ID = "ds"


def _registry() -> trial_registry.TrialRegistry:
    reg = trial_registry.TrialRegistry()
    reg.freeze_family(
        TRIAL_FAMILY_ID, HYPOTHESIS_ID, protocol_hash=PROTOCOL_HASH,
        family_definition_hash=FAMILY_DEFINITION_HASH,
        planned_trials=[("t1", "c1"), ("t2", "c2"), ("t3", "c3")],
        confirmatory=True,
    )
    for tid, chash, sharpe in (("t1", "c1", 0.5), ("t2", "c2", -0.1), ("t3", "c3", 0.0)):
        reg.record_trial(
            TRIAL_FAMILY_ID, tid, config_hash=chash,
            result_payload={"sharpe": sharpe}, code_sha=CODE_SHA, dataset_hash=DATASET_HASH,
            started_at="2026-01-01", completed_at="2026-01-02",
        )
    reg.register_oos_window(
        TRIAL_FAMILY_ID, "w1", oos_generation=1,
        segment_start="2027-01-01", segment_end="2027-12-31",
        dataset_id=DATASET_ID, dataset_hash=DATASET_HASH,
    )
    return reg


def _governed_results() -> dict:
    """Build the five governed statistical results bound to the shared identity."""
    input_artifact = {
        "hypothesis_id": HYPOTHESIS_ID, "protocol_hash": PROTOCOL_HASH,
        "trial_family_id": TRIAL_FAMILY_ID, "family_definition_hash": FAMILY_DEFINITION_HASH,
        "dataset_hash": DATASET_HASH, "code_sha": CODE_SHA,
    }

    mt = MultipleTestingResult(
        result_id="mt1", method="bonferroni", status="OK", alpha=0.05,
        family_id=TRIAL_FAMILY_ID, family_definition_hash=FAMILY_DEFINITION_HASH,
        trial_family_id=TRIAL_FAMILY_ID, tested_hypothesis_id=HYPOTHESIS_ID,
        raw_pvalue=0.001, adjusted_pvalue=0.003, rejected=True, complete_family=True,
        protocol_hash=PROTOCOL_HASH, hypothesis_id=HYPOTHESIS_ID,
        dataset_hash=DATASET_HASH, code_sha=CODE_SHA,
        tested_hypothesis_ids=("h1", "h2", "h3"),
        raw_pvalues=(0.001, 0.20, 0.50),
        family_input_digest=_stable_hash({"family": TRIAL_FAMILY_ID,
                                          "ids": ("h1", "h2", "h3"),
                                          "pvalues": (0.001, 0.20, 0.50)}),
    )
    dsr = DSRResult(
        result_id="dsr1", status="OK", observed_sharpe=1.2, n_observations=250,
        skewness=-0.2, kurtosis=4.0, n_trials=3, deflated_benchmark_sr=0.5,
        psr_z=2.5, probability_sr_exceeds_deflated_benchmark=0.99,
        sharpe_frequency="PER_PERIOD", trial_sharpe_frequency="PER_PERIOD",
        return_frequency="DAILY", confirmatory=True, protocol_hash=PROTOCOL_HASH,
        hypothesis_id=HYPOTHESIS_ID, trial_family_id=TRIAL_FAMILY_ID,
        family_definition_hash=FAMILY_DEFINITION_HASH,
        dataset_hash=DATASET_HASH, code_sha=CODE_SHA,
    )
    pbo_res = PBOResult(
        result_id="pbo1", status="OK", pbo=0.1, n_configs=3, n_observations=12,
        n_subsets=4, total_combinations=6, combinations_evaluated=6,
        sampling_fraction=1.0, approx=False, sampling_method="full_enumeration",
        protocol_hash=PROTOCOL_HASH, hypothesis_id=HYPOTHESIS_ID,
        trial_family_id=TRIAL_FAMILY_ID, family_definition_hash=FAMILY_DEFINITION_HASH,
        dataset_hash=DATASET_HASH, code_sha=CODE_SHA,
    )
    rc = RealityCheckResult(
        result_id="rc1", status="OK", bootstrap_pvalue=0.01, n_rules=3,
        n_observations=100, n_bootstrap=1000, bootstrap_method="stationary",
        mean_block_length=5.0, bootstrap_seed=1, alpha=0.05,
        pvalue_resolution=1 / 1001, protocol_hash=PROTOCOL_HASH, hypothesis_id=HYPOTHESIS_ID,
        trial_family_id=TRIAL_FAMILY_ID, family_definition_hash=FAMILY_DEFINITION_HASH,
        family_id=TRIAL_FAMILY_ID, dataset_hash=DATASET_HASH, code_sha=CODE_SHA,
    )
    rob = RobustnessResult(
        result_id="rob1",
        items={
            "sample_n": RobustnessItem("PASS", "n=100", "e1"),
            "benchmark": RobustnessItem("PASS", "SPX", "e2"),
            "subperiods": RobustnessItem("PASS", "5y", "e3"),
            "regimes": RobustnessItem("PASS", "bull/bear", "e4"),
            "costs": RobustnessItem("PASS", "bps=5", "e5"),
            "outlier_dependence": RobustnessItem("PASS", "winsorized", "e6"),
            "lookahead_control": RobustnessItem("PASS", "point-in-time", "e7"),
            "survivorship_control": RobustnessItem("PASS", "point-in-time universe", "e8"),
            "limitations": RobustnessItem("PASS", "stated", "e9"),
        },
        protocol_hash=PROTOCOL_HASH, hypothesis_id=HYPOTHESIS_ID,
        trial_family_id=TRIAL_FAMILY_ID, family_definition_hash=FAMILY_DEFINITION_HASH,
        dataset_hash=DATASET_HASH, code_sha=CODE_SHA,
    )
    return {
        "multiple_testing": governed_result(mt, input_artifact=input_artifact),
        "dsr": governed_result(dsr, input_artifact=input_artifact),
        "pbo": governed_result(pbo_res, input_artifact=input_artifact),
        "reality_check": governed_result(rc, input_artifact=input_artifact),
        "robustness": governed_result(rob, input_artifact=input_artifact),
    }


def make_governed_empirical_bundle() -> PromotionEvidenceBundle:
    """A registry-generated, fully valid Grade A/B empirical bundle."""
    reg = _registry()
    gr = _governed_results()
    family_receipt = reg.family_receipt(TRIAL_FAMILY_ID)
    completeness = reg.completeness_receipt(TRIAL_FAMILY_ID)
    oos = reg.oos_receipt(TRIAL_FAMILY_ID, "w1")
    app = MethodApplicability(
        dsr=MethodRequirement("REQUIRED"),
        pbo=MethodRequirement("REQUIRED"),
        reality_check=MethodRequirement("REQUIRED"),
        purged_cv=MethodRequirement("NOT_APPLICABLE", reason="non-overlapping fixed-period"),
    )
    bundle = PromotionEvidenceBundle(
        bundle_id="bundle-1",
        hypothesis_id=HYPOTHESIS_ID, protocol_hash=PROTOCOL_HASH,
        trial_family_id=TRIAL_FAMILY_ID, family_definition_hash=FAMILY_DEFINITION_HASH,
        dataset_hash=DATASET_HASH, code_sha=CODE_SHA,
        frozen_family_receipt=family_receipt,
        registry_completeness_receipt=completeness,
        oos_receipt=oos,
        method_applicability=app,
        multiple_testing=gr["multiple_testing"],
        dsr=gr["dsr"], pbo=gr["pbo"],
        reality_check=gr["reality_check"], robustness=gr["robustness"],
    )
    from dataclasses import replace
    return replace(bundle, bundle_digest=bundle.compute_digest())


def make_typed_empirical_context() -> dict:
    """The fully valid A-grade empirical promotion context (bundle-backed).

    Returns the top-level promotion context (source/claim/scope/grade/influence +
    in-sample reproduction) with the governed bundle under ``evidence_bundle``.
    """
    bundle = make_governed_empirical_bundle()
    return {
        "source_id": "s", "claim": "c", "page_or_section": "p", "scope": "us",
        "evidence_type": "EMPIRICAL_STRATEGY",
        "in_sample_metric": 1.0, "in_sample_threshold": 0.0,
        "evidence_bundle": bundle,
        "evidence_grade": "A", "influence_class": "PORTFOLIO_CONSTRUCTION",
    }
