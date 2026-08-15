"""Research governance — R1 LAST-MILE integrity adversarial suite (PR-R1 v3).

Maps 1:1 to the remaining holes from the v3.0 last-mile integrity review:
deep protocol immutability, DSR failure propagation, verifiable external-artifact
lineage, OOS dataset identity, typed/digested statistical evidence, numeric
self-consistency, method applicability, robustness NA matrix, computed policy
freshness, strict timestamp parsing, PBO edge cases, source-catalog provenance,
and contradiction evidence provenance.

Fail-closed is the product. No side effects: pure functions + in-memory stores.
"""
from __future__ import annotations

import math
import sys
from dataclasses import replace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from scripts.lib.research_governance import (  # noqa: E402
    bootstrap_reality_check,
    deflated_sharpe,
    pbo,
    promotion_gate,
    retrieval_contract,
    source_catalog,
    trial_registry,
)
from scripts.lib.research_governance.enums import GateState  # noqa: E402
from scripts.lib.research_governance.models import (  # noqa: E402
    FakeArtifactVerifier,
    ResearchEvidence,
    ResearchHypothesis,
    SampleTimingContract,
    verify_protocol_integrity,
    validate_no_lookahead,
)
from scripts.lib.research_governance.results import (  # noqa: E402
    MethodApplicability,
    MethodRequirement,
    MultipleTestingResult,
    RealityCheckResult,
    RobustnessItem,
    RobustnessResult,
    finalize,
    make_typed_empirical_context,
)
from scripts.lib.research_governance.receipts import governed_result  # noqa: E402
from scripts.lib.research_governance.governed_bundle import (  # noqa: E402
    make_governed_empirical_bundle,
)


_IDENTITY_INPUT = {
    "hypothesis_id": "h1", "protocol_hash": "ph", "trial_family_id": "f",
    "family_definition_hash": "fdh", "dataset_hash": "d0", "code_sha": "c0",
}


def _bundle_with(name, mutated_result):
    """Re-govern a mutated typed result and swap it into a fresh canonical bundle."""
    bundle = make_governed_empirical_bundle()
    mutated = finalize(mutated_result)
    child = governed_result(mutated, input_artifact=_IDENTITY_INPUT)
    b2 = replace(bundle, **{name: child})
    b2 = replace(b2, bundle_digest=b2.compute_digest())
    return dict(make_typed_empirical_context(), evidence_bundle=b2)


# ---------------------------------------------------------------------------
# P0-1 Deep immutability
# ---------------------------------------------------------------------------

def test_frozen_hypothesis_nested_variant_cannot_mutate():
    h = ResearchHypothesis(
        hypothesis_id="h1",
        planned_variants=[{"threshold": 5, "window": [1, 2]}],
        source_claim_ids=["s1"],
    )
    f = h.freeze()
    old = f.protocol_hash
    with pytest.raises(TypeError):
        f.planned_variants[0]["threshold"] = 999  # FrozenDict is immutable
    assert f.protocol_hash == old
    assert f.planned_variants[0]["threshold"] == 5


def test_frozen_hypothesis_source_mutation_does_not_change_frozen():
    h = ResearchHypothesis(hypothesis_id="h1", source_claim_ids=["s1"])
    f = h.freeze()
    old = f.protocol_hash
    h.source_claim_ids.append("s2")
    assert f.source_claim_ids == ("s1",)
    assert f.protocol_hash == old


def test_protocol_integrity_detects_tampering():
    h = ResearchHypothesis(hypothesis_id="h1", planned_variants=[{"threshold": 5}])
    f = h.freeze()
    assert verify_protocol_integrity(f) is True
    tampered = replace(f, planned_variants=tuple())
    assert verify_protocol_integrity(tampered) is False


# ---------------------------------------------------------------------------
# P0-2 DSR wrapper
# ---------------------------------------------------------------------------

def test_deflated_sharpe_propagates_psr_failure():
    trials = [0.2, 0.4, 0.1, 0.5, 0.3, 0.35, 0.25, 0.45, 0.15, 0.3]
    r = deflated_sharpe.deflated_sharpe(1.0, 100, 3.0, 3.0, trials, 10)
    assert r["status"] == "UNAVAILABLE"
    assert r["psr_z"] is None


def test_confirmatory_dsr_requires_frequency_convention():
    trials = [0.2, 0.4, 0.1, 0.5, 0.3, 0.35, 0.25, 0.45, 0.15, 0.3]
    assert deflated_sharpe.deflated_sharpe(1.5, 250, -0.2, 4.0, trials, 10,
                                           confirmatory=True)["status"] == "UNAVAILABLE"
    ok = deflated_sharpe.deflated_sharpe(1.5, 250, -0.2, 4.0, trials, 10,
                                         sharpe_frequency="PER_PERIOD",
                                         trial_sharpe_frequency="PER_PERIOD",
                                         return_frequency="DAILY", confirmatory=True)
    assert ok["status"] == "OK"


# ---------------------------------------------------------------------------
# P0-3 Trial lineage
# ---------------------------------------------------------------------------

def test_external_artifact_mismatch_not_verified():
    verifier = FakeArtifactVerifier(known={"ref1": {"size": 8, "sha256": "a" * 64}})
    reg = trial_registry.TrialRegistry(verifier=verifier)
    reg.freeze_family("f", "h", protocol_hash="ph", family_definition_hash="fdh",
                      planned_trials=[("a", "c1")], confirmatory=True)
    with pytest.raises(ValueError):
        reg.record_trial("f", "a", config_hash="c1", result_hash="b" * 64,
                         result_artifact_ref="ref1", result_artifact_size=8,
                         code_sha="c0", dataset_hash="d0",
                         started_at="2026-01-01", completed_at="2026-01-02")


def test_external_artifact_provenance_retained():
    verifier = FakeArtifactVerifier(known={"ref1": {"size": 8, "sha256": "a" * 64}})
    reg = trial_registry.TrialRegistry(verifier=verifier)
    reg.freeze_family("f", "h", protocol_hash="ph", family_definition_hash="fdh",
                      planned_trials=[("a", "c1")], confirmatory=True)
    rec = reg.record_trial("f", "a", config_hash="c1", result_hash="a" * 64,
                           result_artifact_ref="ref1", result_artifact_size=8,
                           code_sha="c0", dataset_hash="d0",
                           started_at="2026-01-01", completed_at="2026-01-02")
    assert rec.result_artifact_ref == "ref1"
    assert rec.result_artifact_size == 8
    assert rec.hash_algorithm == "sha256"
    assert rec.result_verification_status == "VERIFIED"


def test_confirmatory_completed_missing_code_sha_rejected():
    reg = trial_registry.TrialRegistry()
    reg.freeze_family("f", "h", protocol_hash="ph", family_definition_hash="fdh",
                      planned_trials=[("a", "c1")], confirmatory=True)
    with pytest.raises(ValueError):
        reg.record_trial("f", "a", config_hash="c1", result_payload={"s": 0.5},
                         dataset_hash="d0", started_at="2026-01-01",
                         completed_at="2026-01-02")


def test_confirmatory_completed_missing_dataset_hash_rejected():
    reg = trial_registry.TrialRegistry()
    reg.freeze_family("f", "h", protocol_hash="ph", family_definition_hash="fdh",
                      planned_trials=[("a", "c1")], confirmatory=True)
    with pytest.raises(ValueError):
        reg.record_trial("f", "a", config_hash="c1", result_payload={"s": 0.5},
                         code_sha="c0", started_at="2026-01-01",
                         completed_at="2026-01-02")


def test_terminal_disposition_requires_reason():
    reg = trial_registry.TrialRegistry()
    reg.freeze_family("f", "h", protocol_hash="ph", planned_trials=[("a", "c1")])
    for status in ("INVALID", "FAILED", "CANCELED_WITH_REASON"):
        with pytest.raises(ValueError):
            reg.record_trial("f", "a", config_hash="c1", result_payload={"s": 0.5},
                             terminal_status=status)


def test_selection_requires_recorded_trial():
    reg = trial_registry.TrialRegistry()
    reg.freeze_family("f", "h", protocol_hash="ph", planned_trials=[("a", "c1")])
    with pytest.raises(ValueError):
        reg.record_selection("f", "a", True)


# ---------------------------------------------------------------------------
# P0-4 OOS dataset identity
# ---------------------------------------------------------------------------

def test_same_oos_id_changed_dataset_rejected():
    reg = trial_registry.TrialRegistry()
    reg.freeze_family("f", "h", protocol_hash="ph", planned_trials=[("a", "c1")])
    reg.register_oos_window("f", "w", oos_generation=1, segment_start="2020",
                            dataset_id="ds", dataset_hash="dh1")
    with pytest.raises(ValueError):
        reg.register_oos_window("f", "w", oos_generation=1, segment_start="2020",
                                dataset_id="ds", dataset_hash="dh2")


def test_consumed_segment_changed_dataset_not_fresh():
    reg = trial_registry.TrialRegistry()
    reg.freeze_family("f", "h", protocol_hash="ph", planned_trials=[("a", "c1")])
    reg.register_oos_window("f", "w1", oos_generation=1, segment_start="2020",
                            dataset_id="ds", dataset_hash="dh1")
    reg.consume_oos_window("f", "w1")
    rerun = reg.register_oos_window("f", "w2", oos_generation=1, segment_start="2020",
                                    dataset_id="ds", dataset_hash="dh2")
    assert rerun.rerun_classification == "CORRECTED_DATA_RERUN"
    assert reg.oos_is_untouched("f", "w2") is False


# ---------------------------------------------------------------------------
# P0-5 / P0-6 typed + numeric statistical evidence
# ---------------------------------------------------------------------------

def test_arbitrary_dict_statistics_rejected():
    ctx = dict(make_typed_empirical_context(), evidence_bundle=None, multiple_testing={
        "status": "OK", "method": "bonferroni", "alpha": 0.05,
        "family_id": "f", "family_definition_hash": "fdh", "trial_family_id": "f",
        "tested_hypothesis_id": "h1", "raw_pvalue": 0.001, "adjusted_pvalue": 0.003,
        "rejected": True, "complete_family": True})
    assert promotion_gate.run_promotion_gate(ctx)["overall"] == GateState.FAIL.value


def test_mt_rejection_inconsistency_fails():
    bundle = make_governed_empirical_bundle()
    mt = replace(bundle.multiple_testing.result, adjusted_pvalue=0.90, rejected=True)
    r = promotion_gate.run_promotion_gate(_bundle_with("multiple_testing", mt))
    assert r["overall"] == GateState.FAIL.value
    assert "rejection inconsistency" in r["gate_results"]["RG-6"]["reason"]


def test_mt_alpha_out_of_range_fails():
    bundle = make_governed_empirical_bundle()
    mt = replace(bundle.multiple_testing.result, alpha=2.0)
    assert promotion_gate.run_promotion_gate(
        _bundle_with("multiple_testing", mt))["overall"] == GateState.FAIL.value


def test_mt_bh_fdr_rejected_for_grade_ab():
    bundle = make_governed_empirical_bundle()
    mt = replace(bundle.multiple_testing.result, method="bh_fdr")
    assert promotion_gate.run_promotion_gate(
        _bundle_with("multiple_testing", mt))["overall"] == GateState.FAIL.value


def test_rc_negative_pvalue_fails():
    bundle = make_governed_empirical_bundle()
    rc = replace(bundle.reality_check.result, bootstrap_pvalue=-0.1)
    assert promotion_gate.run_promotion_gate(
        _bundle_with("reality_check", rc))["overall"] == GateState.FAIL.value


def test_rc_alpha_out_of_range_fails():
    bundle = make_governed_empirical_bundle()
    rc = replace(bundle.reality_check.result, alpha=2.0)
    assert promotion_gate.run_promotion_gate(
        _bundle_with("reality_check", rc))["overall"] == GateState.FAIL.value


def test_rc_bootstrap_too_coarse_fails():
    bundle = make_governed_empirical_bundle()
    rc = replace(bundle.reality_check.result, n_bootstrap=9, pvalue_resolution=1 / 10)
    assert promotion_gate.run_promotion_gate(
        _bundle_with("reality_check", rc))["overall"] == GateState.FAIL.value


def test_in_sample_threshold_missing_fails():
    ctx = dict(make_typed_empirical_context(), in_sample_threshold=None)
    assert promotion_gate.run_promotion_gate(ctx)["overall"] == GateState.FAIL.value


def test_in_sample_metric_nan_fails():
    ctx = dict(make_typed_empirical_context(), in_sample_metric=float("nan"))
    assert promotion_gate.run_promotion_gate(ctx)["overall"] == GateState.FAIL.value


# ---------------------------------------------------------------------------
# P0-7 Method applicability
# ---------------------------------------------------------------------------

def test_dsr_required_absent_fails():
    ctx = make_typed_empirical_context()
    b = ctx["evidence_bundle"]
    b2 = replace(b, dsr=None)
    b2 = replace(b2, bundle_digest=b2.compute_digest())
    assert promotion_gate.run_promotion_gate(
        dict(ctx, evidence_bundle=b2))["overall"] == GateState.FAIL.value


def test_pbo_required_absent_fails():
    ctx = make_typed_empirical_context()
    b = ctx["evidence_bundle"]
    b2 = replace(b, pbo=None)
    b2 = replace(b2, bundle_digest=b2.compute_digest())
    assert promotion_gate.run_promotion_gate(
        dict(ctx, evidence_bundle=b2))["overall"] == GateState.FAIL.value


def test_single_fixed_strategy_pbo_not_applicable_allowed():
    ctx = make_typed_empirical_context()
    app = MethodApplicability(
        dsr=MethodRequirement("NOT_APPLICABLE", "single fixed strategy"),
        pbo=MethodRequirement("NOT_APPLICABLE", "one fixed preregistered strategy; no configuration selection"),
        reality_check=MethodRequirement("REQUIRED"),
        purged_cv=MethodRequirement("NOT_APPLICABLE", "fixed-period"),
    )
    b = ctx["evidence_bundle"]
    b2 = replace(b, method_applicability=app, dsr=None, pbo=None)
    b2 = replace(b2, bundle_digest=b2.compute_digest())
    assert promotion_gate.run_promotion_gate(
        dict(ctx, evidence_bundle=b2))["overall"] == GateState.PASS.value


# ---------------------------------------------------------------------------
# P0-8 Robustness NA matrix
# ---------------------------------------------------------------------------

def _ctx_with_robustness(**overrides):
    ctx = make_typed_empirical_context()
    b = ctx["evidence_bundle"]
    items = dict(b.robustness.result.items)
    for k, v in overrides.items():
        items[k] = v
    new_rob = RobustnessResult(
        result_id="rob2", items=items, protocol_hash="ph", hypothesis_id="h1",
        trial_family_id="f", family_definition_hash="fdh",
        dataset_hash="d0", code_sha="c0")
    rob_child = governed_result(new_rob, input_artifact=_IDENTITY_INPUT)
    b2 = replace(b, robustness=rob_child)
    b2 = replace(b2, bundle_digest=b2.compute_digest())
    return dict(ctx, evidence_bundle=b2)


def test_robustness_sample_n_na_blocked():
    ctx = _ctx_with_robustness(sample_n=RobustnessItem("NOT_APPLICABLE", "n/a", ""))
    assert promotion_gate.run_promotion_gate(ctx)["overall"] == GateState.FAIL.value


def test_robustness_lookahead_control_na_blocked():
    ctx = _ctx_with_robustness(lookahead_control=RobustnessItem("NOT_APPLICABLE", "n/a", ""))
    assert promotion_gate.run_promotion_gate(ctx)["overall"] == GateState.FAIL.value


# ---------------------------------------------------------------------------
# P0-9 Policy freshness computed
# ---------------------------------------------------------------------------

def test_policy_overdue_reverify_fails():
    ctx = {
        "source_id": "s", "claim": "c", "page_or_section": "p", "scope": "us",
        "evidence_type": "POLICY_OR_REGULATORY", "evidence_grade": "B",
        "influence_class": "RISK_VETO", "authoritative_source": "IRS",
        "effective_date": "2026-01-01", "jurisdiction": "US",
        "verified_at": "2019-01-01", "current_as_of": "2026-08-01",
        "next_reverify_at": "2020-01-01",
    }
    assert promotion_gate.run_promotion_gate(ctx)["overall"] == GateState.FAIL.value


# ---------------------------------------------------------------------------
# P1-1 Timestamp parsing
# ---------------------------------------------------------------------------

def test_malformed_timestamp_fails_closed():
    assert validate_no_lookahead(SampleTimingContract(
        feature_as_of="2026-8-4", decision_as_of="2026-08-14"))


def test_naive_timestamp_fails_closed():
    assert validate_no_lookahead(SampleTimingContract(
        feature_as_of="2026-08-14T10:00:00", decision_as_of="2026-08-14T13:00:00Z"))


def test_timezone_normalization_correct():
    # 10:00-04:00 == 14:00Z is AFTER 13:00Z => lookahead.
    assert validate_no_lookahead(SampleTimingContract(
        feature_as_of="2026-08-14T10:00:00-04:00",
        decision_as_of="2026-08-14T13:00:00Z"))
    # 10:00-04:00 == 14:00Z is BEFORE 15:00Z => clean.
    assert not validate_no_lookahead(SampleTimingContract(
        feature_as_of="2026-08-14T10:00:00-04:00",
        decision_as_of="2026-08-14T15:00:00Z"))


# ---------------------------------------------------------------------------
# P1-2 PBO edge cases
# ---------------------------------------------------------------------------

def test_pbo_zero_variance_not_silent_zero():
    zero = [[0.05, 0.05, 0.05, 0.05], [0.05, 0.05, 0.05, 0.05]]
    assert pbo.cscv_probability_of_backtest_overfitting(zero, n_subsets=2)["status"] == "UNAVAILABLE"


def test_pbo_n_subsets_zero_unavailable():
    m = [[0.01, -0.01] * 8 for _ in range(3)]
    assert pbo.cscv_probability_of_backtest_overfitting(m, n_subsets=0)["status"] == "UNAVAILABLE"


def test_pbo_huge_full_enumeration_infeasible():
    big = [[0.01 if t % 2 == 0 else -0.01 for t in range(30)] for _ in range(2)]
    r = pbo.cscv_probability_of_backtest_overfitting(big, n_subsets=30)
    assert r["status"] == "COMPUTATION_INFEASIBLE"


# ---------------------------------------------------------------------------
# P1-4 Source catalog provenance
# ---------------------------------------------------------------------------

def test_source_full_text_status_enum_validated():
    # The actual catalog must not contain an unknown full_text_status.
    rep = source_catalog.manifest_report()
    assert rep["provenance_coherent"]
    for s in source_catalog.load_sources():
        assert s["full_text_status"] in source_catalog.FULL_TEXT_STATUSES


def test_cpcv_citation_is_primary_not_phantom():
    cpcv = [s for s in source_catalog.load_sources()
            if s["source_id"] == "lopez_de_prado_cpcv_2017"][0]
    assert cpcv["title"] != "A Practical Approach to Backtest Overfitting"
    assert cpcv.get("doi_or_isbn")


# ---------------------------------------------------------------------------
# P1-5 / P1-6 Contradiction provenance + influence matrix
# ---------------------------------------------------------------------------

def test_contradiction_result_preserves_evidence():
    ev = ResearchEvidence(fact_id="f1", fact="counter", source_id="s1")
    cr = retrieval_contract.ContradictionResult(fact_id="f1", counterevidence=[ev])
    assert isinstance(cr.counterevidence[0], ResearchEvidence)
    assert cr.counterevidence[0].fact_id == "f1"


def test_seasonality_cannot_risk_veto():
    ctx = dict(make_typed_empirical_context(), evidence_type="SEASONALITY",
               influence_class="RISK_VETO")
    assert promotion_gate.run_promotion_gate(ctx)["overall"] == GateState.FAIL.value
