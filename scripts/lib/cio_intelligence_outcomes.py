"""Decision ↔ outcome ↔ lesson linkage for the intelligence fabric.

Does not rewrite decisions. Lessons never become policy while
MEMORY_BEHAVIOR_INFLUENCE=0. Reuses LessonCandidate from memory_consolidator.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from scripts.lib.memory_consolidator import lesson_from_outcomes

AUTHORITY = "READ_ONLY_ADVISORY"
MBI = 0
OUTCOME_AXES = (
    "direction",
    "timing",
    "risk",
    "opportunity_cost",
    "thesis_quality",
    "evidence_quality",
    "notification_quality",
    "research_quality",
    "model_efficiency",
)
MIN_LESSON_SAMPLES = 5


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def link_research_decision(
    *,
    evidence_refs: list[str],
    curation_id: str | None,
    thesis_id: str | None,
    specialist_artifact_ids: list[str] | None = None,
    cio_recommendation: str | None = None,
    notification_id: str | None = None,
    decision_id: str,
) -> dict[str, Any]:
    return {
        "schema": "ResearchDecisionLink@v1",
        "decision_id": decision_id,
        "evidence_refs": list(evidence_refs),
        "curation_id": curation_id,
        "thesis_id": thesis_id,
        "specialist_artifact_ids": list(specialist_artifact_ids or []),
        "cio_recommendation": cio_recommendation,
        "notification_id": notification_id,
        "created_at": _now(),
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
    }


def record_outcome(
    *,
    decision_id: str,
    outcome_id: str,
    axes: dict[str, Any] | None = None,
    elapsed: bool = False,
) -> dict[str, Any]:
    if not elapsed:
        return {
            "schema": "DecisionOutcome@v1",
            "decision_id": decision_id,
            "status": "PENDING_ELAPSED_WINDOW",
            "history_rewritten": False,
            "authority": AUTHORITY,
            "memory_behavior_influence": MBI,
        }
    measured = {k: (axes or {}).get(k) for k in OUTCOME_AXES}
    return {
        "schema": "DecisionOutcome@v1",
        "decision_id": decision_id,
        "outcome_id": outcome_id,
        "axes": measured,
        "history_rewritten": False,
        "decision_mutated": False,
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
    }


def lesson_candidate(*, subject_guid: str, outcome_ids: list[str], statement: str) -> dict[str, Any]:
    row = lesson_from_outcomes(subject_guid=subject_guid, outcome_ids=outcome_ids, statement=statement)
    row["mature"] = len(outcome_ids) >= MIN_LESSON_SAMPLES
    row["methodology_effect"] = False
    row["policy_effect"] = False
    row["memory_behavior_influence"] = 0
    if not row["mature"]:
        row["note"] = "one trade is not methodology"
    return row


def specialist_disagreement_memory(artifacts: list[dict[str, Any]]) -> dict[str, Any]:
    recs = {str(a.get("agent")): a.get("recommendation") for a in artifacts if isinstance(a, dict)}
    disagreements = []
    agents = list(recs)
    for i, left in enumerate(agents):
        for right in agents[i + 1 :]:
            if recs.get(left) != recs.get(right):
                disagreements.append({"left": left, "right": right, "left_rec": recs.get(left), "right_rec": recs.get(right)})
    return {
        "schema": "SpecialistDisagreementMemory@v1",
        "artifact_refs": [a.get("schema") and a for a in artifacts],
        "disagreements": disagreements,
        "minority_overwritten": False,
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
    }


def memory_influence_firewall() -> dict[str, Any]:
    return {
        "MEMORY_BEHAVIOR_INFLUENCE": 0,
        "lessons_rewrite_policy": False,
        "lessons_rewrite_methodology": False,
        "model_policy_auto_changed": False,
        "authority": AUTHORITY,
    }
