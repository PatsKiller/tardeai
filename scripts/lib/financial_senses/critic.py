"""Independent CIO critic — shadow-only adversarial second pass.

The critic is not another visible persona. It is an internal review step that
assumes a proposed material decision MAY BE WRONG and looks for the strongest
evidence against it, missing evidence, unmodeled portfolio effects, and
identity/freshness/source problems.

Shadow-only in this branch: CRITIC_SHADOW=1, CRITIC_BEHAVIOR_INFLUENCE=0. The
critic never changes live decisions and never sends Telegram. A deterministic
engine is the default; an LLM-backed critic is optional and stays dry/shadow.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Optional

from .provider import BaseProvider, Capability
from .result import FinancialSenseResult, STATUS_OK

# Shadow-only flags (fixed in this branch).
CRITIC_SHADOW = 1
CRITIC_BEHAVIOR_INFLUENCE = 0

CRITIC_VERSION = "1.1.0"
# Unmodeled portfolio coverage below this (in %) is a material blind spot.
UNMODELED_MATERIALITY_THRESHOLD_PCT = 5.0

RESULT_NO_MATERIAL_OBJECTION = "NO_MATERIAL_OBJECTION"
RESULT_MATERIAL_OBJECTION = "MATERIAL_OBJECTION"
RESULT_DATA_UNAVAILABLE = "DATA_UNAVAILABLE"

# Material advisory actions: those that move capital or change positions, and
# therefore require substantive evidence before they may pass a shadow review.
# Aligned with the canonical InvestmentDecision action vocabulary (lowercased
# to match the normalized `act` in review_decision).
_MATERIAL_ACTIONS = frozenset(
    {
        "add",
        "trim",
        "exit",
        "rotate",
        "raise_cash",
        "deploy_cash",
        "re_enter",
        "re-enter",
        "reentry",
        "deploy",
        "trim_concentration",
    }
)


@dataclass
class CriticReview:
    critic_review_id: str
    decision_id: Optional[str] = None
    input_digest: Optional[str] = None
    evidence_digest: Optional[str] = None
    proposed_action: Optional[dict] = None
    objections: list[str] = field(default_factory=list)
    missing_evidence: list[str] = field(default_factory=list)
    counterevidence: list[str] = field(default_factory=list)
    portfolio_effects: list[str] = field(default_factory=list)
    identity_risks: list[str] = field(default_factory=list)
    freshness_risks: list[str] = field(default_factory=list)
    result: str = RESULT_NO_MATERIAL_OBJECTION
    recommended_next_step: Optional[str] = None
    created_at: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _digest(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _coerce_pct(value: Any) -> Optional[float]:
    """Parse a percentage; return None if missing, non-numeric, or outside [0,100]."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if v < 0.0 or v > 100.0:
        return None
    return v


def review_decision(evidence_packet: dict, proposed_action: dict) -> CriticReview:
    """Deterministic shadow review. Never mutates anything external.

    evidence_packet keys used:
      facts (list of {key, freshness?}), identity_status, contradictions (list),
      coverage_pct / unmodeled_coverage_pct, vintage_leak (bool),
      counterevidence (list), concentration_evidence.
    proposed_action keys used:
      action, subject, objective, candidate_authority, decision_id.
    """
    evidence = evidence_packet or {}
    action = proposed_action or {}

    input_digest = _digest(proposed_action)
    evidence_digest = _digest(evidence)
    # Bind the review generation to the decision + input + evidence + version,
    # so the same action with different evidence yields a different review id.
    review = CriticReview(
        critic_review_id=(
            "critic-"
            + _digest(
                {
                    "decision_id": action.get("decision_id"),
                    "input_digest": input_digest,
                    "evidence_digest": evidence_digest,
                    "critic_version": CRITIC_VERSION,
                }
            )
        ),
        decision_id=str(action.get("decision_id") or ""),
        input_digest=input_digest,
        evidence_digest=evidence_digest,
        proposed_action=action,
        created_at=_now(),
    )

    if not evidence and not action:
        review.result = RESULT_DATA_UNAVAILABLE
        review.recommended_next_step = "provide evidence packet and proposed action"
        return review

    act = str(action.get("action") or "").lower()

    # 1. Freshness: stale facts or vintage leak.
    for fact in evidence.get("facts") or []:
        if (fact.get("freshness") or "").upper() == "STALE":
            review.freshness_risks.append(f"stale fact: {fact.get('key')}")
    if evidence.get("vintage_leak"):
        review.freshness_risks.append("macro vintage leak: a later revision used at decision time")

    # 2. Identity — fail closed: missing identity is UNKNOWN, not RESOLVED.
    status = str(evidence.get("identity_status") or "UNKNOWN").upper()
    if status != "RESOLVED":
        review.identity_risks.append(f"identity status is {status}")

    # 3. Contradictions / counterevidence (preserved, never deleted).
    for c in evidence.get("contradictions") or []:
        review.counterevidence.append(str(c))
    for c in evidence.get("counterevidence") or []:
        review.counterevidence.append(str(c))
    if review.counterevidence:
        review.objections.append("contradictory evidence present; decision must address it")

    # 4. Unmodeled portfolio effects — material above the documented threshold.
    # `coverage_pct` is MODELED coverage (unmodeled = 100 - value);
    # `unmodeled_coverage_pct` is already the UNMODELED fraction and must not be
    # subtracted from 100 again. Both must be within [0, 100]; a malformed /
    # out-of-range value means coverage cannot be assessed and must never
    # silently pass.
    coverage_malformed = False
    if "coverage_pct" in evidence and evidence.get("coverage_pct") is not None:
        cov = _coerce_pct(evidence["coverage_pct"])
        if cov is None:
            coverage_malformed = True
            unmodeled = None
        else:
            unmodeled = 100.0 - cov
    elif "unmodeled_coverage_pct" in evidence and evidence.get("unmodeled_coverage_pct") is not None:
        unm = _coerce_pct(evidence["unmodeled_coverage_pct"])
        if unm is None:
            coverage_malformed = True
            unmodeled = None
        else:
            unmodeled = unm
    else:
        unmodeled = None

    if coverage_malformed:
        review.missing_evidence.append(
            "portfolio coverage out of range [0,100] or malformed"
        )
        review.result = RESULT_DATA_UNAVAILABLE
        review.recommended_next_step = "provide a valid coverage_pct or unmodeled_coverage_pct in [0,100]"
        return review

    if unmodeled is not None and unmodeled > UNMODELED_MATERIALITY_THRESHOLD_PCT:
        review.portfolio_effects.append(f"{unmodeled:.2f}% of portfolio is unmodeled")
        review.objections.append(
            f"material unmodeled portfolio exposure ({unmodeled:.2f}%)"
        )

    # 5. Missing evidence by action type.
    if act in _MATERIAL_ACTIONS and not action.get("objective"):
        review.missing_evidence.append("no stated objective for a material action")
    if act in ("reentry", "re-enter", "re_enter") and not action.get("candidate_authority"):
        review.missing_evidence.append("re-entry without candidate-specific authority")
    if act in ("trim", "trim_concentration") and not evidence.get("concentration_evidence"):
        review.missing_evidence.append("concentration trim without concentration evidence")

    # 6. Evidence packet absent/incomplete must not silently pass a material action.
    has_evidence_content = bool(
        evidence.get("facts")
        or evidence.get("coverage_pct") is not None
        or evidence.get("unmodeled_coverage_pct") is not None
        or evidence.get("contradictions")
        or evidence.get("counterevidence")
        or evidence.get("concentration_evidence")
        or evidence.get("vintage_leak")
    )
    if act in _MATERIAL_ACTIONS and not has_evidence_content:
        review.missing_evidence.append("material action with no substantive evidence")

    # 7. Unsupported claims (a claim with no incoming evidence).
    for claim in evidence.get("unsupported_claims") or []:
        review.objections.append(f"unsupported claim: {claim}")

    # Determine result. Unmodeled portfolio effects are material.
    material = (
        review.freshness_risks
        or review.identity_risks
        or review.counterevidence
        or review.missing_evidence
        or review.portfolio_effects
        or review.objections
    )
    review.result = RESULT_MATERIAL_OBJECTION if material else RESULT_NO_MATERIAL_OBJECTION
    if review.result == RESULT_MATERIAL_OBJECTION:
        review.recommended_next_step = "resolve objections before proceeding"
    else:
        review.recommended_next_step = "no material objection; proceed subject to normal gates"
    return review


class IndependentCriticProvider(BaseProvider):
    name = "critic"
    version = "1.0.0"
    source_type = "MODEL_INFERENCE"

    def __init__(self, reviewer=None) -> None:
        # reviewer: optional callable(evidence, action) -> CriticReview (e.g. LLM).
        self._reviewer = reviewer or review_decision
        self._configured = True
        self._config_detail = ""

    def _capabilities(self) -> list[Capability]:
        return [
            Capability(
                "critic.review",
                "READ_ONLY",
                input_schema={"evidence": "object", "proposed_action": "object"},
            )
        ]

    def _query(self, capability: str, request: dict) -> FinancialSenseResult:
        if capability != "critic.review":
            return self._unavailable(capability, "unknown capability")
        evidence = request.get("evidence") or {}
        action = request.get("proposed_action") or {}
        if not isinstance(evidence, dict) or not isinstance(action, dict):
            return self._invalid("critic.review", "evidence and proposed_action required")
        review = self._reviewer(evidence, action)
        r = self._ok("critic.review")
        r.data = {"review": review.to_dict() if isinstance(review, CriticReview) else review}
        r.data["shadow_only"] = bool(CRITIC_SHADOW)
        r.data["behavior_influence"] = bool(CRITIC_BEHAVIOR_INFLUENCE)
        r.add_warning(
            "critic is shadow-only: this review cannot alter live decisions or notify anyone"
        )
        return r
