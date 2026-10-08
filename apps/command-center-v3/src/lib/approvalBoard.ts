// Approval board projection (GET /api/v2/coordination/approvals) → page model. Pure, testable.
// 2026-10-08 roadmap Phase 2 PR-C: every open approval package and every active guard grant with its
// time to expiry. Read-only: nothing here approves, grants, consumes or sends.
import type { Tone } from './designTokens'

export interface ApprovalItem {
  kind?: 'package' | 'grant' | string
  id?: string
  scope?: string
  state?: string
  ledger_state?: string
  created_at?: string | null
  expires_at?: string | null
  age_min?: number | null
  ttl_min_left?: number | null
  uses_left?: number | null
  items_total?: number | null
  items_pending?: number | null
  reason?: string
}

export interface ApprovalSource { status?: string; reason?: string; count?: number }

export interface ApprovalBoardPayload {
  schema?: string
  as_of?: string | null
  status?: 'OK' | 'PARTIAL' | 'UNAVAILABLE' | string
  sources?: Record<string, ApprovalSource>
  counts?: Record<string, Record<string, number>>
  expiring?: ApprovalItem[]
  expiring_count?: number
  total?: number
  items?: ApprovalItem[]
  note?: string
}

export interface ApprovalRow {
  key: string
  kind: string
  id: string
  scope: string
  state: string
  tone: Tone
  ttlLabel: string
  ttlMinutes: number | null
  usesLeft: number | null
  pendingLabel: string
  reason: string
  expiresAt: string | null
  expiring: boolean
}

export interface ApprovalCount { kind: string; state: string; n: number; tone: Tone }

export interface ApprovalBoardModel {
  status: 'OK' | 'PARTIAL' | 'UNAVAILABLE'
  statusLabel: string
  statusTone: Tone
  asOfLabel: string
  note: string
  sourceNotes: string[]
  counts: ApprovalCount[]
  expiringCount: number
  rows: ApprovalRow[]
}

export function toneForApprovalState(state: string, ttlMinutes: number | null): Tone {
  switch (state) {
    case 'OPEN':
    case 'ACTIVE':
      return ttlMinutes !== null && ttlMinutes <= 10 ? 'danger' : ttlMinutes !== null && ttlMinutes <= 30 ? 'warning' : 'info'
    case 'EXPIRED':
    case 'DENIED':
      return 'danger'
    case 'CONSUMED':
    case 'APPROVED':
    case 'VALIDATED':
    case 'EXECUTING':
      return 'success'
    default:
      return 'neutral'
  }
}

export function ttlLabel(ttlMinutes: number | null, state: string): string {
  if (ttlMinutes === null) return state === 'OPEN' || state === 'ACTIVE' ? 'no expiry' : ''
  if (ttlMinutes < 0) return `expired ${-ttlMinutes} min ago`
  if (ttlMinutes < 60) return `${ttlMinutes} min left`
  return `${Math.floor(ttlMinutes / 60)} h ${ttlMinutes % 60} min left`
}

export function projectApprovalBoard(payload: ApprovalBoardPayload | null | undefined): ApprovalBoardModel {
  if (!payload || typeof payload !== 'object') {
    return {
      status: 'UNAVAILABLE', statusLabel: 'UNAVAILABLE', statusTone: 'danger', asOfLabel: 'UNDATED',
      note: 'no payload', sourceNotes: [], counts: [], expiringCount: 0, rows: [],
    }
  }
  const status: ApprovalBoardModel['status'] = payload.status === 'OK' ? 'OK' : payload.status === 'PARTIAL' ? 'PARTIAL' : 'UNAVAILABLE'
  const expiringKeys = new Set((payload.expiring ?? []).map(e => `${e.kind ?? '?'}:${e.id ?? '?'}`))
  const counts: ApprovalCount[] = []
  for (const [kind, byState] of Object.entries(payload.counts ?? {})) {
    for (const [state, n] of Object.entries(byState ?? {})) counts.push({ kind, state, n, tone: toneForApprovalState(state, null) })
  }
  counts.sort((a, b) => a.kind.localeCompare(b.kind) || b.n - a.n)
  const rows: ApprovalRow[] = (payload.items ?? []).map(it => {
    const state = String(it.state ?? 'UNKNOWN')
    const ttl = typeof it.ttl_min_left === 'number' ? it.ttl_min_left : null
    const key = `${it.kind ?? '?'}:${it.id ?? '?'}`
    const pending = it.kind === 'package' && typeof it.items_total === 'number'
      ? `${it.items_pending ?? 0}/${it.items_total} pending`
      : ''
    return {
      key, kind: String(it.kind ?? ''), id: String(it.id ?? ''), scope: String(it.scope ?? ''), state,
      tone: toneForApprovalState(state, ttl), ttlLabel: ttlLabel(ttl, state), ttlMinutes: ttl,
      usesLeft: typeof it.uses_left === 'number' ? it.uses_left : null, pendingLabel: pending,
      reason: String(it.reason ?? ''), expiresAt: it.expires_at ?? null, expiring: expiringKeys.has(key),
    }
  })
  const sourceNotes = Object.entries(payload.sources ?? {})
    .filter(([, s]) => s && s.status !== 'OK')
    .map(([name, s]) => `${name}: ${s.status ?? 'UNKNOWN'}${s.reason ? ` (${s.reason})` : ''}`)
  const expiringCount = payload.expiring_count ?? (payload.expiring ?? []).length
  return {
    status,
    statusLabel: status === 'OK' ? `OK · ${payload.total ?? rows.length} rows` : status,
    statusTone: status === 'OK' ? 'success' : status === 'PARTIAL' ? 'warning' : 'danger',
    asOfLabel: payload.as_of ? String(payload.as_of).slice(0, 16).replace('T', ' ') : 'UNDATED',
    note: String(payload.note ?? ''),
    sourceNotes, counts, expiringCount, rows,
  }
}
