"""Research governance — RGA acceptance dry tests (PR-R1)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from scripts.lib.research_governance import acceptance  # noqa: E402
from scripts.lib.research_governance.enums import GateState  # noqa: E402


def test_r1_profile_not_in_scope_never_passes():
    results = {g: GateState.PASS.value for g in acceptance.RGA_IDS}
    # Even if someone wrongly awards PASS to a not-in-scope gate, it must not be
    # counted as a required PASS and must remain reported not_in_scope.
    results["RGA-15"] = GateState.PASS.value
    rep = acceptance.evaluate_profile("R1_foundation", results)
    assert rep["overall"] == GateState.PASS.value  # required gates still pass
    assert "RGA-15" not in rep["required_pass"]
    assert "RGA-15" in rep["not_in_scope"]


def test_r1_profile_fails_if_required_gate_fails():
    results = {g: GateState.PASS.value for g in acceptance.RGA_IDS}
    results["RGA-6"] = GateState.FAIL.value
    rep = acceptance.evaluate_profile("R1_foundation", results)
    assert rep["overall"] == GateState.FAIL.value
    assert "RGA-6" in rep["required_fail"]


def test_r4_requires_all_sixteen():
    results = {g: GateState.PASS.value for g in acceptance.RGA_IDS if g != "RGA-16"}
    results["RGA-16"] = GateState.FAIL.value
    rep = acceptance.evaluate_profile("R4_integration", results)
    assert rep["overall"] == GateState.FAIL.value


def test_r3_requires_rga15():
    results = {g: GateState.PASS.value for g in acceptance.RGA_IDS if g != "RGA-15"}
    results["RGA-15"] = GateState.FAIL.value
    rep = acceptance.evaluate_profile("R3_almanac", results)
    assert rep["overall"] == GateState.FAIL.value
    assert "RGA-15" in rep["required_fail"]


def test_unknown_profile_raises():
    import pytest
    with pytest.raises(ValueError):
        acceptance.evaluate_profile("nope", {})


def test_r1_acceptance_actually_passes():
    rep = acceptance.run_acceptance("R1_foundation")
    assert rep["overall"] == GateState.PASS.value, rep
    assert rep["required_fail"] == []
    assert "RGA-15" in rep["not_in_scope"]
    assert "RGA-16" in rep["not_in_scope"]


def test_r2_r3_r4_profiles_declared():
    assert "R2_mechanics" in acceptance.PHASE_PROFILES
    assert "R3_almanac" in acceptance.PHASE_PROFILES
    assert "R4_integration" in acceptance.PHASE_PROFILES
