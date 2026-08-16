"""cio_decision_quality.py — phase-aware CIO Decision Quality acceptance.

CDQ acceptance gates are evaluated per PR phase. Each phase profile declares
which gates are REQUIRED, CONTRACT_ONLY, or NOT_IN_SCOPE:

  * REQUIRED      — must be PASS. FAIL or NOT_IN_SCOPE here fails the profile.
  * CONTRACT_ONLY — declared but not yet enforceable in this phase; FAIL here
                    fails the profile, NOT_IN_SCOPE/PASS are tolerated.
  * NOT_IN_SCOPE  — explicitly out of scope for this phase; never counted as
                    PASS and never counted toward profile completion.

A profile passes only when every REQUIRED gate is PASS and no CONTRACT_ONLY
gate is FAIL. NOT_IN_SCOPE is a statement of scope, not evidence of success.

Authority: READ_ONLY_ADVISORY. Pure evaluators only — no network, no broker
orders, no Telegram sends.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

AUTHORITY = "READ_ONLY_ADVISORY"
CDQ_VERSION = "cio_decision_quality_1.0.0"

VALID_STATUS = ("PASS", "FAIL", "NOT_IN_SCOPE")

# ─────────────────────────────────────────────────────────────────────────────
# Gate registry (PR1 decision-truth + cross-cutting CDQ-25..29)
# ─────────────────────────────────────────────────────────────────────────────

GATES: dict[str, str] = {
    # PR1 — Decision Truth & Identity
    "PR1_STANDING_CURRENT_PARITY": (
        "standing view and current action are distinct and consistent across "
        "web + Telegram"
    ),
    "PR1_ACTIONABILITY": (
        "stale / risk text can never render ACT NOW; ACT_NOW requires explicit "
        "act_now=True or ACT_NOW label"
    ),
    "PR1_SIZING_ZERO": (
        "no verified sizing objective => recommended delta $0; 10% tranche is "
        "scenario-only"
    ),
    "PR1_DIGEST_409": (
        "DIGEST_CAPABLE decisions require the exact input+evidence digest pair; "
        "missing or wrong digest => 409"
    ),
    "PR1_REENTRY_CANONICAL": (
        "canonical re-entry lifecycle; READY_TO_REVIEW is never RE_ENTER"
    ),
    # Cross-cutting (user-added)
    "CDQ-25": "all production CIO writers/readers execute from approved CURRENT release",
    "CDQ-26": "no live CIO process or scheduled job resolves to deprecated project tree",
    "CDQ-27": "no fallback/scenario-only trim contributes to prospective capital sources",
    "CDQ-28": "operator feedback sample count is disjoint from measured outcome sample count",
    "CDQ-29": "exactly one runtime path owns outcome maturation for each case generation",
    # Tightened capital invariant (PR2)
    "CAPITAL_ACT_NOW_ZERO": (
        "ACT_NOW=0 globally implies deploy_now=0 AND no conditional/prospective "
        "source labeled AVAILABLE_NOW AND no candidate use presented as an "
        "authorized recommendation"
    ),
}

# ─────────────────────────────────────────────────────────────────────────────
# Phase profiles
# ─────────────────────────────────────────────────────────────────────────────

PROFILES: dict[str, dict[str, frozenset[str]]] = {
    "PR1_DECISION_TRUTH": {
        "required": frozenset({
            "PR1_STANDING_CURRENT_PARITY",
            "PR1_ACTIONABILITY",
            "PR1_SIZING_ZERO",
            "PR1_DIGEST_409",
            "PR1_REENTRY_CANONICAL",
            "CDQ-27",
        }),
        "contract_only": frozenset({
            "CDQ-25",
            "CDQ-26",
            "CAPITAL_ACT_NOW_ZERO",
        }),
        "not_in_scope": frozenset({
            "CDQ-28",
            "CDQ-29",
        }),
    },
}

PROFILE_IDS = tuple(PROFILES.keys())


def evaluate_profile(
    profile_id: str,
    results: dict[str, str],
) -> dict[str, Any]:
    """Evaluate a phase profile from a {gate_id: status} map.

    Returns a verdict record with per-gate status, required/contract_only
    aggregation, and an overall `pass` boolean. NOT_IN_SCOPE never counts as
    PASS and never satisfies a REQUIRED gate.
    """
    profile = PROFILES.get(profile_id)
    if profile is None:
        raise ValueError(f"unknown CDQ profile: {profile_id}")

    required = profile["required"]
    contract_only = profile["contract_only"]
    not_in_scope = profile["not_in_scope"]

    normalized: dict[str, str] = {}
    for gid, status in results.items():
        st = str(status or "FAIL").upper()
        normalized[gid] = st if st in VALID_STATUS else "FAIL"

    required_fail: list[str] = []
    for gid in sorted(required):
        st = normalized.get(gid, "NOT_IN_SCOPE")
        if st != "PASS":
            required_fail.append(f"{gid}:{st}")

    contract_fail: list[str] = []
    for gid in sorted(contract_only):
        st = normalized.get(gid, "NOT_IN_SCOPE")
        if st == "FAIL":
            contract_fail.append(f"{gid}:FAIL")

    # NOT_IN_SCOPE gates that are neither required nor contract are declared.
    declared = set(required) | set(contract_only) | set(not_in_scope)
    undeclared = sorted(set(normalized) - declared)

    ok = (not required_fail) and (not contract_fail)

    return {
        "profile": profile_id,
        "version": CDQ_VERSION,
        "authority": AUTHORITY,
        "pass": ok,
        "required": sorted(required),
        "contract_only": sorted(contract_only),
        "not_in_scope": sorted(not_in_scope),
        "required_fail": required_fail,
        "contract_fail": contract_fail,
        "undeclared_gates": undeclared,
        "gates": {gid: normalized.get(gid, "NOT_IN_SCOPE") for gid in sorted(declared)},
        "not_in_scope_counts_as_pass": False,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Pure PR1 evaluators (decision truth & identity)
# ─────────────────────────────────────────────────────────────────────────────

def evaluate_pr1_actionability(decision: dict[str, Any]) -> tuple[str, list[str]]:
    """PR1_ACTIONABILITY — stale/risk text never renders ACT NOW.

    Returns (status, violations). PASS only when a decision whose risk text
    screams breach does not surface as ACT NOW unless act_now/label demand it.
    """
    from scripts.lib.cio_command_center import _actionability_urgency
    label = str(decision.get("action_label") or "").upper()
    act_now = decision.get("act_now") is True or label == "ACT_NOW"
    urgency = _actionability_urgency(decision)
    violations: list[str] = []
    if act_now and urgency != "high":
        violations.append("ACT_NOW did not map to high urgency")
    if not act_now and urgency == "high":
        violations.append("high urgency without explicit ACT_NOW")
    # Risk text alone must never elevate actionability.
    risk = str(decision.get("risk") or "").lower()
    if not act_now and urgency == "high" and ("concentration" in risk or "fire" in risk or "breach" in risk):
        violations.append("risk text elevated urgency to high without ACT_NOW")
    status = "PASS" if not violations else "FAIL"
    return status, violations


def evaluate_pr1_sizing_zero(
    positions: list[dict[str, Any]],
    *,
    portfolio_value: float,
    policy_cap_pct: float,
    fire_pct: float,
) -> tuple[str, list[str]]:
    """PR1_SIZING_ZERO — a below-policy/fire advisory TRIM yields $0 delta.

    Returns (status, violations). Each violation names a symbol that still
    emitted a non-zero recommended delta without a verified objective.
    """
    from scripts.lib.cio_institutional_sizing import recommend_trim
    violations: list[str] = []
    for p in positions:
        mv = float(p.get("market_value_usd") or p.get("current_value_usd") or 0.0)
        weight = (mv / portfolio_value * 100.0) if portfolio_value else 0.0
        if weight >= policy_cap_pct or weight >= fire_pct:
            # Above policy/fire is a real objective; skip the no-objective check.
            continue
        rec = recommend_trim(
            market_value_usd=mv,
            weight_pct=weight,
            portfolio_value_usd=portfolio_value,
            policy_cap_pct=policy_cap_pct,
            fire_pct=fire_pct,
            advisory_trim=True,
        )
        delta = float(rec.get("recommended_delta_usd") or 0.0)
        if delta != 0.0:
            violations.append(
                f"{p.get('symbol')}: below policy/fire advisory TRIM emitted "
                f"{delta} delta (method={rec.get('method')})"
            )
    status = "PASS" if not violations else "FAIL"
    return status, violations


def evaluate_pr1_digest_409(catalog_digest: str, supplied_digest: Optional[str]) -> tuple[str, list[str]]:
    """PR1_DIGEST_409 — DIGEST_CAPABLE requires exact pair; missing => reject.

    Returns (status, violations). A missing supplied digest for a non-empty
    catalog digest must be rejected (fail-closed), never accepted.
    """
    from scripts.api_v3_cio import _digests_match
    violations: list[str] = []
    if catalog_digest and not supplied_digest:
        if _digests_match(supplied_digest or "", catalog_digest):
            violations.append("missing supplied digest accepted for DIGEST_CAPABLE")
    if supplied_digest and supplied_digest != catalog_digest and catalog_digest:
        if _digests_match(supplied_digest, catalog_digest):
            violations.append("wrong supplied digest accepted for DIGEST_CAPABLE")
    status = "PASS" if not violations else "FAIL"
    return status, violations


def evaluate_pr1_reentry_canonical() -> tuple[str, list[str]]:
    """PR1_REENTRY_CANONICAL — READY_TO_REVIEW / NEAR ENTRY never grant RE_ENTER.

    Returns (status, violations).
    """
    from scripts.lib.cio_decision_semantics import (
        REENTRY_LIFECYCLE,
        stance_from_queue_item,
    )
    violations: list[str] = []
    if "RE_ENTER" not in REENTRY_LIFECYCLE:
        violations.append("REENTRY_LIFECYCLE missing RE_ENTER terminal state")
    for state in ("READY TO REVIEW", "NEAR ENTRY", "OVERSOLD REVIEW", "DESK READY"):
        got = stance_from_queue_item({"symbol": "TST", "state": state})
        if got == "RE_ENTER":
            violations.append(f"{state!r} mapped to RE_ENTER")
    status = "PASS" if not violations else "FAIL"
    return status, violations


def evaluate_cdq27_scenario_only_zero(
    positions: list[dict[str, Any]],
    queue: dict[str, Any],
) -> tuple[str, list[str]]:
    """CDQ-27 — no fallback/scenario-only trim contributes to capital sources.

    Returns (status, violations). Uses the capital-sources builder with and
    without portfolio context to prove the trim yields $0 either way.
    """
    from scripts.lib.cio_capital_plan import build_capital_sources
    violations: list[str] = []
    for context in ({"portfolio_value": 0.0}, {}):
        src = build_capital_sources(positions, queue=queue, **context)
        if float(src.get("trims_usd") or 0.0) != 0.0:
            violations.append(
                f"trims_usd={src.get('trims_usd')} with context={context}"
            )
        if float(src.get("total_prospective_raise_usd") or 0.0) != 0.0:
            violations.append(
                f"prospective raise={src.get('total_prospective_raise_usd')} "
                f"with context={context}"
            )
    status = "PASS" if not violations else "FAIL"
    return status, violations
