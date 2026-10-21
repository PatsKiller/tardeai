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
  // EXPIRED by the stale-reservation reaper: an unclaimed shadow-ledger copy, not a failed send (2026-10-20).
  reapedUnclaimed: number | null
  total: number | null
  oldestUnsettledAgeS: number | null
  asOf: string | null
  reason: string | null
  // telegram_outbox — the send-chokepoint ledger, a DIFFERENT ledger from communication_deliveries (audit
  // 2026-10-21). Real failed Telegram sends in the last 24 h, by channel; null = not measured (never zero).
  telegramFailed24h: number | null
  telegramFailedByChannel: Record<string, number> | null
  // reports_archive rows the router held for the digest: never attempted, not failures.
  telegramHeld24h: number | null
  telegramError: string | null
}

const isCount = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v) && v >= 0

const EMPTY = {
  unsettled: null, failed: null, reapedUnclaimed: null, total: null, oldestUnsettledAgeS: null, asOf: null,
  telegramFailed24h: null, telegramFailedByChannel: null, telegramHeld24h: null, telegramError: null,
}

function byChannel(v: unknown): Record<string, number> | null {
  if (!v || typeof v !== 'object' || Array.isArray(v)) return null
  const out: Record<string, number> = {}
  for (const [k, n] of Object.entries(v as Record<string, unknown>)) if (isCount(n)) out[k] = n
  return out
}

/** Project the summary payload. `error` / `loading` come from the fetch hook; `nowMs` is the render clock. */
export function deliveryHealthFrom(
  payload: any,
  opts: { error?: unknown; loading?: boolean; nowMs: number; staleAfterS?: number },
): DeliveryHealth {
  const staleAfterS = opts.staleAfterS ?? 300
  if (!payload) {
    if (opts.loading && !opts.error) return { state: 'LOADING', ...EMPTY, reason: null }
    return { state: 'UNAVAILABLE', ...EMPTY, reason: opts.error ? String(opts.error) : 'no payload' }
  }
  if (payload.status !== 'OK' || !isCount(payload.unsettled) || !isCount(payload.failed)) {
    return { state: 'UNAVAILABLE', ...EMPTY, reason: String(payload.error || payload.status || 'malformed summary') }
  }
  const base = {
    unsettled: payload.unsettled as number,
    failed: payload.failed as number,
    reapedUnclaimed: isCount(payload.reaped_unclaimed) ? (payload.reaped_unclaimed as number) : null,
    total: isCount(payload.total) ? (payload.total as number) : null,
    oldestUnsettledAgeS: isCount(payload.oldest_unsettled_age_s) ? (payload.oldest_unsettled_age_s as number) : null,
    asOf: typeof payload.as_of === 'string' ? payload.as_of : null,
    telegramFailed24h: isCount(payload.telegram_outbox_failed_24h) ? (payload.telegram_outbox_failed_24h as number) : null,
    telegramFailedByChannel: byChannel(payload.telegram_outbox_failed_24h_by_channel),
    telegramHeld24h: isCount(payload.telegram_outbox_held_24h) ? (payload.telegram_outbox_held_24h as number) : null,
    telegramError: typeof payload.telegram_outbox_error === 'string' ? payload.telegram_outbox_error : null,
  }
  const asOfMs = base.asOf ? Date.parse(base.asOf) : NaN
  if (opts.error) return { state: 'STALE', ...base, reason: `refresh failed: ${String(opts.error)}` }
  if (!Number.isFinite(asOfMs)) return { state: 'STALE', ...base, reason: 'no as_of on the summary' }
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

/** "telegram 3 (alerts 2, documents 1)" — the by-channel breakdown of failed Telegram sends; '' when none. */
export function telegramFailedDetail(h: Pick<DeliveryHealth, 'telegramFailedByChannel'>): string {
  const m = h.telegramFailedByChannel
  if (!m) return ''
  const parts = Object.entries(m).filter(([, n]) => n > 0).sort((a, b) => b[1] - a[1]).map(([k, n]) => `${k} ${n}`)
  return parts.join(', ')
}
