/** Home v010 — "Today's priorities" (server ranking, LQ-20261107-2644) and the recorded visit.
 *  The ranking is computed by GET /api/v2/home/priorities-live (scripts/lib/home_priorities_live.py); this file only reads and
 *  describes it. A 404 means the endpoint is not deployed (NEEDS BACKEND stays); a failed read is UNKNOWN, never an
 *  empty "nothing to do". The visit is recorded with a POST after the page's reads settle: a page GET never writes. */
import { readOnce, type Read, type ReadState } from './homeV010'

export const PRIORITIES_API = '/api/v2/home/priorities-live'
export const LAST_SEEN_KEY = 'home.last_seen'
export const PRIORITIES_VISIBLE = 5

export interface PriorityWire {
  rank?: number; kind?: string; id?: string; title?: string; why?: string; tier_label?: string
  priority?: string | null; blocks_trading?: boolean; since?: string | null; stale?: boolean; source?: string; owner?: string | null
  goto?: string | null; count?: number; urgent_count?: number | null
}
export interface PrioritiesWire {
  schema?: string; state?: string; items?: PriorityWire[]; count?: number; truncated?: boolean
  unread?: Array<{ input?: string; reason?: string }>; reason?: string | null; order?: string[]
  /** The server's own compute time (absolute, UTC ISO). The page ages it at render; a ranking with no source time
   *  is never drawn as current (campaign item 1). */
  served_at?: string | null
  /** Population evidence (campaign item 4): one entry per input the ranking runs over — whether it was READ, how many
   *  rows it returned, and why not when it was not. Absent on servers that predate the field: the page then says
   *  only what the body's own `state` proves. */
  inputs?: Array<{ input?: string; read?: boolean; rows?: number | null; reason?: string | null }> | null
}
export interface PriorityRow { id: string; rank: number; kind: string; title: string; why: string; tier: string; blocks: boolean; stale: boolean; since: string | null; goto: string | null }
export type PrioritiesState = ReadState | 'PARTIAL' | 'NOT_DEPLOYED'
export interface PrioritiesView {
  state: PrioritiesState; rows: PriorityRow[]; total: number; note: string | null; needsBackend: boolean
  /** The ranking's source time, or null when the body carried none (then the page says so; it never invents one). */
  servedAt: string | null
  /** One line naming each input's population ("incidents 12 rows · approvals 0 rows · stop advice not read"), or
   *  null when the body carries no `inputs` — never a sentence derived from a count the server did not send. */
  evidence: string | null
}

/** The body's `served_at`, carried only when it parses: a bad string is "no source time", not a guess. */
function servedAtOf(d: PrioritiesWire): string | null {
  return typeof d.served_at === 'string' && !Number.isNaN(Date.parse(d.served_at)) ? d.served_at : null
}

/** One line per input, from the server's own `inputs` array. A row count the server did not send is not invented:
 *  "read" without a count stays "read". Absent array -> null (an older server), never a sentence about it. */
function evidenceOf(d: PrioritiesWire): string | null {
  const inputs = Array.isArray(d.inputs) ? d.inputs.filter(x => x && typeof x === 'object') : []
  if (!inputs.length) return null
  return inputs.map(x => {
    const name = String(x.input || 'input')
    if (x.read !== true) return `${name} not read`
    return typeof x.rows === 'number' && Number.isFinite(x.rows) ? `${name} ${x.rows} row${x.rows === 1 ? '' : 's'}` : `${name} read`
  }).join(' · ')
}

/** What the card draws. The server's order is kept exactly (the client never re-ranks). */
export function prioritiesView(r: Read<PrioritiesWire> | undefined): PrioritiesView {
  const none = { servedAt: null, evidence: null }
  if (!r || r.state === 'LOADING') return { state: 'LOADING', rows: [], total: 0, note: 'reading…', needsBackend: false, ...none }
  if (r.state !== 'OK') {
    if (r.error === 'HTTP 404') return { state: 'NOT_DEPLOYED', rows: [], total: 0, note: 'No server ranking in this build; see Action required above.', needsBackend: true, ...none }
    return { state: r.state, rows: [], total: 0, note: `ranking could not be read (${r.error || 'read failed'}) — see Action required above`, needsBackend: false, ...none }
  }
  const d = r.data || {}
  const st = String(d.state || '')
  const items = Array.isArray(d.items) ? d.items : null
  if (!items || !['OK', 'PARTIAL', 'UNKNOWN'].includes(st)) {
    return { state: 'UNKNOWN', rows: [], total: 0, note: 'ranking unreadable: response carried no state / items', needsBackend: false, ...none }
  }
  const unread = (d.unread || []).map(u => `${u.input || 'input'}: ${u.reason || 'not read'}`)
  const servedAt = servedAtOf(d)
  const evidence = evidenceOf(d)
  // A1: the card prints `evidence` beside its own state, so an `OK` body that names an input it did not read would
  // contradict itself in one sentence ("every input was read · … approvals not read"). The producer derives `state`
  // from these same inputs, so this cannot fire on an honest body; it is defence in depth, and it is cheap because
  // the page already holds the evidence. Such a body is drawn as PARTIAL — the all-clear sentence is demoted to the
  // PARTIAL note, which names exactly what was ranked without.
  const unreadInputs = Array.isArray(d.inputs)
    ? d.inputs.filter(x => x && typeof x === 'object' && x.read !== true).map(x => String(x.input || 'input'))
    : []
  const partial = st === 'PARTIAL' || (st === 'OK' && unreadInputs.length > 0)
  const without = unread.length ? unread : unreadInputs.map(i => `${i}: not read`)
  if (st === 'UNKNOWN') return { state: 'UNKNOWN', rows: [], total: 0, note: `no input could be read — ${unread.join('; ')}`, needsBackend: false, servedAt, evidence }
  const rows: PriorityRow[] = items.map((x, n) => ({
    id: x.id || `prio-${n}`, rank: typeof x.rank === 'number' ? x.rank : n + 1, kind: x.kind || 'ITEM', title: x.title || 'untitled',
    why: x.why || 'cause not recorded', tier: x.tier_label || '', blocks: !!x.blocks_trading, stale: !!x.stale, since: x.since || null, goto: x.goto || null,
  }))
  return { state: partial ? 'PARTIAL' : 'OK', rows, total: typeof d.count === 'number' ? d.count : rows.length,
    note: partial ? `ranked without: ${without.join('; ')}` : null, needsBackend: false, servedAt, evidence }
}

export function deviceOf(width: number): 'phone' | 'desktop' { return width < 768 ? 'phone' : 'desktop' }

/** Record this visit (server stamps the time; only the device is sent). Never throws; returns what happened. */
export async function recordVisit(width: number, fetchImpl: typeof fetch = fetch): Promise<'RECORDED' | 'REFUSED' | 'FAILED'> {
  try {
    const r = await fetchImpl('/api/v2/ui/prefs', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, credentials: 'same-origin',
      body: JSON.stringify({ key: LAST_SEEN_KEY, value: { device: deviceOf(width) } }),
    })
    if (r.status === 401 || r.status === 403) return 'REFUSED'
    if (!r.ok) return 'FAILED'
    const body = await r.json().catch(() => null) as { ok?: boolean } | null
    return body && body.ok === false ? 'REFUSED' : 'RECORDED'
  } catch { return 'FAILED' }
}

export { readOnce }
