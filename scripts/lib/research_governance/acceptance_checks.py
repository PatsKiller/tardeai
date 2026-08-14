"""Research governance — R1 acceptance checks with GOLDEN/REFERENCE validation.

Each check returns (state, detail). Statistical checks compare against frozen
golden vectors or decisive semantic fixtures — NOT merely "value is in [0,1]".

Golden vectors were computed independently from the published formulas (Bailey &
López de Prado DSR; Bailey/Borwein/López de Prado/Zhu PBO/CSCV; White 2000 /
Sullivan–Timmermann–White Reality Check) and frozen here so a regression that
silently flips a sign, drops a mean term, or mis-centers a null is caught.

The checks test the REAL governance claims: provenance over the actual catalog,
family-bound statistics, anti-gaming registry semantics, multi-block CPCV
leakage, and fail-closed promotion — not toy objects.
"""
from __future__ import annotations

import random
from typing import Callable

from .enums import EvidenceGrade, EvidenceType, GateState, InfluenceClass, ResearchStatus
from .models import (
    ResearchEvidence,
    SampleTimingContract,
    _stable_hash,
    validate_no_lookahead,
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


# --------------------------------------------------------------------------
# Golden fixtures
# --------------------------------------------------------------------------

def _dsr_trials() -> list[float]:
    return [0.2, 0.4, 0.1, 0.5, 0.3, 0.35, 0.25, 0.45, 0.15, 0.3]


def _stable_winner_matrix():
    return [[(0.02 if c == 0 else (0.005 if c == 1 else -0.005))
             + ((t * 7 + c * 13) % 5 - 2) * 0.001 for t in range(16)] for c in range(3)]


def _overfit_matrix():
    return [[(0.06 if (t // 4) == c else -0.02)
             + ((t * 7 + c * 13) % 5 - 2) * 0.001 for t in range(16)] for c in range(3)]


def _empirical_ctx() -> dict:
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


# --------------------------------------------------------------------------
# Checks
# --------------------------------------------------------------------------

def _check_source_registry() -> tuple[str, str]:
    rep = source_catalog.manifest_report()
    if not rep["manifest_ok"]:
        return _fail(f"source manifest mismatch: {rep}")
    if not rep["provenance_coherent"]:
        return _fail(f"source provenance incoherent: {rep['provenance_issues']}")
    if "expectations_investing_rappaport_mauboussin" not in source_catalog.expected_required_ids():
        return _fail("Expectations Investing missing from expected manifest")
    if "sullivan_timmermann_white_calendar_effects_2001" not in source_catalog.expected_required_ids():
        return _fail("STW calendar-effects source missing from expected manifest")
    if "stock_traders_almanac" not in source_catalog.expected_required_ids():
        return _fail("Stock Trader's Almanac missing from expected manifest")
    return _pass(f"{rep['actual_institutional_books']} institutional books + "
                 f"{rep['actual_practitioner_sources']} practitioner + "
                 f"{rep['actual_primary_research']} papers; "
                 f"json_hash={rep['catalog_json_hash'][:12]}")


def _check_provenance() -> tuple[str, str]:
    # Validate the ACTUAL catalog, not a toy source.
    rep = source_catalog.manifest_report()
    if not rep["provenance_coherent"]:
        return _fail(f"catalog provenance incoherent: {rep['provenance_issues']}")
    sources = source_catalog.load_sources()
    for s in sources:
        if not s.get("source_id") or not s.get("source_type") or not s.get("title"):
            return _fail(f"source missing identity metadata: {s['source_id']}")
        fts = s.get("full_text_status")
        cs = s.get("claim_status")
        if fts == "NOT_FOUND_IN_FILE_LIBRARY" and cs != "SOURCE_CLAIM_INCOMPLETE":
            return _fail(f"{s['source_id']} missing full text but not SOURCE_CLAIM_INCOMPLETE")
    return _pass("provenance coherent: missing full text => SOURCE_CLAIM_INCOMPLETE; identity metadata present")


def _check_lifecycle_separated() -> tuple[str, str]:
    if EvidenceType.SEASONALITY.value == ResearchStatus.OOS_SUPPORTED.value:
        return _fail("type and status must be distinct")
    if ResearchStatus.OOS_SUPPORTED.value == EvidenceGrade.B.value:
        return _fail("status and grade must be distinct")
    if EvidenceGrade.B.value == EvidenceType.SEASONALITY.value:
        return _fail("grade and type must be distinct")
    return _pass("type / status / grade are orthogonal enums")


def _check_trial_registry() -> tuple[str, str]:
    # Confirmatory family requires family_definition_hash.
    reg = trial_registry.TrialRegistry()
    try:
        reg.freeze_family("fam", "h", protocol_hash="ph",
                          planned_trials=[("t1", "c1")], confirmatory=True)
        return _fail("confirmatory family without family_definition_hash must be rejected")
    except ValueError:
        pass

    # Full confirmatory family with anti-gaming semantics.
    reg.freeze_family("fam", "h", protocol_hash="ph", family_definition_hash="fdh",
                      planned_trials=[("t1", "c1"), ("t2", "c2"), ("t3", "c3")],
                      confirmatory=True)
    reg.record_trial("fam", "t1", config_hash="c1", result_payload={"sharpe": 0.5})
    reg.record_trial("fam", "t2", config_hash="c2", result_payload={"sharpe": -0.1})
    reg.record_trial("fam", "t3", config_hash="c3", result_payload={"sharpe": 0.0})
    rep = reg.completeness_report("fam")
    if not rep["complete"]:
        return _fail(f"fully accounted confirmatory family should be complete: {rep}")

    # External result-hash must have an artifact reference.
    reg2 = trial_registry.TrialRegistry()
    reg2.freeze_family("fam2", "h2", protocol_hash="ph2", planned_trials=[("a", "c1")])
    try:
        reg2.record_trial("fam2", "a", config_hash="c1", result_hash="d" * 64)
        return _fail("opaque result_hash without artifact reference must be rejected")
    except ValueError:
        pass

    # Changed OOS payload rejected + consumed segment alias blocked.
    reg3 = trial_registry.TrialRegistry()
    reg3.freeze_family("fam3", "h3", protocol_hash="ph3", planned_trials=[("a", "c1")])
    reg3.register_oos_window("fam3", "w1", oos_generation=1, segment_start="2020")
    try:
        reg3.register_oos_window("fam3", "w1", oos_generation=2, segment_start="2021")
        return _fail("changed OOS payload must be rejected")
    except ValueError:
        pass
    reg3.consume_oos_window("fam3", "w1")
    try:
        reg3.register_oos_window("fam3", "w2", oos_generation=1, segment_start="2020")
        return _fail("consumed segment alias under a new id must be rejected")
    except ValueError:
        pass

    return _pass("frozen confirmatory family + immutable trials + OOS anti-gaming enforced")


def _check_no_lookahead() -> tuple[str, str]:
    reg = trial_registry.TrialRegistry()
    try:
        reg.record_trial("nope", "t1", config_hash="c1", result_payload={"x": 1})
        return _fail("recording a trial before freeze must be rejected")
    except ValueError:
        pass
    # Sample-timing contract: feature_as_of after decision cutoff => lookahead.
    if not validate_no_lookahead(SampleTimingContract(
            feature_as_of="2026-08-15", decision_as_of="2026-08-14")):
        return _fail("feature_as_of after decision_as_of must be flagged as lookahead")
    if validate_no_lookahead(SampleTimingContract(
            feature_as_of="2026-08-13", decision_as_of="2026-08-14")):
        return _fail("clean timing must pass no-lookahead")
    return _pass("freeze-before-trial + terminal OOS consumption + feature_as_of timing")


def _check_multiple_testing() -> tuple[str, str]:
    pvals = [0.001, 0.01, 0.2, 0.5]
    b = multiple_testing.bonferroni(pvals, alpha=0.05)
    if b["rejected"] != [True, True, False, False]:
        return _fail(f"bonferroni wrong: {b['rejected']}")
    for bad in ([0.5, -0.1], [0.5, 1.5], [0.5, float("nan")], [0.5, float("inf")]):
        try:
            multiple_testing.bonferroni(bad, alpha=0.05)
            return _fail(f"invalid p-values not rejected: {bad}")
        except ValueError:
            pass
    return _pass("multiple-testing correct + strict input validation")


def _check_deflated_sharpe() -> tuple[str, str]:
    trials = _dsr_trials()
    r = deflated_sharpe.deflated_benchmark_sr(trials, 10)
    if r["status"] != "OK":
        return _fail(f"DSR golden should be OK: {r}")
    golden = 0.503279766668363
    if abs(r["deflated_benchmark_sr"] - golden) > 1e-9:
        return _fail(f"DSR golden mismatch: got {r['deflated_benchmark_sr']!r} want {golden!r}")
    r2 = deflated_sharpe.deflated_benchmark_sr([x + 0.5 for x in trials], 10)
    if abs((r2["deflated_benchmark_sr"] - r["deflated_benchmark_sr"]) - 0.5) > 1e-9:
        return _fail("DSR benchmark must be translation-invariant")
    if deflated_sharpe.psr(1.0, 0.0, 100, 3.0, 3.0)["status"] != "UNAVAILABLE":
        return _fail("DSR negative denominator-square must be UNAVAILABLE, not raise")
    return _pass("DSR golden + translation invariance + fail-closed denominator")


def _check_pbo() -> tuple[str, str]:
    if pbo.cscv_probability_of_backtest_overfitting([[0.01, 0.02]])["status"] != "NOT_APPLICABLE":
        return _fail("PBO with single config must be NOT_APPLICABLE")
    stable = pbo.cscv_probability_of_backtest_overfitting(_stable_winner_matrix(), n_subsets=4)
    overfit = pbo.cscv_probability_of_backtest_overfitting(_overfit_matrix(), n_subsets=4)
    if stable["pbo"] >= 0.5:
        return _fail(f"stable winner should be LOW PBO, got {stable['pbo']!r}")
    if overfit["pbo"] <= 0.5:
        return _fail(f"overfit rotating winner should be HIGH PBO, got {overfit['pbo']!r}")

    # Tie/permutation invariant.
    equal = [[0.01, 0.02, 0.01, 0.02, 0.01, 0.02, 0.01, 0.02],
             [0.01, 0.02, 0.01, 0.02, 0.01, 0.02, 0.01, 0.02],
             [0.01, 0.02, 0.01, 0.02, 0.01, 0.02, 0.01, 0.02]]
    a = pbo.cscv_probability_of_backtest_overfitting(equal, n_subsets=2)["pbo"]
    b = pbo.cscv_probability_of_backtest_overfitting(list(reversed(equal)), n_subsets=2)["pbo"]
    if a != b:
        return _fail(f"PBO tie ranking must be permutation-invariant: {a} vs {b}")

    # Default must be full enumeration (not a silent approximation).
    r_full = pbo.cscv_probability_of_backtest_overfitting(_stable_winner_matrix(), n_subsets=8)
    if r_full["approx"]:
        return _fail("default PBO must be full enumeration, not approx")
    return _pass(f"PBO rank semantics + tie invariance + full enumeration correct "
                 f"(stable={stable['pbo']:.2f}, overfit={overfit['pbo']:.2f})")


def _check_reality_check() -> tuple[str, str]:
    rng = random.Random(0)
    null = [[rng.gauss(0, 1) for _ in range(100)] for _ in range(5)]
    alt = [[0.25 + rng.gauss(0, 1) for _ in range(100)] for _ in range(3)]

    r_null = bootstrap_reality_check.reality_check_pvalue(null, n_bootstrap=1000, seed=1)
    if r_null["bootstrap_pvalue"] < 0.1:
        return _fail(f"null family spuriously rejected: p={r_null['bootstrap_pvalue']}")
    r_alt = bootstrap_reality_check.reality_check_pvalue(alt, n_bootstrap=1000, seed=1)
    if r_alt["bootstrap_pvalue"] > 0.01:
        return _fail(f"obvious alternative not rejected: p={r_alt['bootstrap_pvalue']}")

    # Block length < 1 must be rejected.
    if bootstrap_reality_check.reality_check_pvalue(alt, n_bootstrap=100, mean_block_length=0.5)["status"] != "UNAVAILABLE":
        return _fail("mean_block_length < 1 must be UNAVAILABLE")

    # Confirmatory Reality Check requires family binding.
    r_conf = bootstrap_reality_check.reality_check_pvalue(
        alt, n_bootstrap=100, family_id="f", family_definition_hash="fdh", confirmatory=True)
    if r_conf["status"] != "OK":
        return _fail(f"valid confirmatory RC should be OK: {r_conf}")
    r_missing = bootstrap_reality_check.reality_check_pvalue(alt, n_bootstrap=100, confirmatory=True)
    if r_missing["status"] != "UNAVAILABLE":
        return _fail("confirmatory RC without family binding must be UNAVAILABLE")

    # Family correction is no more favorable than cherry-picking.
    strong = [0.2 + rng.gauss(0, 1) for _ in range(100)]
    weak = [[rng.gauss(0, 1) for _ in range(100)] for _ in range(4)]
    p_single = bootstrap_reality_check.reality_check_pvalue([strong], n_bootstrap=1000, seed=1)["bootstrap_pvalue"]
    p_family = bootstrap_reality_check.reality_check_pvalue([strong] + weak, n_bootstrap=1000, seed=1)["bootstrap_pvalue"]
    if p_family < p_single:
        return _fail("family correction must not be MORE significant than winner-only")
    return _pass("Reality Check null/alternative/family + block-length + binding semantics correct")


def _check_cv_purging() -> tuple[str, str]:
    labels = [(i * 3, i * 3 + 1) for i in range(9)]
    folds = cv.purged_walk_forward(9, labels, n_splits=3, embargo=100)
    if folds[1]["train"] != [0, 1, 2]:
        return _fail(f"walk-forward erased pre-test history under embargo: {folds[1]}")

    labels2 = [(i * 3, i * 3 + 1) for i in range(9)]
    kf = cv.purged_kfold(9, labels2, n_splits=3, embargo=3)
    if 3 in kf[0]["train"]:
        return _fail("post-test sample inside embargo should be removed from k-fold training")
    if 4 not in kf[0]["train"]:
        return _fail("post-test sample after the embargo window must remain in training")

    # Multi-test-group CPCV golden: test groups {0,2} => sandwiched group 1 embargoed.
    labels4 = [(i * 10, i * 10 + 1) for i in range(12)]
    parts = cv.combinatorial_purged_cv(12, labels4, n_groups=4, n_test_groups=2, embargo=25)
    target = None
    for p in parts:
        if set(p["test"]) == {0, 1, 2, 6, 7, 8}:
            target = p
    if target is None:
        return _fail("CPCV did not produce test groups {0,2}")
    if 3 in target["train"] or 4 in target["train"]:
        return _fail(f"CPCV leaked sandwiched samples (3,4) into training: {target['train']}")
    if 5 not in target["train"]:
        return _fail("CPCV over-embargoed sample 5 (outside window)")
    return _pass("walk-forward / purged-k-fold / multi-block CPCV semantics correct")


def _check_promotion_contract() -> tuple[str, str]:
    if set(promotion_gate.GATE_IDS) != {f"RG-{i}" for i in range(12)}:
        return _fail("promotion gate must define RG-0..RG-11")
    names = {gid: promotion_gate._GATES[i][1] for i, gid in enumerate(f"RG-{k}" for k in range(12))}
    if names.get("RG-10") != "decision_use_audit":
        return _fail("RG-10 must be decision_use_audit")
    if names.get("RG-11") != "live_degradation_retirement":
        return _fail("RG-11 must be live_degradation_retirement")
    return _pass("promotion-gate contract present; RG-10/11 mapping restored")


def _check_retrieval_contract() -> tuple[str, str]:
    if not hasattr(retrieval_contract, "ResearchQuery"):
        return _fail("structured ResearchQuery contract missing")
    q = retrieval_contract.ResearchQuery(asset_class="equity", symbols=["SPY"])
    if retrieval_contract.validate_research_query(q):
        return _fail("valid structured query must pass validation")
    if not retrieval_contract.validate_research_query(retrieval_contract.ResearchQuery()):
        return _fail("empty query must be invalid")
    ev = ResearchEvidence(
        fact_id="f1", fact="fact", source_id="s1",
        evidence_type=EvidenceType.SEASONALITY,
        research_status=ResearchStatus.OOS_SUPPORTED,
        evidence_grade=EvidenceGrade.D,
        influence_class=InfluenceClass.CONTEXT_MODIFIER,
    )
    if not retrieval_contract.validate_retrieval_result(ev):
        return _fail("OOS_SUPPORTED with grade D should fail validation")
    if not hasattr(retrieval_contract, "ContradictionResult"):
        return _fail("ContradictionResult contract missing")
    return _pass("retrieval contract: structured query + contradiction output + fail-closed validation")


def _check_authority_boundary() -> tuple[str, str]:
    ok = promotion_gate.run_promotion_gate(_empirical_ctx())
    if ok["promotion_state"] != "CIO_CONTEXT_ELIGIBLE":
        return _fail(f"valid A-grade empirical should reach CIO_CONTEXT_ELIGIBLE: {ok['promotion_state']}")

    x = promotion_gate.run_promotion_gate(dict(_empirical_ctx(), evidence_grade="X"))
    if x["promotion_state"] != "INVALIDATED" or x["overall"] != GateState.FAIL.value:
        return _fail("grade X must be INVALIDATED/FAIL")
    d = promotion_gate.run_promotion_gate(dict(_empirical_ctx(), evidence_grade="D"))
    if d["promotion_state"] != "SOURCE_ONLY":
        return _fail("grade D must cap at SOURCE_ONLY")
    c = promotion_gate.run_promotion_gate(dict(_empirical_ctx(), evidence_grade="C"))
    if c["promotion_state"] != "EXPLORATORY_SHADOW":
        return _fail("grade C must cap at EXPLORATORY_SHADOW")
    ta = promotion_gate.run_promotion_gate(dict(_empirical_ctx(), claims_trade_authority=True))
    if ta["overall"] != GateState.FAIL.value:
        return _fail("claiming trade authority must fail")

    # Missing oos_untouched => FAIL (fail-closed).
    missing = promotion_gate.run_promotion_gate(dict(_empirical_ctx(), oos_untouched=None))
    if missing["overall"] != GateState.FAIL.value:
        return _fail("missing oos_untouched must FAIL")
    return _pass("authority boundary + grade ceilings + fail-closed OOS enforced")


def _check_scope_guard() -> tuple[str, str]:
    from . import pr_scope_guard
    for f in ("scripts/lib/cio_acceptance_v4.py", "apps/command-center-v3/x.tsx",
              "RELEASE_MANIFEST.json", "scripts/deploy_portfolio_server.sh"):
        if not pr_scope_guard.is_denied(f):
            return _fail(f"scope guard failed to deny {f}")
    if pr_scope_guard.is_denied("scripts/lib/research_governance/trial_registry.py"):
        return _fail("scope guard wrongly denied an allowed file")
    return _pass("scope guard denies off-limits files")


R1_CHECKS: dict[str, Callable[[], tuple[str, str]]] = {
    "RGA-1": _check_source_registry,
    "RGA-2": _check_provenance,
    "RGA-3": _check_lifecycle_separated,
    "RGA-4": _check_trial_registry,
    "RGA-5": _check_no_lookahead,
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
