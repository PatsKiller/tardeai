"""Research governance — registry + producer generated governed bundle (PR-R1).

Builds a fully valid, registry-generated Grade A/B empirical promotion bundle.

Unlike a "value factory", this module does NOT hand-author statistical outputs.
It assembles RAW canonical inputs (frozen trial family, raw p-values, raw Sharpe
vector/moments, raw PBO return matrix, raw Reality Check differential matrix, raw
robustness checklist items) and passes them to the method-specific governed
producers in `producers.py`. Those producers invoke the actual statistical
implementations and issue issuer-authenticated receipts. Expected result values
may be ASSERTED downstream, but are never inserted here as produced values.

Pure/in-memory, no provider/broker/DB calls.
"""
from __future__ import annotations

import math

from . import producers, trial_registry
from .models import FrozenDict, _stable_hash
from .receipts import PromotionEvidenceBundle
from .results import (
    MethodApplicability,
    MethodRequirement,
    RobustnessItem,
)

# Shared canonical identity for the whole research generation.
HYPOTHESIS_ID = "h1"
PROTOCOL_HASH = "ph"
TRIAL_FAMILY_ID = "f"
FAMILY_DEFINITION_HASH = "fdh"
DATASET_HASH = "d0"
CODE_SHA = "c0"
DATASET_ID = "ds"

# Raw trial family (ids, config hashes, backtest Sharpe per trial). This is the
# ACTUAL distribution DSR deflates against.
_TRIALS = (("t1", "c1", 0.5), ("t2", "c2", -0.1), ("t3", "c3", 0.0))


def _registry() -> trial_registry.TrialRegistry:
    reg = trial_registry.TrialRegistry()
    reg.freeze_family(
        TRIAL_FAMILY_ID, HYPOTHESIS_ID, protocol_hash=PROTOCOL_HASH,
        family_definition_hash=FAMILY_DEFINITION_HASH,
        planned_trials=[(tid, chash) for tid, chash, _ in _TRIALS],
        confirmatory=True,
    )
    for tid, chash, sharpe in _TRIALS:
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


def _pbo_matrix():
    """Raw configuration-return matrix (3 configs x 12 observations). Config 0 wins."""
    return (
        (0.05, -0.01, 0.04, -0.02, 0.05, -0.01, 0.04, -0.02, 0.05, -0.01, 0.04, -0.02),
        (0.01, 0.00, 0.01, -0.01, 0.01, 0.00, 0.01, -0.01, 0.01, 0.00, 0.01, -0.01),
        (-0.01, 0.00, -0.01, 0.00, -0.01, 0.00, -0.01, 0.00, -0.01, 0.00, -0.01, 0.00),
    )


def _rc_differentials():
    """Raw Reality Check differential matrix (3 rules x 100 observations)."""
    return (
        tuple(0.20 + 0.01 * math.sin(i) for i in range(100)),
        tuple(0.00 + 0.01 * math.sin(i + 1) for i in range(100)),
        tuple(-0.05 + 0.01 * math.sin(i + 2) for i in range(100)),
    )


def _robustness_items() -> FrozenDict:
    return FrozenDict({
        "sample_n": RobustnessItem("PASS", "n=100", "e1"),
        "benchmark": RobustnessItem("PASS", "SPX", "e2"),
        "subperiods": RobustnessItem("PASS", "5y", "e3"),
        "regimes": RobustnessItem("PASS", "bull/bear", "e4"),
        "costs": RobustnessItem("PASS", "bps=5", "e5"),
        "outlier_dependence": RobustnessItem("PASS", "winsorized", "e6"),
        "lookahead_control": RobustnessItem("PASS", "point-in-time", "e7"),
        "survivorship_control": RobustnessItem("PASS", "point-in-time universe", "e8"),
        "limitations": RobustnessItem("PASS", "stated", "e9"),
    })


def _identity_kwargs():
    return {
        "hypothesis_id": HYPOTHESIS_ID, "protocol_hash": PROTOCOL_HASH,
        "trial_family_id": TRIAL_FAMILY_ID, "family_definition_hash": FAMILY_DEFINITION_HASH,
        "dataset_hash": DATASET_HASH, "code_sha": CODE_SHA,
    }


def _governed_results() -> dict:
    """Run the five method-specific governed producers from raw inputs."""
    ident = _identity_kwargs()
    trial_ids = tuple(tid for tid, _, _ in _TRIALS)
    config_hashes = tuple(chash for _, chash, _ in _TRIALS)
    trial_sharpes = tuple(sharpe for _, _, sharpe in _TRIALS)

    multiple_testing = producers.run_governed_multiple_testing(
        producers.MultipleTestingInput(
            tested_hypothesis_id=HYPOTHESIS_ID, method="bonferroni", alpha=0.05,
            tested_trial_ids=trial_ids, tested_config_hashes=config_hashes,
            raw_pvalues=(0.001, 0.20, 0.50), focal_trial_id="t1",
            **ident,
        ))
    dsr = producers.run_governed_dsr(
        producers.DSRInput(
            observed_sharpe=0.5, n_observations=250, skewness=-0.2, kurtosis=4.0,
            trial_sharpes=trial_sharpes, n_trials=len(trial_sharpes),
            sharpe_frequency="PER_PERIOD", trial_sharpe_frequency="PER_PERIOD",
            return_frequency="DAILY", confirmatory=True,
            **ident,
        ))
    pbo_res = producers.run_governed_pbo(
        producers.PBOInput(
            config_returns=_pbo_matrix(), n_subsets=4, max_combinations=None, seed=0,
            performance="sharpe",
            **ident,
        ))
    rc = producers.run_governed_reality_check(
        producers.RealityCheckInput(
            family_id=TRIAL_FAMILY_ID, differentials=_rc_differentials(),
            n_bootstrap=1000, mean_block_length=5.0, seed=1, confirmatory=True,
            **ident,
        ))
    rob = producers.run_governed_robustness(
        producers.RobustnessInput(items=_robustness_items(), **ident))

    return {
        "multiple_testing": multiple_testing,
        "dsr": dsr,
        "pbo": pbo_res,
        "reality_check": rc,
        "robustness": rob,
    }


def make_governed_empirical_bundle() -> PromotionEvidenceBundle:
    """A registry-generated, producer-governed, fully valid Grade A/B bundle."""
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
