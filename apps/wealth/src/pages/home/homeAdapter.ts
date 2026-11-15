import type { Envelope } from '../../api/client.ts'
import type { RenderState } from '../../components/renderState.ts'
import { deriveRenderState } from '../../components/renderState.ts'

export type Row = Record<string, unknown>
export type Read = Envelope<unknown> | null
export const record = (v: unknown): Row => v !== null && typeof v === 'object' && !Array.isArray(v) ? v as Row : {}
export const rows = (v: unknown): Row[] => Array.isArray(v) ? v.map(record) : []
export const text = (v: unknown): string => typeof v === 'string' ? v : ''
export const number = (v: unknown): number | null => typeof v === 'number' && Number.isFinite(v) ? v : null
export const clock = (v: unknown): string | null => {
  const s = text(v)
  return /T.*(?:Z|[+-]\d{2}:\d{2})$/.test(s) && Number.isFinite(Date.parse(s)) ? s : null
}
export function body(v: unknown): Row {
  let r = record(v)
  // Preserve nested failures: HTTP 200 is only transport success.
  for (let i = 0; i < 3 && r.data !== undefined; i++) {
    if (r.ok === false || r.error) return r
    r = record(r.data)
  }
  return r
}
export function ageLabel(stamp: unknown, now: number): string {
  const c = clock(stamp)
  return c ? `source ${c} · ${Math.max(0, (now - Date.parse(c)) / 3600000).toFixed(1)} h old` : `${text(stamp) || 'No source time'} · age unknown`
}
export function state<T>(read: Read, map: (r: Row) => T, now: number, stamp?: (r: Row) => unknown, empty?: (v: T) => boolean): RenderState<T> {
  const base = deriveRenderState({ envelope: read, now, spec: {
    path: read?.spec.path ?? '', timeoutMs: 8000, heavy: true, unavailableWhen: [], clock: 'none', note: 'page-owned contract',
  } })
  const convert = (wire: unknown) => {
    const r = body(wire), p = record(r._product)
    const bad = r.ok === false || !!r.error || ['UNKNOWN', 'UNAVAILABLE', 'unavailable', 'no_snapshot', 'not_evaluated'].includes(text(r.state || r.status))
    const stale = r.stale === true || record(r.freshness).stale === true || p.greyed === true || (p.status !== undefined && p.status !== 'OK')
    return { r, bad, stale }
  }
  if (!read || read.data === null) {
    const lg = read?.lastGood === null || !read?.lastGood ? null : convert(read.lastGood)
    return { ...base, data: null, lastGood: lg && !lg.bad ? map(lg.r) : null } as RenderState<T>
  }
  const { r, bad, stale } = convert(read.data)
  const asOf = clock(stamp?.(r)), ageHours = asOf ? Math.max(0, (now - Date.parse(asOf)) / 3600000) : null
  const data = map(r)
  if (bad || stale) return {
    ...base, status: 'UNKNOWN', reason: bad ? 'Source unavailable; no current result can be confirmed.' : 'Source reports stale or greyed data; it is not current.',
    data: null, lastGood: null, asOf, ageHours,
  }
  if (empty?.(data)) return { ...base, status: asOf ? 'EMPTY' : 'UNKNOWN', reason: asOf ? 'No items at the source time.' : 'No items returned; age unknown, so absence is unproven.', data: asOf ? data : null, lastGood: null, asOf, ageHours }
  return { ...base, status: 'OK', data, lastGood: null, asOf, ageHours, healthUnproven: 'Source health is unproven; source and build clocks are shown separately.' }
}
export const money = (v: number | null): string => v === null ? 'Unknown' : new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(v)
export const percent = (v: number | null): string => v === null ? 'Unknown' : `${v > 0 ? '+' : ''}${v.toFixed(2)}%`
export const tone = (v: number | null): string => v === null || v === 0 ? 'money-unknown' : v > 0 ? 'money-gain' : 'money-loss'
export function accountMap(...sources: unknown[]): Map<string, string> {
  const out = new Map<string, string>()
  for (const source of sources) {
    const r = body(source)
    for (const [key, label] of Object.entries(record(r.account_labels))) if (typeof label === 'string' && label !== key) out.set(key, label)
    for (const row of rows(record(r.portfolio_aggregate).accounts)) {
      const key = text(row.account_id || row.account), label = text(row.account_label)
      if (key && label && label !== key) out.set(key, label)
    }
  }
  return out
}
export function safeText(value: unknown, labels: Map<string, string> = new Map()): string {
  let s = text(value)
  for (const [key, label] of [...labels].sort((a, b) => b[0].length - a[0].length)) if (key) s = s.split(key).join(label)
  // Opaque broker identifiers are never a display fallback.
  return s.replace(/\b(?:[A-Z0-9]{8,}|\d{6,}|[a-z]+_[a-z]+_[0-9a-f]{6,})\b/g, '[account withheld]')
}
export function safeUrl(value: unknown): string | null {
  try { const u = new URL(text(value)); return u.protocol === 'https:' && !u.username && !u.password ? u.href : null } catch { return null }
}

export interface Mover { symbol: string; held: boolean | null; price: number | null; change: number | null; impact: number | null; close: string; extended: string }
export interface Story { title: string; publisher: string; published: string; url: string | null; why: string; kind: string }
export interface Priority { title: string; why: string; kind: string; since: string; owner: string }
export interface Overview { value: number | null; source: string; build: string; session: string; accounts: { label: string; value: number | null; source: string }[] }
export interface Snapshot { moves: Mover[]; feed: Story[]; brief: string; quoteClock: string; build: string; macro: { label: string; value: string }[]; week: { title: string; when: string }[] }
export const snapshot = (r: Row): Row => r.snapshot !== undefined ? record(r.snapshot) : r
export function overviewModel(r: Row): Overview {
  const total = record(r.portfolio_total), agg = record(r.portfolio_aggregate), session = record(r.market_session)
  return {
    value: number(total.value), source: text(record(record(r.clock_provenance).quote).as_of), build: text(total.as_of),
    session: text(session.latest_open_session) || text(session.status),
    accounts: rows(agg.accounts).map(a => ({ label: text(a.account_label) && a.account_label !== a.account_id && a.account_label !== a.account ? text(a.account_label) : 'Account label unavailable', value: number(a.total_usd), source: text(a.as_of) })),
  }
}
export function snapshotModel(r: Row, labels: Map<string, string>): Snapshot {
  const s = snapshot(r)
  return {
    moves: rows(s.moves).map(m => ({ symbol: text(m.symbol), held: typeof m.held === 'boolean' ? m.held : null, price: number(m.price), change: number(m.change_pct), impact: number(m.dollar_impact), close: safeText(m.close_tag, labels), extended: text(record(m.extended).label) })),
    feed: rows(s.feed).map(f => ({ title: safeText(f.title, labels), publisher: safeText(f.source, labels), published: text(f.published_at), url: safeUrl(f.url), why: safeText(f.so_what, labels), kind: text(f.kind) })),
    brief: safeText(record(s.cio_brief).summary || record(s.cio_brief).headline, labels),
    quoteClock: text(s.quotes_as_of), build: text(s.generated_at),
    macro: rows(s.macro).map(m => ({ label: safeText(m.label || m.name, labels), value: safeText(m.value, labels) })),
    week: rows(s.week_ahead).map(w => ({ title: safeText(w.title || w.event, labels), when: text(w.date || w.when) })),
  }
}
export function prioritiesModel(r: Row, labels: Map<string, string>): Priority[] {
  return rows(r.items).map((p, i) => ({
    // STOP source titles contain raw account identifiers, so reconstruct that title.
    title: p.kind === 'STOP' ? `Protection review ${i + 1}` : safeText(p.title, labels),
    why: safeText(p.why || p.reason, labels), kind: text(p.kind), since: text(p.since), owner: safeText(p.owner, labels),
  }))
}
export function marketMoversModel(r: Row): Mover[] {
  return Object.values(record(r.signals)).flatMap(s => rows(record(s).rows)).map(m => ({
    symbol: text(m.symbol), held: typeof m.held === 'boolean' ? m.held : null, price: number(m.last), change: number(m.change_pct), impact: null, close: '', extended: '',
  })).filter((m, i, all) => all.findIndex(x => x.symbol === m.symbol) === i)
}
export function homeToday(reads: Record<string, Read>, now: number) {
  const labels = accountMap(reads.overview?.data)
  return {
    overview: state(reads.overview ?? null, overviewModel, now, r => record(record(r.clock_provenance).quote).as_of),
    snapshot: state(reads.snapshot ?? null, r => snapshotModel(r, labels), now, r => snapshot(r).quotes_as_of),
    movers: state(reads.movers ?? null, marketMoversModel, now, r => r.captured_at, m => m.length === 0),
    priorities: state(reads.priorities ?? null, r => prioritiesModel(r, labels), now, undefined, p => p.length === 0),
    labels,
  }
}
export type HomeTodayModel = ReturnType<typeof homeToday>
