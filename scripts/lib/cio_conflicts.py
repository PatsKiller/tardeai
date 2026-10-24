"""CIO-owned conflict projections for review, brief, Ask and promotion consumers.

The schemas are produced by the one nested conflict ledger writer. These explicit
references bring them into the native CIO census rather than hiding a nested store.
"""
from scripts.lib.conflicts.cio import context_for, digest
from scripts.lib.conflicts.ledger import list_records

EVENT_SCHEMA = "ConflictEvent@v1"
RECORD_SCHEMA = "ConflictRecord@v1"
DECISION_SCHEMA = "ConflictDecision@v1"


def conflicts_for(root, security_guid):
    """Shared records, never per-consumer classification or source selection."""
    return context_for(root, security_guid)


def brief_context(root):
    return digest(root)


def conviction_gate(root, security_guid):
    context = context_for(root, security_guid)
    return {"actionable_promotion_allowed": not context["blocks_promotion"],
            "reason": (context.get("gap") or {}).get("reason") or "open conflict requires a current owner decision or source repair"
            if context["blocks_promotion"] else None,
            "conflicts": context["open_conflicts"]}
