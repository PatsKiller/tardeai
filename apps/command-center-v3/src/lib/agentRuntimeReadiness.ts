export interface AgentRuntimeReadinessWiring {
  read_api: {
    state: 'GATE_OFF' | 'MISSING_DSN' | 'NOT_CONNECTED' | 'CONNECTED'
    gate_enabled: boolean
    dsn_configured: boolean
  }
  dispatch: {
    state: 'MISSING_OPERATOR_AUTH' | 'MISSING_QUEUE_MODULE' | 'MISSING_DSN' | 'MISSING_PROVIDER' | 'KILL_SWITCH_OFF' | 'WIRED'
    operator_auth: boolean
    queue_module_configured: boolean
    dispatch_dsn_configured: boolean
    provider_module_configured: boolean
    kill_switch_present: boolean
  }
}

export interface AgentRuntimeReadinessBlocker {
  agent_id: string
  display_name: string
  source_class: string
  next_gate_state: string
  next_gate_id: string | null
  next_step_hint?: string
  promotion_eligibility: string
  declared_lifecycle_state: string
  review_health: string
  sample_size: number | null
  required_sample_size: number | null
  dispatch_operable?: boolean
}

export interface AgentRuntimeReadinessPayload {
  contract: string
  observed_at: string
  read_only: true
  wiring: AgentRuntimeReadinessWiring
  fleet_summary: {
    wave1_agents: number
    wave2_agents: number
    catalog_only_agents: number
    observability_agents: number
    runtime_evidence_agents: number
    total_agents: number
  }
  agents: AgentRuntimeReadinessBlocker[]
  runbook_refs: string[]
  manual_run_command_template: string
}

export interface ResolvedReadinessView {
  state: 'CONNECTED' | 'UNAVAILABLE'
  payload: AgentRuntimeReadinessPayload | null
  detail: string
}

export async function resolveAgentRuntimeReadiness(fetchImpl?: typeof fetch): Promise<ResolvedReadinessView> {
  const doFetch = fetchImpl ?? (typeof fetch !== 'undefined' ? fetch : undefined)
  if (!doFetch) return { state: 'UNAVAILABLE', payload: null, detail: 'No fetch available.' }
  try {
    const response = await doFetch('/api/v3/agent-runtime/readiness', { method: 'GET', headers: { accept: 'application/json' } })
    if (!response.ok) return { state: 'UNAVAILABLE', payload: null, detail: `Readiness HTTP ${response.status}` }
    const payload = await response.json() as AgentRuntimeReadinessPayload
    if (payload?.read_only !== true) {
      return { state: 'UNAVAILABLE', payload: null, detail: 'Invalid readiness payload.' }
    }
    return { state: 'CONNECTED', payload, detail: 'Operator readiness loaded.' }
  } catch (err) {
    return { state: 'UNAVAILABLE', payload: null, detail: String((err as Error)?.message ?? err) }
  }
}

export function manualRunCommand(agentId: string, template?: string): string {
  const base = template ?? (
    'AGENT_RUNTIME_OPERATOR_AUTH=1 AGENT_RUNTIME_QUEUE_MODULE=agent_runtime_dispatch_boot '
    + '.venv/bin/python scripts/agent_runtime/agents/run_once.py --agent <agent_id> --once'
  )
  return base.replace('<agent_id>', agentId)
}

export interface PromotionGateRow {
  gate_id: string
  description: string
  status: string
  measured_value: number | boolean | null
  threshold: number
  comparator: string
}

export interface PromotionGatesPayload {
  contract: string
  agent_id: string
  maturity_target: string
  promotable: boolean
  blockers: string[]
  gates: PromotionGateRow[]
}

export async function resolvePromotionGates(agentId: string, fetchImpl?: typeof fetch): Promise<PromotionGatesPayload | null> {
  const doFetch = fetchImpl ?? (typeof fetch !== 'undefined' ? fetch : undefined)
  if (!doFetch) return null
  try {
    const response = await doFetch(`/api/v3/agent-maturity/${encodeURIComponent(agentId)}/promotion-gates`, {
      method: 'GET', headers: { accept: 'application/json' },
    })
    if (!response.ok) return null
    return await response.json() as PromotionGatesPayload
  } catch {
    return null
  }
}

/** Map maturity observations to catalog rows for the agent table. */
export function catalogFromMaturity(
  rows: import('./agentMaturityObservability').AgentMaturityObservation[],
  roleByAgent?: Map<string, string>,
): Array<{ agentId: string; displayName: string; role: string; subsystem: string; lifecycle: string; enabled: boolean; retrievalRequired: boolean; deadlineSeconds: number }> {
  return rows.map(row => ({
    agentId: row.agent_id,
    displayName: row.display_name,
    role: roleByAgent?.get(row.agent_id) ?? row.display_name,
    subsystem: row.subsystem,
    lifecycle: row.declared_lifecycle_state,
    enabled: row.declared_lifecycle_state === 'SHADOW' || row.environment === 'SHADOW',
    retrievalRequired: row.operator_checks_required.some(c => /retrieval/i.test(c)) || row.maturity_framework === 'agent-runtime-mvl',
    deadlineSeconds: 600,
  }))
}
