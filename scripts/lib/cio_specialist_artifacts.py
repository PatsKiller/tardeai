"""CIO specialist-artifact resolver — reconstruct committee inputs from real output.

Phase 4a (closing the loop). When a CIO run resumes (or a SPECIALIST_COMPLETION
run fires), the worker must convene the advisory committee from *completed*
specialist output, not an empty artifact list. This pure module resolves completed
handoffs into SpecialistAdvisory-shaped dicts consumable by
`vote_from_specialist_advisory`.

Read-only, provider-call-free. No execution authority.
"""
from __future__ import annotations

from typing import Any, Callable

# Handoff statuses that are terminal but contribute no advisory — they neither
# produce a vote nor keep the run waiting.
_NON_CONTRIBUTING_TERMINAL = frozenset({"FAILED", "EXPIRED", "CANCELLED", "BLOCKED"})

# Fallback vote position used when a legacy completion carries no explicit position.
_DEFAULT_POSITION = "NEUTRAL"
_DEFAULT_CONFIDENCE = 0.5


def extract_advisory_from_handoff(handoff: dict[str, Any] | None) -> dict[str, Any] | None:
    """Reconstruct a SpecialistAdvisory-shaped dict from a COMPLETED handoff.

    Prefers the full `specialist_advisory` envelope persisted on HANDOFF_COMPLETED.
    Falls back to a minimal NEUTRAL advisory when only summary/evidence are present,
    so a legacy completion still convenes — but never fabricates a position.
    """
    if not isinstance(handoff, dict):
        return None
    if handoff.get("current_status") != "COMPLETED":
        return None

    adv = handoff.get("specialist_advisory")
    if isinstance(adv, dict) and adv:
        out = dict(adv)
        out.setdefault("specialist_id", handoff.get("to_agent") or "")
        out.setdefault("position", _DEFAULT_POSITION)
        out.setdefault("confidence", _DEFAULT_CONFIDENCE)
        out.setdefault("rationale", str(handoff.get("summary") or ""))
        return out

    to_agent = handoff.get("to_agent") or ""
    if not to_agent:
        return None

    return {
        "specialist_id": to_agent,
        "position": _DEFAULT_POSITION,
        "confidence": _DEFAULT_CONFIDENCE,
        "rationale": str(handoff.get("summary") or ""),
        "evidence_refs": list(handoff.get("evidence_refs") or []),
    }


def resolve_run_specialist_advisories(
    run: dict[str, Any],
    get_handoff: Callable[[str], dict[str, Any] | None],
) -> dict[str, Any]:
    """Resolve completed specialist advisories for a CIO run.

    Scans the run's `parent_handoff_ids` and `specialist_requests`. Returns:
      advisories             — SpecialistAdvisory-shaped dicts from COMPLETED handoffs
      completed_handoff_ids  — handoff ids that produced an advisory
      pending_handoff_ids    — handoff ids still outstanding (PENDING/CLAIMED/STARTED)
      covered_specialists    — to_agent of every referenced handoff (completed or not)
    """
    handoff_ids: list[str] = []
    for key in ("parent_handoff_ids", "specialist_requests"):
        for hid in run.get(key) or []:
            if hid and hid not in handoff_ids:
                handoff_ids.append(hid)

    advisories: list[dict[str, Any]] = []
    completed: list[str] = []
    pending: list[str] = []
    covered: set[str] = set()

    for hid in handoff_ids:
        try:
            h = get_handoff(hid)
        except Exception:
            h = None

        if not isinstance(h, dict):
            pending.append(hid)
            continue

        to_agent = h.get("to_agent") or ""
        if to_agent:
            covered.add(to_agent)

        status = h.get("current_status")
        if status == "COMPLETED":
            adv = extract_advisory_from_handoff(h)
            if adv:
                advisories.append(adv)
                completed.append(hid)
            else:
                pending.append(hid)
        elif status in _NON_CONTRIBUTING_TERMINAL:
            # Terminal, no contribution — do not keep the run waiting on it.
            continue
        else:
            pending.append(hid)

    return {
        "advisories": advisories,
        "completed_handoff_ids": completed,
        "pending_handoff_ids": pending,
        "covered_specialists": covered,
    }
