/** Ticker Prospectus — pure view model (contract: handoffs/prospectus-20261026/CONTRACT.md, operator-approved
 *  2026-10-26). Shapes mirror the API exactly; every function here is pure (no network, no React) so it runs in the
 *  build as `node --experimental-strip-types src/lib/prospectusModel.test.ts`.
 *
 *  API (portfolio-server, read-only GETs; operator-only POST):
 *    GET  /api/v2/prospectus/index
 *    GET  /api/v2/prospectus/{symbol}[?version=]
 *    GET  /api/v2/prospectus/{symbol}/file/{html|pdf|docx}[?version=]
 *    POST /api/v2/prospectus/{symbol}/refresh
 */
import { readableTime } from './readableTime.ts'

export type ProspectusStatus = 'ready' | 'partial' | 'queued' | 'running' | 'failed' | 'missing'
export type ProspectusScope = 'holding' | 'watch'
export type ProspectusFileKind = 'pdf' | 'docx' | 'html'
export type ScopeFilter = 'holdings' | 'watch' | 'all' | 'rewrite'

export type ProspectusIndexItem = {
  symbol: string
  name?: string | null
  scope: ProspectusScope
  version?: string | null
  generated_at?: string | null
  model?: string | null
  cost_usd?: number | string | null
  status: ProspectusStatus
  stale?: boolean
  next_due?: string | null
  verdict_line?: string | null
  /** Optional, additive: why the last run failed (shown on failed rows when present). */
  failure_reason?: string | null
}

export type ProspectusBudget = {
  credit_remaining_usd?: number | string | null
  today_used_usd?: number | string | null
  daily_cap_usd?: number | string | null
}

/** Optional, additive (not in the 10-26 contract): the server says whether this viewer is the operator.
 *  "Rewrite now" renders only when `viewer.operator === true`; absent means hidden (fail closed). */
export type ProspectusViewer = { operator?: boolean }

export type ProspectusIndex = {
  items: ProspectusIndexItem[]
  totals?: { ready?: number; queued?: number; missing?: number; failed?: number; running?: number }
  budget?: ProspectusBudget
  viewer?: ProspectusViewer
}

export type ProspectusCitation = { id: string; source: string; as_of?: string | null; url?: string | null }
export type ProspectusSection = { id: string; title: string; body_md: string; citations?: ProspectusCitation[] }
export type ChartPoint = [string | number, number | null]
export type ChartSeries = { name: string; points: ChartPoint[] }
export type ChartAnnotation = { kind?: string; label?: string; y?: number | null; x?: string | number | null; low?: number | null; high?: number | null }
export type ProspectusChart = { id: string; type: string; title: string; series: ChartSeries[]; annotations?: ChartAnnotation[] }
export type ProspectusVersion = { version: string; generated_at?: string | null; model?: string | null }

export type ProspectusDoc = {
  symbol: string
  name?: string | null
  scope?: ProspectusScope
  version?: string | null
  generated_at?: string | null
  model?: string | null
  status?: ProspectusStatus
  stale?: boolean
  failure_reason?: string | null
  verdict_line?: string | null
  sections?: ProspectusSection[]
  charts?: ProspectusChart[]
  versions?: ProspectusVersion[]
  viewer?: ProspectusViewer
  /** Institutional blocks computed by the backend from house data (never model output). Each may be absent. */
  blocks?: ProspectusBlocks
  source_coverage?: SourceCoverage
  partial_gaps?: string[]
  facts?: ProspectusFact[]
  inputs_digest?: Record<string, unknown>
  next_due?: string | null
  mode?: string
}

export const API_BASE = '/api/v2/prospectus'
export const STATUSES: readonly ProspectusStatus[] = ['ready', 'partial', 'queued', 'running', 'failed', 'missing'] as const

/** Contract section order. Unknown ids keep their payload order after these. */
export const SECTION_ORDER = ['summary_verdict', 'business_and_moat', 'financials_and_trend', 'valuation_vs_peers',
  'catalysts_and_dates', 'risks', 'analyst_view', 'thesis_breakers', 'position_and_plan'] as const

/** Each section gets its own accent so the report reads as colored, sectioned blocks (tone names, never hex). */
export const SECTION_TONE: Record<string, 'success' | 'warning' | 'danger' | 'info' | 'ai' | 'neutral'> = {
  summary_verdict: 'ai', business_and_moat: 'info', financials_and_trend: 'success', valuation_vs_peers: 'info',
  catalysts_and_dates: 'warning', risks: 'danger', analyst_view: 'ai', thesis_breakers: 'danger', position_and_plan: 'success',
}

export function indexPath(): string { return `${API_BASE}/index` }

export function detailPath(symbol: string, version?: string | null): string {
  const base = `${API_BASE}/${encodeURIComponent(normSymbol(symbol))}`
  return version ? `${base}?version=${encodeURIComponent(version)}` : base
}

export function filePath(symbol: string, kind: ProspectusFileKind, version?: string | null): string {
  const base = `${API_BASE}/${encodeURIComponent(normSymbol(symbol))}/file/${kind}`
  return version ? `${base}?version=${encodeURIComponent(version)}` : base
}

export function refreshPath(symbol: string): string { return `${API_BASE}/${encodeURIComponent(normSymbol(symbol))}/refresh` }

/** App route (react-router, under the /v3 base). */
export function pageRoute(symbol?: string | null): string { return symbol ? `/prospectus/${encodeURIComponent(normSymbol(symbol))}` : '/prospectus' }

export function normSymbol(s: unknown): string { return String(s ?? '').trim().toUpperCase() }

/** "Needs rewrite": stale or failed (the operator's chip in the approved mockup). */
export function needsRewrite(item: Pick<ProspectusIndexItem, 'stale' | 'status'>): boolean {
  return !!item.stale || item.status === 'failed'
}

export function scopeMatches(item: Pick<ProspectusIndexItem, 'scope' | 'stale' | 'status'>, f: ScopeFilter): boolean {
  if (f === 'all') return true
  if (f === 'rewrite') return needsRewrite(item)
  return f === 'holdings' ? item.scope === 'holding' : item.scope === 'watch'
}

export function searchMatches(item: Pick<ProspectusIndexItem, 'symbol' | 'name' | 'verdict_line'>, q: string): boolean {
  const s = q.trim().toLowerCase()
  if (!s) return true
  return [item.symbol, item.name, item.verdict_line].some(v => String(v ?? '').toLowerCase().includes(s))
}

const STATUS_RANK: Record<ProspectusStatus, number> = { failed: 0, running: 1, queued: 2, partial: 3, ready: 3, missing: 4 }

/** Holdings first, then failures/stale up top within a scope, then alphabetical. Deterministic. */
export function sortItems(items: ProspectusIndexItem[]): ProspectusIndexItem[] {
  return [...items].sort((a, b) =>
    (a.scope === b.scope ? 0 : a.scope === 'holding' ? -1 : 1)
    || (STATUS_RANK[a.status] ?? 9) - (STATUS_RANK[b.status] ?? 9)
    || Number(!!b.stale) - Number(!!a.stale)
    || a.symbol.localeCompare(b.symbol))
}

export function filterItems(items: ProspectusIndexItem[], f: ScopeFilter, q: string, status: ProspectusStatus | 'any' = 'any'): ProspectusIndexItem[] {
  return sortItems(items.filter(i => scopeMatches(i, f) && searchMatches(i, q) && (status === 'any' || i.status === status)))
}

export function scopeCounts(items: ProspectusIndexItem[]): Record<ScopeFilter, number> {
  return { holdings: items.filter(i => i.scope === 'holding').length, watch: items.filter(i => i.scope === 'watch').length,
    all: items.length, rewrite: items.filter(needsRewrite).length }
}

/** Totals from the server when present, else counted from items (never invented). */
export function totals(idx: ProspectusIndex | null | undefined): Record<ProspectusStatus, number> {
  const items = idx?.items ?? []
  const counted = Object.fromEntries(STATUSES.map(s => [s, items.filter(i => i.status === s).length])) as Record<ProspectusStatus, number>
  const t = idx?.totals ?? {}
  return {
    partial: numOr((t as Record<string, unknown>).partial, counted.partial),
    ready: numOr(t.ready, counted.ready), queued: numOr(t.queued, counted.queued), running: numOr(t.running, counted.running),
    failed: numOr(t.failed, counted.failed), missing: numOr(t.missing, counted.missing),
  }
}

function numOr(v: unknown, d: number): number { const n = Number(v); return v != null && Number.isFinite(n) ? n : d }

export function toNumber(v: unknown): number | null {
  if (v == null || v === '') return null
  const n = Number(v)
  return Number.isFinite(n) ? n : null
}

export function usd(v: unknown): string {
  const n = toNumber(v)
  return n == null ? '—' : `$${n.toFixed(2)}`
}

/** Credit budget line: remaining, today used / daily cap, and a 0..1 fill for the meter. */
export function budgetView(b: ProspectusBudget | null | undefined): { remaining: string; used: string; cap: string; fill: number | null; tone: 'success' | 'warning' | 'danger' | 'neutral' } {
  const used = toNumber(b?.today_used_usd), cap = toNumber(b?.daily_cap_usd), rem = toNumber(b?.credit_remaining_usd)
  const fill = used != null && cap != null && cap > 0 ? Math.max(0, Math.min(1, used / cap)) : null
  const tone = fill == null ? 'neutral' : fill >= 1 ? 'danger' : fill >= 0.8 ? 'warning' : 'success'
  return { remaining: usd(rem), used: usd(used), cap: usd(cap), fill, tone }
}

/** Model chip: claude-fable-* → Fable, claude-opus-* → Opus, anything else shown as given (short). */
export function modelLabel(model: unknown): { label: string; tier: 'fable' | 'opus' | 'other' | 'none' } {
  const m = String(model ?? '').toLowerCase()
  if (!m) return { label: '—', tier: 'none' }
  if (m.includes('fable')) return { label: 'Fable', tier: 'fable' }
  if (m.includes('opus')) return { label: 'Opus', tier: 'opus' }
  return { label: String(model).replace(/^claude-/, '').slice(0, 18), tier: 'other' }
}

export const STATUS_LABEL: Record<ProspectusStatus, string> = { ready: 'Ready', partial: 'Partial', queued: 'Queued', running: 'Writing', failed: 'Failed', missing: 'Missing' }
export const STATUS_TONE: Record<ProspectusStatus, 'success' | 'warning' | 'danger' | 'info' | 'neutral'> = {
  ready: 'success', partial: 'warning', queued: 'info', running: 'info', failed: 'danger', missing: 'danger',
}

/** Row status chip: a stale ready report reads "Needs rewrite" (approved mockup). */
export function rowStatus(item: Pick<ProspectusIndexItem, 'status' | 'stale'>): { label: string; tone: 'success' | 'warning' | 'danger' | 'info' | 'neutral' } {
  const st = statusOf(item.status)
  if (item.stale && (st === 'ready' || st === 'partial')) return { label: 'Needs rewrite', tone: 'warning' }
  return { label: STATUS_LABEL[st], tone: STATUS_TONE[st] }
}

export function statusOf(v: unknown): ProspectusStatus {
  const s = String(v ?? '').toLowerCase()
  return (STATUSES as readonly string[]).includes(s) ? s as ProspectusStatus : 'missing'
}

/** ET, readable; date-only stamps stay dates. Never a raw ISO string on screen. */
export function whenEt(iso: unknown): string {
  if (!iso) return '—'
  return (readableTime(iso) ?? '—').replace(/ \(date only\)$/, '')
}

/** Sections in contract order; unknown ids after, in payload order; empty bodies dropped (no empty bullets). */
export function orderedSections(sections: ProspectusSection[] | null | undefined, scope?: ProspectusScope): ProspectusSection[] {
  const list = (sections ?? []).filter(s => s && String(s.body_md ?? '').trim())
    .filter(s => !(s.id === 'position_and_plan' && scope === 'watch'))
  const rank = (id: string) => { const i = (SECTION_ORDER as readonly string[]).indexOf(id); return i < 0 ? SECTION_ORDER.length : i }
  return list.map((s, i) => ({ s, i })).sort((a, b) => rank(a.s.id) - rank(b.s.id) || a.i - b.i).map(x => x.s)
}

/** Markdown blocks (no HTML is ever injected): headings, bullet / numbered items, paragraphs. */
export type MdBlock = { kind: 'h' | 'li' | 'oli' | 'p'; text: string; level?: number }
export function mdBlocks(md: string): MdBlock[] {
  const out: MdBlock[] = []
  let para: string[] = []
  const flush = () => { if (para.length) { out.push({ kind: 'p', text: para.join(' ') }); para = [] } }
  for (const raw of String(md ?? '').replace(/\r\n/g, '\n').split('\n')) {
    const line = raw.trim()
    if (!line) { flush(); continue }
    if (/^([-*•]|\d+[.)])$/.test(line)) { flush(); continue }  // an empty bullet is never rendered
    const h = /^(#{1,4})\s+(.*)$/.exec(line)
    const li = /^[-*•]\s+(.*)$/.exec(line)
    const oli = /^\d+[.)]\s+(.*)$/.exec(line)
    if (h) { flush(); out.push({ kind: 'h', text: h[2], level: h[1].length }) }
    else if (li) { flush(); if (li[1].trim()) out.push({ kind: 'li', text: li[1] }) }
    else if (oli) { flush(); if (oli[1].trim()) out.push({ kind: 'oli', text: oli[1] }) }
    else para.push(line)
  }
  flush()
  return out
}

/** Split text on inline citation markers `[c1]` / `[^c1]` whose id is a known citation. */
export function splitCitations(text: string, ids: Set<string>): Array<{ text: string } | { cite: string }> {
  const out: Array<{ text: string } | { cite: string }> = []
  const re = /\[\^?([A-Za-z0-9_.:-]+)\](?!\()/g
  let last = 0
  for (const m of text.matchAll(re)) {
    if (!ids.has(m[1])) continue
    if (m.index! > last) out.push({ text: text.slice(last, m.index) })
    out.push({ cite: m[1] })
    last = m.index! + m[0].length
  }
  if (last < text.length) out.push({ text: text.slice(last) })
  return out
}

/** Rows for a recharts line/bar chart: one row per x, one key per series name. */
export function chartRows(series: ChartSeries[] | null | undefined): Array<Record<string, string | number | null>> {
  const rows = new Map<string, Record<string, string | number | null>>()
  for (const s of series ?? []) {
    for (const p of s.points ?? []) {
      if (!Array.isArray(p)) continue
      const x = String(p[0])
      const row = rows.get(x) ?? { x }
      const y = toNumber(p[1])
      row[s.name] = y
      rows.set(x, row)
    }
  }
  return [...rows.values()]
}

/** Analyst target range: low / mean / high (+ current price when given) from series or annotations. */
export function targetRange(c: ProspectusChart): { low: number | null; mean: number | null; high: number | null; current: number | null } {
  const pick = (name: RegExp) => {
    const a = (c.annotations ?? []).find(x => name.test(String(x.kind ?? x.label ?? '')))
    if (a && toNumber(a.y) != null) return toNumber(a.y)
    for (const s of c.series ?? []) if (name.test(s.name)) { const p = s.points?.[s.points.length - 1]; if (p) return toNumber(p[1]) }
    for (const s of c.series ?? []) for (const p of s.points ?? []) if (name.test(String(p[0]))) return toNumber(p[1])
    return null
  }
  const ann = (c.annotations ?? []).find(a => toNumber(a.low) != null && toNumber(a.high) != null)
  return {
    low: ann ? toNumber(ann.low) : pick(/low/i),
    mean: pick(/mean|median|avg|average|consensus/i),
    high: ann ? toNumber(ann.high) : pick(/high/i),
    current: pick(/current|price|last/i),
  }
}

/** Horizontal reference lines (stop / entry / target) a price chart should draw. */
export function priceLines(c: ProspectusChart): Array<{ y: number; label: string; tone: 'danger' | 'success' | 'info' | 'warning' }> {
  const out: Array<{ y: number; label: string; tone: 'danger' | 'success' | 'info' | 'warning' }> = []
  for (const a of c.annotations ?? []) {
    const y = toNumber(a.y)
    if (y == null) continue
    const k = String(a.kind ?? a.label ?? '').toLowerCase()
    const tone = k.includes('stop') ? 'danger' : k.includes('entry') || k.includes('basis') || k.includes('cost') ? 'success' : k.includes('target') ? 'info' : 'warning'
    out.push({ y, label: a.label || a.kind || 'level', tone })
  }
  return out
}

export function chartKind(c: ProspectusChart): 'line' | 'bar' | 'range' | 'unknown' {
  const t = String(c.type ?? '').toLowerCase()
  if (t === 'line' || t === 'area') return 'line'
  if (t === 'bar' || t === 'column') return 'bar'
  if (t === 'range') return 'range'
  return 'unknown'
}

/** Detail page state from the index row and/or the detail payload. */
export type DetailState = 'loading' | 'ready' | 'partial' | 'missing' | 'queued' | 'running' | 'failed' | 'error'
export function detailState(opts: { loading: boolean; httpStatus?: number | null; error?: unknown; doc?: ProspectusDoc | null; row?: ProspectusIndexItem | null }): DetailState {
  const { loading, httpStatus, error, doc, row } = opts
  const hasBody = !!doc && (doc.sections?.length ?? 0) > 0
  if (hasBody) return doc!.status === 'partial' ? 'partial' : 'ready'
  const st = doc?.status ?? row?.status
  if (st === 'failed') return 'failed'
  if (st === 'running') return 'running'
  if (st === 'queued') return 'queued'
  if (httpStatus === 404 || st === 'missing') return 'missing'
  if (loading) return 'loading'
  if (error) return 'error'
  return 'missing'
}

// ── Institutional blocks (backend scripts/lib/prospectus/blocks.py + domains.py shapes) ─────────────────────────────

export type ProspectusFact = { id: string; kind?: string; label: string; value?: number; unit?: string; text?: string; source?: string; as_of?: string | null; url?: string }
type Num = number | null | undefined
export type RelLine = { name: string; points: ChartPoint[] }
export type RelReturnRow = { name: string } & Partial<Record<'1W' | '1M' | '3M' | 'YTD' | '1Y' | '3Y', Num>>
export type RelativePerformance = {
  series?: Partial<Record<'3M' | 'YTD' | '1Y' | '3Y', RelLine[]>>
  returns?: RelReturnRow[]
  excess_vs_spy?: Partial<Record<string, Num>>
  rank_in_industry?: { rank: number; of: number; percentile?: number } | null
  rs_rating_12m?: Num
  sector_trend?: Record<string, unknown> | null
  industry_trend?: Record<string, unknown> | null
  benchmarks?: string[]
  gaps?: string[]
}
export type PeerRow = { symbol: string; is_subject?: boolean; consensus?: string | null } & Record<string, unknown>
export type PeerComparison = { industry?: string; rows?: PeerRow[]; median?: Record<string, Num> | null; fields?: string[]; labels?: Record<string, string>; gaps?: string[] }
export type Estimates = { eps_surprises?: { date?: string | null; actual?: Num; estimate?: Num; surprise_pct?: Num }[]; revisions_90d?: { up?: Num; down?: Num }; next_report?: string | null; gaps?: string[] }
export type ScenarioCase = { case: 'bear' | 'base' | 'bull'; price?: Num; probability_pct?: Num; narrative?: string; change_pct?: Num }
export type Scenarios = { cases?: ScenarioCase[]; footer?: string; probability_basis?: string; gaps?: string[] }
export type MacroSeries = { label: string; value?: Num; as_of?: string | null; chg_3m?: Num; trend?: string | null; effect?: string | null }
export type MacroSensitivity = { series?: Record<string, MacroSeries>; rate_beta_10y?: Num; next_events?: Array<Record<string, unknown>>; gaps?: string[] }
export type SecFiling = { form: string; filed_at?: string | null; url?: string | null; what_changed?: string | null }
export type SecFilings = { filings?: SecFiling[]; form4_90d?: { buys?: Num; sells?: Num } | null; gaps?: string[] }
export type EarningsCall = { bullets?: string[]; transcripts?: { id?: string; label: string; as_of?: string | null; url?: string | null }[]; gaps?: string[] }
export type ProspectusBlocks = {
  relative_performance?: RelativePerformance
  peer_comparison?: PeerComparison
  estimates?: Estimates
  ownership_flows?: Record<string, unknown>
  risk_technicals?: Record<string, unknown>
  scenarios?: Scenarios
  macro_sensitivity?: MacroSensitivity
  sec_filings?: SecFilings
  earnings_call?: EarningsCall
  options_sentiment_dividends?: Record<string, unknown>
  verdict_tiles?: Partial<Record<VerdictTileId, { value?: string | null; sub?: string | null; tone?: string | null }>>
}
export type CoverageDomain = { domain: string; status: string; reason?: string | null; as_of?: string | null; label?: string | null }
export type SourceCoverage = { domains?: CoverageDomain[]; key_gaps?: string[]; counts?: Record<string, number> }

export const REL_WINDOWS = ['3M', 'YTD', '1Y', '3Y'] as const
export const RET_COLUMNS = ['1W', '1M', '3M', 'YTD', '1Y', '3Y'] as const
export const RET_COLUMNS_PHONE = ['1M', 'YTD', '1Y', '3Y'] as const

/** Benchmark display names (sector ETFs keep their ticker, labelled as the sector ETF). */
export function benchName(name: string, subject: string, benchmarks: string[] = []): string {
  if (name === subject) return name
  if (name === 'SPY') return 'S&P 500'
  if (name === 'QQQ') return 'Nasdaq-100'
  if (/industry/i.test(name)) return name
  if (benchmarks.includes(name) || /^XL[A-Z]{1,2}$/.test(name)) return `Sector ETF ${name}`
  return name
}

export function pct(v: unknown, digits = 1, signed = true): string {
  const n = toNumber(v)
  if (n == null) return '—'
  return `${signed && n > 0 ? '+' : ''}${n.toFixed(digits)}%`
}

export function fmtNum(v: unknown, digits = 2): string {
  const n = toNumber(v)
  return n == null ? '—' : n.toFixed(digits)
}

export function signTone(v: unknown): 'success' | 'danger' | 'neutral' {
  const n = toNumber(v)
  return n == null || n === 0 ? 'neutral' : n > 0 ? 'success' : 'danger'
}

/** Rows for the rebased chart in one window: { x, [line.name]: value }. */
export function relRows(rel: RelativePerformance | null | undefined, w: string): { rows: Array<Record<string, string | number | null>>; names: string[] } {
  const lines = (rel?.series as Record<string, RelLine[]> | undefined)?.[w] ?? []
  return { rows: chartRows(lines), names: lines.map(l => l.name) }
}

/** The windows that actually have lines (the toggle only offers these). */
export function relWindows(rel: RelativePerformance | null | undefined): string[] {
  return REL_WINDOWS.filter(w => ((rel?.series as Record<string, RelLine[]> | undefined)?.[w] ?? []).length > 0)
}

const PEER_DEFAULT_LABELS: Record<string, string> = {
  market_cap_b: 'Mkt cap ($B)', forward_pe: 'P/E fwd', ev_ebitda: 'EV/EBITDA', sales_growth_past_5y_pct: 'Rev growth 5y',
  oper_margin_pct: 'Op margin', roe_pct: 'ROE', div_yield_pct: 'Div yield', total_debt_equity: 'Debt/Equity',
  perf_year_pct: '1Y return', consensus: 'Consensus',
}
export function peerColumns(pc: PeerComparison | null | undefined): Array<{ key: string; label: string }> {
  const fields = pc?.fields?.length ? pc.fields : Object.keys(PEER_DEFAULT_LABELS).filter(k => k !== 'consensus')
  return [...fields.map(k => ({ key: k, label: PEER_DEFAULT_LABELS[k] || pc?.labels?.[k] || k })), { key: 'consensus', label: 'Consensus' }]
}
export function peerCell(key: string, v: unknown): string {
  if (key === 'consensus') return v ? String(v) : '—'
  const n = toNumber(v)
  if (n == null) return '—'
  if (key === 'market_cap_b') return `$${n.toFixed(1)}B`
  if (key.endsWith('_pct')) return `${n.toFixed(1)}%`
  return `${n.toFixed(1)}×`
}

/** Coverage chip tone: green used, amber stale, grey not applicable / empty, red failed. */
export function coverageTone(status: string): 'success' | 'warning' | 'neutral' | 'danger' {
  const s = String(status || '').toLowerCase()
  if (s === 'used') return 'success'
  if (s === 'stale') return 'warning'
  if (s === 'failed') return 'danger'
  return 'neutral'
}
export function domainLabel(d: CoverageDomain): string {
  if (d.label) return d.label
  return String(d.domain || '').replace(/[_-]+/g, ' ').replace(/^./, c => c.toUpperCase())
}

export type VerdictTileId = 'verdict' | 'price' | 'position' | 'stop' | 'yield'
export type VerdictTile = { id: VerdictTileId; label: string; value: string | null; sub: string | null; tone: 'success' | 'warning' | 'danger' | 'info' | 'ai' | 'neutral' }

function fact(doc: ProspectusDoc, re: RegExp): ProspectusFact | undefined {
  return (doc.facts ?? []).find(f => re.test(f.label))
}

/** The five verdict tiles. Server-supplied `blocks.verdict_tiles` win; otherwise each is read from the cited facts by
 *  label. A tile the data cannot fill has value null (rendered "not available yet"), never an invented number. */
export function verdictTiles(doc: ProspectusDoc | null | undefined): VerdictTile[] {
  const d = doc ?? ({ symbol: '' } as ProspectusDoc)
  const given = d.blocks?.verdict_tiles ?? {}
  const digest = (d.inputs_digest ?? {}) as Record<string, unknown>
  const stanceRaw = digest.cio_stance as unknown
  const stance = typeof stanceRaw === 'string' ? stanceRaw : (stanceRaw && typeof stanceRaw === 'object' ? String((stanceRaw as Record<string, unknown>).stance ?? '') : '')
  const lead = /^([A-Z][A-Z -]{1,16}?)\s*(?:[—:–-]|$)/.exec(String(d.verdict_line ?? ''))
  const verdictWord = (stance || lead?.[1] || '').trim().toUpperCase().replace(/_/g, ' ') || null
  const conv = fact(d, /^CIO conviction/i)
  const close = fact(d, /^Last close/i)
  const day = fact(d, /(day|1-day|today).*(change|move)/i)
  const mv = fact(d, /^Market value/i)
  const plDollar = fact(d, /^Unrealized P\/L \$/i)
  const plPct = fact(d, /^Unrealized P\/L %/i)
  const stop = fact(d, /^Recorded protective stop level/i)
  const dist = fact(d, /^Distance from last close to stop/i)
  const yld = fact(d, /^Dividend yield/i)
  const exp = fact(d, /expense ratio/i)
  const money = (v: unknown) => { const n = toNumber(v); return n == null ? null : `$${n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` }
  const verdictTone = /SELL|EXIT|TRIM|REVIEW|AVOID/.test(verdictWord ?? '') ? 'danger' : /HOLD|WATCH|WAIT/.test(verdictWord ?? '') ? 'success' : /BUY|ADD|ACCUM/.test(verdictWord ?? '') ? 'success' : 'neutral'
  const base: VerdictTile[] = [
    { id: 'verdict', label: 'Verdict', value: verdictWord, sub: conv?.value != null ? `CIO conviction ${Math.round(conv.value)}/100` : null, tone: verdictTone },
    { id: 'price', label: 'Price', value: money(close?.value), sub: day?.value != null ? `${pct(day.value, 2)} today` : null, tone: signTone(day?.value) === 'neutral' ? 'neutral' : signTone(day?.value) },
    d.scope === 'watch'
      ? { id: 'position', label: 'Your position', value: 'Not held', sub: 'Watch list', tone: 'neutral' }
      : { id: 'position', label: 'Your position', value: money(mv?.value), sub: plDollar?.value != null || plPct?.value != null ? `${plDollar?.value != null ? `${plDollar.value >= 0 ? '+' : '−'}${money(Math.abs(plDollar.value))}` : ''}${plPct?.value != null ? ` (${pct(plPct.value, 1)})` : ''} on cost`.trim() : null, tone: signTone(plDollar?.value ?? plPct?.value) },
    { id: 'stop', label: 'Stop', value: money(stop?.value), sub: dist?.value != null ? `${Math.abs(dist.value).toFixed(1)}% below` : (d.scope === 'watch' ? 'No position' : null), tone: stop ? 'warning' : 'neutral' },
    { id: 'yield', label: 'Yield · Expense', value: yld || exp ? `${yld?.value != null ? `${yld.value.toFixed(2)}%` : '—'} · ${exp?.value != null ? `${exp.value.toFixed(2)}%` : '—'}` : null, sub: yld || exp ? 'trailing 12 months' : null, tone: 'neutral' },
  ]
  return base.map(t => {
    const g = given[t.id]
    if (!g) return t
    const tone = (['success', 'warning', 'danger', 'info', 'ai', 'neutral'] as const).find(x => x === g.tone) ?? t.tone
    return { ...t, value: g.value ?? t.value, sub: g.sub ?? t.sub, tone }
  })
}

/** Every citation across the sections, de-duplicated by id, in first-seen order (the "Sources" list). */
export function allCitations(sections: ProspectusSection[] | null | undefined): ProspectusCitation[] {
  const seen = new Map<string, ProspectusCitation>()
  for (const s of sections ?? []) for (const c of s.citations ?? []) if (c && !seen.has(c.id)) seen.set(c.id, c)
  return [...seen.values()]
}

/** Section ids that render as their own tile row / summary instead of the narrative grid. */
export const SUMMARY_SECTION = 'summary_verdict'
