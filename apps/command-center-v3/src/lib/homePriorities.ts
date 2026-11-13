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
}
export interface PriorityRow { id: string; rank: number; kind: string; title: string; why: string; tier: string; blocks: boolean; stale: boolean; since: string | null; goto: string | null }
export type PrioritiesState = ReadState | 'PARTIAL' | 'NOT_DEPLOYED'
export interface PrioritiesView { state: PrioritiesState; rows: PriorityRow[]; total: number; note: string | null; needsBackend: boolean }

/** What the card draws. The server's order is kept exactly (the client never re-ranks). */
export function prioritiesView(r: Read<PrioritiesWire> | undefined): PrioritiesView {
  if (!r || r.state === 'LOADING') return { state: 'LOADING', rows: [], total: 0, note: 'reading…', needsBackend: false }
  if (r.state !== 'OK') {
    if (r.error === 'HTTP 404') return { state: 'NOT_DEPLOYED', rows: [], total: 0, note: 'No server ranking in this build; see Action required above.', needsBackend: true }
    return { state: r.state, rows: [], total: 0, note: `ranking could not be read (${r.error || 'read failed'}) — see Action required above`, needsBackend: false }
  }
  const d = r.data || {}
  const st = String(d.state || '')
  const items = Array.isArray(d.items) ? d.items : null
  if (!items || !['OK', 'PARTIAL', 'UNKNOWN'].includes(st)) {
    return { state: 'UNKNOWN', rows: [], total: 0, note: 'ranking unreadable: response carried no state / items', needsBackend: false }
  }
  const unread = (d.unread || []).map(u => `${u.input || 'input'}: ${u.reason || 'not read'}`)
  if (st === 'UNKNOWN') return { state: 'UNKNOWN', rows: [], total: 0, note: `no input could be read — ${unread.join('; ')}`, needsBackend: false }
  const rows: PriorityRow[] = items.map((x, n) => ({
    id: x.id || `prio-${n}`, rank: typeof x.rank === 'number' ? x.rank : n + 1, kind: x.kind || 'ITEM', title: x.title || 'untitled',
    why: x.why || 'cause not recorded', tier: x.tier_label || '', blocks: !!x.blocks_trading, stale: !!x.stale, since: x.since || null, goto: x.goto || null,
  }))
  return { state: st === 'PARTIAL' ? 'PARTIAL' : 'OK', rows, total: typeof d.count === 'number' ? d.count : rows.length,
    note: st === 'PARTIAL' ? `ranked without: ${unread.join('; ')}` : null, needsBackend: false }
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
