export interface DispatchOutcomeSummary {
  contract: string
  dispatch_id: string
  agent_id: string
  max_batch: number
  outcomes: Record<string, number>
  run_ids: string[]
  detail: string
  authority: {
    mutation: boolean
    financial_action: boolean
    schedule_change: boolean
  }
}

export interface DispatchBlocker {
  state: 'BLOCKED' | 'READY'
  reason: string | null
}

export async function probeDispatchReady(fetchImpl?: typeof fetch): Promise<DispatchBlocker> {
  const doFetch = fetchImpl ?? (typeof fetch !== 'undefined' ? fetch : undefined)
  if (!doFetch) return { state: 'BLOCKED', reason: 'No fetch available.' }
  try {
    const response = await doFetch('/api/v3/agent-runtime/readiness', { method: 'GET', headers: { accept: 'application/json' } })
    if (!response.ok) return { state: 'BLOCKED', reason: `Readiness HTTP ${response.status}` }
    const body = await response.json() as { wiring?: { dispatch?: { state?: string } } }
    const st = body?.wiring?.dispatch?.state
    if (st === 'WIRED') return { state: 'READY', reason: null }
    return { state: 'BLOCKED', reason: st ? st.replace(/_/g, ' ') : 'Dispatch not wired' }
  } catch (err) {
    return { state: 'BLOCKED', reason: String((err as Error)?.message ?? err) }
  }
}

export async function dispatchAgentRun(
  agentId: string,
  maxBatch = 1,
  fetchImpl?: typeof fetch,
): Promise<{ ok: true; payload: DispatchOutcomeSummary } | { ok: false; status: number; detail: string }> {
  const doFetch = fetchImpl ?? (typeof fetch !== 'undefined' ? fetch : undefined)
  if (!doFetch) return { ok: false, status: 0, detail: 'No fetch available.' }
  try {
    const response = await doFetch('/api/v3/agent-runtime/dispatch', {
      method: 'POST',
      headers: { accept: 'application/json', 'content-type': 'application/json' },
      body: JSON.stringify({ agent_id: agentId, max_batch: maxBatch }),
    })
    const payload = await response.json() as DispatchOutcomeSummary & { detail?: string }
    if (!response.ok) {
      return { ok: false, status: response.status, detail: String(payload?.detail ?? `HTTP ${response.status}`) }
    }
    return { ok: true, payload }
  } catch (err) {
    return { ok: false, status: 0, detail: String((err as Error)?.message ?? err) }
  }
}
