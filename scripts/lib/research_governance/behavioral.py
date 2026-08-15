"""R7 BEHAVIORAL_FRAMEWORK producer — citation-only catalog frames.

Public operator summaries of three institutional-canon books. No book full
text, no page numbers, no quoted paragraphs. Influence is CONTEXT_MODIFIER.
Never a standalone sell. Never creates TRIM. partisan_conclusion is always
null — this module does not invent political conclusions.

Authority: READ_ONLY_ADVISORY.
"""
from __future__ import annotations

from typing import Any

from .enums import EvidenceGrade, EvidenceType, InfluenceClass, ResearchStatus
from .models import ResearchEvidence

AUTHORITY = "READ_ONLY_ADVISORY"
MAX_INFLUENCE_PCT = 10.0

# Catalog source_ids only (see config/cio_research_source_catalog.json).
_HOUSEL = "housel_psychology_of_money"
_MARKS = "marks_most_important_thing"
_MALKIEL = "malkiel_random_walk"

FRAMES: dict[str, dict] = {
    _HOUSEL: {
        "source_id": _HOUSEL,
        "title": "The Psychology of Money",
        "summary": (
            "Public operator summary: this catalog source is commonly cited for "
            "the idea that long-run investor results depend more on behavior "
            "than on incremental information. Not a book extract."
        ),
        "citation_only": True,
        "fulltext": False,
    },
    _MARKS: {
        "source_id": _MARKS,
        "title": "The Most Important Thing",
        "summary": (
            "Public operator summary: this catalog source is commonly cited for "
            "second-level thinking and treating risk as more than a single "
            "volatility number. Not a book extract."
        ),
        "citation_only": True,
        "fulltext": False,
    },
    _MALKIEL: {
        "source_id": _MALKIEL,
        "title": "A Random Walk Down Wall Street",
        "summary": (
            "Public operator summary: this catalog source is commonly cited for "
            "the claim that most active stock-picking does not reliably beat a "
            "diversified market portfolio after costs. Not a book extract."
        ),
        "citation_only": True,
        "fulltext": False,
    },
}


def _source_claim(meta: dict) -> dict[str, Any]:
    return {
        "source_id": meta["source_id"],
        "title": meta["title"],
        "summary": meta["summary"],
        "citation_only": True,
        "fulltext": False,
        "claim_status": "SOURCE_CLAIM_INCOMPLETE",
        "page_or_section": None,
        "quoted_paragraph": None,
    }


def _frame_record(frame_id: str, meta: dict) -> dict[str, Any]:
    return {
        "id": frame_id,
        "source_id": meta["source_id"],
        "title": meta["title"],
        "summary": meta["summary"],
        "citation_only": True,
        "fulltext": False,
        "evidence_type": EvidenceType.BEHAVIORAL_FRAMEWORK.value,
        "research_status": ResearchStatus.SOURCE_CLAIM.value,
        "evidence_grade": EvidenceGrade.D.value,
        "influence_class": InfluenceClass.CONTEXT_MODIFIER.value,
        "partisan_conclusion": None,
        "standalone_sell": False,
        "creates_trim": False,
        "layers": {
            "source_claim": _source_claim(meta),
        },
    }


def bundle() -> dict:
    """Citation-only behavioral pack. Context modifier, never a trade."""
    frames = {fid: _frame_record(fid, meta) for fid, meta in FRAMES.items()}
    return {
        "authority": AUTHORITY,
        "partisan_conclusion": None,
        "standalone_sell": False,
        "creates_trim": False,
        "influence": InfluenceClass.CONTEXT_MODIFIER.value,
        "influence_class": InfluenceClass.CONTEXT_MODIFIER.value,
        "max_influence_pct": MAX_INFLUENCE_PCT,
        "fulltext": False,
        "citation_only": True,
        "evidence_type": EvidenceType.BEHAVIORAL_FRAMEWORK.value,
        "evidence_grade": EvidenceGrade.D.value,
        "research_status": ResearchStatus.SOURCE_CLAIM.value,
        "frames": frames,
    }


def as_research_evidence(frame_id: str) -> ResearchEvidence:
    """Grade D / SOURCE_CLAIM — no lawful full text, so no reproduction."""
    if frame_id not in FRAMES:
        raise KeyError(f"unknown behavioral frame: {frame_id}")
    meta = FRAMES[frame_id]
    return ResearchEvidence(
        fact_id=f"behavioral:{frame_id}",
        fact=meta["summary"],
        source_id=meta["source_id"],
        evidence_type=EvidenceType.BEHAVIORAL_FRAMEWORK,
        research_status=ResearchStatus.SOURCE_CLAIM,
        evidence_grade=EvidenceGrade.D,
        influence_class=InfluenceClass.CONTEXT_MODIFIER,
        current_applicability="context_only",
        caveat="Citation-only public operator summary. Not a book extract. No full text.",
        role_in_decision="risk_modifier_or_context",
    )
