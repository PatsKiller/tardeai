import { normalizeAgentId } from './agentRuntimeDetailAdapter'

export interface AgentRunRollupEntry {
  agentId: string
  lastStartedAt: string | null
  lastCompletedAt: string | null
  lastUpdatedAt: string | null
  lastStatus: string | null
  lastRunId: string | null
  runCount: number
}

export interface FleetRunPulse {
  total: number
  completed: number
  failed: number
  running: number
  blocked: number
  newestStartedAt: string | null
}

const RUNNING = new Set(['RUNNING', 'RETRIEVING', 'REASONING'])
const FAILED = new Set(['FAILED', 'DEADLINE_EXCEEDED'])
const BLOCKED = new Set(['BLOCKED', 'REVIEW_REQUIRED'])

function ts(row: Record<string, unknown>, key: string): string | null {
  const v = String(row[key] ?? '').trim()
  return v || null
}

/** Build per-agent last-run rollup from a runs listing (newest first preferred). */
export function buildAgentRunRollup(rows: Array<Record<string, unknown>>): Map<string, AgentRunRollupEntry> {
  const out = new Map<string, AgentRunRollupEntry>()
  for (const row of rows) {
    const agentId = normalizeAgentId(row.agent_id)
    if (!agentId) continue
    const started = ts(row, 'started_at')
    const existing = out.get(agentId)
    if (existing) {
      existing.runCount += 1
      continue
    }
    out.set(agentId, {
      agentId,
      lastStartedAt: started,
      lastCompletedAt: ts(row, 'completed_at'),
      lastUpdatedAt: ts(row, 'updated_at') ?? started,
      lastStatus: String(row.status ?? '').trim() || null,
      lastRunId: String(row.run_id ?? '').trim() || null,
      runCount: 1,
    })
  }
  return out
}

export function buildFleetRunPulse(rows: Array<Record<string, unknown>>): FleetRunPulse {
  let completed = 0
  let failed = 0
  let running = 0
  let blocked = 0
  let newest = 0
  let newestStartedAt: string | null = null
  for (const row of rows) {
    const status = String(row.status ?? '').toUpperCase()
    if (RUNNING.has(status)) running += 1
    else if (FAILED.has(status)) failed += 1
    else if (BLOCKED.has(status)) blocked += 1
    else if (status === 'COMPLETED') completed += 1
    const started = ts(row, 'started_at')
    if (started) {
      const t = Date.parse(/[zZ]$|[+-]\d\d:?\d\d$/.test(started) ? started : `${started}Z`)
      if (!Number.isNaN(t) && t > newest) {
        newest = t
        newestStartedAt = started
      }
    }
  }
  return { total: rows.length, completed, failed, running, blocked, newestStartedAt }
}

export async function fetchAgentRuntimeRuns(
  baseUrl: string,
  fetchImpl?: typeof fetch,
  limit = 200,
): Promise<Array<Record<string, unknown>> | null> {
  const doFetch = fetchImpl ?? (typeof fetch !== 'undefined' ? fetch : undefined)
  if (!doFetch) return null
  try {
    const resp = await doFetch(`${baseUrl}/api/v3/agent-runtime/runs?limit=${limit}`, {
      method: 'GET',
      headers: { accept: 'application/json' },
    })
    if (!resp.ok) return null
    const body = await resp.json() as { read_only?: boolean; data?: unknown }
    if (body?.read_only !== true || !Array.isArray(body.data)) return null
    return body.data as Array<Record<string, unknown>>
  } catch {
    return null
  }
}
