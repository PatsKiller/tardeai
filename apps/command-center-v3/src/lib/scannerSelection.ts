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

export interface ScoutPill {
  isScout: boolean
  text?: string
  colorToken?: string
  subtitle?: string
  hints?: string[]
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
  return {
    isScout: true,
    text,
    colorToken: row.operator_color_token || 'socialScout',
    subtitle: row.operator_subtitle || 'Not quite there yet',
    hints,
  }
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
