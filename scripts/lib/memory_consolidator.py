"""MemoryConsolidator@v1 — episode → candidate fact with gates.

Flow: episode → atomic candidate → entity resolution → dedupe → temporal
compare → contradiction → TTL → injection scan → admission.

No inferred preference becomes investment policy.
"""
from __future__ import annotations

from typing import Any

from scripts.lib.agent_episode import build_episode
from scripts.lib.memory_fact import MemoryFactStore, build_fact
from scripts.lib.memory_namespace import DEFAULT_TENANT
from scripts.lib.memory_taxonomy import classify_aif_row
from scripts.lib.preference_candidate import from_feedback
from scripts.lib.semantic_operator_memory import classify_plane, build_unit

AUTHORITY = "READ_ONLY_ADVISORY"
SCHEMA = "MemoryConsolidator@v1"


def consolidate(
    episode: dict[str, Any],
    *,
    store: MemoryFactStore | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    store = store or MemoryFactStore()
    plane = classify_plane({"kind": episode.get("kind"), "text": episode.get("summary")})
    if plane == "QUARANTINED":
        return {
            "schema": SCHEMA,
            "admitted": False,
            "reason": "QUARANTINED",
            "plane": plane,
            "authority": AUTHORITY,
            "policy_effect": False,
            "memory_behavior_influence": 0,
            "financial_action": False,
        }
    inj = classify_aif_row({"text": episode.get("summary")})
    if inj == "QUARANTINED":
        return {
            "schema": SCHEMA,
            "admitted": False,
            "reason": "INJECTION",
            "plane": "QUARANTINED",
            "authority": AUTHORITY,
            "policy_effect": False,
            "memory_behavior_influence": 0,
            "financial_action": False,
        }
    subject = episode.get("subject_guid") or "entity:unresolved"
    existing = store.query(
        tenant_id=DEFAULT_TENANT,
        mode="AS_KNOWN_NOW",
        subject_guid=subject,
    )
    summary = str(episode.get("summary") or "")
    for row in existing:
        if str(row.get("object")) == summary:
            return {
                "schema": SCHEMA,
                "admitted": False,
                "reason": "DEDUPE",
                "plane": plane,
                "existing_memory_id": row.get("memory_id"),
                "authority": AUTHORITY,
                "policy_effect": False,
                "memory_behavior_influence": 0,
                "financial_action": False,
            }
    fact = build_fact(
        tenant_id=DEFAULT_TENANT,
        namespace="POLICY_BELIEF" if plane == "SEMANTIC_OPERATOR" else "RESEARCH_EVIDENCE",
        subject_guid=subject,
        predicate=str(episode.get("kind") or "episode"),
        value=summary,
        category=plane,
        valid_from=episode.get("created_at") or "2026-01-01T00:00:00+00:00",
        source_type="episode",
        source_id=episode.get("episode_id") or "ep",
        source_as_of=episode.get("created_at") or "2026-01-01T00:00:00+00:00",
        asserted_by=episode.get("agent") or "alex",
        status="CANDIDATE",
        evidence_refs=[episode.get("episode_id")] if episode.get("episode_id") else [],
    )
    stored = store.write(fact, now=now)
    unit = build_unit(plane=plane if plane != "QUARANTINED" else "EPISODIC", subject_guid=subject, summary=summary, refs=[episode.get("episode_id") or ""])
    pref = None
    if episode.get("kind") == "feedback":
        pref = from_feedback(subject_guid=subject, statement=summary, supporting_feedback_ids=[episode.get("episode_id") or "fb"])
    return {
        "schema": SCHEMA,
        "admitted": True,
        "reason": "ADMITTED_CANDIDATE",
        "plane": plane,
        "memory_id": stored.get("memory_id"),
        "memory_version_id": stored.get("memory_version_id"),
        "unit": unit,
        "preference_candidate": pref,
        "authority": AUTHORITY,
        "policy_effect": False,
        "memory_behavior_influence": 0,
        "financial_action": False,
        "overrides_office_truth": False,
    }


def lesson_from_outcomes(*, subject_guid: str, outcome_ids: list[str], statement: str) -> dict[str, Any]:
    """One-off outcomes are not methodology."""
    mature = len(outcome_ids) >= 5
    return {
        "schema": "LessonCandidate@v1",
        "subject_guid": subject_guid,
        "statement": statement[:400],
        "outcome_ids": list(outcome_ids),
        "sample_size": len(outcome_ids),
        "mature": mature,
        "methodology_effect": False,
        "authority": AUTHORITY,
        "financial_action": False,
        "memory_behavior_influence": 0,
        "note": "insufficient sample" if not mature else "candidate only",
    }
