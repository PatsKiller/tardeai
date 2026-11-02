// Co-coordinators by territory (operator 2026-11-02, PLAN_CO_COORDINATORS_20261102): types and pure helpers for the
// read-only view of GET /api/v2/coordination/coordinators and /board. No writes: scripts/coordinator.py is the only
// writer of the registry and the shared notebook.

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

export type CoordinatorsPayload = {
  schema?: string
  generated_at?: string
  store?: string
  registry_present?: boolean
  stale_after_minutes?: number
  lead?: string | null
  coordinators?: CoordinatorRow[]
  territories?: Record<string, string>
  assignments?: Record<string, string>
  pending_checks?: CheckRow[]
  pending_decisions?: CheckRow[]
  inbox?: Record<string, number>
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

export function stateTone(state?: string): 'positive' | 'warning' | 'neutral' | 'danger' {
  if (state === 'active') return 'positive'
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
