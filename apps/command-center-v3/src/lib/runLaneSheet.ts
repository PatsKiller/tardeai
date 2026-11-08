// LQ-20261107-611 · Ops → Controls · "Run a lane" sheet model. Pure: no React, no DOM, no fetch.
// Wire shapes mirror scripts/lib/ops_n8n_lane_run.py (lanes_view, batch_progress). The server decides every
// refusal; this module only searches, labels and summarizes what the server sent.
export const LANES_PATH = '/api/v2/ops/controls/lanes'
export const batchPath = (batchId: string) => `${LANES_PATH}/batch/${encodeURIComponent(batchId)}`

export const KIND_DRY = 'n8n_lane_run.dry'
export const KIND_LIVE = 'n8n_lane_run.live'
export const KIND_ALL_DRY = 'n8n_lane_run_all.dry'
export const KIND_ALL_LIVE = 'n8n_lane_run_all.live'
export const KIND_CANCEL = 'n8n_lane_run.cancel'

export type Avail = { available: boolean; reason: string | null; live_listed?: boolean }
export type LaneReceipt = {
  run_id?: string; lane_id?: string; mode?: string; state: string; reason?: string | null; flock_held?: boolean
  exit_code?: number | null; duration_s?: number | null; finished_at?: string | null
  output_signal_advanced?: boolean | null
}
export type LaneRow = {
  lane_id: string; family: string; schedule?: string | null
  dry: Avail; live: Avail
  run_all_live: { included: boolean; excluded_because: string[] }
  run_all_dry: { included: boolean }
  output_signal?: unknown; last_receipt?: LaneReceipt | null
}
export type LanesView = {
  schema?: string; generated_at?: string; live_list_missing?: boolean; market_open_today?: boolean | null
  lanes: LaneRow[]
  run_all: { dry_count: number; live_count: number; live_excluded: Array<{ lane_id: string; reasons: string[] }>; cooldown_s: number }
  note?: string
}
export type BatchCounts = { queued: number; running: number; done: number; failed: number; cancelled: number }
export type BatchProgress = { batch_id: string; total: number; counts: BatchCounts; finished: boolean; runs: LaneReceipt[] }

export function filterLanes(rows: readonly LaneRow[] | null | undefined, query: string): LaneRow[] {
  const q = query.trim().toLowerCase()
  const all = rows ? [...rows] : []
  if (!q) return all
  return all.filter(r => r.lane_id.toLowerCase().includes(q) || r.family.toLowerCase().includes(q))
}

/** "exit 0 · 2.5 s · output signal advanced" — or the lock/reason that explains why nothing ran. */
export function receiptLine(r: LaneReceipt | null | undefined): string {
  if (!r) return 'never run through the executor'
  if (r.flock_held) return 'skipped: lane lock held (flock_held) — another run is in flight'
  const parts: string[] = []
  if (r.state === 'REQUESTED') return 'queued'
  if (r.state === 'RUNNING') return 'running'
  if (r.state === 'RUN_REFUSED' && r.reason === 'cancelled_by_operator') return 'cancelled before it started'
  parts.push(r.exit_code === null || r.exit_code === undefined ? r.state : `exit ${r.exit_code}`)
  if (typeof r.duration_s === 'number') parts.push(`${r.duration_s.toFixed(1)} s`)
  if (r.reason && r.reason !== 'flock_held') parts.push(r.reason)
  parts.push(r.output_signal_advanced === true ? 'output signal advanced: yes' : r.output_signal_advanced === false ? 'output signal advanced: no' : 'output signal: not measured')
  return parts.join(' · ')
}

export function progressSummary(p: BatchProgress | null | undefined): string {
  if (!p) return 'waiting for the first row'
  const c = p.counts
  return `${c.queued} queued · ${c.running} running · ${c.done} done${c.failed ? ` · ${c.failed} failed` : ''}${c.cancelled ? ` · ${c.cancelled} cancelled` : ''} of ${p.total}`
}

export const canCancelQueued = (p: BatchProgress | null | undefined): boolean => !!p && p.counts.queued > 0

/** The v2 routes wrap {ok, data}; accept the bare body too. `key` names a field only the real payload has. */
export function unwrapEnvelope<T>(body: unknown, key: string): T | null {
  const b = body as Record<string, unknown> | null | undefined
  if (!b || typeof b !== 'object') return null
  if (key in b) return b as unknown as T
  const d = b.data as Record<string, unknown> | undefined
  return d && typeof d === 'object' && key in d ? (d as unknown as T) : null
}
