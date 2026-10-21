// "Needs action" inbox (audit 2026-10-21): GET /api/v2/needs-action. Every source is probed independently; an
// unreadable source is an item. "Nothing needs action" is shown ONLY when every source answered — a fetch error, a
// missing payload or a PARTIAL answer is never an empty green.

export type Severity = 'P0' | 'P1' | 'P2' | 'P3'
export const SEVERITIES: Severity[] = ['P0', 'P1', 'P2', 'P3']

export interface NeedsActionItem {
  severity: Severity
  title: string
  why: string
  where: string   // router path inside the /v3 basename
  source: string
  since: string | null
}

export interface NeedsActionModel {
  state: 'LOADING' | 'UNAVAILABLE' | 'ITEMS' | 'CLEAR' | 'STALE'
  counts: Record<Severity, number>
  items: NeedsActionItem[]
  allSourcesAnswered: boolean
  unavailableSources: string[]
  asOf: string | null
  reason: string | null
}

const zero = (): Record<Severity, number> => ({ P0: 0, P1: 0, P2: 0, P3: 0 })

/** "/v3/system?tab=Jobs" → "/system?tab=Jobs" (the router basename is /v3). Non-CC paths fall back to "/". */
export function routerPath(where: unknown): string {
  const w = typeof where === 'string' ? where : ''
  if (w === '/v3' || w === '/v3/') return '/'
  if (w.startsWith('/v3/') || w.startsWith('/v3?')) return w.slice(3)
  return w.startsWith('/') ? w : '/'
}

export function needsActionFrom(
  payload: any,
  opts: { loading?: boolean; error?: unknown; nowMs?: number; staleAfterS?: number } = {},
): NeedsActionModel {
  const base = { counts: zero(), items: [] as NeedsActionItem[], allSourcesAnswered: false, unavailableSources: [] as string[], asOf: null }
  if (!payload || typeof payload !== 'object') {
    if (opts.loading && !opts.error) return { state: 'LOADING', ...base, reason: null }
    return { state: 'UNAVAILABLE', ...base, reason: opts.error ? String(opts.error) : 'no payload' }
  }
  if (!Array.isArray(payload.items)) return { state: 'UNAVAILABLE', ...base, reason: 'malformed payload' }
  const items: NeedsActionItem[] = payload.items
    .filter((i: any) => i && SEVERITIES.includes(i.severity))
    .map((i: any) => ({
      severity: i.severity as Severity, title: String(i.title ?? ''), why: String(i.why ?? ''),
      where: routerPath(i.where), source: String(i.source ?? ''), since: typeof i.since === 'string' ? i.since : null,
    }))
  items.sort((a, b) => SEVERITIES.indexOf(a.severity) - SEVERITIES.indexOf(b.severity))
  const counts = zero()
  for (const i of items) counts[i.severity]++
  const sources = payload.sources && typeof payload.sources === 'object' ? payload.sources : {}
  const unavailableSources = Object.entries(sources).filter(([, s]: [string, any]) => s?.status !== 'OK').map(([k]) => k)
  const allSourcesAnswered = payload.all_sources_answered === true && unavailableSources.length === 0
  const asOf = typeof payload.as_of === 'string' ? payload.as_of : null
  const common = { counts, items, allSourcesAnswered, unavailableSources, asOf }
  if (opts.error) return { state: 'STALE', ...common, reason: `refresh failed: ${String(opts.error)}` }
  if (opts.nowMs != null && asOf) {
    const age = (opts.nowMs - Date.parse(asOf)) / 1000
    if (Number.isFinite(age) && age > (opts.staleAfterS ?? 300)) return { state: 'STALE', ...common, reason: `as of ${asOf}` }
  }
  if (items.length === 0 && allSourcesAnswered) return { state: 'CLEAR', ...common, reason: null }
  if (items.length === 0) return { state: 'UNAVAILABLE', ...common, reason: 'not every source answered' }
  return { state: 'ITEMS', ...common, reason: null }
}

export function severityTone(s: Severity): 'danger' | 'warning' | 'info' | 'neutral' {
  return s === 'P0' || s === 'P1' ? 'danger' : s === 'P2' ? 'warning' : 'info'
}
