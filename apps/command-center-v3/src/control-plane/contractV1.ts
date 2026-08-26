/** ControlPlane@v1.0.0 frozen types. Integrator-owned. Do not infer states here. */

export const CONTROL_PLANE_CONTRACT_VERSION = 'ControlPlane@v1.0.0' as const

export type RuntimeStatus =
  | 'LIVE_EVENT_DRIVEN'
  | 'LIVE_SCHEDULED'
  | 'CALLABLE_ONLY'
  | 'EXPECTED_IDLE'
  | 'SHADOW'
  | 'DISABLED'
  | 'BROKEN'

export type EvidenceClass =
  | 'SOURCE_ONLY'
  | 'UNIT'
  | 'INTEGRATION'
  | 'HISTORICAL_REPLAY'
  | 'GOLDEN_SHADOW'
  | 'SHADOW'
  | 'DRY_RUN'
  | 'OPERATOR_REQUESTED_LIVE'
  | 'CURRENT_SMOKE'
  | 'NATURAL_CURRENT'
  | 'NATURAL_LONGITUDINAL'

export type WorkflowNodeKind =
  | 'event'
  | 'entity'
  | 'materiality'
  | 'graph'
  | 'research'
  | 'specialist'
  | 'council'
  | 'cio'
  | 'notification'
  | 'checkpoint'
  | 'outcome'
  | 'learning'

export interface ControlPlaneEnvelope<T> {
  schema: typeof CONTROL_PLANE_CONTRACT_VERSION
  page: string
  as_of: string
  evidence_class: EvidenceClass
  source_sha: string
  data_quality: string
  authority: 'READ_ONLY_ADVISORY'
  memory_behavior_influence: 0
  computes_cio_decisions: false
  computes_agent_state: false
  computes_maturity: false
  computes_notification_eligibility: false
  payload: T
  financial_action: false
}

export interface AgentRuntimeStatus {
  agent_id: string
  role: string
  state: RuntimeStatus
  trigger_classes: string[]
  last_wake: string | null
  wake_reason: string | null
  current_task: string | null
  queue: number
  last_artifact_id: string | null
  last_success: string | null
  last_failure: string | null
  route: string | null
  model: string | null
  cost: number
  next_eligible_wake: string | null
  evidence_class: EvidenceClass
}

export interface WorkflowNode {
  node_id: string
  kind: WorkflowNodeKind
  label: string
  status: string
  entity_refs: string[]
  artifact_refs: string[]
  started_at: string | null
  ended_at: string | null
  evidence_class: EvidenceClass
}

export interface WorkflowEdge {
  edge_id: string
  from_node: string
  to_node: string
  event_id: string | null
  causal_reason: string
}

export interface WorkflowTrace {
  trace_id: string
  status: string
  evidence_class: EvidenceClass
  source_sha: string
  nodes: WorkflowNode[]
  edges: WorkflowEdge[]
  started_at: string
  updated_at: string
  failure_reason: string | null
}

export interface ResearchAttentionStatus {
  subject_id: string
  state: string
  why_now: string
  why_not_now: string
  freshness: string
  research_gap_id: string | null
  cadence: string
  route: string
  cost: number
  yield: string
  universe: string
  active_set: boolean
  due: boolean
  event_woken: boolean
  source_usage: Record<string, number>
  llm_eligibility: string
  evidence_class: EvidenceClass
}

export interface CanonicalStoreStatus {
  logical_store: string
  physical_root: string
  writer: string
  readers: string[]
  schema_version: string
  last_write: string | null
  freshness: string
  record_count: number | null
  duplicate_count: number | null
  quarantine_count: number | null
  orphan_count: number | null
  source_sha: string | null
  authority: string
}

export interface IdentityStatus {
  entity_id: string
  issuer: string | null
  security: string | null
  listing: string | null
  aliases: string[]
  identifiers: Record<string, string | null>
  state: 'CONFIRMED' | 'CANDIDATE' | 'UNRESOLVED_WITH_REASON'
  unresolved_reason: string | null
  source: string
  as_of: string
}

export interface NotificationStatus {
  notification_id: string
  class: string
  decision: string
  canary: boolean
  interdict: boolean
  renderer: string
  rendered_at: string | null
  delivered_at: string | null
  receipt_at: string | null
  dedupe_key: string | null
  suppression_reason: string | null
  evidence_class: EvidenceClass
}

export interface LearningEvidenceStatus {
  item_id: string
  kind: string
  status: string
  score: number | null
  evidence_class: EvidenceClass
  proof_refs: string[]
  limiting_factor: string
  next_proof: string
}

export interface MaturityDimension {
  dimension: string
  score: number
  evidence_class: EvidenceClass
  proof_refs: string[]
  limiting_factor: string
  next_proof: string
}

export interface AuditCapabilityClaim {
  claim_id: string
  claim: string
  implementation_ref: string
  test_ref: string
  evidence_ref: string
  evidence_class: EvidenceClass
  limitations: string
  reproduction_command: string
}
