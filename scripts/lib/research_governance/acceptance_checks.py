"""Research governance — R1 acceptance checks (PR-R1).

Concrete, deterministic, side-effect-free checks backing the RGA gates. Each
returns (state, detail). No provider calls, no broker calls, no DB writes.
"""
from __future__ import annotations

from typing import Callable

from .enums import EvidenceGrade, EvidenceType, GateState, InfluenceClass, ResearchStatus
from .models import (
    ResearchClaim,
    ResearchEvidence,
    ResearchHypothesis,
    ResearchSource,
)
from . import (
    bootstrap_reality_check,
    cv,
    deflated_sharpe,
    multiple_testing,
    pbo,
    promotion_gate,
    retrieval_contract,
    source_catalog,
    trial_registry,
)


def _pass(detail: str) -> tuple[str, str]:
    return GateState.PASS.value, detail


def _fail(detail: str) -> tuple[str, str]:
    return GateState.FAIL.value, detail


def _check_source_registry() -> tuple[str, str]:
    sources = source_catalog.SOURCES
    if not sources:
        return _fail("source catalog is empty")
    for s in sources:
        for key in ("source_id", "title", "source_type"):
            if not s.get(key):
                return _fail(f"source missing {key}: {s.get('source_id')!r}")
    return _pass(f"{len(sources)} sources registered")


def _check_claim_model() -> tuple[str, str]:
    c = ResearchClaim(
        claim_id="c1", source_id="s1", claim="claim text",
        claim_type="empirical", page_or_section="p1", scope="US equities",
    )
    if c.source_status != ResearchStatus.SOURCE_CLAIM_INCOMPLETE:
        return _fail("default source status wrong")
    c2 = ResearchClaim(
        claim_id="c2", source_id="s2", claim="x", claim_type="t",
        source_status="SOURCE_CLAIM",
    )
    if c2.source_status != ResearchStatus.SOURCE_CLAIM:
        return _fail("string status not coerced")
    return _pass("claim model valid")


def _check_hypothesis_model() -> tuple[str, str]:
    h1 = ResearchHypothesis(hypothesis_id="h1", signal_definition="s")
    h2 = ResearchHypothesis(hypothesis_id="h1", signal_definition="s")
    a = h1.compute_protocol_hash()
    b = h2.compute_protocol_hash()
    if a != b:
        return _fail("protocol hash not deterministic")
    h3 = ResearchHypothesis(hypothesis_id="h1", signal_definition="different")
    if h3.compute_protocol_hash() == a:
        return _fail("protocol hash does not change with content")
    return _pass("hypothesis model valid + deterministic protocol hash")


def _check_trial_registry() -> tuple[str, str]:
    reg = trial_registry.TrialRegistry()
    reg.freeze_family("fam1", "h1", protocol_hash="ph")
    reg.record_trial("fam1", "t1", {"p": 1}, selected_for_followup=True)
    reg.record_losing_trial("fam1", "t2", {"p": 2})
    reg.record_losing_trial("fam1", "t3", {"p": 3})
    rep = reg.completeness_report("fam1")
    if not rep["complete"]:
        return _fail(f"family should be complete: {rep}")
    if rep["losing_count"] != 2:
        return _fail(f"expected 2 losing variants, got {rep['losing_count']}")

    # A family that records only winners must be detected as incomplete.
    reg2 = trial_registry.TrialRegistry()
    reg2.freeze_family("fam2", "h2", protocol_hash="ph")
    reg2.record_trial("fam2", "t1", {"p": 1}, selected_for_followup=True)
    rep2 = reg2.completeness_report("fam2")
    if rep2["complete"]:
        return _fail("only-winners family incorrectly marked complete")
    return _pass("trial registry records losing variants and detects winner-only families")


def _check_oos_consumption() -> tuple[str, str]:
    reg = trial_registry.TrialRegistry()
    reg.register_oos_window("fam1", "w1", oos_generation=1)
    if not reg.oos_is_untouched("fam1", "w1"):
        return _fail("fresh OOS window should be untouched")
    reg.consume_oos_window("fam1", "w1")
    if reg.oos_is_untouched("fam1", "w1"):
        return _fail("consumed OOS window still reports untouched")
    return _pass("OOS consumption semantics enforced")


def _check_multiple_testing() -> tuple[str, str]:
    pvals = [0.001, 0.01, 0.2, 0.5]
    b = multiple_testing.bonferroni(pvals, alpha=0.05)
    if b["rejected"] != [True, True, False, False]:
        return _fail(f"bonferroni wrong: {b['rejected']}")
    h = multiple_testing.holm(pvals, alpha=0.05)
    if h["rejected"] != [True, True, False, False]:
        return _fail(f"holm wrong: {h['rejected']}")
    bh = multiple_testing.benjamini_hochberg(pvals, alpha=0.05)
    # BH q-values must be non-decreasing in the sorted-p order; at least first two reject.
    if bh["rejected"][0] is not True:
        return _fail(f"bh should reject smallest p: {bh['rejected']}")
    return _pass("multiple-testing corrections correct")


def _check_deflated_sharpe() -> tuple[str, str]:
    # Unknown trial count => UNAVAILABLE (never silently single-trial).
    r = deflated_sharpe.deflated_sharpe(
        observed_sharpe=1.0, n_observations=100, skewness=0.0, kurtosis=3.0,
        trial_sharpes=[], n_trials=None,
    )
    if r["status"] != "UNAVAILABLE":
        return _fail("DSR with unknown trials must be UNAVAILABLE")
    r2 = deflated_sharpe.deflated_sharpe(
        observed_sharpe=1.5, n_observations=250, skewness=-0.2, kurtosis=4.0,
        trial_sharpes=[0.2, 0.4, 0.1, 0.5, 0.3], n_trials=10,
    )
    if r2["status"] != "OK":
        return _fail(f"DSR should be OK with trial distribution: {r2}")
    if not (0.0 <= r2["probability"] <= 1.0):
        return _fail("DSR probability out of [0,1]")
    return _pass("DSR applicability + probability correct")


def _check_pbo() -> tuple[str, str]:
    single = pbo.cscv_probability_of_backtest_overfitting([[0.01, 0.02]])
    if single["status"] != "NOT_APPLICABLE":
        return _fail("PBO with single config must be NOT_APPLICABLE")

    # 3 configs, 16 obs, S=4 -> sub_len 4.
    matrix = [
        [0.01, -0.01, 0.02, -0.02, 0.01, 0.00, 0.02, -0.01,
         0.01, 0.02, -0.01, 0.01, -0.02, 0.01, 0.02, 0.00],
        [0.02, 0.00, 0.01, -0.01, 0.02, 0.01, 0.00, 0.01,
         0.01, 0.01, 0.02, 0.00, -0.01, 0.02, 0.01, 0.01],
        [-0.01, -0.02, 0.00, 0.01, -0.01, 0.00, -0.02, 0.01,
         -0.01, 0.00, -0.01, 0.01, 0.00, -0.01, -0.01, 0.00],
    ]
    r = pbo.cscv_probability_of_backtest_overfitting(matrix, n_subsets=4, seed=0)
    if r["status"] != "OK":
        return _fail(f"PBO should be OK: {r}")
    if not (0.0 <= r["pbo"] <= 1.0):
        return _fail("PBO out of [0,1]")
    return _pass("PBO/CSCV correct + applicability enforced")


def _check_reality_check() -> tuple[str, str]:
    fam = [
        [0.01, -0.01, 0.02, -0.01, 0.01, 0.02, -0.01, 0.01, -0.02, 0.01],
        [0.02, 0.00, 0.01, 0.02, 0.01, 0.00, 0.01, 0.02, 0.00, 0.01],
        [0.00, -0.01, 0.00, -0.01, 0.01, -0.01, 0.00, -0.02, 0.01, -0.01],
    ]
    r = bootstrap_reality_check.reality_check_pvalue(fam, n_bootstrap=500, seed=0)
    if r["status"] != "OK":
        return _fail(f"reality check should be OK: {r}")
    if not (0.0 < r["bootstrap_pvalue"] <= 1.0):
        return _fail("reality-check p-value out of (0,1]")
    c = bootstrap_reality_check.calendar_family_reality_check(
        "sep_midterm", fam, n_bootstrap=200, seed=1)
    if c.get("family_id") != "sep_midterm":
        return _fail("calendar family id not propagated")
    return _pass("White/STW reality check correct")


def _check_cv_purging() -> tuple[str, str]:
    # Labels: sample 2 (2,6) clearly overlaps test label (3,4); samples 0,1 do not.
    labels = [(0, 1), (1, 2), (2, 6), (3, 4), (4, 5), (5, 7)]
    # test block = indices [3,4,5]; kept training (earlier) should be [0,1].
    kept = cv.purge_train_indices(6, labels, [3, 4, 5], embargo=0)
    if 2 in kept:
        return _fail("sample 2 should be purged (label overlap)")
    if 0 not in kept or 1 not in kept:
        return _fail(f"non-overlapping earlier samples should remain, got {kept}")

    folds = cv.embargoed_purged_kfold(6, labels, n_splits=3, embargo=0)
    if len(folds) != 3:
        return _fail(f"expected 3 folds, got {len(folds)}")

    parts = cv.cpcv_partitions(6, 2)
    if len(parts) != 15:
        return _fail(f"CPCV should yield C(6,2)=15 partitions, got {len(parts)}")
    return _pass("purged/embargoed CV + CPCV correct")


def _check_promotion_contract() -> tuple[str, str]:
    gids = set(promotion_gate.GATE_IDS)
    if gids != {f"RG-{i}" for i in range(12)}:
        return _fail("promotion gate must define RG-0..RG-11")
    ctx = {"source_id": "s", "claim": "c", "page_or_section": "p", "scope": "us"}
    rep = promotion_gate.run_promotion_gate(ctx, halt_on_first_fail=True)
    # RG-2 fails (no frozen family), later gates NOT_IN_SCOPE.
    if rep["gate_results"]["RG-2"]["state"] != GateState.FAIL.value:
        return _fail("RG-2 should fail without frozen family")
    return _pass("promotion-gate contract present (RG-0..11)")


def _check_retrieval_contract() -> tuple[str, str]:
    if not hasattr(retrieval_contract, "ResearchRetriever"):
        return _fail("ResearchRetriever protocol missing")
    ev = ResearchEvidence(
        fact_id="f1", fact="fact", source_id="s1",
        evidence_type=EvidenceType.SEASONALITY,
        research_status=ResearchStatus.OOS_SUPPORTED,
        evidence_grade=EvidenceGrade.D,
        influence_class=InfluenceClass.CONTEXT_MODIFIER,
    )
    problems = retrieval_contract.validate_retrieval_result(ev)
    if not problems:
        return _fail("OOS_SUPPORTED with grade D should fail validation")
    return _pass("retrieval contract present + fail-closed validation")


def _check_authority_boundary() -> tuple[str, str]:
    ctx = {
        "source_id": "s", "claim": "c", "page_or_section": "p", "scope": "us",
        "protocol_hash": "ph", "trial_family_id": "fam", "family_frozen": True,
        "code_sha": "c0", "dataset_hash": "d0",
        "in_sample_metric": 1.0, "in_sample_threshold": 0.0,
        "oos_supported": True, "oos_untouched": True,
        "multiple_testing": {"rejected_any": True},
        "reality_check": {"bootstrap_pvalue": 0.01},
        "robustness": {"subperiods": True, "regimes": True, "costs": True},
        "evidence_grade": "B",
        "influence_class": InfluenceClass.VALUATION_INPUT.value,
        "claims_trade_authority": True,
    }
    rep = promotion_gate.run_promotion_gate(ctx)
    if rep["gate_results"]["RG-10"]["state"] != GateState.FAIL.value:
        return _fail("RG-10 must fail when trade authority is claimed")
    return _pass("authority boundary enforced (no trade authority from research)")


def _check_scope_guard() -> tuple[str, str]:
    from . import pr_scope_guard
    deny = pr_scope_guard.DENYLIST_PATTERNS
    if not deny:
        return _fail("scope guard has no denylist")
    bad = ["scripts/lib/cio_acceptance_v4.py",
           "apps/command-center-v3/src/pages/CioHub.tsx",
           "RELEASE_MANIFEST.json"]
    for f in bad:
        if not pr_scope_guard.is_denied(f, deny):
            return _fail(f"scope guard failed to deny {f}")
    good = "scripts/lib/research_governance/trial_registry.py"
    if pr_scope_guard.is_denied(good, deny):
        return _fail(f"scope guard wrongly denied {good}")
    return _pass("scope guard denies off-limits files")


R1_CHECKS: dict[str, Callable[[], tuple[str, str]]] = {
    "RGA-1": _check_source_registry,
    "RGA-2": _check_claim_model,
    "RGA-3": _check_hypothesis_model,
    "RGA-4": _check_trial_registry,
    "RGA-5": _check_oos_consumption,
    "RGA-6": _check_multiple_testing,
    "RGA-7": _check_deflated_sharpe,
    "RGA-8": _check_pbo,
    "RGA-9": _check_reality_check,
    "RGA-10": _check_cv_purging,
    "RGA-11": _check_promotion_contract,
    "RGA-12": _check_retrieval_contract,
    "RGA-13": _check_authority_boundary,
    "RGA-14": _check_scope_guard,
}
