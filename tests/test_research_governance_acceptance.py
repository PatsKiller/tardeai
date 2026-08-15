"""Research governance — acceptance phase-profile + golden tests (PR-R1)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from scripts.lib.research_governance import acceptance  # noqa: E402
from scripts.lib.research_governance.enums import GateState  # noqa: E402


def test_r1_acceptance_actually_passes_golden():
    rep = acceptance.run_acceptance("R1_foundation")
    assert rep["overall"] == GateState.PASS.value
    assert rep["required_runtime_fail"] == []
    assert rep["required_contract_fail"] == []
    assert "RGA-15" in rep["not_in_scope"]
    assert "RGA-16" in rep["not_in_scope"]


def test_not_in_scope_never_counts_as_pass():
    rep = acceptance.evaluate_profile(
        "R1_foundation",
        {"RGA-1": "PASS", "RGA-2": "PASS", "RGA-3": "PASS", "RGA-4": "PASS",
         "RGA-5": "PASS", "RGA-6": "PASS", "RGA-7": "PASS", "RGA-8": "PASS",
         "RGA-9": "PASS", "RGA-10": "PASS", "RGA-11": "PASS", "RGA-12": "PASS",
         "RGA-13": "PASS", "RGA-14": "PASS",
         "RGA-15": "PASS", "RGA-16": "PASS"},
    )
    assert rep["overall"] == GateState.PASS.value
    assert rep["not_in_scope_count"] == 2


def test_required_fail_blocks_profile():
    rep = acceptance.evaluate_profile(
        "R1_foundation",
        {"RGA-1": "FAIL", "RGA-2": "PASS", "RGA-3": "PASS", "RGA-4": "PASS",
         "RGA-5": "PASS", "RGA-6": "PASS", "RGA-7": "PASS", "RGA-8": "PASS",
         "RGA-9": "PASS", "RGA-10": "PASS", "RGA-11": "PASS", "RGA-12": "PASS",
         "RGA-13": "PASS", "RGA-14": "PASS", "RGA-15": "NOT_IN_SCOPE",
         "RGA-16": "NOT_IN_SCOPE"},
    )
    assert rep["overall"] == GateState.FAIL.value
    assert "RGA-1" in rep["required_runtime_fail"]


def test_contract_only_fail_blocks_profile():
    # A broken contract-only gate must still fail R1 overall.
    rep = acceptance.evaluate_profile(
        "R1_foundation",
        {"RGA-1": "PASS", "RGA-2": "PASS", "RGA-3": "PASS", "RGA-4": "PASS",
         "RGA-5": "PASS", "RGA-6": "PASS", "RGA-7": "PASS", "RGA-8": "PASS",
         "RGA-9": "PASS", "RGA-10": "PASS", "RGA-11": "FAIL", "RGA-12": "PASS",
         "RGA-13": "PASS", "RGA-14": "PASS", "RGA-15": "NOT_IN_SCOPE",
         "RGA-16": "NOT_IN_SCOPE"},
    )
    assert rep["overall"] == GateState.FAIL.value
    assert "RGA-11" in rep["required_contract_fail"]


def test_r2_mechanics_profile_implemented():
    rep = acceptance.run_acceptance("R2_mechanics")
    assert rep.get("not_implemented") is not True
    assert rep["overall"] == GateState.PASS.value
    assert "R2A-1" in rep["required_runtime_pass"]


def test_r4_requires_all_sixteen():
    prof = acceptance.PHASE_PROFILES["R4_integration"]
    assert prof["required_runtime"] == list(acceptance.RGA_IDS)


def test_canonical_gate_names():
    assert acceptance.GATE_NAMES["RGA-15"] == "almanac_reproduction"
    assert acceptance.GATE_NAMES["RGA-16"] == "research_decision_use_audit"
    assert len(acceptance.RGA_IDS) == 16
