"""R4 adapter: map existing CIO research-brain facts → ResearchEvidence.

Does not modify cio_research_retriever. Dry-callable. Opt-in audit wrapper
records decision use without changing production default behavior.
"""
from __future__ import annotations

from typing import Any, Optional

from .almanac import as_research_evidence, bundle as almanac_bundle
from .decision_use_audit import LEDGER, DecisionUseLedger, DecisionUseRecord
from .enums import EvidenceGrade, EvidenceType, InfluenceClass, ResearchStatus
from .models import ResearchEvidence
from .retrieval_contract import ResearchQuery


AUTHORITY = "READ_ONLY_ADVISORY"


def _grade(raw: Any) -> EvidenceGrade:
    try:
        return EvidenceGrade(str(raw))
    except Exception:
        return EvidenceGrade.D


def cio_fact_to_evidence(fact: dict[str, Any]) -> ResearchEvidence:
    grade = _grade(fact.get("evidence_grade") or fact.get("grade") or "D")
    status = ResearchStatus.SOURCE_CLAIM
    if grade in {EvidenceGrade.A, EvidenceGrade.B, EvidenceGrade.C}:
        status = ResearchStatus.IN_SAMPLE_REPRODUCED
    return ResearchEvidence(
        fact_id=str(fact.get("source_id") or fact.get("fact_id") or fact.get("title") or "cio-fact"),
        fact=str(fact.get("title") or fact.get("fact") or fact.get("note") or ""),
        source_id=str(fact.get("source_id") or "cio_research_library"),
        source_date=str((fact.get("citation") or {}).get("date") or "") or None,
        evidence_type=EvidenceType.SEASONALITY if fact.get("family") == "seasonality" else EvidenceType.SOURCE_NARRATIVE,
        research_status=status,
        evidence_grade=grade,
        influence_class=InfluenceClass.CONTEXT_MODIFIER,
        reproduction_ids=["cio-brain"] if grade != EvidenceGrade.D else [],
        sample_n=fact.get("n"),
        current_applicability=str(fact.get("current_applicability") or "") or None,
        role_in_decision="risk_modifier_or_context",
        caveat="Adapted from CIO research-brain compact fact. Context only.",
    )


def retrieve_for_decision(
    *,
    decision_id: str,
    query: Optional[ResearchQuery] = None,
    as_of_year: int = 2026,
    ledger: Optional[DecisionUseLedger] = None,
) -> tuple[list[ResearchEvidence], DecisionUseRecord]:
    """Dry R4 retrieve-before-synthesis with mandatory audit.

    Uses the R3 Almanac bundle (fixture). Optionally merges CIO compact facts
    if that module imports cleanly — failure is fail-soft (Almanac still returns).
    """
    q = query or ResearchQuery(calendar_context="seasonality", max_facts=12)
    evidence: list[ResearchEvidence] = []
    pack = almanac_bundle(as_of_year=as_of_year)
    for sl in pack["slices"].values():
        ev = as_research_evidence(sl)
        if ev.evidence_grade != EvidenceGrade.X:
            evidence.append(ev)
    try:
        from scripts.lib.cio_research_retriever import retrieve_research_context
        from datetime import datetime, timezone
        raw = retrieve_research_context(datetime.now(timezone.utc), symbols=[])
        for f in (raw.get("relevant_facts") or raw.get("facts") or raw.get("items") or []):
            if isinstance(f, dict):
                evidence.append(cio_fact_to_evidence(f))
    except Exception:
        pass
    book = ledger or LEDGER
    rec = book.record(
        decision_id=decision_id,
        query={
            "calendar_context": q.calendar_context,
            "max_facts": q.max_facts,
            "as_of_year": as_of_year,
        },
        evidence=evidence[: q.max_facts],
        influence_cap_pct=float(pack["max_influence_pct"]),
    )
    return evidence[: q.max_facts], rec
