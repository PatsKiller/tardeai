// Frontend adapter for the read-only agent-runtime API.
//
// It replaces the hardcoded fixture snapshot ONLY when the read API is actually available and
// returns valid read-only data. Otherwise it preserves an explicit, visible fallback state so the
// Command Center never silently presents fixture data as if it were live:
//
//   FIXTURE       – no read API configured (VITE_AGENT_RUNTIME_API_BASE unset); fixture shown.
//   NOT_CONNECTED – API host reachable but the reader adapter is not wired (HTTP 503); fixture shown.
//   UNAVAILABLE   – API errored, unreachable, or returned a malformed/non-read-only body; fixture shown.
//   STALE         – live data returned but older than the freshness budget; live data shown, flagged.
//   SHADOW        – live read-only data within the freshness budget; live data shown.
//
// The adapter issues only GET requests and refuses any response that claims mutation authority.
import { AGENT_RUNTIME_SNAPSHOT, type AgentRuntimeSnapshot } from './agentRuntimeMonitoring.ts'

export type AdapterState = 'FIXTURE' | 'NOT_CONNECTED' | 'UNAVAILABLE' | 'STALE' | 'SHADOW'

export interface ReadApiConfig {
  baseUrl: string | null
  now?: () => number
  staleAfterMs?: number
  fetchImpl?: typeof fetch
}

export interface ResolvedRuntimeView {
  state: AdapterState
  snapshot: AgentRuntimeSnapshot
  detail: string
  live: boolean
}

const DEFAULT_STALE_AFTER_MS = 15 * 60 * 1000

const STATUS_BUCKET: Record<string, keyof AgentRuntimeSnapshot['runs']> = {
  RUNNING: 'running',
  RETRIEVING: 'running',
  REASONING: 'running',
  REVIEW_REQUIRED: 'blocked',
  BLOCKED: 'blocked',
  FAILED: 'failed',
  CANCELLED: 'cancelled',
  DEADLINE_EXCEEDED: 'deadlineExceeded',
}

function fixtureView(state: AdapterState, detail: string): ResolvedRuntimeView {
  return { state, snapshot: { ...AGENT_RUNTIME_SNAPSHOT, source: 'FIXTURE', adapterState: 'FIXTURE_ONLY' }, detail, live: false }
}

// Read the API base URL from the Vite environment. Unset => null => FIXTURE (unchanged default).
export function readApiBaseFromEnv(env?: Record<string, string | undefined>): string | null {
  const source = env ?? (typeof import.meta !== 'undefined' ? (import.meta as { env?: Record<string, string | undefined> }).env : undefined)
  const raw = source?.VITE_AGENT_RUNTIME_API_BASE
  const trimmed = (raw ?? '').trim()
  return trimmed ? trimmed.replace(/\/$/, '') : null
}

export async function resolveAgentRuntimeView(config: ReadApiConfig): Promise<ResolvedRuntimeView> {
  const { baseUrl } = config
  if (!baseUrl) return fixtureView('FIXTURE', 'No read API configured — showing fixture snapshot.')

  const now = config.now ?? Date.now
  const staleAfterMs = config.staleAfterMs ?? DEFAULT_STALE_AFTER_MS
  const doFetch = config.fetchImpl ?? (typeof fetch !== 'undefined' ? fetch : undefined)
  if (!doFetch) return fixtureView('UNAVAILABLE', 'No fetch implementation available in this runtime.')

  let response: Response
  try {
    response = await doFetch(`${baseUrl}/api/v3/agent-runtime/runs?limit=200`, {
      method: 'GET',
      headers: { accept: 'application/json' },
    })
  } catch (err) {
    return fixtureView('UNAVAILABLE', `Read API unreachable: ${String((err as Error)?.message ?? err)}`)
  }

  if (response.status === 503) return fixtureView('NOT_CONNECTED', 'Read API reachable but reader adapter is not connected.')
  if (!response.ok) return fixtureView('UNAVAILABLE', `Read API returned HTTP ${response.status}.`)

  let body: unknown
  try {
    body = await response.json()
  } catch {
    return fixtureView('UNAVAILABLE', 'Read API returned a non-JSON body.')
  }

  const payload = body as {
    read_only?: boolean
    authority?: Record<string, boolean>
    data?: Array<Record<string, unknown>>
    as_of?: string
  }
  if (payload?.read_only !== true || !Array.isArray(payload.data)) {
    return fixtureView('UNAVAILABLE', 'Read API response was not a valid read-only listing.')
  }
  // Defense in depth: refuse any surface that advertises mutation/provider/service/financial authority.
  if (payload.authority && Object.values(payload.authority).some(Boolean)) {
    return fixtureView('UNAVAILABLE', 'Read API advertised non-zero authority; refusing to trust it.')
  }

  const rows = payload.data
  const runs: AgentRuntimeSnapshot['runs'] = {
    total: rows.length, running: 0, blocked: 0, failed: 0, cancelled: 0, deadlineExceeded: 0, stale: 0,
  }
  let newest = 0
  let anyShadow = false
  for (const row of rows) {
    const bucket = STATUS_BUCKET[String(row.status ?? '').toUpperCase()]
    if (bucket) runs[bucket] += 1
    if (String(row.environment ?? '').toUpperCase() === 'SHADOW') anyShadow = true
    const ts = Date.parse(String(row.updated_at ?? row.started_at ?? ''))
    if (!Number.isNaN(ts)) newest = Math.max(newest, ts)
  }

  const asOf = payload.as_of ?? (newest ? new Date(newest).toISOString() : new Date(now()).toISOString())
  const ageMs = newest ? now() - newest : Number.POSITIVE_INFINITY
  const stale = rows.length > 0 && ageMs > staleAfterMs
  if (stale) runs.stale = runs.total

  const snapshot: AgentRuntimeSnapshot = {
    contract: 'agent-runtime-monitoring-v1',
    source: 'SHADOW',
    asOf,
    adapterState: 'CONNECTED_READ_ONLY',
    runs,
    evidence: { ...AGENT_RUNTIME_SNAPSHOT.evidence },
  }

  if (stale) {
    return { state: 'STALE', snapshot: { ...snapshot, source: 'UNAVAILABLE' }, detail: `Live data is stale (age ${Math.round(ageMs / 1000)}s).`, live: true }
  }
  return { state: anyShadow || rows.length > 0 ? 'SHADOW' : 'NOT_CONNECTED', snapshot, detail: 'Live read-only data from the agent-runtime read API.', live: true }
}
