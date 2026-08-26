"""PreferenceCandidate@v1 — repeated feedback may propose, never enact, policy.

MEMORY_BEHAVIOR_INFLUENCE remains 0. Operator confirmation required.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

AUTHORITY = "READ_ONLY_ADVISORY"
SCHEMA = "PreferenceCandidate@v1"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def from_feedback(
    *,
    subject_guid: str,
    statement: str,
    supporting_feedback_ids: list[str],
    contradictions: list[str] | None = None,
    first_seen: str | None = None,
    last_seen: str | None = None,
) -> dict[str, Any]:
    n = len(supporting_feedback_ids)
    return {
        "schema": SCHEMA,
        "preference_candidate_id": str(uuid.uuid4()),
        "subject_guid": subject_guid,
        "statement": statement[:400],
        "supporting_feedback_ids": list(supporting_feedback_ids),
        "contradictions": list(contradictions or []),
        "sample_size": n,
        "confidence": "low" if n < 3 else ("medium" if n < 8 else "high"),
        "first_seen": first_seen or _now(),
        "last_seen": last_seen or _now(),
        "operator_confirmed": False,
        "policy_effect": False,
        "memory_behavior_influence": 0,
        "authority": AUTHORITY,
        "financial_action": False,
    }


def confirm(candidate: dict[str, Any], *, operator_id: str) -> dict[str, Any]:
    """Confirmation records intent. It does not flip MEMORY_BEHAVIOR_INFLUENCE."""
    out = dict(candidate)
    out["operator_confirmed"] = True
    out["confirmed_by"] = operator_id
    out["confirmed_at"] = _now()
    out["policy_effect"] = False
    out["memory_behavior_influence"] = 0
    return out
