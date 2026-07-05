"""Hermes operator approval boundaries — advisory-only, execution-blocked."""
from __future__ import annotations

from typing import Any

HERMES_ADVISORY_ONLY = True

EXECUTION_BLOCKED_SURFACES = frozenset({
    "live_broker_writes",
    "schwab_transport",
    "fidelity_transport",
    "oco_readiness",
    "protective_stop_placement",
    "position_liquidation",
    "strategy_promotion_live",
    "2fa_approval",
    "execution_state",
    "api_write_enabled",
})

OPERATOR_APPROVAL_REQUIRED = frozenset({
    "scope_budget_change",
    "widen_scope",
    "retire_source",
    "strategy_config_change",
    "threshold_outside_rails",
})

AUTO_APPLY_INSIDE_RAILS = frozenset({
    "raise_threshold_small",
    "lower_threshold_small",
    "tighten_scope_minor",
})


def hermes_governance_status() -> dict[str, Any]:
    """Return hard governance boundaries for API and tests."""
    return {
        "advisory_only": HERMES_ADVISORY_ONLY,
        "execution_blocked_surfaces": sorted(EXECUTION_BLOCKED_SURFACES),
        "operator_approval_required_actions": sorted(OPERATOR_APPROVAL_REQUIRED),
        "auto_apply_inside_rails_actions": sorted(AUTO_APPLY_INSIDE_RAILS),
        "broker_writes_allowed": False,
        "oco_modification_allowed": False,
        "stop_placement_allowed": False,
        "strategy_live_promotion_allowed": False,
        "note": "Hermes informs, ranks, warns, and proposes — never executes",
    }


def assert_hermes_cannot_modify_execution(surface: str) -> dict[str, Any]:
    """Raise-style check returning blocked result for execution surfaces."""
    s = str(surface or "").lower()
    if s in EXECUTION_BLOCKED_SURFACES or any(x in s for x in ("broker", "oco", "2fa", "liquidat")):
        return {
            "allowed": False,
            "surface": surface,
            "reason": "hermes_advisory_only_execution_blocked",
            "advisory_only": True,
        }
    return {"allowed": True, "surface": surface, "advisory_only": True}


def classify_proposal_action(proposal: dict[str, Any]) -> dict[str, Any]:
    """Classify whether a proposal can auto-apply or needs operator."""
    gates = proposal.get("evidence_gates") or (proposal.get("evidence") or {}).get("evidence_gates") or {}
    allowed_action = gates.get("allowed_action", "operator_approval_required")
    can_auto = allowed_action == "auto_apply_inside_rails" and gates.get("gates_pass")
    return {
        "allowed_action": allowed_action,
        "can_auto_apply": can_auto,
        "requires_operator_approval": not can_auto,
        "advisory_only": True,
        "gates_pass": gates.get("gates_pass", False),
    }