// Co-coordinators by territory (operator 2026-11-02, PLAN_CO_COORDINATORS_20261102): types and pure helpers for the
// read-only view of GET /api/v2/coordination/coordinators and /board. No writes: scripts/coordinator.py is the only
// writer of the registry and the shared notebook.

import type { Tone } from './designTokens'

export type CoordinatorState = 'active' | 'stale' | 'stood_down'
export type CoordinatorRole = 'lead' | 'member' | 'observer'

export type CoordinatorRow = {
  id: string
  vendor?: string | null
  session?: string | null
  where?: string | null
  territories?: string[]
  role?: CoordinatorRole | string
  appointed_by?: string | null
  appointed_quote?: string | null
  appointed_at?: string | null
  last_heartbeat?: string | null
  status?: string | null
  state?: CoordinatorState
  stale_after_minutes?: number
}

export type CheckRow = { subject?: string; sha?: string; coordinator?: string | null; ts?: string; detail?: string | null }

export type AgentRow = {
  session?: string
  state?: string
  captured_at?: string | null
  file_modified_at?: string | null
  path?: string
  bytes?: number | null
}

export type DocsPayload = {
  schema?: string
  name?: string | null
  present?: boolean
  path?: string
  modified_at?: string | null
  text?: string | null
  error?: string | null
}

export type CoordinatorsPayload = {
  schema?: string
  generated_at?: string
  store?: string
  registry_present?: boolean
  registry_error?: string | null
  registry_unreadable?: boolean
  divergent?: boolean
  registry_problems?: string[]
  stale_after_minutes?: number
  lead?: string | null
  coordinators?: CoordinatorRow[]
  territories?: Record<string, string>
  assignments?: Record<string, string>
  pending_checks?: CheckRow[]
  pending_decisions?: CheckRow[]
  inbox?: Record<string, number>
  agents?: AgentRow[]
}

export type BoardEvent = { ts?: string; kind?: string; subject?: string | null; detail?: string | null; coordinator?: string | null }

export type BoardPayload = {
  schema?: string
  generated_at?: string
  board_present?: boolean
  board_md?: string | null
  events?: BoardEvent[]
  pending_checks?: CheckRow[]
  pending_decisions?: CheckRow[]
  inbox?: Record<string, number>
}

/**
 * The join line only belongs to the identity currently selected. useApi retains the previous response while a new
 * path loads, so checking the id's syntax alone could show (and copy) a line for the previous vendor or id.
 */
export function joinLineForSelection(
  data: { id?: string; vendor?: string; line?: string | null } | null | undefined,
  id: string,
  vendor: string,
): string {
  if (!data || data.id !== id || data.vendor !== vendor) return ''
  return data.line || ''
}

/** The line a READABLE but divergent registry must show, or null.
 *
 *  The server already publishes `divergent` and `registry_problems` (two leads, a top-level lead that disagrees with
 *  the role, duplicate ids …); the panel drew the cards and said nothing, so a registry that cannot be trusted looked
 *  exactly like a healthy one. An unreadable registry has its own banner (`registry_error`) and is not repeated here.
 *  Nothing on this page repairs a divergence (codex-cloud P2, CoordinatorsPanel). */
export function divergenceLine(p?: {
  divergent?: boolean; registry_error?: string | null; registry_problems?: string[]
} | null): string | null {
  if (!p || p.registry_error) return null
  if (p.divergent !== true) return null
  const problems = (p.registry_problems || []).map(x => String(x || '').trim()).filter(Boolean)
  return problems.length
    ? `The coordinator registry disagrees with itself: ${problems.join('; ')} — nothing here repairs it.`
    : 'The coordinator registry disagrees with itself — nothing here repairs it.'
}

export function stateTone(state?: string): Tone {
  if (state === 'active') return 'success'
  if (state === 'stale') return 'warning'
  if (state === 'stood_down') return 'neutral'
  return 'neutral'
}

export function stateLabel(state?: string): string {
  return state === 'stood_down' ? 'stood down' : state || 'unknown'
}

export function heartbeatLabel(iso?: string | null): string {
  if (!iso) return 'never'
  const t = Date.parse(iso)
  if (Number.isNaN(t)) return 'unknown'
  const mins = Math.max(0, Math.round((Date.now() - t) / 60000))
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const h = Math.floor(mins / 60)
  return h < 48 ? `${h}h ago` : `${Math.floor(h / 24)}d ago`
}

export function byTerritory(assignments: Record<string, string> | undefined): Array<{ territory: string; subjects: string[] }> {
  const m = new Map<string, string[]>()
  for (const [subject, territory] of Object.entries(assignments || {})) {
    const list = m.get(territory) || []
    list.push(subject)
    m.set(territory, list)
  }
  return [...m.entries()]
    .map(([territory, subjects]) => ({ territory, subjects: subjects.sort() }))
    .sort((a, b) => a.territory.localeCompare(b.territory))
}

export function sortCoordinators(rows: CoordinatorRow[] | undefined): CoordinatorRow[] {
  const rank: Record<string, number> = { lead: 0, member: 1, observer: 2 }
  return [...(rows || [])].sort(
    (a, b) => (rank[String(a.role)] ?? 9) - (rank[String(b.role)] ?? 9) || String(a.id).localeCompare(String(b.id)),
  )
}
