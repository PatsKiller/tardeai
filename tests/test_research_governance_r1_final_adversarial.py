"""Research governance — R1 FINAL merge-blocker adversarial suite (v4).

This is the "one good bundle, alter ONE thing, assert the exact gate/reason"
suite required by the R1 final merge-blocker closure prompt. It targets the
governance bypasses the earlier 202-test suite did NOT exercise at the right
layer:

  * a caller-built self-digested typed result is NOT evidence provenance;
  * a governed receipt binds output/input/code/family identity;
  * the canonical bundle enforces EXACT cross-result identity (6 fields);
  * the frozen family definition is deeply immutable;
  * OOS economic identity excludes generation;
  * multiple-testing is recomputable from the complete (un-omittable) family;
  * DSR/PBO/RC numeric self-consistency + boundary conventions;
  * full-text provenance all-fields-required;
  * retrieval freshness is enforced (future/stale/missing date);
  * deep-frozen nested results; chronological CV ordering; scope-guard base.

Pure/in-memory. No provider/broker/DB calls. Every negative case starts from a
fully valid registry-generated bundle and alters exactly one field.
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
    cv,
    deflated_sharpe,
    pbo,
    promotion_gate,
    retrieval_contract,
    source_catalog,
    trial_registry,
)
from scripts.lib.research_governance.enums import (  # noqa: E402
    EvidenceGrade,
    EvidenceType,
    GateState,
    InfluenceClass,
    ResearchStatus,
)
from scripts.lib.research_governance.governed_bundle import (  # noqa: E402
    make_governed_empirical_bundle,
    make_typed_empirical_context,
)
from scripts.lib.research_governance.models import ResearchEvidence  # noqa: E402
from scripts.lib.research_governance.receipts import (  # noqa: E402
    GovernedResult,
    governed_result,
)
from scripts.lib.research_governance.results import (  # noqa: E402
    MethodApplicability,
    MethodRequirement,
    finalize,
)


_IDENTITY = {
    "hypothesis_id": "h1", "protocol_hash": "ph", "trial_family_id": "f",
    "family_definition_hash": "fdh", "dataset_hash": "d0", "code_sha": "c0",
}

_CHILD_NAMES = ("multiple_testing", "dsr", "pbo", "reality_check", "robustness")
_IDENTITY_FIELDS = ("hypothesis_id", "protocol_hash", "trial_family_id",
                    "family_definition_hash", "dataset_hash", "code_sha")


def _bundle_with_child(name, value):
    """Replace one bundle child and recompute the bundle digest."""
    ctx = make_typed_empirical_context()
    b = ctx["evidence_bundle"]
    b2 = replace(b, **{name: value})
    b2 = replace(b2, bundle_digest=b2.compute_digest())
    return dict(ctx, evidence_bundle=b2)


# ---------------------------------------------------------------------------
# P0-1 — caller-built typed result is not provenance
# ---------------------------------------------------------------------------

def test_caller_built_typed_result_rejected_all_five():
    b = make_governed_empirical_bundle()
    for name in _CHILD_NAMES:
        bare = getattr(b, name).result  # self-digested typed result, NOT governed
        assert bare.verify(), f"{name} self-digest should verify (only self-consistency)"
        r = promotion_gate.run_promotion_gate(_bundle_with_child(name, bare))
        assert r["overall"] == GateState.FAIL.value, f"{name} bare typed must fail"
        assert "must be a governed result" in r["evidence_bundle"], f"{name} reason"


# ---------------------------------------------------------------------------
# P0-1 — governed receipt hash / input / code / family mismatches
# ---------------------------------------------------------------------------

def test_receipt_output_result_hash_mismatch_fails():
    b = make_governed_empirical_bundle()
    gr = b.dsr
    bad_receipt = replace(gr.receipt, result_payload_hash="0" * 64)
    bad_receipt = replace(bad_receipt, receipt_digest=bad_receipt.compute_digest())
    bad_gr = GovernedResult(receipt=bad_receipt, result=gr.result)
    r = promotion_gate.run_promotion_gate(_bundle_with_child("dsr", bad_gr))
    assert r["overall"] == GateState.FAIL.value
    assert "does not bind its result digest" in r["evidence_bundle"]


def test_receipt_input_hash_mismatch_fails():
    b = make_governed_empirical_bundle()
    res = b.dsr.result
    child = governed_result(res, input_artifact=dict(_IDENTITY, dataset_hash="dX"))
    r = promotion_gate.run_promotion_gate(_bundle_with_child("dsr", child))
    assert r["overall"] == GateState.FAIL.value
    assert "input_artifact_hash" in r["evidence_bundle"]


@pytest.mark.parametrize("field", ["dataset_hash", "code_sha", "family_definition_hash"])
def test_receipt_identity_field_mismatch_fails(field):
    b = make_governed_empirical_bundle()
    res = replace(b.dsr.result, **{field: "zzz"})
    child = governed_result(finalize(res), input_artifact=dict(_IDENTITY, **{field: "zzz"}))
    r = promotion_gate.run_promotion_gate(_bundle_with_child("dsr", child))
    assert r["overall"] == GateState.FAIL.value
    assert f"{field} mismatch" in r["evidence_bundle"]


# ---------------------------------------------------------------------------
# P0-2 / P0-3 — canonical bundle + exact cross-result identity
# ---------------------------------------------------------------------------

def test_applicability_mutation_changes_bundle_digest():
    b = make_governed_empirical_bundle()
    base_digest = b.bundle_digest
    mutated = MethodApplicability(
        dsr=MethodRequirement("REQUIRED"), pbo=MethodRequirement("REQUIRED"),
        reality_check=MethodRequirement("REQUIRED"),
        purged_cv=MethodRequirement("NOT_APPLICABLE", "changed reason"))
    b2 = replace(b, method_applicability=mutated)
    b2 = replace(b2, bundle_digest=b2.compute_digest())
    assert b2.bundle_digest != base_digest
    assert b2.verify() is True


def test_cross_result_identity_exact_for_all_children():
    b = make_governed_empirical_bundle()
    for name in _CHILD_NAMES:
        base = getattr(b, name).result
        for field in _IDENTITY_FIELDS:
            res = replace(base, **{field: "zzz"})
            child = governed_result(finalize(res),
                                    input_artifact=dict(_IDENTITY, **{field: "zzz"}))
            r = promotion_gate.run_promotion_gate(_bundle_with_child(name, child))
            assert r["overall"] == GateState.FAIL.value, f"{name}.{field} must fail"
            assert f"{field} mismatch" in r["evidence_bundle"], f"{name}.{field} reason"


# ---------------------------------------------------------------------------
# P0-4 / P0-5 — frozen family immutability + no caller boolean trust
# ---------------------------------------------------------------------------

def test_mutable_family_definition_attack():
    reg = trial_registry.TrialRegistry()
    planned = [("t1", "c1"), ("t2", "c2")]
    fr = reg.freeze_family("f", "h", protocol_hash="ph", family_definition_hash="fdh",
                           planned_trials=planned, confirmatory=True)
    planned.append(("t3", "c3"))
    assert len(fr.planned_trial_ids) == 2
    with pytest.raises(TypeError):
        fr.planned_trial_ids[0] = "X"
    with pytest.raises(TypeError):
        fr.planned_config_hashes["t1"] = "X"
    with pytest.raises(Exception):
        fr.protocol_hash = "evil"
    with pytest.raises(Exception):
        fr.confirmatory = False
    assert fr.verify()


def test_family_frozen_raw_boolean_rejected():
    ctx = dict(make_typed_empirical_context(), evidence_bundle=None, family_frozen=True)
    r = promotion_gate.run_promotion_gate(ctx)
    assert r["overall"] == GateState.FAIL.value
    assert r["gate_results"]["RG-2"]["state"] == GateState.FAIL.value
    assert "governed bundle" in r["gate_results"]["RG-2"]["reason"]


# ---------------------------------------------------------------------------
# P0-6 / P0-7 — OOS receipt + generation excluded from economic identity
# ---------------------------------------------------------------------------

def test_oos_raw_boolean_rejected():
    ctx = dict(make_typed_empirical_context(), evidence_bundle=None,
               oos_supported=True, oos_untouched=True)
    r = promotion_gate.run_promotion_gate(ctx)
    assert r["overall"] == GateState.FAIL.value
    assert r["gate_results"]["RG-5"]["state"] == GateState.FAIL.value
    assert "OOS receipt" in r["gate_results"]["RG-5"]["reason"]


def test_same_segment_new_generation_not_fresh():
    reg = trial_registry.TrialRegistry()
    reg.freeze_family("f", "h", protocol_hash="ph", planned_trials=[("a", "c1")])
    reg.register_oos_window("f", "w1", oos_generation=1, segment_start="2020",
                            segment_end="2021", dataset_id="ds", dataset_hash="dh1")
    reg.consume_oos_window("f", "w1")
    with pytest.raises(ValueError):
        reg.register_oos_window("f", "w2", oos_generation=2, segment_start="2020",
                                segment_end="2021", dataset_id="ds", dataset_hash="dh1")
    rerun = reg.register_oos_window("f", "w3", oos_generation=2, segment_start="2020",
                                    segment_end="2021", dataset_id="ds", dataset_hash="dh2")
    assert rerun.rerun_classification == "CORRECTED_DATA_RERUN"
    assert not reg.oos_is_untouched("f", "w3")


# ---------------------------------------------------------------------------
# P0-8 — multiple testing recomputable from complete (un-omittable) family
# ---------------------------------------------------------------------------

def test_complete_family_omission_fails():
    b = make_governed_empirical_bundle()
    mt = b.multiple_testing.result
    # Drop the losing trial (h3) but keep complete_family=True without re-binding.
    shrunk = replace(mt, tested_hypothesis_ids=("h1", "h2"), raw_pvalues=(0.001, 0.20))
    assert any("family_input_digest" in p for p in shrunk.validate())
    child = governed_result(finalize(shrunk), input_artifact=_IDENTITY)
    r = promotion_gate.run_promotion_gate(_bundle_with_child("multiple_testing", child))
    assert r["overall"] == GateState.FAIL.value
    assert "family_input_digest" in r["evidence_bundle"]


# ---------------------------------------------------------------------------
# P0-9 / P0-10 / P1-1 — numeric self-consistency + boundary conventions
# ---------------------------------------------------------------------------

def test_dsr_annualization_golden_equivalence():
    trials = [0.2, 0.4, 0.1, 0.5, 0.3, 0.35, 0.25, 0.45, 0.15, 0.3]
    ppy = 252
    pp = deflated_sharpe.deflated_sharpe(
        0.075, 250, -0.2, 4.0, trials, 10,
        sharpe_frequency="PER_PERIOD", trial_sharpe_frequency="PER_PERIOD",
        return_frequency="DAILY", confirmatory=True)
    ann = deflated_sharpe.deflated_sharpe(
        0.075 * math.sqrt(ppy), 250, -0.2, 4.0, [t * math.sqrt(ppy) for t in trials], 10,
        sharpe_frequency="ANNUALIZED", trial_sharpe_frequency="ANNUALIZED",
        return_frequency="DAILY", confirmatory=True, periods_per_year=ppy)
    assert pp["status"] == "OK" and ann["status"] == "OK"
    assert abs(pp["deflated_benchmark_sr"] - ann["deflated_benchmark_sr"]) < 1e-9
    assert abs(pp["psr_z"] - ann["psr_z"]) < 1e-9
    # Ambiguous / mixed conventions fail closed.
    assert deflated_sharpe.deflated_sharpe(
        0.075, 250, -0.2, 4.0, trials, 10,
        sharpe_frequency="ANNUALIZED", trial_sharpe_frequency="PER_PERIOD",
        return_frequency="DAILY", confirmatory=True, periods_per_year=ppy)["status"] == "UNAVAILABLE"


def test_pbo_lambda_zero_boundary():
    identical = [[0.01, -0.02, 0.03, -0.01, 0.02, -0.03, 0.01, -0.02]] * 3
    r = pbo.cscv_probability_of_backtest_overfitting(identical, n_subsets=2)
    assert r["status"] == "OK"
    assert r["pbo"] == 0.0
    assert r["lambda_zero_policy"] == "counts_as_not_overfit"


def test_pbo_combination_sampling_tie_consistency():
    b = make_governed_empirical_bundle()
    p = b.pbo.result
    assert p.validate() == []
    assert any("total_combinations" in m for m in replace(p, total_combinations=999).validate())
    assert any("sampling_fraction" in m for m in replace(p, sampling_fraction=0.5).validate())
    assert any("tie_fraction" in m for m in replace(p, tie_fraction=0.5).validate())


def test_reality_check_resolution_recomputation():
    b = make_governed_empirical_bundle()
    rc = b.reality_check.result
    assert abs(rc.pvalue_resolution - 1.0 / (rc.n_bootstrap + 1)) < 1e-12
    assert any("pvalue_resolution" in m for m in replace(rc, pvalue_resolution=1 / 100).validate())


# ---------------------------------------------------------------------------
# P1-3 — full-text provenance all-fields-required (one test per missing field)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("missing", ["source_location", "source_hash", "verified_at", "license_class"])
def test_full_text_missing_field_fails(missing):
    src = {
        "source_id": "fake", "full_text_status": "AVAILABLE_LICENSED",
        "claim_status": "SOURCE_CLAIM_COMPLETE",
        "source_location": "/tmp/x", "source_hash": "a" * 64,
        "verified_at": "2026-01-01", "license_class": "LICENSED",
    }
    if missing == "license_class":
        src["license_class"] = "UNKNOWN"
    else:
        src[missing] = ""
    assert source_catalog.validate_source_provenance(src), f"missing {missing} must fail"


# ---------------------------------------------------------------------------
# P1-4 — retrieval freshness enforced (future / stale / missing date)
# ---------------------------------------------------------------------------

def _evidence(source_date):
    return ResearchEvidence(
        fact_id="f", fact="fact", source_id="s",
        evidence_type=EvidenceType.SEASONALITY,
        research_status=ResearchStatus.OOS_SUPPORTED,
        evidence_grade=EvidenceGrade.D,
        influence_class=InfluenceClass.CONTEXT_MODIFIER,
        source_date=source_date,
    )


def test_retrieval_freshness_enforced():
    q = retrieval_contract.ResearchQuery(asset_class="equity", as_of="2026-08-14",
                                         max_source_age_days=30)
    assert retrieval_contract.validate_evidence_for_query(_evidence("2026-09-01"), q)
    assert retrieval_contract.validate_evidence_for_query(_evidence("2020-01-01"), q)
    assert retrieval_contract.validate_evidence_for_query(_evidence(None), q)
    assert retrieval_contract.validate_evidence_for_query(_evidence("2026-08-01"), q) == []


# ---------------------------------------------------------------------------
# P1-5 — deep-frozen nested results
# ---------------------------------------------------------------------------

def test_nested_frozen_result_mutation():
    b = make_governed_empirical_bundle()
    rob = b.robustness.result
    with pytest.raises(TypeError):
        rob.items["sample_n"] = "X"
    with pytest.raises(TypeError):
        rob.items["new"] = "Y"
    with pytest.raises(Exception):
        b.bundle_digest = "tampered"


# ---------------------------------------------------------------------------
# P1-8 — CV chronological ordering precondition
# ---------------------------------------------------------------------------

def test_unordered_cv_input_fails():
    labels = [(20, 21), (0, 1), (10, 11)]
    with pytest.raises(ValueError):
        cv.purged_kfold(3, labels, n_splits=2, embargo=1)
    with pytest.raises(ValueError):
        cv.purge_train_indices(3, labels, test_indices=[0])


# ---------------------------------------------------------------------------
# P2-2 — scope guard base truth
# ---------------------------------------------------------------------------

def test_scope_guard_denies_shared_files():
    from scripts.lib.research_governance import pr_scope_guard
    assert pr_scope_guard.evaluate(["scripts/lib/cio_acceptance_v4.py"])["state"] == "FAIL"
    assert pr_scope_guard.evaluate(["scripts/lib/research_governance/trial_registry.py"])["state"] == "PASS"
    assert pr_scope_guard.evaluate(["docs/investment-office/R1_FORMULA_AND_REFERENCE_AUDIT.md"])["state"] == "PASS"
