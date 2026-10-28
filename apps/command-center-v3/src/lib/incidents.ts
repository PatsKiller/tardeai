// Ops → Incidents (operator 2026-10-27): wire types + pure helpers for GET /api/v2/ops/incidents
// (scripts/lib/incidents_view.py over the IncidentRecord@v1 ledger, data/coordination/incidents).

export const INCIDENTS_PATH = '/api/v2/ops/incidents'

export type IncidentStatus = 'open' | 'fixing' | 'fixed' | 'blocked' | 'closed'
export type Tone = 'success' | 'warning' | 'danger' | 'info' | 'neutral'

export type IncidentAttempt = {
  at?: string; actor?: string; action?: string; result?: string; ok?: boolean | null
  provider?: string; class?: string; proposed?: string; rationale?: string; output_tail?: string
}
export type FixRef = { kind: 'pr' | 'commit' | 'receipt' | 'doc' | 'incident'; ref: string }
export type Incident = {
  schema: string; id: string; opened_at: string; updated_at: string; status: IncidentStatus
  source: { kind: string; watcher?: string; job?: string; lane?: string; session?: string; agent?: string }
  title: string; where?: string; severity?: string; owner?: string; fingerprint?: string
  evidence: string[]; attempts: IncidentAttempt[]; fix_refs: FixRef[]
  notes?: { at: string; actor: string; text: string }[]
  blocked_reason?: string | null; handoff?: string | null; resolution?: string | null; closed_at?: string | null
  acknowledged?: { at: string; actor: string; decision_ref?: string; comment?: string | null } | null
  escalations?: { at: string; reason?: string; delivered?: boolean }[]
  recurrence_of?: string | null
}
export type IncidentsWire = {
  schema: string; ledger_present: boolean; generated_at: string | null
  summary: { counts: Record<IncidentStatus, number>; unresolved: number; oldest_unresolved_id: string | null; oldest_unresolved_age_min: number | null } | null
  incidents: Incident[]; watchers_as_of: string | null; supervisor_as_of: string | null
}
export type IncidentDetailWire = { incident: Incident; events: Record<string, unknown>[] }

export const STATUS_ORDER: IncidentStatus[] = ['open', 'fixing', 'blocked', 'fixed', 'closed']
export const STATUS_FILTERS: Array<[string, string]> = [['active', 'Active'], ['open', 'Open'], ['fixing', 'Fixing'], ['blocked', 'Blocked'], ['fixed', 'Fixed'], ['closed', "Won't fix"], ['all', 'All']]

export function statusLabel(s: string): { label: string; tone: Tone } {
  switch (s) {
    case 'open': return { label: 'Open', tone: 'danger' }
    case 'fixing': return { label: 'Fixing', tone: 'warning' }
    case 'blocked': return { label: 'Blocked — needs a person', tone: 'danger' }
    case 'fixed': return { label: 'Fixed', tone: 'success' }
    case 'closed': return { label: "Closed — won't fix", tone: 'neutral' }
    default: return { label: `Unknown (${s})`, tone: 'warning' }
  }
}

export function matchesFilter(i: Incident, f: string): boolean {
  if (f === 'all') return true
  if (f === 'active') return i.status === 'open' || i.status === 'fixing' || i.status === 'blocked'
  return i.status === f
}

/** "12 min", "3 h 05 min", "2 d 4 h" from an ISO time to now (or the incident's close). */
export function ageText(fromIso: string | null | undefined, toIso?: string | null, nowMs: number = Date.now()): string {
  if (!fromIso || !Number.isFinite(Date.parse(fromIso))) return '—'
  const end = toIso && Number.isFinite(Date.parse(toIso)) ? Date.parse(toIso) : nowMs
  const m = Math.max(0, Math.floor((end - Date.parse(fromIso)) / 60000))
  if (m < 60) return `${m} min`
  if (m < 1440) return `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, '0')} min`
  return `${Math.floor(m / 1440)} d ${Math.floor((m % 1440) / 60)} h`
}

export function sourceText(i: Incident): string {
  const s = i.source || { kind: '?' }
  const tail = s.watcher ?? s.job ?? s.lane ?? s.session ?? s.agent
  return tail ? `${s.kind} · ${tail}` : s.kind
}

const REPO = 'https://github.com/PatsKiller/tardeai'
/** A fix ref as {label, href?}: PR numbers and commits link to GitHub; receipts and docs are plain text. */
export function refLink(r: FixRef): { label: string; href?: string } {
  if (r.kind === 'pr') {
    const m = /(\d+)$/.exec(r.ref)
    if (/^https:\/\/github\.com\//.test(r.ref)) return { label: m ? `PR #${m[1]}` : r.ref, href: r.ref }
    return m ? { label: `PR #${m[1]}`, href: `${REPO}/pull/${m[1]}` } : { label: r.ref }
  }
  if (r.kind === 'commit' && /^[0-9a-f]{7,40}$/.test(r.ref)) return { label: `commit ${r.ref.slice(0, 9)}`, href: `${REPO}/commit/${r.ref}` }
  return { label: `${r.kind}: ${r.ref}` }
}

export function canAct(i: Incident): { ack: boolean; close: boolean } {
  const terminal = i.status === 'fixed' || i.status === 'closed'
  return { ack: !terminal && !i.acknowledged, close: !terminal }
}

export function sortIncidents(rows: Incident[]): Incident[] {
  return [...rows].sort((a, b) => {
    const sa = STATUS_ORDER.indexOf(a.status), sb = STATUS_ORDER.indexOf(b.status)
    if (sa !== sb) return sa - sb
    const terminal = a.status === 'fixed' || a.status === 'closed'
    return terminal ? Date.parse(b.updated_at) - Date.parse(a.updated_at) : Date.parse(a.opened_at) - Date.parse(b.opened_at)
  })
}
