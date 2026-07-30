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
  production_activation_authorized: boolean | null
  declared_production_activation_authorized: boolean | null
  effective_production_activation_verified: boolean
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

// ── Presentation helpers (pure; front-end only, no backend/data change) ──────
// These derive sort order, tones, and rail state from the existing read-only
// payload so the scoreboard can rank "closest to eligible" and colour-tone
// status without touching the API or its numbers.

export type MaturityTone = 'green' | 'amber' | 'red' | 'slate'
export type MaturityRail = 'favorable' | 'attention' | 'breach' | 'neutral'

/** Sample gate progress 0-100, or null when the sample size is unknown. */
export function samplePct(row: AgentMaturityObservation): number | null {
  const n = row.sample_size
  const req = row.required_sample_size
  if (n === null || req === null || !req) return null
  return Math.max(0, Math.min(100, Math.round((n / req) * 100)))
}

const ELIGIBILITY_ORDER: Record<string, number> = {
  ELIGIBLE_FOR_HUMAN_REVIEW: 0,
  CAPPED_BY_SAMPLE_SIZE: 1,
  HUMAN_REVIEW_REQUIRED: 2,
  INSUFFICIENT_EVIDENCE: 3,
  NOT_ELIGIBLE: 4,
  NOT_RUN: 5,
  UNKNOWN: 6,
  RESTRICTED: 7,
}

/** Rank rows most-actionable first: eligible, then capped (higher sample % first),
 *  then human-review-required, then insufficient/not-run, restricted last. */
export function eligibilityRank(row: AgentMaturityObservation): number {
  const base = ELIGIBILITY_ORDER[row.promotion_eligibility] ?? 8
  const pct = samplePct(row) ?? 0
  return base * 1000 - pct
}

export function eligibilityTone(elig: string): MaturityTone {
  if (elig === 'ELIGIBLE_FOR_HUMAN_REVIEW') return 'green'
  if (elig === 'RESTRICTED') return 'red'
  if (elig === 'CAPPED_BY_SAMPLE_SIZE' || elig === 'HUMAN_REVIEW_REQUIRED') return 'amber'
  return 'slate'
}

export function healthTone(health: string): MaturityTone {
  if (health === 'HEALTHY') return 'green'
  if (health === 'TIMEOUT' || health === 'INVALID_OUTPUT') return 'red'
  if (
    health === 'DEGRADED_FALLBACK' || health === 'STALE_CACHE' ||
    health === 'INCOMPLETE_CONSENSUS' || health === 'MISSING_REVIEWER' ||
    health === 'PROVIDER_UNAVAILABLE'
  ) return 'amber'
  return 'slate'
}

export function lifecycleTone(state: string): MaturityTone {
  if (state === 'OPERATIONAL') return 'green'
  if (state === 'SHADOW') return 'amber'
  if (state === 'RESTRICTED' || state === 'RETOOL') return 'red'
  return 'slate'
}

/** The 3px left-rail semantic for a row. */
export function maturityRail(row: AgentMaturityObservation): MaturityRail {
  if (row.promotion_eligibility === 'ELIGIBLE_FOR_HUMAN_REVIEW') return 'favorable'
  if (row.promotion_eligibility === 'RESTRICTED') return 'breach'
  if (row.review_health === 'TIMEOUT' || row.review_health === 'INVALID_OUTPUT') return 'breach'
  if (
    row.promotion_eligibility === 'CAPPED_BY_SAMPLE_SIZE' ||
    row.promotion_eligibility === 'HUMAN_REVIEW_REQUIRED' ||
    healthTone(row.review_health) === 'amber'
  ) return 'attention'
  return 'neutral'
}

export function needsAttention(row: AgentMaturityObservation): boolean {
  const rail = maturityRail(row)
  return rail === 'attention' || rail === 'breach'
}

/** Fleet-wide mean sample-gate progress (honest 0 when nothing is measured). */
export function fleetGateCoveragePct(rows: AgentMaturityObservation[]): number {
  if (!rows.length) return 0
  const sum = rows.reduce((acc, r) => acc + (samplePct(r) ?? 0), 0)
  return Math.round(sum / rows.length)
}

// ── Front-end-only PREVIEW data ──────────────────────────────────────────────
// Illustrative rows so the redesigned board can be seen populated while the live
// runtime read adapter is unwired (every live row is currently UNKNOWN). This is
// NOT a backend call and NEVER merges with live data; it is watermarked SAMPLE in
// the UI and only shown when the operator explicitly toggles Preview on.

function previewRow(
  over: Partial<AgentMaturityObservation> & { agent_id: string; display_name: string },
): AgentMaturityObservation {
  return {
    schema_version: 'agent-maturity-observation-v1',
    observed_at: '2026-07-30T15:00:00Z',
    agent_id: over.agent_id,
    display_name: over.display_name,
    subsystem: over.subsystem ?? 'agent_runtime',
    agent_kind: over.agent_kind ?? 'reflective',
    environment: over.environment ?? 'LAB',
    declared_lifecycle_state: over.declared_lifecycle_state ?? 'SHADOW',
    effective_authority_state: 'NO_FINANCIAL_AUTHORITY',
    allowed_authorities: [],
    denied_authorities: ['broker', 'production_config', 'operator_2fa'],
    production_activation_authorized: false,
    declared_production_activation_authorized: false,
    effective_production_activation_verified: false,
    activation_evidence_state: 'REPOSITORY_EVIDENCE',
    maturity_framework: 'agent-runtime-mvl',
    maturity_framework_version: 'mvl-v1',
    maturity_score: over.maturity_score ?? null,
    maturity_tier: over.maturity_tier ?? null,
    component_scores: {},
    sample_size: over.sample_size ?? null,
    required_sample_size: over.required_sample_size ?? 100,
    sample_progress_state: over.sample_progress_state ?? 'UNKNOWN',
    sample_cap_reason: over.sample_cap_reason ?? null,
    next_gate_id: over.next_gate_id ?? 'min_artifact_population',
    next_gate_description: over.next_gate_description ?? 'Accumulate reviewed artifact evidence before human review.',
    next_gate_state: over.next_gate_state ?? 'UNKNOWN',
    promotion_eligibility: over.promotion_eligibility ?? 'HUMAN_REVIEW_REQUIRED',
    promotion_authority: 'HUMAN_ONLY',
    automatic_promotion_permitted: false,
    review_provenance: over.review_provenance ?? 'REPOSITORY_EVIDENCE',
    review_health: over.review_health ?? 'NOT_RUN',
    review_model: null,
    review_provider: null,
    review_route: null,
    review_prompt_version: null,
    review_input_hash: null,
    review_response_hash: null,
    last_successful_review_at: over.last_successful_review_at ?? null,
    last_degraded_review_at: over.last_degraded_review_at ?? null,
    last_human_authority_change_at: null,
    last_restriction_or_demotion_at: over.last_restriction_or_demotion_at ?? null,
    freshness_state: over.freshness_state ?? 'CURRENT_REPOSITORY_EVIDENCE',
    source_class: 'REPOSITORY_EVIDENCE',
    evidence_refs: over.evidence_refs ?? ['config/agent_maturity_catalog.json'],
    warnings: over.warnings ?? [],
    operator_checks_required: over.operator_checks_required ?? [],
  }
}

export function previewMaturityPayload(): AgentMaturityPayload {
  const data: AgentMaturityObservation[] = [
    previewRow({
      agent_id: 'sentinel', display_name: 'Sentinel',
      declared_lifecycle_state: 'SHADOW', sample_size: 100, required_sample_size: 100,
      sample_progress_state: 'MEASURED', maturity_score: 78, maturity_tier: 'mature',
      review_health: 'HEALTHY', next_gate_id: 'independent_review_complete', next_gate_state: 'PASSED',
      promotion_eligibility: 'ELIGIBLE_FOR_HUMAN_REVIEW',
      last_successful_review_at: '2026-07-30T09:12:00Z',
    }),
    previewRow({
      agent_id: 'darwin', display_name: 'Darwin',
      declared_lifecycle_state: 'SHADOW', sample_size: 62, required_sample_size: 100,
      sample_progress_state: 'CAPPED_BY_SAMPLE_SIZE', maturity_score: 66,
      review_health: 'HEALTHY', next_gate_id: 'min_artifact_population', next_gate_state: 'CAPPED_BY_SAMPLE_SIZE',
      promotion_eligibility: 'CAPPED_BY_SAMPLE_SIZE', sample_cap_reason: '62/100 reviewed samples',
      last_successful_review_at: '2026-07-30T08:40:00Z',
    }),
    previewRow({
      agent_id: 'iris', display_name: 'Iris',
      declared_lifecycle_state: 'SHADOW', sample_size: 45, required_sample_size: 100,
      sample_progress_state: 'CAPPED_BY_SAMPLE_SIZE', maturity_score: 51,
      review_health: 'DEGRADED_FALLBACK', next_gate_id: 'healthy_review_evidence', next_gate_state: 'INSUFFICIENT_EVIDENCE',
      promotion_eligibility: 'HUMAN_REVIEW_REQUIRED',
      last_degraded_review_at: '2026-07-30T07:55:00Z',
      warnings: ['Review degraded to deterministic fallback; provider unavailable.'],
    }),
    previewRow({
      agent_id: 'vega', display_name: 'Vega',
      declared_lifecycle_state: 'DESIGNED', sample_size: null, required_sample_size: 100,
      sample_progress_state: 'UNKNOWN', review_health: 'NOT_RUN',
      next_gate_id: 'measure_framework_gates', next_gate_state: 'UNKNOWN',
      promotion_eligibility: 'INSUFFICIENT_EVIDENCE',
      operator_checks_required: ['Connect runtime evidence source.'],
    }),
    previewRow({
      agent_id: 'aegis', display_name: 'Aegis',
      declared_lifecycle_state: 'RESTRICTED', sample_size: 30, required_sample_size: 100,
      sample_progress_state: 'CAPPED_BY_SAMPLE_SIZE', review_health: 'STALE_CACHE',
      next_gate_id: 'clear_restriction', next_gate_state: 'FAILED',
      promotion_eligibility: 'RESTRICTED',
      last_restriction_or_demotion_at: '2026-07-29T22:10:00Z',
      warnings: ['Restricted after authority-violation check; review before reinstating.'],
    }),
  ]
  const eligible = data.filter(r => r.promotion_eligibility === 'ELIGIBLE_FOR_HUMAN_REVIEW').length
  const capped = data.filter(r => r.promotion_eligibility === 'CAPPED_BY_SAMPLE_SIZE').length
  const unverified = data.filter(r => r.freshness_state.includes('UNVERIFIED')).length
  return {
    contract: 'agent-maturity-read-api-v1 (PREVIEW)',
    schema_version: 'agent-maturity-observation-v1',
    generated_at: '2026-07-30T15:00:00Z · SAMPLE',
    freshness: 'PREVIEW',
    source_availability: {},
    unverified_source_warnings: [],
    read_only: true,
    authority: {},
    summary: {
      total_agents: data.length,
      by_lifecycle_state: {},
      by_authority_state: {},
      by_gate_state: {},
      by_review_health: {},
      sample_size_capped_agents: capped,
      eligible_for_human_review: eligible,
      unverified_runtime_status: unverified,
      frameworks: ['agent-runtime-mvl'],
    },
    data,
    evidence_refs: [],
  }
}

export function previewMaturityView(): ResolvedAgentMaturityView {
  return {
    state: 'CONNECTED',
    payload: previewMaturityPayload(),
    detail: 'PREVIEW - illustrative sample data, not live.',
  }
}
