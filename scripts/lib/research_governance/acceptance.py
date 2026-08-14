"""Research governance — subsystem acceptance RGA-1..RGA-16 (PR-R1).

Separate namespace from the promotion ladder (RG-*). RG gates govern the
lifecycle of a particular hypothesis/fact; RGA gates govern whether the research
SUBSYSTEM ITSELF is production-quality.

Phase-aware acceptance: an early PR cannot honestly pass gates that belong to a
later phase. Each gate is PASS / FAIL / NOT_IN_SCOPE. `NOT_IN_SCOPE` is NEVER
counted as a PASS. A profile passes only when every gate it *requires* passes.

Profiles:
  R1_foundation  required RGA-1..10, 13, 14; contract_only 11, 12; not_in_scope 15, 16
  R2_mechanics   inherits R1; adds fixed_income/etf/valuation mechanics
  R3_almanac     inherits R1; requires RGA-15 (almanac reproduction)
  R4_integration requires all RGA-1..16
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List

from .enums import GateState

RGA_IDS: tuple[str, ...] = tuple(f"RGA-{i}" for i in range(1, 17))

GATE_NAMES: dict[str, str] = {
    "RGA-1": "source_registry",
    "RGA-2": "claim_model",
    "RGA-3": "hypothesis_model",
    "RGA-4": "trial_registry",
    "RGA-5": "oos_consumption",
    "RGA-6": "multiple_testing",
    "RGA-7": "deflated_sharpe",
    "RGA-8": "pbo",
    "RGA-9": "reality_check",
    "RGA-10": "cv_purging",
    "RGA-11": "promotion_gate_contract",
    "RGA-12": "retrieval_contract",
    "RGA-13": "authority_boundary",
    "RGA-14": "scope_guard",
    "RGA-15": "almanac_reproduction",
    "RGA-16": "research_decision_use_audit",
}


# Phase profiles. `required` gates must PASS. `contract_only` gates must have a
# present contract but are not live-integrated yet. `not_in_scope` are explicitly
# out of scope and never count as PASS.
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
        "adds": ["fixed_income_mechanics", "etf_mechanics", "valuation_framework"],
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

    # Never let a declared-not-in-scope gate leak into the required accounting,
    # and never count it as a PASS.
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
    """Run the actual R1 acceptance checks and fold through a phase profile."""
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
            state, detail = check()
            results[gid] = state
        except Exception as exc:  # noqa: BLE001 - fail-closed on any check error
            results[gid] = GateState.FAIL.value

    report = evaluate_profile(profile_name, results)
    report["_detail"] = {gid: checks.get(gid) for gid in RGA_IDS}
    return report
