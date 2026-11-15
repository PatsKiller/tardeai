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
export const money = (v: number | null): string => {
  if (v === null) return 'Unknown'
  // Whole-dollar rounding would print a real sub-$1 amount as $0; a signed bound is honest, $0 is not.
  if (v !== 0 && Math.abs(v) < 1) return `${v < 0 ? '-<' : '<'}$1`
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(v)
}
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
  return s.replace(/\b(?:[A-Z]{1,3}\d{6,}|[a-z]+_[a-z]+_[0-9a-f]{6,})\b/g, '[account withheld]')
}
export function safeUrl(value: unknown): string | null {
  try { const u = new URL(text(value)); return u.protocol === 'https:' && !u.username && !u.password ? u.href : null } catch { return null }
}

export interface Mover { symbol: string; held: boolean | null; price: number | null; change: number | null; impact: number | null; close: string; extended: string; ext?: { price: number | null; change: number | null; at: string; reference: string; state: string } }
export interface Story { title: string; publisher: string; published: string; url: string | null; why: string; kind: string }
export interface Priority {
  kind: string; title: string; why: string; since: string; owner: string
  status: string; statusLabel: string; stale: boolean | null; staleLabel: string
  scope: string; label: string
}
export interface Priorities { protection: Priority[]; history: Priority[] }
export interface Overview { value: number | null; source: string; build: string; session: string; dataAsOf: string; oldestAccount: string; accounts: { label: string; value: number | null; source: string }[] }
export interface Snapshot {
 moves: Mover[]; feed: Story[]; brief: string; briefAt: string; briefSource: string; quoteClock: string; build: string
 macro: { headlines: Story[]; quotes: { label: string; level: number | null; change: number | null; at: string; session: string; reference: string }[]; status: string; overseas: string }
 week: { title: string; when: string; time: string; kind: string }[]; weekFrom: string; weekTo: string; fedSpeakers: string
}
export const snapshot = (r: Row): Row => r.snapshot !== undefined ? record(r.snapshot) : r
export function overviewModel(r: Row): Overview {
  const total = record(r.portfolio_total), agg = record(r.portfolio_aggregate), session = record(r.market_session), labels = accountMap(r)
  return {
    value: number(total.value), source: text(record(record(r.clock_provenance).quote).as_of), build: text(total.as_of),
    session: text(r.market_session) || text(session.latest_open_session) || text(session.status),
    dataAsOf: text(r.data_as_of), oldestAccount: labels.get(text(r.data_as_of_account)) || (r.data_as_of_account ? 'Account label unavailable' : ''),
    accounts: rows(agg.accounts).map(a => ({ label: labels.get(text(a.account || a.account_id)) || 'Account label unavailable', value: number(a.total_value), source: text(a.position_observation_time) })),
  }
}
export function snapshotModel(r: Row, labels: Map<string, string>): Snapshot {
 const s = snapshot(r), brief = record(s.cio_brief), summary = record(brief.summary), run = record(brief.run)
 const macro = record(s.macro), futures = record(macro.futures), current = record(macro.now), week = record(s.week_ahead)
 const story = (f: Row): Story => ({title:safeText(f.title,labels),publisher:safeText(f.source,labels),published:text(f.published_at),url:safeUrl(f.source_url || f.url),why:safeText(f.so_what,labels),kind:text(f.kind)})
 return {
  moves:rows(s.moves).map(m => {
   const ext = record(m.extended)
   return {symbol:text(m.symbol),held:typeof m.held === 'boolean' ? m.held : null,price:number(m.price),change:number(m.change_pct),impact:number(m.dollar_impact),close:safeText(m.close_tag,labels),extended:text(ext.session_label),
    ext:m.extended ? {price:number(ext.price),change:ext.state === 'print' ? number(ext.change_pct) : null,at:text(ext.printed_at),reference:text(ext.reference_date),state:text(ext.state)} : undefined}
  }),
  feed:rows(s.feed).map(story),
  brief:safeText(run.same_run === false ? run.text : summary.text || brief.summary || brief.headline,labels),
  briefAt:text(brief.as_of),briefSource:text(summary.source),
  quoteClock:text(s.quotes_as_of),build:text(s.generated_at),
  macro:{headlines:rows(macro.headlines).map(story),status:text(futures.status),overseas:safeText(record(current.overseas).label,labels),
   quotes:rows(futures.quotes).map(q=>({label:safeText(q.label || q.symbol,labels),level:number(q.level),change:q.level_only === true ? null : number(q.change_pct),at:text(q.printed_at),session:text(q.session_label),reference:text(q.reference_date)}))},
  week:rows(week.events).map(w=>({title:safeText(w.label,labels),when:text(w.date),time:text(w.time_et),kind:text(w.kind)})),
  weekFrom:text(week.from),weekTo:text(week.to),fedSpeakers:safeText(week.fed_speakers,labels),
 }
}
const KIND_WORD: Record<string, string> = { INCIDENT: 'incident', APPROVALS: 'approval request', STOP: 'stop item' }
/** The producer's STOP title is "<Action> · <symbol> · <account>"; the account segment is a raw key, so only the symbol is kept. */
export function stopScope(p: Row): { symbol: string } | null {
  const symbol = text(p.title).split(' · ')[1]?.trim() || ''
  return /^[A-Z0-9][A-Z0-9.\-]{0,9}$/.test(symbol) ? { symbol } : null
}
export function prioritiesModel(r: Row, labels: Map<string, string>): Priorities {
  const protection: Priority[] = [], history: Priority[] = []
  for (const p of rows(r.items)) {
    const kind = text(p.kind).toUpperCase(), status = text(p.status), stale = typeof p.stale === 'boolean' ? p.stale : null
    const item: Priority = {
      kind, title: safeText(p.title, labels), why: safeText(p.why || p.reason, labels), since: text(p.since), owner: safeText(p.owner, labels),
      status, statusLabel: status ? `Status ${safeText(status, labels)}` : 'Status Unknown',
      stale, staleLabel: stale === null ? 'Freshness not served' : stale ? 'Producer reports stale' : 'Producer reports not stale',
      scope: '', label: '',
    }
    // Only a typed, account-scoped item is a protection fact. Everything else is recorded history: the producer's
    // category is quoted as its source, never restated as this desk's own protection or stop-gap claim, and age
    // alone never resolves a row.
    const scope = kind === 'STOP' ? stopScope(p) : null
    if (scope) protection.push({ ...item, scope: scope.symbol, title: `Protection review ${protection.length + 1}` })
    else history.push({ ...item, label: `Recorded ${KIND_WORD[kind] || `item (${kind || 'kind unrecorded'})`} · source category: ` })
  }
  return { protection, history }
}
export function marketMoversModel(r: Row): Mover[] {
  return Object.values(record(r.signals)).flatMap(s => rows(record(s).rows)).map(m => ({
    symbol: text(m.symbol), held: m.held === true ? true : m.watch === true ? false : null, price: number(m.last), change: number(m.change_pct), impact: null, close: '', extended: '',
  })).filter((m, i, all) => all.findIndex(x => x.symbol === m.symbol) === i)
}
export function homeToday(reads: Record<string, Read>, now: number) {
  const labels = accountMap(reads.overview?.data)
  return {
    overview: state(reads.overview ?? null, overviewModel, now, r => record(record(r.clock_provenance).quote).as_of),
    snapshot: state(reads.snapshot ?? null, r => snapshotModel(r, labels), now, r => snapshot(r).quotes_as_of),
    movers: state(reads.movers ?? null, marketMoversModel, now, r => r.captured_at, m => m.length === 0),
    priorities: state(reads.priorities ?? null, r => prioritiesModel(r, labels), now, undefined, p => p.protection.length === 0 && p.history.length === 0),
    labels,
  }
}
export type HomeTodayModel = ReturnType<typeof homeToday>

export interface ReviewItem { title: string; why: string; category: string; severity: string; since: string; accounts: string[]; thesis: string; horizon: string; evidence: { label: string; value: string }[] }
export interface ReviewQueue { items: ReviewItem[]; sources: { name: string; status: string; asOf: string; basis: string; stale: boolean | null }[]; allAnswered: boolean; anyStale: boolean; servedStale: boolean; severity: { name: string; count: number | null }[] }
export function reviewModel(r: Row): ReviewQueue {
  const labels = accountMap(r)
  for (const item of rows(r.items)) {
    const e = record(item.evidence)
    const keys = Array.isArray(e.accounts) ? e.accounts : []
    const names = Array.isArray(e.account_labels) ? e.account_labels : []
    keys.forEach((key, i) => { if (typeof key === 'string' && typeof names[i] === 'string' && key !== names[i]) labels.set(key, names[i]) })
  }
  return {
    allAnswered: r.all_sources_answered === true, anyStale: r.any_source_stale !== false,
    servedStale: record(r.served).stale === true,
    severity: ['P0', 'P1', 'P2', 'P3'].map(name => ({ name, count: number(record(r.severity_counts)[name]) })),
    sources: Object.entries(record(r.sources)).map(([name, v]) => {
      const s = record(v)
      return { name, status: text(s.status) || 'Unknown', asOf: text(s.as_of), basis: text(s.as_of_basis), stale: typeof s.stale === 'boolean' ? s.stale : null }
    }),
    items: rows(r.items).map(i => {
      const e = record(i.evidence)
      return {
        title: safeText(i.title, labels), why: safeText(i.why, labels),
        category: text(i.category), severity: text(i.severity), since: text(i.since),
        accounts: Array.isArray(e.account_labels) ? e.account_labels.map(v => safeText(v, labels)).filter(Boolean) : text(i.account_label) ? [safeText(i.account_label, labels)] : [],
        thesis: safeText(i.thesis || e.thesis, labels), horizon: safeText(i.horizon || e.horizon, labels),
        evidence: ['symbol', 'reason', 'coverage_verdict', 'fallback_reason', 'money_basis'].flatMap(key => {
          const value = i[key] ?? e[key]
          return typeof value === 'string' ? [{ label: key.replace(/_/g, ' '), value: safeText(value, labels) }] : []
        }),
      }
    }),
  }
}
export interface MarketReport { status: string; greyed: boolean; cause: string }
export interface Market { tier: string; score: number | null; mode: string; asOf: string; built: string; contributors: { name: string; detail: string; points: number | null; asOf: string }[]; categories: { name: string; status: string; detail: string; asOf: string }[]; history: { asOf: string; tier: string; score: number | null }[]; reported?: MarketReport }
export const SCENARIOS = ['IF WEAKNESS PERSISTS', 'IF CONDITIONS STABILIZE', 'IF LEADERSHIP RECOVERS'].map(title => ({ title, availability: 'Not available — methodology pending' }))
export function marketModel(r: Row): Market {
  return {
    tier: text(r.tier) || 'Unknown', score: number(r.score), mode: text(r.mode) || 'Mode unknown', asOf: text(r.as_of), built: text(r.generated_at),
    contributors: rows(r.contributors).map(c => ({ name: safeText(c.name), detail: safeText(c.detail), points: number(c.points), asOf: text(c.as_of) })),
    categories: rows(r.categories).map(c => ({ name: safeText(c.name), status: safeText(c.state), detail: safeText(c.detail), asOf: text(c.as_of) })),
    history: rows(r.history).map(h => ({ asOf: text(h.as_of), tier: text(h.tier), score: number(h.score) })),
  }
}
/** The producer's own verdict on the served copy; null unless it says the copy is not current. */
export function staleReport(r: Row): MarketReport | null {
  const p = record(r._product), ps = record(r.product_stale)
  const status = (text(ps.status) || text(p.status)).toUpperCase(), greyed = ps.greyed === true || p.greyed === true
  // A body that disagrees with its own product ("OK" while the row is marked stale) supports no last-known claim.
  if (!greyed && (status === '' || status === 'OK')) return null
  return { status: status || 'UNKNOWN', greyed, cause: text(ps.reason) || text(p.reason) }
}
/** The producer's own words for why the served copy is not current. Never a client TTL. */
export function staleLabel(rep: { status: string; greyed: boolean }): string {
  if (rep.greyed) return 'producer reports last-good past its hard expiry (greyed)'
  return rep.status === 'STALE' ? 'producer reports stale (age past its declared bound)' : `producer reports ${rep.status.toLowerCase() || 'not current'}`
}
export function marketState(read: Read, now: number): RenderState<Market> {
  if (read?.data !== null && read?.data !== undefined) {
    const r = body(read.data), c = clock(r.as_of)
    // Freshness is the stored producer's verdict, evaluated at its own build time.
    // Its rounded age and previous-hour input cannot be replaced by an exact client one-hour gate.
    if (r.ok === false || r.error || r.state !== 'evaluated' || r.stale !== false || !c || record(r._product).status !== 'OK' || record(r._product).greyed === true) {
      const detail = safeText(r.error || r.reason), rep = staleReport(r)
      // The serving layer keeps a stale tier and marks it stale (risk display rule, operator 13 Nov 2026).
      // Show that copy as dated last-known, never as current: data stays null, the cause is the producer's own
      // reason, the source observation time is preserved, and no age bound or TTL is invented here.
      const last = rep && text(r.tier) ? { ...marketModel(r), reported: rep } : null
      const why = rep ? `${staleLabel(rep)}${rep.cause ? ` — ${rep.cause}` : ''}` : ''
      const reason = last
        ? `Not current: ${why}. The last stored assessment is shown with its own source time and is not current.`
        : `Market nowcast unavailable or source verdict unproven. An evaluated state, explicit nonstale producer verdict, OK product and zoned source time are required.${detail ? ' Source: ' + detail : ''}`
      return { status: 'UNKNOWN', reason, data: null, lastGood: last, lastGoodAgeSeconds: c ? Math.max(0, Math.round((now - Date.parse(c)) / 1000)) : null, asOf: c, ageHours: c ? Math.max(0, (now - Date.parse(c)) / 3600000) : null, healthUnproven: null }
    }
  }
  return state(read, marketModel, now, r => r.as_of)
}

export function cioContextModel(r: Row, labels: Map<string,string>) {
 const advice=record(r.advice), card=record(r.card), eligible=advice.ok===true && r.advisory_only===true
 return {
  built:text(r.generated_at),eligible,reason:safeText(advice.reason,labels),
  facts:eligible ? ['posture','tier','score','buys_line'].flatMap(key=>{
   const f=record(card[key]),value=typeof f.value==='number' ? String(f.value) : safeText(f.value,labels)
   return value ? [{label:key.replace(/_/g,' '),value,at:text(f.as_of)}] : []
  }) : [],
  inputs:Object.entries(record(r.inputs)).map(([name,v])=>({name:name.replace(/_/g,' '),at:text(record(v).as_of),present:record(v).present===true,stale:record(v).stale===true,role:safeText(record(v).role,labels)})),
  notes:rows(r.notes).map(n=>({title:safeText(n.topic,labels),text:safeText(n.text,labels),at:text(n.as_of)})),
 }
}
