// Platform health (2026-10-21) — projection of GET /api/v2/system/platform-health (PlatformHealth@v1).
//
// The server answers one row per probe (n8n, always-on units, disk / CPU / memory, backup, main Postgres) with
// status OK | WARN | CRIT | UNKNOWN. This projection keeps the codebase's "never show zero for unavailable" rule
// (see commsDeliveryHealth.ts): a missing payload is UNAVAILABLE, an unrecognised or missing status is UNKNOWN —
// never OK — and a row whose as_of is older than two minutes, or a payload kept after a failed refresh, is STALE.

export type PlatformStatus = 'OK' | 'WARN' | 'CRIT' | 'UNKNOWN' | 'STALE'
export type PlatformState = 'OK' | 'WARN' | 'CRIT' | 'UNKNOWN' | 'STALE' | 'UNAVAILABLE' | 'LOADING'
export type PlatformTone = 'success' | 'warning' | 'danger' | 'neutral'

export interface PlatformRow {
  id: string
  group: string
  label: string
  status: PlatformStatus
  value: string
  reason: string | null
  asOf: string | null
  source: string | null
}

export interface PlatformGroup {
  group: string
  title: string
  rows: PlatformRow[]
  worst: PlatformStatus
}

export interface PlatformHealth {
  state: PlatformState
  rows: PlatformRow[]
  groups: PlatformGroup[]
  counts: Record<PlatformStatus, number>
  asOf: string | null
  reason: string | null
}

export const STALE_AFTER_S = 120

const SERVER_STATUSES = new Set(['OK', 'WARN', 'CRIT', 'UNKNOWN'])
const RANK: Record<PlatformStatus, number> = { OK: 0, STALE: 1, UNKNOWN: 2, WARN: 3, CRIT: 4 }
const GROUP_TITLES: Record<string, string> = {
  n8n: 'n8n',
  services: 'Host services',
  host: 'Disk · CPU · memory',
  backup: 'Backup',
  postgres: 'Main Postgres',
}
const GROUP_ORDER = ['n8n', 'services', 'host', 'backup', 'postgres']

const emptyCounts = (): Record<PlatformStatus, number> => ({ OK: 0, WARN: 0, CRIT: 0, UNKNOWN: 0, STALE: 0 })

export function worstOf(statuses: PlatformStatus[]): PlatformStatus {
  if (statuses.length === 0) return 'UNKNOWN'
  return statuses.reduce((a, b) => (RANK[b] > RANK[a] ? b : a), 'OK' as PlatformStatus)
}

export function toneFor(s: PlatformState): PlatformTone {
  if (s === 'OK') return 'success'
  if (s === 'WARN' || s === 'STALE') return 'warning'
  if (s === 'CRIT') return 'danger'
  return 'neutral'
}

function valueText(v: unknown): string {
  if (v === null || v === undefined || v === '') return '—'
  if (typeof v === 'number') return Number.isFinite(v) ? v.toLocaleString() : '—'
  return String(v)
}

/** Project the payload. `error` / `loading` come from the fetch hook; `nowMs` is the render clock. */
export function platformHealthFrom(
  payload: any,
  opts: { error?: unknown; loading?: boolean; nowMs: number; staleAfterS?: number },
): PlatformHealth {
  const staleAfterS = opts.staleAfterS ?? STALE_AFTER_S
  const empty = { rows: [], groups: [], counts: emptyCounts(), asOf: null }
  if (!payload) {
    if (opts.loading && !opts.error) return { state: 'LOADING', ...empty, reason: null }
    return { state: 'UNAVAILABLE', ...empty, reason: opts.error ? String(opts.error) : 'no payload' }
  }
  if (payload.status !== 'OK' || !Array.isArray(payload.items) || payload.items.length === 0) {
    return { state: 'UNAVAILABLE', ...empty, reason: String(payload.error || payload.status || 'malformed platform-health payload') }
  }
  const refreshFailed = Boolean(opts.error)
  const rows: PlatformRow[] = payload.items.map((it: any): PlatformRow => {
    const raw = String(it?.status ?? '').toUpperCase()
    let status: PlatformStatus = SERVER_STATUSES.has(raw) ? (raw as PlatformStatus) : 'UNKNOWN'
    let reason: string | null = typeof it?.reason === 'string' && it.reason ? it.reason : null
    if (!SERVER_STATUSES.has(raw)) reason = reason ?? `unrecognised status ${JSON.stringify(it?.status ?? null)}`
    const asOf = typeof it?.as_of === 'string' ? it.as_of : null
    const asOfMs = asOf ? Date.parse(asOf) : NaN
    if (status !== 'UNKNOWN') {
      if (!Number.isFinite(asOfMs)) {
        status = 'STALE'
        reason = 'no as_of on this reading'
      } else if ((opts.nowMs - asOfMs) / 1000 > staleAfterS) {
        status = 'STALE'
        reason = `last read ${asOf}${reason ? ` (${reason})` : ''}`
      } else if (refreshFailed) {
        status = 'STALE'
        reason = `refresh failed: ${String(opts.error)}`
      }
    }
    return {
      id: String(it?.id ?? ''),
      group: String(it?.group ?? 'other'),
      label: String(it?.label ?? it?.id ?? '?'),
      status,
      // An UNKNOWN row never shows a number: the probe could not look.
      value: status === 'UNKNOWN' ? 'UNKNOWN' : valueText(it?.value),
      reason,
      asOf,
      source: typeof it?.source === 'string' ? it.source : null,
    }
  })
  const counts = emptyCounts()
  for (const r of rows) counts[r.status]++
  const groupNames = [...GROUP_ORDER.filter(g => rows.some(r => r.group === g)),
    ...[...new Set(rows.map(r => r.group))].filter(g => !GROUP_ORDER.includes(g))]
  const groups = groupNames.map(g => {
    const gr = rows.filter(r => r.group === g)
    return { group: g, title: GROUP_TITLES[g] ?? g, rows: gr, worst: worstOf(gr.map(r => r.status)) }
  })
  return {
    state: worstOf(rows.map(r => r.status)),
    rows,
    groups,
    counts,
    asOf: typeof payload.as_of === 'string' ? payload.as_of : null,
    reason: refreshFailed ? `refresh failed: ${String(opts.error)}` : null,
  }
}

/** One-line summary for the Home card, e.g. "21 OK · 2 WARN". Zero-count states are omitted. */
export function countsLabel(c: Record<PlatformStatus, number>): string {
  const order: PlatformStatus[] = ['CRIT', 'WARN', 'UNKNOWN', 'STALE', 'OK']
  const parts = order.filter(s => c[s] > 0).map(s => `${c[s]} ${s}`)
  return parts.length ? parts.join(' · ') : '—'
}
