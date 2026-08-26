"""Deterministic thesis/delta precedence for advisory decisions.

The gate can restrict or preserve an upstream advisory action. It never creates
RE_ENTER, ADD, BUY, broker authority, or execution instructions.
"""
from __future__ import annotations

from typing import Any

AUTHORITY = "READ_ONLY_ADVISORY"
SCHEMA = "ThesisDecisionGate@v1"


def apply_thesis_decision_gate(
    *,
    current_action: str,
    governed_verdict: str | None,
    thesis_state: str | None,
    thesis_stance: str | None = None,
    delta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply fail-closed thesis precedence without generating a promotion."""
    action = str(current_action or "WAIT").upper()
    upstream_action = action
    upstream_verdict = str(governed_verdict or "").upper() or None
    effective_verdict = upstream_verdict
    state = str(thesis_state or "INSUFFICIENT_DATA").upper()
    stance = str(thesis_stance or "").upper()
    classification = str((delta or {}).get("classification") or "").upper()
    freshness_state = str(((delta or {}).get("freshness") or {}).get("state") or "UNKNOWN").upper()
    fresh_delta = freshness_state != "STALE"
    reasons: list[str] = []

    invalidated = state in {"BROKEN", "INVALIDATED"} or stance in {"AVOID", "DO_NOT_REENTER", "RETIRED"}
    invalidated = invalidated or (fresh_delta and classification == "INVALIDATES")
    conflicted = state == "CONFLICTED" or (fresh_delta and classification == "CONFLICTED")
    weakened = fresh_delta and classification == "WEAKENS"
    incomplete = state in {"RESEARCH_REQUIRED", "INSUFFICIENT_DATA", "STALE"} or classification == "INSUFFICIENT_DATA"

    if invalidated:
        action = "AVOID" if upstream_action in {"AVOID", "REENTER", "RE_ENTER"} else "WAIT"
        effective_verdict = None
        reasons.append("FRESH_THESIS_INVALIDATION_BLOCKS_REENTER")
    elif conflicted:
        action = "WAIT"
        effective_verdict = None
        reasons.append("THESIS_CONFLICT_FAILS_CLOSED_TO_REVIEW")
    elif weakened:
        if action in {"REENTER", "RE_ENTER", "ADD", "BUY"}:
            action = "NEAR"
        reasons.append("WEAKENING_CAN_DEMOTE_BUT_NEVER_PROMOTE")
    elif incomplete:
        if not upstream_verdict and action in {"REENTER", "RE_ENTER", "ADD", "BUY"}:
            action = "NEAR"
        reasons.append("INCOMPLETE_RESEARCH_BLOCKS_UNGOVERNED_HIGH_CONVICTION")
    elif classification in {"CONFIRMS", "STRENGTHENS"}:
        reasons.append("POSITIVE_DELTA_MAY_RAISE_COMPLETENESS_NOT_ACTION")
    elif classification == "NO_NEW_INFO":
        reasons.append("NO_NEW_INFO_NO_ADVISORY_CHANGE")
    else:
        reasons.append("NO_MATERIAL_THESIS_RESTRICTION")

    return {
        "schema": SCHEMA,
        "upstream_action": upstream_action,
        "effective_action": action,
        "operator_governed_verdict": upstream_verdict,
        "effective_governed_verdict": effective_verdict,
        "thesis_state": state,
        "delta_id": (delta or {}).get("delta_id"),
        "delta_classification": classification or None,
        "delta_freshness": freshness_state,
        "restricted": action != upstream_action or effective_verdict != upstream_verdict,
        "reason_codes": reasons,
        "positive_delta_created_promotion": False,
        "authority": AUTHORITY,
        "financial_action": False,
    }
