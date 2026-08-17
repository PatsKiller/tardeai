"""agent_followup.py — durable follow-up binding + proactive advisory messages.

READ_ONLY_ADVISORY. Implements Phase 6 (Autonomous Office Initiative):
durable next-review bindings for material non-actions, notification-policy
reopen logic, and the proactive advisory message format.

Invariants:
  * a material non-action (WAIT / REVALIDATE / DATA_UNAVAILABLE / DEFER /
    RESEARCH) must bind a durable next review with a kind in
    {TIME, CONDITION, DATA_FRESHNESS, EVENT}, or explicitly
    NEXT_REVIEW_UNAVAILABLE + reason — never a bare "NEXT REVIEW"
  * an unchanged replay of a prior REJECT / ACK / DONE is SUPPRESSed
  * new evidence may reopen a prior REJECT only as
    "WHAT CHANGED SINCE YOUR REJECT" — never silently
  * proactive advisory messages omit the memory line entirely unless a
    decision-relevant memory view is supplied (never mention memory just to
    sound intelligent)
"""
from __future__ import annotations

import uuid
from typing import Any, Optional

from scripts.lib.agent_notification_intelligence import (
    NEXT_KIND_CONDITION,
    NEXT_KIND_DATA_FRESHNESS,
    NEXT_KIND_EVENT,
    NEXT_KIND_TIME,
    NEXT_REVIEW_UNAVAILABLE,
)

# Non-action current actions that MUST bind a durable next review.
_NON_ACTION_ACTIONS = frozenset({
    "WAIT",
    "REVALIDATE",
    "DATA_UNAVAILABLE",
    "DEFER",
    "RESEARCH",
})

_BOUND_KINDS = frozenset({
    NEXT_KIND_TIME,
    NEXT_KIND_CONDITION,
    NEXT_KIND_DATA_FRESHNESS,
    NEXT_KIND_EVENT,
})

_SUPPRESSING_DISPOSITIONS = frozenset({"REJECT", "ACK", "DONE"})

_REOPEN_LABEL = "WHAT CHANGED SINCE YOUR REJECT"


def build_durable_next_review(
    current_action: str,
    *,
    kind: Optional[str],
    due_at: Optional[str] = None,
    condition: Optional[str] = None,
    revisit_id: Optional[str] = None,
    lineage: Optional[str] = None,
    unavailable_reason: Optional[str] = None,
) -> dict[str, Any]:
    """Build a durable next-review binding (or explicit unavailable record).

    A non-action current_action requires a bound ``kind`` in
    {TIME, CONDITION, DATA_FRESHNESS, EVENT}. The only acceptable alternative
    is an explicit ``NEXT_REVIEW_UNAVAILABLE`` with a ``reason``. A bare
    "NEXT REVIEW" with no binding raises ``ValueError``.
    """
    action = str(current_action or "").upper()
    k = str(kind or "").upper()

    if k == NEXT_REVIEW_UNAVAILABLE:
        if not unavailable_reason:
            raise ValueError("NEXT_REVIEW_UNAVAILABLE requires a reason")
        return {
            "kind": NEXT_REVIEW_UNAVAILABLE,
            "due_at": None,
            "condition": None,
            "revisit_id": None,
            "lineage": lineage,
            "reason": unavailable_reason,
        }

    if k not in _BOUND_KINDS:
        if action in _NON_ACTION_ACTIONS:
            raise ValueError(
                f"non-action current_action={action!r} requires a bound next-review "
                f"kind (TIME/CONDITION/DATA_FRESHNESS/EVENT) or "
                f"NEXT_REVIEW_UNAVAILABLE + reason; got kind={k!r}"
            )
        raise ValueError(f"bare next review requires a binding kind; got kind={k!r}")

    return {
        "kind": k,
        "due_at": due_at,
        "condition": condition,
        "revisit_id": revisit_id or f"rv_{uuid.uuid4().hex[:16]}",
        "lineage": lineage,
    }


def validate_durable_next_review(next_review: Any) -> tuple[bool, str]:
    """Reject a bare or under-bound next review. Returns (ok, reason).

    * ``kind`` is required.
    * ``TIME`` requires ``due_at``.
    * ``CONDITION`` / ``DATA_FRESHNESS`` / ``EVENT`` require a condition or
      event descriptor.
    * a bound kind requires ``revisit_id`` or ``lineage``.
    * ``NEXT_REVIEW_UNAVAILABLE`` requires ``reason``.
    """
    if not isinstance(next_review, dict):
        return False, "next_review missing"
    kind = str(next_review.get("kind") or "").upper()
    if not kind:
        return False, "next_review.kind missing"

    if kind == NEXT_REVIEW_UNAVAILABLE:
        if not next_review.get("reason"):
            return False, "NEXT_REVIEW_UNAVAILABLE without reason"
        return True, "explicitly unavailable"

    if kind == NEXT_KIND_TIME:
        if not next_review.get("due_at"):
            return False, "TIME next review without due_at"
    elif kind in (NEXT_KIND_CONDITION, NEXT_KIND_DATA_FRESHNESS, NEXT_KIND_EVENT):
        descriptor = (
            next_review.get("condition")
            or next_review.get("event")
            or next_review.get("descriptor")
        )
        if not descriptor:
            return False, f"{kind} next review without condition/event descriptor"
    else:
        return False, f"unknown kind: {kind}"

    if not (next_review.get("revisit_id") or next_review.get("lineage")):
        return False, f"kind={kind} without revisit_id or lineage"

    return True, f"bound ({kind})"


def reopen_after_reject(
    previous_disposition: Optional[str],
    same_identity: bool,
    same_evidence: bool,
) -> str:
    """Decide whether a previously-seen recommendation may be re-sent.

    * ``SUPPRESS`` — an unchanged replay of a prior REJECT / ACK / DONE.
    * ``WHAT CHANGED SINCE YOUR REJECT`` — a prior REJECT exists but the
      evidence digest changed.
    * ``ALLOW`` — everything else (no prior suppressing disposition, or a new
      identity).
    """
    disposition = str(previous_disposition or "").upper()

    if disposition in _SUPPRESSING_DISPOSITIONS and same_identity and same_evidence:
        return "SUPPRESS"
    # Only the SAME recommendation with changed evidence may be reopened as
    # "WHAT CHANGED SINCE YOUR REJECT". A new identity is ALLOW regardless of
    # whether the evidence also changed.
    if disposition == "REJECT" and same_identity and not same_evidence:
        return _REOPEN_LABEL
    return "ALLOW"


def _format_next_review(next_review: Any) -> str:
    if isinstance(next_review, dict):
        kind = str(next_review.get("kind") or "")
        if kind == NEXT_REVIEW_UNAVAILABLE:
            return f"{kind}: {next_review.get('reason', '')}".strip()
        due = (
            next_review.get("due_at")
            or next_review.get("condition")
            or next_review.get("event")
            or next_review.get("revisit_id")
            or ""
        )
        return f"{kind} {due}".strip()
    return str(next_review)


def compose_advisory_message(
    *,
    what_changed: str,
    current_action: str,
    why: str,
    memory_view: Optional[str] = None,
    counter_thesis: Optional[str] = None,
    changes_my_mind: Optional[str] = None,
    next_review: Any = None,
) -> str:
    """Assemble the proactive advisory message.

    Sections: WHAT CHANGED / MY CURRENT ACTION / WHY /
    MEMORY-PRIOR-OPERATOR-VIEW / COUNTER-THESIS / WHAT CHANGES MY MIND /
    NEXT REVIEW.

    The MEMORY-PRIOR-OPERATOR-VIEW line is emitted only when ``memory_view`` is
    decision-relevant and non-empty; it is omitted otherwise — memory is never
    mentioned merely to sound intelligent.
    """
    sections: list[tuple[str, str]] = [
        ("WHAT CHANGED", str(what_changed or "")),
        ("MY CURRENT ACTION", str(current_action or "")),
        ("WHY", str(why or "")),
    ]
    if memory_view:
        sections.append(("MEMORY-PRIOR-OPERATOR-VIEW", str(memory_view)))
    if counter_thesis:
        sections.append(("COUNTER-THESIS", str(counter_thesis)))
    if changes_my_mind:
        sections.append(("WHAT CHANGES MY MIND", str(changes_my_mind)))
    if next_review is not None:
        sections.append(("NEXT REVIEW", _format_next_review(next_review)))

    return "\n\n".join(f"{label}\n{body}" for label, body in sections)
