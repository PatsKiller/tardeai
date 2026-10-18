// Notification outbox projection (GET /api/v2/coordination/outbox) → page model. Pure, testable.
// 2026-10-08 roadmap Phase 2 PR-A: what the senders did — sent / suppressed / recorded / withdrawn with the
// recorded reason. Read-only; n8n never sends and nothing here mutates anything.
import type { Tone } from './designTokens'

export interface OutboxItem {
  outbox?: string
  id?: string
  state?: string
  reason?: string
  channel?: string
  subject?: string
  attempts?: number | null
  created_at?: string | null
  age_min?: number | null
}

export interface OutboxPayload {
  schema?: string
  as_of?: string | null
  status?: 'OK' | 'UNAVAILABLE' | 'DISABLED' | string
  window_hours?: number
  counts?: Record<string, Record<string, number>> | null
  count?: number | null
  total?: number | null
  last_good_at?: string | null
  coverage?: { since?: string; through?: string; aggregation_complete?: boolean; items_truncated?: boolean; returned_rows?: number }
  items?: OutboxItem[]
  note?: string
}

export interface OutboxRow {
  key: string
  outbox: string
  id: string
  state: string
  tone: Tone
  reason: string
  channel: string
  subject: string
  attempts: number | null
  createdAt: string | null
  ageMinutes: number | null
}

export interface OutboxCount { outbox: string; state: string; n: number; tone: Tone }

export interface OutboxModel {
  status: 'OK' | 'UNAVAILABLE' | 'DISABLED' | 'STALE' | 'PARTIAL'
  statusLabel: string
  statusTone: Tone
  windowLabel: string
  lastGoodAgeMinutes: number | null
  note: string
  counts: OutboxCount[]
  rows: OutboxRow[]
}

export function toneForOutboxState(state: string): Tone {
  switch (state) {
    case 'sent': return 'success'
    case 'suppressed': return 'neutral'
    case 'withdrawn':
    case 'failed': return 'danger'
    case 'recorded':
    case 'pending':
    case 'queued': return 'warning'
    default: return 'info'
  }
}

export function projectOutbox(payload: OutboxPayload | null | undefined, opts: { error?: boolean; stale?: boolean; nowMs?: number } = {}): OutboxModel {
  if (!payload || typeof payload !== 'object') {
    return { status: 'UNAVAILABLE', statusLabel: 'UNAVAILABLE', statusTone: 'danger', windowLabel: 'UNDATED', lastGoodAgeMinutes: null, note: 'no payload', counts: [], rows: [] }
  }
  const known = !payload.schema || ['NotificationOutboxProjection@v1', 'NotificationOutboxProjection@v2'].includes(payload.schema)
  const legacy = payload.schema !== 'NotificationOutboxProjection@v2'
  const age = payload.as_of ? (opts.nowMs ?? Date.now()) - Date.parse(payload.as_of) : null
  const stale = !!opts.stale || (!legacy && (age == null || !Number.isFinite(age) || age < 0 || age > 180_000))
  let status: OutboxModel['status'] = !known ? 'UNAVAILABLE' : opts.error || stale ? 'STALE' : payload.status === 'OK' ? legacy ? 'PARTIAL' : 'OK' : payload.status === 'DISABLED' ? 'DISABLED' : 'UNAVAILABLE'
  const groups = Object.values(payload.counts ?? {})
  const validCounts = groups.every(c => c && typeof c === 'object' && !Array.isArray(c) && Object.values(c).every(n => Number.isSafeInteger(n) && n >= 0))
  const sum = validCounts ? groups.reduce((total, c) => total + Object.values(c).reduce((a, n) => a + n, 0), 0) : NaN
  if (!legacy && status === 'OK' && (payload.coverage?.aggregation_complete !== true || !validCounts || typeof payload.total !== 'number' || sum !== payload.total)) status = 'PARTIAL'
  const complete = status === 'OK' && payload.coverage?.aggregation_complete === true
  // Respect explicit null and never promote an unavailable capture to last-good.
  const last = payload.last_good_at === undefined ? (known && payload.status === 'OK' ? payload.as_of : null) : payload.last_good_at
  const lastGoodAgeMinutes = last && Number.isFinite(Date.parse(last)) && Date.parse(last) <= (opts.nowMs ?? Date.now()) ? Math.round(((opts.nowMs ?? Date.now()) - Date.parse(last)) / 60_000) : null
  const counts: OutboxCount[] = []
  for (const [outbox, byState] of Object.entries(complete || (legacy && status === 'PARTIAL') ? payload.counts ?? {} : {})) {
    for (const [state, n] of Object.entries(byState ?? {})) counts.push({ outbox, state, n, tone: toneForOutboxState(state) })
  }
  counts.sort((a, b) => a.outbox.localeCompare(b.outbox) || b.n - a.n)
  const rows: OutboxRow[] = (known ? payload.items ?? [] : []).map(it => {
    const state = String(it.state ?? 'unknown')
    return {
      key: `${it.outbox ?? '?'}:${it.id ?? '?'}`,
      outbox: String(it.outbox ?? ''), id: String(it.id ?? ''), state, tone: toneForOutboxState(state),
      reason: String(it.reason ?? ''), channel: String(it.channel ?? ''), subject: String(it.subject ?? ''),
      attempts: typeof it.attempts === 'number' && Number.isFinite(it.attempts) ? it.attempts : null, createdAt: it.created_at ?? null,
      ageMinutes: typeof it.age_min === 'number' ? it.age_min : null,
    }
  })
  return {
    status,
    statusLabel: complete ? `AVAILABLE · ${payload.total ?? 'UNAVAILABLE'} recorded rows; ${rows.length} details${payload.coverage?.items_truncated ? ' (limited)' : ''}` : status === 'PARTIAL' && legacy ? `LEGACY SAMPLE · ${rows.length} details; full totals unknown` : status,
    statusTone: status === 'OK' ? 'success' : status === 'DISABLED' ? 'neutral' : status === 'STALE' || status === 'PARTIAL' ? 'warning' : 'danger',
    windowLabel: complete ? `${payload.coverage?.since ?? 'unknown'} → ${payload.coverage?.through ?? 'unknown'} (UTC)` : legacy ? 'Legacy sample; window completeness unknown' : 'UNAVAILABLE window',
    note: String(payload.note ?? ''),
    counts, rows, lastGoodAgeMinutes,
  }
}
