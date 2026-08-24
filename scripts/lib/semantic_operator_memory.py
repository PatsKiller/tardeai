"""SemanticOperatorMemory@v1 — not a second document corpus.

Planes stay separated. Research prose belongs in RAG/evidence.
"""
from __future__ import annotations

from typing import Any

AUTHORITY = "READ_ONLY_ADVISORY"
SCHEMA = "SemanticOperatorMemory@v1"
PLANES = (
    "RESEARCH_POINTER",
    "EPISODIC",
    "SEMANTIC_OPERATOR",
    "POLICY_POINTER",
    "LESSON_POINTER",
    "QUARANTINED",
)


def classify_plane(row: dict[str, Any]) -> str:
    text = str(row.get("text") or row.get("summary") or "").lower()
    if "ignore previous" in text or "place order" in text:
        return "QUARANTINED"
    kind = str(row.get("kind") or row.get("plane") or "").upper()
    if kind in PLANES:
        return kind
    if kind in {"RESEARCH", "RESEARCH_REFERENCE", "EVIDENCE"}:
        return "RESEARCH_POINTER"
    if kind in {"EPISODE", "EPISODIC"}:
        return "EPISODIC"
    if kind in {"LESSON", "OUTCOME"}:
        return "LESSON_POINTER"
    if kind in {"POLICY", "OPERATOR_POLICY"}:
        return "POLICY_POINTER"
    return "SEMANTIC_OPERATOR"


def build_unit(*, plane: str, subject_guid: str | None, summary: str, refs: list[str] | None = None) -> dict[str, Any]:
    if plane not in PLANES:
        raise RuntimeError("UNKNOWN_MEMORY_PLANE")
    if plane == "QUARANTINED":
        raise RuntimeError("QUARANTINED_NOT_ADMITTED")
    return {
        "schema": SCHEMA,
        "plane": plane,
        "subject_guid": subject_guid,
        "summary": summary[:400],
        "refs": list(refs or []),
        "authority": AUTHORITY,
        "financial_action": False,
        "overrides_office_truth": False,
        "policy_effect": False,
    }
