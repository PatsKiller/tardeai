"""In-memory ResearchRetriever — dry R4 adapter. No production engines."""
from __future__ import annotations

from typing import Iterable, Sequence

from .enums import EvidenceGrade
from .models import ResearchEvidence
from .retrieval_contract import ContradictionResult, ResearchQuery, ResearchRetriever, validate_retrieval_result


class InMemoryRetriever:
    """Stores normalized ResearchEvidence. Implements the R1 protocol."""

    def __init__(self, evidence: Iterable[ResearchEvidence] | None = None) -> None:
        self._items: list[ResearchEvidence] = []
        for e in evidence or []:
            problems = validate_retrieval_result(e)
            if problems:
                raise ValueError(f"invalid evidence {e.fact_id}: {problems}")
            self._items.append(e)

    def add(self, evidence: ResearchEvidence) -> None:
        problems = validate_retrieval_result(evidence)
        if problems:
            raise ValueError(f"invalid evidence {evidence.fact_id}: {problems}")
        self._items.append(evidence)

    def retrieve(self, query: ResearchQuery) -> Sequence[ResearchEvidence]:
        out: list[ResearchEvidence] = []
        min_g = query.evidence_min_grade
        order = {EvidenceGrade.A: 0, EvidenceGrade.B: 1, EvidenceGrade.C: 2, EvidenceGrade.D: 3, EvidenceGrade.X: 9}
        for e in self._items:
            if order.get(e.evidence_grade, 9) > order.get(min_g, 3):
                continue
            if query.calendar_context and e.evidence_type.value != "SEASONALITY":
                if query.calendar_context.lower() not in (e.fact or "").lower():
                    continue
            if query.free_text:
                blob = f"{e.fact} {e.source_id} {e.fact_id}".lower()
                if query.free_text.lower() not in blob:
                    continue
            out.append(e)
        out.sort(key=lambda e: order.get(e.evidence_grade, 9))
        return out[: max(1, int(query.max_facts))]

    def retrieve_by_source(self, source_id: str, *, limit: int = 20) -> Sequence[ResearchEvidence]:
        hits = [e for e in self._items if e.source_id == source_id]
        return hits[:limit]

    def search_contradictions(self, fact_id: str, *, limit: int = 20) -> ContradictionResult:
        target = next((e for e in self._items if e.fact_id == fact_id), None)
        if target is None:
            return ContradictionResult(fact_id=fact_id)
        supporting, counter, conflict = [], [], []
        for e in self._items:
            if e.fact_id == fact_id:
                continue
            if fact_id in (e.contradicts_refs or []) or e.fact_id in (target.contradicts_refs or []):
                conflict.append(e)
            elif e.evidence_grade == EvidenceGrade.X:
                counter.append(e)
            elif e.source_id == target.source_id:
                supporting.append(e)
        return ContradictionResult(
            fact_id=fact_id,
            supporting=supporting[:limit],
            counterevidence=counter[:limit],
            unresolved_conflicts=conflict[:limit],
        )


def _assert_protocol(obj: InMemoryRetriever) -> None:
    assert isinstance(obj, ResearchRetriever)
