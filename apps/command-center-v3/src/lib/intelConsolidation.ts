/** Intel consolidation (design intel/v001, operator-approved 2026-11-06) and Strategy two tabs (strategy/v001).
 *
 *  Pure helpers only, so they can be tested without a browser:
 *   - the redirect table: every retired Intel page still opens, at its new home, with its query mapped;
 *   - the real-conflict rule for Holdings verdicts: a mark / market-value disagreement is a conflict only when its
 *     relative gap exceeds the desk's own materiality threshold (served by /api/v3/advisory as
 *     `conflict_materiality_pct`, read from config/advisory_desk.yaml). The analyst-denominator note alone is never
 *     a conflict. With no threshold on the payload the rule fails closed: every mark / MV disagreement stays a conflict;
 *   - which advisory rows the Holdings verdicts tab hides (model-portfolio allocation gaps and paper-account rows);
 *   - Aegis thesis-broken split into held (CIO Desk) and not held (Research Intel › Thesis watch);
 *   - the Setups aggregation over real closed round trips (rec-intel lifecycle-performance) and the earnings-quality
 *     arithmetic over holdings P/E and forward P/E.
 *  Nothing here names a ticker or carries a numeric threshold of its own. */

// ── Redirects ────────────────────────────────────────────────────────────────────────────────────────────────────

export type IntelRedirect = { from: string; to: string; why: string }

/** The route → new-home table (documented in the report and asserted by intelConsolidation.test.ts). */
export const INTEL_REDIRECTS: readonly IntelRedirect[] = [
  { from: '/advisory', to: '/cio?tab=holdings', why: 'Advisory per-holding verdicts fold into CIO Desk › Holdings verdicts' },
  { from: '/intelligence', to: '/research-intelligence', why: 'Intelligence retires; its tabs map onto Research Intel (?tab mapped)' },
  { from: '/closed-loop', to: '/research-intelligence?tab=lineage', why: 'Lineage is the single surviving copy of Closed Loop' },
  { from: '/rec-intel', to: '/strategy?tab=setups', why: 'Real round trips by origin live in Strategy › Setups; ?symbol= opens that Prospectus' },
  { from: '/hermes', to: '/ops/engines', why: 'Hermes engine room moves to Ops › Engines (?tab kept)' },
] as const

/** Old Intelligence ?tab values → their new home. Unknown or absent tabs open Research Intel › Briefs. */
const INTELLIGENCE_TAB_HOME: Record<string, string> = {
  'closed-loop': '/research-intelligence?tab=lineage',
  inferences: '/research-intelligence?tab=thesis',
  news: '/research-intelligence?tab=news',
  research: '/research-intelligence?tab=briefs',
  sources: '/research-intelligence?tab=sources',
  workflow: '/ops/jobs?view=workflow',
  // Command Center / Signal Quality were client-side triage duplicates; Research Intel is their home now.
  command: '/research-intelligence',
  quality: '/research-intelligence',
}

/** Where a request for the retired /intelligence page goes. The rotation tab keeps its existing redirect. */
export function intelligenceRedirect(search: string): string {
  const q = new URLSearchParams(search)
  const tab = (q.get('tab') || '').trim().toLowerCase()
  if (tab === 'rotation') return '/rotation'
  return INTELLIGENCE_TAB_HOME[tab] ?? '/research-intelligence'
}

/** /rec-intel?symbol=X (Watchlist cards link there) opens that ticker's Prospectus, whose My history block shows
 *  the trades; without a symbol it opens Strategy › Setups (by discovery source). */
export function recIntelRedirect(search: string): string {
  const sym = (new URLSearchParams(search).get('symbol') || '').trim().toUpperCase()
  if (sym && /^[A-Z0-9.\-]{1,12}$/.test(sym)) return `/prospectus/${encodeURIComponent(sym)}`
  return '/strategy?tab=setups'
}

/** Keep the query string when a retired route maps one-for-one (e.g. /hermes?tab=Provenance&symbol=X). */
export function keepQueryRedirect(to: string, search: string): string {
  const s = search && search !== '?' ? (search.startsWith('?') ? search : `?${search}`) : ''
  if (!s) return to
  return to.includes('?') ? `${to}&${s.slice(1)}` : `${to}${s}`
}

// ── CIO Desk › Holdings verdicts: real conflicts only ───────────────────────────────────────────────────────────

export type ConflictFacts = {
  current_mark?: number | null
  implied_price_from_mv?: number | null
  implied_market_value?: number | null
  market_value?: number | null
  price_fields?: Record<string, unknown> | null
  conflicts?: string[] | null
}
export type ConflictRow = {
  data_quality?: { conflicts?: string[] | null; action_suppressed?: boolean } | null
  canonical_financial_facts?: ConflictFacts | null
  expand?: { canonical_financial_facts?: ConflictFacts | null } | null
}

const MARK_RE = /canonical mark \(([-\d.,]+)\)\s*≠\s*implied-from-MV \(([-\d.,]+)\)/
const MV_RE = /shares×price \(([-\d.,]+)\)\s*≠\s*market_value \(([-\d.,]+)\)/
const DUAL_RE = /^Dual price fields disagree/

const num = (v: unknown): number | null => {
  if (v == null || v === '') return null
  const n = typeof v === 'number' ? v : Number(String(v).replace(/,/g, ''))
  return Number.isFinite(n) ? n : null
}

/** Relative gap between two values, in percent of the larger magnitude (bounded 0–100 for same-sign values). */
export function relGapPct(a: number | null, b: number | null): number | null {
  if (a == null || b == null) return null
  const base = Math.max(Math.abs(a), Math.abs(b))
  if (base === 0) return 0
  return (Math.abs(a - b) / base) * 100
}

/** Every mark / market-value disagreement on the row, as relative gaps in percent. An empty list means the row
 *  carries no mark conflict at all (for example only the analyst-denominator note). A disagreement whose size
 *  cannot be measured is reported as `null` (treated as material). */
export function markConflictGaps(row: ConflictRow): (number | null)[] {
  const facts = row.expand?.canonical_financial_facts || row.canonical_financial_facts || null
  const msgs = [
    ...(row.data_quality?.conflicts || []),
    ...(facts?.conflicts || []),
  ].filter((c, i, a) => typeof c === 'string' && a.indexOf(c) === i)
  const gaps: (number | null)[] = []
  for (const m of msgs) {
    let hit = MARK_RE.exec(m)
    if (hit) {
      gaps.push(relGapPct(num(facts?.current_mark) ?? num(hit[1]), num(facts?.implied_price_from_mv) ?? num(hit[2])))
      continue
    }
    hit = MV_RE.exec(m)
    if (hit) {
      gaps.push(relGapPct(num(facts?.implied_market_value) ?? num(hit[1]), num(facts?.market_value) ?? num(hit[2])))
      continue
    }
    if (DUAL_RE.test(m)) {
      const vals = Object.values(facts?.price_fields || {}).map(num).filter((v): v is number => v != null && v > 0)
      gaps.push(vals.length >= 2 ? relGapPct(Math.min(...vals), Math.max(...vals)) : null)
    }
    // Anything else ("Analyst upside uses a different denominator…", the suppression banner) is a note, not a mark conflict.
  }
  return gaps
}

/** True only when the row's marks really disagree: some mark / MV gap is above the materiality threshold.
 *  `materialityPct` missing → fail closed (any mark / MV disagreement counts). */
export function isRealConflict(row: ConflictRow, materialityPct: number | null | undefined): boolean {
  const gaps = markConflictGaps(row)
  if (!gaps.length) return false
  const t = typeof materialityPct === 'number' && Number.isFinite(materialityPct) && materialityPct >= 0 ? materialityPct : null
  if (t == null) return true
  return gaps.some(g => g == null || g > t)
}

/** The conflict messages worth showing for a real conflict (the suppression banner and analyst note dropped). */
export function realConflictMessages(row: ConflictRow): string[] {
  const facts = row.expand?.canonical_financial_facts || row.canonical_financial_facts || null
  return [...(row.data_quality?.conflicts || []), ...(facts?.conflicts || [])]
    .filter((c, i, a) => typeof c === 'string' && a.indexOf(c) === i)
    .filter(c => MARK_RE.test(c) || MV_RE.test(c) || DUAL_RE.test(c))
}

// ── Rows the Holdings verdicts tab hides (data and backend untouched) ──────────────────────────────────────────

export type VerdictRow = { symbol?: string; account?: string | null; row_class?: string; verdict?: string; verdict_suppressed?: boolean }

const PAPER_ACCOUNT_RE = /(alpaca|paper)/i

/** Model-portfolio allocation-gap rows (row_class allocation, symbol ALLOC:…) and any paper-account row. */
export function isHiddenAdvisoryRow(r: VerdictRow): boolean {
  if (r.row_class === 'allocation') return true
  if (String(r.symbol || '').startsWith('ALLOC:')) return true
  if (PAPER_ACCOUNT_RE.test(String(r.account || ''))) return true
  return false
}

/** Verdict counts over the visible rows, largest first. Suppressed verdicts count as "Not enough data". */
export function verdictMix(rows: VerdictRow[]): { verdict: string; count: number }[] {
  const c = new Map<string, number>()
  for (const r of rows) {
    if (isHiddenAdvisoryRow(r)) continue
    const v = r.verdict_suppressed ? 'INSUFFICIENT_DATA' : String(r.verdict || 'UNKNOWN').toUpperCase()
    c.set(v, (c.get(v) || 0) + 1)
  }
  return [...c.entries()].map(([verdict, count]) => ({ verdict, count })).sort((a, b) => b.count - a.count || a.verdict.localeCompare(b.verdict))
}

// ── Aegis thesis-broken: held → CIO Desk, not held → Research Intel › Thesis watch ─────────────────────────────

export type AegisRow = { inference_type?: string; subject?: string; title?: string; body?: string; severity?: string; confidence?: number | string }

export function heldSymbolSet(holdings: { symbol?: string; is_cash?: boolean }[]): Set<string> {
  return new Set(holdings.filter(h => !h.is_cash).map(h => String(h.symbol || '').trim().toUpperCase()).filter(Boolean))
}

export function splitAegisByHeld(results: AegisRow[], held: Set<string>): { held: AegisRow[]; notHeld: AegisRow[] } {
  const aegis = results.filter(r => r.inference_type === 'aegis_thesis' && r.subject && r.subject !== 'portfolio')
  const out = { held: [] as AegisRow[], notHeld: [] as AegisRow[] }
  for (const r of aegis) (held.has(String(r.subject).toUpperCase()) ? out.held : out.notHeld).push(r)
  return out
}

// ── Research Intel tabs ───────────────────────────────────────────────────────────────────────────────────────

export const RESEARCH_INTEL_TABS = [
  { id: 'briefs', label: 'Briefs' },
  { id: 'news', label: 'News' },
  { id: 'thesis', label: 'Thesis watch' },
  { id: 'lineage', label: 'Lineage' },
  { id: 'sources', label: 'Sources' },
] as const
export type ResearchIntelTab = (typeof RESEARCH_INTEL_TABS)[number]['id']

const RI_ALIASES: Record<string, ResearchIntelTab> = {
  briefs: 'briefs', research: 'briefs', news: 'news', thesis: 'thesis', 'thesis-watch': 'thesis', inferences: 'thesis',
  lineage: 'lineage', 'closed-loop': 'lineage', sources: 'sources',
}
export function resolveResearchIntelTab(raw: string | null | undefined): ResearchIntelTab {
  return RI_ALIASES[String(raw || '').trim().toLowerCase()] ?? 'briefs'
}

// ── Strategy › Setups (real closed round trips) ───────────────────────────────────────────────────────────────

export type ClosedTrade = { symbol?: string; account?: string; origin?: string | null; setup?: string | null; close_date?: string; pnl?: number | null; pnl_pct?: number | null; hold_days?: number | null }
export type TradeGroup = { key: string; trades: number; wins: number; winRatePct: number | null; profitFactor: number | null; perTrade: number | null; total: number; avgReturnPct: number | null }

/** Real broker trades only: rows on a paper/Alpaca account are never counted. */
export function realTrades<T extends { account?: string | null }>(rows: T[]): T[] {
  return rows.filter(r => !PAPER_ACCOUNT_RE.test(String(r.account || '')))
}

export function summarizeTrades(key: string, rows: ClosedTrade[]): TradeGroup {
  const pnls = rows.map(r => num(r.pnl)).filter((v): v is number => v != null)
  const wins = pnls.filter(p => p > 0)
  const losses = pnls.filter(p => p < 0)
  const grossWin = wins.reduce((a, b) => a + b, 0)
  const grossLoss = -losses.reduce((a, b) => a + b, 0)
  const total = pnls.reduce((a, b) => a + b, 0)
  const rets = rows.map(r => num(r.pnl_pct)).filter((v): v is number => v != null)
  return {
    key,
    trades: rows.length,
    wins: wins.length,
    winRatePct: pnls.length ? (wins.length / pnls.length) * 100 : null,
    profitFactor: grossLoss > 0 ? grossWin / grossLoss : null,
    perTrade: pnls.length ? total / pnls.length : null,
    total,
    avgReturnPct: rets.length ? rets.reduce((a, b) => a + b, 0) / rets.length : null,
  }
}

/** Group closed trades by a field (setup or discovery origin), optionally inside a trailing window of days. */
export function groupTrades(rows: ClosedTrade[], by: 'setup' | 'origin', opts: { nowMs?: number; days?: number | null; untagged: string }): TradeGroup[] {
  const now = opts.nowMs ?? Date.now()
  const inWindow = (r: ClosedTrade) => {
    if (!opts.days) return true
    const t = r.close_date ? Date.parse(r.close_date) : NaN
    return Number.isFinite(t) && now - t <= opts.days * 86_400_000
  }
  const m = new Map<string, ClosedTrade[]>()
  for (const r of realTrades(rows)) {
    if (!inWindow(r)) continue
    const k = String((by === 'setup' ? r.setup : r.origin) || '').trim() || opts.untagged
    if (!m.has(k)) m.set(k, [])
    m.get(k)!.push(r)
  }
  return [...m.entries()].map(([k, v]) => summarizeTrades(k, v)).sort((a, b) => b.trades - a.trades || a.key.localeCompare(b.key))
}

// ── Strategy › Earnings quality ───────────────────────────────────────────────────────────────────────────────

export type HoldingFundamentals = { symbol?: string; company?: string; sector?: string; pe?: number | string | null; forward_pe?: number | string | null; peg?: number | string | null; eps_ttm?: number | string | null; is_cash?: boolean; asset_type?: string; market_value?: number | null }
export type EarningsRow = { symbol: string; company: string; sector: string; pe: number | null; forwardPe: number | null; peg: number | null; impliedEpsGrowthPct: number | null; note: string }

/** One row per held symbol: trailing and forward P/E and the EPS growth the forward multiple implies
 *  (trailing P/E ÷ forward P/E − 1, same price). Facts only — no label or threshold. */
export function earningsQuality(holdings: HoldingFundamentals[]): EarningsRow[] {
  const by = new Map<string, HoldingFundamentals>()
  for (const h of holdings) {
    const s = String(h.symbol || '').trim().toUpperCase()
    if (!s || h.is_cash || s === 'CASH') continue
    if (!by.has(s)) by.set(s, h)
  }
  const rows: EarningsRow[] = []
  for (const [symbol, h] of by) {
    const pe = num(h.pe), fpe = num(h.forward_pe), peg = num(h.peg)
    const implied = pe != null && fpe != null && pe > 0 && fpe > 0 ? (pe / fpe - 1) * 100 : null
    const note = pe == null && fpe == null ? 'No earnings data on file (fund or no coverage)'
      : pe == null || pe <= 0 ? (fpe != null && fpe > 0 ? 'No trailing earnings; forward estimate only' : 'No trailing earnings')
        : fpe == null || fpe <= 0 ? 'No forward estimate on file'
          : implied != null && implied >= 0 ? `Forward multiple implies EPS ${implied >= 0 ? '+' : ''}${implied.toFixed(0)}%`
            : `Forward multiple implies EPS ${implied!.toFixed(0)}% (estimates below trailing)`
    rows.push({ symbol, company: String(h.company || ''), sector: String(h.sector || ''), pe, forwardPe: fpe, peg, impliedEpsGrowthPct: implied, note })
  }
  return rows.sort((a, b) => (b.impliedEpsGrowthPct ?? -Infinity) - (a.impliedEpsGrowthPct ?? -Infinity) || a.symbol.localeCompare(b.symbol))
}
