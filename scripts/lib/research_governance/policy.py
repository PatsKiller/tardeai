"""R7 POLICY_OR_REGULATORY producer.

Type-specific evidence for promotion-gate policy contracts that already exist
on the R1 ladder. Freshness is *computed* from dates (same function the gate
uses) — never a caller boolean.

Authority: READ_ONLY_ADVISORY. Policy informs; it does not trade.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from .enums import EvidenceGrade, EvidenceType, GateState, InfluenceClass, ResearchStatus
from .models import ResearchEvidence
from .promotion_gate import _policy_freshness

AUTHORITY = "READ_ONLY_ADVISORY"

# Type-specific keys `promotion_gate._type_specific_gates` records for POLICY.
POLICY_TYPE_GATE_KEYS: tuple[str, ...] = (
    "authoritative_source",
    "effective_date",
    "jurisdiction",
    "freshness",
)

_REQUIRED_IDENTITY = ("jurisdiction", "effective_date", "authoritative_source")


@dataclass(frozen=True)
class PolicyRule:
    rule_id: str
    fact: str
    source_id: str
    authoritative_source: str
    jurisdiction: str
    effective_date: str  # YYYY-MM-DD
    verified_at: str
    current_as_of: str
    next_reverify_at: Optional[str] = None
    future_effective: bool = False
    citation_url: Optional[str] = None
    citation_title: Optional[str] = None


def _present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str) and not value.strip():
        return False
    return True


def promotion_ctx(rule: PolicyRule) -> dict:
    """Dict keys the policy type-specific promotion gates expect, plus the
    shared fields `run_promotion_gate` needs so those gates actually execute.

    Influence is CONTEXT_MODIFIER: policy informs, it does not trade.
    """
    def _strip(value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

    jurisdiction = _strip(rule.jurisdiction) if rule.jurisdiction is not None else ""
    return {
        "authoritative_source": _strip(rule.authoritative_source),
        "effective_date": _strip(rule.effective_date),
        "jurisdiction": jurisdiction,
        "verified_at": rule.verified_at,
        "current_as_of": rule.current_as_of,
        "next_reverify_at": rule.next_reverify_at,
        "future_effective": rule.future_effective,
        "source_id": rule.source_id,
        "claim": rule.fact,
        "page_or_section": rule.citation_title or rule.rule_id,
        "scope": jurisdiction or "unspecified",
        "evidence_type": EvidenceType.POLICY_OR_REGULATORY.value,
        "evidence_grade": EvidenceGrade.C.value,
        "influence_class": InfluenceClass.CONTEXT_MODIFIER.value,
        "citation_url": rule.citation_url,
        "citation_title": rule.citation_title,
        "authority": AUTHORITY,
        "claims_trade_authority": False,
    }


def evaluate_policy(rule: PolicyRule) -> dict:
    """Compute freshness the same way `promotion_gate._policy_freshness` does.

    Returns ``{status: OK|UNAVAILABLE, reason, ctx}``. Missing identity fields,
    a future effective date without ``future_effective=True``, or a stale
    reverify window are UNAVAILABLE — never a guessed OK.
    """
    ctx = promotion_ctx(rule)
    missing = [name for name in _REQUIRED_IDENTITY if not _present(getattr(rule, name, None))]
    if missing:
        return {
            "status": "UNAVAILABLE",
            "reason": f"missing {', '.join(missing)}",
            "ctx": ctx,
        }
    state, reason = _policy_freshness(ctx)
    if state is GateState.PASS:
        return {"status": "OK", "reason": reason, "ctx": ctx}
    return {"status": "UNAVAILABLE", "reason": reason, "ctx": ctx}


def as_research_evidence(rule: PolicyRule, evaluation: dict) -> ResearchEvidence:
    """Policy informs a decision; it never becomes a standalone trade."""
    ok = isinstance(evaluation, dict) and evaluation.get("status") == "OK"
    return ResearchEvidence(
        fact_id=rule.rule_id,
        fact=rule.fact,
        source_id=rule.source_id,
        source_date=rule.effective_date,
        evidence_type=EvidenceType.POLICY_OR_REGULATORY,
        research_status=ResearchStatus.SOURCE_CLAIM,
        evidence_grade=EvidenceGrade.C if ok else EvidenceGrade.D,
        influence_class=InfluenceClass.CONTEXT_MODIFIER,
        current_applicability="ok" if ok else "unavailable",
        caveat=None if not isinstance(evaluation, dict) else evaluation.get("reason"),
        role_in_decision="risk_modifier_or_context",
        valid_from=rule.effective_date,
    )
