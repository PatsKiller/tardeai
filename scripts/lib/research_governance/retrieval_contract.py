"""Research governance — retrieval contract (PR-R1, adapter-first).

The retrieval layer is defined by an interface, not by wiring any of the three
existing production engines (rag_retrieval, advisory/kb_lessons, hermes backend).
Those are off-limits until R4. This module declares:

  - `ResearchRetriever` Protocol: what any adapter must implement.
  - `validate_retrieval_result`: structural contract check (fail-closed).

A caller that consumes research evidence only ever sees normalized
`ResearchEvidence` objects; adapters are responsible for mapping their native
records into that shape.
"""
from __future__ import annotations

from typing import Any, Protocol, Sequence, runtime_checkable

from .enums import EvidenceGrade, EvidenceType, InfluenceClass, ResearchStatus
from .models import ResearchEvidence


@runtime_checkable
class ResearchRetriever(Protocol):
    """Minimal retrieval surface every adapter must satisfy."""

    def retrieve(self, query: str, *, limit: int = 20) -> Sequence[ResearchEvidence]:
        """Return normalized evidence for a query, best-first."""

    def retrieve_by_source(self, source_id: str, *, limit: int = 20) -> Sequence[ResearchEvidence]:
        """Return evidence attributable to a source."""

    def search_contradictions(self, fact_id: str, *, limit: int = 20) -> Sequence[ResearchEvidence]:
        """Return evidence that contradicts the given fact."""


_REQUIRED_STR_FIELDS = ("fact_id", "fact", "source_id")
_ENUM_FIELDS = {
    "evidence_type": EvidenceType,
    "research_status": ResearchStatus,
    "evidence_grade": EvidenceGrade,
    "influence_class": InfluenceClass,
}


def validate_retrieval_result(evidence: ResearchEvidence) -> list[str]:
    """Fail-closed structural validation. Returns a list of problems ([] = OK)."""
    problems: list[str] = []
    for field in _REQUIRED_STR_FIELDS:
        val = getattr(evidence, field, None)
        if not isinstance(val, str) or not val.strip():
            problems.append(f"missing/invalid required field: {field}")
    for field, enum_cls in _ENUM_FIELDS.items():
        val = getattr(evidence, field, None)
        if not isinstance(val, enum_cls):
            problems.append(f"missing/invalid enum field: {field}")
    if problems:
        return problems

    # Grade/status coherence: a D-grade source claim cannot masquerade as OOS.
    if (evidence.research_status == ResearchStatus.OOS_SUPPORTED
            and evidence.evidence_grade not in {EvidenceGrade.A, EvidenceGrade.B}):
        problems.append("OOS_SUPPORTED requires evidence grade A or B")
    if (evidence.research_status in {ResearchStatus.IN_SAMPLE_REPRODUCED, ResearchStatus.OOS_SUPPORTED}
            and not evidence.reproduction_ids):
        problems.append("reproduced status requires reproduction_ids")
    return problems
