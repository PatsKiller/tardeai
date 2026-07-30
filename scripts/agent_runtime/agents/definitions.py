from __future__ import annotations

from typing import Mapping

from ..contracts import AgentDefinition, BudgetPolicy, DeploymentState
from .base import (
    OutputKind,
    ShadowAgentSpec,
    Trigger,
    TriggerKind,
    assert_fleet_separation,
)

OWNER = "architecture-owner"


def _def(
    agent_id: str,
    display_name: str,
    role: str,
    *,
    allowed_job_types: tuple[str, ...],
    allowed_tools: tuple[str, ...],
    denied_tools: tuple[str, ...],
    retrieval_required: bool,
    enabled: bool,
    state: DeploymentState,
    budget: BudgetPolicy,
    version: str = "1.0.0-shadow",
) -> AgentDefinition:
    return AgentDefinition(
        agent_id=agent_id,
        display_name=display_name,
        role=role,
        version=version,
        owner=OWNER,
        allowed_job_types=allowed_job_types,
        allowed_tools=allowed_tools,
        denied_tools=denied_tools,
        retrieval_required=retrieval_required,
        budget=budget,
        deployment_state=state,
        enabled=enabled,
    )


# ---------------------------------------------------------------------------
# Wave 1 — the four initial autonomous SHADOW agents (enabled in SHADOW)
# ---------------------------------------------------------------------------

_SENTINEL = ShadowAgentSpec(
    definition=_def(
        "sentinel",
        "Sentinel",
        "Decision-integrity reflective critic",
        allowed_job_types=("watch_ticket_review", "decision_integrity_review", "known_bad_regression"),
        allowed_tools=("kb.search", "kb.get_lesson", "kb.get_case", "ticket.read", "validator.read", "artifact.write", "quarantine.stage"),
        denied_tools=("kb.ratify", "score.write", "hypothesis.promote", "ticket.write", "quality.override"),
        retrieval_required=True,
        enabled=True,
        state=DeploymentState.SHADOW,
        budget=BudgetPolicy(max_model_calls=3, max_tool_calls=12, max_cost_usd=0.0, deadline_seconds=360),
    ),
    summary=(
        "Independently challenges each Watch artifact after deterministic validation: "
        "retrieves immutable evidence, hunts contradictions, missing evidence and unsafe "
        "assumptions, and files a structured integrity review. Cannot change any Watch "
        "decision, ticket, quality admission or order."
    ),
    triggers=(
        Trigger(TriggerKind.WATCH_ARTIFACT_CHANGED, "A new or changed Watch artifact is published"),
        Trigger(TriggerKind.PACKET_REBUILD, "A decision packet is rebuilt"),
        Trigger(TriggerKind.CONTRADICTION_EXCEPTION, "A contradiction or quality exception is raised"),
    ),
    allowed_output_kinds=(OutputKind.INTEGRITY_REVIEW, OutputKind.IMPROVEMENT_PROPOSAL),
    reviewer_agent_id="iris",
    scorer_agent_id="darwin",
    maturity_target="MVL operational shadow",
    wave="INITIAL",
)

_DARWIN = ShadowAgentSpec(
    definition=_def(
        "darwin",
        "Darwin",
        "Outcome-join and artifact scorer",
        allowed_job_types=("artifact_scoring", "outcome_join", "calibration_evidence"),
        allowed_tools=("artifact.read", "outcome.read", "case.read", "score.write"),
        denied_tools=("artifact.write", "config.promote", "lesson.ratify", "scoring_policy.write", "threshold.write"),
        retrieval_required=False,
        enabled=True,
        state=DeploymentState.SHADOW,
        budget=BudgetPolicy(max_model_calls=0, max_tool_calls=12, max_cost_usd=0.0, deadline_seconds=600),
    ),
    summary=(
        "Joins artifacts to deterministic outcomes, scores predefined dimensions and "
        "detects calibration drift, producing scorecards and improvement proposals. "
        "Cannot alter scoring policy, prompts, thresholds or configuration."
    ),
    triggers=(
        Trigger(TriggerKind.OUTCOME_EVIDENCE_AVAILABLE, "Deterministic outcome evidence becomes available"),
        Trigger(TriggerKind.SCHEDULED_SWEEP, "A bounded scheduled scoring sweep runs"),
    ),
    allowed_output_kinds=(OutputKind.SCORECARD, OutputKind.IMPROVEMENT_PROPOSAL),
    reviewer_agent_id="iris",
    scorer_agent_id="sentinel",
    maturity_target="MVL operational shadow",
    wave="INITIAL",
)

_IRIS = ShadowAgentSpec(
    definition=_def(
        "iris",
        "Iris",
        "Knowledge curation and lesson-lifecycle reviewer",
        allowed_job_types=("lesson_review", "knowledge_quality", "retrieval_audit"),
        allowed_tools=("kb.search", "kb.get_lesson", "kb.get_case", "lesson_review.write", "contradiction.write"),
        denied_tools=("lesson.ratify", "config.promote", "hypothesis.promote", "kb.write", "lesson.retire"),
        retrieval_required=True,
        enabled=True,
        state=DeploymentState.SHADOW,
        budget=BudgetPolicy(max_model_calls=3, max_tool_calls=16, max_cost_usd=0.0, deadline_seconds=600),
    ),
    summary=(
        "Reviews provenance and temporal validity of candidate lessons, finds "
        "contradictions and duplicates, and produces lesson-review and curation "
        "artifacts. Cannot ratify or promote a lesson."
    ),
    triggers=(
        Trigger(TriggerKind.CANDIDATE_LESSON, "A candidate lesson is registered"),
        Trigger(TriggerKind.CONTRADICTION_EXCEPTION, "A knowledge contradiction is raised"),
        Trigger(TriggerKind.RETRIEVAL_QUALITY_EXCEPTION, "A retrieval-quality exception is raised"),
        Trigger(TriggerKind.REPEATED_FINDING, "A repeated Sentinel/Darwin finding recurs"),
    ),
    allowed_output_kinds=(OutputKind.LESSON_REVIEW, OutputKind.CURATION_ARTIFACT),
    reviewer_agent_id="sentinel",
    scorer_agent_id="darwin",
    maturity_target="MVL operational shadow",
    wave="INITIAL",
)

_REFLECTION = ShadowAgentSpec(
    definition=_def(
        "reflection",
        "Nightly Reflection",
        "Case-to-lesson and hypothesis-candidate generation",
        allowed_job_types=("nightly_reflection", "exception_reflection"),
        allowed_tools=("kb.search", "case.read", "exception.read", "lesson_candidate.write", "hypothesis.register"),
        denied_tools=("lesson.ratify", "hypothesis.promote", "config.promote", "backtest.launch"),
        retrieval_required=True,
        enabled=True,
        state=DeploymentState.SHADOW,
        budget=BudgetPolicy(max_model_calls=3, max_tool_calls=20, max_cost_usd=0.0, deadline_seconds=1200),
    ),
    summary=(
        "On a bounded nightly batch of completed cases, exceptions and scored "
        "artifacts, generates candidate lessons and preregistered hypotheses, "
        "identifies recurring failure patterns and proposes research/test work. "
        "Cannot activate a hypothesis, merge, deploy or change configuration."
    ),
    triggers=(
        Trigger(TriggerKind.NIGHTLY_BATCH, "A bounded nightly batch of completed cases and scored artifacts is ready"),
    ),
    allowed_output_kinds=(OutputKind.CANDIDATE_LESSON, OutputKind.CANDIDATE_HYPOTHESIS, OutputKind.RESEARCH_TASK),
    reviewer_agent_id="iris",
    scorer_agent_id="darwin",
    maturity_target="MVL operational shadow",
    wave="INITIAL",
)


# ---------------------------------------------------------------------------
# Wave 2 — prepared but DISABLED (DESIGNED, enabled=False). Definitions only.
# ---------------------------------------------------------------------------

_MARIA = ShadowAgentSpec(
    definition=_def(
        "maria",
        "Maria",
        "Evidence-bound fundamental and catalyst research critic",
        allowed_job_types=("fundamental_research_review", "catalyst_review"),
        allowed_tools=("kb.search", "kb.get_lesson", "filing.read", "catalyst.read", "fundamentals.read", "artifact.write"),
        denied_tools=("proposal.authorize", "config.promote", "ticket.write"),
        retrieval_required=True,
        enabled=False,
        state=DeploymentState.DESIGNED,
        budget=BudgetPolicy(max_model_calls=3, max_tool_calls=16, max_cost_usd=0.0, deadline_seconds=600),
    ),
    summary=(
        "Evidence-bound fundamental/catalyst research review. Every claim must cite "
        "immutable evidence; invented structure is rejected. Advisory only. DISABLED "
        "pending wave-1 maturity acceptance."
    ),
    triggers=(
        Trigger(TriggerKind.WATCH_ARTIFACT_CHANGED, "A research-eligible artifact is published"),
        Trigger(TriggerKind.RESEARCH_REQUEST, "A bounded research request is enqueued by the scheduler"),
    ),
    allowed_output_kinds=(OutputKind.RESEARCH_REVIEW, OutputKind.IMPROVEMENT_PROPOSAL),
    reviewer_agent_id="iris",
    scorer_agent_id="darwin",
    maturity_target="Wave-2 shadow research critic",
    wave="SECOND",
)

_VEGA = ShadowAgentSpec(
    definition=_def(
        "vega",
        "Vega",
        "Technical-structure review critic",
        allowed_job_types=("technical_structure_review",),
        allowed_tools=("kb.search", "chart.read", "indicator.read", "level.read", "artifact.write"),
        denied_tools=("proposal.authorize", "config.promote", "ticket.write"),
        retrieval_required=True,
        enabled=False,
        state=DeploymentState.DESIGNED,
        budget=BudgetPolicy(max_model_calls=3, max_tool_calls=14, max_cost_usd=0.0, deadline_seconds=600),
    ),
    summary=(
        "Reviews technical structure (levels, indicators, regime) against immutable "
        "market evidence. Advisory only. DISABLED pending wave-1 maturity acceptance."
    ),
    triggers=(
        Trigger(TriggerKind.WATCH_ARTIFACT_CHANGED, "A technical-structure-eligible artifact is published"),
        Trigger(TriggerKind.PACKET_REBUILD, "A decision packet is rebuilt"),
    ),
    allowed_output_kinds=(OutputKind.TECHNICAL_STRUCTURE_REVIEW, OutputKind.IMPROVEMENT_PROPOSAL),
    reviewer_agent_id="sentinel",
    scorer_agent_id="darwin",
    maturity_target="Wave-2 shadow technical critic",
    wave="SECOND",
)

_RISK_AGENT = ShadowAgentSpec(
    definition=_def(
        "risk_agent",
        "Guardian Risk",
        "Critic of deterministic risk evidence",
        allowed_job_types=("risk_evidence_review",),
        allowed_tools=("kb.search", "risk_evidence.read", "exposure.read", "artifact.write"),
        denied_tools=("risk_policy.write", "position.close", "config.promote", "limit.write"),
        retrieval_required=True,
        enabled=False,
        state=DeploymentState.DESIGNED,
        budget=BudgetPolicy(max_model_calls=2, max_tool_calls=12, max_cost_usd=0.0, deadline_seconds=600),
    ),
    summary=(
        "Critiques deterministic risk evidence (exposure, concentration, stop "
        "coverage) without any position or limit authority. Advisory only. DISABLED "
        "pending wave-1 maturity acceptance."
    ),
    triggers=(
        Trigger(TriggerKind.QUALITY_EXCEPTION, "A risk-evidence quality exception is raised"),
        Trigger(TriggerKind.SCHEDULED_SWEEP, "A bounded scheduled risk-evidence sweep runs"),
    ),
    allowed_output_kinds=(OutputKind.RISK_EVIDENCE_CRITIQUE, OutputKind.IMPROVEMENT_PROPOSAL),
    reviewer_agent_id="iris",
    scorer_agent_id="darwin",
    maturity_target="Wave-2 shadow risk critic",
    wave="SECOND",
)

_AEGIS = ShadowAgentSpec(
    definition=_def(
        "aegis",
        "Aegis",
        "Incident-review and remediation-proposal critic",
        allowed_job_types=("incident_review", "remediation_proposal"),
        allowed_tools=("kb.search", "incident.read", "log.read", "remediation_proposal.write"),
        denied_tools=("service.restart", "config.promote", "remediation.apply", "systemd.enable"),
        retrieval_required=True,
        enabled=False,
        state=DeploymentState.DESIGNED,
        budget=BudgetPolicy(max_model_calls=3, max_tool_calls=16, max_cost_usd=0.0, deadline_seconds=900),
    ),
    summary=(
        "Reviews incidents and drafts remediation proposals from immutable logs and "
        "incident evidence. Proposals are advisory drafts; Aegis cannot restart a "
        "service, apply a fix or change configuration. DISABLED pending wave-1 "
        "maturity acceptance."
    ),
    triggers=(
        Trigger(TriggerKind.INCIDENT_OPENED, "An incident is opened"),
        Trigger(TriggerKind.REPEATED_FINDING, "A repeated operational finding recurs"),
    ),
    allowed_output_kinds=(OutputKind.REMEDIATION_PROPOSAL, OutputKind.RESEARCH_TASK, OutputKind.DRAFT_PR),
    reviewer_agent_id="sentinel",
    scorer_agent_id="darwin",
    maturity_target="Wave-2 shadow incident critic",
    wave="SECOND",
)


# ---------------------------------------------------------------------------
# Population-integrity scanner — enabled SHADOW. Deterministic (0 model calls,
# retrieval not required); files structured exception findings, advisory only.
# Mirrors the argus contract in config/agent_maturity_catalog.json.
# ---------------------------------------------------------------------------
_ARGUS = ShadowAgentSpec(
    definition=_def(
        "argus",
        "Argus",
        "Population-integrity reflective scanner",
        allowed_job_types=("population_integrity_scan", "presentation_consistency_scan"),
        allowed_tools=("artifact.read", "population.read", "exception.write"),
        denied_tools=("artifact.write", "ticket.write", "config.promote"),
        retrieval_required=False,
        enabled=True,
        state=DeploymentState.SHADOW,
        budget=BudgetPolicy(max_model_calls=0, max_tool_calls=20, max_cost_usd=0.0, deadline_seconds=900),
    ),
    summary=(
        "Deterministically scans the artifact / holdings / watchlist population for "
        "cross-artifact contradictions, drift and presentation inconsistencies, and "
        "files structured exception findings. Advisory only: it cannot write a ticket, "
        "promote config, or alter any sovereign decision."
    ),
    triggers=(
        Trigger(TriggerKind.SCHEDULED_SWEEP, "A bounded population-integrity sweep runs"),
        Trigger(TriggerKind.QUALITY_EXCEPTION, "A population-level quality exception is raised"),
    ),
    allowed_output_kinds=(OutputKind.INTEGRITY_REVIEW, OutputKind.IMPROVEMENT_PROPOSAL),
    reviewer_agent_id="sentinel",
    scorer_agent_id="darwin",
    maturity_target="Phase 2 shadow",
    wave="INITIAL",
)


FLEET: dict[str, ShadowAgentSpec] = {
    spec.agent_id: spec
    for spec in (
        _SENTINEL,
        _DARWIN,
        _IRIS,
        _REFLECTION,
        _ARGUS,
        _MARIA,
        _VEGA,
        _RISK_AGENT,
        _AEGIS,
    )
}

# INITIAL_SHADOW_AGENT_IDS = the enabled SHADOW fleet. argus was authored + enabled
# after the original four; being enabled, it belongs here (not the disabled 2nd wave).
INITIAL_SHADOW_AGENT_IDS: tuple[str, ...] = ("sentinel", "darwin", "iris", "reflection", "argus")
SECOND_WAVE_AGENT_IDS: tuple[str, ...] = ("maria", "vega", "risk_agent", "aegis")

# Fail-closed at import time: the entire fleet must satisfy the separation and
# authority invariants, or the module cannot be imported.
assert_fleet_separation(FLEET)


def fleet() -> Mapping[str, ShadowAgentSpec]:
    return dict(FLEET)


def spec(agent_id: str) -> ShadowAgentSpec:
    if agent_id not in FLEET:
        raise KeyError(f"unknown agent: {agent_id}")
    return FLEET[agent_id]


def initial_agents() -> dict[str, ShadowAgentSpec]:
    return {agent_id: FLEET[agent_id] for agent_id in INITIAL_SHADOW_AGENT_IDS}


def second_wave_agents() -> dict[str, ShadowAgentSpec]:
    return {agent_id: FLEET[agent_id] for agent_id in SECOND_WAVE_AGENT_IDS}


def reviewer_scorer_matrix() -> dict[str, dict[str, str]]:
    """The independent reviewer/scorer assignment for every producer."""
    return {
        agent_id: {
            "reviewer": spec.reviewer_agent_id,
            "scorer": spec.scorer_agent_id,
        }
        for agent_id, spec in FLEET.items()
    }
