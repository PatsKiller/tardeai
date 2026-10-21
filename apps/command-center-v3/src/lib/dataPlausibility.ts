// Data plausibility view (audit 2026-10-21): GET /api/v2/system/data-plausibility serves the latest
// data_plausibility_monitor.py receipt. A missing/unreadable/old receipt is never an empty green.

export type PlausibilityStatus = 'OK' | 'BLOCK' | 'STALE' | 'NO_RECEIPT' | 'UNAVAILABLE' | 'LOADING'

export interface PlausibilityRule {
  name: string
  status: string
  severity: string
  violations: number | null
  total: number | null
  detail: string
}

export interface PlausibilityModel {
  status: PlausibilityStatus
  checked: number | null
  violations: number | null
  blocking: number | null
  blockingItems: string[]
  ranAt: string | null
  ageH: number | null
  rules: PlausibilityRule[] | null
  note: string | null
}

const cnt = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) && v >= 0 ? v : null)
const KNOWN: PlausibilityStatus[] = ['OK', 'BLOCK', 'STALE', 'NO_RECEIPT', 'UNAVAILABLE']

export function plausibilityFrom(payload: any, opts: { loading?: boolean; error?: unknown } = {}): PlausibilityModel {
  const empty = { checked: null, violations: null, blocking: null, blockingItems: [], ranAt: null, ageH: null, rules: null }
  if (!payload) {
    if (opts.loading && !opts.error) return { status: 'LOADING', ...empty, note: null }
    return { status: 'UNAVAILABLE', ...empty, note: opts.error ? String(opts.error) : 'no payload' }
  }
  const status: PlausibilityStatus = KNOWN.includes(payload.status) ? payload.status : 'UNAVAILABLE'
  const rules = Array.isArray(payload.rules)
    ? payload.rules.map((r: any) => ({
        name: `${r?.table ?? '?'}.${r?.column ?? '?'}`, status: String(r?.status ?? ''), severity: String(r?.severity ?? ''),
        violations: cnt(r?.violations), total: cnt(r?.total), detail: String(r?.detail ?? ''),
      }))
    : null
  return {
    status, checked: cnt(payload.checked), violations: cnt(payload.violations), blocking: cnt(payload.blocking),
    blockingItems: Array.isArray(payload.blocking_items) ? payload.blocking_items.map(String) : [],
    ranAt: typeof payload.ran_at === 'string' ? payload.ran_at : null,
    ageH: typeof payload.age_h === 'number' ? payload.age_h : null, rules,
    note: typeof payload.note === 'string' ? payload.note : null,
  }
}

export function plausibilityTone(s: PlausibilityStatus): 'success' | 'warning' | 'danger' | 'neutral' {
  return s === 'OK' ? 'success' : s === 'STALE' ? 'warning' : s === 'LOADING' ? 'neutral' : 'danger'
}
