// scannerSelection.ts — pure helpers for the Trade AI scanner: top-N pagination, persistent
// cross-page symbol selection, Thinkorswim copy formatting, and Social Scout pill derivation.
//
// SAFETY: these are presentation/selection utilities only. Nothing here executes, validates, or
// queues a trade. A Social Scout is awareness-only — getSocialScoutPill never returns a tradeable
// flag, and selection/copy never touches any broker or validation path.

export interface ScannerRow {
  symbol: string
  score?: number
  decision?: string
  source?: string
  route?: string
  route_actionability?: string
  scout_status?: string
  scout_pillar_count?: number
  scout_pillars_met?: string[]
  scout_pillars_missing?: string[]
  operator_pill?: string
  operator_subtitle?: string
  operator_color_token?: string
  operator_tooltip_hints?: string[]
  not_validation_ready?: boolean
  not_tradeable?: boolean
  float_class?: string
  manual_review_required?: boolean
  awareness_status?: string
  setup_class?: string
  squeeze_sort_score?: number
  runner_sort_score?: number
  micro_float_sort_score?: number
  low_price_sort_score?: number
  rvol?: number
  volume?: number
  gap_pct?: number | string
  change_pct?: number | string
  disqualified?: boolean
  disqualification_reason?: string
  soft_flag_reason?: string
  price?: number
  grade?: string
  float_m?: number | string
  catalyst?: string
  catalyst_verified?: boolean
  sector?: string
  industry?: string
}

export interface PillDetail {
  text?: string
  subtitle?: string
  hints?: string[]
  tooltip?: string
}

export type TosFormat = 'comma' | 'newline' | 'space'

export interface PageView<T> {
  items: T[]
  page: number
  pageCount: number
  total: number      // size of the top-N window actually paged (≤ topN)
  from: number       // 1-based index of first item shown (0 when empty)
  to: number         // 1-based index of last item shown (0 when empty)
}

/** Slice the top-N ranked rows into a single page. Page is clamped to [1, pageCount]; the page count
 *  is based on the top-N window (default 30), NOT the full row set. */
export function pageSlice<T>(rows: T[], page: number, topN = 30, pageSize = 10): PageView<T> {
  const top = (rows || []).slice(0, topN)
  const pageCount = Math.max(1, Math.ceil(top.length / pageSize))
  const p = Math.min(Math.max(1, Math.floor(page) || 1), pageCount)
  const start = (p - 1) * pageSize
  const items = top.slice(start, start + pageSize)
  return {
    items, page: p, pageCount, total: top.length,
    from: top.length ? start + 1 : 0,
    to: start + items.length,
  }
}

/** Split the top-N ranked rows into pages of pageSize. */
export function paginateTopN<T>(rows: T[], topN = 30, pageSize = 10): { pages: T[][]; pageCount: number; total: number } {
  const top = (rows || []).slice(0, topN)
  const pageCount = Math.max(1, Math.ceil(top.length / pageSize))
  const pages: T[][] = []
  for (let i = 0; i < pageCount; i++) pages.push(top.slice(i * pageSize, (i + 1) * pageSize))
  return { pages, pageCount, total: top.length }
}

/** Toggle one symbol in/out of the selection. Case-insensitive, de-duplicated, order-preserving. */
export function toggleSelectedSymbol(selected: string[] | Set<string>, symbol: string): string[] {
  const arr = Array.isArray(selected) ? selected : Array.from(selected)
  const sym = String(symbol || '').trim().toUpperCase()
  if (!sym) return dedupeSymbols(arr)
  const out = dedupeSymbols(arr)
  const idx = out.indexOf(sym)
  if (idx >= 0) out.splice(idx, 1)
  else out.push(sym)
  return out
}

/** Union of the current selection and a page's worth of symbols (e.g. "select visible page"). */
export function selectSymbols(selected: string[] | Set<string>, symbols: string[]): string[] {
  const out = dedupeSymbols(Array.isArray(selected) ? selected : Array.from(selected))
  for (const raw of symbols || []) {
    const s = String(raw || '').trim().toUpperCase()
    if (s && !out.includes(s)) out.push(s)
  }
  return out
}

/** Remove a page's worth of symbols from the current selection (e.g. "clear visible page"). */
export function deselectSymbols(selected: string[] | Set<string>, symbols: string[]): string[] {
  const drop = new Set((symbols || []).map(s => String(s || '').trim().toUpperCase()))
  return dedupeSymbols(Array.isArray(selected) ? selected : Array.from(selected)).filter(s => !drop.has(s))
}

/** Case-insensitive de-dupe, order-preserving. */
export function dedupeSymbols(symbols: string[]): string[] {
  const seen = new Set<string>()
  const out: string[] = []
  for (const raw of symbols || []) {
    const s = String(raw || '').trim().toUpperCase()
    if (s && !seen.has(s)) { seen.add(s); out.push(s) }
  }
  return out
}

/** Format selected symbols for pasting into Thinkorswim. De-duplicated; never throws. */
export function formatThinkorswimSymbols(symbols: string[], format: TosFormat = 'comma'): string {
  const out = dedupeSymbols(symbols)
  const sep = format === 'newline' ? '\n' : format === 'space' ? ' ' : ','
  return out.join(sep)
}

/** localStorage key for selection, scoped by day (and optional run id) so selections don't persist
 *  forever across scanner runs. */
export function selectionStorageKey(dateISO?: string, runId?: string | null): string {
  const d = dateISO || new Date().toISOString().slice(0, 10)
  const base = `tradeai.scanner.selectedSymbols.${d}`
  return runId ? `${base}.${runId}` : base
}

export interface ScoutPill extends PillDetail {
  isScout: boolean
  colorToken?: string
}

export interface TopGainerPill extends PillDetail {
  isTopGainer: boolean
}

export interface SqueezePill extends PillDetail {
  isSqueeze: boolean
}

export interface RunnerPill extends PillDetail {
  isRunner: boolean
}

export interface MicroFloatPill extends PillDetail {
  isMicroFloat: boolean
}

function _pct(raw: number | string | null | undefined): string {
  if (raw == null || raw === '') return '—'
  const s = String(raw).replace(/%$/, '').trim()
  const n = parseFloat(s)
  if (!Number.isFinite(n)) return s.includes('%') ? s : `${s}%`
  return `${n >= 0 ? '+' : ''}${n.toFixed(n % 1 === 0 ? 0 : 1)}%`
}

function _num(raw: number | string | null | undefined, digits = 2): string {
  if (raw == null || raw === '') return '—'
  const n = typeof raw === 'number' ? raw : parseFloat(String(raw).replace(/,/g, ''))
  return Number.isFinite(n) ? n.toFixed(digits) : '—'
}

/** Multi-line native tooltip: ticker metrics + pill context + operator disclaimer. */
export function buildPillTooltip(
  row: ScannerRow | null | undefined,
  kind: 'scout' | 'topGainer' | 'squeeze' | 'runner' | 'microFloat' | 'lowPrice',
  opts: { subtitle?: string; hints?: string[]; footer?: string },
): string {
  if (!row) return ''
  const sym = String(row.symbol || '').toUpperCase() || '—'
  const kindLabel = kind === 'scout' ? 'Social Scout' : kind === 'squeeze' ? 'Squeeze / R/S' : kind === 'runner' ? 'High RVOL Runner' : kind === 'microFloat' ? 'Micro-Float Runner' : kind === 'lowPrice' ? 'Low-Price Spike' : 'Top Gainer'
  const lines: string[] = [`${sym} — ${kindLabel}`]

  if (opts.subtitle) lines.push(opts.subtitle)

  const metrics: string[] = []
  if (row.price != null) metrics.push(`Price $${_num(row.price)}`)
  if (row.change_pct != null && row.change_pct !== '') metrics.push(`Chg ${_pct(row.change_pct)}`)
  if (row.gap_pct != null && row.gap_pct !== '') metrics.push(`Gap ${_pct(row.gap_pct)}`)
  if (row.rvol != null) metrics.push(`RVOL ${_num(row.rvol, 1)}x`)
  if (row.float_m != null && row.float_m !== '' && row.float_m !== '0' && row.float_m !== 0) {
    metrics.push(`Float ${_num(row.float_m, 2)}M`)
  }
  if (metrics.length) lines.push(metrics.join(' · '))

  const scan: string[] = []
  if (row.score != null) scan.push(`Score ${row.score}`)
  if (row.grade) scan.push(`Grade ${row.grade}`)
  if (row.decision) scan.push(`Decision ${row.decision}`)
  if (scan.length) lines.push(scan.join(' · '))

  if (row.sector) lines.push(`Sector ${row.sector}${row.industry ? ` · ${row.industry}` : ''}`)

  const cat = row.catalyst ? String(row.catalyst).slice(0, 100) : ''
  if (cat) {
    const v = row.catalyst_verified === true ? '✓' : row.catalyst_verified === false ? '?' : ''
    lines.push(`Catalyst${v ? ` ${v}` : ''}: ${cat}`)
  }

  const flag = row.soft_flag_reason || row.disqualification_reason
  if (flag) lines.push(`Flag: ${String(flag).slice(0, 140)}`)

  if (row.scout_pillar_count != null && kind === 'scout') {
    const met = (row.scout_pillars_met || []).join(', ')
    const miss = (row.scout_pillars_missing || []).join(', ')
    lines.push(`Pillars ${row.scout_pillar_count}/5${met ? ` · met: ${met}` : ''}${miss ? ` · missing: ${miss}` : ''}`)
  }

  if (row.squeeze_sort_score != null && kind === 'squeeze') {
    lines.push(`Squeeze rank score ${Math.round(Number(row.squeeze_sort_score))}`)
  }
  if (row.runner_sort_score != null && kind === 'runner') {
    lines.push(`Runner rank score ${Math.round(Number(row.runner_sort_score))}`)
  }

  if (opts.hints?.length) {
    for (const h of opts.hints.slice(0, 4)) lines.push(`• ${h}`)
  }

  lines.push(opts.footer || 'Awareness only — not auto GO / not validation-fast-path eligible.')
  return lines.join('\n')
}

/** Derive the Social Scout pill for a scanner row using API-provided fields (no pillar recompute).
 *  Returns isScout=false for non-scout rows (GO rows, 0–1 pillars). Awareness-only: this never
 *  signals tradeability. */
export function getSocialScoutPill(row: ScannerRow | null | undefined): ScoutPill {
  if (!row || row.scout_status !== 'SOCIAL_SCOUT') return { isScout: false }
  const count = row.scout_pillar_count ?? 0
  const large = row.float_class === 'large_float' || row.manual_review_required === true
  const text = row.operator_pill
    || (large ? `SOCIAL SCOUT · LARGE FLOAT · ${count}/5` : `SOCIAL SCOUT · ${count}/5`)
  const hints = (row.operator_tooltip_hints && row.operator_tooltip_hints.length)
    ? row.operator_tooltip_hints
    : missingPillarHints(row.scout_pillars_missing)
  const subtitle = row.operator_subtitle || 'Not quite there yet'
  return {
    isScout: true,
    text,
    colorToken: row.operator_color_token || 'socialScout',
    subtitle,
    hints,
    tooltip: buildPillTooltip(row, 'scout', {
      subtitle,
      hints,
      footer: 'Social Scout — partial setup (≥2/5 pillars). Awareness only; never tradeable via auto route.',
    }),
  }
}

/** Top Finviz gainer — awareness only (blocked from momentum-scalp GO, e.g. reverse split). */
export function getTopGainerPill(row: ScannerRow | null | undefined): TopGainerPill {
  if (!row || row.awareness_status === 'SQUEEZE' || row.setup_class === 'squeeze') return { isTopGainer: false }
  if (row.awareness_status !== 'TOP_GAINER') return { isTopGainer: false }
  const chg = row.change_pct != null && row.change_pct !== '' ? String(row.change_pct).replace(/%$/, '') : ''
  const text = row.operator_pill || (chg ? `TOP GAINER · +${chg}%` : 'TOP GAINER')
  const hints = (row.operator_tooltip_hints && row.operator_tooltip_hints.length)
    ? row.operator_tooltip_hints
    : row.disqualification_reason
      ? [String(row.disqualification_reason)]
      : ['Awareness only — not momentum-scalp GO']
  const subtitle = row.operator_subtitle || 'Leading Finviz gainer — awareness only'
  return {
    isTopGainer: true,
    text,
    subtitle,
    hints,
    tooltip: buildPillTooltip(row, 'topGainer', {
      subtitle,
      hints,
      footer: 'Top Gainer — Finviz prime-setup leader. Not momentum-scalp auto GO.',
    }),
  }
}

/** Reverse-split squeeze — manual review only (Ross-style runners). */
export function getSqueezePill(row: ScannerRow | null | undefined): SqueezePill {
  const isSqueeze = !!row && (
    row.awareness_status === 'SQUEEZE'
    || row.setup_class === 'squeeze'
    || row.operator_color_token === 'squeeze'
  )
  if (!isSqueeze) return { isSqueeze: false }
  const rvol = row.rvol != null ? `${Number(row.rvol).toFixed(1)}x` : ''
  const text = row.operator_pill || (rvol ? `SQUEEZE · R/S · ${rvol}` : 'SQUEEZE · R/S')
  const hints = (row.operator_tooltip_hints && row.operator_tooltip_hints.length)
    ? row.operator_tooltip_hints
    : row.soft_flag_reason
      ? [String(row.soft_flag_reason)]
      : ['Manual review only — not auto GO']
  const subtitle = row.operator_subtitle || 'Reverse-split squeeze — Entry Desk'
  return {
    isSqueeze: true,
    text,
    subtitle,
    hints,
    tooltip: buildPillTooltip(row, 'squeeze', {
      subtitle,
      hints,
      footer: 'Squeeze / MANUAL_REVIEW — Ross-style R/S runner. Use Entry Desk; never auto GO.',
    }),
  }
}

export function isSqueezeRow(row: ScannerRow | null | undefined): boolean {
  return getSqueezePill(row).isSqueeze
}

/** High-RVOL WAIT upgraded to MANUAL_REVIEW — Ross-style momentum runners. */
export function getRunnerPill(row: ScannerRow | null | undefined): RunnerPill {
  const isRunner = !!row && (
    row.awareness_status === 'HIGH_RVOL'
    || row.setup_class === 'high_rvol_runner'
    || (row.decision === 'MANUAL_REVIEW' && row.operator_color_token === 'runner')
  )
  if (!isRunner || isSqueezeRow(row) || isMicroFloatRow(row)) return { isRunner: false }
  const rvol = row.rvol != null ? `${Number(row.rvol).toFixed(1)}x` : ''
  const text = row.operator_pill || (rvol ? `RUNNER · ${rvol}` : 'RUNNER')
  const hints = (row.operator_tooltip_hints && row.operator_tooltip_hints.length)
    ? row.operator_tooltip_hints
    : row.soft_flag_reason
      ? [String(row.soft_flag_reason)]
      : ['High RVOL — manual review only']
  const subtitle = row.operator_subtitle || 'High RVOL runner — Entry Desk'
  return {
    isRunner: true,
    text,
    subtitle,
    hints,
    tooltip: buildPillTooltip(row, 'runner', {
      subtitle,
      hints,
      footer: 'RUNNER / MANUAL_REVIEW — high RVOL momentum. Use Entry Desk; never auto GO.',
    }),
  }
}

export function isRunnerRow(row: ScannerRow | null | undefined): boolean {
  return getRunnerPill(row).isRunner
}

/** Micro-float + RVOL — manual review only (Ross-style low-float runners). */
export function getMicroFloatPill(row: ScannerRow | null | undefined): MicroFloatPill {
  const isMicroFloat = !!row && (
    row.awareness_status === 'MICRO_FLOAT'
    || row.setup_class === 'micro_float_runner'
    || row.operator_color_token === 'microFloat'
  )
  if (!isMicroFloat || isSqueezeRow(row)) return { isMicroFloat: false }
  const rvol = row.rvol != null ? `${Number(row.rvol).toFixed(1)}x` : ''
  const text = row.operator_pill || (rvol ? `MICRO · ${rvol}` : 'MICRO')
  const hints = (row.operator_tooltip_hints && row.operator_tooltip_hints.length)
    ? row.operator_tooltip_hints
    : row.soft_flag_reason
      ? [String(row.soft_flag_reason)]
      : ['Micro-float — manual review only']
  const subtitle = row.operator_subtitle || 'Micro-float runner — Entry Desk'
  return {
    isMicroFloat: true,
    text,
    subtitle,
    hints,
    tooltip: buildPillTooltip(row, 'microFloat', {
      subtitle,
      hints,
      footer: 'MICRO-FLOAT / MANUAL_REVIEW — low float + RVOL. Entry Desk only; never auto GO.',
    }),
  }
}

export function isMicroFloatRow(row: ScannerRow | null | undefined): boolean {
  return getMicroFloatPill(row).isMicroFloat
}

export interface LowPricePill {
  isLowPrice: boolean
  text?: string
  subtitle?: string
  hints?: string[]
  tooltip?: string
}

/** Sub-$2 spike — manual review only (Ross-style pump/squeeze). */
export function getLowPricePill(row: ScannerRow | null | undefined): LowPricePill {
  const isLowPrice = !!row && (
    row.awareness_status === 'LOW_PRICE'
    || row.setup_class === 'low_price_runner'
    || row.operator_color_token === 'lowPrice'
  )
  if (!isLowPrice || isSqueezeRow(row)) return { isLowPrice: false }
  const chg = row.change_pct != null ? `${Number(String(row.change_pct).replace('%', '')).toFixed(0)}%` : ''
  const text = row.operator_pill || (chg ? `LOW · ${chg}` : 'LOW')
  const subtitle = row.operator_subtitle || 'Low-price spike — Entry Desk'
  const hints = (row.operator_tooltip_hints && row.operator_tooltip_hints.length)
    ? row.operator_tooltip_hints
    : row.soft_flag_reason ? [String(row.soft_flag_reason)] : ['Sub-$2 spike — manual review only']
  return {
    isLowPrice: true,
    text,
    subtitle,
    hints,
    tooltip: buildPillTooltip(row, 'lowPrice', {
      subtitle,
      hints,
      footer: 'LOW-PRICE / MANUAL_REVIEW — sub-$2 momentum. Entry Desk only; never auto GO.',
    }),
  }
}

export function isLowPriceRow(row: ScannerRow | null | undefined): boolean {
  return getLowPricePill(row).isLowPrice
}

/** Any Ross-style MANUAL_REVIEW awareness lane (squeeze, runner, micro, low, momentum). */
export function isManualReviewRow(row: ScannerRow | null | undefined): boolean {
  if (!row) return false
  if ((row.decision || '').toUpperCase() === 'MANUAL_REVIEW') return true
  return isSqueezeRow(row) || isRunnerRow(row) || isMicroFloatRow(row) || isLowPriceRow(row)
    || row.setup_class === 'momentum_runner' || row.awareness_status === 'MOMENTUM_RUNNER'
}

export type ScannerSortMode = 'awareness' | 'score' | 'rvol' | 'change' | 'symbol'

export function sortTickerList<T extends ScannerRow>(rows: T[], mode: ScannerSortMode = 'awareness'): T[] {
  const out = rows.slice()
  if (mode === 'symbol') {
    return out.sort((a, b) => String(a.symbol || '').localeCompare(String(b.symbol || '')))
  }
  if (mode === 'score') {
    return out.sort((a, b) => Number(b.score ?? 0) - Number(a.score ?? 0))
  }
  if (mode === 'rvol') {
    return out.sort((a, b) => Number(b.rvol ?? 0) - Number(a.rvol ?? 0))
  }
  if (mode === 'change') {
    const chg = (r: ScannerRow) => parseFloat(String(r.change_pct ?? '').replace('%', '')) || 0
    return out.sort((a, b) => chg(b) - chg(a))
  }
  return out.sort((a, b) => scannerSortKey(b) - scannerSortKey(a))
}

export function scannerSortKey(row: ScannerRow): number {
  if (row.awareness_status === 'SQUEEZE' || row.setup_class === 'squeeze') {
    const sq = row.squeeze_sort_score
    if (sq != null && Number.isFinite(Number(sq))) return 1100 + Number(sq)
    const rvol = parseFloat(String(row.rvol ?? ''))
    const gap = parseFloat(String(row.gap_pct ?? '').replace('%', ''))
    return 1100 + (Number.isFinite(rvol) ? rvol * Math.max(Math.abs(gap), 1) : 0)
  }
  if (row.awareness_status === 'MICRO_FLOAT' || row.setup_class === 'micro_float_runner') {
    const ms = row.micro_float_sort_score
    if (ms != null && Number.isFinite(Number(ms))) return 1075 + Number(ms)
    const rvol = parseFloat(String(row.rvol ?? ''))
    return 1075 + (Number.isFinite(rvol) ? rvol * 2 : 0)
  }
  if (row.awareness_status === 'LOW_PRICE' || row.setup_class === 'low_price_runner') {
    const ls = row.low_price_sort_score
    if (ls != null && Number.isFinite(Number(ls))) return 1060 + Number(ls)
    const chg = parseFloat(String(row.change_pct ?? '').replace('%', ''))
    return 1060 + (Number.isFinite(chg) ? chg : 0)
  }
  if (row.awareness_status === 'MOMENTUM_RUNNER' || row.setup_class === 'momentum_runner') {
    return 1040 + Number(row.score ?? 0)
  }
  if (row.awareness_status === 'HIGH_RVOL' || row.setup_class === 'high_rvol_runner') {
    const rs = row.runner_sort_score
    if (rs != null && Number.isFinite(Number(rs))) return 1050 + Number(rs)
    const rvol = parseFloat(String(row.rvol ?? ''))
    const gap = parseFloat(String(row.gap_pct ?? '').replace('%', ''))
    return 1050 + (Number.isFinite(rvol) ? rvol * Math.max(Math.abs(gap), 1) : 0)
  }
  if (row.awareness_status === 'TOP_GAINER') {
    const chg = parseFloat(String(row.change_pct ?? '').replace('%', ''))
    return 1000 + (Number.isFinite(chg) ? chg : 0)
  }
  return Number(row.score ?? 0)
}

/** Map missing pillar keys → operator-facing tooltip hints (fallback when the API omits hints). */
export function missingPillarHints(missing?: string[]): string[] {
  const map: Record<string, string> = {
    catalyst_evidence: 'Needs catalyst verification',
    market_confirmation: 'Needs market confirmation',
    structure_tradeability: 'Needs tradeability check',
  }
  const out: string[] = []
  for (const m of missing || []) if (map[m]) out.push(map[m])
  return out
}
