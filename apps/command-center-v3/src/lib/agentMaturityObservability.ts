export type ReviewHealth =
  | 'HEALTHY'
  | 'DEGRADED_FALLBACK'
  | 'TIMEOUT'
  | 'STALE_CACHE'
  | 'MISSING_REVIEWER'
  | 'INCOMPLETE_CONSENSUS'
  | 'PROVIDER_UNAVAILABLE'
  | 'INVALID_OUTPUT'
  | 'NOT_RUN'
  | 'UNKNOWN'

export interface AgentMaturityObservation {
  schema_version: string
  observed_at: string
  agent_id: string
  display_name: string
  subsystem: string
  agent_kind: string
  environment: string
  declared_lifecycle_state: string
  effective_authority_state: string
  allowed_authorities: string[]
  denied_authorities: string[]
  production_activation_authorized: boolean
  activation_evidence_state: string
  maturity_framework: string
  maturity_framework_version: string | null
  maturity_score: number | null
  maturity_tier: string | null
  component_scores: Record<string, unknown>
  sample_size: number | null
  required_sample_size: number | null
  sample_progress_state: string
  sample_cap_reason: string | null
  next_gate_id: string | null
  next_gate_description: string | null
  next_gate_state: string
  promotion_eligibility: string
  promotion_authority: 'HUMAN_ONLY'
  automatic_promotion_permitted: false
  review_provenance: string
  review_health: ReviewHealth
  review_model: string | null
  review_provider: string | null
  review_route: string | null
  review_prompt_version: string | null
  review_input_hash: string | null
  review_response_hash: string | null
  last_successful_review_at: string | null
  last_degraded_review_at: string | null
  last_human_authority_change_at: string | null
  last_restriction_or_demotion_at: string | null
  freshness_state: string
  source_class: string
  evidence_refs: string[]
  warnings: string[]
  operator_checks_required: string[]
}

export interface AgentMaturityPayload {
  contract: string
  schema_version: string
  generated_at: string
  freshness: string
  source_availability: Record<string, string>
  unverified_source_warnings: string[]
  read_only: true
  authority: Record<string, boolean>
  summary: {
    total_agents: number
    by_lifecycle_state: Record<string, number>
    by_authority_state: Record<string, number>
    by_gate_state: Record<string, number>
    by_review_health: Record<string, number>
    sample_size_capped_agents: number
    eligible_for_human_review: number
    unverified_runtime_status: number
    frameworks: string[]
  }
  data: AgentMaturityObservation[]
  evidence_refs: string[]
}

export interface ResolvedAgentMaturityView {
  state: 'CONNECTED' | 'NOT_CONNECTED' | 'UNAVAILABLE'
  payload: AgentMaturityPayload | null
  detail: string
}

export function maturityHealthLabel(health: string): string {
  if (health === 'DEGRADED_FALLBACK') return 'DEGRADED - DETERMINISTIC FALLBACK'
  if (health === 'STALE_CACHE') return 'STALE CACHED REVIEW'
  return health.replace(/_/g, ' ')
}

export async function resolveAgentMaturityView(fetchImpl?: typeof fetch): Promise<ResolvedAgentMaturityView> {
  const doFetch = fetchImpl ?? (typeof fetch !== 'undefined' ? fetch : undefined)
  if (!doFetch) return { state: 'UNAVAILABLE', payload: null, detail: 'No fetch implementation available.' }
  try {
    const response = await doFetch('/api/v3/agent-maturity', { method: 'GET', headers: { accept: 'application/json' } })
    if (response.status === 503) return { state: 'NOT_CONNECTED', payload: null, detail: 'Maturity read API is not connected.' }
    if (!response.ok) return { state: 'UNAVAILABLE', payload: null, detail: `Maturity read API returned HTTP ${response.status}.` }
    const payload = await response.json() as AgentMaturityPayload
    if (payload?.read_only !== true || !Array.isArray(payload.data)) {
      return { state: 'UNAVAILABLE', payload: null, detail: 'Maturity response was not a valid read-only payload.' }
    }
    if (payload.authority && Object.values(payload.authority).some(Boolean)) {
      return { state: 'UNAVAILABLE', payload: null, detail: 'Maturity API advertised non-zero authority; refusing to trust it.' }
    }
    if (payload.data.some(row => row.automatic_promotion_permitted !== false || row.promotion_authority !== 'HUMAN_ONLY')) {
      return { state: 'UNAVAILABLE', payload: null, detail: 'Maturity API returned an unsafe promotion contract.' }
    }
    return { state: 'CONNECTED', payload, detail: 'Read-only maturity observations loaded.' }
  } catch (err) {
    return { state: 'UNAVAILABLE', payload: null, detail: `Maturity API unreachable: ${String((err as Error)?.message ?? err)}` }
  }
}
