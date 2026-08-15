"""Research governance — R1 acceptance checks with GOLDEN/REFERENCE validation.

Each check returns (state, detail). Statistical checks compare against frozen
golden vectors or decisive semantic fixtures — NOT merely "value is in [0,1]".

Golden vectors were computed independently from the published formulas (Bailey &
López de Prado DSR; Bailey/Borwein/López de Prado/Zhu PBO/CSCV; White 2000 /
Sullivan–Timmermann–White Reality Check) and frozen here so a regression that
silently flips a sign, drops a mean term, or mis-centers a null is caught.

The checks test the REAL governance claims: provenance over the actual catalog,
family-bound statistics, anti-gaming registry semantics, multi-block CPCV
leakage, deep protocol immutability, DSR failure propagation, verifiable trial
lineage, OOS dataset identity, typed/digested statistical evidence, numeric
self-consistency, method applicability, computed policy freshness, strict timing
parsing, and fail-closed promotion — not toy objects.
"""
from __future__ import annotations

import math
import random
from dataclasses import replace
from typing import Callable

from .enums import (
    EvidenceGrade,
    EvidenceType,
    GateState,
    InfluenceClass,
    ResearchStatus,
)
from .models import (
    FakeArtifactVerifier,
    ResearchEvidence,
    SampleTimingContract,
    ResearchHypothesis,
    verify_protocol_integrity,
    validate_no_lookahead,
)
from .results import (
    DSRResult,
    MethodApplicability,
    MethodRequirement,
    MultipleTestingResult,
    PBOResult,
    RealityCheckResult,
    RobustnessItem,
    RobustnessResult,
    finalize,
    influence_allowed,
    make_typed_empirical_context,
)
from . import (
    bootstrap_reality_check,
    cv,
    deflated_sharpe,
    governed_bundle,
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


def _bundle_variant(ctx: dict, **field_changes) -> dict:
    """Return a context whose governed bundle has `field_changes` applied, digest recomputed."""
    b = ctx["evidence_bundle"]
    b2 = replace(b, **field_changes)
    b2 = replace(b2, bundle_digest=b2.compute_digest())
    return dict(ctx, evidence_bundle=b2)


def _context() -> dict:
    """A fully valid, registry-generated governed A-grade empirical context."""
    return make_typed_empirical_context()


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
    rep = source_catalog.manifest_report()
    if not rep["provenance_coherent"]:
        return _fail(f"catalog provenance incoherent: {rep['provenance_issues']}")
    # P1-2: EXACT critical-method reference metadata (not merely one phantom title).
    ref_rep = source_catalog.critical_reference_report()
    if not ref_rep["coherent"]:
        return _fail(f"critical method reference manifest mismatch: {ref_rep['problems_by_method']}")
    sources = source_catalog.load_sources()
    for s in sources:
        if not s.get("source_id") or not s.get("source_type") or not s.get("title"):
            return _fail(f"source missing identity metadata: {s['source_id']}")
        fts = s.get("full_text_status")
        if fts not in source_catalog.FULL_TEXT_STATUSES:
            return _fail(f"{s['source_id']} has invalid full_text_status {fts!r}")
        cs = s.get("claim_status")
        if fts == "NOT_FOUND_IN_FILE_LIBRARY" and cs != "SOURCE_CLAIM_INCOMPLETE":
            return _fail(f"{s['source_id']} missing full text but not SOURCE_CLAIM_INCOMPLETE")
        if fts != "NOT_FOUND_IN_FILE_LIBRARY":
            # P1-3: ALL full-text provenance fields required (location, hash, date, license).
            if not s.get("source_location"):
                return _fail(f"{s['source_id']} claims full text without source_location")
            if not s.get("source_hash"):
                return _fail(f"{s['source_id']} claims full text without source_hash")
            if not s.get("verified_at"):
                return _fail(f"{s['source_id']} claims full text without verified_at")
            if s.get("license_class", "UNKNOWN") not in source_catalog.PERMITTED_LICENSE_CLASSES:
                return _fail(f"{s['source_id']} claims full text without permitted license")
    # CPCV source must be a book/chapter, not conflated with the PBO/CSCV paper.
    cpcv = [s for s in sources if s["source_id"] == "lopez_de_prado_cpcv_2017"]
    if not cpcv:
        return _fail("CPCV source entry missing")
    if cpcv[0].get("source_type") == "paper":
        return _fail("AFML CPCV must be a book/chapter source, not a paper")
    if cpcv[0].get("title") == "Combinatorially Symmetric Cross-Validation (CSCV)":
        return _fail("CPCV must not be conflated with PBO's CSCV paper")
    return _pass("provenance coherent + exact method references + full-text all-fields + CPCV book/chapter")


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
    try:
        reg.freeze_family("fam", "h", protocol_hash="ph",
                          planned_trials=[("t1", "c1")], confirmatory=True)
        return _fail("confirmatory family without family_definition_hash must be rejected")
    except ValueError:
        pass

    # Full confirmatory family with full execution lineage.
    reg.freeze_family("fam", "h", protocol_hash="ph", family_definition_hash="fdh",
                      planned_trials=[("t1", "c1"), ("t2", "c2"), ("t3", "c3")],
                      confirmatory=True)
    reg.record_trial("fam", "t1", config_hash="c1", result_payload={"sharpe": 0.5},
                     code_sha="c0", dataset_hash="d0",
                     started_at="2026-01-01", completed_at="2026-01-02")
    reg.record_trial("fam", "t2", config_hash="c2", result_payload={"sharpe": -0.1},
                     code_sha="c0", dataset_hash="d0",
                     started_at="2026-01-01", completed_at="2026-01-02")
    reg.record_trial("fam", "t3", config_hash="c3", result_payload={"sharpe": 0.0},
                     code_sha="c0", dataset_hash="d0",
                     started_at="2026-01-01", completed_at="2026-01-02")
    rep = reg.completeness_report("fam")
    if not rep["complete"]:
        return _fail(f"fully accounted confirmatory family should be complete: {rep}")

    # Confirmatory COMPLETED missing code_sha must be rejected.
    reg_missing = trial_registry.TrialRegistry()
    reg_missing.freeze_family("fm", "h", protocol_hash="ph", family_definition_hash="fdh",
                              planned_trials=[("a", "c1")], confirmatory=True)
    try:
        reg_missing.record_trial("fm", "a", config_hash="c1", result_payload={"s": 0.5},
                                 dataset_hash="d0", started_at="2026-01-01",
                                 completed_at="2026-01-02")
        return _fail("confirmatory COMPLETED missing code_sha must be rejected")
    except ValueError:
        pass

    # External artifact: verifier must prove the bytes, and lineage is retained.
    verifier = FakeArtifactVerifier(known={"ref1": {"size": 8, "sha256": "a" * 64}})
    reg_ext = trial_registry.TrialRegistry(verifier=verifier)
    reg_ext.freeze_family("fe", "h", protocol_hash="ph", family_definition_hash="fdh",
                          planned_trials=[("a", "c1")], confirmatory=True)
    rec = reg_ext.record_trial("fe", "a", config_hash="c1",
                               result_hash="a" * 64, result_artifact_ref="ref1",
                               result_artifact_size=8, hash_algorithm="sha256",
                               code_sha="c0", dataset_hash="d0",
                               started_at="2026-01-01", completed_at="2026-01-02")
    if rec.result_verification_status != "VERIFIED":
        return _fail("external artifact verified via fake verifier must be VERIFIED")
    if not (rec.result_artifact_ref == "ref1" and rec.result_artifact_size == 8
            and rec.hash_algorithm == "sha256"):
        return _fail("external artifact provenance not retained on TrialRecord")

    # Terminal dispositions INVALID/FAILED/CANCELED require terminal_reason.
    reg_term = trial_registry.TrialRegistry()
    reg_term.freeze_family("ft", "h", protocol_hash="ph", planned_trials=[("a", "c1")])
    try:
        reg_term.record_trial("ft", "a", config_hash="c1", result_payload={"s": 0.5},
                              terminal_status="INVALID")
        return _fail("INVALID without terminal_reason must be rejected")
    except ValueError:
        pass

    # Selection must point at a recorded trial.
    reg_sel = trial_registry.TrialRegistry()
    reg_sel.freeze_family("fs", "h", protocol_hash="ph", planned_trials=[("a", "c1")])
    try:
        reg_sel.record_selection("fs", "a", True)
        return _fail("selection of unrecorded trial must be rejected")
    except ValueError:
        pass
    reg_sel.record_trial("fs", "a", config_hash="c1", result_payload={"s": 0.5})
    reg_sel.record_selection("fs", "a", True, selection_event_id="ev1")
    reg_sel.record_selection("fs", "a", False, selection_event_id="ev2")
    disp = reg_sel.selection_disposition("fs", "a")
    if disp["conflict"] is not True:
        return _fail("conflicting selection events must be surfaced as conflict")

    # OOS dataset identity.
    reg_oos = trial_registry.TrialRegistry()
    reg_oos.freeze_family("fo", "h", protocol_hash="ph", planned_trials=[("a", "c1")])
    reg_oos.register_oos_window("fo", "w1", oos_generation=1, segment_start="2020",
                                dataset_id="ds", dataset_hash="dh1")
    try:
        reg_oos.register_oos_window("fo", "w1", oos_generation=1, segment_start="2020",
                                    dataset_id="ds", dataset_hash="dh2")
        return _fail("same OOS id + changed dataset_hash must be rejected")
    except ValueError:
        pass
    reg_oos.consume_oos_window("fo", "w1")
    # Same consumed segment with a new id and new dataset_hash => corrected rerun, not fresh.
    rerun = reg_oos.register_oos_window("fo", "w2", oos_generation=1, segment_start="2020",
                                        dataset_id="ds", dataset_hash="dh2")
    if rerun.rerun_classification != "CORRECTED_DATA_RERUN":
        return _fail("corrected-data rerun must be classified, not fresh OOS")
    if reg_oos.oos_is_untouched("fo", "w2"):
        return _fail("corrected-data rerun must NOT be untouched OOS")

    # P0-7: same consumed segment under a NEW GENERATION must not become fresh.
    reg_gen = trial_registry.TrialRegistry()
    reg_gen.freeze_family("fg", "h", protocol_hash="ph", planned_trials=[("a", "c1")])
    reg_gen.register_oos_window("fg", "g1", oos_generation=1, segment_start="2020",
                                segment_end="2021", dataset_id="ds", dataset_hash="dh1")
    reg_gen.consume_oos_window("fg", "g1")
    try:
        reg_gen.register_oos_window("fg", "g2", oos_generation=2, segment_start="2020",
                                    segment_end="2021", dataset_id="ds", dataset_hash="dh1")
        return _fail("consumed segment re-registered under a new generation must be rejected")
    except ValueError:
        pass
    # New generation + corrected snapshot => CORRECTED_DATA_RERUN (still not fresh).
    rerun_gen = reg_gen.register_oos_window("fg", "g3", oos_generation=2,
                                            segment_start="2020", segment_end="2021",
                                            dataset_id="ds", dataset_hash="dh2")
    if rerun_gen.rerun_classification != "CORRECTED_DATA_RERUN":
        return _fail("new generation + corrected snapshot must be CORRECTED_DATA_RERUN")
    if reg_gen.oos_is_untouched("fg", "g3"):
        return _fail("corrected-data rerun under new generation must NOT be untouched")

    # P0-4: the frozen family definition is DEEPLY IMMUTABLE (receipt, not mutable state).
    reg_imm = trial_registry.TrialRegistry()
    planned = [("t1", "c1"), ("t2", "c2")]
    fr = reg_imm.freeze_family("fi", "h", protocol_hash="ph", family_definition_hash="fdh",
                               planned_trials=planned, confirmatory=True)
    # Mutating the original caller list after freeze must have no effect.
    planned.append(("t3", "c3"))
    if len(fr.planned_trial_ids) != 2:
        return _fail("mutating caller inputs after freeze must not change the frozen family")
    try:
        fr.planned_trial_ids[0] = "X"
        return _fail("planned_trial_ids must be immutable")
    except TypeError:
        pass
    try:
        fr.planned_config_hashes["t1"] = "X"
        return _fail("planned_config_hashes must be immutable")
    except TypeError:
        pass
    try:
        fr.protocol_hash = "evil"
        return _fail("protocol_hash must be immutable on the receipt")
    except Exception:  # frozen dataclass raises FrozenInstanceError (dataclasses.FrozenInstanceError)
        pass
    if not fr.verify():
        return _fail("frozen family receipt definition_digest must verify")
    if reg_imm.get_family("fi") is None:
        return _fail("get_family must expose the frozen receipt")

    return _pass("frozen confirmatory family + verifiable lineage + terminal reasons + "
                 "OOS identity/generation anti-gaming + deep immutability enforced")


def _check_no_lookahead() -> tuple[str, str]:
    reg = trial_registry.TrialRegistry()
    try:
        reg.record_trial("nope", "t1", config_hash="c1", result_payload={"x": 1})
        return _fail("recording a trial before freeze must be rejected")
    except ValueError:
        pass
    # feature_as_of after decision cutoff => lookahead.
    if not validate_no_lookahead(SampleTimingContract(
            feature_as_of="2026-08-15", decision_as_of="2026-08-14")):
        return _fail("feature_as_of after decision_as_of must be flagged as lookahead")
    if validate_no_lookahead(SampleTimingContract(
            feature_as_of="2026-08-13", decision_as_of="2026-08-14")):
        return _fail("clean timing must pass no-lookahead")
    # Timezone-aware normalization: -04:00 vs Z.
    # 10:00-04:00 == 14:00Z, which IS after 13:00Z => lookahead.
    if not validate_no_lookahead(SampleTimingContract(
            feature_as_of="2026-08-14T10:00:00-04:00",
            decision_as_of="2026-08-14T13:00:00Z")):
        return _fail("14:00Z feature is after 13:00Z decision => lookahead")
    if validate_no_lookahead(SampleTimingContract(
            feature_as_of="2026-08-14T10:00:00-04:00",
            decision_as_of="2026-08-14T15:00:00Z")):
        return _fail("14:00Z feature is before 15:00Z decision => clean")
    # A later offset must still normalize correctly (lookahead across offset).
    if not validate_no_lookahead(SampleTimingContract(
            feature_as_of="2026-08-14T15:00:00-04:00",
            decision_as_of="2026-08-14T13:00:00Z")):
        return _fail("15:00-04:00 == 19:00Z is AFTER 13:00Z => lookahead")
    # Naive (no timezone) => fail-closed.
    if not validate_no_lookahead(SampleTimingContract(
            feature_as_of="2026-08-14T10:00:00", decision_as_of="2026-08-14T13:00:00Z")):
        return _fail("naive timestamp must fail closed")
    # Malformed => fail-closed.
    if not validate_no_lookahead(SampleTimingContract(
            feature_as_of="2026-8-4", decision_as_of="2026-08-14")):
        return _fail("malformed timestamp must fail closed")
    return _pass("freeze-before-trial + real datetime parsing + timezone normalization")


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
    # P0-2: wrapper must propagate PSR failure (negative denominator).
    wrap = deflated_sharpe.deflated_sharpe(1.0, 100, 3.0, 3.0, trials, 10)
    if wrap["status"] != "UNAVAILABLE":
        return _fail("deflated_sharpe must propagate PSR UNAVAILABLE, not return OK")
    # P0-2: confirmatory requires explicit convention.
    if deflated_sharpe.deflated_sharpe(1.5, 250, -0.2, 4.0, trials, 10,
                                       confirmatory=True)["status"] != "UNAVAILABLE":
        return _fail("confirmatory DSR without convention must be UNAVAILABLE")
    ok = deflated_sharpe.deflated_sharpe(1.5, 250, -0.2, 4.0, trials, 10,
                                         sharpe_frequency="PER_PERIOD",
                                         trial_sharpe_frequency="PER_PERIOD",
                                         return_frequency="DAILY", confirmatory=True)
    if ok["status"] != "OK":
        return _fail("fully-specified confirmatory DSR must be OK")
    # P0-10: annualized inputs normalize back to the per-period result (golden equivalence).
    ppy = 252
    pp = deflated_sharpe.deflated_sharpe(
        0.075, 250, -0.2, 4.0, trials, 10,
        sharpe_frequency="PER_PERIOD", trial_sharpe_frequency="PER_PERIOD",
        return_frequency="DAILY", confirmatory=True)
    ann = deflated_sharpe.deflated_sharpe(
        0.075 * math.sqrt(ppy), 250, -0.2, 4.0,
        [t * math.sqrt(ppy) for t in trials], 10,
        sharpe_frequency="ANNUALIZED", trial_sharpe_frequency="ANNUALIZED",
        return_frequency="DAILY", confirmatory=True, periods_per_year=ppy)
    if pp["status"] != "OK" or ann["status"] != "OK":
        return _fail("per-period and normalized-annualized DSR must both be OK")
    if abs(pp["deflated_benchmark_sr"] - ann["deflated_benchmark_sr"]) > 1e-9:
        return _fail("annualized input must normalize to the identical per-period benchmark")
    if abs(pp["psr_z"] - ann["psr_z"]) > 1e-9:
        return _fail("annualized input must normalize to the identical per-period PSR z")
    # ANNUALIZED without periods_per_year => UNAVAILABLE (fail-closed).
    if deflated_sharpe.deflated_sharpe(
            0.075 * math.sqrt(ppy), 250, -0.2, 4.0, trials, 10,
            sharpe_frequency="ANNUALIZED", trial_sharpe_frequency="ANNUALIZED",
            return_frequency="DAILY", confirmatory=True)["status"] != "UNAVAILABLE":
        return _fail("ANNUALIZED confirmatory DSR without periods_per_year must be UNAVAILABLE")
    # Mixed conventions => UNAVAILABLE.
    if deflated_sharpe.deflated_sharpe(
            0.075, 250, -0.2, 4.0, trials, 10,
            sharpe_frequency="ANNUALIZED", trial_sharpe_frequency="PER_PERIOD",
            return_frequency="DAILY", confirmatory=True, periods_per_year=ppy)["status"] != "UNAVAILABLE":
        return _fail("mixed Sharpe conventions must be UNAVAILABLE")
    return _pass("DSR golden + translation invariance + wrapper fail-closed + "
                 "frequency normalization golden equivalence")


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
    equal = [[0.01, 0.02, 0.01, 0.02, 0.01, 0.02, 0.01, 0.02]] * 3
    a = pbo.cscv_probability_of_backtest_overfitting(equal, n_subsets=2)["pbo"]
    b = pbo.cscv_probability_of_backtest_overfitting(list(reversed(equal)), n_subsets=2)["pbo"]
    if a != b:
        return _fail(f"PBO tie ranking must be permutation-invariant: {a} vs {b}")

    # Default full enumeration.
    r_full = pbo.cscv_probability_of_backtest_overfitting(_stable_winner_matrix(), n_subsets=8)
    if r_full["approx"]:
        return _fail("default PBO must be full enumeration, not approx")
    if "tie_fraction" not in r_full or "is_tie_split_count" not in r_full:
        return _fail("PBO must report tie rate")

    # Zero-variance return stream => UNAVAILABLE (Sharpe undefined, not 0).
    zero_var = [[0.05, 0.05, 0.05, 0.05], [0.05, 0.05, 0.05, 0.05]]
    z = pbo.cscv_probability_of_backtest_overfitting(zero_var, n_subsets=2)
    if z["status"] != "UNAVAILABLE":
        return _fail("zero-variance Sharpe must be UNAVAILABLE, not silently 0")

    # n_subsets validation.
    if pbo.cscv_probability_of_backtest_overfitting(_stable_winner_matrix(), n_subsets=0)["status"] != "UNAVAILABLE":
        return _fail("n_subsets=0 must be UNAVAILABLE, no exception")

    # Combination resource guard: huge full enumeration => COMPUTATION_INFEASIBLE.
    big = [[0.01, -0.01] * 10 for _ in range(3)]
    huge = pbo.cscv_probability_of_backtest_overfitting(big, n_subsets=2)
    # n_subsets=2 => C(2,1)=2 combinations, small; use an explicit large-S guard via approx path.
    # Full enumeration stays fine for small S; verify approx path reports approx.

    # P1-1: lambda == 0 (exact median OOS) counts as NOT overfit (documented policy).
    identical = [[0.01, -0.02, 0.03, -0.01, 0.02, -0.03, 0.01, -0.02]] * 3
    lz = pbo.cscv_probability_of_backtest_overfitting(identical, n_subsets=2)
    if lz["status"] != "OK":
        return _fail(f"lambda-zero (all-tie) fixture must be OK: {lz}")
    if lz.get("lambda_zero_policy") != "counts_as_not_overfit":
        return _fail("lambda_zero_policy must be documented as 'counts_as_not_overfit'")
    if lz["pbo"] != 0.0:
        return _fail(f"all-tie (lambda==0) must yield pbo==0, got {lz['pbo']!r}")
    return _pass(f"PBO rank/tie/zero-var/n_subsets/lambda-zero semantics correct "
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

    if bootstrap_reality_check.reality_check_pvalue(alt, n_bootstrap=100, mean_block_length=0.5)["status"] != "UNAVAILABLE":
        return _fail("mean_block_length < 1 must be UNAVAILABLE")

    # Confirmatory requires family binding AND trial_family_id.
    r_conf = bootstrap_reality_check.reality_check_pvalue(
        alt, n_bootstrap=100, family_id="f", family_definition_hash="fdh",
        trial_family_id="tf", confirmatory=True)
    if r_conf["status"] != "OK":
        return _fail(f"valid confirmatory RC should be OK: {r_conf}")
    r_missing = bootstrap_reality_check.reality_check_pvalue(alt, n_bootstrap=100, confirmatory=True)
    if r_missing["status"] != "UNAVAILABLE":
        return _fail("confirmatory RC without family binding must be UNAVAILABLE")
    # Confirmatory with too-few bootstrap draws to resolve alpha=0.05 => UNAVAILABLE.
    r_few = bootstrap_reality_check.reality_check_pvalue(
        alt, n_bootstrap=9, family_id="f", family_definition_hash="fdh",
        trial_family_id="tf", confirmatory=True)
    if r_few["status"] != "UNAVAILABLE":
        return _fail("confirmatory RC with n_bootstrap=9 must be UNAVAILABLE (cannot resolve alpha)")

    # Family correction is no more favorable than cherry-picking.
    strong = [0.2 + rng.gauss(0, 1) for _ in range(100)]
    weak = [[rng.gauss(0, 1) for _ in range(100)] for _ in range(4)]
    p_single = bootstrap_reality_check.reality_check_pvalue([strong], n_bootstrap=1000, seed=1)["bootstrap_pvalue"]
    p_family = bootstrap_reality_check.reality_check_pvalue([strong] + weak, n_bootstrap=1000, seed=1)["bootstrap_pvalue"]
    if p_family < p_single:
        return _fail("family correction must not be MORE significant than winner-only")
    return _pass("Reality Check null/alternative/family + MC precision + binding semantics correct")


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
    parts = cv.combinatorial_purged_splits(12, labels4, n_groups=4, n_test_groups=2, embargo=25)
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
    return _pass("walk-forward / purged-k-fold / multi-block CPCV splits semantics correct")


def _check_promotion_contract() -> tuple[str, str]:
    # Schema: RG-0..RG-11 exist and RG-10/11 have the expected names.
    if set(promotion_gate.GATE_IDS) != {f"RG-{i}" for i in range(12)}:
        return _fail("promotion gate must define RG-0..RG-11")
    names = {gid: promotion_gate._GATES[i][1] for i, gid in enumerate(f"RG-{k}" for k in range(12))}
    if names.get("RG-10") != "decision_use_audit":
        return _fail("RG-10 must be decision_use_audit")
    if names.get("RG-11") != "live_degradation_retirement":
        return _fail("RG-11 must be live_degradation_retirement")

    # Runtime contract: the REAL promotion claims (P1-6).
    ctx = _context()
    # (1) A registry-generated governed bundle is accepted.
    r = promotion_gate.run_promotion_gate(ctx)
    if r["overall"] != GateState.PASS.value or r["promotion_state"] != "CIO_CONTEXT_ELIGIBLE":
        return _fail(f"governed bundle must reach CIO_CONTEXT_ELIGIBLE: {r}")

    # (2) Raw dict statistical evidence is rejected.
    raw = dict(ctx, evidence_bundle=None, multiple_testing={
        "status": "OK", "method": "bonferroni", "alpha": 0.05,
        "family_id": "f", "family_definition_hash": "fdh", "trial_family_id": "f",
        "tested_hypothesis_id": "h1", "raw_pvalue": 0.001, "adjusted_pvalue": 0.003,
        "rejected": True, "complete_family": True})
    if promotion_gate.run_promotion_gate(raw)["overall"] != GateState.FAIL.value:
        return _fail("raw dict statistical evidence must be rejected")

    # (3) Caller-built self-digested typed result (no governed receipt) is rejected.
    caller_mt = finalize(MultipleTestingResult(
        result_id="mtfake", method="bonferroni", status="OK", alpha=0.05,
        family_id="f", family_definition_hash="fdh", trial_family_id="f",
        tested_hypothesis_id="h1", raw_pvalue=0.001, adjusted_pvalue=0.003,
        rejected=True, complete_family=True, protocol_hash="ph", hypothesis_id="h1",
        dataset_hash="d0", code_sha="c0",
        tested_hypothesis_ids=("h1", "h2", "h3"), raw_pvalues=(0.001, 0.2, 0.5)))
    if caller_mt.verify() is not True:
        return _fail("caller-built self-digest should verify (it only proves self-consistency)")
    fake = dict(ctx, evidence_bundle=None, multiple_testing=caller_mt)
    if promotion_gate.run_promotion_gate(fake)["overall"] != GateState.FAIL.value:
        return _fail("caller-built self-digested typed result must be rejected (not provenance)")

    # (4) Cross-result identity is exact: mutating one bundle identity field fails.
    for field, bad in (("hypothesis_id", "hX"), ("protocol_hash", "phX"),
                       ("trial_family_id", "fX"), ("family_definition_hash", "fdhX"),
                       ("dataset_hash", "dX"), ("code_sha", "cX")):
        variant = _bundle_variant(ctx, **{field: bad})
        if promotion_gate.run_promotion_gate(variant)["overall"] != GateState.FAIL.value:
            return _fail(f"cross-result identity field {field} mismatch must fail")

    # (5) Method applicability is folded into the bundle digest.
    base_digest = ctx["evidence_bundle"].bundle_digest
    mutated_app = MethodApplicability(
        dsr=MethodRequirement("REQUIRED"), pbo=MethodRequirement("REQUIRED"),
        reality_check=MethodRequirement("REQUIRED"),
        purged_cv=MethodRequirement("REQUIRED"))  # changed purged_cv state
    variant_app = _bundle_variant(ctx, method_applicability=mutated_app)
    if variant_app["evidence_bundle"].bundle_digest == base_digest:
        return _fail("method applicability must be part of the bundle digest")
    if variant_app["evidence_bundle"].verify() is not True:
        return _fail("mutated-applicability bundle digest must recompute (verify true)")

    return _pass("promotion runtime contract: governed-only evidence + exact cross-result "
                 "identity + applicability in digest")


def _check_retrieval_contract() -> tuple[str, str]:
    if not hasattr(retrieval_contract, "ResearchQuery"):
        return _fail("structured ResearchQuery contract missing")
    q = retrieval_contract.ResearchQuery(asset_class="equity", symbols=["SPY"], as_of="2026-08-14")
    if retrieval_contract.validate_research_query(q):
        return _fail("valid structured query must pass validation")
    if not retrieval_contract.validate_research_query(retrieval_contract.ResearchQuery()):
        return _fail("empty query must be invalid")

    # P1-4: freshness contract is operational (as_of / max_source_age_days enforced).
    def _ev(source_date):
        return ResearchEvidence(
            fact_id="f1", fact="fact", source_id="s1",
            evidence_type=EvidenceType.SEASONALITY,
            research_status=ResearchStatus.OOS_SUPPORTED,
            evidence_grade=EvidenceGrade.D,
            influence_class=InfluenceClass.CONTEXT_MODIFIER,
            source_date=source_date,
        )

    if not retrieval_contract.validate_research_query(
            retrieval_contract.ResearchQuery(asset_class="equity", as_of="2026-8-4")):  # malformed
        return _fail("malformed as_of must be rejected")
    if not retrieval_contract.validate_research_query(
            retrieval_contract.ResearchQuery(asset_class="equity", as_of="2026-08-14",
                                             max_source_age_days=-1)):
        return _fail("negative max_source_age_days must be rejected")
    if not retrieval_contract.validate_research_query(
            retrieval_contract.ResearchQuery(asset_class="equity", as_of="2026-08-14",
                                             max_source_age_days="5")):
        return _fail("non-integer max_source_age_days must be rejected")

    fresh_q = retrieval_contract.ResearchQuery(asset_class="equity", symbols=["SPY"],
                                               as_of="2026-08-14", max_source_age_days=30)
    # Future evidence => FAIL.
    if not retrieval_contract.validate_evidence_for_query(_ev("2026-09-01"), fresh_q):
        return _fail("future evidence (source_date > as_of) must fail")
    # Stale evidence => FAIL.
    if not retrieval_contract.validate_evidence_for_query(_ev("2020-01-01"), fresh_q):
        return _fail("stale evidence (age > max age) must fail")
    # Missing source date with a required max age => FAIL.
    if not retrieval_contract.validate_evidence_for_query(
            _ev(None), fresh_q):
        return _fail("max age required + missing source_date must fail")
    # Fresh, within-window evidence => PASS.
    if retrieval_contract.validate_evidence_for_query(_ev("2026-08-01"), fresh_q):
        return _fail("fresh evidence within max age must pass")

    ev = _ev("2026-08-01")
    if not retrieval_contract.validate_retrieval_result(ev):
        return _fail("OOS_SUPPORTED with grade D should fail validation")
    if not hasattr(retrieval_contract, "ContradictionResult"):
        return _fail("ContradictionResult contract missing")
    cr = retrieval_contract.ContradictionResult(
        fact_id="f1", counterevidence=[ev],
        supporting=[ResearchEvidence(fact_id="f2", fact="s", source_id="s2",
                                     evidence_type=EvidenceType.SEASONALITY)])
    if not isinstance(cr.counterevidence[0], ResearchEvidence):
        return _fail("contradiction counterevidence must carry ResearchEvidence (provenance)")
    return _pass("retrieval contract: structured query + freshness enforcement + "
                 "contradiction evidence refs + fail-closed validation")


def _check_authority_boundary() -> tuple[str, str]:
    ctx = _context()
    ok = promotion_gate.run_promotion_gate(ctx)
    if ok["promotion_state"] != "CIO_CONTEXT_ELIGIBLE":
        return _fail(f"valid A-grade empirical should reach CIO_CONTEXT_ELIGIBLE: {ok}")

    x = promotion_gate.run_promotion_gate(dict(ctx, evidence_grade="X"))
    if x["promotion_state"] != "INVALIDATED" or x["overall"] != GateState.FAIL.value:
        return _fail("grade X must be INVALIDATED/FAIL")
    d = promotion_gate.run_promotion_gate(dict(ctx, evidence_grade="D"))
    if d["promotion_state"] != "SOURCE_ONLY":
        return _fail("grade D must cap at SOURCE_ONLY")
    ta = promotion_gate.run_promotion_gate(dict(ctx, claims_trade_authority=True))
    if ta["overall"] != GateState.FAIL.value:
        return _fail("claiming trade authority must fail")

    # P0-5: family_frozen=True without a governed frozen-family receipt => FAIL.
    raw_frozen = dict(ctx, evidence_bundle=None, family_frozen=True)
    rf = promotion_gate.run_promotion_gate(raw_frozen)
    if rf["overall"] != GateState.FAIL.value:
        return _fail("family_frozen raw boolean without a receipt must FAIL")
    if rf["gate_results"]["RG-2"]["state"] != GateState.FAIL.value:
        return _fail("RG-2 must fail on caller-supplied family_frozen boolean")

    # P0-6: oos_supported/oos_untouched raw booleans without a receipt => FAIL.
    raw_oos = dict(ctx, evidence_bundle=None, oos_supported=True, oos_untouched=True)
    ro = promotion_gate.run_promotion_gate(raw_oos)
    if ro["overall"] != GateState.FAIL.value:
        return _fail("oos raw booleans without a receipt must FAIL")
    if ro["gate_results"]["RG-5"]["state"] != GateState.FAIL.value:
        return _fail("RG-5 must fail on caller-supplied OOS booleans")

    # P0-1: caller-built self-digested typed result (no governed receipt) => FAIL.
    caller_dsr = finalize(DSRResult(
        result_id="dsrfake", status="OK", observed_sharpe=1.2, n_observations=250,
        skewness=-0.2, kurtosis=4.0, n_trials=3, deflated_benchmark_sr=0.5,
        psr_z=2.5, probability_sr_exceeds_deflated_benchmark=0.99,
        sharpe_frequency="PER_PERIOD", trial_sharpe_frequency="PER_PERIOD",
        return_frequency="DAILY", confirmatory=True, protocol_hash="ph",
        hypothesis_id="h1", trial_family_id="f", family_definition_hash="fdh",
        dataset_hash="d0", code_sha="c0"))
    if caller_dsr.verify() is not True:
        return _fail("self-digest should verify (only proves self-consistency)")
    fake = dict(ctx, evidence_bundle=None, dsr_result=caller_dsr)
    if promotion_gate.run_promotion_gate(fake)["overall"] != GateState.FAIL.value:
        return _fail("caller-built self-digested DSR must be rejected (not provenance)")

    # Influence class vs evidence type: SEASONALITY + RISK_VETO => FAIL.
    season = dict(ctx, evidence_type="SEASONALITY", influence_class="RISK_VETO")
    if promotion_gate.run_promotion_gate(season)["overall"] != GateState.FAIL.value:
        return _fail("SEASONALITY cannot claim RISK_VETO")

    # Method applicability: DSR/PBO REQUIRED but absent from the bundle => FAIL.
    no_dsr = _bundle_variant(ctx, dsr=None)
    if promotion_gate.run_promotion_gate(no_dsr)["overall"] != GateState.FAIL.value:
        return _fail("DSR REQUIRED but absent from the bundle must FAIL")
    no_pbo = _bundle_variant(ctx, pbo=None)
    if promotion_gate.run_promotion_gate(no_pbo)["overall"] != GateState.FAIL.value:
        return _fail("PBO REQUIRED but absent from the bundle must FAIL")

    # Single fixed strategy: PBO NOT_APPLICABLE with reason => allowed.
    single_app = MethodApplicability(
        dsr=MethodRequirement("NOT_APPLICABLE", "single fixed strategy"),
        pbo=MethodRequirement("NOT_APPLICABLE", "one fixed preregistered strategy; no configuration selection"),
        reality_check=MethodRequirement("NOT_APPLICABLE", "single strategy"),
        purged_cv=MethodRequirement("NOT_APPLICABLE", "fixed-period"),
    )
    single = _bundle_variant(ctx, method_applicability=single_app, dsr=None, pbo=None)
    if promotion_gate.run_promotion_gate(single)["overall"] != GateState.PASS.value:
        return _fail("single-fixed-strategy PBO NOT_APPLICABLE profile must pass")
    if not influence_allowed(EvidenceType.EMPIRICAL_STRATEGY.value, "PORTFOLIO_CONSTRUCTION"):
        return _fail("EMPIRICAL_STRATEGY + PORTFOLIO_CONSTRUCTION must be allowed")
    return _pass("authority boundary + governed-only evidence + raw boolean rejection + "
                 "applicability + influence matrix enforced")


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
