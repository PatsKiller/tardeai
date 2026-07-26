export type AgentLifecycle = 'DESIGNED' | 'SHADOW' | 'OPERATIONAL' | 'RESTRICTED' | 'RETOOL' | 'RETIRED'
export type EvidenceState = 'FIXTURE' | 'LAB' | 'SHADOW' | 'PRODUCTION' | 'UNAVAILABLE'

export interface AgentBudget {
  maxModelCalls: number
  maxToolCalls: number
  maxCostUsd: number
  deadlineSeconds: number
}

export interface AgentRuntimeDefinition {
  agentId: string
  displayName: string
  role: string
  objective: string
  owner: string
  version: string
  lifecycle: AgentLifecycle
  enabled: boolean
  retrievalRequired: boolean
  trigger: string
  artifact: string
  reviewer: string
  scorer: string
  allowedTools: string[]
  deniedTools: string[]
  budget: AgentBudget
  limitations: string[]
  disableControl: string
  rollbackControl: string
  docsPath: string
}

export interface AgentRuntimeSnapshot {
  contract: 'agent-runtime-monitoring-v1'
  source: EvidenceState
  asOf: string
  adapterState: 'NOT_CONNECTED' | 'FIXTURE_ONLY' | 'CONNECTED_READ_ONLY'
  runs: {
    total: number
    running: number
    blocked: number
    failed: number
    cancelled: number
    deadlineExceeded: number
    stale: number
  }
  evidence: {
    artifacts: number
    unreviewed: number
    unscored: number
    cases: number
    lessons: number
  }
}

export const AGENT_RUNTIME_CONTRACT = 'agent-runtime-monitoring-v1' as const
export const AGENT_RUNTIME_SOURCE_AS_OF = '2026-07-25T22:30:00Z'

export const DENIED_AUTHORITIES = [
  'Broker writes',
  'Order submission or modification',
  'Account or position writes',
  'Approval mutation',
  '2FA requests',
  'Production database writes',
  'Production config promotion',
  'Raw secret access',
  'Service or scheduler control',
] as const

const zeroCost = (deadlineSeconds: number, maxToolCalls: number, maxModelCalls = 0): AgentBudget => ({
  maxModelCalls,
  maxToolCalls,
  maxCostUsd: 0,
  deadlineSeconds,
})

export const AGENT_RUNTIME_CATALOG: AgentRuntimeDefinition[] = [
  {
    agentId: 'sentinel', displayName: 'Sentinel', lifecycle: 'SHADOW', enabled: true, version: '1.0.0-shadow', owner: 'architecture-owner',
    role: 'Decision integrity and contradiction review', objective: 'Challenge Watch artifacts after deterministic validation without altering the sovereign decision.',
    retrievalRequired: true, trigger: 'Validated Watch artifact or known-bad fixture', artifact: 'sentinel_integrity_review_v1', reviewer: 'independent critic or operator', scorer: 'darwin',
    allowedTools: ['kb.search', 'kb.get_case', 'ticket.read', 'validator.read', 'artifact.write', 'quarantine.stage'],
    deniedTools: ['broker.*', 'order.*', 'approval.*', '2fa.*', 'config.promote'], budget: zeroCost(360, 12, 3),
    limitations: ['No production persistence connected', 'No authority to edit or release a ticket', 'MVL population acceptance not complete'],
    disableControl: 'Disable sentinel in the versioned agent registry.', rollbackControl: 'Restore the prior registry and prompt contract.', docsPath: 'docs/agent_runtime/AGENT_HANDBOOK.md#sentinel',
  },
  {
    agentId: 'darwin', displayName: 'Darwin', lifecycle: 'SHADOW', enabled: true, version: '1.0.0-shadow', owner: 'architecture-owner',
    role: 'Outcome joins, scoring, and calibration evidence', objective: 'Score immutable artifacts against deterministic outcomes without promoting policy.',
    retrievalRequired: false, trigger: 'Artifact outcome becomes available', artifact: 'darwin_score_v1', reviewer: 'operator or score-policy reviewer', scorer: 'deterministic score policy',
    allowedTools: ['artifact.read', 'outcome.read', 'case.read', 'score.write'], deniedTools: ['artifact.write', 'lesson.ratify', 'config.promote'], budget: zeroCost(600, 12),
    limitations: ['Outcome adapter not connected', 'No automatic promotion', 'MVL 95% scoring gate not measured'], disableControl: 'Disable darwin in the registry.', rollbackControl: 'Revert score-policy version.', docsPath: 'docs/agent_runtime/AGENT_HANDBOOK.md#darwin',
  },
  {
    agentId: 'iris', displayName: 'Iris', lifecycle: 'SHADOW', enabled: true, version: '1.0.0-shadow', owner: 'architecture-owner',
    role: 'Knowledge curation and lesson lifecycle review', objective: 'Review candidate lessons, contradictions, provenance, and temporal validity.',
    retrievalRequired: true, trigger: 'Candidate lesson, retrieval audit, or contradiction', artifact: 'iris_lesson_review_v1', reviewer: 'operator', scorer: 'darwin',
    allowedTools: ['kb.search', 'kb.get_lesson', 'kb.get_case', 'lesson_review.write', 'contradiction.write'], deniedTools: ['lesson.ratify', 'config.promote', 'hypothesis.promote'], budget: zeroCost(900, 20, 2),
    limitations: ['Ratification remains human-controlled', 'KB write adapter pending'], disableControl: 'Disable iris in the registry.', rollbackControl: 'Restore prior lesson-review contract.', docsPath: 'docs/agent_runtime/AGENT_HANDBOOK.md#iris',
  },
  {
    agentId: 'reflection', displayName: 'Nightly Reflection', lifecycle: 'SHADOW', enabled: true, version: '1.0.0-shadow', owner: 'architecture-owner',
    role: 'Case-to-lesson and hypothesis candidate generation', objective: 'Convert bounded cases and exceptions into candidates without changing production behavior.',
    retrievalRequired: true, trigger: 'Bounded nightly case and exception batch', artifact: 'reflection_candidate_bundle_v1', reviewer: 'iris or operator', scorer: 'darwin',
    allowedTools: ['kb.search', 'case.read', 'exception.read', 'lesson_candidate.write', 'hypothesis.register'], deniedTools: ['lesson.ratify', 'hypothesis.promote', 'config.promote'], budget: zeroCost(1200, 20, 3),
    limitations: ['No schedule activated', 'No authoritative case adapter connected'], disableControl: 'Keep the reflection trigger disabled.', rollbackControl: 'Remove staged candidates and restore prior prompt version.', docsPath: 'docs/agent_runtime/AGENT_HANDBOOK.md#nightly-reflection',
  },
  {
    agentId: 'argus', displayName: 'Argus', lifecycle: 'DESIGNED', enabled: false, version: '1.0.0-designed', owner: 'architecture-owner',
    role: 'Population-wide integrity scan', objective: 'Detect cross-card contradictions and drift without silently repairing packets.', retrievalRequired: true,
    trigger: 'Post-publication population scan', artifact: 'argus_population_exception_v1', reviewer: 'operator or aegis', scorer: 'darwin',
    allowedTools: ['watch.read', 'artifact.read', 'exception.write'], deniedTools: ['packet.write', 'broker.*', 'config.promote'], budget: zeroCost(900, 30, 1),
    limitations: ['Phase 2 only', 'No scheduled population scan'], disableControl: 'Remain disabled in the registry.', rollbackControl: 'Remove staged exceptions from the fixture adapter.', docsPath: 'docs/agent_runtime/AGENT_HANDBOOK.md#argus',
  },
  {
    agentId: 'maria', displayName: 'Maria', lifecycle: 'DESIGNED', enabled: false, version: '1.0.0-designed', owner: 'research-owner',
    role: 'Fundamental and catalyst research', objective: 'Produce evidence-bound fundamental research and counter-thesis artifacts.', retrievalRequired: true,
    trigger: 'Research request or material catalyst change', artifact: 'maria_research_artifact_v1', reviewer: 'sentinel or independent research critic', scorer: 'darwin',
    allowedTools: ['kb.search', 'fundamentals.read', 'events.read', 'research.write'], deniedTools: ['ticket.write', 'broker.*', 'config.promote'], budget: zeroCost(1200, 24, 3),
    limitations: ['Durable integration deferred'], disableControl: 'Remain disabled in the MVL registry.', rollbackControl: 'Restore prior research prompt/version.', docsPath: 'docs/agent_runtime/AGENT_HANDBOOK.md#maria',
  },
  {
    agentId: 'vega', displayName: 'Vega', lifecycle: 'DESIGNED', enabled: false, version: '1.0.0-designed', owner: 'technical-research-owner',
    role: 'Technical structure and setup lifecycle', objective: 'Interpret deterministic technical features without inventing price facts.', retrievalRequired: true,
    trigger: 'Closed-bar technical-state change', artifact: 'vega_structure_review_v1', reviewer: 'sentinel', scorer: 'darwin', allowedTools: ['kb.search', 'technicals.read', 'artifact.write'],
    deniedTools: ['market_fact.write', 'ticket.release', 'broker.*'], budget: zeroCost(600, 16, 2), limitations: ['Waits for stable technical artifacts'], disableControl: 'Remain disabled.', rollbackControl: 'Revert technical review contract.', docsPath: 'docs/agent_runtime/AGENT_HANDBOOK.md#vega',
  },
  {
    agentId: 'pulse', displayName: 'Pulse', lifecycle: 'DESIGNED', enabled: false, version: '1.0.0-designed', owner: 'microstructure-owner',
    role: 'Moomoo microstructure interpretation', objective: 'Review deterministic Level 2 and tape features outside latency-critical paths.', retrievalRequired: true,
    trigger: 'Material microstructure feature change', artifact: 'pulse_microstructure_review_v1', reviewer: 'sentinel', scorer: 'darwin', allowedTools: ['kb.search', 'microstructure.read', 'replay.read', 'artifact.write'],
    deniedTools: ['raw_tick.stream', 'broker.*', 'order.*'], budget: zeroCost(300, 12, 1), limitations: ['Blocked on Moomoo feature plane'], disableControl: 'Remain disabled.', rollbackControl: 'Remove feature-plane integration.', docsPath: 'docs/agent_runtime/AGENT_HANDBOOK.md#pulse',
  },
  {
    agentId: 'steph', displayName: 'Steph', lifecycle: 'DESIGNED', enabled: false, version: '1.0.0-designed', owner: 'portfolio-owner',
    role: 'Portfolio and account allocation', objective: 'Stage allocation proposals from deterministic account and position facts.', retrievalRequired: true,
    trigger: 'Portfolio review or allocation request', artifact: 'steph_allocation_review_v1', reviewer: 'guardian risk and operator', scorer: 'darwin', allowedTools: ['kb.search', 'portfolio.read', 'account.read', 'proposal.stage'],
    deniedTools: ['account.write', 'position.write', 'broker.*'], budget: zeroCost(900, 20, 2), limitations: ['Durable integration deferred'], disableControl: 'Remain disabled.', rollbackControl: 'Discard staged allocation artifacts.', docsPath: 'docs/agent_runtime/AGENT_HANDBOOK.md#steph',
  },
  {
    agentId: 'risk_agent', displayName: 'Guardian Risk', lifecycle: 'DESIGNED', enabled: false, version: '1.0.0-designed', owner: 'risk-owner',
    role: 'Portfolio and ticket risk critic', objective: 'Challenge concentration, event, liquidity, and scenario risk without overriding central risk.', retrievalRequired: true,
    trigger: 'Proposal-eligible artifact or portfolio-risk change', artifact: 'guardian_risk_review_v1', reviewer: 'operator', scorer: 'darwin', allowedTools: ['kb.search', 'risk.read', 'portfolio.read', 'review.write'],
    deniedTools: ['risk.override', 'broker.*', 'approval.*'], budget: zeroCost(360, 16, 2), limitations: ['Central risk remains deterministic'], disableControl: 'Remain disabled.', rollbackControl: 'Restore previous risk-review contract.', docsPath: 'docs/agent_runtime/AGENT_HANDBOOK.md#guardian-risk',
  },
  {
    agentId: 'tax_agent', displayName: 'Ledger Tax', lifecycle: 'DESIGNED', enabled: false, version: '1.0.0-designed', owner: 'tax-owner',
    role: 'Tax, wash-sale, and account constraints', objective: 'Surface evidence-backed tax and account constraints without executing trades.', retrievalRequired: true,
    trigger: 'Tax-sensitive proposal or lot review', artifact: 'ledger_tax_review_v1', reviewer: 'operator', scorer: 'darwin', allowedTools: ['kb.search', 'tax_lots.read', 'account.read', 'review.write'],
    deniedTools: ['tax_trade.execute', 'broker.*', 'account.write'], budget: zeroCost(900, 16, 2), limitations: ['Lot and basis adapters not connected'], disableControl: 'Remain disabled.', rollbackControl: 'Discard staged tax reviews.', docsPath: 'docs/agent_runtime/AGENT_HANDBOOK.md#ledger-tax',
  },
  {
    agentId: 'hermes', displayName: 'Hermes', lifecycle: 'DESIGNED', enabled: false, version: '1.0.0-designed', owner: 'research-owner',
    role: 'Hypothesis discovery and experiment design', objective: 'Register preregistered hypotheses and experiments without promotion authority.', retrievalRequired: true,
    trigger: 'Scored anomaly or research request', artifact: 'hermes_hypothesis_v1', reviewer: 'darwin and operator', scorer: 'darwin', allowedTools: ['kb.search', 'case.read', 'score.read', 'hypothesis.register', 'experiment_plan.write'],
    deniedTools: ['hypothesis.promote', 'config.promote', 'config.activate'], budget: zeroCost(1200, 20, 3), limitations: ['Activation deferred until KB and Darwin evidence'], disableControl: 'Remain disabled.', rollbackControl: 'Discard staged hypotheses.', docsPath: 'docs/agent_runtime/AGENT_HANDBOOK.md#hermes',
  },
  {
    agentId: 'aegis', displayName: 'Aegis', lifecycle: 'DESIGNED', enabled: false, version: '1.0.0-designed', owner: 'reliability-owner',
    role: 'Incident and reliability investigation', objective: 'Create immutable incident cases and remediation proposals without applying fixes.', retrievalRequired: true,
    trigger: 'Runtime incident or repeated exception', artifact: 'aegis_incident_case_v1', reviewer: 'operator', scorer: 'darwin', allowedTools: ['kb.search', 'incident.read', 'logs.read', 'case.write', 'remediation.stage'],
    deniedTools: ['shell.*', 'systemd.*', 'production.*'], budget: zeroCost(1800, 30, 3), limitations: ['Blocked on durable case pipeline'], disableControl: 'Remain disabled.', rollbackControl: 'Discard staged remediation proposals.', docsPath: 'docs/agent_runtime/AGENT_HANDBOOK.md#aegis',
  },
  {
    agentId: 'alex', displayName: 'Alex', lifecycle: 'DESIGNED', enabled: false, version: '1.0.0-designed', owner: 'cio-owner',
    role: 'CIO synthesis for unresolved trade-offs', objective: 'Present unresolved evidence and trade-offs after lower layers complete.', retrievalRequired: true,
    trigger: 'Escalated disagreement after deterministic and specialist review', artifact: 'alex_cio_synthesis_v1', reviewer: 'operator', scorer: 'darwin', allowedTools: ['kb.search', 'artifact.read', 'review.read', 'synthesis.write'],
    deniedTools: ['decision.override', 'broker.*', 'approval.*'], budget: zeroCost(900, 20, 2), limitations: ['Deferred until lower layers are reliable'], disableControl: 'Remain disabled.', rollbackControl: 'Discard synthesis artifact.', docsPath: 'docs/agent_runtime/AGENT_HANDBOOK.md#alex',
  },
  {
    agentId: 'concierge', displayName: 'Concierge', lifecycle: 'DESIGNED', enabled: false, version: '1.0.0-designed', owner: 'operator-experience-owner',
    role: 'Governed OpenClaw operator interface', objective: 'Expose status, explain, cancel, resume, and replay through governed tools only.', retrievalRequired: false,
    trigger: 'Operator command', artifact: 'concierge_operator_response_v1', reviewer: 'operator', scorer: 'darwin', allowedTools: ['run.status', 'run.cancel', 'run.resume', 'artifact.explain'],
    deniedTools: ['shell.exec', 'prod_db.write', 'broker.submit', 'config.promote'], budget: zeroCost(60, 8), limitations: ['Governed tool integration not activated'], disableControl: 'Remain disabled.', rollbackControl: 'Remove OpenClaw route binding.', docsPath: 'docs/agent_runtime/AGENT_HANDBOOK.md#concierge',
  },
  {
    agentId: 'atlas', displayName: 'Atlas', lifecycle: 'DESIGNED', enabled: false, version: '1.0.0-designed', owner: 'architecture-owner',
    role: 'General durable-workflow orchestration', objective: 'Coordinate bounded workflows only after the MVL proves durable evidence and utility.', retrievalRequired: true,
    trigger: 'Deferred', artifact: 'atlas_workflow_state_v1', reviewer: 'operator', scorer: 'darwin', allowedTools: ['run.create', 'run.status', 'handoff.stage'],
    deniedTools: ['broker.*', 'order.*', 'production.*', 'config.promote'], budget: zeroCost(1200, 30, 2), limitations: ['Explicitly deferred until MVL acceptance'], disableControl: 'Remain disabled.', rollbackControl: 'Remove orchestrator route and staged runs.', docsPath: 'docs/agent_runtime/AGENT_HANDBOOK.md#atlas',
  },
]

export const AGENT_RUNTIME_SNAPSHOT: AgentRuntimeSnapshot = {
  contract: AGENT_RUNTIME_CONTRACT,
  source: 'FIXTURE',
  asOf: AGENT_RUNTIME_SOURCE_AS_OF,
  adapterState: 'FIXTURE_ONLY',
  runs: { total: 0, running: 0, blocked: 0, failed: 0, cancelled: 0, deadlineExceeded: 0, stale: 0 },
  evidence: { artifacts: 0, unreviewed: 0, unscored: 0, cases: 0, lessons: 0 },
}

export function validateAgentRuntimeCatalog(catalog: AgentRuntimeDefinition[] = AGENT_RUNTIME_CATALOG): string[] {
  const issues: string[] = []
  const seen = new Set<string>()
  for (const agent of catalog) {
    if (seen.has(agent.agentId)) issues.push(`duplicate agent id: ${agent.agentId}`)
    seen.add(agent.agentId)
    if (!agent.owner || !agent.version || !agent.objective || !agent.artifact) issues.push(`${agent.agentId}: incomplete definition`)
    if (!agent.disableControl || !agent.rollbackControl) issues.push(`${agent.agentId}: missing disable or rollback control`)
    if (agent.lifecycle === 'OPERATIONAL') issues.push(`${agent.agentId}: OPERATIONAL is unsupported before acceptance evidence`)
    if (agent.enabled && agent.lifecycle !== 'SHADOW') issues.push(`${agent.agentId}: enabled agents must remain SHADOW in this tranche`)
    if (agent.allowedTools.some(tool => /^(broker|order|trade|execution|approval|2fa|production|shell|systemd)\./i.test(tool))) {
      issues.push(`${agent.agentId}: forbidden authority appears in allowed tools`)
    }
  }
  return issues
}

export function summarizeAgentRuntime(catalog: AgentRuntimeDefinition[] = AGENT_RUNTIME_CATALOG) {
  const lifecycle = catalog.reduce<Record<AgentLifecycle, number>>((acc, agent) => {
    acc[agent.lifecycle] += 1
    return acc
  }, { DESIGNED: 0, SHADOW: 0, OPERATIONAL: 0, RESTRICTED: 0, RETOOL: 0, RETIRED: 0 })
  return {
    total: catalog.length,
    enabled: catalog.filter(agent => agent.enabled).length,
    retrievalRequired: catalog.filter(agent => agent.retrievalRequired).length,
    lifecycle,
    catalogIssues: validateAgentRuntimeCatalog(catalog),
  }
}
