"""
CIO Action Validator — Post-synthesis action evidence validation.

After Alex produces a proposed action, validates whether the evidence
needed to execute that action is present. A BUY without buying power
is not an actionable recommendation.
"""

from __future__ import annotations
from typing import Any, Optional

# Action types from synthesis output
ACTION_TYPES = frozenset({"BUY", "SELL", "SELL_TAXABLE", "TRIM", "HOLD", "NO_ACTION"})

# Post-synthesis evidence requirements per action type
POST_SYNTHESIS_REQUIREMENTS = {
    "BUY": {
        "REQUIRED": ["portfolio", "cash_buying_power", "risk", "investment_policy"],
        "OPTIONAL": ["holdings_detail", "fundamentals", "catalysts", "analyst_actions"],
    },
    "SELL": {
        "REQUIRED": ["portfolio", "holdings_detail", "risk"],
        "OPTIONAL": [],
    },
    "SELL_TAXABLE": {
        "REQUIRED": ["portfolio", "holdings_detail", "risk", "cost_basis", "account_constraints"],
        "OPTIONAL": ["tax_lots"],
    },
    "TRIM": {
        "REQUIRED": ["portfolio", "holdings_detail", "risk", "investment_policy"],
        "OPTIONAL": ["cost_basis"],
    },
    "HOLD": {
        "REQUIRED": ["portfolio", "risk"],
        "OPTIONAL": [],
    },
    "NO_ACTION": {
        "REQUIRED": ["portfolio", "risk"],
        "OPTIONAL": [],
    },
}


def determine_action_type(proposed_action: dict[str, Any]) -> str:
    """Derive action type from synthesis output."""
    raw = proposed_action.get("action", proposed_action.get("proposed_action", ""))
    raw_upper = str(raw).upper().strip()

    if raw_upper in ACTION_TYPES:
        return raw_upper

    # Map common variations
    if raw_upper in ("BUY", "BUY_NEW"):
        return "BUY"
    if raw_upper in ("SELL", "SELL_ALL", "CLOSE"):
        return "SELL"
    if raw_upper in ("TRIM", "REDUCE", "PARTIAL_SELL"):
        return "TRIM"
    return "NO_ACTION"


def derive_taxable_sell_type(action_type: str, account_type: Optional[str]) -> str:
    """Determine if a SELL should be treated as SELL_TAXABLE based on account type.
    
    The validator derives taxability from account evidence, not from the model.
    The model does not get to declare its own tax-evidence requirements.
    
    Returns SELL_TAXABLE if account is taxable, SELL otherwise.
    """
    if action_type == "SELL":
        if account_type and account_type.upper() in ("TAXABLE", "INDIVIDUAL", "JOINT", "CASH"):
            return "SELL_TAXABLE"
    return action_type


def validate_action_evidence(
    action_type: str,
    snapshot_domains: dict[str, dict[str, Any]],
    *,
    account_type: Optional[str] = None,
    account_type_unknown: bool = False,
) -> dict[str, Any]:
    """Validate that required evidence exists for a proposed action.
    
    Returns:
        {
            "actionable": bool,
            "blocking_gaps": list[dict],
            "optional_gaps": list[dict],
            "action_type": str,
            "partial_recommendation": Optional[str],
        }
    """
    # Derive taxable sell type from account evidence, not model declaration
    actual_action_type = derive_taxable_sell_type(action_type, account_type)

    if actual_action_type not in POST_SYNTHESIS_REQUIREMENTS:
        return {
            "actionable": False,
            "blocking_gaps": [{"reason": f"Unknown action type: {action_type}"}],
            "optional_gaps": [],
            "action_type": action_type,
            "partial_recommendation": None,
        }

    reqs = POST_SYNTHESIS_REQUIREMENTS[actual_action_type]
    blocking_gaps = []
    optional_gaps = []

    # Check required domains
    for domain in reqs["REQUIRED"]:
        domain_entry = snapshot_domains.get(domain, {})
        state = domain_entry.get("state", "DATA_UNAVAILABLE")
        if state in ("DATA_UNAVAILABLE", "ERROR", "STALE", "CONFLICTED"):
            blocking_gaps.append({
                "domain": domain,
                "state": state,
                "reason": domain_entry.get("gap_reason", domain_entry.get("reason_code", "")),
                "is_required": True,
            })

    # Account type unknown is a special blocking condition for tax-sensitive actions
    if actual_action_type == "SELL" and account_type_unknown:
        blocking_gaps.append({
            "domain": "account_constraints",
            "state": "DATA_UNAVAILABLE",
            "reason": "Account type unknown — cannot determine tax treatment",
            "is_required": True,
        })

    # Check optional domains
    for domain in reqs["OPTIONAL"]:
        domain_entry = snapshot_domains.get(domain, {})
        state = domain_entry.get("state", "DATA_UNAVAILABLE")
        if state in ("DATA_UNAVAILABLE", "ERROR", "STALE"):
            optional_gaps.append({
                "domain": domain,
                "state": state,
                "reason": domain_entry.get("gap_reason", ""),
                "is_required": False,
            })

    actionable = len(blocking_gaps) == 0

    partial_recommendation = None
    if not actionable:
        gap_descriptions = [g["domain"] for g in blocking_gaps]
        partial_recommendation = (
            f"The evidence points toward {action_type}, but this action cannot be "
            f"made actionable until the following evidence is verified: "
            f"{', '.join(gap_descriptions)}"
        )

    return {
        "actionable": actionable,
        "blocking_gaps": blocking_gaps,
        "optional_gaps": optional_gaps,
        "action_type": actual_action_type,
        "partial_recommendation": partial_recommendation,
    }
