"""Research governance — R1 TRUE-PROVENANCE adversarial matrix (v5).

The "one valid producer-generated bundle, alter ONE thing, assert the exact
reason/gate" suite required by the v5 true-provenance + final-rebase closeout
prompt. It closes the remaining P0 trust-boundary holes:

  * a prebuilt statistical result can never become governed evidence (P0-1);
  * method-specific producers invoke the actual implementations (P0-1);
  * producer code identity = source bytes, not a version label (P0-2);
  * receipts are issued (HMAC-signed), not self-certified (P0-3);
  * completeness binds the exact frozen family definition (P0-4);
  * multiple-testing family == the exact frozen trial/config family (P0-5);
  * OOS receipt binds the exact bundle dataset + confirmatory fields (P0-6);
  * AFML ISBN corrected to Wiley hardcover/e-book (P1-1);
  * retrieval datetime fail-closed edges (P1-2);
  * status="OK" requires material outputs (P1-4);
  * scope guard fails closed on unresolved remote base (P2-1).

Pure/in-memory. No provider/broker/DB calls.
"""
from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from scripts.lib.research_governance import (  # noqa: E402
    bootstrap_reality_check,
    deflated_sharpe,
    multiple_testing,
    pbo,
    producers,
    promotion_gate,
    pr_scope_guard,
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
)
from scripts.lib.research_governance.models import FrozenDict, ResearchEvidence  # noqa: E402
from scripts.lib.research_governance.receipts import (  # noqa: E402
    FrozenTrialFamilyReceipt,
    OOSReceipt,
    RegistryCompletenessReceipt,
    governed_result,
    producer_source_digest,
    sign_receipt,
)
from scripts.lib.research_governance.results import finalize  # noqa: E402

_IDENTITY = {
    "hypothesis_id": "h1", "protocol_hash": "ph", "trial_family_id": "f",
    "family_definition_hash": "fdh", "dataset_hash": "d0", "code_sha": "c0",
}
_CHILD_NAMES = ("multiple_testing", "dsr", "pbo", "reality_check", "robustness")


def _bundle_with_child(name, value):
    """Replace one bundle child and recompute the bundle digest."""
    from scripts.lib.research_governance.governed_bundle import make_typed_empirical_context
    ctx = make_typed_empirical_context()
    b = ctx["evidence_bundle"]
    b2 = replace(b, **{name: value})
    b2 = replace(b2, bundle_digest=b2.compute_digest())
    return dict(ctx, evidence_bundle=b2)


# ---------------------------------------------------------------------------
# 01–06: a prebuilt (hand-authored favorable) result can never become governed
# ---------------------------------------------------------------------------

_FAVORABLE_OVERRIDES = {
    "dsr": dict(psr_z=999.0, probability_sr_exceeds_deflated_benchmark=0.999999),
    "pbo": dict(pbo=0.001),
    "reality_check": dict(bootstrap_pvalue=0.001),
    "multiple_testing": dict(adjusted_pvalue=0.0001, rejected=True),
    "robustness": {},
}


@pytest.mark.parametrize("name", _CHILD_NAMES)
def test_hand_authored_favorable_cannot_be_promoted(name):
    b = make_governed_empirical_bundle()
    res = replace(getattr(b, name).result, **_FAVORABLE_OVERRIDES[name])
    res = finalize(res)
    child = governed_result(res, input_artifact=_IDENTITY)
    # The generic wrapper is UNSIGNED => not issuer-authenticated provenance.
    assert child.receipt.verify() is False
    r = promotion_gate.run_promotion_gate(_bundle_with_child(name, child))
    assert r["overall"] == GateState.FAIL.value
    assert "does not verify" in r["evidence_bundle"]


# ---------------------------------------------------------------------------
# 07–10: method-specific producer output == real function output
# ---------------------------------------------------------------------------

def test_governed_dsr_equals_real_dsr():
    inp = producers.DSRInput(
        observed_sharpe=0.5, n_observations=250, skewness=-0.2, kurtosis=4.0,
        trial_sharpes=(0.5, -0.1, 0.0), n_trials=3,
        sharpe_frequency="PER_PERIOD", trial_sharpe_frequency="PER_PERIOD",
        return_frequency="DAILY", confirmatory=True, **_IDENTITY,
    )
    gr = producers.run_governed_dsr(inp)
    real = deflated_sharpe.deflated_sharpe(
        0.5, 250, -0.2, 4.0, (0.5, -0.1, 0.0), 3,
        sharpe_frequency="PER_PERIOD", trial_sharpe_frequency="PER_PERIOD",
        return_frequency="DAILY", confirmatory=True)
    assert real["status"] == "OK"
    assert gr.result.deflated_benchmark_sr == real["deflated_benchmark_sr"]
    assert gr.result.psr_z == real["psr_z"]
    assert gr.result.probability_sr_exceeds_deflated_benchmark == \
        real["probability_sr_exceeds_deflated_benchmark"]


def test_governed_pbo_equals_real_pbo():
    matrix = (
        (0.05, -0.01, 0.04, -0.02, 0.05, -0.01),
        (0.01, 0.00, 0.01, -0.01, 0.01, 0.00),
        (-0.01, 0.00, -0.01, 0.00, -0.01, 0.00),
    )
    gr = producers.run_governed_pbo(
        producers.PBOInput(config_returns=matrix, n_subsets=2, seed=0,
                           performance="sharpe", **_IDENTITY))
    real = pbo.cscv_probability_of_backtest_overfitting(
        matrix, n_subsets=2, seed=0, performance="sharpe")
    assert real["status"] == "OK"
    assert gr.result.pbo == real["pbo"]
    assert gr.result.total_combinations == real["total_combinations"]
    assert gr.result.sampling_fraction == real["sampling_fraction"]


def test_governed_reality_check_equals_real_rc():
    diffs = (
        (0.20, 0.10, 0.30, 0.00, 0.20, 0.10),
        (0.00, 0.05, 0.00, 0.05, 0.00, 0.05),
        (-0.05, 0.00, -0.02, 0.01, -0.03, 0.00),
    )
    gr = producers.run_governed_reality_check(
        producers.RealityCheckInput(
            family_id="f", differentials=diffs, n_bootstrap=100,
            mean_block_length=2.0, seed=1, confirmatory=True, **_IDENTITY))
    real = bootstrap_reality_check.reality_check_pvalue(
        diffs, n_bootstrap=100, mean_block_length=2.0, seed=1,
        family_id="f", family_definition_hash="fdh", trial_family_id="f",
        confirmatory=True)
    assert real["status"] == "OK"
    assert gr.result.bootstrap_pvalue == real["bootstrap_pvalue"]
    assert gr.result.pvalue_resolution == real["pvalue_resolution"]


def test_governed_multiple_testing_equals_real_corrections():
    pvals = (0.001, 0.20, 0.50)
    for method, fn in (("bonferroni", multiple_testing.bonferroni),
                       ("holm", multiple_testing.holm)):
        gr = producers.run_governed_multiple_testing(
            producers.MultipleTestingInput(
                tested_hypothesis_id="h1", method=method, alpha=0.05,
                tested_trial_ids=("t1", "t2", "t3"),
                tested_config_hashes=("c1", "c2", "c3"),
                raw_pvalues=pvals, focal_trial_id="t1", **_IDENTITY))
        real = fn(list(pvals), 0.05)
        assert gr.result.adjusted_pvalue == real["adjusted"][0]
        assert gr.result.rejected == real["rejected"][0]


# ---------------------------------------------------------------------------
# 11: producer source digest represents code, not a label
# ---------------------------------------------------------------------------

def test_producer_source_digest_represents_code_not_label():
    from scripts.lib.research_governance.models import _stable_hash
    p = Path(deflated_sharpe.__file__)
    real = hashlib.sha256(p.read_bytes()).hexdigest()
    assert producer_source_digest("deflated_sharpe") == real
    # A changed artifact (simulated) yields a different digest.
    changed = hashlib.sha256(p.read_bytes() + b"\n# changed").hexdigest()
    assert changed != real
    # It is NOT a metadata-label hash of {module, version}.
    label = _stable_hash({"module": "deflated_sharpe", "version": "1.0"})
    assert real != label


# ---------------------------------------------------------------------------
# 12–15: forged self-digest receipts fail issuer verification
# ---------------------------------------------------------------------------

def test_forged_result_receipt_self_digest_fails_issuer():
    b = make_governed_empirical_bundle()
    gr = b.dsr
    forged = replace(gr.receipt, issuer_id=None, signature=None)
    forged = replace(forged, receipt_digest=forged.compute_digest())
    assert forged.compute_digest() == forged.receipt_digest  # self-consistent
    assert forged.verify() is False  # but not issuer-authenticated


def test_forged_family_receipt_self_digest_fails_issuer():
    fr = FrozenTrialFamilyReceipt(
        family_id="f", hypothesis_id="h", protocol_hash="ph",
        family_definition_hash="fdh", confirmatory=True,
        planned_trial_ids=("t1", "t2"),
        planned_config_hashes=FrozenDict({"t1": "c1", "t2": "c2"}),
        frozen_at="2026-01-01T00:00:00+00:00", definition_digest="",
    )
    fr = replace(fr, definition_digest=fr.compute_definition_digest())
    assert fr.definition_digest == fr.compute_definition_digest()
    assert fr.verify() is False


def test_forged_completeness_receipt_self_digest_fails_issuer():
    rc = RegistryCompletenessReceipt(
        family_id="f", complete=True, planned_trial_count=2, recorded_trial_count=2,
        terminal_counts=FrozenDict({"COMPLETED": 2}),
        definition_digest="d" * 64, generated_at="2026-01-01T00:00:00+00:00",
    )
    rc = replace(rc, receipt_digest=rc.compute_digest())
    assert rc.verify() is False


def test_forged_oos_receipt_self_digest_fails_issuer():
    o = OOSReceipt(
        oos_window_id="w1", economic_segment_id="e", dataset_id="ds", dataset_hash="d0",
        segment_start="2027-01-01", segment_end="2027-12-31", oos_generation=1,
        protocol_hash="ph", trial_family_id="f", family_definition_hash="fdh",
        registered_at="2026-01-01T00:00:00+00:00", consumed_at=None,
        rerun_classification=None, untouched=True,
    )
    o = replace(o, receipt_digest=o.compute_digest())
    assert o.verify() is False


# ---------------------------------------------------------------------------
# 16–19: completeness receipt binds the exact frozen family definition
# ---------------------------------------------------------------------------

def _bundle_with_completeness(**overrides):
    b = make_governed_empirical_bundle()
    rc = sign_receipt(replace(b.registry_completeness_receipt, **overrides))
    b2 = replace(b, registry_completeness_receipt=rc)
    return replace(b2, bundle_digest=b2.compute_digest())


def test_completeness_definition_mismatch_fails():
    assert any("definition_digest" in p
               for p in _bundle_with_completeness(definition_digest="x" * 64).validate_bundle())


def test_completeness_planned_count_mismatch_fails():
    assert any("planned_trial_count" in p
               for p in _bundle_with_completeness(planned_trial_count=99).validate_bundle())


def test_completeness_recorded_count_mismatch_fails():
    assert any("recorded_trial_count" in p
               for p in _bundle_with_completeness(recorded_trial_count=99).validate_bundle())


def test_completeness_terminal_count_sum_mismatch_fails():
    assert any("terminal_counts" in p
               for p in _bundle_with_completeness(
                   terminal_counts=FrozenDict({"COMPLETED": 99})).validate_bundle())


# ---------------------------------------------------------------------------
# 20–22: multiple-testing family == the exact frozen trial/config family
# ---------------------------------------------------------------------------

def _bundle_with_mt(trial_ids, config_hashes, pvalues, focal="t1"):
    b = make_governed_empirical_bundle()
    mt = producers.run_governed_multiple_testing(
        producers.MultipleTestingInput(
            tested_hypothesis_id="h1", method="bonferroni", alpha=0.05,
            tested_trial_ids=trial_ids, tested_config_hashes=config_hashes,
            raw_pvalues=pvalues, focal_trial_id=focal, **_IDENTITY))
    b2 = replace(b, multiple_testing=mt)
    return replace(b2, bundle_digest=b2.compute_digest())


def test_mt_frozen_trial_ids_mismatch_fails():
    problems = _bundle_with_mt(("t1", "t2"), ("c1", "c2"), (0.001, 0.20)).validate_bundle()
    assert any("tested_trial_ids" in p for p in problems)


def test_mt_frozen_config_hash_mismatch_fails():
    problems = _bundle_with_mt(
        ("t1", "t2", "t3"), ("c1", "c2", "cX"), (0.001, 0.20, 0.50)).validate_bundle()
    assert any("tested_config_hashes" in p for p in problems)


def test_mt_omission_of_losing_trial_fails():
    b = make_governed_empirical_bundle()
    mt = b.multiple_testing.result
    shrunk = replace(mt, tested_hypothesis_ids=("h1", "h2"), raw_pvalues=(0.001, 0.20))
    assert any("family_input_digest" in p for p in shrunk.validate())
    child = governed_result(finalize(shrunk), input_artifact=_IDENTITY)
    r = promotion_gate.run_promotion_gate(_bundle_with_child("multiple_testing", child))
    assert r["overall"] == GateState.FAIL.value
    assert "family_input_digest" in r["evidence_bundle"]


def test_mt_exact_frozen_family_recomputation_pass():
    b = make_governed_empirical_bundle()
    assert b.multiple_testing.receipt.verify() is True
    assert b.multiple_testing.result.validate() == []


# ---------------------------------------------------------------------------
# 23–27: OOS receipt binds the exact bundle dataset + confirmatory fields
# ---------------------------------------------------------------------------

def test_oos_dataset_hash_mismatch_fails():
    b = make_governed_empirical_bundle()
    bad_oos = sign_receipt(replace(b.oos_receipt, dataset_hash="dX"))
    b2 = replace(b, oos_receipt=bad_oos)
    b2 = replace(b2, bundle_digest=b2.compute_digest())
    assert any("dataset_hash != bundle" in p for p in b2.validate_bundle())


def _confirmatory_registry():
    reg = trial_registry.TrialRegistry()
    reg.freeze_family("f", "h", protocol_hash="ph", family_definition_hash="fdh",
                      planned_trials=[("t1", "c1")], confirmatory=True)
    reg.record_trial("f", "t1", config_hash="c1", result_payload={"s": 0.5},
                     code_sha="c0", dataset_hash="d0", started_at="2026-01-01",
                     completed_at="2026-01-02")
    return reg


@pytest.mark.parametrize("blank", ["dataset_id", "dataset_hash", "segment_start", "segment_end"])
def test_confirmatory_oos_blank_field_fails(blank):
    reg = _confirmatory_registry()
    kwargs = dict(oos_generation=1, segment_start="2027-01-01", segment_end="2027-12-31",
                  dataset_id="ds", dataset_hash="d0")
    kwargs[blank] = ""
    with pytest.raises(ValueError):
        reg.register_oos_window("f", "w1", **kwargs)


def test_oos_dataset_matches_bundle_pass():
    b = make_governed_empirical_bundle()
    assert b.oos_receipt.dataset_hash == b.dataset_hash
    assert b.oos_receipt.verify() is True


# ---------------------------------------------------------------------------
# 28–31: status="OK" requires material outputs
# ---------------------------------------------------------------------------

def test_dsr_ok_requires_material_outputs():
    b = make_governed_empirical_bundle()
    for field in ("deflated_benchmark_sr", "psr_z",
                  "probability_sr_exceeds_deflated_benchmark"):
        broken = replace(b.dsr.result, **{field: None})
        assert any(field in p for p in broken.validate()), field


def test_rc_ok_requires_resolution():
    b = make_governed_empirical_bundle()
    broken = replace(b.reality_check.result, pvalue_resolution=None)
    assert any("pvalue_resolution" in p for p in broken.validate())


def test_pbo_ok_requires_diagnostics():
    b = make_governed_empirical_bundle()
    assert b.pbo.result.validate() == []
    broken = replace(b.pbo.result, total_combinations=999)
    assert any("total_combinations" in p for p in broken.validate())


# ---------------------------------------------------------------------------
# 32–34: retrieval datetime fail-closed edges
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


def test_naive_datetime_source_date_fails_closed():
    q = retrieval_contract.ResearchQuery(asset_class="equity", as_of="2026-08-14",
                                         max_source_age_days=30)
    problems = retrieval_contract.validate_evidence_for_query(
        _evidence(datetime(2026, 8, 1)), q)
    assert any("malformed source_date" in p for p in problems)


def test_date_only_as_of_aware_datetime_source_controlled_failure():
    q = retrieval_contract.ResearchQuery(asset_class="equity", as_of="2026-08-14")
    problems = retrieval_contract.validate_evidence_for_query(
        _evidence(datetime(2026, 8, 1, tzinfo=timezone.utc)), q)
    assert any("mixed date/datetime precision" in p for p in problems)


def test_aware_datetime_as_of_date_only_source_controlled_failure():
    q = retrieval_contract.ResearchQuery(asset_class="equity", as_of="2026-08-14T00:00:00+00:00")
    problems = retrieval_contract.validate_evidence_for_query(_evidence("2026-08-01"), q)
    assert any("mixed date/datetime precision" in p for p in problems)


# ---------------------------------------------------------------------------
# 35: scope guard fails closed on unresolved remote base
# ---------------------------------------------------------------------------

def test_scope_guard_remote_base_unresolved_fails(monkeypatch):
    monkeypatch.setattr(pr_scope_guard, "_fresh_remote_main_sha", lambda repo_root: None)
    with pytest.raises(RuntimeError):
        pr_scope_guard._resolve_effective_base(
            ROOT, "0" * 40, require_remote=True)
    # Offline developer mode is allowed but is NOT merge acceptance.
    import re
    offline = pr_scope_guard._resolve_effective_base(
        ROOT, "0" * 40, require_remote=False)
    assert re.fullmatch(r"[0-9a-f]{40}", offline)


# ---------------------------------------------------------------------------
# 36–38: AFML ISBN corrected to Wiley hardcover/e-book
# ---------------------------------------------------------------------------

def test_old_afml_isbn_rejected():
    srcs = source_catalog.load_sources()
    cpcv = next(s for s in srcs if s["source_id"] == "lopez_de_prado_cpcv_2017")
    assert cpcv["doi_or_isbn"] != "9781119482089"
    assert "9781119482089" not in json.dumps(srcs)  # nowhere in the catalog


def test_wiley_hardcover_and_ebook_isbns_accepted():
    srcs = source_catalog.load_sources()
    cpcv = next(s for s in srcs if s["source_id"] == "lopez_de_prado_cpcv_2017")
    afml = next(s for s in srcs if s["source_id"] == "lopez_de_prado_afml")
    assert cpcv["isbn_hardcover"] == "9781119482086"
    assert cpcv["isbn_ebook"] == "9781119482109"
    assert afml["isbn_hardcover"] == "9781119482086"
    assert afml["isbn_ebook"] == "9781119482109"
    assert source_catalog.critical_reference_report()["coherent"] is True
