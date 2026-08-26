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
from datetime import date, datetime, timezone
from typing import Any, Protocol, Sequence, runtime_checkable

from .enums import EvidenceGrade, EvidenceType, InfluenceClass, ResearchStatus
from .models import ResearchEvidence


def _parse_as_of(value: str):
    """Strictly parse an ``as_of`` cutoff. Returns date (or aware datetime).

    Raises ValueError on malformed / naive-datetime / mixed inputs.
    """
    if not isinstance(value, str) or not value.strip():
        raise ValueError("empty as_of")
    v = value.strip()
    # Date-only.
    if len(v) == 10 and v[4] == "-" and v[7] == "-" and v.replace("-", "").isdigit():
        return date.fromisoformat(v)
    dt = datetime.fromisoformat(v)
    if dt.tzinfo is None:
        raise ValueError("naive as_of datetime (timezone required)")
    return dt.astimezone(timezone.utc)


def _coerce_date(value: Any):
    """Coerce a source_date to a comparable date/datetime (raises if malformed).

    A naive datetime is rejected (fail-closed) — an unaware timestamp cannot be
    safely compared against an aware cutoff.
    """
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("naive datetime source_date (timezone required)")
        return value.astimezone(timezone.utc)
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return _parse_as_of(value)
    raise ValueError(f"not a date: {value!r}")


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
    as_of: str | None = None
    max_source_age_days: int | None = None

    def __post_init__(self) -> None:
        if isinstance(self.evidence_min_grade, str):
            self.evidence_min_grade = EvidenceGrade(self.evidence_min_grade)


@dataclass
class ContradictionResult:
    """Structured contradiction/support output for a fact.

    Carries full `ResearchEvidence` objects (never prose) so the CIO synthesis
    layer keeps provenance — fact_id, source_id, research_status, evidence_grade,
    and reproduction ids/digests — for every supporting/counterevidence/conflict
    entry.
    """

    fact_id: str
    supporting: list[ResearchEvidence] = field(default_factory=list)
    counterevidence: list[ResearchEvidence] = field(default_factory=list)
    unresolved_conflicts: list[ResearchEvidence] = field(default_factory=list)
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
    failure, but a query with no structured intent and no free text is invalid.

    Freshness contract (P1-4): ``as_of`` must parse (strict ISO-8601) and
    ``max_source_age_days`` must be a non-negative integer when present.
    """
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
    if query.as_of is not None:
        try:
            _parse_as_of(query.as_of)
        except ValueError as exc:
            problems.append(f"malformed as_of: {exc}")
    if query.max_source_age_days is not None:
        if not isinstance(query.max_source_age_days, int) or isinstance(query.max_source_age_days, bool):
            problems.append("max_source_age_days must be an integer")
        elif query.max_source_age_days < 0:
            problems.append("max_source_age_days must be >= 0")
    return problems


def validate_evidence_for_query(evidence: ResearchEvidence,
                                query: ResearchQuery) -> list[str]:
    """Enforce the retrieval freshness contract for one evidence object.

    Rules (fail-closed):
      * malformed ``as_of`` / negative max age => the query itself is invalid;
      * ``source_date`` after ``as_of`` => future evidence => FAIL;
      * ``source_date`` older than ``as_of - max_source_age`` => stale => FAIL;
      * max age required + missing ``source_date`` => FAIL.
    """
    problems: list[str] = []
    # Re-run query-level validation first (cutoff/age parse).
    problems.extend(validate_research_query(query))
    if query.as_of is None:
        return problems  # no cutoff => no freshness constraint in R1

    try:
        cutoff = _parse_as_of(query.as_of)
    except ValueError as exc:
        problems.append(f"malformed as_of: {exc}")
        return problems

    if evidence.source_date is None:
        if query.max_source_age_days is not None:
            problems.append("max_source_age_days required but evidence has no source_date")
        return problems

    try:
        src = _coerce_date(evidence.source_date)
    except ValueError as exc:
        problems.append(f"malformed source_date: {exc}")
        return problems

    # Mixed date/datetime precision is not safely comparable => controlled FAIL
    # (never an uncontrolled TypeError).
    if isinstance(cutoff, datetime) != isinstance(src, datetime):
        problems.append("source_date and as_of have mixed date/datetime precision")
        return problems

    if src > cutoff:
        problems.append(f"future evidence: source_date {evidence.source_date} > as_of {query.as_of}")
    if query.max_source_age_days is not None:
        age = (cutoff - src).days
        if age > query.max_source_age_days:
            problems.append(
                f"stale evidence: age {age}d > max_source_age_days {query.max_source_age_days}")
    return problems
