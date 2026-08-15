"""R4 live degradation / retirement of research facts.

Dry-testable, in-process. A fact is degraded when:
  * evidence_grade is X
  * research_status is FAILED_REPRODUCTION / INVALIDATED / RETIRED
  * source/as-of is older than max_age_days
  * OOS window was consumed and the fact still claims OOS_SUPPORTED without a new segment

READ_ONLY_ADVISORY.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Optional

from .enums import EvidenceGrade, ResearchStatus
from .models import ResearchEvidence

AUTHORITY = "READ_ONLY_ADVISORY"


def _as_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    v = str(value).strip()
    if len(v) >= 10 and v[4] == "-" and v[7] == "-":
        return date.fromisoformat(v[:10])
    return None


@dataclass(frozen=True)
class DegradationDecision:
    fact_id: str
    action: str  # keep | degrade | retire
    reason: str
    authority: str = AUTHORITY


def evaluate_fact(
    evidence: ResearchEvidence,
    *,
    as_of: Optional[str] = None,
    max_age_days: Optional[int] = 3650,
    oos_consumed: bool = False,
) -> DegradationDecision:
    fid = evidence.fact_id
    if evidence.evidence_grade == EvidenceGrade.X:
        return DegradationDecision(fid, "retire", "grade X invalidated")
    if evidence.research_status in {
        ResearchStatus.FAILED_REPRODUCTION,
        ResearchStatus.INVALIDATED,
        ResearchStatus.RETIRED,
    }:
        return DegradationDecision(fid, "retire", f"status {evidence.research_status.value}")
    if evidence.valid_to:
        end = _as_date(evidence.valid_to)
        now = _as_date(as_of) or datetime.now(timezone.utc).date()
        if end and now > end:
            return DegradationDecision(fid, "retire", "valid_to elapsed")
    if max_age_days is not None and evidence.source_date:
        src = _as_date(evidence.source_date)
        now = _as_date(as_of) or datetime.now(timezone.utc).date()
        if src and (now - src).days > int(max_age_days):
            return DegradationDecision(fid, "degrade", f"source older than {max_age_days} days")
    if oos_consumed and evidence.research_status == ResearchStatus.OOS_SUPPORTED:
        return DegradationDecision(fid, "degrade", "OOS segment consumed; cannot remain untouched OOS")
    return DegradationDecision(fid, "keep", "no degradation trigger")


def apply_degradation(evidence: ResearchEvidence, decision: DegradationDecision) -> ResearchEvidence:
    if decision.action == "keep":
        return evidence
    if decision.action == "retire":
        evidence.research_status = ResearchStatus.RETIRED
        evidence.evidence_grade = EvidenceGrade.X
        evidence.current_applicability = f"RETIRED: {decision.reason}"
        return evidence
    # degrade: cap at D / SOURCE_CLAIM unless already worse
    if evidence.evidence_grade in {EvidenceGrade.A, EvidenceGrade.B, EvidenceGrade.C}:
        evidence.evidence_grade = EvidenceGrade.D
    if evidence.research_status == ResearchStatus.OOS_SUPPORTED:
        evidence.research_status = ResearchStatus.SOURCE_CLAIM
    evidence.caveat = (evidence.caveat or "") + f" [DEGRADED: {decision.reason}]"
    return evidence
