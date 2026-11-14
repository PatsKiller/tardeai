/**
 * DefenseProjection@v1 (design defense/v001) — types and pure display helpers for the v3 Defense page.
 *
 * The projection is built server-side by scripts/defense_engine_build.py and served by
 * GET /api/v2/defense/engine. Every sentence and number on the page comes from it; these helpers only
 * choose a tone, format a clock or a dollar figure, and say "not on file" when a field is missing.
 * Nothing here sizes, orders or sets a level: the projection carries no such field (schema test).
 */

export type Tone = 'good' | 'warn' | 'bad' | 'info' | 'muted'
export type Section = { as_of?: string | null; stale_reason?: string | null }

/** LQ-20261107-1837 (C4): what the Defense page may take from the live authorities instead of the projection's
 *  frozen copy. Both come from functions in `metricAuthority.ts`; absent means the surface falls back to the
 *  projection's own field (and keeps saying where it came from). */
export type LiveAuthority = {
  marketRisk?: { tier: string; score: number | null; asOf: string | null } | null
  unprotected?: { count: number | null; valueUsd: number | null; asOf: string | null } | null
}

export type LadderStep = { tier: string; min_score: number | null; current: boolean }
export type TierSection = Section & {
  tier?: string | null
  score?: number | null
  shock?: { class?: string | null; label?: string | null; confidence?: number | null; headline?: string | null }
  confirming?: { n?: number | null; of?: number | null }
  ladder?: LadderStep[]
  since?: string | null
  acknowledged_at?: string | null
  deescalates_if?: string | null
  held_by_session_rule?: boolean | null
  sessions_recorded?: { n?: number | null; of?: number | null }
  history?: { as_of?: string | null; score?: number | null; tier?: string | null }[]
}
export type ExposureRow = {
  symbol: string; account_label?: string | null; value_usd?: number | null; stressed_share?: number | null
  usd_exposed?: number | null; stop_distance_pct?: number | null; stance?: string | null; stance_label?: string | null
}
export type Budget = { account_label?: string | null; budget?: string | null; limit?: number | null; actual?: number | null; unit?: string | null }
export type ExposureSection = Section & {
  invested_usd?: number | null; cash_usd?: number | null; cash_pct_book?: number | null
  stressed_usd?: number | null; stressed_pct_invested?: number | null; stressed_pct_book?: number | null
  stressed_groups?: string[]; rows?: ExposureRow[]
  /** DR-D01 (sprint 8H-2 b1): what the dollars above rest on. `coverage_status` is the server's verdict —
   *  `measured` (every non-cash position carried a look-through), `partial` (some did not: `stressed_usd` is a
   *  floor, not the book's exposure) or `unknown` (nothing to measure). A projection built before this field
   *  existed publishes none of them, and the view must then say Unknown: a missing look-through and a genuine
   *  zero printed the same "$0 · 0 % of invested" (audit DR-D01). */
  coverage_status?: 'measured' | 'partial' | 'unknown' | string | null
  positions_count?: number | null; mapped_count?: number | null; unmapped_count?: number | null
  mapped_usd?: number | null; unmapped_usd?: number | null; look_through_basis?: string[]
  /** F1: non-cash positions with no usable value. They never enter `positions_count` (that count is the rows the
   *  figure summed), so a book of two positions, one unpriced, used to publish "1 of 1 positions mapped". They
   *  make `coverage_status` partial. `unpriced_count` absent = not published. */
  unpriced_count?: number | null; unpriced_symbols?: string[]
  residuals?: { count?: number | null; usd_exposed?: number | null; symbols?: string[] }
  unmapped?: { symbol: string; account_label?: string | null; usd?: number | null; reason?: string | null }[]
  budgets?: Budget[]
  rotate?: { key?: string; label?: string | null; state?: string | null; rs5?: number | null; usd?: number | null }[]
}
export type ProtectionUnit = { count?: number | null; value_usd?: number | null }
/** DR-D02: the stop total decomposed by state, plus what it excludes and what it cannot measure.
 *
 *  The view used to print one merged headline ("3 without a broker stop") for a total that Risk and Portfolio
 *  split into two no-stop positions and one planned-only level. The producer now publishes every state, the
 *  merged figure labelled as "no resting broker order", the excluded positions and the quantities it cannot
 *  measure, so the page prints the decomposition instead of choosing one of the three totals. */
export type ProtectionReconciliation = {
  counted_positions?: number | null
  by_state?: Partial<Record<'active' | 'pending_activation' | 'planned_only' | 'no_stop' | 'unknown' | 'filled', ProtectionUnit>>
  no_resting_order?: ProtectionUnit & { definition?: string | null }
  resting_or_pending?: ProtectionUnit
  excluded?: { count?: number | null; value_usd?: number | null; by_reason?: unknown; note?: string | null }
  partial_quantities?: { known?: boolean | null; reason?: string | null }
  coverage?: string | null
}
export type ProtectionUnknownRow = { symbol?: string | null; account_label?: string | null; value_usd?: number | null; state?: string | null; cause?: string | null; reason?: string | null }
export type StopsSection = Section & {
  no_stop?: { count?: number | null; value_usd?: number | null }
  pending?: { count?: number | null; value_usd?: number | null }
  planned_only?: number | null; active?: number | null; filled?: { count?: number | null }
  near_threshold_pct?: number | null
  gaps?: { symbol: string; account_label?: string | null; value_usd?: number | null; state?: string | null }[]
  near?: { symbol: string; account_label?: string | null; distance_pct?: number | null }[]
  reconciliation?: ProtectionReconciliation | null
  unknown_rows?: ProtectionUnknownRow[] | null
  hedged_share?: string | null; beta?: string | null
}
// `when` is the rule in words (defense_engine._hedge_section publishes it, lines 532-533); the view prints it
// where it exists and falls back to the numeric threshold.
export type HedgeTrigger = { id: string; label: string; value?: number | null; threshold?: number | null; unit?: string | null; met?: boolean | null; detail?: string | null; when?: string | null }
export type HedgeSection = Section & {
  readiness?: 'NOT NOW' | 'CONDITIONS MET' | 'UNKNOWN' | string | null
  shock_class?: string | null; shock_confidence?: number | null
  triggers?: HedgeTrigger[]; met_count?: number | null; of?: number | null
  inverse_triggers?: Record<string, { inverse?: string | null; trigger?: boolean | null; exposure_pct?: number | null; reason?: string | null }>
  inverse_lane?: { inverse?: string | null; bench?: string | null; name?: string | null; leverage?: string | null; expense_pct?: number | null; thesis_state?: string | null; thesis_label?: string | null }[]
  thesis_light?: { state?: string | null; label?: string | null; reason?: string | null; as_of?: string | null; stale_reason?: string | null }
  put_protection?: { qqq_atm_iv?: number | null; as_of?: string | null; structures?: number | null; lifecycle?: { state?: string | null; as_of?: string | null; stale_reason?: string | null } }
}
export type BaseRates = Section & {
  rows?: { label: string; median_pct?: number | null; p10_pct?: number | null; lower_pct?: number | null; n?: number | null }[]
  n?: number | null; further_drop_pct?: number | null; notes?: { id?: string; text?: string }[]; caveat?: string | null
}
export type CashSection = Section & {
  state?: string | null; yields_on_file?: boolean | null; risk_free_rate_constant?: number | null
  cash_pct_book?: number | null; cash_usd?: number | null
  vehicles?: { symbol: string; name?: string | null; category?: string | null; yield_pct?: number | null }[]
}
export type SectorSection = Section & {
  engine?: { key: string; label: string; state?: string | null; rs5?: number | null; check_data?: boolean | null }[]
  stressed?: string[]; sectors_measured?: number | null; sectors_hit?: number | null
  desk_copy?: Section & { classified?: number | null; of?: number | null }
  disagreements?: { label?: string; engine?: string | null; desk?: string | null }[]
}
export type SourceRow = { id: string; label: string; as_of?: string | null; age_hours?: number | null; sla_hours?: number | null; lane_ids?: string[]; state: string; stale_reason?: string | null }
export type Step = { id: string; sheet: string; tone?: string | null; title: string; text: string }
export type DefenseProjection = {
  schema: 'DefenseProjection@v1'
  generated_at: string
  as_of?: string | null
  stale_reason?: string | null
  narrative: { headline?: string | null; where_we_stand?: (Section & { field?: string; text: string })[]; what_to_do?: Step[]; disclaimer?: string | null }
  tier: TierSection
  exposure: ExposureSection
  stops: StopsSection
  hedge_readiness: HedgeSection
  playbook: Section & { current_tier?: string | null; stage_text?: string | null; stage_text_reason?: string | null; black_tier?: string | null; hedge_conditions?: string[]; deescalates_if?: string | null }
  base_rates: BaseRates
  cash_alternatives: CashSection
  sector_posture: SectorSection
  recommendations: Section & { mode?: string | null; counts?: Record<string, number>; dropped_unheld?: { group: string; title?: string | null; symbols: string[] }[]; short_side?: { title?: string | null; symbols?: string[]; mode?: string | null }[]; note?: string | null }
  watch_next: Section & { items?: { kind?: string; text: string; as_of?: string | null }[] }
  industries?: Section & { count?: number | null; bottom?: { name?: string | null; state?: string | null }[] }
  sources: SourceRow[]
  source_summary?: Record<string, number>
  served?: { served_from?: string | null; age_hours?: number | null; stale?: boolean | null; fallback_reason?: string | null }
}

export const GAP = 'not on file'
export const LADDER_ORDER = ['GREEN', 'BLUE', 'YELLOW', 'ORANGE', 'RED'] as const

export function isProjection(x: unknown): x is DefenseProjection {
  return !!x && typeof x === 'object' && (x as { schema?: unknown }).schema === 'DefenseProjection@v1'
}

/** The endpoint serves a stale-aware envelope ({served_from, stale, data: projection}); accept it or a bare projection. */
export function unwrapProjection(x: unknown): DefenseProjection | null {
  if (isProjection(x)) return x
  for (let i = 0, cur: unknown = x; i < 3 && cur && typeof cur === 'object'; i++) {
    cur = (cur as { data?: unknown }).data
    if (isProjection(cur)) return cur
  }
  return null
}

export function tierTone(tier: string | null | undefined): Tone {
  switch ((tier ?? '').toUpperCase()) {
    case 'RED': case 'ORANGE': return 'bad'
    case 'YELLOW': return 'warn'
    case 'BLUE': return 'info'
    case 'GREEN': return 'good'
    default: return 'muted'
  }
}

export function num(v: unknown): number | null {
  return typeof v === 'number' && Number.isFinite(v) ? v : null
}

/** "$86.4K", "$1.2M", "$211" — or GAP. */
export function money(v: unknown): string {
  const n = num(v)
  if (n === null) return GAP
  const a = Math.abs(n), s = n < 0 ? '−' : ''
  if (a >= 1e6) return `${s}$${(a / 1e6).toFixed(1)}M`
  if (a >= 1e4) return `${s}$${(a / 1e3).toFixed(1)}K`
  if (a >= 1e3) return `${s}$${(a / 1e3).toFixed(1)}K`
  return `${s}$${Math.round(a)}`
}

export function pct(v: unknown, digits = 0): string {
  const n = num(v)
  return n === null ? GAP : `${n.toFixed(digits)}%`
}

export function signed(v: unknown, digits = 1): string {
  const n = num(v)
  if (n === null) return GAP
  return `${n > 0 ? '+' : n < 0 ? '−' : ''}${Math.abs(n).toFixed(digits)}`
}

/** A clock that never invents a time: "16:15 ET", "Fri 16:15 ET" (other day), or GAP. */
export function clockET(iso: string | null | undefined, now: Date = new Date()): string {
  if (!iso || !/T.*(?:Z|[+-]\d\d:\d\d)$/.test(iso)) return iso && /^\d{4}-\d\d-\d\d$/.test(iso) ? `${iso.slice(5)} close` : GAP
  const t = new Date(iso)
  if (Number.isNaN(t.getTime())) return GAP
  const fmt = (o: Intl.DateTimeFormatOptions) => new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', ...o }).format(t)
  const day = (d: Date) => new Intl.DateTimeFormat('en-CA', { timeZone: 'America/New_York' }).format(d)
  const hm = fmt({ hour: '2-digit', minute: '2-digit', hour12: false })
  if (day(t) === day(now)) return `${hm} ET`
  const ageDays = (now.getTime() - t.getTime()) / 86_400_000
  if (ageDays < 6) return `${fmt({ weekday: 'short' })} ${hm} ET`
  return fmt({ month: 'short', day: 'numeric' })
}

export function sourceTone(state: string): Tone {
  return state === 'fresh' ? 'good' : state === 'stale' || state === 'paused' ? 'warn' : state === 'missing' || state === 'no_writer' ? 'bad' : 'muted'
}

/** "7 fresh · 1 paused · 1 no writer" — zero counts are left out. */
export function sourceSummaryText(summary: Record<string, number> | undefined, sources: SourceRow[] = []): string {
  const counts = summary ?? sources.reduce<Record<string, number>>((acc, s) => ({ ...acc, [s.state]: (acc[s.state] ?? 0) + 1 }), {})
  const order = ['fresh', 'stale', 'missing', 'paused', 'no_writer']
  const parts = order.filter(k => (counts[k] ?? 0) > 0).map(k => `${counts[k]} ${k.replace('_', ' ')}`)
  return parts.length ? parts.join(' · ') : 'no sources on file'
}

export function readinessTone(r: string | null | undefined): Tone {
  return r === 'CONDITIONS MET' ? 'bad' : r === 'NOT NOW' ? 'info' : 'warn'
}

/** The ladder in engine order, with the current tier marked, even if the projection omitted steps. */
export function ladder(t: TierSection): LadderStep[] {
  const byTier = new Map((t.ladder ?? []).map(s => [s.tier, s]))
  return LADDER_ORDER.map(tier => byTier.get(tier) ?? { tier, min_score: null, current: (t.tier ?? '').toUpperCase() === tier })
}

/** Where the score sits on a 0–100 bar (clamped), or null when not measured. */
export function scorePosition(score: unknown): number | null {
  const n = num(score)
  return n === null ? null : Math.max(0, Math.min(100, n))
}

export type Line = { id: string; sheet: string; label: string; sub: string; value: string; valueSub?: string; tone: Tone; asOf?: string | null; staleReason?: string | null }

export interface UnprotectedPair { count: number | null; valueUsd: number | null; asOf: string | null; staleReason: string | null; source: 'cio_truth' | 'projection' }

/** The unprotected count and value from ONE source (LQ-20261107-1837 REWORK 2, must-fix F1).
 *
 *  cio_truth's `stops.unprotected_count` counts positions worth $100 or more; the projection's
 *  `stops.no_stop` slice was built over its own rows. Pairing a count from one with a value from the other
 *  prints two populations as one figure — the defect LQ-20261107-1390 removed, reintroduced by a per-field
 *  `??`. So: when cio_truth published either figure it is the source, both fields come from it, and a null
 *  value prints as a gap ("unknown beats wrong"). The projection supplies the pair only when cio_truth
 *  published neither figure, and then it supplies BOTH. */
export function unprotectedPair(p: DefenseProjection, live?: LiveAuthority | null): UnprotectedPair {
  const a = live?.unprotected ?? null
  if (a && (num(a.count) !== null || num(a.valueUsd) !== null)) {
    return { count: num(a.count), valueUsd: num(a.valueUsd), asOf: a.asOf ?? null, staleReason: null, source: 'cio_truth' }
  }
  const s = p.stops ?? {}
  return { count: num(s.no_stop?.count), valueUsd: num(s.no_stop?.value_usd), asOf: s.as_of ?? null, staleReason: s.stale_reason ?? null, source: 'projection' }
}

/** DR-D02: the stop line's sentence. When the projection publishes the reconciliation, the total is decomposed
 *  by state ("2 no stop · 1 planned only · 8 resting or pending · 12 counted") so the Defense total, Portfolio's
 *  two unprotected and Risk's two-plus-one are visibly the same book. A projection built before the field existed
 *  falls back to the merged count, labelled for what the source actually says: no RESTING order. */
export function stopsSub(s: StopsSection | null | undefined, unprotCount: number | null | undefined): string {
  const x = s ?? {}
  const r = x.reconciliation
  if (!r) return `${unprotCount ?? GAP} no resting order · ${x.pending?.count ?? GAP} pending`
  const n = (v: number | null | undefined) => v ?? GAP
  return [
    `${n(r.by_state?.no_stop?.count)} no stop`,
    `${n(r.by_state?.planned_only?.count)} planned only`,
    `${n(r.resting_or_pending?.count)} resting or pending`,
    `${n(r.counted_positions)} counted`,
  ].join(' · ')
}

export interface TierPair { tier: string | null; score: number | null; asOf: string | null; source: 'snapshot' | 'projection' }

/** The market-risk tier, score and clock from ONE record (LQ-20261107-1837 REWORK 2, F4).
 *
 *  A snapshot that answered with a tier but no score prints a gap for the score; it never borrows the
 *  projection's frozen number, and the clock shown is the answered record's own — dating the snapshot's
 *  figure with the projection's `as_of` names the wrong record. */
export function tierPair(p: DefenseProjection, live?: LiveAuthority | null): TierPair {
  const a = live?.marketRisk ?? null
  if (a && (a.tier != null || num(a.score) !== null)) {
    return { tier: a.tier ?? null, score: num(a.score), asOf: a.asOf ?? null, source: 'snapshot' }
  }
  const t = p.tier ?? {}
  return { tier: t.tier ?? null, score: num(t.score), asOf: t.as_of ?? null, source: 'projection' }
}

export type TierClockFacts = {
  /** The live observation, when the snapshot answered (a tier or a score). Null otherwise. */
  live: { tier: string | null; score: number | null; asOf: string | null } | null
  /** The projection's frozen copy — the record that built the ladder text and the recommendations. */
  projected: { tier: string | null; score: number | null; asOf: string | null; builtAt: string }
  /** The two records say different things (tier, or a score at the page's 0.05 precision). */
  disagree: boolean
  /** Whole minutes the live evidence is newer than the projection's input; null when unknown or not newer. */
  lagMinutes: number | null
}

/** Whole minutes `newer` leads `older`; null when either is not an instant or it does not lead. */
export function newerMinutes(newer: string | null | undefined, older: string | null | undefined): number | null {
  const at = (v: string) => (/T.*(?:Z|[+-]\d\d:\d\d)$/.test(v) ? Date.parse(v) : NaN)
  if (!newer || !older) return null
  const a = at(newer), b = at(older)
  if (!Number.isFinite(a) || !Number.isFinite(b)) return null
  const minutes = Math.floor((a - b) / 60_000)
  return minutes > 0 ? minutes : null
}

/** DR-D04 (sprint 8H-2 b3): the clocks behind the market-risk conclusions.
 *
 *  The page reads the live snapshot (/api/v2/market-risk/latest) AND the projection, which embeds a frozen copy
 *  of the same tier and score and republishes the snapshot as one of its source rows. Two nearly identical
 *  source cards with different clocks ("Market risk (engine) 07:00 ET", "Market Risk engine 08:00 ET") left the
 *  reader unable to say which record the headline, ladder and trigger text came from. This gathers the two
 *  records once so every surface names its own: the live observation with its evidence time, the projection
 *  with its build time and input time, whether they disagree, and how far the projection trails. */
export function tierClockFacts(p: DefenseProjection, live?: LiveAuthority | null): TierClockFacts {
  const a = live?.marketRisk ?? null
  const answered = a && (a.tier != null || num(a.score) !== null)
  const t = p.tier ?? {}
  const projected = { tier: t.tier ?? null, score: num(t.score), asOf: t.as_of ?? null, builtAt: p.generated_at }
  const observed = answered ? { tier: a!.tier ?? null, score: num(a!.score), asOf: a!.asOf ?? null } : null
  const disagree = !!observed && (
    (observed.tier != null && projected.tier != null && observed.tier !== projected.tier)
    || (observed.score != null && projected.score != null && Math.abs(observed.score - projected.score) >= 0.05))
  return { live: observed, projected, disagree, lagMinutes: newerMinutes(observed?.asOf, projected.asOf) }
}

/** DR-D01: how much of the book the exposure figure rests on, and whether the figure may be printed at all.
 *  Only `coverage_status: 'measured'` yields a number; everything else — `partial`, `unknown`, or a projection
 *  built before the field existed — yields `headline: 'Unknown'` with the coverage that IS known. A Book whose
 *  look-through failed must never read as a calm zero. */
export type ExposureCoverage = { state: 'measured' | 'unknown'; headline: string; detail: string; tone: Tone }

export function exposureCoverage(e: ExposureSection | null | undefined): ExposureCoverage {
  const x = e ?? {}
  const status = String(x.coverage_status ?? '').toLowerCase()
  const positions = num(x.positions_count), mapped = num(x.mapped_count), unmappedUsd = num(x.unmapped_usd)
  // "0 of 0 positions mapped" is not a coverage statement — an empty book gets its own sentence below (F2)
  const positionsText = positions != null && mapped != null && positions > 0 ? `${mapped} of ${positions} positions mapped` : null
  // Dollars only from the projection's own total: the `unmapped[]` list is capped server-side (`max_rows`), so
  // summing it would understate how much of the book is not counted. Its length is a "listed" floor, said so.
  const unmappedN = num(x.unmapped_count) ?? (x.unmapped?.length || null)
  const unmappedText = unmappedUsd ? `${money(unmappedUsd)} not mapped`
    : unmappedN ? `${unmappedN} position${unmappedN === 1 ? '' : 's'} not mapped` : null
  const unpricedN = num(x.unpriced_count) ?? null
  const unpricedText = unpricedN ? `${unpricedN} position${unpricedN === 1 ? '' : 's'} with no value` : null
  if (status === 'measured') {
    // `measured` cannot carry an unpriced position (the producer makes it partial), so this branch names none.
    const detail = [positionsText, unmappedText].filter(Boolean).join(' · ')
    return { state: 'measured', headline: money(x.stressed_usd),
      detail: detail || 'coverage not published', tone: (num(x.stressed_pct_invested) ?? 0) >= 10 ? 'warn' : 'muted' }
  }
  // F2 (REVIEW-S2-defense-reentry-b1-cc-deepseek-3): two different facts shared one sentence.
  //   positions_count published as 0, nothing unmapped, nothing unpriced -> the projection read a book and found
  //   no non-cash position;   the coverage fields absent altogether -> the read (or this build) predates coverage,
  //   which says nothing about how many positions exist. Never print the first as the second, or vice versa.
  const emptyBook = status !== 'partial' && positions === 0 && !unmappedN && !unpricedN
  const detail = [status === 'partial' ? 'partial coverage'
    : emptyBook ? 'no non-cash position is on file'
    : 'exposure coverage not published',
    positionsText, unmappedText, unpricedText]
    .filter(Boolean).join(' · ')
  return { state: 'unknown', headline: 'Unknown', detail, tone: 'warn' }
}

/** DR-D03: the hedge verdict's sentence. `met_count` counts only evaluated-true conditions, so an unevaluated one
 *  is neither met nor not met — it is Unknown, and the sentence says how many. Silent when nothing was measured. */
export function hedgeSub(h: HedgeSection | null | undefined): string {
  const x = h ?? {}
  const triggers = x.triggers ?? []
  if (x.met_count == null || x.of == null) return x.stale_reason ?? GAP
  const unknown = triggers.filter(t => t.met == null).length
  return `${x.met_count} of ${x.of} met${unknown ? ` · ${unknown} unknown` : ''}`
}

/** "The defense, line by line": one row per sheet, every value from one projection field. `live`, when given,
 *  carries the two figures LQ-20261107-1837 mapped to an authority OUTSIDE the projection: the market-risk
 *  score (MarketRiskSnapshot@v1) and the unprotected-position count (cio_truth). The projection's copies are
 *  frozen at build time, so the live one wins where it is present — as a whole record, never field by field. */
export function defenseLines(p: DefenseProjection, now: Date = new Date(), live?: LiveAuthority): Line[] {
  const e = p.exposure ?? {}, s = p.stops ?? {}, h = p.hedge_readiness ?? {}, sec = p.sector_posture ?? {}
  const c = p.cash_alternatives ?? {}, b = p.base_rates ?? {}, w = p.watch_next ?? {}
  const unprot = unprotectedPair(p, live)
  const topNames = [...new Set((e.rows ?? []).map(r => r.symbol))].slice(0, 2).join(' · ')
  const brSpy = (b.rows ?? [])[0]
  const cov = exposureCoverage(e)
  return [
    // DR-D01: the figure prints only when the projection says the look-through measured the whole book; a partial
    // or unpublished coverage prints Unknown with what it does cover (see `exposureCoverage`).
    { id: 'book', sheet: 'exposure', label: 'Book in stressed groups',
      sub: topNames || (cov.state === 'unknown' ? (e.stale_reason ?? 'the projection publishes no exposure coverage') : (e.stale_reason ?? GAP)),
      value: cov.headline, valueSub: cov.state === 'measured' ? [e.stressed_pct_invested != null ? `${pct(e.stressed_pct_invested)} of invested` : null, cov.detail !== 'coverage not published' ? cov.detail : null].filter(Boolean).join(' · ') : cov.detail,
      tone: cov.tone, asOf: e.as_of, staleReason: e.stale_reason },
    { id: 'stops', sheet: 'stops', label: 'Stop coverage',
      sub: stopsSub(s, unprot.count),
      // REWORK 3 (N1): an unknown count is not zero. `?? 0` painted a real cio_truth dollar figure green when the
      // record published the value but not the count — the pair rule makes that a legitimate answer, so the tone
      // must say "no reading", never "nothing unprotected". Unknown beats wrong.
      value: money(unprot.valueUsd), valueSub: 'unprotected', tone: unprot.count == null ? 'muted' : unprot.count > 0 ? 'warn' : 'good',
      asOf: unprot.asOf, staleReason: unprot.staleReason },
    // DR-D03: the verdict names how many of its conditions were never evaluated. "1 of 2 met" alone reads as
    // "the other one is false"; when a trigger's `met` is null it is Unknown, and the sentence must say so.
    { id: 'hedge', sheet: 'hedge', label: 'Hedge readiness',
      sub: hedgeSub(h),
      value: h.readiness ?? 'UNKNOWN', valueSub: h.shock_class ? `${h.shock_class.toLowerCase()} shock` : undefined,
      tone: readinessTone(h.readiness), asOf: h.as_of, staleReason: h.stale_reason },
    { id: 'sector', sheet: 'sector', label: 'Sector posture',
      sub: (sec.stressed ?? []).length ? `${(sec.stressed ?? []).join(', ')} STRESS` : (sec.stale_reason ?? 'no group in stress'),
      value: `${(sec.stressed ?? []).length} stressed`,
      valueSub: sec.sectors_measured != null && sec.sectors_hit != null ? `${sec.sectors_measured - sec.sectors_hit} of ${sec.sectors_measured} holding` : undefined,
      tone: (sec.stressed ?? []).length ? 'warn' : 'good', asOf: sec.as_of, staleReason: sec.stale_reason },
    { id: 'cash', sheet: 'cash', label: 'Cash alternatives', sub: c.yields_on_file ? 'yields on file' : `yields ${GAP}${c.as_of ? ` · last run ${clockET(c.as_of, now)}` : ''}`,
      value: pct(c.cash_pct_book ?? e.cash_pct_book), valueSub: money(c.cash_usd ?? e.cash_usd) === GAP ? undefined : money(c.cash_usd ?? e.cash_usd),
      tone: c.yields_on_file ? 'muted' : 'warn', asOf: c.as_of, staleReason: c.stale_reason },
    { id: 'base', sheet: 'base', label: 'What usually happens next', sub: b.n ? `${b.n} similar days · history, not a forecast` : (b.stale_reason ?? GAP),
      value: b.further_drop_pct != null ? pct(b.further_drop_pct) : brSpy ? pct(brSpy.median_pct, 1) : GAP,
      valueSub: b.further_drop_pct != null ? 'saw a further drop' : brSpy ? brSpy.label : undefined,
      tone: 'muted', asOf: b.as_of, staleReason: b.stale_reason },
    { id: 'watch', sheet: 'watch', label: 'Watch next session', sub: (w.items ?? []).slice(0, 3).map(i => i.text).join(' · ') || (w.stale_reason ?? GAP),
      value: `${(w.items ?? []).length}`, valueSub: 'items', tone: 'muted', asOf: w.as_of, staleReason: w.stale_reason },
    { id: 'sources', sheet: 'sources', label: 'Sources', sub: (p.sources ?? []).filter(x => x.state !== 'fresh').map(x => `${x.label} ${x.state.replace('_', ' ')}`).join(' · ') || 'all fresh',
      value: sourceSummaryText(p.source_summary, p.sources), tone: (p.sources ?? []).some(x => x.state !== 'fresh') ? 'warn' : 'good', asOf: p.generated_at },
  ]
}

/** Short definitions for dotted terms (tap on a phone, hover on desktop). */
export const GLOSSARY: Record<string, string> = {
  'look-through': "Counts what a fund holds, not just its label: a fund that is 48% tech adds 48% of its value to Technology.",
  'put/call': 'Open put contracts divided by open call contracts. Well above its usual level means traders are paying for protection.',
  'exit review': "The engine's stance for a holding in a stressed group that is near or past its stop: look at it now. Not an instruction to sell.",
  'considered when': 'The conditions under which a hedge would be worth a look. Nothing is recommended, and no size is shown.',
  'stressed groups': 'Sectors or baskets the Market Risk engine rates STRESS or WEAKENING right now.',
  'daily reset': 'Inverse ETFs target the opposite of one day’s move. Held for weeks, the result can drift from the opposite of the index.',
  'protective put': 'An option that caps the loss on one holding below a price, for a premium paid up front.',
  'tier': 'The Market Risk engine’s alert level, from GREEN (calm) to RED (stress confirmed across several categories).',
}
