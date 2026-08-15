"""R2 adversarial matrix + provenance + scope + R1 regression hooks."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.research_governance import acceptance  # noqa: E402
from scripts.lib.research_governance.mechanics.common import (  # noqa: E402
    InputDatum,
    AssumptionClass,
    Quantity,
    Unit,
    convert_quantity,
)
from scripts.lib.research_governance.mechanics.etf import tracking_difference  # noqa: E402
from scripts.lib.research_governance.mechanics.fixed_income import analyze_bond  # noqa: E402
from scripts.lib.research_governance.producers import (  # noqa: E402
    FixedIncomeInput,
    run_governed_fixed_income,
)
from scripts.lib.research_governance.receipts import governed_result  # noqa: E402
from scripts.lib.research_governance.mechanics.results import wrap_mechanic  # noqa: E402
from scripts.lib.research_governance.results import finalize  # noqa: E402
from scripts.lib.research_governance import pr_scope_guard  # noqa: E402


def test_root_solver_non_convergence_unavailable():
    # Price so high it cannot be reached even at y=-50%
    r = analyze_bond(
        instrument_id="x", settlement="2020-01-01", maturity="2021-01-01",
        coupon_rate=0.0, frequency="annual", day_count="30/360_US",
        dirty_price=1e9,
    )
    assert r.status.value == "UNAVAILABLE"
    assert "bracket" in r.reason.lower() or "residual" in r.reason.lower() or r.reason_code


def test_percent_decimal_mismatch_fails_closed():
    try:
        convert_quantity(Quantity(5.0, Unit.PERCENT), Unit.USD)
        raise AssertionError("should fail")
    except Exception as exc:
        assert "mismatch" in str(exc).lower() or "conversion" in str(exc).lower()


def test_usd_millions_guard():
    q = convert_quantity(Quantity(2.0, Unit.USD_MILLIONS), Unit.USD)
    assert q.value == 2_000_000.0
    try:
        convert_quantity(Quantity(2.0, Unit.USD_MILLIONS), Unit.SHARES)
        raise AssertionError("should fail")
    except Exception:
        pass


def test_bps_conversion_golden():
    q = convert_quantity(Quantity(25.0, Unit.BASIS_POINTS), Unit.DECIMAL_RATE)
    assert abs(q.value - 0.0025) < 1e-15


def test_missing_source_as_of():
    d = InputDatum("nav", 1.0, Unit.USD, AssumptionClass.VERIFIED_FACT_INPUT, as_of="")
    try:
        d.require_as_of()
        raise AssertionError("should fail")
    except Exception as exc:
        assert getattr(exc, "status").value == "UNAVAILABLE"


def test_caller_built_result_not_governed():
    calc = analyze_bond(
        instrument_id="z", settlement="2019-01-01", maturity="2020-01-01",
        coupon_rate=0.0, frequency="annual", day_count="ACT/365",
        yield_to_maturity=0.05,
    )
    typed = finalize(wrap_mechanic("fixed_income", calc))
    fake = governed_result(typed, input_artifact={"caller": True})
    assert fake.receipt.verify() is False


def test_governed_producer_result_authentic():
    g = run_governed_fixed_income(FixedIncomeInput(
        instrument_id="z", settlement="2019-01-01", maturity="2020-01-01",
        coupon_rate=0.0, frequency="annual", day_count="ACT/365",
        yield_to_maturity=0.05,
    ))
    assert g.receipt.verify() is True
    assert g.receipt.validate() == []
    digest1 = g.receipt.producer_code_sha
    # Implementation-bound: digest is sha256 of fixed_income.py bytes
    src = ROOT / "scripts/lib/research_governance/mechanics/fixed_income.py"
    import hashlib
    assert digest1 == hashlib.sha256(src.read_bytes()).hexdigest()


def test_forged_receipt_rejected():
    g = run_governed_fixed_income(FixedIncomeInput(
        instrument_id="z", settlement="2019-01-01", maturity="2020-01-01",
        coupon_rate=0.0, frequency="annual", day_count="ACT/365",
        yield_to_maturity=0.05,
    ))
    from dataclasses import replace
    forged = replace(g.receipt, signature="0" * 64)
    assert forged.verify() is False


def test_authority_read_only():
    r = analyze_bond(
        instrument_id="z", settlement="2019-01-01", maturity="2020-01-01",
        coupon_rate=0.0, frequency="annual", day_count="ACT/365",
        yield_to_maturity=0.05,
    )
    assert r.authority == "READ_ONLY_ADVISORY"


def test_r2_forbidden_shared_cio_file_denied():
    assert pr_scope_guard.is_denied("scripts/lib/cio_acceptance_v4.py")
    assert pr_scope_guard.is_denied("scripts/lib/cio_capital_plan.py")
    assert pr_scope_guard.evaluate(["scripts/lib/cio_command_center.py"])["state"] == "FAIL"


def test_r2_profile_includes_r1_foundation():
    prof = acceptance.PHASE_PROFILES["R2_mechanics"]
    for gid in acceptance.PHASE_PROFILES["R1_foundation"]["required_runtime"]:
        assert gid in prof["required_runtime"]
    assert "RGA-15" in prof["not_in_scope"]
    assert "RGA-16" in prof["not_in_scope"]


def test_deterministic_profile_does_not_require_pbo():
    from scripts.lib.research_governance.promotion_gate import _type_specific_gates
    from scripts.lib.research_governance.enums import EvidenceType
    gates = _type_specific_gates({"evidence_type": EvidenceType.DETERMINISTIC_MECHANICS.value})
    names = [g[0] for g in gates]
    assert "pbo" not in names
    assert "dsr" not in names
    assert "reference_tests" in names


def test_valuation_profile_requires_sensitivity():
    from scripts.lib.research_governance.promotion_gate import _type_specific_gates
    from scripts.lib.research_governance.enums import EvidenceType
    gates = _type_specific_gates({"evidence_type": EvidenceType.VALUATION_MODEL.value})
    names = [g[0] for g in gates]
    assert "scenario_sensitivity" in names


def test_r3_almanac_files_absent():
    assert not (ROOT / "scripts/lib/research_governance/almanac.py").exists()


def test_r4_live_integration_absent():
    assert not (ROOT / "scripts/lib/research_governance/live_alex.py").exists()
    assert not (ROOT / "scripts/lib/research_governance/cio_wire.py").exists()


def test_td_unit_mismatch():
    r = tracking_difference(
        instrument_id="X", fund_return=10.0, benchmark_return=0.09,
        return_basis="price", fund_unit=Unit.PERCENT, bench_unit=Unit.DECIMAL_RATE,
    )
    assert r.status.value == "INVALID_INPUT"


def test_r1_and_r2_acceptance_pass():
    r1 = acceptance.run_acceptance("R1_foundation")
    r2 = acceptance.run_acceptance("R2_mechanics")
    assert r1["overall"] == "PASS", r1
    assert r2["overall"] == "PASS", r2
