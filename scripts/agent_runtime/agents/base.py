from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping

from ..contracts import (
    FORBIDDEN_TOOL_PREFIXES,
    AgentDefinition,
    DeploymentState,
)

# ---------------------------------------------------------------------------
# Triggers
# ---------------------------------------------------------------------------
# A trigger is *descriptive metadata* only.  It documents the deterministic,
# externally-owned event that a NON-agentic scheduler observes before it may
# enqueue a bounded job for the agent.  An agent can never satisfy or fire its
# own trigger, and the trigger carries no authority.


class TriggerKind(str, Enum):
    WATCH_ARTIFACT_CHANGED = "WATCH_ARTIFACT_CHANGED"
    PACKET_REBUILD = "PACKET_REBUILD"
    CONTRADICTION_EXCEPTION = "CONTRADICTION_EXCEPTION"
    QUALITY_EXCEPTION = "QUALITY_EXCEPTION"
    OUTCOME_EVIDENCE_AVAILABLE = "OUTCOME_EVIDENCE_AVAILABLE"
    SCHEDULED_SWEEP = "SCHEDULED_SWEEP"
    CANDIDATE_LESSON = "CANDIDATE_LESSON"
    RETRIEVAL_QUALITY_EXCEPTION = "RETRIEVAL_QUALITY_EXCEPTION"
    REPEATED_FINDING = "REPEATED_FINDING"
    NIGHTLY_BATCH = "NIGHTLY_BATCH"
    INCIDENT_OPENED = "INCIDENT_OPENED"
    RESEARCH_REQUEST = "RESEARCH_REQUEST"
    MATERIAL_PORTFOLIO_CHANGE = "MATERIAL_PORTFOLIO_CHANGE"
    CIO_SCHEDULED_BRIEF = "CIO_SCHEDULED_BRIEF"


@dataclass(frozen=True)
class Trigger:
    kind: TriggerKind
    description: str
    # The deterministic source that owns the event. Agents are never listed here.
    owned_by: str = "deterministic-scheduler"

    def validate(self) -> None:
        if not self.description.strip():
            raise ValueError("trigger description is required")
        if self.owned_by.strip().lower() in {"", "agent", "self", "model"}:
            raise ValueError("triggers may not be owned by an agent or a model")


# ---------------------------------------------------------------------------
# Governed output kinds
# ---------------------------------------------------------------------------
# The kinds of advisory evidence an agent may emit through the governed output
# channel.  None of these is an execution, promotion, or activation.


class OutputKind(str, Enum):
    INTEGRITY_REVIEW = "INTEGRITY_REVIEW"
    SCORECARD = "SCORECARD"
    IMPROVEMENT_PROPOSAL = "IMPROVEMENT_PROPOSAL"
    LESSON_REVIEW = "LESSON_REVIEW"
    CURATION_ARTIFACT = "CURATION_ARTIFACT"
    CANDIDATE_LESSON = "CANDIDATE_LESSON"
    CANDIDATE_HYPOTHESIS = "CANDIDATE_HYPOTHESIS"
    REMEDIATION_PROPOSAL = "REMEDIATION_PROPOSAL"
    RESEARCH_TASK = "RESEARCH_TASK"
    DRAFT_PR = "DRAFT_PR"
    RESEARCH_REVIEW = "RESEARCH_REVIEW"
    TECHNICAL_STRUCTURE_REVIEW = "TECHNICAL_STRUCTURE_REVIEW"
    RISK_EVIDENCE_CRITIQUE = "RISK_EVIDENCE_CRITIQUE"
    # CIO / wealth-advisory outputs (Wave 3)
    CIO_SYNTHESIS = "CIO_SYNTHESIS"
    ACTION_ITEM = "ACTION_ITEM"
    ALLOCATION_REVIEW = "ALLOCATION_REVIEW"
    TAX_LOT_REVIEW = "TAX_LOT_REVIEW"
    WEALTH_SYNTHESIS = "WEALTH_SYNTHESIS"


# Tool-name fragments that would, if allow-listed, hand an agent authority it must
# never hold.  These are checked *in addition to* ``FORBIDDEN_TOOL_PREFIXES`` and
# cover the self-governance surface (an agent changing its own schedule, budget,
# permissions, or promoting its own outputs).
SELF_GOVERNANCE_TOKENS = (
    "schedule",
    "enqueue_self",
    "budget.set",
    "budget.write",
    "permission",
    "permissions",
    "promote",
    "ratify",
    "activate",
    "deploy",
    "merge",
    "enable_agent",
    "grant",
)


@dataclass(frozen=True)
class ShadowAgentSpec:
    """A complete, governed definition of one autonomous SHADOW agent.

    The spec binds an :class:`AgentDefinition` (the runtime authority contract)
    to its trigger surface, the advisory outputs it may produce, and the two
    *different* agents that independently review and score its artifacts.  It
    carries no ability to act; it is data plus hard guards.
    """

    definition: AgentDefinition
    summary: str
    triggers: tuple[Trigger, ...]
    allowed_output_kinds: tuple[OutputKind, ...]
    reviewer_agent_id: str
    scorer_agent_id: str
    maturity_target: str
    wave: str  # "INITIAL" | "SECOND" | "THIRD"
    circuit_breaker_trips_open_after: int = 3
    max_queue_depth: int = 64
    dedup_key: str = "input_hash"
    stale_input_seconds: int = 900
    authority_note: str = "ADVISORY_ONLY; deterministic core remains sovereign"

    @property
    def agent_id(self) -> str:
        return self.definition.agent_id

    def validate(self) -> None:
        self.definition.validate()
        if not self.summary.strip():
            raise ValueError(f"{self.agent_id}: summary is required")
        if not self.triggers:
            raise ValueError(f"{self.agent_id}: at least one trigger is required")
        for trigger in self.triggers:
            trigger.validate()
        if not self.allowed_output_kinds:
            raise ValueError(f"{self.agent_id}: at least one output kind is required")
        # Independent review and independent scoring: neither may be the producer.
        if self.reviewer_agent_id == self.agent_id:
            raise ValueError(f"{self.agent_id}: an agent may not be its own reviewer")
        if self.scorer_agent_id == self.agent_id:
            raise ValueError(f"{self.agent_id}: an agent may not be its own scorer")
        if self.wave not in {"INITIAL", "SECOND", "THIRD"}:
            raise ValueError(f"{self.agent_id}: wave must be INITIAL, SECOND, or THIRD")
        if self.circuit_breaker_trips_open_after < 1:
            raise ValueError(f"{self.agent_id}: circuit breaker threshold must be >= 1")
        if self.max_queue_depth < 1:
            raise ValueError(f"{self.agent_id}: max_queue_depth must be >= 1")
        if self.stale_input_seconds < 1:
            raise ValueError(f"{self.agent_id}: stale_input_seconds must be >= 1")
        assert_no_self_governance(self)

    @property
    def is_operable_now(self) -> bool:
        """True only for an agent that is enabled in DESIGNED/SHADOW.

        Second-wave (disabled / DESIGNED-only) agents return False and cannot be
        instantiated into a runtime.
        """
        return self.definition.enabled and self.definition.deployment_state in {
            DeploymentState.SHADOW,
            DeploymentState.DESIGNED,
        }


def assert_no_self_governance(spec: ShadowAgentSpec) -> None:
    """Fail closed if a spec could grant an agent authority over itself or the
    system, beyond the constitutional deny-list already enforced by contracts."""
    allowed = [tool.strip().lower() for tool in spec.definition.allowed_tools]
    for tool in allowed:
        for prefix in FORBIDDEN_TOOL_PREFIXES:
            if tool == prefix.rstrip(".") or tool.startswith(prefix):
                raise ValueError(
                    f"{spec.agent_id}: forbidden tool cannot be allow-listed: {tool}"
                )
        for token in SELF_GOVERNANCE_TOKENS:
            if token in tool:
                raise ValueError(
                    f"{spec.agent_id}: self-governance tool cannot be allow-listed: {tool}"
                )
    # An operable agent must be SHADOW/DESIGNED and never OPERATIONAL here.
    if spec.definition.deployment_state is DeploymentState.OPERATIONAL:
        raise ValueError(
            f"{spec.agent_id}: OPERATIONAL is not reachable through a Lane D definition"
        )


def assert_fleet_separation(specs: Mapping[str, ShadowAgentSpec]) -> None:
    """Validate the whole fleet: unique ids, real reviewers/scorers, and the
    independent-reviewer / independent-scorer invariant across every producer."""
    for agent_id, spec in specs.items():
        if agent_id != spec.agent_id:
            raise ValueError(f"registry key {agent_id!r} != spec.agent_id {spec.agent_id!r}")
        spec.validate()
        if spec.reviewer_agent_id not in specs:
            raise ValueError(f"{agent_id}: reviewer {spec.reviewer_agent_id} is not in the fleet")
        if spec.scorer_agent_id not in specs:
            raise ValueError(f"{agent_id}: scorer {spec.scorer_agent_id} is not in the fleet")


# Re-exported for tests that assert the deny surface stays wired to contracts.
FORBIDDEN_TOOL_PREFIXES = FORBIDDEN_TOOL_PREFIXES
