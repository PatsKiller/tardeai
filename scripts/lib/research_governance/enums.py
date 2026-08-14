"""Research governance — canonical enums (PR-R1, additive-only).

Three orthogonal dimensions describe a research fact; they must never be
collapsed into a single field:

  evidence_type   — WHAT kind of knowledge this is.
  research_status — WHERE it sits in the lifecycle (provenance → reproduction → OOS).
  evidence_grade  — HOW strong the evidence is for its declared scope (A/B/C/D/X).

Authority: READ_ONLY_ADVISORY. None of these enums confers trade authority.
"""
from __future__ import annotations

from enum import Enum


class EvidenceType(str, Enum):
    """The kind of knowledge a fact represents."""
    SOURCE_NARRATIVE = "SOURCE_NARRATIVE"
    DETERMINISTIC_MECHANICS = "DETERMINISTIC_MECHANICS"
    EMPIRICAL_STRATEGY = "EMPIRICAL_STRATEGY"
    EMPIRICAL_FACTOR = "EMPIRICAL_FACTOR"
    SEASONALITY = "SEASONALITY"
    VALUATION_MODEL = "VALUATION_MODEL"
    POLICY_OR_REGULATORY = "POLICY_OR_REGULATORY"
    BEHAVIORAL_FRAMEWORK = "BEHAVIORAL_FRAMEWORK"


class ResearchStatus(str, Enum):
    """Lifecycle position. `reproduced_oos` is a status, NOT a grade."""
    SOURCE_CLAIM_INCOMPLETE = "SOURCE_CLAIM_INCOMPLETE"
    SOURCE_CLAIM = "SOURCE_CLAIM"
    HYPOTHESIS_REGISTERED = "HYPOTHESIS_REGISTERED"
    IN_SAMPLE_REPRODUCED = "IN_SAMPLE_REPRODUCED"
    OOS_SUPPORTED = "OOS_SUPPORTED"
    ROBUSTNESS_SUPPORTED = "ROBUSTNESS_SUPPORTED"
    FAILED_REPRODUCTION = "FAILED_REPRODUCTION"
    INVALIDATED = "INVALIDATED"
    RETIRED = "RETIRED"


class EvidenceGrade(str, Enum):
    """Type-aware quality grade. See grade rules in acceptance.py."""
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    X = "X"


class GateState(str, Enum):
    """Promotion-gate and acceptance-gate verdicts.

    `NOT_APPLICABLE` is a promotion-gate verdict (a gate not required for this
    evidence type, with a reason). `NOT_IN_SCOPE` is an acceptance-gate verdict
    (a subsystem gate that belongs to a later phase). Neither is a PASS.
    """
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_IN_SCOPE = "NOT_IN_SCOPE"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    BLOCKED = "BLOCKED"


class InfluenceClass(str, Enum):
    """What authority a verified fact is permitted to have over a decision."""
    HARD_RESEARCH_GOVERNANCE = "HARD_RESEARCH_GOVERNANCE"
    DETERMINISTIC_MECHANICS = "DETERMINISTIC_MECHANICS"
    RISK_VETO = "RISK_VETO"
    VALUATION_INPUT = "VALUATION_INPUT"
    PORTFOLIO_CONSTRUCTION = "PORTFOLIO_CONSTRUCTION"
    CONTEXT_MODIFIER = "CONTEXT_MODIFIER"


class TrialTerminalStatus(str, Enum):
    """Terminal disposition of a trial record (required for completeness)."""
    COMPLETED = "COMPLETED"
    INVALID = "INVALID"
    CANCELED_WITH_REASON = "CANCELED_WITH_REASON"
    FAILED = "FAILED"


TERMINAL_STATUSES = frozenset(s.value for s in TrialTerminalStatus)


# A linear promotion ladder for a single hypothesis/fact (RG-0..RG-11 use these
# as the "current position" a fact holds). Ordering is meaningful: a fact may
# only move forward, never silently leap backward without an invalidation event.
PROMOTION_STATES: tuple[str, ...] = (
    "SOURCE_ONLY",
    "EXPLORATORY_ONLY",
    "ELIGIBLE_FOR_REPRODUCTION",
    "REPRODUCED_IN_SAMPLE",
    "ELIGIBLE_FOR_OOS",
    "OOS_SUPPORTED",
    "ELIGIBLE_FOR_SHADOW_CONTEXT",
    "ELIGIBLE_FOR_CIO_CONTEXT",
    "BLOCKED",
    "INVALIDATED",
    "RETIRED",
)
