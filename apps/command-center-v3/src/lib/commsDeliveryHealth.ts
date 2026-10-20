// Communications delivery health (external review 2026-10-18, N3).
//
// The strip used to count RESERVED/SENDING and FAILED/BOUNCED/EXPIRED rows in the latest 500 deliveries it had
// fetched for the table: an older backlog was invisible, and a missing payload or a failed request rendered as
// "un-settled 0 · failed 0" — a false green. The counts now come from GET /api/v2/communications/deliveries/summary
// (one server-side aggregate over the whole table), and anything short of a fresh OK answer is shown as
// UNAVAILABLE or STALE, never as zero.

export type DeliveryHealthState = 'OK' | 'STALE' | 'UNAVAILABLE' | 'LOADING'

export interface DeliveryHealth {
  state: DeliveryHealthState
  unsettled: number | null
  failed: number | null
  total: number | null
  oldestUnsettledAgeS: number | null
  asOf: string | null
  reason: string | null
  lastGoodAgeS: number | null
  windowStart: string | null
  windowEnd: string | null
}

const isCount = (v: unknown): v is number => typeof v === 'number' && Number.isSafeInteger(v) && v >= 0

const EMPTY = { unsettled: null, failed: null, total: null, oldestUnsettledAgeS: null, asOf: null, lastGoodAgeS: null, windowStart: null, windowEnd: null }

/** Project the summary payload. `error` / `loading` come from the fetch hook; `nowMs` is the render clock. */
export function deliveryHealthFrom(
  payload: any,
  opts: { error?: unknown; loading?: boolean; stale?: boolean; nowMs: number; staleAfterS?: number },
): DeliveryHealth {
  const staleAfterS = opts.staleAfterS ?? 300
  if (!payload) {
    if (opts.loading && !opts.error) return { state: 'LOADING', ...EMPTY, reason: null }
    return { state: 'UNAVAILABLE', ...EMPTY, reason: opts.error ? String(opts.error) : 'no payload' }
  }
  if (payload.schema !== 'CommunicationsDeliverySummary@v1' || payload.ok !== true || payload.status !== 'OK'
      || !isCount(payload.unsettled) || !isCount(payload.failed) || !isCount(payload.total)
      || payload.unsettled + payload.failed > payload.total || payload.coverage?.complete !== true
      || payload.coverage?.scope !== 'all_retained_rows') {
    return { state: 'UNAVAILABLE', ...EMPTY, reason: String(payload.error || payload.status || 'malformed summary') }
  }
  const base = {
    unsettled: payload.unsettled as number,
    failed: payload.failed as number,
    total: isCount(payload.total) ? (payload.total as number) : null,
    oldestUnsettledAgeS: isCount(payload.oldest_unsettled_age_s) ? (payload.oldest_unsettled_age_s as number) : null,
    asOf: typeof payload.as_of === 'string' ? payload.as_of : null,
    lastGoodAgeS: null as number | null,
    windowStart: typeof payload.coverage.window_start === 'string' ? payload.coverage.window_start : null,
    windowEnd: typeof payload.coverage.window_end === 'string' ? payload.coverage.window_end : null,
  }
  const asOfMs = base.asOf ? Date.parse(base.asOf) : NaN
  const aware = (s: string | null) => s !== null && /(?:Z|[+-]\d\d:\d\d)$/.test(s) && Number.isFinite(Date.parse(s))
  if (!aware(base.asOf) || !aware(base.windowEnd) || base.windowEnd !== base.asOf
      || !Number.isFinite(opts.nowMs) || asOfMs > opts.nowMs + 60_000
      || (payload.total > 0 && (!aware(base.windowStart) || Date.parse(base.windowStart!) > asOfMs))
      || (payload.total === 0 && base.windowStart !== null)) {
    return { state: 'UNAVAILABLE', ...EMPTY, reason: 'invalid aggregation window' }
  }
  base.lastGoodAgeS = Math.max(0, (opts.nowMs - asOfMs) / 1000)
  if (opts.error || opts.stale) return { state: 'STALE', ...base, reason: 'refresh failed; retained observation' }
  if ((opts.nowMs - asOfMs) / 1000 > staleAfterS) {
    return { state: 'STALE', ...base, reason: `as of ${base.asOf}` }
  }
  return { state: 'OK', ...base, reason: null }
}

/** Short human age: 45s, 12m, 3h, 2d. */
export function ageLabel(s: number | null): string {
  if (s == null) return '—'
  if (s < 60) return `${Math.round(s)}s`
  if (s < 3600) return `${Math.round(s / 60)}m`
  if (s < 86400) return `${Math.round(s / 3600)}h`
  return `${Math.round(s / 86400)}d`
}
