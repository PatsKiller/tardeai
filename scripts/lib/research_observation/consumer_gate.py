"""Downstream consumer gate — reject ineligible research observations.

Command Center display consumers may accept DISPLAY_ONLY with a degraded
label. Proposal and agent consumers must receive ELIGIBLE only.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from .contract import ResearchObservation
from .eligibility import (
    DEFAULT_POLICY,
    EligibilityPolicy,
    EligibilityResult,
    evaluate_eligibility,
)
from .statuses import EligibilityDecision


# Canonical consumer kinds used in the product→consumer ledger.
CONSUMER_KINDS = frozenset({"display", "proposal", "agent"})


@dataclass(frozen=True)
class ConsumerGateResult:
    accepted: bool
    consumer_kind: str
    consumer_id: str
    decision: EligibilityDecision
    reasons: tuple[str, ...]
    observation_run_id: Optional[str]
    observation_source_hash: Optional[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "consumer_kind": self.consumer_kind,
            "consumer_id": self.consumer_id,
            "decision": self.decision.value,
            "reasons": list(self.reasons),
            "observation_run_id": self.observation_run_id,
            "observation_source_hash": self.observation_source_hash,
        }


def gate_for_consumer(
    obs: ResearchObservation,
    *,
    consumer_id: str,
    consumer_kind: str = "proposal",
    policy: EligibilityPolicy = DEFAULT_POLICY,
    now: Optional[datetime] = None,
    expected_run_id: Optional[str] = None,
    expected_source_hash: Optional[str] = None,
) -> ConsumerGateResult:
    """Gate a research observation for a named downstream consumer."""
    kind = consumer_kind if consumer_kind in CONSUMER_KINDS else "proposal"
    result: EligibilityResult = evaluate_eligibility(
        obs,
        policy=policy,
        now=now or datetime.now(timezone.utc),
        expected_run_id=expected_run_id,
        expected_source_hash=expected_source_hash,
        consumer_kind=kind,
    )
    if kind == "display":
        accepted = result.decision in (
            EligibilityDecision.ELIGIBLE,
            EligibilityDecision.DISPLAY_ONLY,
        )
    else:
        accepted = result.decision == EligibilityDecision.ELIGIBLE
    return ConsumerGateResult(
        accepted=accepted,
        consumer_kind=kind,
        consumer_id=consumer_id,
        decision=result.decision,
        reasons=result.reasons,
        observation_run_id=obs.run_id,
        observation_source_hash=obs.source_hash,
    )


class IneligibleResearchError(ValueError):
    """Raised when a proposal/agent consumer refuses an ineligible record."""

    def __init__(self, gate: ConsumerGateResult):
        self.gate = gate
        super().__init__(f"INELIGIBLE for {gate.consumer_id} ({gate.consumer_kind}): " + "; ".join(gate.reasons))


def assert_eligible_or_raise(
    obs: ResearchObservation,
    *,
    consumer_id: str,
    consumer_kind: str = "proposal",
    policy: EligibilityPolicy = DEFAULT_POLICY,
    now: Optional[datetime] = None,
    expected_run_id: Optional[str] = None,
    expected_source_hash: Optional[str] = None,
) -> ConsumerGateResult:
    """Fail closed: raise if the consumer must not accept the observation."""
    gate = gate_for_consumer(
        obs,
        consumer_id=consumer_id,
        consumer_kind=consumer_kind,
        policy=policy,
        now=now,
        expected_run_id=expected_run_id,
        expected_source_hash=expected_source_hash,
    )
    if not gate.accepted:
        raise IneligibleResearchError(gate)
    return gate
