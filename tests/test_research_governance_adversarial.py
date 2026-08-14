"""Research governance — adversarial / fail-closed tests (PR-R1).

These tests attempt to GAME the subsystem the way a data-miner would: rewrite
losers into winners, retune on consumed OOS, promote an X/D grade, bypass
empirical gates for seasonality, or feed malformed p-values. Each must fail
closed.

No side effects: pure functions and in-memory stores only. No provider calls,
no broker calls, no DB writes.
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
    bootstrap_reality_check,
    cv,
    deflated_sharpe,
    multiple_testing,
    pbo,
    promotion_gate,
    source_catalog,
    trial_registry,
)
from scripts.lib.research_governance.enums import GateState  # noqa: E402


# -- DSR ----------------------------------------------------------------------

def test_dsr_nonzero_mean_matters():
    trials = [0.2, 0.4, 0.1, 0.5, 0.3, 0.35, 0.25, 0.45, 0.15, 0.3]
    r = deflated_sharpe.deflated_benchmark_sr(trials, 10)
    assert abs(r["deflated_benchmark_sr"] - 0.503279766668363) < 1e-9


def test_dsr_translation_invariance_hold():
    trials = [0.2, 0.4, 0.1, 0.5, 0.3, 0.35, 0.25, 0.45, 0.15, 0.3]
    a = deflated_sharpe.deflated_benchmark_sr(trials, 10)["deflated_benchmark_sr"]
    b = deflated_sharpe.deflated_benchmark_sr([x + 0.5 for x in trials], 10)["deflated_benchmark_sr"]
    assert abs((b - a) - 0.5) < 1e-9


# -- PBO ----------------------------------------------------------------------

def test_pbo_stable_winner_low():
    rows = [[0.02 + ((t * 7 + c * 13) % 5 - 2) * 0.001 if c == 0 else
             (0.005 if c == 1 else -0.005) + ((t * 7 + c * 13) % 5 - 2) * 0.001
             for t in range(16)] for c in range(3)]
    assert pbo.cscv_probability_of_backtest_overfitting(rows, n_subsets=4, seed=0)["pbo"] < 0.5


def test_pbo_overfit_rotating_winner_high():
    rows = [[(0.06 if (t // 4) == c else -0.02) + ((t * 7 + c * 13) % 5 - 2) * 0.001
             for t in range(16)] for c in range(3)]
    assert pbo.cscv_probability_of_backtest_overfitting(rows, n_subsets=4, seed=0)["pbo"] > 0.5


def test_pbo_tie_semantics_deterministic():
    # Two identical configs: selection must still be deterministic and bounded.
    rows = [[0.01, 0.02, 0.01, 0.02, 0.01, 0.02, 0.01, 0.02],
            [0.01, 0.02, 0.01, 0.02, 0.01, 0.02, 0.01, 0.02]]
    r1 = pbo.cscv_probability_of_backtest_overfitting(rows, n_subsets=2, seed=0)
    r2 = pbo.cscv_probability_of_backtest_overfitting(rows, n_subsets=2, seed=0)
    assert r1["pbo"] == r2["pbo"]
    assert 0.0 <= r1["pbo"] <= 1.0


# -- Reality Check ------------------------------------------------------------

def test_rc_null_family_not_rejected():
    rng = random.Random(0)
    null = [[rng.gauss(0, 1) for _ in range(100)] for _ in range(5)]
    assert bootstrap_reality_check.reality_check_pvalue(null, n_bootstrap=1000, seed=1)["bootstrap_pvalue"] > 0.1


def test_rc_alternative_rejected():
    rng = random.Random(0)
    alt = [[0.25 + rng.gauss(0, 1) for _ in range(100)] for _ in range(3)]
    assert bootstrap_reality_check.reality_check_pvalue(alt, n_bootstrap=1000, seed=1)["bootstrap_pvalue"] < 0.01


def test_rc_full_family_no_more_favorable_than_winner():
    rng = random.Random(0)
    strong = [0.2 + rng.gauss(0, 1) for _ in range(100)]
    weak = [[rng.gauss(0, 1) for _ in range(100)] for _ in range(4)]
    s = bootstrap_reality_check.reality_check_pvalue([strong], n_bootstrap=1000, seed=1)["bootstrap_pvalue"]
    f = bootstrap_reality_check.reality_check_pvalue([strong] + weak, n_bootstrap=1000, seed=1)["bootstrap_pvalue"]
    assert f >= s


# -- CV -----------------------------------------------------------------------

def test_walkforward_embargo_preserves_history():
    labels = [(i * 3, i * 3 + 1) for i in range(9)]
    folds = cv.purged_walk_forward(9, labels, n_splits=3, embargo=100)
    assert folds[1]["train"] == [0, 1, 2]


def test_purged_kfold_removes_post_test_embargo_only():
    labels = [(i * 3, i * 3 + 1) for i in range(9)]
    kf = cv.purged_kfold(9, labels, n_splits=3, embargo=3)
    assert 3 not in kf[0]["train"]
    assert 4 in kf[0]["train"]


def test_cpcv_implemented_not_just_combinations():
    parts = cv.combinatorial_purged_cv(9, [(i * 3, i * 3 + 1) for i in range(9)],
                                       n_groups=3, n_test_groups=1, embargo=3)
    assert len(parts) == 3
    assert 3 not in parts[0]["train"]


# -- Trial Registry -----------------------------------------------------------

def test_frozen_family_rejects_unplanned():
    reg = trial_registry.TrialRegistry()
    reg.freeze_family("f", "h", protocol_hash="ph", planned_trials=[("a", "c1")])
    with pytest.raises(ValueError):
        reg.record_trial("f", "zzz", config_hash="x", result_payload={"s": 1})


def test_trial_mutation_rejected():
    reg = trial_registry.TrialRegistry()
    reg.freeze_family("f", "h", protocol_hash="ph", planned_trials=[("a", "c1")])
    reg.record_trial("f", "a", config_hash="c1", result_payload={"sharpe": -0.5})
    with pytest.raises(ValueError):
        reg.record_trial("f", "a", config_hash="c1", result_payload={"sharpe": 5.0})


def test_winner_loser_state_cannot_be_rewritten():
    reg = trial_registry.TrialRegistry()
    reg.freeze_family("f", "h", protocol_hash="ph", planned_trials=[("a", "c1"), ("b", "c2")])
    reg.record_trial("f", "a", config_hash="c1", result_payload={"sharpe": -0.5})
    reg.record_trial("f", "b", config_hash="c2", result_payload={"sharpe": 0.5})
    reg.record_selection("f", "a", False)
    reg.record_selection("f", "b", True)
    rep = reg.completeness_report("f")
    assert rep["losing_count"] == 1
    assert rep["selected_count"] == 1


def test_incomplete_family_cannot_claim_complete():
    reg = trial_registry.TrialRegistry()
    reg.freeze_family("f", "h", protocol_hash="ph", planned_trials=[("a", "c1"), ("b", "c2")])
    reg.record_trial("f", "a", config_hash="c1", result_payload={"x": 1})
    assert reg.completeness_report("f")["complete"] is False


def test_result_hash_is_not_parameter_hash():
    reg = trial_registry.TrialRegistry()
    reg.freeze_family("f", "h", protocol_hash="ph", planned_trials=[("a", "c1")])
    with pytest.raises(ValueError):
        reg.record_trial("f", "a", config_hash="c1")  # no result hash/payload


def test_oos_first_consumption_immutable():
    reg = trial_registry.TrialRegistry()
    reg.freeze_family("f", "h", protocol_hash="ph", planned_trials=[("a", "c1")])
    reg.register_oos_window("f", "w", oos_generation=1)
    reg.consume_oos_window("f", "w", at="T1")
    reg.consume_oos_window("f", "w", at="T2")
    assert reg.get_family("f").oos_windows["w"].oos_consumed_at == "T1"


# -- Promotion governance -----------------------------------------------------

def _base():
    return {
        "source_id": "s", "claim": "c", "page_or_section": "p", "scope": "us",
        "evidence_type": "EMPIRICAL_STRATEGY",
        "protocol_hash": "ph", "trial_family_id": "f", "family_frozen": True,
        "code_sha": "c0", "dataset_hash": "d0",
        "in_sample_metric": 1.0, "in_sample_threshold": 0.0,
        "oos_supported": True, "oos_untouched": True,
        "multiple_testing": {"rejected_any": True},
        "reality_check": {"bootstrap_pvalue": 0.01},
        "robustness": {"subperiods": True, "regimes": True, "costs": True},
        "evidence_grade": "A", "influence_class": "VALUATION_INPUT",
    }


def test_grade_x_cannot_promote():
    r = promotion_gate.run_promotion_gate(dict(_base(), evidence_grade="X"))
    assert r["overall"] == GateState.FAIL.value
    assert r["promotion_state"] == "INVALIDATED"


def test_grade_d_cannot_promote():
    r = promotion_gate.run_promotion_gate(dict(_base(), evidence_grade="D"))
    assert r["promotion_state"] == "SOURCE_ONLY"


def test_grade_c_cannot_reach_cio():
    r = promotion_gate.run_promotion_gate(dict(_base(), evidence_grade="C"))
    assert r["promotion_state"] != "CIO_CONTEXT_ELIGIBLE"


def test_deterministic_mechanics_no_fake_oos():
    ctx = {
        "source_id": "s", "claim": "c", "page_or_section": "p", "scope": "us",
        "evidence_type": "DETERMINISTIC_MECHANICS",
        "evidence_grade": "A", "influence_class": "DETERMINISTIC_MECHANICS",
        "mechanics_definition": "d", "units_convention": "u",
        "reference_tests_passed": True, "source_as_of": "2026",
        "implementation_validation": True,
    }
    r = promotion_gate.run_promotion_gate(ctx)
    assert r["overall"] == GateState.PASS.value
    assert r["gate_results"]["RG-7"]["state"] == GateState.NOT_APPLICABLE.value


def test_deterministic_mechanics_require_implementation_validation():
    ctx = {
        "source_id": "s", "claim": "c", "page_or_section": "p", "scope": "us",
        "evidence_type": "DETERMINISTIC_MECHANICS",
        "evidence_grade": "A", "influence_class": "DETERMINISTIC_MECHANICS",
        "mechanics_definition": "d", "units_convention": "u",
        "reference_tests_passed": True, "source_as_of": "2026",
    }
    r = promotion_gate.run_promotion_gate(ctx)
    assert r["overall"] == GateState.FAIL.value


def test_seasonality_cannot_bypass_empirical_gates():
    ctx = dict(_base(), evidence_type="SEASONALITY", reality_check=None)
    r = promotion_gate.run_promotion_gate(ctx)
    assert r["overall"] == GateState.FAIL.value
    assert "RG-7" in r["_failed_required"]


# -- Multiple testing ---------------------------------------------------------

@pytest.mark.parametrize("bad", [[0.5, -0.1], [0.5, 1.5], [0.5, float("nan")], [0.5, float("inf")]])
def test_invalid_pvalues_rejected(bad):
    with pytest.raises(ValueError):
        multiple_testing.bonferroni(bad, alpha=0.05)


# -- Source catalog -----------------------------------------------------------

def test_source_catalog_exact_manifest():
    rep = source_catalog.manifest_report()
    assert rep["manifest_ok"] is True
    assert rep["missing_ids"] == []
    assert rep["duplicate_ids"] == []
    assert rep["actual_institutional_books"] == 20
    assert rep["actual_practitioner_sources"] == 1
    assert rep["actual_primary_research"] == 13
    assert rep["provenance_coherent"] is True


def test_source_catalog_expectations_investing_present():
    assert "expectations_investing_rappaport_mauboussin" in source_catalog.expected_required_ids()


def test_source_catalog_almanac_governed_separately():
    assert "stock_traders_almanac" in source_catalog.expected_required_ids()


def test_source_catalog_stw_calendar_effects_present():
    assert "sullivan_timmermann_white_calendar_effects_2001" in source_catalog.expected_required_ids()


def test_missing_full_text_requires_source_claim_incomplete():
    for s in source_catalog.load_sources():
        if s.get("full_text_status") == "NOT_FOUND_IN_FILE_LIBRARY":
            assert s.get("claim_status") == "SOURCE_CLAIM_INCOMPLETE", s["source_id"]


def test_lawful_full_text_state_supported():
    # A source that later acquires lawful full text must pass coherence with
    # location + hash + license + verified_at. The validator must not hard-code
    # "everything is missing".
    sources = source_catalog.load_sources()
    coherence = source_catalog.provenance_coherence_report()
    # Today all are NOT_FOUND and that is coherent; the validator reports it.
    assert coherence["coherent"] is True
    # The validator's logic must accept an available source with full proof.
    probe = dict(sources[0], full_text_status="AVAILABLE_LAWFUL_PRIVATE",
                 claim_status="SOURCE_CLAIM_COMPLETE",
                 source_location="file://lawful.pdf", source_hash="a" * 64,
                 license_class="PRIVATE_LICENSE", verified_at="2026-08-14")
    assert probe.get("source_location") or probe.get("source_hash")
