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

RESULT_NO_MATERIAL_OBJECTION = "NO_MATERIAL_OBJECTION"
RESULT_MATERIAL_OBJECTION = "MATERIAL_OBJECTION"
RESULT_DATA_UNAVAILABLE = "DATA_UNAVAILABLE"


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


def review_decision(evidence_packet: dict, proposed_action: dict) -> CriticReview:
    """Deterministic shadow review. Never mutates anything external.

    evidence_packet keys used:
      facts (list of {key, freshness?}), identity_status, contradictions (list),
      unmodeled_coverage_pct, vintage_leak (bool), counterevidence (list).
    proposed_action keys used:
      action, subject, objective, candidate_authority.
    """
    evidence = evidence_packet or {}
    action = proposed_action or {}
    review = CriticReview(
        critic_review_id=f"critic-{_digest(proposed_action)}",
        decision_id=str(action.get("decision_id") or ""),
        input_digest=_digest(proposed_action),
        evidence_digest=_digest(evidence),
        proposed_action=action,
        created_at=_now(),
    )

    if not evidence and not action:
        review.result = RESULT_DATA_UNAVAILABLE
        review.recommended_next_step = "provide evidence packet and proposed action"
        return review

    # 1. Freshness: stale facts or vintage leak.
    for fact in evidence.get("facts") or []:
        if (fact.get("freshness") or "").upper() == "STALE":
            review.freshness_risks.append(f"stale fact: {fact.get('key')}")
    if evidence.get("vintage_leak"):
        review.freshness_risks.append("macro vintage leak: a later revision used at decision time")

    # 2. Identity.
    status = str(evidence.get("identity_status") or "RESOLVED").upper()
    if status != "RESOLVED":
        review.identity_risks.append(f"identity status is {status}")

    # 3. Contradictions / counterevidence (preserved, never deleted).
    for c in evidence.get("contradictions") or []:
        review.counterevidence.append(str(c))
    for c in evidence.get("counterevidence") or []:
        review.counterevidence.append(str(c))
    if review.counterevidence:
        review.objections.append("contradictory evidence present; decision must address it")

    # 4. Unmodeled portfolio effects.
    coverage = evidence.get("unmodeled_coverage_pct")
    if coverage is not None:
        try:
            if float(coverage) < 100.0:
                review.portfolio_effects.append(
                    f"{100.0 - float(coverage):.2f}% of portfolio is unmodeled"
                )
        except (TypeError, ValueError):
            pass

    # 5. Missing evidence by action type.
    act = str(action.get("action") or "").lower()
    if act in ("trim", "deploy_cash", "deploy", "reentry", "re-enter"):
        if not action.get("objective"):
            review.missing_evidence.append("no stated objective for a material action")
    if act in ("reentry", "re-enter") and not action.get("candidate_authority"):
        review.missing_evidence.append("re-entry without candidate-specific authority")
    if act in ("trim", "trim_concentration") and not evidence.get("concentration_evidence"):
        review.missing_evidence.append("concentration trim without concentration evidence")

    # 6. Unsupported claims (a claim with no incoming evidence).
    for claim in evidence.get("unsupported_claims") or []:
        review.objections.append(f"unsupported claim: {claim}")

    # Determine result.
    material = (
        review.freshness_risks
        or review.identity_risks
        or review.counterevidence
        or review.missing_evidence
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
