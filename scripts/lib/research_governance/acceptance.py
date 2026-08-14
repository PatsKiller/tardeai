"""Research governance — subsystem acceptance RGA-1..RGA-16 (PR-R1).

Separate namespace from the promotion ladder (RG-*). RG gates govern the
lifecycle of a particular hypothesis/fact; RGA gates govern whether the research
SUBSYSTEM ITSELF is production-quality.

Canonical RGA mapping (single source of truth — keep plan, docs, runner, and
result packet consistent with this):

  RGA-1  source_registry_exact_manifest
  RGA-2  provenance_complete
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

Phase-aware acceptance: PASS / FAIL / NOT_IN_SCOPE. `NOT_IN_SCOPE` is NEVER
counted as a PASS. A profile passes only when every gate it *requires* passes.
The R1 profile validates STATISTICAL CORRECTNESS via golden/reference vectors,
not merely value ranges.
"""
from __future__ import annotations

from typing import Any, Callable

from .enums import GateState

RGA_IDS: tuple[str, ...] = tuple(f"RGA-{i}" for i in range(1, 17))

GATE_NAMES: dict[str, str] = {
    "RGA-1": "source_registry_exact_manifest",
    "RGA-2": "provenance_complete",
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

PHASE_PROFILES: dict[str, dict[str, list[str]]] = {
    "R1_foundation": {
        "required": ["RGA-1", "RGA-2", "RGA-3", "RGA-4", "RGA-5", "RGA-6",
                     "RGA-7", "RGA-8", "RGA-9", "RGA-10", "RGA-13", "RGA-14"],
        "contract_only": ["RGA-11", "RGA-12"],
        "not_in_scope": ["RGA-15", "RGA-16"],
    },
    "R2_mechanics": {
        "required": ["RGA-1", "RGA-2", "RGA-3", "RGA-4", "RGA-5", "RGA-6",
                     "RGA-7", "RGA-8", "RGA-9", "RGA-10", "RGA-13", "RGA-14"],
        "contract_only": ["RGA-11", "RGA-12"],
        "not_in_scope": ["RGA-15", "RGA-16"],
    },
    "R3_almanac": {
        "required": ["RGA-1", "RGA-2", "RGA-3", "RGA-4", "RGA-5", "RGA-6",
                     "RGA-7", "RGA-8", "RGA-9", "RGA-10", "RGA-13", "RGA-14",
                     "RGA-15"],
        "contract_only": ["RGA-11", "RGA-12"],
        "not_in_scope": ["RGA-16"],
    },
    "R4_integration": {
        "required": list(RGA_IDS),
        "contract_only": [],
        "not_in_scope": [],
    },
}


def evaluate_profile(profile_name: str, results: dict[str, str]) -> dict[str, Any]:
    """Compute an acceptance verdict from per-gate states.

    `results` maps gate_id -> one of PASS / FAIL / NOT_IN_SCOPE. `NOT_IN_SCOPE`
    is NEVER counted as a PASS: a profile passes only when every gate it
    *requires* passes. Gates the profile declares out of scope are reported as
    not_in_scope regardless of any accidental value in `results`.
    """
    if profile_name not in PHASE_PROFILES:
        raise ValueError(f"unknown acceptance profile: {profile_name}")
    profile = PHASE_PROFILES[profile_name]

    required = profile["required"]
    not_in_scope = profile["not_in_scope"]

    required_pass = [gid for gid in required
                     if results.get(gid) == GateState.PASS.value]
    fails = [gid for gid in required
             if results.get(gid) != GateState.PASS.value]

    overall = GateState.PASS.value if not fails else GateState.FAIL.value
    return {
        "profile": profile_name,
        "overall": overall,
        "required_pass": required_pass,
        "required_fail": fails,
        "not_in_scope": not_in_scope,
        "not_in_scope_count": len(not_in_scope),
        "contract_only": profile["contract_only"],
        "results": dict(results),
    }


Check = Callable[[], tuple[str, str]]


def run_acceptance(profile_name: str = "R1_foundation") -> dict[str, Any]:
    """Run the actual acceptance checks and fold through a phase profile."""
    from . import acceptance_checks

    checks: dict[str, Check] = acceptance_checks.R1_CHECKS
    results: dict[str, str] = {}

    profile = PHASE_PROFILES[profile_name]
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

    report = evaluate_profile(profile_name, results)
    return report
