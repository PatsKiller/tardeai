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
  /** "Since this report" (operator 2026-10-27): what happened after this version was written. Latest version only. */
  since_report?: SinceReport | null
}

export type SinceImpact = 'none' | 'watch' | 'thesis' | 'breaker' | 'stop'
export type SinceItem = {
  id: string; at?: string | null; kind?: string | null; title?: string | null; source?: string | null; url?: string | null
  material: boolean; badge: string; status: string
  note?: { impact?: SinceImpact | null; which_breaker?: string | null; one_line?: string | null; at?: string | null } | null
}
export type SinceReport = {
  written_at?: string | null; checked_at?: string | null; items: SinceItem[]; item_count?: number
  hidden?: Record<string, number>
  price?: { at_report?: number | null; last_close?: number | null; as_of?: string | null; move_pct?: number | null } | null
  stop_events?: { kind: string; at_report?: number[] | null; now?: number[] | null; status?: string }[]
  rewrite?: { reason?: string | null; status?: string | null } | null
  next_window?: { id?: string; start?: string; time?: string | null; label?: string | null } | null
}

/** Tone for a CIO news-note impact (never hex). */
export function impactTone(impact: unknown): 'danger' | 'warning' | 'info' | 'neutral' {
  const i = String(impact ?? '')
  return i === 'breaker' || i === 'stop' ? 'danger' : i === 'thesis' ? 'warning' : i === 'watch' ? 'info' : 'neutral'
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
export type MdBlock = { kind: 'h' | 'li' | 'oli' | 'p' | 'table'; text: string; level?: number; head?: string[]; rows?: string[][] }
const MD_ROW_RE = /^\|.*\|$/
const MD_SEP_RE = /^\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?$/
const mdCells = (l: string) => l.replace(/^\|/, '').replace(/\|$/, '').split('|').map(c => c.trim())
export function mdBlocks(md: string): MdBlock[] {
  const out: MdBlock[] = []
  let para: string[] = []
  const flush = () => { if (para.length) { out.push({ kind: 'p', text: para.join(' ') }); para = [] } }
  const lines = String(md ?? '').replace(/\r\n/g, '\n').split('\n')
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trim()
    // A markdown pipe table (header, separator, rows) renders as a table, never as raw "| a | b |" text.
    if (MD_ROW_RE.test(line) && i + 1 < lines.length && MD_SEP_RE.test(lines[i + 1].trim()) && lines[i + 1].includes('|')) {
      flush()
      const head = mdCells(line)
      const rows: string[][] = []
      let j = i + 2
      for (; j < lines.length && MD_ROW_RE.test(lines[j].trim()); j++) rows.push([...mdCells(lines[j].trim()), ...head.map(() => '')].slice(0, head.length))
      out.push({ kind: 'table', text: '', head, rows })
      i = j - 1
      continue
    }
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
  const out = [...rows.values()]
  // A common axis: when every x is an ISO date, merge on the sorted dates (series with gaps stay aligned).
  if (isDateAxis(out.map(r => r.x))) out.sort((a, b) => String(a.x).localeCompare(String(b.x)))
  return out
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
/** House stop policy's recommended stop beside the broker stop and its state (backend scripts/lib/prospectus/stops.py). */
export type StopPlan = {
  not_applicable?: string
  recommended?: { level?: Num; method?: string | null; distance_pct?: Num; usd_at_risk?: Num; policy?: string; as_of?: string | null;
    band?: { label?: string | null; stop_min_pct?: Num; stop_max_pct?: Num; levels?: Num[] } }
  broker?: { level?: Num; state?: 'active' | 'resting' | 'filled' | 'none' | 'unknown'; as_of?: string | null; source?: string; other_accounts?: string | null }
  comparison?: string
  advisory?: string
  gaps?: string[]
}
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
  stop_plan?: StopPlan
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
  const lines = nonEmptySeries((rel?.series as Record<string, RelLine[]> | undefined)?.[w] ?? [])
  return { rows: chartRows(lines), names: lines.map(l => l.name) }
}

/** The windows that actually have lines (the toggle only offers these). */
export function relWindows(rel: RelativePerformance | null | undefined): string[] {
  return REL_WINDOWS.filter(w => nonEmptySeries((rel?.series as Record<string, RelLine[]> | undefined)?.[w] ?? []).length > 0)
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
const STOP_STATE_SHORT: Record<string, string> = { active: 'active', resting: 'resting', filled: 'filled', none: 'none on record' }

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
  const fp = ((d.blocks as Record<string, unknown> | undefined)?.fund_profile ?? {}) as Record<string, unknown>
  // Yield tile reads the same fund-profile fields as the fund block; facts are the fallback (stocks).
  const yldFact = fact(d, /^(Dividend yield|Fund distribution yield)/i)
  const expFact = fact(d, /expense ratio/i)
  const yld = toNumber(fp.dividend_yield_pct) != null ? { value: toNumber(fp.dividend_yield_pct) as number } : yldFact
  const exp = toNumber(fp.expense_ratio_pct) != null ? { value: toNumber(fp.expense_ratio_pct) as number } : expFact
  const money = (v: unknown) => { const n = toNumber(v); return n == null ? null : `$${n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` }
  const verdictTone = /SELL|EXIT|TRIM|REVIEW|AVOID/.test(verdictWord ?? '') ? 'danger' : /HOLD|WATCH|WAIT/.test(verdictWord ?? '') ? 'success' : /BUY|ADD|ACCUM/.test(verdictWord ?? '') ? 'success' : 'neutral'
  const base: VerdictTile[] = [
    { id: 'verdict', label: 'Verdict', value: verdictWord, sub: conv?.value != null ? `CIO conviction ${Math.round(conv.value)}/100` : null, tone: verdictTone },
    { id: 'price', label: 'Price', value: money(close?.value), sub: day?.value != null ? `${pct(day.value, 2)} today` : null, tone: signTone(day?.value) === 'neutral' ? 'neutral' : signTone(day?.value) },
    d.scope === 'watch'
      ? { id: 'position', label: 'Your position', value: 'Not held', sub: 'Watch list', tone: 'neutral' }
      : { id: 'position', label: 'Your position', value: money(mv?.value), sub: plDollar?.value != null || plPct?.value != null ? `${plDollar?.value != null ? `${plDollar.value >= 0 ? '+' : '−'}${money(Math.abs(plDollar.value))}` : ''}${plPct?.value != null ? ` (${pct(plPct.value, 1)})` : ''} on cost`.trim() : null, tone: signTone(plDollar?.value ?? plPct?.value) },
    { id: 'stop', label: 'Stop', value: money(stop?.value), sub: dist?.value != null ? `${Math.abs(dist.value).toFixed(1)}% below` : (d.scope === 'watch' ? 'No position' : null), tone: stop ? 'warning' : 'neutral' },
    exp || Object.keys(fp).length
      ? { id: 'yield', label: 'Yield · Expense', value: yld || exp ? `${yld?.value != null ? `${yld.value.toFixed(2)}%` : '—'} · ${exp?.value != null ? `${exp.value.toFixed(2)}%` : '—'}` : null, sub: yld || exp ? 'trailing 12 months' : null, tone: 'neutral' }
      : { id: 'yield', label: 'Dividend yield', value: yld?.value != null ? `${yld.value.toFixed(2)}%` : null, sub: yld ? 'trailing 12 months' : null, tone: 'neutral' },
  ]
  const merged = base.map(t => {
    const g = given[t.id]
    if (!g) return t
    const tone = (['success', 'warning', 'danger', 'info', 'ai', 'neutral'] as const).find(x => x === g.tone) ?? t.tone
    return { ...t, value: g.value ?? t.value, sub: g.sub ?? t.sub, tone }
  })
  // Stop tile, concise: "$33.59 · resting" + "house $32.83". Other accounts live in the stop-plan block, not the tile.
  const sp = d.blocks?.stop_plan
  if (sp && !sp.not_applicable) {
    const brokerLevel = money(sp.broker?.level)
    const house = money(sp.recommended?.level)
    const state = STOP_STATE_SHORT[String(sp.broker?.state ?? '')] ?? null
    const i = merged.findIndex(t => t.id === 'stop')
    if (i >= 0 && (brokerLevel || house)) {
      merged[i] = { ...merged[i], value: brokerLevel ? `${brokerLevel}${state ? ` · ${state}` : ''}` : (state ?? 'No broker stop'),
        sub: house ? `house ${house}` : null, tone: sp.broker?.state === 'none' ? 'danger' : merged[i].tone === 'neutral' ? 'warning' : merged[i].tone }
    }
  }
  return merged
}

/** Every citation across the sections, de-duplicated by id, in first-seen order (the "Sources" list). */
export function allCitations(sections: ProspectusSection[] | null | undefined): ProspectusCitation[] {
  const seen = new Map<string, ProspectusCitation>()
  for (const s of sections ?? []) for (const c of s.citations ?? []) if (c && !seen.has(c.id)) seen.set(c.id, c)
  return [...seen.values()]
}

/** Section ids that render as their own tile row / summary instead of the narrative grid. */
export const SUMMARY_SECTION = 'summary_verdict'

// ── Presentation polish (design prospectus/v001.1, operator 2026-10-26: "what are these F with the numbers all over
//    the pages? … internal pointers. Do those really need to be shown?") ───────────────────────────────────────────
//    The backend attaches `presentation` (scripts/lib/prospectus/presentation.py) to the detail payload; every function
//    below reads it and falls back to the same rules computed here when it is absent (older payloads, fixtures).

export type Footnote = { n: number; id: string; label: string; source?: string | null; as_of?: string | null; url?: string | null; value?: string | null }
export type CoverageItem = { domain: string; label: string; status: string; as_of?: string | null; reason?: string | null }
export type CoverageGroupId = 'used' | 'stale' | 'failed' | 'missing'
export type FundStructureRow = { group: string; label: string; value: string; cites?: string[] }
export type FundStructure = {
  rows: FundStructureRow[]
  top_holdings: { symbol?: string | null; name: string; weight_pct?: number | null }[]
  sectors: { name: string; weight_pct: number }[]
  countries: { name: string; weight_pct: number }[]
  missing: string[]
  as_of?: string | null
}
export type Presentation = {
  schema?: string
  display_name?: string | null
  is_fund?: boolean
  footnotes?: Footnote[]
  section_footnotes?: Record<string, number[]>
  fund_structure?: FundStructure | null
  coverage?: { groups: Record<CoverageGroupId, CoverageItem[]>; counts: Record<CoverageGroupId, number>; hidden: number; key_gaps?: string[] } | null
  validation?: Validation | null
  street?: StreetTable[]
}

/** The one validation statement shown instead of citations (presentation.validation). */
export type Validation = {
  status: 'validated' | 'partial' | 'unchecked'
  line: string
  figures?: number
  sources?: number
  not_validated?: number
  by_source?: Record<string, number>
  unreliable?: { id: string; label: string; reason: string }[]
  reasons?: string[]
  as_of?: string | null
  gate_status?: string | null
}

/** A Street table (tables.street_tables): analyst coverage, action log, estimates, catalysts, positioning, valuation. */
export type StreetTable = {
  id: string
  title: string
  columns: string[]
  rows: string[][]
  kpis?: [string, string][]
  note?: string | null
  highlight?: number | null
}

export function validationOf(doc: ProspectusDoc | null | undefined): Validation | null {
  const v = presentationOf(doc)?.validation
  return v && v.line ? v : null
}

export function validationTone(v: Validation | null | undefined): 'success' | 'warning' | 'neutral' {
  return v?.status === 'validated' ? 'success' : v?.status === 'partial' ? 'warning' : 'neutral'
}

export function streetTables(doc: ProspectusDoc | null | undefined): StreetTable[] {
  const t = presentationOf(doc)?.street
  return Array.isArray(t) ? t.filter(x => x && x.id && Array.isArray(x.columns)) : []
}

/** Blank cells ("n/a", "—", "n/a · n/a") never print; a row whose value cells are all blank folds into one note. */
export function streetRows(t: StreetTable): { rows: string[][]; absent: string[] } {
  const keyed = ['Measure'].includes(t.columns[0])
  const rows: string[][] = []
  const absent: string[] = []
  for (const r of t.rows ?? []) {
    if (keyed && r.slice(1).every(c => isBlankValue(c))) absent.push(String(r[0]))
    else rows.push(r)
  }
  return { rows, absent }
}

/** One bracket group of citation ids: "[F7]", "[F7, F8]", "[^c1]" (same rule as presentation.GROUP_RE). */
const CITE_GROUP_RE = /\[\^?([A-Za-z][\w.:-]*(?:\s*[,;]\s*\^?[A-Za-z][\w.:-]*)*)\](?!\()/g
const FACT_ID_RE = /^[FW]\d+$/  // internal fact (F7) and web-fact (W2) ids; never shown
export const UNRELIABLE_RE = /(?:statistically\s+)?(?:not reliable|unreliable)(?:\s*\([^)]*\)|:\s*[^;.\n\][]+)?/gi

function groupIds(g: string): string[] { return g.split(/[,;]/).map(s => s.trim().replace(/^\^/, '')).filter(Boolean) }

/** Render-side prose cleanup: dangling empty bullets, doubled spaces, space before punctuation, empty brackets. */
export function cleanProse(text: unknown): string {
  const lines: string[] = []
  for (const raw of String(text ?? '').replace(/\r\n/g, '\n').split('\n')) {
    if (/^\s*([-*•]|\d{1,2}[.)])\s*$/.test(raw)) continue
    const lead = /^\s*/.exec(raw)![0]
    let body = raw.slice(lead.length)
    body = body.replace(/[ \t ]{2,}/g, ' ').replace(/\s+\[\s*\]|\(\s*\)/g, '').replace(/\s+([,.;:!?])(?=\s|$)/g, '$1')
    lines.push((/^([-*•]|\d{1,2}[.)])\s/.test(body) ? lead : '') + body.replace(/\s+$/, ''))
  }
  return lines.join('\n').replace(/\n{3,}/g, '\n\n').trim()
}

function walkStrings(o: unknown, out: string[]): string[] {
  if (typeof o === 'string') out.push(o)
  else if (Array.isArray(o)) o.forEach(v => walkStrings(v, out))
  else if (o && typeof o === 'object') Object.values(o as Record<string, unknown>).forEach(v => walkStrings(v, out))
  return out
}

/** Footnotes 1..n in order of first use: verdict line, sections in reading order, then block texts. */
export function footnotes(doc: ProspectusDoc | null | undefined): Footnote[] {
  if (!doc) return []
  const given = (doc as ProspectusDoc & { presentation?: Presentation }).presentation?.footnotes
  if (Array.isArray(given) && given.length) return given
  const known = new Map<string, Record<string, unknown>>()
  for (const f of doc.facts ?? []) if (f?.id) known.set(f.id, f as unknown as Record<string, unknown>)
  for (const s of doc.sections ?? []) for (const c of s.citations ?? []) if (c?.id) known.set(c.id, { ...(known.get(c.id) ?? {}), ...Object.fromEntries(Object.entries(c).filter(([, v]) => v != null && v !== '')) })
  // Reading order: verdict line, "My history" (rendered right after the tiles), the sections, then the other blocks.
  const blocks = (doc.blocks ?? {}) as Record<string, unknown>
  const texts = [String(doc.verdict_line ?? ''), ...walkStrings(blocks.my_history, []), ...orderedSections(doc.sections, doc.scope).map(s => s.body_md),
    ...walkStrings(Object.fromEntries(Object.entries(blocks).filter(([k]) => k !== 'my_history')), [])]
  const order: string[] = []
  const seen = new Set<string>()
  for (const t of texts) for (const m of t.matchAll(CITE_GROUP_RE)) {
    const ids = groupIds(m[1])
    if (!ids.length || !ids.every(i => FACT_ID_RE.test(i) || known.has(i))) continue
    for (const i of ids) if (!seen.has(i)) { seen.add(i); order.push(i) }
  }
  return order.map((id, k) => {
    const f = known.get(id) ?? {}
    const v = f.value != null ? `${f.value}${f.unit === '%' ? '%' : f.unit ? ` ${f.unit}` : ''}` : String(f.text ?? '').slice(0, 140)
    return { n: k + 1, id, label: String(f.label ?? f.source ?? 'Source not recorded'), source: (f.source as string) ?? null, as_of: (f.as_of as string) ?? null, url: (f.url as string) ?? null, value: v || null }
  })
}

export type TextPart = { text: string; muted?: boolean } | { notes: Footnote[]; ids: string[] }

/** Split prose into text runs, muted "not reliable (…)" notes and footnote groups (known ids only; unknown internal
 *  F-ids are dropped, never shown raw). */
export function splitFootnotes(text: string, byId: Map<string, Footnote>): TextPart[] {
  const out: TextPart[] = []
  const pushText = (t: string) => {
    if (!t) return
    let last = 0
    for (const m of t.matchAll(UNRELIABLE_RE)) {
      if (m.index! > last) out.push({ text: t.slice(last, m.index) })
      out.push({ text: m[0], muted: true })
      last = m.index! + m[0].length
    }
    if (last < t.length) out.push({ text: t.slice(last) })
  }
  let last = 0
  for (const m of text.matchAll(CITE_GROUP_RE)) {
    const ids = groupIds(m[1])
    if (!ids.length || !ids.every(i => FACT_ID_RE.test(i) || byId.has(i))) continue
    pushText(text.slice(last, m.index).replace(/\s+$/, ''))
    const notes = ids.map(i => byId.get(i)).filter((x): x is Footnote => !!x)
    out.push({ notes, ids })
    last = m.index! + m[0].length
  }
  pushText(text.slice(last))
  return out
}

/** Footnotes a section's prose uses, ascending. */
export function sectionFootnotes(s: ProspectusSection, byId: Map<string, Footnote>): Footnote[] {
  const ns = new Map<number, Footnote>()
  for (const m of String(s.body_md ?? '').matchAll(CITE_GROUP_RE)) for (const i of groupIds(m[1])) { const f = byId.get(i); if (f) ns.set(f.n, f) }
  return [...ns.values()].sort((a, b) => a.n - b.n)
}

/** Header name: the presentation's display name, else the payload name; never the symbol repeated. */
export function displayName(doc: ProspectusDoc | null | undefined, row?: ProspectusIndexItem | null): string {
  const sym = normSymbol(doc?.symbol ?? row?.symbol)
  const cands = [(doc as (ProspectusDoc & { presentation?: Presentation }) | null | undefined)?.presentation?.display_name, doc?.name, row?.name]
  for (const c of cands) { const s = String(c ?? '').trim(); if (s && s.toUpperCase() !== sym) return s }
  return ''
}

export function presentationOf(doc: ProspectusDoc | null | undefined): Presentation | null {
  return (doc as (ProspectusDoc & { presentation?: Presentation }) | null | undefined)?.presentation ?? null
}

/** A fund (ETF / mutual fund): the presentation says so, or the fund profile / look-through block is present. */
export function isFundDoc(doc: ProspectusDoc | null | undefined): boolean {
  const p = presentationOf(doc)
  if (p && typeof p.is_fund === 'boolean') return p.is_fund
  const b = (doc?.blocks ?? {}) as Record<string, unknown>
  const fp = b.fund_profile as Record<string, unknown> | undefined
  return !!(fp && Object.keys(fp).length && !fp.not_applicable) || !!b.fund_lookthrough
}

export const COVERAGE_GROUPS: Array<[CoverageGroupId, string]> = [['used', 'Used'], ['stale', 'Stale'], ['failed', 'Failed'], ['missing', 'Missing']]

/** Source coverage grouped for a security report: not-applicable / plumbing domains are hidden (kept in the JSON). */
export function coverageGroups(doc: ProspectusDoc | null | undefined): { groups: Record<CoverageGroupId, CoverageItem[]>; counts: Record<CoverageGroupId, number>; hidden: number } {
  const p = presentationOf(doc)?.coverage
  if (p && p.groups) return { groups: p.groups, counts: p.counts, hidden: p.hidden ?? 0 }
  const groups: Record<CoverageGroupId, CoverageItem[]> = { used: [], stale: [], failed: [], missing: [] }
  let hidden = 0
  for (const d of doc?.source_coverage?.domains ?? []) {
    const st = String(d.status || '').toLowerCase()
    if (st === 'not_applicable') { hidden++; continue }
    const g: CoverageGroupId = st === 'used' || st === 'stale' || st === 'failed' ? st : 'missing'
    groups[g].push({ domain: d.domain, label: domainLabel(d), status: st, as_of: d.as_of, reason: d.reason })
  }
  return { groups, counts: { used: groups.used.length, stale: groups.stale.length, failed: groups.failed.length, missing: groups.missing.length }, hidden }
}

/** "missing value" test for a rendered cell: '—', 'n/a', '— / —', '— · —'. */
export function isBlankValue(v: unknown): boolean {
  if (v == null) return true
  if (typeof v !== 'string' && typeof v !== 'number') return false
  return /^[\s·/|,()—-]*(?:(?:n\/a|none|not available(?: yet)?|—|-)[\s·/|,()—-]*)*$/i.test(String(v))
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const ISO_DAY = /^\d{4}-\d{2}-\d{2}/
export function isDateAxis(xs: Array<string | number | null>): boolean { return xs.length > 0 && xs.every(x => ISO_DAY.test(String(x))) }
/** '2026-01-14' → 'Jan 26' (month + 2-digit year); anything else unchanged. */
export function monthLabel(x: unknown): string {
  const s = String(x ?? '')
  return ISO_DAY.test(s) ? `${MONTHS[Number(s.slice(5, 7)) - 1]} ${s.slice(2, 4)}` : s
}
/** Evenly spaced ticks on month boundaries (the first point of a month), at most `want`. */
export function monthTicks(xs: string[], want = 6): string[] {
  if (!isDateAxis(xs)) return []
  let starts = xs.map((x, i) => (i === 0 || x.slice(0, 7) !== xs[i - 1].slice(0, 7) ? i : -1)).filter(i => i >= 0)
  if (starts.length > 2 && starts[1] - starts[0] < (xs.length / starts.length) / 2) starts = starts.slice(1)  // a stub first month would crowd the next label
  const step = Math.max(1, Math.ceil(starts.length / want))
  return starts.filter((_, k) => k % step === 0).map(i => xs[i])
}
/** Series that have at least one numeric point (an empty series is never drawn or put in a legend). */
export function nonEmptySeries<T extends { points?: ChartPoint[] }>(series: T[] | null | undefined): T[] {
  return (series ?? []).filter(s => (s.points ?? []).some(p => Array.isArray(p) && toNumber(p[1]) != null))
}

/** Footnote label for a group: consecutive runs of three or more compress ("117–121"), others list ("3,4"). */
export function footnoteLabel(ns: number[]): string {
  const xs = [...new Set(ns)].sort((a, b) => a - b)
  const out: string[] = []
  for (let i = 0; i < xs.length;) {
    let j = i
    while (j + 1 < xs.length && xs[j + 1] === xs[j] + 1) j++
    out.push(j - i >= 2 ? `${xs[i]}–${xs[j]}` : xs.slice(i, j + 1).join(','))
    i = j + 1
  }
  return out.join(',')
}
