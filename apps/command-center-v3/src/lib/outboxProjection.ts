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
  attempts?: number
  created_at?: string | null
  age_min?: number | null
}

export interface OutboxPayload {
  schema?: string
  as_of?: string | null
  status?: 'OK' | 'UNAVAILABLE' | 'DISABLED' | string
  window_hours?: number
  counts?: Record<string, Record<string, number>>
  count?: number
  total?: number
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
  attempts: number
  createdAt: string | null
  ageMinutes: number | null
}

export interface OutboxCount { outbox: string; state: string; n: number; tone: Tone }

export interface OutboxModel {
  status: 'OK' | 'UNAVAILABLE' | 'DISABLED'
  statusLabel: string
  statusTone: Tone
  windowLabel: string
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

export function projectOutbox(payload: OutboxPayload | null | undefined): OutboxModel {
  if (!payload || typeof payload !== 'object') {
    return { status: 'UNAVAILABLE', statusLabel: 'UNAVAILABLE', statusTone: 'danger', windowLabel: 'UNDATED', note: 'no payload', counts: [], rows: [] }
  }
  const status: OutboxModel['status'] = payload.status === 'OK' ? 'OK' : payload.status === 'DISABLED' ? 'DISABLED' : 'UNAVAILABLE'
  const counts: OutboxCount[] = []
  for (const [outbox, byState] of Object.entries(payload.counts ?? {})) {
    for (const [state, n] of Object.entries(byState ?? {})) counts.push({ outbox, state, n, tone: toneForOutboxState(state) })
  }
  counts.sort((a, b) => a.outbox.localeCompare(b.outbox) || b.n - a.n)
  const rows: OutboxRow[] = (payload.items ?? []).map(it => {
    const state = String(it.state ?? 'unknown')
    return {
      key: `${it.outbox ?? '?'}:${it.id ?? '?'}`,
      outbox: String(it.outbox ?? ''), id: String(it.id ?? ''), state, tone: toneForOutboxState(state),
      reason: String(it.reason ?? ''), channel: String(it.channel ?? ''), subject: String(it.subject ?? ''),
      attempts: Number(it.attempts ?? 0), createdAt: it.created_at ?? null,
      ageMinutes: typeof it.age_min === 'number' ? it.age_min : null,
    }
  })
  return {
    status,
    statusLabel: status === 'OK' ? `OK · ${payload.total ?? rows.length} in window` : status,
    statusTone: status === 'OK' ? 'success' : status === 'DISABLED' ? 'neutral' : 'danger',
    windowLabel: payload.window_hours ? `last ${payload.window_hours} h` : 'UNDATED',
    note: String(payload.note ?? ''),
    counts, rows,
  }
}
