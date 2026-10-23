/**
 * Trade AI opportunities model (operator-approved Gate 3 design Main.dc.html, 2026-10-22).
 *
 * Pure: turns the existing /api/v2/trade-ai/scanner rows into the six filter tiles, the float-first
 * table / cards, the filter chips and the AI-analysis panel, and maps the Level 2 entry signals that
 * /api/v3/active-trader/alerts already serves (scripts/active_trader/microstructure_signals.py via
 * momentum_alerts_api._signals_view) onto the panel's chips.
 *
 * Gate 2 fields — catalyst type, catalyst grade (★), validation, the action score and the AI checks —
 * come from the CIO prospect record (AGENTS.md §26), which does not exist yet. Until a row carries them
 * they render "—" with GATE2_TIP; nothing here invents a grade, a score or a verdict. Awareness only:
 * a scanner decision never grants approval.
 */

export type Decision = 'GO' | 'WAIT' | 'MANUAL' | 'AVOID' | 'OTHER'
export type SortKey = 'score' | 'float' | 'rvol' | 'chg' | 'grade' | 'act'

export const GATE2_TIP = 'Arrives with the CIO prospect record (Gate 2, AGENTS.md §26). Until that store exists this field is not computed, so it shows —.'

export interface Opportunity {
  sym: string
  sector: string | null
  float: number | null          // millions of shares
  volume: number | null
  rvol: number | null
  chg: number | null            // percent
  price: number | null
  score: number | null          // scanner score
  setupGrade: string | null     // scanner setup grade letter (A–F)
  decision: Decision
  decisionRaw: string
  catalyst: string | null
  catalystSource: string | null
  catalystVerified: boolean | null
  catalystConfidence: number | null
  // Gate 2 (null until the CIO prospect record serves them)
  catalystType: string | null
  catalystGrade: number | null  // 1–5
  validation: string | null
  validationOk: boolean | null
  act: number | null            // 0–100
  // existing scanner critic (an LLM review the scanner already runs) — shown as such, never as Gate 2
  critic: { verdict: string; confidence: number | null; reasoning: string | null; flags: string[] } | null
  pill: string | null
  subtitle: string | null
  raw: any
}

const num = (v: unknown): number | null => {
  if (v === null || v === undefined || v === '') return null
  const n = Number(v)
  return Number.isFinite(n) ? n : null
}

export function normDecision(d: unknown): Decision {
  const s = String(d ?? '').toUpperCase().replace(/-/g, '_')
  if (s === 'GO') return 'GO'
  if (s === 'WAIT') return 'WAIT'
  if (s === 'MANUAL_REVIEW' || s === 'MANUAL') return 'MANUAL'
  if (s === 'AVOID' || s === 'NO_GO' || s === 'NOGO' || s === 'NO') return 'AVOID'
  return 'OTHER'
}

export function toOpportunity(t: any): Opportunity {
  const critic = t?.critic_verdict
    ? { verdict: String(t.critic_verdict), confidence: num(t.critic_confidence), reasoning: t.critic_reasoning ?? null,
        flags: Array.isArray(t.critic_flags) ? t.critic_flags.map(String) : [] }
    : null
  const grade = num(t?.catalyst_grade)
  return {
    sym: String(t?.symbol ?? '—').toUpperCase(),
    sector: t?.sector ?? null,
    // A float of 0 means the scanner had no float, not a zero-share float: unknown, never "micro".
    float: (() => { const f = num(t?.float_m ?? t?.float); return f != null && f > 0 ? f : null })(),
    volume: num(t?.volume),
    rvol: num(t?.rvol),
    chg: num(t?.change_pct ?? t?.change),
    price: num(t?.price),
    score: num(t?.score),
    setupGrade: t?.grade ? String(t.grade) : null,
    decision: normDecision(t?.decision),
    decisionRaw: String(t?.decision ?? '—'),
    catalyst: t?.catalyst ? String(t.catalyst) : null,
    catalystSource: t?.catalyst_source ?? null,
    catalystVerified: typeof t?.catalyst_verified === 'boolean' ? t.catalyst_verified : null,
    catalystConfidence: num(t?.catalyst_confidence),
    catalystType: t?.catalyst_type ? String(t.catalyst_type) : null,
    catalystGrade: grade != null && grade >= 0 && grade <= 5 ? Math.round(grade) : null,
    validation: t?.catalyst_validation ? String(t.catalyst_validation) : null,
    validationOk: typeof t?.catalyst_validation_ok === 'boolean' ? t.catalyst_validation_ok : null,
    act: num(t?.action_score),
    critic,
    pill: t?.operator_pill ?? null,
    subtitle: t?.operator_subtitle ?? null,
    raw: t,
  }
}

export interface Filters {
  dec: Decision | null
  minGrade: number
  floatMax: number | null
  rvolMin: number | null
  sector: string | null
}

export const NO_FILTERS: Filters = { dec: null, minGrade: 0, floatMax: null, rvolMin: null, sector: null }

export function applyFilters(rows: Opportunity[], f: Filters): Opportunity[] {
  return rows.filter(r =>
    (!f.dec || r.decision === f.dec)
    && (!f.minGrade || (r.catalystGrade != null && r.catalystGrade >= f.minGrade))
    && (f.floatMax == null || (r.float != null && r.float < f.floatMax))
    && (f.rvolMin == null || (r.rvol != null && r.rvol >= f.rvolMin))
    && (!f.sector || r.sector === f.sector))
}

const DEC_RANK: Record<Decision, number> = { GO: 4, MANUAL: 3, WAIT: 2, OTHER: 1, AVOID: 0 }

export function sortOpportunities(rows: Opportunity[], key: SortKey): Opportunity[] {
  const out = [...rows]
  const desc = (a: number | null, b: number | null) => (b ?? -Infinity) - (a ?? -Infinity)
  if (key === 'float') return out.sort((a, b) => (a.float ?? Infinity) - (b.float ?? Infinity))
  if (key === 'rvol') return out.sort((a, b) => desc(a.rvol, b.rvol))
  if (key === 'chg') return out.sort((a, b) => desc(a.chg, b.chg))
  if (key === 'grade') return out.sort((a, b) => desc(a.catalystGrade, b.catalystGrade) || desc(a.score, b.score))
  if (key === 'act') return out.sort((a, b) => desc(a.act, b.act) || desc(a.score, b.score))
  return out.sort((a, b) => DEC_RANK[b.decision] - DEC_RANK[a.decision] || desc(a.score, b.score))
}

export function floatBand(f: number | null): number | null {
  if (f == null) return null
  return f < 5 ? 5 : f < 20 ? 20 : null
}

export interface Tile { key: string; label: string; value: number | null; hint: string; tone: 'success' | 'warning' | 'ai' | 'info' | 'neutral'; active: boolean; disabled: boolean; patch: (active: boolean) => Partial<Filters>; tip?: string }

// The decision tiles count TODAY'S UNIVERSE (every row any run surfaced today), never the latest run.
// The header SETUPS · LATEST RUN tile counts only the latest run, so the two differ by design
// (operator 2026-10-23: "0 GO · 0 WAIT · 7 NOGO" in the header vs "19 WAIT · 71 MANUAL REVIEW" here).
export const UNIVERSE_TILE_TIP = "Counts every row in today's scanner universe: each symbol any run surfaced today, at its latest decision. "
  + 'The header SETUPS · LATEST RUN tile counts only the most recent run, so the two numbers differ by design.'

export function buildTiles(all: Opportunity[], f: Filters): Tile[] {
  const count = (fn: (r: Opportunity) => boolean) => all.filter(fn).length
  const hasGate2 = all.some(r => r.catalystGrade != null)
  const uni = `today's universe · ${all.length} rows`
  return [
    { key: 'go', label: 'GO', value: count(r => r.decision === 'GO'), hint: uni, tip: UNIVERSE_TILE_TIP, tone: 'success', active: f.dec === 'GO', disabled: false, patch: a => ({ dec: a ? null : 'GO' }) },
    { key: 'wait', label: 'WAIT', value: count(r => r.decision === 'WAIT'), hint: uni, tip: UNIVERSE_TILE_TIP, tone: 'warning', active: f.dec === 'WAIT', disabled: false, patch: a => ({ dec: a ? null : 'WAIT' }) },
    { key: 'manual', label: 'Manual review', value: count(r => r.decision === 'MANUAL'), hint: `${uni} · Entry Desk only`, tip: UNIVERSE_TILE_TIP, tone: 'ai', active: f.dec === 'MANUAL', disabled: false, patch: a => ({ dec: a ? null : 'MANUAL' }) },
    { key: 'grade', label: 'Grade ★4+', value: hasGate2 ? count(r => (r.catalystGrade ?? 0) >= 4) : null, hint: hasGate2 ? 'strong catalysts' : 'Gate 2', tone: 'warning', active: f.minGrade === 4, disabled: !hasGate2, tip: hasGate2 ? undefined : GATE2_TIP, patch: a => ({ minGrade: a ? 0 : 4 }) },
    { key: 'float', label: 'Float < 5M', value: count(r => r.float != null && r.float < 5), hint: 'micro float', tone: 'info', active: f.floatMax === 5, disabled: false, patch: a => ({ floatMax: a ? null : 5 }) },
    { key: 'rvol', label: 'RVOL ≥ 10×', value: count(r => r.rvol != null && r.rvol >= 10), hint: 'high attention', tone: 'info', active: f.rvolMin === 10, disabled: false, patch: a => ({ rvolMin: a ? null : 10 }) },
  ]
}

export function filterChips(f: Filters): Array<{ label: string; clear: Partial<Filters> }> {
  const out: Array<{ label: string; clear: Partial<Filters> }> = []
  if (f.dec) out.push({ label: `Decision: ${f.dec === 'MANUAL' ? 'Manual review' : f.dec}`, clear: { dec: null } })
  if (f.minGrade) out.push({ label: `Grade ≥ ${f.minGrade}`, clear: { minGrade: 0 } })
  if (f.floatMax != null) out.push({ label: `Float < ${f.floatMax}M`, clear: { floatMax: null } })
  if (f.rvolMin != null) out.push({ label: `RVOL ≥ ${f.rvolMin}×`, clear: { rvolMin: null } })
  if (f.sector) out.push({ label: `Sector: ${f.sector}`, clear: { sector: null } })
  return out
}

export function stars(g: number | null): string {
  if (g == null) return '—'
  return '★★★★★'.slice(0, g) + '☆☆☆☆☆'.slice(0, 5 - g)
}

export function floatText(f: number | null): string {
  return f == null ? '—' : `${f.toFixed(f < 10 ? 2 : 1)}M`
}

export function volText(v: number | null): string {
  if (v == null) return '—'
  if (v >= 1e6) return `${(v / 1e6).toFixed(1)}M`
  if (v >= 1e3) return `${Math.round(v / 1e3)}K`
  return String(Math.round(v))
}

export function rvolText(v: number | null): string {
  return v == null ? '—' : `${v.toFixed(v < 10 ? 1 : 0)}×`
}

export function chgText(v: number | null): string {
  return v == null ? '—' : `${v > 0 ? '+' : ''}${v.toFixed(1)}%`
}

// ── Level 2 / tape (served entry signals) ─────────────────────────────────────────────────────────
export type L2Chip = { key: string; label: string; on: boolean | null; value: string; warn: boolean; tip: string }
export interface L2View {
  watched: boolean
  state: string
  feed: string
  stale: boolean
  summary: string
  entry: L2Chip[]
  exit: L2Chip[]
  at: string | null
}

const ENTRY_DEFS: Array<{ key: string; label: string; warn?: boolean; tip: string }> = [
  { key: 'spread', label: 'Spread', tip: 'Inside spread in basis points (lit when ≤ 25 bps)' },
  { key: 'imbalance', label: 'Bid/ask depth', tip: 'Bid depth ÷ ask depth from the served book (lit when ≥ 1.5)' },
  { key: 'supply_thinning', label: 'Supply thinning', tip: 'Ask size near the price shrinking over the window' },
  { key: 'ask_refill', label: 'Ask refill', warn: true, tip: 'A seller reloading the offer (bearish when lit)' },
  { key: 'book_pull', label: 'Book pull', warn: true, tip: 'Both sides of the book pulled' },
  { key: 'volume_acceleration', label: 'Volume accel.', tip: 'Last minute volume vs the prior average' },
  { key: 'high_break', label: 'High break', tip: 'Broke the premarket or session high' },
  { key: 'vwap_distance', label: 'VWAP distance', warn: true, tip: 'Extended above session VWAP (warning when lit)' },
]
const EXIT_DEFS: Array<{ key: string; label: string; tip: string }> = [
  { key: 'tape_flip', label: 'Tape flip', tip: 'Prints flipped to the bid' },
  { key: 'volume_climax', label: 'Volume climax', tip: 'Blow-off volume bar with an upper wick' },
  { key: 'ask_wall', label: 'Ask wall', tip: 'Large offer stacked above the price' },
  { key: 'close_below_prior_low', label: 'Close < prior low', tip: '1-minute close under the prior bar low' },
  { key: 'vwap_loss', label: 'VWAP loss', tip: 'Lost session VWAP' },
]
const NOT_SERVED = 'Not served for scanner names: exit signals are computed by the Active Trader exit watch for open scalps.'

function fmtVal(v: unknown): string {
  if (v == null) return '—'
  if (typeof v === 'number') return Math.abs(v) >= 100 ? v.toFixed(0) : v.toFixed(2).replace(/\.?0+$/, '')
  if (typeof v === 'boolean') return v ? 'yes' : 'no'
  return String(v)
}

/** Latest served Active Trader decision row for this symbol, or null. */
export function latestAlertFor(feed: any, sym: string): any | null {
  const rows: any[] = Array.isArray(feed?.decisions) ? feed.decisions : []
  const mine = rows.filter(r => String(r?.symbol ?? '').toUpperCase() === sym.toUpperCase())
  if (!mine.length) return null
  return mine.reduce((a, b) => ((Number(b?.ts_epoch) || 0) > (Number(a?.ts_epoch) || 0) ? b : a))
}

export function l2View(row: any | null, maxAgeS = 15): L2View {
  const blankEntry = ENTRY_DEFS.map(d => ({ key: d.key, label: d.label, on: null, value: '—', warn: !!d.warn, tip: d.tip }))
  const exit = EXIT_DEFS.map(d => ({ key: d.key, label: d.label, on: null, value: '—', warn: true, tip: `${d.tip}. ${NOT_SERVED}` }))
  if (!row) {
    return { watched: false, state: 'NOT WATCHED', feed: 'no book subscribed', stale: false,
      summary: 'Level 2 starts when the symbol reaches the Active Trader watch', entry: blankEntry, exit, at: null }
  }
  const l2 = row.l2 ?? {}
  const age = num(l2.age_s)
  const stale = age == null || age > maxAgeS
  const detail: Record<string, any> = row.signals?.detail ?? {}
  const spread = num(l2.spread_bps)
  const depth = num(l2.depth_ratio)
  const entry: L2Chip[] = ENTRY_DEFS.map(d => {
    if (d.key === 'spread') return { ...blankEntry[0], on: spread == null ? null : spread <= 25, value: spread == null ? '—' : `${spread.toFixed(0)} bps` }
    if (d.key === 'imbalance') return { ...blankEntry[1], on: depth == null ? null : depth >= 1.5, value: depth == null ? '—' : `${depth.toFixed(1)} : 1` }
    const s = detail[d.key]
    const base = blankEntry.find(b => b.key === d.key)!
    if (!s) return base
    return { ...base, on: typeof s.on === 'boolean' ? s.on : null, value: fmtVal(s.value) }
  })
  const lit = entry.filter(c => c.on === true && !c.warn).length
  const warns = entry.filter(c => c.on === true && c.warn).length
  const levels = num(l2.levels)
  return {
    watched: true,
    state: String(row.verdict || row.kind || 'WATCHED').toUpperCase(),
    feed: `${l2.source ?? 'book'}${levels != null ? ` · ${levels} levels` : ''}${age != null ? ` · ${age < 1 ? age.toFixed(1) : Math.round(age)} s old` : ''}${stale ? ' (stale)' : ''}`,
    stale,
    summary: row.signals?.status && row.signals.status !== 'OK'
      ? `Signals: ${String(row.signals.status).replace(/_/g, ' ').toLowerCase()}`
      : `${lit} of ${ENTRY_DEFS.length - 3} entry signals lit${warns ? ` · ${warns} warning${warns > 1 ? 's' : ''}` : ' · no warnings'}`,
    entry, exit, at: row.at ?? null,
  }
}
