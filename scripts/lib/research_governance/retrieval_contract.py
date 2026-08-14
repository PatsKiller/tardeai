"""Research governance — retrieval contract (PR-R1, adapter-first).

The retrieval layer is defined by an interface, not by wiring any of the three
existing production engines (rag_retrieval, advisory/kb_lessons, hermes backend).
Those are off-limits until R4. This module declares:

  - `ResearchQuery`: the STRUCTURED query intent (not a free-text string).
  - `ResearchRetriever` Protocol: what any adapter must implement.
  - `validate_retrieval_result`: structural contract check (fail-closed).
  - `ContradictionResult`: structured supporting/counterevidence/conflict output.

A caller that consumes research evidence only ever sees normalized
`ResearchEvidence` objects; adapters are responsible for mapping their native
records into that shape.

R1 is adapter-CONTRACT only; do not wire production retrieval yet.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, Sequence, runtime_checkable

from .enums import EvidenceGrade, EvidenceType, InfluenceClass, ResearchStatus
from .models import ResearchEvidence


@dataclass
class ResearchQuery:
    """Structured retrieval intent. Text search is a convenience, not the contract."""

    asset_class: str | None = None
    symbols: list[str] = field(default_factory=list)
    decision_type: str | None = None
    portfolio_role: str | None = None
    horizon: str | None = None
    account_type: str | None = None
    regime: str | None = None
    calendar_context: str | None = None
    risk_issue: str | None = None
    valuation_issue: str | None = None
    instrument_type: str | None = None
    evidence_min_grade: EvidenceGrade = EvidenceGrade.D
    max_facts: int = 20
    free_text: str | None = None

    def __post_init__(self) -> None:
        if isinstance(self.evidence_min_grade, str):
            self.evidence_min_grade = EvidenceGrade(self.evidence_min_grade)


@dataclass
class ContradictionResult:
    """Structured contradiction/support output for a fact."""

    fact_id: str
    supporting: list[str] = field(default_factory=list)
    counterevidence: list[str] = field(default_factory=list)
    unresolved_conflicts: list[str] = field(default_factory=list)
    synthesis_constraints: list[str] = field(default_factory=list)


@runtime_checkable
class ResearchRetriever(Protocol):
    """Minimal retrieval surface every adapter must satisfy."""

    def retrieve(self, query: ResearchQuery) -> Sequence[ResearchEvidence]:
        """Return normalized evidence for a structured query, best-first."""

    def retrieve_by_source(self, source_id: str, *, limit: int = 20) -> Sequence[ResearchEvidence]:
        """Return evidence attributable to a source."""

    def search_contradictions(self, fact_id: str, *, limit: int = 20) -> ContradictionResult:
        """Return supporting/counterevidence/conflicts for a fact."""


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


def validate_research_query(query: ResearchQuery) -> list[str]:
    """Validate a structured query. Free-text-only queries are a warning, not a
    failure, but a query with no structured intent and no free text is invalid."""
    problems: list[str] = []
    structured = any([
        query.asset_class, query.symbols, query.decision_type, query.portfolio_role,
        query.horizon, query.account_type, query.regime, query.calendar_context,
        query.risk_issue, query.valuation_issue, query.instrument_type,
    ])
    if not structured and not query.free_text:
        problems.append("query must specify structured intent or free_text")
    if query.max_facts <= 0:
        problems.append("max_facts must be positive")
    return problems
