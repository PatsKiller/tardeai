"""Research governance — promotion gate (RG-0..11) dry tests (PR-R1)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from scripts.lib.research_governance import promotion_gate as pg  # noqa: E402
from scripts.lib.research_governance.enums import GateState, InfluenceClass  # noqa: E402


def _full_ctx(**overrides):
    ctx = {
        "source_id": "s",
        "claim": "c",
        "page_or_section": "p",
        "scope": "us",
        "protocol_hash": "ph",
        "trial_family_id": "fam",
        "family_frozen": True,
        "code_sha": "c0",
        "dataset_hash": "d0",
        "in_sample_metric": 1.0,
        "in_sample_threshold": 0.0,
        "oos_supported": True,
        "oos_untouched": True,
        "multiple_testing": {"rejected_any": True},
        "reality_check": {"bootstrap_pvalue": 0.01},
        "robustness": {"subperiods": True, "regimes": True, "costs": True},
        "evidence_grade": "B",
        "influence_class": InfluenceClass.VALUATION_INPUT.value,
        "claims_trade_authority": False,
    }
    ctx.update(overrides)
    return ctx


def test_gate_ids_are_rg0_to_rg11():
    assert pg.GATE_IDS == tuple(f"RG-{i}" for i in range(12))


def test_full_ctx_passes_all():
    rep = pg.run_promotion_gate(_full_ctx())
    assert rep["overall"] == GateState.PASS.value
    assert rep["passed"] == 12
    assert rep["failed"] == 0


def test_missing_source_fails_rg0():
    rep = pg.run_promotion_gate({}, halt_on_first_fail=False)
    assert rep["gate_results"]["RG-0"]["state"] == GateState.FAIL.value
    assert rep["overall"] == GateState.FAIL.value


def test_halt_on_first_fail_marks_later_not_in_scope():
    rep = pg.run_promotion_gate({}, halt_on_first_fail=True)
    assert rep["gate_results"]["RG-1"]["state"] == GateState.NOT_IN_SCOPE.value


def test_authority_boundary_blocks_promotion():
    ctx = _full_ctx(claims_trade_authority=True)
    rep = pg.run_promotion_gate(ctx)
    assert rep["gate_results"]["RG-10"]["state"] == GateState.FAIL.value
    assert rep["overall"] == GateState.FAIL.value


def test_consumed_oos_blocks_rg5():
    ctx = _full_ctx(oos_untouched=False)
    rep = pg.run_promotion_gate(ctx)
    assert rep["gate_results"]["RG-5"]["state"] == GateState.FAIL.value


def test_reality_check_failure_blocks_rg7():
    ctx = _full_ctx(reality_check={"bootstrap_pvalue": 0.9})
    rep = pg.run_promotion_gate(ctx)
    assert rep["gate_results"]["RG-7"]["state"] == GateState.FAIL.value


def test_multiple_testing_failure_blocks_rg6():
    ctx = _full_ctx(multiple_testing={"rejected_any": False})
    rep = pg.run_promotion_gate(ctx)
    assert rep["gate_results"]["RG-6"]["state"] == GateState.FAIL.value


def test_weak_robustness_blocks_rg8():
    ctx = _full_ctx(robustness={"subperiods": True, "regimes": False, "costs": True})
    rep = pg.run_promotion_gate(ctx)
    assert rep["gate_results"]["RG-8"]["state"] == GateState.FAIL.value


def test_promotion_state_tracks_highest_earned():
    rep = pg.run_promotion_gate(_full_ctx())
    assert rep["promotion_state"] == "ELIGIBLE_FOR_CIO_CONTEXT"
    partial = pg.run_promotion_gate(_full_ctx(reality_check={"bootstrap_pvalue": 0.9}))
    # RG-7 fails => promotion state caps at OOS_SUPPORTED (6 gates passed).
    assert partial["promotion_state"] == "OOS_SUPPORTED"
