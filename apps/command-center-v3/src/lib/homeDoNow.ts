// Home "Do now" (operator-approved Home redesign, 2026-10-22). Pure helpers for the new Home page:
//   - doNowFrom: GET /api/v2/home/do-now (HomeDoNow@v1) → tab model. "Nothing to do" only when every source answered;
//     a fetch error, a missing payload or a PARTIAL answer is never an empty green (the needs-action invariant).
//   - positionsFreshness: the header STALE badge (holdings envelope age; 30 min SLA in market hours).
//   - moversBars / accountRows / cashPct: the right-column numbers, each with the tooltip text that names its source.
// Positions come from holdings.json via /api/v2/overview and the risk snapshot: no approved positions_current reader
// batch covers Home yet (batch #1 is the Watch held flag), so every number says so.

export type Severity = 'P0' | 'P1' | 'P2' | 'P3'
export type Category = 'protect' | 'decide' | 'fix'
export type Tab = 'all' | Category
export const SEVERITIES: Severity[] = ['P0', 'P1', 'P2', 'P3']
export const TABS: { key: Tab; label: string }[] = [
  { key: 'all', label: 'All' },
  { key: 'protect', label: 'Protect money' },
  { key: 'decide', label: 'Decide' },
  { key: 'fix', label: 'Fix system' },
]
export const TOP_N = 7
export const STALE_AFTER_S = 300
export const POSITIONS_SLA_MARKET_S = 30 * 60

export interface DoNowItem {
  id: string
  category: Category
  severity: Severity
  title: string
  why: string
  actionLabel: string
  where: string           // router path inside the /v3 basename
  money: number | null
  moneyBasis: string | null
  sources: string[]
  since: string | null
}

export interface DoNowSource { name: string; status: string; asOf: string | null; basis: string | null; ageS: number | null; stale: boolean; error: string | null }

export interface DoNowNumbers {
  available: boolean
  unprotected: number | null
  unprotectedValue: number | null
  unprotectedBasis: string
  heatPct: number | null
  heatLimitPct: number
  heatBasis: string
  positionsSource: string
  asOf: string | null
  stale: boolean
}

export interface DoNowModel {
  state: 'LOADING' | 'UNAVAILABLE' | 'ITEMS' | 'CLEAR' | 'STALE'
  items: DoNowItem[]
  counts: Record<Tab, number>
  allSourcesAnswered: boolean
  sources: DoNowSource[]
  unavailableSources: string[]
  staleSources: string[]
  asOf: string | null
  reason: string | null
  rolledUp: { raw: number | null; afterDedupe: number | null; inboxTotal: number | null; needsActionTotal: number | null }
  numbers: DoNowNumbers
}

/** "/v3/risk?symbol=X" → "/risk?symbol=X" (router basename is /v3). Non-CC paths fall back to "/". */
export function routerPath(where: unknown): string {
  const w = typeof where === 'string' ? where : ''
  if (w === '/v3' || w === '/v3/') return '/'
  if (w.startsWith('/v3/') || w.startsWith('/v3?')) return w.slice(3)
  return w.startsWith('/') && !w.startsWith('//') ? w : '/'
}

const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null)
const str = (v: unknown): string | null => (typeof v === 'string' && v ? v : null)
const CATS: Category[] = ['protect', 'decide', 'fix']

function numbersFrom(n: any): DoNowNumbers {
  const ok = n && typeof n === 'object' && n.status === 'OK'
  return {
    available: !!ok,
    unprotected: ok ? num(n.unprotected_positions) : null,
    unprotectedValue: ok ? num(n.unprotected_value_usd) : null,
    unprotectedBasis: (ok && str(n.unprotected_basis)) || 'unavailable',
    heatPct: ok ? num(n.heat_pct) : null,
    heatLimitPct: (ok && num(n.heat_limit_pct)) || 5,
    heatBasis: (ok && str(n.heat_basis)) || 'unavailable',
    positionsSource: (ok && str(n.positions_source)) || 'unavailable',
    asOf: ok ? str(n.as_of) : null,
    stale: !!(ok && n.stale),
  }
}

export function doNowFrom(
  payload: any,
  opts: { loading?: boolean; error?: unknown; nowMs?: number; staleAfterS?: number } = {},
): DoNowModel {
  const empty = {
    items: [] as DoNowItem[], counts: { all: 0, protect: 0, decide: 0, fix: 0 } as Record<Tab, number>,
    allSourcesAnswered: false, sources: [] as DoNowSource[], unavailableSources: [] as string[], staleSources: [] as string[],
    asOf: null, rolledUp: { raw: null, afterDedupe: null, inboxTotal: null, needsActionTotal: null }, numbers: numbersFrom(null),
  }
  if (!payload || typeof payload !== 'object') {
    if (opts.loading && !opts.error) return { state: 'LOADING', ...empty, reason: null }
    return { state: 'UNAVAILABLE', ...empty, reason: opts.error ? String(opts.error) : 'no payload' }
  }
  if (payload.schema !== 'HomeDoNow@v1' || !Array.isArray(payload.items)) return { state: 'UNAVAILABLE', ...empty, reason: 'malformed payload' }
  const items: DoNowItem[] = payload.items
    .filter((i: any) => i && SEVERITIES.includes(i.severity) && CATS.includes(i.category))
    .map((i: any) => ({
      id: String(i.id ?? ''), category: i.category as Category, severity: i.severity as Severity,
      title: String(i.title ?? ''), why: String(i.why ?? ''),
      actionLabel: String(i.action?.label ?? 'Open'), where: routerPath(i.action?.where),
      money: num(i.money_at_risk_usd), moneyBasis: str(i.money_basis),
      sources: Array.isArray(i.sources) ? i.sources.map(String) : [], since: str(i.since),
    }))
  // The server sorts (money at risk, then severity, then category); the client keeps that order.
  const counts: Record<Tab, number> = { all: items.length, protect: 0, decide: 0, fix: 0 }
  for (const i of items) counts[i.category]++
  const srcObj = payload.sources && typeof payload.sources === 'object' ? payload.sources : {}
  const sources: DoNowSource[] = Object.entries(srcObj).map(([name, s]: [string, any]) => ({
    name, status: String(s?.status ?? 'UNKNOWN'), asOf: str(s?.as_of), basis: str(s?.as_of_basis),
    ageS: num(s?.age_s), stale: !!s?.stale, error: str(s?.error),
  }))
  const unavailableSources = sources.filter(s => s.status !== 'OK' && s.status !== 'NO_RECEIPT').map(s => s.name)
  const staleSources = sources.filter(s => s.stale).map(s => s.name)
  const allSourcesAnswered = payload.all_sources_answered === true && unavailableSources.length === 0
  const asOf = str(payload.as_of)
  const ru = payload.rolled_up ?? {}
  const common = {
    items, counts, allSourcesAnswered, sources, unavailableSources, staleSources, asOf,
    rolledUp: { raw: num(ru.raw_items), afterDedupe: num(ru.after_dedupe), inboxTotal: num(ru.inbox_total), needsActionTotal: num(ru.needs_action_total) },
    numbers: numbersFrom(payload.numbers),
  }
  if (opts.error) return { state: 'STALE', ...common, reason: `refresh failed: ${String(opts.error)}` }
  if (opts.nowMs != null && asOf) {
    const age = (opts.nowMs - Date.parse(asOf)) / 1000
    if (Number.isFinite(age) && age > (opts.staleAfterS ?? STALE_AFTER_S)) return { state: 'STALE', ...common, reason: `as of ${asOf}` }
  }
  if (items.length === 0 && allSourcesAnswered) return { state: 'CLEAR', ...common, reason: null }
  if (items.length === 0) return { state: 'UNAVAILABLE', ...common, reason: 'not every source answered' }
  return { state: 'ITEMS', ...common, reason: null }
}

export function visibleItems(m: DoNowModel, tab: Tab, showAll: boolean, topN = TOP_N): { shown: DoNowItem[]; total: number } {
  const filtered = tab === 'all' ? m.items : m.items.filter(i => i.category === tab)
  return { shown: showAll ? filtered : filtered.slice(0, topN), total: filtered.length }
}

export function severityTone(s: Severity): 'danger' | 'warning' | 'info' {
  return s === 'P0' || s === 'P1' ? 'danger' : s === 'P2' ? 'warning' : 'info'
}

export function ageLabel(s: number | null): string {
  if (s == null || !Number.isFinite(s) || s < 0) return 'age unknown'
  if (s < 90) return `${Math.round(s)} s`
  if (s < 5400) return `${Math.round(s / 60)} min`
  if (s < 172800) return `${Math.round(s / 3600)} h`
  return `${Math.round(s / 86400)} d`
}

export function money(v: number | null | undefined, signed = false): string {
  if (v == null || !Number.isFinite(v)) return '—'
  const abs = '$' + Math.round(Math.abs(v)).toLocaleString('en-US')
  if (!signed) return v < 0 ? `−${abs}` : abs
  return (v < 0 ? '−' : v > 0 ? '+' : '') + abs
}

export function pct(v: number | null | undefined, signed = true, digits = 2): string {
  if (v == null || !Number.isFinite(v)) return '—'
  const s = Math.abs(v).toFixed(digits) + '%'
  return signed ? (v < 0 ? '−' : v > 0 ? '+' : '') + s : (v < 0 ? '−' : '') + s
}

/** True during regular US equity hours (Mon–Fri 09:30–16:00 America/New_York). Holidays are not modelled: on a
 *  holiday this errs toward calling 30-minute-old positions STALE, never toward calling old data fresh. */
export function inMarketHours(nowMs: number): boolean {
  const parts = new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', weekday: 'short', hour: '2-digit', minute: '2-digit', hour12: false })
    .formatToParts(new Date(nowMs))
  const get = (t: string) => parts.find(p => p.type === t)?.value ?? ''
  const wd = get('weekday')
  if (wd === 'Sat' || wd === 'Sun') return false
  const mins = (Number(get('hour')) % 24) * 60 + Number(get('minute'))
  return mins >= 570 && mins < 960
}

export interface PositionsFreshness { stale: boolean; ageS: number | null; label: string; tip: string }

/** The header badge. Source: /api/v2/overview observation.envelopes.holdings (holdings.json). STALE when the server
 *  says not FRESH, when there is no observation time, or when positions are older than 30 min in market hours (the
 *  positions_store freshness SLA in docs/architecture/DATA_DICTIONARY.md). */
export function positionsFreshness(overview: any, nowMs: number): PositionsFreshness {
  const env = overview?.observation?.envelopes?.holdings
  const observed = str(env?.observed_at) ?? str(overview?.last_repriced)
  const t = observed ? Date.parse(observed) : NaN
  const ageS = Number.isFinite(t) ? Math.max(0, (nowMs - t) / 1000) : null
  const server = str(env?.freshness?.status)
  const market = inMarketHours(nowMs)
  const overSla = ageS != null && market && ageS > POSITIONS_SLA_MARKET_S
  const stale = ageS == null || (server != null && server !== 'FRESH') || overSla
  const why = ageS == null ? 'no observation time on the holdings envelope'
    : server != null && server !== 'FRESH' ? `server freshness ${server}`
    : overSla ? 'older than the 30 min market-hours SLA' : market ? 'within the 30 min market-hours SLA' : 'market closed; the 24 h file threshold applies'
  return {
    stale, ageS,
    label: `Positions ${ageLabel(ageS)} old${stale ? ' · STALE' : ''}`,
    tip: `Holdings observed ${observed ?? 'UNKNOWN'} (holdings.json via /api/v2/overview; positions_current is not yet approved for Home). ${why}.`,
  }
}

export interface MoverBar { sym: string; amount: number; widthPct: number; negative: boolean; dayPct: number | null }

/** "What moved your book today": overview.top_movers (dollar day change per holding), largest absolute first.
 *  The bar width is relative to the largest absolute move shown. */
export function moversBars(overview: any, max = 6): { bars: MoverBar[]; shownSum: number; total: number | null } {
  const rows = (Array.isArray(overview?.top_movers) ? overview.top_movers : [])
    .map((m: any) => ({ sym: String(m?.symbol ?? ''), amount: num(m?.day_change), dayPct: num(m?.day_change_pct) }))
    .filter((m: any) => m.sym && m.amount != null && m.amount !== 0)
    .sort((a: any, b: any) => Math.abs(b.amount) - Math.abs(a.amount))
    .slice(0, max)
  const top = rows.length ? Math.abs(rows[0].amount) : 0
  const bars = rows.map((m: any) => ({ sym: m.sym, amount: m.amount, dayPct: m.dayPct, negative: m.amount < 0,
    widthPct: top ? Math.max(4, Math.round(Math.abs(m.amount) / top * 100)) : 0 }))
  return { bars, shownSum: bars.reduce((s: number, b: MoverBar) => s + b.amount, 0), total: num(overview?.today_change) }
}

export interface AccountRow { key: string; name: string; value: number | null; d1: number | null; ytd: number | null; ytdApprox: boolean; tip: string }

export function accountName(a: string): string {
  return a.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}

function periodChange(d: any): { ch: number | null; approx: boolean; note: string | null } {
  if (!d || typeof d !== 'object') return { ch: null, approx: false, note: null }
  const preferDisp = Boolean(d.nav_is_not_market_only || d.display_change != null)
  const ch = num(preferDisp && d.display_change != null ? d.display_change : d.change)
  return { ch, approx: Boolean(d.nav_is_not_market_only || d.is_false_positive), note: [d.display_label, d.adjustment_note].filter(Boolean).join(' · ') || null }
}

/** Accounts table: value, 1D, YTD from /api/v2/portfolio/performance (display_change preferred, i.e. ex-transfers
 *  when flagged, the same rule as Portfolio → Returns); 1D falls back to overview.today_by_account. */
export function accountRows(perf: any, overview: any): AccountRow[] {
  const rows: AccountRow[] = []
  const all1d = periodChange(perf?.periods?.['1D'])
  const allYtd = periodChange(perf?.periods?.YTD)
  const allValue = num(perf?.current_value) ?? num(overview?.portfolio_value)
  if (allValue != null || all1d.ch != null) {
    rows.push({ key: 'all', name: 'All accounts', value: allValue, d1: all1d.ch ?? num(overview?.today_change), ytd: allYtd.ch, ytdApprox: allYtd.approx,
      tip: ['All accounts · /api/v2/portfolio/performance', allYtd.approx ? 'YTD ≈ market change ex-transfers' : null, allYtd.note].filter(Boolean).join('\n') })
  }
  const accts = perf?.accounts && typeof perf.accounts === 'object' ? perf.accounts : null
  if (accts) {
    for (const [k, row] of Object.entries(accts) as [string, any][]) {
      const d1 = periodChange(row?.periods?.['1D'])
      const y = periodChange(row?.periods?.YTD)
      rows.push({ key: k, name: accountName(k), value: num(row?.current_value), d1: d1.ch ?? num(overview?.today_by_account?.[k]?.change),
        ytd: y.ch, ytdApprox: y.approx, tip: [`${accountName(k)} · /api/v2/portfolio/performance`, y.approx ? 'YTD ≈ market change ex-transfers' : null, y.note].filter(Boolean).join('\n') })
    }
  } else if (overview?.today_by_account && typeof overview.today_by_account === 'object') {
    for (const [k, row] of Object.entries(overview.today_by_account) as [string, any][]) {
      rows.push({ key: k, name: accountName(k), value: num(row?.value), d1: num(row?.change), ytd: null, ytdApprox: false,
        tip: `${accountName(k)} · /api/v2/overview today_by_account (performance unavailable; YTD unknown)` })
    }
  }
  return rows
}

/** Cash as % of the book from /api/v2/overview (total_cash / portfolio_value). null when either is missing. */
export function cashPct(overview: any): number | null {
  const cash = num(overview?.total_cash)
  const pv = num(overview?.portfolio_value)
  if (cash == null || pv == null || pv <= 0) return null
  return (cash / pv) * 100
}
