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
  residuals?: { count?: number | null; usd_exposed?: number | null; symbols?: string[] }
  unmapped?: { symbol: string; account_label?: string | null; usd?: number | null; reason?: string | null }[]
  budgets?: Budget[]
  rotate?: { key?: string; label?: string | null; state?: string | null; rs5?: number | null; usd?: number | null }[]
}
export type StopsSection = Section & {
  no_stop?: { count?: number | null; value_usd?: number | null }
  pending?: { count?: number | null; value_usd?: number | null }
  planned_only?: number | null; active?: number | null; filled?: { count?: number | null }
  near_threshold_pct?: number | null
  gaps?: { symbol: string; account_label?: string | null; value_usd?: number | null; state?: string | null }[]
  near?: { symbol: string; account_label?: string | null; distance_pct?: number | null }[]
  hedged_share?: string | null; beta?: string | null
}
export type HedgeTrigger = { id: string; label: string; value?: number | null; threshold?: number | null; unit?: string | null; met?: boolean | null; detail?: string | null }
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

/** "The defense, line by line": one row per sheet, every value from one projection field. */
export function defenseLines(p: DefenseProjection, now: Date = new Date()): Line[] {
  const e = p.exposure ?? {}, s = p.stops ?? {}, h = p.hedge_readiness ?? {}, sec = p.sector_posture ?? {}
  const c = p.cash_alternatives ?? {}, b = p.base_rates ?? {}, w = p.watch_next ?? {}
  const topNames = [...new Set((e.rows ?? []).map(r => r.symbol))].slice(0, 2).join(' · ')
  const brSpy = (b.rows ?? [])[0]
  return [
    { id: 'book', sheet: 'exposure', label: 'Book in stressed groups', sub: topNames || (e.stale_reason ?? GAP),
      value: money(e.stressed_usd), valueSub: e.stressed_pct_invested != null ? `${pct(e.stressed_pct_invested)} of invested` : undefined,
      tone: (num(e.stressed_pct_invested) ?? 0) >= 10 ? 'warn' : 'muted', asOf: e.as_of, staleReason: e.stale_reason },
    { id: 'stops', sheet: 'stops', label: 'Stop coverage',
      sub: `${s.no_stop?.count ?? GAP} without a broker stop · ${s.pending?.count ?? GAP} pending`,
      value: money(s.no_stop?.value_usd), valueSub: 'unprotected', tone: (s.no_stop?.count ?? 0) > 0 ? 'warn' : 'good', asOf: s.as_of, staleReason: s.stale_reason },
    { id: 'hedge', sheet: 'hedge', label: 'Hedge readiness',
      sub: h.met_count != null && h.of != null ? `${h.met_count} of ${h.of} triggers met` : (h.stale_reason ?? GAP),
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
