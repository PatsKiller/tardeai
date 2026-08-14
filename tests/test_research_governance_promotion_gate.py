"""Research governance — promotion gate type-awareness + grade-ceiling tests (PR-R1)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from scripts.lib.research_governance import promotion_gate as pg  # noqa: E402
from scripts.lib.research_governance.enums import GateState  # noqa: E402


def _empirical_base():
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
        "evidence_grade": "A",
        "influence_class": "VALUATION_INPUT",
    }


def test_rg_ladder_restored_rg10_rg11():
    assert set(pg.GATE_IDS) == {f"RG-{i}" for i in range(12)}
    names = {gid: pg._GATES[i][1] for i, gid in enumerate(f"RG-{k}" for k in range(12))}
    assert names["RG-10"] == "decision_use_audit"
    assert names["RG-11"] == "live_degradation_retirement"


def test_grade_a_full_profile_reaches_cio_context():
    r = pg.run_promotion_gate(_empirical_base())
    assert r["overall"] == GateState.PASS.value
    assert r["promotion_state"] == "CIO_CONTEXT_ELIGIBLE"


def test_grade_x_never_promotes():
    r = pg.run_promotion_gate(dict(_empirical_base(), evidence_grade="X"))
    assert r["overall"] == GateState.FAIL.value
    assert r["promotion_state"] == "INVALIDATED"


def test_grade_d_caps_at_source_only():
    r = pg.run_promotion_gate(dict(_empirical_base(), evidence_grade="D"))
    assert r["promotion_state"] == "SOURCE_ONLY"


def test_grade_c_cannot_reach_cio_context():
    r = pg.run_promotion_gate(dict(_empirical_base(), evidence_grade="C"))
    assert r["promotion_state"] == "EXPLORATORY_SHADOW"
    assert r["promotion_state"] != "CIO_CONTEXT_ELIGIBLE"


def test_claiming_trade_authority_blocks():
    r = pg.run_promotion_gate(dict(_empirical_base(), claims_trade_authority=True))
    assert r["overall"] == GateState.FAIL.value


def test_empirical_requires_full_ladder():
    # Missing reality check -> a required empirical gate fails.
    r = pg.run_promotion_gate(dict(_empirical_base(), reality_check=None))
    assert r["overall"] == GateState.FAIL.value
    assert "RG-7" in r["_failed_required"]


def test_seasonality_cannot_bypass_empirical_gates():
    ctx = dict(_empirical_base(), evidence_type="SEASONALITY")
    # Remove reality check: seasonality must still fail.
    ctx["reality_check"] = None
    r = pg.run_promotion_gate(ctx)
    assert r["overall"] == GateState.FAIL.value
    assert "RG-7" in r["_failed_required"]


def test_deterministic_mechanics_do_not_require_fake_oos():
    ctx = {
        "source_id": "s", "claim": "c", "page_or_section": "p", "scope": "us",
        "evidence_type": "DETERMINISTIC_MECHANICS",
        "evidence_grade": "A", "influence_class": "DETERMINISTIC_MECHANICS",
        "mechanics_definition": "duration", "units_convention": "years",
        "reference_tests_passed": True, "source_as_of": "2026-01-01",
    }
    r = pg.run_promotion_gate(ctx)
    assert r["overall"] == GateState.PASS.value
    # Empirical gates must be NOT_APPLICABLE, not failed.
    assert r["gate_results"]["RG-4"]["state"] == GateState.NOT_APPLICABLE.value
    assert r["gate_results"]["RG-7"]["state"] == GateState.NOT_APPLICABLE.value


def test_policy_requires_jurisdiction_not_sharpe():
    ctx = {
        "source_id": "s", "claim": "c", "page_or_section": "p", "scope": "us",
        "evidence_type": "POLICY_OR_REGULATORY",
        "evidence_grade": "B", "influence_class": "RISK_VETO",
        "authoritative_source": "IRS", "effective_date": "2026-01-01",
        "jurisdiction": "US", "freshness": "2026-08-01",
    }
    r = pg.run_promotion_gate(ctx)
    assert r["overall"] == GateState.PASS.value
    # Missing jurisdiction must fail (not a statistical requirement).
    bad = dict(ctx, jurisdiction=None)
    rb = pg.run_promotion_gate(bad)
    assert rb["overall"] == GateState.FAIL.value


def test_valuation_model_requires_assumptions_not_cscv():
    ctx = {
        "source_id": "s", "claim": "c", "page_or_section": "p", "scope": "us",
        "evidence_type": "VALUATION_MODEL",
        "evidence_grade": "B", "influence_class": "VALUATION_INPUT",
        "model_identity": "dcf", "assumption_provenance": "x",
        "scenario_sensitivity": "y", "calibration": "z",
    }
    r = pg.run_promotion_gate(ctx)
    assert r["overall"] == GateState.PASS.value
    assert r["gate_results"]["RG-7"]["state"] == GateState.NOT_APPLICABLE.value


def test_source_narrative_is_source_only():
    ctx = {
        "source_id": "s", "claim": "c", "page_or_section": "p", "scope": "us",
        "evidence_type": "SOURCE_NARRATIVE",
        "evidence_grade": "D", "influence_class": "CONTEXT_MODIFIER",
    }
    r = pg.run_promotion_gate(ctx)
    assert r["promotion_state"] == "SOURCE_ONLY"


def test_missing_evidence_type_fails():
    r = pg.run_promotion_gate({"source_id": "s"})
    assert r["overall"] == GateState.FAIL.value
