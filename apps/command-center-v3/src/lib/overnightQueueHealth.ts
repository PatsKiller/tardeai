// Overnight LLM queue health (audit 2026-10-21): GET /api/v2/queue/summary (deep_overnight_llm_queue) had no page.
// Thresholds mirror scripts/lib/needs_action.py QUEUE_WARN / QUEUE_CRIT — change both together.

export type QueueLevel = 'OK' | 'WARN' | 'CRIT' | 'UNAVAILABLE' | 'LOADING'

export const QUEUE_WARN = { pending: 500, failed: 50, nights: 3 }
export const QUEUE_CRIT = { pending: 1500, failed: 200, nights: 7 }

export interface QueueHealth {
  level: QueueLevel
  pending: number | null
  failed: number | null
  doneToday: number | null
  capPerNight: number | null
  drainNights: number | null
  nextWindowInHours: number | null
  reasons: string[]
}

const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) && v >= 0 ? v : null)
const EMPTY = { pending: null, failed: null, doneToday: null, capPerNight: null, drainNights: null, nextWindowInHours: null }

export function queueHealthFrom(payload: any, opts: { loading?: boolean; error?: unknown } = {}): QueueHealth {
  if (!payload) {
    if (opts.loading && !opts.error) return { level: 'LOADING', ...EMPTY, reasons: [] }
    return { level: 'UNAVAILABLE', ...EMPTY, reasons: [opts.error ? String(opts.error) : 'no payload'] }
  }
  // measured=false: the queue table could not be read and the zeros are not measurements.
  if (payload.measured === false || num(payload.pending) == null || num(payload.failed) == null) {
    return { level: 'UNAVAILABLE', ...EMPTY, reasons: ['queue table could not be read'] }
  }
  const pending = payload.pending as number
  const failed = payload.failed as number
  const cap = num(payload.cap_tonight)
  const drain = num(payload.estimated_completion_nights) ?? (cap ? Math.round((pending / cap) * 10) / 10 : null)
  const critR: string[] = []
  const warnR: string[] = []
  if (pending >= QUEUE_CRIT.pending) critR.push(`backlog ${pending} ≥ ${QUEUE_CRIT.pending}`)
  else if (pending >= QUEUE_WARN.pending) warnR.push(`backlog ${pending} ≥ ${QUEUE_WARN.pending}`)
  if (failed >= QUEUE_CRIT.failed) critR.push(`failed ${failed} ≥ ${QUEUE_CRIT.failed}`)
  else if (failed >= QUEUE_WARN.failed) warnR.push(`failed ${failed} ≥ ${QUEUE_WARN.failed}`)
  if (drain != null && drain >= QUEUE_CRIT.nights) critR.push(`drain ${drain} nights ≥ ${QUEUE_CRIT.nights}`)
  else if (drain != null && drain >= QUEUE_WARN.nights) warnR.push(`drain ${drain} nights ≥ ${QUEUE_WARN.nights}`)
  const level: QueueLevel = critR.length ? 'CRIT' : warnR.length ? 'WARN' : 'OK'
  const reasons = [...critR, ...warnR]
  return {
    level, pending, failed, doneToday: num(payload.done_today), capPerNight: cap, drainNights: drain,
    nextWindowInHours: num(payload.next_window_in_hours), reasons,
  }
}

export function queueLevelTone(level: QueueLevel): 'success' | 'warning' | 'danger' | 'neutral' {
  return level === 'OK' ? 'success' : level === 'WARN' ? 'warning' : level === 'LOADING' ? 'neutral' : 'danger'
}
