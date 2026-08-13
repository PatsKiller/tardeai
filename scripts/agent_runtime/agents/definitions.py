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
        budget=BudgetPolicy(max_model_calls=3, max_tool_calls=12, max_cost_usd=0.01, deadline_seconds=360),
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
        budget=BudgetPolicy(max_model_calls=3, max_tool_calls=16, max_cost_usd=0.01, deadline_seconds=600),
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
        budget=BudgetPolicy(max_model_calls=3, max_tool_calls=20, max_cost_usd=0.01, deadline_seconds=1200),
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
        "Research Director — evidence-bound fundamental and catalyst research critic",
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
        "Guardian",
        "Independent Risk Officer — deterministic-first risk critique",
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

_VIGIL = ShadowAgentSpec(
    definition=_def(
        "vigil",
        "Vigil",
        "Health Signal Fusion Inspector",
        allowed_job_types=("incident_review", "remediation_proposal", "health_inspection"),
        allowed_tools=(
            "health.read", "freshness.read",
            "db.query", "log.tail", "cron.manifest",
            "escalation.write", "finding.stage",
        ),
        denied_tools=(
            "*.write", "*.delete", "*.execute",
            "broker.*", "trading.*", "config.promote",
        ),
        retrieval_required=False,
        enabled=True,
        state=DeploymentState.SHADOW,
        budget=BudgetPolicy(max_model_calls=5, max_tool_calls=20, max_cost_usd=0.01, deadline_seconds=900),
    ),
    summary=(
        "Multi-layered health inspection agent: reads health surfaces (health_agent, "
        "system_health_agent, pipeline_freshness_monitor, hermes_pipeline_health), fuses "
        "signals via local LLM to identify root cause, stages findings in hermes_research_intelligence, "
        "and escalates P0/P1 to the staleness escalation queue. Shadow deployment: read-only "
        "inspection with no broker/trading/config-promote authority. The agent CAN write findings "
        "and escalation queue entries, but cannot execute remediations, restart services, or "
        "change configurations."
    ),
    triggers=(
        Trigger(TriggerKind.INCIDENT_OPENED, "An incident is opened"),
        Trigger(TriggerKind.SCHEDULED_SWEEP, "A scheduled health inspection sweep runs"),
    ),
    allowed_output_kinds=(OutputKind.REMEDIATION_PROPOSAL, OutputKind.INTEGRITY_REVIEW),
    reviewer_agent_id="sentinel",
    scorer_agent_id="darwin",
    maturity_target="MVL operational shadow",
    wave="INITIAL",
)


# ---------------------------------------------------------------------------
# Wave 3 — CIO + Wealth Advisory agents (enabled in SHADOW, advisory-only)
# ---------------------------------------------------------------------------
# Alex (CIO): Chief Investment Officer — owns the final investment recommendation.
# Morgan (CWO): Chief Wealth Officer — total financial life planning.
# Steph: Senior Portfolio & Wealth Strategist — allocation, rotation, sizing.
# Ledger (stable id `tax_agent` in the watch pipeline): Tax & account-constraint critic.
# Guardian role is served by the existing risk_agent (Wave 2); enable separately.
# ---------------------------------------------------------------------------

_ALEX = ShadowAgentSpec(
    definition=_def(
        "alex",
        "Alex",
        "Chief Investment Officer — autonomous advisory synthesis",
        allowed_job_types=("cio_synthesis", "action_ledger_management", "specialist_delegation", "portfolio_review"),
        allowed_tools=(
            "data_broker.read", "portfolio.read", "risk.read", "allocation.read",
            "financial_snapshot.read", "action_ledger.write", "action_ledger.read",
            "agent_artifact.read", "kb.search", "kb.get_case",
            "proposal.stage_advisory",
        ),
        denied_tools=(
            "broker.write", "order.*", "risk_policy.write", "position.*",
            "config.promote", "2fa.*", "secret.*", "broker.submit",
            "stop.*", "approval.*",
        ),
        retrieval_required=True,
        enabled=True,
        state=DeploymentState.SHADOW,
        budget=BudgetPolicy(max_model_calls=3, max_tool_calls=20, max_cost_usd=0.05, deadline_seconds=900),
    ),
    summary=(
        "Autonomous CIO synthesis agent. Reads canonical Trade AI Data Broker "
        "projections and financial snapshots, maintains the CIO action ledger, "
        "coordinates specialist research via governed handoff contracts, and "
        "produces advisory CIO synthesis artifacts. SHADOW deployment: shadow "
        "outputs only — no Telegram send, no broker action, no autonomous paid "
        "model calls without operator confirmation. Cannot submit orders, change "
        "positions, modify risk limits, perform 2FA, or read secrets."
    ),
    triggers=(
        Trigger(TriggerKind.CIO_SCHEDULED_BRIEF, "A scheduled CIO brief window opens (premarket/close/weekly)"),
        Trigger(TriggerKind.MATERIAL_PORTFOLIO_CHANGE, "A material portfolio composition or risk change is detected"),
        Trigger(TriggerKind.WATCH_ARTIFACT_CHANGED, "A CIO-relevant Watch artifact is published"),
        Trigger(TriggerKind.SCHEDULED_SWEEP, "A bounded scheduled CIO sweep runs"),
    ),
    allowed_output_kinds=(OutputKind.CIO_SYNTHESIS, OutputKind.ACTION_ITEM, OutputKind.IMPROVEMENT_PROPOSAL),
    reviewer_agent_id="iris",
    scorer_agent_id="darwin",
    maturity_target="Wave-3 shadow CIO synthesis",
    wave="THIRD",
)

_STEPH = ShadowAgentSpec(
    definition=_def(
        "steph",
        "Steph",
        "Senior Portfolio & Wealth Strategist — allocation, rotation, position sizing",
        allowed_job_types=(
            "allocation_review", "wealth_scenario_analysis", "income_sleeve_review",
            "drift_monitoring", "rotation_proposal", "position_sizing",
        ),
        allowed_tools=(
            "portfolio.read", "allocation.read", "income.read", "goals.read",
            "retirement_projection.read", "kb.search", "artifact.write",
        ),
        denied_tools=(
            "trade.authorize", "rebalance.execute", "config.promote",
            "broker.*", "position.*", "order.*",
        ),
        retrieval_required=True,
        enabled=True,
        state=DeploymentState.SHADOW,
        budget=BudgetPolicy(max_model_calls=2, max_tool_calls=14, max_cost_usd=0.03, deadline_seconds=600),
    ),
    summary=(
        "Senior Portfolio Advisor reporting to Alex. Maintains target allocation "
        "framework (asset class, sector, factor, geographic, liquidity buckets). "
        "Continuously compares current book vs target and quantifies drift. "
        "Proposes rotation candidates with clear thesis, expected edge, and risk "
        "contribution. Sizes new ideas relative to existing risk budget and "
        "correlation. Flags near-ready setups for Active Trader desk. Produces "
        "ALLOCATION_REVIEW on cadence set by Alex. Advisory only — cannot execute "
        "rebalances, authorize trades, or change configuration. DISABLED pending "
        "CIO synthesis maturity acceptance."
    ),
    triggers=(
        Trigger(TriggerKind.CIO_SCHEDULED_BRIEF, "A scheduled allocation review window opens"),
        Trigger(TriggerKind.MATERIAL_PORTFOLIO_CHANGE, "A material allocation drift is detected"),
        Trigger(TriggerKind.RESEARCH_REQUEST, "A bounded allocation research request is enqueued"),
    ),
    allowed_output_kinds=(OutputKind.ALLOCATION_REVIEW, OutputKind.IMPROVEMENT_PROPOSAL),
    reviewer_agent_id="iris",
    scorer_agent_id="darwin",
    maturity_target="Wave-3 shadow senior portfolio advisor",
    wave="THIRD",
)

_LEDGER = ShadowAgentSpec(
    definition=_def(
        "ledger",
        "Ledger",
        "Tax & Account-Constraint Specialist — tax-lot and account-constraint critic",
        allowed_job_types=("tax_lot_review", "account_constraint_review", "wash_sale_check"),
        allowed_tools=(
            "tax_lot.read", "holding_period.read", "account_type.read",
            "wash_sale.check", "kb.search", "artifact.write",
        ),
        denied_tools=(
            "trade.execute", "lot.select", "config.promote",
            "broker.*", "order.*",
        ),
        retrieval_required=True,
        enabled=False,
        state=DeploymentState.DESIGNED,
        budget=BudgetPolicy(max_model_calls=2, max_tool_calls=12, max_cost_usd=0.02, deadline_seconds=600),
    ),
    summary=(
        "Tax-lot and account-constraint critic. Reviews tax lots, holding periods, "
        "wash-sale windows, and account-type constraints (taxable vs IRA vs Roth). "
        "Produces advisory tax-lot review artifacts. Cannot execute trades, select "
        "specific lots, or change configuration. DISABLED pending CIO synthesis "
        "maturity acceptance (AGENTS.md: 'not yet operational')."
    ),
    triggers=(
        Trigger(TriggerKind.CIO_SCHEDULED_BRIEF, "A scheduled tax/account review window opens"),
        Trigger(TriggerKind.QUALITY_EXCEPTION, "A tax-lot or account-constraint quality exception is raised"),
    ),
    allowed_output_kinds=(OutputKind.TAX_LOT_REVIEW, OutputKind.IMPROVEMENT_PROPOSAL),
    reviewer_agent_id="iris",
    scorer_agent_id="darwin",
    maturity_target="Wave-3 shadow tax critic",
    wave="THIRD",
)

_MORGAN = ShadowAgentSpec(
    definition=_def(
        "morgan",
        "Morgan",
        "Chief Wealth Officer — total financial life planning",
        allowed_job_types=(
            "wealth_synthesis", "goal_tracking", "liquidity_planning",
            "tax_coordination", "estate_review", "multi_account_coordination",
        ),
        allowed_tools=(
            "portfolio.read", "tax_lot.read", "income.read", "goals.read",
            "retirement_projection.read", "kb.search", "artifact.write",
        ),
        denied_tools=(
            "trade.*", "broker.*", "order.*", "rebalance.execute",
            "config.promote", "position.*",
        ),
        retrieval_required=True,
        enabled=True,
        state=DeploymentState.SHADOW,
        budget=BudgetPolicy(max_model_calls=2, max_tool_calls=14, max_cost_usd=0.03, deadline_seconds=600),
    ),
    summary=(
        "Senior Wealth Advisor reporting to Alex. Mandate: the operator's total "
        "financial life — spending needs, tax location, estate/liquidity planning, "
        "multi-account coordination, and long-term goal tracking. Treats taxable "
        "brokerage, retirement accounts, and cash reserves as one wealth system. "
        "Tracks after-tax expected return and tax drag across the entire book. "
        "Maintains running view of liquidity needs (next 12–24 months) vs investable "
        "assets. Surfaces tax-lot harvesting opportunities, wash-sale risks, and "
        "charitable/gifting windows in coordination with Ledger. Flags when portfolio "
        "risk threatens a stated wealth goal. Produces WEALTH_SYNTHESIS on cadence "
        "set by Alex. Advisory only — cannot execute rebalances, authorize trades, "
        "or change configuration. ENABLED in SHADOW 2026-08-09 — CIO synthesis "
        "maturity at 11/12 gates, producing real advisory output (PFLT disposition, "
        "allocation drift)."
    ),
    triggers=(
        Trigger(TriggerKind.CIO_SCHEDULED_BRIEF, "A scheduled wealth review window opens"),
        Trigger(TriggerKind.MATERIAL_PORTFOLIO_CHANGE, "A material change affecting wealth goals"),
        Trigger(TriggerKind.RESEARCH_REQUEST, "A bounded wealth research request is enqueued"),
    ),
    allowed_output_kinds=(OutputKind.WEALTH_SYNTHESIS, OutputKind.IMPROVEMENT_PROPOSAL),
    reviewer_agent_id="iris",
    scorer_agent_id="darwin",
    maturity_target="Wave-3 shadow senior wealth advisor",
    wave="THIRD",
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
        _VIGIL,
        _ALEX,
        _STEPH,
        _LEDGER,
        _MORGAN,
    )
}

# INITIAL_SHADOW_AGENT_IDS = the enabled SHADOW fleet. argus was authored + enabled
# after the original four; being enabled, it belongs here (not the disabled 2nd wave).
# alex is enabled in SHADOW as Wave 3 — shadow CIO synthesis only, no Telegram, no
# autonomous paid model calls.
INITIAL_SHADOW_AGENT_IDS: tuple[str, ...] = ("sentinel", "darwin", "iris", "reflection", "argus", "vigil", "alex", "steph", "morgan")
SECOND_WAVE_AGENT_IDS: tuple[str, ...] = ("maria", "vega", "risk_agent", "aegis")
THIRD_WAVE_AGENT_IDS: tuple[str, ...] = ("steph", "ledger", "morgan")

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


def third_wave_agents() -> dict[str, ShadowAgentSpec]:
    return {agent_id: FLEET[agent_id] for agent_id in THIRD_WAVE_AGENT_IDS}


def reviewer_scorer_matrix() -> dict[str, dict[str, str]]:
    """The independent reviewer/scorer assignment for every producer."""
    return {
        agent_id: {
            "reviewer": spec.reviewer_agent_id,
            "scorer": spec.scorer_agent_id,
        }
        for agent_id, spec in FLEET.items()
    }
