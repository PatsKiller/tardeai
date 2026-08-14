"""Research governance — subsystem acceptance RGA-1..RGA-16 (PR-R1).

Separate namespace from the promotion ladder (RG-*). RG gates govern the
lifecycle of a particular hypothesis/fact; RGA gates govern whether the research
SUBSYSTEM ITSELF is production-quality.

Canonical RGA mapping (single source of truth — keep plan, docs, runner, and
result packet consistent with this):

  RGA-1  source_registry_exact_manifest
  RGA-2  provenance_state_coherent
  RGA-3  lifecycle_grade_separated
  RGA-4  trial_registry_frozen_complete
  RGA-5  no_lookahead_contract
  RGA-6  multiple_testing_validated
  RGA-7  deflated_sharpe_golden
  RGA-8  pbo_golden
  RGA-9  reality_check_golden
  RGA-10 cv_purging_golden
  RGA-11 promotion_gate_contract
  RGA-12 retrieval_contract
  RGA-13 authority_boundary
  RGA-14 scope_guard
  RGA-15 almanac_reproduction             (R3)
  RGA-16 research_decision_use_audit      (R4)

Phase-aware acceptance with three disjoint collections:

  required_runtime  — runtime correctness (golden vectors, fail-closed behavior).
  required_contract — the contract EXISTS and is correct (must still pass; a
                      "contract-only" gate that is broken still fails the profile).
  not_in_scope      — belongs to a later phase; NEVER counts as a PASS.

Overall PASS requires EVERY required_runtime == PASS AND EVERY
required_contract == PASS. `NOT_IN_SCOPE` never counts as a PASS.
"""
from __future__ import annotations

from typing import Any, Callable

from .enums import GateState

RGA_IDS: tuple[str, ...] = tuple(f"RGA-{i}" for i in range(1, 17))

GATE_NAMES: dict[str, str] = {
    "RGA-1": "source_registry_exact_manifest",
    "RGA-2": "provenance_state_coherent",
    "RGA-3": "lifecycle_grade_separated",
    "RGA-4": "trial_registry_frozen_complete",
    "RGA-5": "no_lookahead_contract",
    "RGA-6": "multiple_testing_validated",
    "RGA-7": "deflated_sharpe_golden",
    "RGA-8": "pbo_golden",
    "RGA-9": "reality_check_golden",
    "RGA-10": "cv_purging_golden",
    "RGA-11": "promotion_gate_contract",
    "RGA-12": "retrieval_contract",
    "RGA-13": "authority_boundary",
    "RGA-14": "scope_guard",
    "RGA-15": "almanac_reproduction",
    "RGA-16": "research_decision_use_audit",
}

# R2 mechanics acceptance does not exist yet; it must fail closed rather than
# silently pass by reusing the R1 gate set. R2 is NOT authorized.
PHASE_PROFILES: dict[str, dict[str, list[str]]] = {
    "R1_foundation": {
        "required_runtime": ["RGA-1", "RGA-2", "RGA-3", "RGA-4", "RGA-5", "RGA-6",
                             "RGA-7", "RGA-8", "RGA-9", "RGA-10", "RGA-13", "RGA-14"],
        "required_contract": ["RGA-11", "RGA-12"],
        "not_in_scope": ["RGA-15", "RGA-16"],
    },
    "R2_mechanics": {
        "required_runtime": [],
        "required_contract": [],
        "not_in_scope": [],
        "not_implemented": True,
    },
    "R3_almanac": {
        "required_runtime": ["RGA-1", "RGA-2", "RGA-3", "RGA-4", "RGA-5", "RGA-6",
                             "RGA-7", "RGA-8", "RGA-9", "RGA-10", "RGA-13", "RGA-14",
                             "RGA-15"],
        "required_contract": ["RGA-11", "RGA-12"],
        "not_in_scope": ["RGA-16"],
    },
    "R4_integration": {
        "required_runtime": list(RGA_IDS),
        "required_contract": [],
        "not_in_scope": [],
    },
}


def evaluate_profile(profile_name: str, results: dict[str, str]) -> dict[str, Any]:
    """Compute an acceptance verdict from per-gate states.

    `results` maps gate_id -> one of PASS / FAIL / NOT_IN_SCOPE. `NOT_IN_SCOPE`
    is NEVER counted as a PASS. Overall PASS requires EVERY required_runtime gate
    to pass AND EVERY required_contract gate to pass.

    A profile marked `not_implemented` always returns NOT_IMPLEMENTED (fail-closed).
    """
    if profile_name not in PHASE_PROFILES:
        raise ValueError(f"unknown acceptance profile: {profile_name}")
    profile = PHASE_PROFILES[profile_name]

    if profile.get("not_implemented"):
        return {
            "profile": profile_name,
            "overall": GateState.NOT_IMPLEMENTED.value,
            "not_implemented": True,
            "required_runtime_pass": [], "required_runtime_fail": [],
            "required_contract_pass": [], "required_contract_fail": [],
            "not_in_scope": profile["not_in_scope"],
            "results": dict(results),
        }

    required_runtime = profile["required_runtime"]
    required_contract = profile["required_contract"]

    rt_pass = [gid for gid in required_runtime
               if results.get(gid) == GateState.PASS.value]
    rt_fail = [gid for gid in required_runtime
               if results.get(gid) != GateState.PASS.value]
    rc_pass = [gid for gid in required_contract
               if results.get(gid) == GateState.PASS.value]
    rc_fail = [gid for gid in required_contract
               if results.get(gid) != GateState.PASS.value]

    overall = (GateState.PASS.value
               if not rt_fail and not rc_fail else GateState.FAIL.value)
    return {
        "profile": profile_name,
        "overall": overall,
        "required_runtime_pass": rt_pass,
        "required_runtime_fail": rt_fail,
        "required_contract_pass": rc_pass,
        "required_contract_fail": rc_fail,
        "not_in_scope": profile["not_in_scope"],
        "not_in_scope_count": len(profile["not_in_scope"]),
        "results": dict(results),
    }


Check = Callable[[], tuple[str, str]]


def run_acceptance(profile_name: str = "R1_foundation") -> dict[str, Any]:
    """Run the actual acceptance checks and fold through a phase profile."""
    profile = PHASE_PROFILES[profile_name]
    if profile.get("not_implemented"):
        return evaluate_profile(profile_name, {})

    from . import acceptance_checks

    checks: dict[str, Check] = acceptance_checks.R1_CHECKS
    results: dict[str, str] = {}

    for gid in RGA_IDS:
        if gid in profile["not_in_scope"]:
            results[gid] = GateState.NOT_IN_SCOPE.value
            continue
        check = checks.get(gid)
        if check is None:
            results[gid] = GateState.NOT_IN_SCOPE.value
            continue
        try:
            state, _detail = check()
            results[gid] = state
        except Exception:  # noqa: BLE001 - fail-closed on any check error
            results[gid] = GateState.FAIL.value

    return evaluate_profile(profile_name, results)
