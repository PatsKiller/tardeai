/** Watch Decision Desk V5 — feature flag + canonical strategy-refresh client.
 *
 * THE split this fixes (baseline audit 2026-07-22): "Refresh Strategy" must hit
 * the canonical packet-rebuild orchestrator (/api/v2/watch/decision/refresh),
 * while the old generic enrichment endpoint is honestly labelled "Refresh
 * Inputs". The server owns scheduling — the browser only requests and polls.
 *
 * Rollback: localStorage.setItem('WATCH_DECISION_DESK_V5', 'off') → Card v4
 * presentation returns (action-policy authority is unchanged either way).
 */

export function watchV5Enabled(): boolean {
  try {
    return localStorage.getItem('WATCH_DECISION_DESK_V5') !== 'off'
  } catch {
    return true
  }
}

export type RefreshScope = 'INPUTS_ONLY' | 'AFFECTED_DIMENSIONS' | 'FULL_STRATEGY'
export type AnalysisTier = 'LOCAL_QUANT' | 'STANDARD_BLIND' | 'PREMIUM_REVIEW'

export interface RefreshEnqueueResult {
  ok: boolean
  run_id?: number
  queued?: number
  skipped_locked?: number
  estimated_lane_calls?: number
  error?: string
  state?: string
}

export async function enqueueStrategyRefresh(
  symbols: string[],
  opts: { scope?: RefreshScope; tier?: AnalysisTier; force?: boolean; reason?: string } = {},
): Promise<RefreshEnqueueResult> {
  const r = await fetch('/api/v2/watch/decision/refresh', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      symbols,
      scope: opts.scope ?? 'AFFECTED_DIMENSIONS',
      analysis_tier: opts.tier ?? 'LOCAL_QUANT',
      force: !!opts.force,
      requested_by: 'operator',
      reason: opts.reason ?? 'manual_card_refresh',
    }),
  })
  const j = await r.json()
  return (j?.data ?? j) as RefreshEnqueueResult
}

export interface RunJobStatus {
  symbol: string
  state: string
  stage: string | null
  packet_id_after: number | null
  error: string | null
}

export interface RunStatus {
  ok: boolean
  run_id: number
  state: string
  jobs: RunJobStatus[]
}

export async function pollRefreshRun(
  runId: number,
  opts: { timeoutMs?: number; intervalMs?: number; onTick?: (s: RunStatus) => void } = {},
): Promise<RunStatus | null> {
  const deadline = Date.now() + (opts.timeoutMs ?? 240_000)
  const interval = opts.intervalMs ?? 3_000
  while (Date.now() < deadline) {
    try {
      const r = await fetch(`/api/v2/watch/decision/refresh/status?run_id=${runId}`)
      const j = await r.json()
      const s = (j?.data ?? j) as RunStatus
      opts.onTick?.(s)
      if (s.state && !['QUEUED', 'RUNNING'].includes(s.state)) return s
    } catch { /* transient poll errors are fine */ }
    await new Promise(res => setTimeout(res, interval))
  }
  return null
}

/** Desk-toolbar summary (counts by freshness state + session/policy). */
export async function fetchDeskSummary(): Promise<any> {
  const r = await fetch('/api/v2/watch/decision/summary')
  const j = await r.json()
  return j?.data ?? j
}
