"""Research governance — R1 acceptance checks with GOLDEN/REFERENCE validation.

Each check returns (state, detail). Statistical checks compare against frozen
golden vectors or decisive semantic fixtures — NOT merely "value is in [0,1]".

Golden vectors were computed independently from the published formulas (Bailey &
López de Prado DSR; Bailey/Borwein/López de Prado/Zhu PBO/CSCV; White 2000 /
Sullivan–Timmermann–White Reality Check) and frozen here so a regression that
silently flips a sign, drops a mean term, or mis-centers a null is caught.
"""
from __future__ import annotations

import math
import random
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


# --------------------------------------------------------------------------
# Golden fixtures
# --------------------------------------------------------------------------

def _dsr_trials() -> list[float]:
    return [0.2, 0.4, 0.1, 0.5, 0.3, 0.35, 0.25, 0.45, 0.15, 0.3]


def _stable_winner_matrix():
    rows = []
    for c in range(3):
        row = []
        for t in range(16):
            base = 0.02 if c == 0 else (0.005 if c == 1 else -0.005)
            row.append(base + ((t * 7 + c * 13) % 5 - 2) * 0.001)
        rows.append(row)
    return rows


def _overfit_matrix():
    rows = []
    for c in range(3):
        row = []
        for t in range(16):
            seg = t // 4
            base = 0.06 if seg == c else -0.02
            row.append(base + ((t * 7 + c * 13) % 5 - 2) * 0.001)
        rows.append(row)
    return rows


# --------------------------------------------------------------------------
# Checks
# --------------------------------------------------------------------------

def _check_source_registry() -> tuple[str, str]:
    rep = source_catalog.manifest_report()
    if not rep["manifest_ok"]:
        return _fail(f"source manifest mismatch: {rep}")
    return _pass(f"{rep['actual_books']} books + {rep['actual_primary_research']} papers; "
                 f"json_hash={rep['catalog_json_hash'][:12]}")


def _check_provenance() -> tuple[str, str]:
    s = ResearchSource(source_id="s", source_type="book", title="T")
    if s.full_text_status != "NOT_FOUND_IN_FILE_LIBRARY":
        return _fail("missing full text must be honestly recorded")
    c = ResearchClaim(claim_id="c", source_id="s", claim="x", claim_type="t",
                      source_status=ResearchStatus.SOURCE_CLAIM_INCOMPLETE)
    if c.source_status != ResearchStatus.SOURCE_CLAIM_INCOMPLETE:
        return _fail("unread source must default to SOURCE_CLAIM_INCOMPLETE")
    if not source_catalog.manifest_report()["honest_full_text_status"]:
        return _fail("some catalog entries claim full text they do not have")
    return _pass("provenance honest; unread sources remain SOURCE_CLAIM_INCOMPLETE")


def _check_lifecycle_separated() -> tuple[str, str]:
    if EvidenceType.SEASONALITY.value == ResearchStatus.OOS_SUPPORTED.value:
        return _fail("type and status must be distinct")
    if ResearchStatus.OOS_SUPPORTED.value == EvidenceGrade.B.value:
        return _fail("status and grade must be distinct")
    if EvidenceGrade.B.value == EvidenceType.SEASONALITY.value:
        return _fail("grade and type must be distinct")
    return _pass("type / status / grade are orthogonal enums")


def _check_trial_registry() -> tuple[str, str]:
    reg = trial_registry.TrialRegistry()
    reg.freeze_family(
        "fam1", "h1", protocol_hash="ph1",
        planned_trials=[("t1", "cfg1"), ("t2", "cfg2"), ("t3", "cfg3")],
    )
    reg.record_trial("fam1", "t1", config_hash="cfg1", result_payload={"sharpe": 0.5})
    reg.record_trial("fam1", "t2", config_hash="cfg2", result_payload={"sharpe": -0.1})
    reg.record_trial("fam1", "t3", config_hash="cfg3", result_payload={"sharpe": 0.0})
    reg.record_selection("fam1", "t1", True, reason="winner")
    reg.record_selection("fam1", "t2", False)
    rep = reg.completeness_report("fam1")
    if not rep["complete"]:
        return _fail(f"fully accounted family should be complete: {rep}")
    if rep["losing_count"] != 1:
        return _fail(f"expected 1 losing selection, got {rep['losing_count']}")

    # Incomplete: a planned trial without a terminal outcome blocks completeness.
    reg2 = trial_registry.TrialRegistry()
    reg2.freeze_family("fam2", "h2", protocol_hash="ph2",
                       planned_trials=[("a", "c1"), ("b", "c2")])
    reg2.record_trial("fam2", "a", config_hash="c1", result_payload={"x": 1})
    if reg2.completeness_report("fam2")["complete"]:
        return _fail("family with an unaccounted planned trial must be incomplete")
    return _pass("frozen family requires every planned variant accounted; losers recorded")


def _check_no_lookahead() -> tuple[str, str]:
    reg = trial_registry.TrialRegistry()
    # Cannot record a trial before freezing (no peek at data without a frozen family).
    try:
        reg.record_trial("nope", "t1", config_hash="c1", result_payload={"x": 1})
        return _fail("recording a trial before freeze must be rejected")
    except ValueError:
        pass
    # OOS consumption is terminal: a consumed window cannot be treated as untouched.
    reg.freeze_family("f", "h", protocol_hash="ph", planned_trials=[("t1", "c1")])
    reg.register_oos_window("f", "w1", oos_generation=1)
    reg.consume_oos_window("f", "w1")
    if reg.oos_is_untouched("f", "w1"):
        return _fail("consumed OOS window must not report untouched")
    return _pass("no-lookahead: freeze-before-trial + terminal OOS consumption")


def _check_multiple_testing() -> tuple[str, str]:
    pvals = [0.001, 0.01, 0.2, 0.5]
    b = multiple_testing.bonferroni(pvals, alpha=0.05)
    if b["rejected"] != [True, True, False, False]:
        return _fail(f"bonferroni wrong: {b['rejected']}")
    if multiple_testing.holm(pvals, alpha=0.05)["rejected"] != [True, True, False, False]:
        return _fail("holm wrong")
    if not multiple_testing.benjamini_hochberg(pvals, alpha=0.05)["rejected"][0]:
        return _fail("BH should reject the smallest p")
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
    # Translation invariance: +c on every trial Sharpe => +c on the benchmark.
    r2 = deflated_sharpe.deflated_benchmark_sr([x + 0.5 for x in trials], 10)
    if abs((r2["deflated_benchmark_sr"] - r["deflated_benchmark_sr"]) - 0.5) > 1e-9:
        return _fail("DSR benchmark must be translation-invariant")
    # Unknown trial count => UNAVAILABLE (never silently single-trial).
    if deflated_sharpe.deflated_sharpe(1.0, 100, 0.0, 3.0, [], None)["status"] != "UNAVAILABLE":
        return _fail("DSR with unknown trials must be UNAVAILABLE")
    return _pass("DSR golden + translation invariance correct")


def _check_pbo() -> tuple[str, str]:
    if pbo.cscv_probability_of_backtest_overfitting([[0.01, 0.02]])["status"] != "NOT_APPLICABLE":
        return _fail("PBO with single config must be NOT_APPLICABLE")
    stable = pbo.cscv_probability_of_backtest_overfitting(_stable_winner_matrix(), n_subsets=4, seed=0)
    overfit = pbo.cscv_probability_of_backtest_overfitting(_overfit_matrix(), n_subsets=4, seed=0)
    if stable["pbo"] >= 0.5:
        return _fail(f"stable winner should be LOW PBO, got {stable['pbo']!r}")
    if overfit["pbo"] <= 0.5:
        return _fail(f"overfit rotating winner should be HIGH PBO, got {overfit['pbo']!r}")
    return _pass(f"PBO rank semantics correct (stable={stable['pbo']:.2f}, overfit={overfit['pbo']:.2f})")


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

    # Family correction is no more favorable than cherry-picking the winner.
    strong = [0.2 + rng.gauss(0, 1) for _ in range(100)]
    weak = [[rng.gauss(0, 1) for _ in range(100)] for _ in range(4)]
    p_single = bootstrap_reality_check.reality_check_pvalue([strong], n_bootstrap=1000, seed=1)
    p_family = bootstrap_reality_check.reality_check_pvalue([strong] + weak, n_bootstrap=1000, seed=1)
    p_single_v = p_single["bootstrap_pvalue"]
    p_family_v = p_family["bootstrap_pvalue"]
    if p_family_v < p_single_v:
        return _fail(f"family correction must not be MORE significant than winner-only "
                     f"(family={p_family_v} < single={p_single_v})")
    return _pass("Reality Check null/alternative/family semantics correct")


def _check_cv_purging() -> tuple[str, str]:
    # labels spaced so earlier samples do not overlap the test block.
    labels = [(i * 3, i * 3 + 1) for i in range(9)]
    folds = cv.purged_walk_forward(9, labels, n_splits=3, embargo=100)
    # Walk-forward fold 1: test [3,4,5], earlier training [0,1,2] must SURVIVE a
    # large embargo (embargo does not erase pre-test history).
    if folds[1]["train"] != [0, 1, 2]:
        return _fail(f"walk-forward erased pre-test history under embargo: {folds[1]}")

    # Purged k-fold: post-test samples inside the embargo are removed; samples
    # after the embargo remain.
    labels2 = [(i * 3, i * 3 + 1) for i in range(9)]
    kf = cv.purged_kfold(9, labels2, n_splits=3, embargo=3)
    fold0 = kf[0]  # test [0,1,2]; post-test training 3..8
    if 3 in fold0["train"]:
        return _fail("post-test sample inside embargo should be removed from k-fold training")
    if 4 not in fold0["train"]:
        return _fail("post-test sample after the embargo window must remain in training")

    parts = cv.combinatorial_purged_cv(9, labels2, n_groups=3, n_test_groups=1, embargo=0)
    if len(parts) != 3:
        return _fail(f"CPCV should yield C(3,1)=3 partitions, got {len(parts)}")
    for p in parts:
        if not p["test"]:
            return _fail("CPCV test set empty")
    return _pass("walk-forward / purged-k-fold / CPCV semantics correct")


def _check_promotion_contract() -> tuple[str, str]:
    if set(promotion_gate.GATE_IDS) != {f"RG-{i}" for i in range(12)}:
        return _fail("promotion gate must define RG-0..RG-11")
    names = {gid: promotion_gate._GATES[i][1] for i, gid in
             enumerate(f"RG-{k}" for k in range(12))}
    if names.get("RG-10") != "decision_use_audit":
        return _fail("RG-10 must be decision_use_audit")
    if names.get("RG-11") != "live_degradation_retirement":
        return _fail("RG-11 must be live_degradation_retirement")
    return _pass("promotion-gate contract present; RG-10/11 mapping restored")


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
    if not retrieval_contract.validate_retrieval_result(ev):
        return _fail("OOS_SUPPORTED with grade D should fail validation")
    return _pass("retrieval contract present + fail-closed validation")


def _check_authority_boundary() -> tuple[str, str]:
    base = {
        "source_id": "s", "claim": "c", "page_or_section": "p", "scope": "us",
        "evidence_type": EvidenceType.EMPIRICAL_STRATEGY.value,
        "protocol_hash": "ph", "trial_family_id": "f", "family_frozen": True,
        "code_sha": "c0", "dataset_hash": "d0",
        "in_sample_metric": 1.0, "in_sample_threshold": 0.0,
        "oos_supported": True, "oos_untouched": True,
        "multiple_testing": {"rejected_any": True},
        "reality_check": {"bootstrap_pvalue": 0.01},
        "robustness": {"subperiods": True, "regimes": True, "costs": True},
        "evidence_grade": "A",
        "influence_class": InfluenceClass.VALUATION_INPUT.value,
    }
    ok = promotion_gate.run_promotion_gate(dict(base))
    if ok["promotion_state"] != "CIO_CONTEXT_ELIGIBLE":
        return _fail(f"valid A-grade empirical should reach CIO_CONTEXT_ELIGIBLE: {ok['promotion_state']}")

    # Grade X never promotes.
    x = promotion_gate.run_promotion_gate(dict(base, evidence_grade="X"))
    if x["promotion_state"] != "INVALIDATED" or x["overall"] != GateState.FAIL.value:
        return _fail("grade X must be INVALIDATED/FAIL")
    # Grade D cannot reach CIO context.
    d = promotion_gate.run_promotion_gate(dict(base, evidence_grade="D"))
    if d["promotion_state"] != "SOURCE_ONLY":
        return _fail("grade D must cap at SOURCE_ONLY")
    # Grade C cannot reach live CIO context.
    c = promotion_gate.run_promotion_gate(dict(base, evidence_grade="C"))
    if c["promotion_state"] != "EXPLORATORY_SHADOW":
        return _fail("grade C must cap at EXPLORATORY_SHADOW")
    # Trade authority claim blocks.
    ta = promotion_gate.run_promotion_gate(dict(base, claims_trade_authority=True))
    if ta["overall"] != GateState.FAIL.value:
        return _fail("claiming trade authority must fail")
    return _pass("authority boundary + grade ceilings enforced")


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
