export interface AgentOperationsEntry {
  agent_id: string
  display_name: string
  enabled: boolean
  lifecycle: string
  role: string
  summary: string
  trigger_kind: string | null
  trigger_description: string | null
  triggers: Array<{ kind: string; description: string }>
  interacts_with: string[]
  allowed_outputs: string[]
  reviewer_agent_id: string | null
  scorer_agent_id: string | null
  subsystem?: string
  owner?: string | null
  allowed_tools?: string[]
  denied_tools?: string[]
  retrieval_required?: boolean
  autonomy: {
    execution: string
    capability: string
    event_queue_state: string
    per_run_operator_approval_required: boolean | null
    human_review_scope: string
    self_scheduling_permitted: boolean
    financial_authority: 'NONE'
  }
  schedule_mode: string
  designed_schedule: string
  configured_calendar: string | null
  timer_unit: string | null
  timer_state: 'OPERATOR_CHECK_REQUIRED' | 'NOT_INSTALLED' | 'NOT_APPLICABLE' | 'INACTIVE' | 'ACTIVE'
  timer_scope: 'SYSTEM' | 'USER' | null
  last_timer_run_at: string | null
  next_timer_at: string | null
  last_dispatch_at: string | null
  last_dispatch_outcome: string | null
  last_run_id: string | null
  manual_run_command: string | null
  timer_probe_hint: string | null
  source_state?: 'READY' | 'BLOCKED_SOURCE' | 'STALE_SOURCE' | 'NOT_CONFIGURED'
  queue_depth?: number
  oldest_queued_source_at?: string | null
  last_trigger_at?: string | null
  last_trigger_kind?: string | null
  openclaw_persona_registered?: boolean
  openclaw_persona_model?: string | null
  openclaw_persona_soul_exists?: boolean
  shadow_dispatch_model?: string | null
}

export interface OpenClawPersonaRow {
  persona_id: string
  fleet_agent_id?: string | null
  fleet_subsystem?: string | null
  registered?: boolean
  model?: string | null
  soul_exists?: boolean
  workspace?: string | null
}

export interface PromotionFrameworkMeta {
  min_artifact_population: number
  gate_source: string
  promotion_authority: string
  automatic_operational: boolean
  note: string
}

export interface AgentOperationsPayload {
  contract: string
  observed_at: string
  read_only: true
  timer_probe_enabled: boolean
  promotion_framework?: PromotionFrameworkMeta
  shadow_dispatch_model?: string | null
  openclaw_personas?: OpenClawPersonaRow[]
  health_monitor: {
    state: 'HEALTHY' | 'DEGRADED' | 'NOT_INSTALLED' | 'STALE' | 'INVALID' | 'UNKNOWN'
    last_checked_at: string | null
    age_seconds?: number | null
    detail: string
  }
  sources?: Array<{ source_id: string; state: string; detail: string; last_observed_at?: string | null }>
  queue_posture?: { available: boolean; per_agent: Record<string, unknown>; producer_last_at?: string | null }
  schedule_manifest?: string | null
  agents: AgentOperationsEntry[]
}

export interface ResolvedOperationsView {
  state: 'CONNECTED' | 'UNAVAILABLE'
  payload: AgentOperationsPayload | null
  detail: string
}

export async function resolveAgentRuntimeOperations(
  agentId?: string,
  fetchImpl?: typeof fetch,
): Promise<ResolvedOperationsView> {
  const doFetch = fetchImpl ?? (typeof fetch !== 'undefined' ? fetch : undefined)
  if (!doFetch) return { state: 'UNAVAILABLE', payload: null, detail: 'No fetch available.' }
  const qs = agentId ? `?agent_id=${encodeURIComponent(agentId)}` : ''
  try {
    const response = await doFetch(`/api/v3/agent-runtime/operations${qs}`, {
      method: 'GET',
      headers: { accept: 'application/json' },
    })
    if (!response.ok) return { state: 'UNAVAILABLE', payload: null, detail: `Operations HTTP ${response.status}` }
    const payload = await response.json() as AgentOperationsPayload
    if (payload?.read_only !== true || !Array.isArray(payload.agents)) {
      return { state: 'UNAVAILABLE', payload: null, detail: 'Invalid operations payload.' }
    }
    return { state: 'CONNECTED', payload, detail: 'Operations posture loaded.' }
  } catch (err) {
    return { state: 'UNAVAILABLE', payload: null, detail: String((err as Error)?.message ?? err) }
  }
}

export function operationsByAgent(payload: AgentOperationsPayload | null): Map<string, AgentOperationsEntry> {
  const m = new Map<string, AgentOperationsEntry>()
  for (const row of payload?.agents ?? []) m.set(row.agent_id, row)
  return m
}
