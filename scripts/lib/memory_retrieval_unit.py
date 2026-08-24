"""MemoryRetrievalUnit@v1 — bounded ASKU-equivalent for ContextEnvelope."""
from __future__ import annotations

from typing import Any

AUTHORITY = "READ_ONLY_ADVISORY"
SCHEMA = "MemoryRetrievalUnit@v1"
MODES = (
    "CURRENT",
    "HISTORICAL",
    "WHAT_CHANGED",
    "COUNTEREVIDENCE",
    "OPERATOR_MEMORY",
    "RESEARCH_EVIDENCE",
)


def from_fact(fact: dict[str, Any], *, mode: str, why_selected: str, scores: dict[str, float] | None = None) -> dict[str, Any]:
    if mode not in MODES:
        raise RuntimeError("UNKNOWN_RETRIEVAL_MODE")
    scores = scores or {}
    summary = fact.get("object")
    if not isinstance(summary, str):
        summary = str(summary)[:240]
    return {
        "schema": SCHEMA,
        "memory_id": fact.get("memory_id"),
        "memory_version_id": fact.get("memory_version_id"),
        "subject_guid": fact.get("subject_guid"),
        "namespace": fact.get("namespace"),
        "content_summary": summary[:500],
        "valid_from": fact.get("valid_from"),
        "valid_to": fact.get("valid_to"),
        "tx_from": fact.get("tx_from"),
        "tx_to": fact.get("tx_to"),
        "source_refs": [fact.get("source_id")],
        "evidence_refs": list(fact.get("evidence_refs") or []),
        "contradiction_refs": list(fact.get("contradiction_refs") or []),
        "authority": AUTHORITY,
        "confidence": fact.get("confidence"),
        "retrieval_score": float(scores.get("retrieval") or 0),
        "semantic_score": float(scores.get("semantic") or 0),
        "temporal_score": float(scores.get("temporal") or 0),
        "source_score": float(scores.get("source") or 0),
        "why_selected": why_selected,
        "token_estimate": max(1, len(summary) // 4),
        "mode": mode,
        "overrides_office_truth": False,
        "financial_action": False,
    }
