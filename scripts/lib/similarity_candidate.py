"""SimilarityCandidate@v1 — ANN may hypothesize; it may not ratify edges."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

AUTHORITY = "READ_ONLY_ADVISORY"
SCHEMA = "SimilarityCandidate@v1"
STATUSES = ("CANDIDATE", "SUPPORTED", "DISPUTED", "REJECTED", "RATIFIED", "EXPIRED")


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def from_similarity(
    *,
    source_entity_guid: str,
    target_entity_guid: str,
    relationship_hypothesis: str,
    similarity: float,
    embedding_model: str,
    embedding_version: str,
    evidence_refs: list[str] | None = None,
) -> dict[str, Any]:
    """High cosine is a candidate, never RELATED_TO."""
    return {
        "schema": SCHEMA,
        "candidate_relationship_id": str(uuid.uuid4()),
        "source_entity_guid": source_entity_guid,
        "target_entity_guid": target_entity_guid,
        "relationship_hypothesis": relationship_hypothesis,
        "similarity": float(similarity),
        "embedding_model": embedding_model,
        "embedding_version": embedding_version,
        "generated_at": _now(),
        "evidence_refs": list(evidence_refs or []),
        "status": "CANDIDATE",
        "confidence": "low",
        "source": "ANN_SIMILARITY",
        "authoritative": False,
        "authority": AUTHORITY,
        "financial_action": False,
    }


def promote(candidate: dict[str, Any], *, mechanism: str, actor: str) -> dict[str, Any]:
    """Only deterministic mapping or Librarian/curator ratification."""
    allowed = {"DETERMINISTIC_SOURCE_MAPPING", "LIBRARIAN_RATIFICATION", "CURATOR_RATIFICATION"}
    if mechanism not in allowed:
        raise RuntimeError("SIMILARITY_CANNOT_SELF_RATIFY")
    if candidate.get("status") != "CANDIDATE" and candidate.get("status") != "SUPPORTED":
        raise RuntimeError("CANDIDATE_NOT_PROMOTABLE")
    out = dict(candidate)
    out["status"] = "RATIFIED"
    out["authoritative"] = True
    out["promoted_by"] = actor
    out["promotion_mechanism"] = mechanism
    out["promoted_at"] = _now()
    return out
