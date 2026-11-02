/** Market-risk projection model for Home and the Risk page (design home/v002, risk/v002; DSN-20261031-market-risk-ui).
 *  Pure: shapes GET /api/v2/market-risk/latest into what the UI renders. No scoring here — a tier the engine did not
 *  compute is shown as NOT EVALUATED, never inferred from one source. */
import type { Tone } from './designTokens'

export type Tier = 'GREEN' | 'NONE' | 'BLUE' | 'YELLOW' | 'ORANGE' | 'RED' | 'NOT_EVALUATED'
export type MarketRiskState = 'not_evaluated' | 'evaluated' | 'stale'

export interface Contributor { name: string; points: number; detail?: string | null; as_of?: string | null }
export interface Category { name: string; state: 'CALM' | 'WARN' | 'STRESS' | 'UNKNOWN'; detail?: string | null; weight?: number | null; as_of?: string | null }
export interface Episode { id: string; tier: Tier; opened_at: string; repeats?: number; max_repeats?: number; acknowledged_at?: string | null; acknowledged_by?: string | null; status?: 'OPEN' | 'ACKED' | 'RESOLVED' }
/** `actual`/`limit` may be absent: the live projection carries budget names only (review of PR 2383, M3). */
export interface BudgetRow { budget: string; actual: number; limit: number; unit?: string; breached?: boolean; scope?: string | null }
export interface Book { vulnerability?: number | null; budgets?: BudgetRow[]; positions?: { symbol: string; stop_distance_pct?: number | null; note?: string | null }[]; note?: string | null }
export interface ProbRow { horizon: string; move_1_5?: number | null; move_3?: number | null; up?: number | null; down?: number | null; vix_up_20?: number | null; trend_continues?: number | null }
export interface HistoryPoint { as_of: string; score: number; tier: Tier; sent?: string | null }
export interface OptionsFlowSource { as_of?: string | null; age_hours?: number | null; findings: { symbol: string; state: string; pc_vol_ratio?: number | null; pc_vol_factor?: number | null; pc_oi_ratio?: number | null; pc_oi_factor?: number | null }[]; priority?: string | null; session?: string | null }

export interface MarketRisk {
  schema?: string
  state: MarketRiskState
  tier: Tier
  score: number | null
  as_of: string | null
  age_hours: number | null
  stale: boolean
  reason?: string | null
  contributors: Contributor[]
  categories: Category[]
  confirming?: { n: number; of: number } | null
  deescalates_if?: string | null
  uplift?: { market_score?: number | null; vulnerability?: number | null; note?: string | null } | null
  episode?: Episode | null
  book?: Book | null
  probabilities?: ProbRow[] | null
  history?: HistoryPoint[]
  sources?: { options_flow?: OptionsFlowSource } | null
  /** 'shadow': evaluated by `market_risk_evaluate.py --shadow` — no alert was sent for this tier. 'live': --apply. */
  mode?: 'live' | 'shadow' | null
  /** The tier rests only on data carried across a market closure: shown, never alerted on (PR 2431). */
  carried_only?: boolean
  /* ── design home/v005 (engine pass-through + the API-side dollar join) ── */
  shock_type?: ShockType | null
  sectors?: { stressed?: string[]; sectors_measured?: number; benchmark?: { symbol?: string } } | null
  heatmap?: HeatRow[]
  reentry_watch?: Record<string, ReentryCard>
  book_exposure?: BookExposure | null
  book_exposure_error?: string | null
  review?: ReviewItem[]
  budgets_detail?: BudgetDetail[]
  reentry_detail?: Record<string, ReentryDetail>
  reentry_card?: { recent_sessions?: number; max_rows?: number } | null
  card_config?: CardConfig | null
  alerts?: { sends: number; priorities: string[] } | null
  /* ── design home/v006 (API-side join: scripts/lib/market_risk_home_actions.py) ── */
  protect?: ProtectBlock | null
  hedge?: HedgeBlock | null
  rotate?: RotateBlock | null
  sectors_folded?: FoldedGroup[]
  glossary?: Record<string, GlossaryTerm> | null
  segments_status?: Record<string, SegmentStatus> | null
}

export interface GlossaryTerm { label: string; text: string }
export interface ProtectItem extends ReviewItem { pct_account?: number | null; consideration?: string | null; clauses?: { key: string; text: string }[] }
export interface ProtectBlock { items: ProtectItem[]; more: { symbol: string; account_label?: string | null; short?: string | null; to?: string | null }[] }
export interface HedgeBlock {
  verdict: 'NOT_NOW' | 'WATCH' | 'CONSIDER' | 'UNKNOWN'; thesis_state?: string; candidates?: string[]; since?: string | null; as_of?: string | null; reason?: string | null
  thresholds?: { trigger_book_pct?: number | null; index_trigger_lagging_sectors?: number | null; materiality_exposure_pct?: number | null; bounce_day_pct?: number | null }
  largest_weakening?: { label?: string | null; pct_invested?: number | null } | null; lagging_count?: number | null
  stressed_usd?: number | null; stressed_pct_book?: number | null; stressed_pct_invested?: number | null
  entry?: { inverse?: string | null; bench?: string | null; state?: string | null; label?: string | null } | null
}
export interface RotateGroup { key: string; label: string; rs1: number | null; rs5: number | null; state?: string | null; leadership_class?: string | null; desk_state?: string | null; usd?: number | null }
export interface RotateBlock { groups: RotateGroup[]; as_of?: string | null; none_reason?: string | null }
export interface FoldedGroup { key: string; label: string; state: string; usd: number }
export interface SegmentStatus { status: 'approved' | 'pending'; groups?: Record<string, number> | null; basis?: string | null; as_of?: string | null; source?: string | null }

/** Display limits from config (home_review / reentry_watch.card), passed by the API — never literals in the UI. */
export interface CardConfig { fold_below_usd?: number; max_review_items?: number; max_reentry_rows?: number; recent_sessions?: number; lookthrough_top_groups?: number; budget_drivers_shown?: number }

export interface ShockType { class?: string; label?: string; headline?: string }
export interface HeatRow { key: string; label: string; kind: string; state: string; tier?: string; r1?: number | null; r5?: number | null; rs1?: number | null; rs5?: number | null; reason_unknown?: string | null; as_of?: string | null }
export interface ExposureRow { symbol: string; account_label: string; value_usd: number; pct_account: number | null; stressed_share: number; usd_exposed: number; stop_distance_pct: number | null; stance: string | null; material: boolean }
export interface BookExposure {
  total_usd: number; home_total_usd?: number | null; reconciles: boolean; cash_usd: number; invested_usd: number
  stressed_groups: string[]; stressed_usd: number; stressed_pct_book: number | null; stressed_pct_invested: number | null; cash_pct_book: number | null
  largest_contributor?: { symbol: string; account_label: string; group: string | null; share: number | null } | null
  groups: Record<string, { usd: number; pct_book: number | null }>
  unmapped: { symbol: string; account_label: string; usd: number; reason: string }[]
  rows: ExposureRow[]; more: { count: number; usd: number }; zero_exposure_symbols: string[]
  as_of?: string | null; stops_known?: boolean
}
export interface ReviewItem { symbol: string; account_label: string; kinds: string[]; text: string; usd: number; to: string }
export interface BudgetDetail { account_label: string; budget: string; limit: number | null; actual: number | null; unit: string; actual_usd: number | null; drivers: { name: string; usd: number | null }[] }
export interface StageCond { key: string; met: boolean; text: string }
export interface ReentryStages {
  verdict?: string; exit_price?: number | null; last_close?: number | null; last_date?: string | null; swing_low?: number | null; invalidation_level?: number | null
  sma10?: number | null; sma20?: number | null; anchored_vwap?: number | null; pct_vs_exit?: number | null; pct_vs_sma20?: number | null; trend?: 'up' | 'down' | 'flat' | null
  stage1?: { met: number; of: number; conditions: StageCond[] }; stage2?: { met: boolean; conditions: StageCond[] }; error?: string
}
export interface WashSale { state: 'occurred' | 'window_open'; loss_sale_date?: string; until?: string; rebuy_date?: string; rebuy_price?: number | null; account_label?: string; deferred_loss_usd?: number | null }
export interface ReentryCard { symbol: string; exit_date: string; exit_price?: number | null; status?: string; conditions?: StageCond[]; stages?: ReentryStages | null; wash_sale?: WashSale | null; look_through?: { groups?: Record<string, number>; basis?: string | null } | null }
export interface ReentryDetail { exit_account_label?: string | null; held_elsewhere_labels?: string[]; wash_sale?: WashSale | null }

export const ACTIONABLE: readonly Tier[] = ['ORANGE', 'RED'] as const

/** Unwrap the API envelope ({ok, data}) or a bare projection; null when nothing usable arrived. */
export function unwrapMarketRisk(resp: unknown): MarketRisk | null {
  const raw: any = resp && typeof resp === 'object' && 'data' in (resp as any) ? (resp as any).data : resp
  if (!raw || typeof raw !== 'object' || typeof raw.state !== 'string') return null
  return {
    schema: raw.schema, state: raw.state, tier: (raw.tier || 'NOT_EVALUATED') as Tier,
    score: typeof raw.score === 'number' ? raw.score : null, as_of: raw.as_of ?? null,
    age_hours: typeof raw.age_hours === 'number' ? raw.age_hours : null, stale: !!raw.stale, reason: raw.reason ?? null,
    contributors: Array.isArray(raw.contributors) ? raw.contributors : [], categories: Array.isArray(raw.categories) ? raw.categories : [],
    confirming: raw.confirming ?? null, deescalates_if: raw.deescalates_if ?? null, uplift: raw.uplift ?? null,
    episode: raw.episode ?? null, book: raw.book ?? null, probabilities: raw.probabilities ?? null,
    history: Array.isArray(raw.history) ? raw.history : [], sources: raw.sources ?? null,
    mode: raw.mode === 'shadow' ? 'shadow' : raw.mode === 'live' ? 'live' : null,
    carried_only: raw.carried_only === true,
    shock_type: raw.shock_type ?? null, sectors: raw.sectors ?? null,
    heatmap: Array.isArray(raw.heatmap) ? raw.heatmap : [],
    reentry_watch: raw.reentry_watch && typeof raw.reentry_watch === 'object' ? raw.reentry_watch : {},
    book_exposure: raw.book_exposure ?? null, book_exposure_error: raw.book_exposure_error ?? null,
    review: Array.isArray(raw.review) ? raw.review : [],
    budgets_detail: Array.isArray(raw.budgets_detail) ? raw.budgets_detail : [],
    reentry_detail: raw.reentry_detail && typeof raw.reentry_detail === 'object' ? raw.reentry_detail : {},
    reentry_card: raw.reentry_card ?? null,
    card_config: raw.card_config ?? null,
    alerts: raw.alerts && typeof raw.alerts.sends === 'number' ? { sends: raw.alerts.sends, priorities: Array.isArray(raw.alerts.priorities) ? raw.alerts.priorities : [] } : null,
    protect: raw.protect && Array.isArray(raw.protect.items) ? { items: raw.protect.items, more: Array.isArray(raw.protect.more) ? raw.protect.more : [] } : null,
    hedge: raw.hedge && typeof raw.hedge.verdict === 'string' ? raw.hedge : null,
    rotate: raw.rotate && Array.isArray(raw.rotate.groups) ? raw.rotate : null,
    sectors_folded: Array.isArray(raw.sectors_folded) ? raw.sectors_folded : [],
    glossary: raw.glossary && typeof raw.glossary === 'object' ? raw.glossary : null,
    segments_status: raw.segments_status && typeof raw.segments_status === 'object' ? raw.segments_status : null,
  }
}

export function tierTone(tier: Tier | string | null | undefined): Tone {
  switch (String(tier || '').toUpperCase()) {
    case 'GREEN': return 'success'
    case 'BLUE': return 'info'
    case 'YELLOW': return 'warning'
    case 'ORANGE': return 'elevated'
    case 'RED': return 'danger'
    default: return 'neutral'
  }
}

/** Design home/v002 section 2: the banner shows only for an evaluated, non-stale ORANGE or RED. */
export function bannerVisible(mr: MarketRisk | null): boolean {
  return !!mr && mr.state === 'evaluated' && !mr.stale && ACTIONABLE.includes(mr.tier)
}

export function tierWord(mr: MarketRisk | null): string {
  if (!mr) return 'unavailable'
  if (mr.state === 'not_evaluated') return 'NOT EVALUATED'
  return mr.tier
}

/** The marker every surface shows beside a shadow tier: the engine evaluated it, nobody was alerted. '' when live. */
export const SHADOW_MARKER = 'SHADOW · not alerting'
export const CARRIED_MARKER = 'CARRIED · not alerting'
/** The "not alerting" label: SHADOW (evaluated by --shadow) or CARRIED (the tier rests only on data carried across a
 *  market closure, so no alert was sent). '' for an alerting live tier. */
export function shadowMarker(mr: MarketRisk | null): string {
  if (!mr || mr.state === 'not_evaluated') return ''
  if (mr.mode === 'shadow') return SHADOW_MARKER
  if (!mr.carried_only) return ''
  // under --apply a carried tier sends one informational card and never pages (review of PR 2447); 0 sends: none
  const a = mr.alerts
  return a && a.sends > 0 ? `CARRIED · informational card sent (${a.priorities.join('/') || 'informational'}), no page` : CARRIED_MARKER
}
/** The marker after its first word ("not alerting", "informational card sent (P3), no page"). */
export function markerRest(mr: MarketRisk | null): string {
  const m = shadowMarker(mr)
  return m.includes(' · ') ? m.slice(m.indexOf(' · ') + 3) : ''
}

/** The header fact: value line and one-line why (top contributor), with the tier's tone. */
export function factLine(mr: MarketRisk | null): { value: string; sub: string; tone: Tone } {
  if (!mr) return { value: '—', sub: 'market risk unavailable', tone: 'neutral' }
  if (mr.state === 'not_evaluated') {
    const flow = mr.sources?.options_flow
    const f = flow?.findings?.find(x => x.state === 'STRESS') || flow?.findings?.find(x => x.state === 'WARN')
    return { value: 'NOT EVALUATED', sub: f ? `options flow ${f.state.toLowerCase()}: ${f.symbol} put/call vol ${fmtNum(f.pc_vol_ratio)}` : 'engine not live yet', tone: f?.state === 'STRESS' ? 'warning' : 'neutral' }
  }
  const top = mr.contributors[0]
  const score = mr.score != null ? ` ${Math.round(mr.score)}` : ''
  const sub = mr.state === 'stale' ? `stale — last evaluation ${shortTime(mr.as_of)}` : top ? `${top.name.toLowerCase()}${top.detail ? ` · ${top.detail}` : ''}` : (mr.confirming ? `${mr.confirming.n} of ${mr.confirming.of} categories` : '')
  const sh = shadowMarker(mr)
  return { value: `${mr.tier}${score}`, sub: sh ? `${sh}${sub ? ` · ${sub}` : ''}` : sub, tone: mr.state === 'stale' ? 'neutral' : tierTone(mr.tier) }
}

export function contributorsLine(mr: MarketRisk | null): string {
  if (!mr?.contributors?.length) return ''
  return mr.contributors.slice(0, 5).map(c => `${c.name} ${c.points >= 0 ? '+' : ''}${Math.round(c.points)}`).join(' · ')
}

export function pointsSum(mr: MarketRisk | null): number | null {
  if (!mr?.contributors?.length) return null
  return mr.contributors.reduce((a, c) => a + (Number(c.points) || 0), 0)
}

export function episodeLine(mr: MarketRisk | null): string {
  const e = mr?.episode
  if (!e) return ''
  const rep = e.repeats != null ? ` · repeat ${e.repeats}${e.max_repeats ? ` of ${e.max_repeats}` : ''}` : ''
  const ack = e.acknowledged_at ? `acknowledged ${shortTime(e.acknowledged_at)}` : 'not acknowledged'
  return `since ${shortTime(e.opened_at)}${rep} · ${ack}`
}

export function fmtNum(v: number | null | undefined, digits = 2): string {
  return v == null || Number.isNaN(Number(v)) ? '—' : Number(v).toFixed(digits)
}

export function fmtPct(v: number | null | undefined): string {
  return v == null || Number.isNaN(Number(v)) ? '—' : `${Math.round(Number(v) * (Math.abs(Number(v)) <= 1 ? 100 : 1))}%`
}

/** Readable ET time, never a raw ISO stamp (design rule 5). */
export function shortTime(iso: string | null | undefined): string {
  if (!iso) return 'time unavailable'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return 'time unavailable'
  return d.toLocaleString('en-US', { timeZone: 'America/New_York', weekday: 'short', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).replace(',', '') + ' ET'
}

/* ── Design home/v004: the YELLOW summary card (calm, collapsible, no Acknowledge) ─────────────────────────────── */

/** Phone width per design/README.md rule 5 (≤820 px): the card starts collapsed there and open on wider screens. */
export const SUMMARY_PHONE_MAX_PX = 820
/** Browser-storage key for the viewer's open/closed choice (a convenience only; the default applies without it). */
export const SUMMARY_OPEN_KEY = 'cc.home.marketRiskSummary.open'

/** v004: the summary card shows only for a YELLOW the engine evaluated (live or shadow), fresh or stale. ORANGE/RED keep
 *  the v002 banner; GREEN, BLUE, not evaluated and a load error show nothing in the slot. */
export function summaryVisible(mr: MarketRisk | null): boolean {
  return !!mr && mr.tier === 'YELLOW' && (mr.state === 'evaluated' || mr.state === 'stale')
}

/** Open by default on desktop, collapsed on phone; a stale card starts collapsed on every width and ignores the stored
 *  choice (its numbers are hidden anyway). `stored` is the viewer's remembered choice, or null. */
export function summaryDefaultOpen(opts: { phone: boolean; stale: boolean; stored: boolean | null }): boolean {
  if (opts.stale) return false
  if (opts.stored != null) return opts.stored
  return !opts.phone
}

/** One decimal, signed: "+34.4". */
export function fmtPoints(p: number | null | undefined): string {
  const n = Number(p)
  if (p == null || Number.isNaN(n)) return '—'
  return `${n >= 0 ? '+' : ''}${n.toFixed(1)}`
}

/** "single_sector_pct" → "single sector". Labels from the engine stay as they are. */
export function budgetLabel(name: string | null | undefined): string {
  return String(name || 'budget').replace(/_pct$/, '').replace(/_/g, ' ').trim()
}

export interface SummaryBook {
  vulnerability: string | null
  breaches: string[]
  nearStop: string[]
  otherDrivers: string
  note: string
}

export interface SummaryModel {
  stale: boolean
  score: string | null
  /** The collapsed one-liner (contributors with points, N of 9, evaluated time), or the stale line. */
  line: string
  evaluated: string
  confirm: string
  contributors: { name: string; detail: string; points: string }[]
  uplift: string | null
  notMeasured: string
  book: SummaryBook | null
  deescalates: string | null
  footer: string
  links: { label: string; to: string; testid: string }[]
}

export const SUMMARY_LINKS = [
  { label: 'Open Risk →', to: '/risk?tab=market-risk', testid: 'home-market-risk-summary-open-risk' },
  { label: 'Review stops →', to: '/risk?tab=exposure', testid: 'home-market-risk-summary-review-stops' },
] as const

function listFirst(items: string[], n = 3): string {
  if (!items.length) return ''
  return items.slice(0, n).join(', ') + (items.length > n ? ` +${items.length - n} more` : '')
}

function summaryBook(mr: MarketRisk): SummaryBook | null {
  const b = mr.book
  if (!b) return null
  const budgets = (b.budgets ?? []).filter(x => x && x.breached !== false)
  const positions = (b.positions ?? []).filter(p => p && p.symbol)
  if (b.vulnerability == null && !budgets.length && !positions.length) return null
  const breaches = budgets.map(x => {
    const unit = x.unit ?? '%'
    const vs = typeof x.actual === 'number' && typeof x.limit === 'number' ? ` ${x.actual}${unit} vs ${x.limit}${unit}` : ''
    const scope = x.scope === 'account' ? ' (one account)' : ''
    return `${budgetLabel(x.budget)}${vs}${scope}`
  })
  const near = positions.filter(p => typeof p.stop_distance_pct === 'number')
    .map(p => `${p.symbol} stop ${Number(p.stop_distance_pct).toFixed(1)}% below`)
  const others = positions.filter(p => typeof p.stop_distance_pct !== 'number').map(p => p.symbol)
  return {
    vulnerability: b.vulnerability != null ? `${Math.round(Number(b.vulnerability))}/100` : null,
    breaches,
    nearStop: near,
    otherDrivers: listFirst(others),
    note: 'Advisory only. No order, size or stop level is implied.',
  }
}

/** Everything the v004 card renders, from the API projection. Pure; null when the card is not shown. Never carries an
 *  acknowledge action: YELLOW never pages and has no episode. */
export function summaryModel(mr: MarketRisk | null): SummaryModel | null {
  if (!summaryVisible(mr) || !mr) return null
  const shadow = mr.mode === 'shadow'
  const footer = `YELLOW never pages and has nothing to acknowledge.${shadow ? ' Shadow mode: no alert was sent for this tier.' : ''}`
  const links = SUMMARY_LINKS.map(l => ({ ...l }))
  const evaluated = `evaluated ${shortTime(mr.as_of)}`
  if (mr.state === 'stale' || mr.stale) {
    return {
      stale: true, score: null, evaluated, confirm: '',
      line: `stale — last evaluation ${shortTime(mr.as_of)}. Numbers hidden until the engine runs again.`,
      contributors: [], uplift: null, notMeasured: '', book: null, deescalates: null,
      footer: 'The engine has not run since this evaluation, so the score, contributors and your book are hidden until it runs again.',
      links,
    }
  }
  const contributors = mr.contributors.filter(c => Number(c.points) > 0).slice(0, 5).map(c => ({
    name: c.name,
    detail: [c.detail, c.as_of ? shortTime(c.as_of) : null].filter(Boolean).join(' · '),
    points: fmtPoints(c.points),
  }))
  const confirm = mr.confirming ? `${mr.confirming.n} of ${mr.confirming.of} categories confirm` : ''
  const lead = contributors.length ? contributors.map(c => `${c.name} ${c.points}`).join(' · ') : 'no category above 0 points'
  const line = [lead, mr.confirming ? `${mr.confirming.n} of ${mr.confirming.of} confirm` : '', evaluated].filter(Boolean).join(' · ')
  const scored = new Set(contributors.map(c => c.name.toLowerCase()))
  const unknown = mr.categories.filter(c => c.state === 'UNKNOWN').map(c => c.name.toLowerCase())
  const zero = mr.categories.filter(c => c.state !== 'UNKNOWN' && !scored.has(c.name.toLowerCase())).map(c => c.name.toLowerCase())
  const parts: string[] = []
  if (unknown.length) parts.push(`Not measured: ${unknown.join(', ')}.`)
  if (zero.length) parts.push(`${zero.length > 1 ? `${zero.slice(0, -1).join(', ')} and ${zero[zero.length - 1]}` : zero[0]} add 0.`.replace(/^./, s => s.toUpperCase()))
  const uplift = mr.uplift ? (mr.uplift.note ?? `Market ${mr.uplift.market_score ?? '—'} → ${mr.tier} after portfolio vulnerability ${mr.uplift.vulnerability ?? '—'}`) : null
  return {
    stale: false,
    score: mr.score != null ? String(Math.round(mr.score)) : null,
    line, evaluated, confirm, contributors, uplift,
    notMeasured: parts.join(' '),
    book: summaryBook(mr),
    deescalates: mr.deescalates_if ?? null,
    footer, links,
  }
}


/* ── Design home/v005: the actionable card (verdict with dollars, sectors, positions, review, budgets, re-entry) ──── */

/** "$12,346" — whole dollars; "—" when unknown. */
export function fmtUsd(v: number | null | undefined): string {
  if (v == null || Number.isNaN(Number(v))) return '—'
  return `$${Math.round(Number(v)).toLocaleString('en-US')}`
}
/** A price: "$12.34". */
export function fmtPrice(v: number | null | undefined): string {
  if (v == null || Number.isNaN(Number(v))) return '—'
  return `$${Number(v).toFixed(2)}`
}
/** Signed percent with one decimal: "−3.1%" / "+1.6%". */
export function fmtSignedPct(v: number | null | undefined): string {
  if (v == null || Number.isNaN(Number(v))) return '—'
  const n = Number(v)
  return `${n > 0 ? '+' : n < 0 ? '−' : ''}${Math.abs(n).toFixed(1)}%`
}
/** "Fri 10-30" from an ISO date (ET calendar date, no time). */
export function shortDay(d: string | null | undefined): string {
  if (!d) return '—'
  const t = new Date(`${String(d).slice(0, 10)}T12:00:00Z`)
  if (Number.isNaN(t.getTime())) return String(d)
  return t.toLocaleDateString('en-US', { timeZone: 'UTC', weekday: 'short', month: '2-digit', day: '2-digit' }).replace(',', '').replace('/', '-')
}

const SHOCK_WORDS: Record<string, string> = {
  SECTOR: 'Sector selloff', SYSTEMIC: 'Market-wide selloff', FACTOR: 'Factor rotation', RATES: 'Rates shock',
  CREDIT: 'Credit stress', EVENT: 'Event shock',
}
const STRESSED = new Set(['STRESS', 'WEAK'])

export type GroupChip = 'STRESS' | 'WEAK' | 'RESILIENT' | 'HOLDING' | 'NOT MEAS.'
export interface SectorRowModel { key: string; label: string; theme: boolean; chip: GroupChip; tone: Tone; rs1: string; rs5: string; rs1n: number | null; rs5n: number | null; usd: string; pctBook: string; held: boolean; unknown: boolean; reason: string | null }
export interface ReentryRowModel {
  symbol: string; head: string; now: string; vsExit: string; vsExitNeg: boolean; vsMa: string; trend: string; verdict: string; verdictTone: Tone
  stage1: string; waiting: string; invalidates: string; stage2: string; wash: { text: string; tone: 'info' | 'warning' } | null; earnings: string | null; lookThrough: string
}
export interface BudgetLine { account: string; text: string; drivers: string }
export interface ActionableModel {
  verdict: string
  exposure: string | null
  exposureNote: string | null
  topReview: ReviewItem | null
  sectors: SectorRowModel[]
  sectorsFoot: string
  positions: ExposureRow[]
  positionsMore: string
  review: ReviewItem[]
  budgets: BudgetLine[]
  /** Breaches the engine named but whose numbers the API could not read: said, never dropped (review of PR 2447). */
  budgetsNote: string | null
  /** False when the stop read failed: the stop column says "stops unavailable", never "no stop". */
  stopsKnown: boolean
  reentry: ReentryRowModel[]
  reentryMore: string
  /* design home/v006 */
  foldLine: string
  protect: { items: ProtectRowModel[]; more: string } | null
  hedge: HedgeModel | null
  rotate: RotateModel | null
  segments: SegmentRowModel[]
  glossary: Record<string, GlossaryTerm>
}
export interface ProtectRowModel { symbol: string; account: string; usd: string; pct: string; consideration: string; to: string; linkLabel: string }
export interface HedgeModel { verdict: string; tone: Tone; line: string; lane: string; short: string }
export interface RotateModel { rows: { key: string; label: string; rs1: string; rs5: string; rs1n: number | null; rs5n: number | null; desk: string; usd: string }[]; foot: string; none: string | null; short: string }
export interface SegmentRowModel { symbol: string; status: 'approved' | 'pending'; line: string; split: { label: string; pct: number }[] }

const HEDGE_WORD: Record<string, { word: string; tone: Tone }> = {
  NOT_NOW: { word: 'Not now', tone: 'success' }, WATCH: { word: 'Watch', tone: 'warning' },
  CONSIDER: { word: 'Consider', tone: 'elevated' }, UNKNOWN: { word: 'Unknown', tone: 'warning' },
}
const THESIS_WORDS: Record<string, string> = { RED: 'no bearish thesis', AMBER: 'deteriorating, not yet eligible', GREEN: 'thesis green' }

/** design home/v006 Hedge block text: the Defense desk's stoplight verdict against its own config thresholds. */
export function hedgeModel(h: HedgeBlock | null | undefined): HedgeModel | null {
  if (!h) return null
  const w = HEDGE_WORD[h.verdict] ?? HEDGE_WORD.UNKNOWN
  const t = h.thresholds ?? {}
  const lw = h.largest_weakening
  const pct = (v: number | null | undefined) => v == null ? '—' : `${(+v).toFixed(1)}%`
  const now = `now ${lw?.label ? `${lw.label} ${pct(lw.pct_invested)}` : 'no sector weakening'}, ${h.lagging_count ?? 0} sector${h.lagging_count === 1 ? '' : 's'} lagging`
  let line: string
  if (h.verdict === 'NOT_NOW') {
    line = `${fmtUsd(h.stressed_usd ?? 0)} (${pct(h.stressed_pct_book)} of book · ${pct(h.stressed_pct_invested)} of invested) is in stressed groups. The Defense desk considers a hedge when one weakening sector is ≥ ${t.trigger_book_pct ?? '—'}% of invested, or ${t.index_trigger_lagging_sectors ?? '—'}+ sectors lag — ${now}.`
  } else if (h.verdict === 'CONSIDER') {
    const e = h.entry
    line = `${lw?.label ?? 'A sector'} is ${pct(lw?.pct_invested)} of invested and weakening — above the ${t.trigger_book_pct ?? '—'}% the Defense desk uses.${e?.inverse ? ` ${e.inverse}: thesis green · entry ${String(e.label ?? e.state ?? 'not evaluated').toLowerCase()} (bounce days of +${t.bounce_day_pct ?? '—'}% on ${e.bench ?? 'the index'}).` : ''}`
  } else if (h.verdict === 'WATCH') {
    line = `A trigger is active but your mapped exposure is below the ${t.materiality_exposure_pct ?? '—'}% materiality the stoplight uses — ${now}.`
  } else {
    line = `Defense stoplight ${h.reason === 'stale' ? `last ran ${shortTime(h.as_of)}` : (h.reason ?? 'unavailable')} — no verdict until it runs again.`
  }
  const lane = h.thesis_state && THESIS_WORDS[h.thesis_state]
    ? `Inverse lane ${(h.candidates ?? []).join(' · ')}: ${THESIS_WORDS[h.thesis_state]}${h.since ? ` since ${shortDay(h.since)}` : ''}.`
    : ''
  const short = h.verdict === 'NOT_NOW' ? `${pct(h.stressed_pct_book)} of book in stressed groups` : h.verdict === 'CONSIDER' ? `${lw?.label ?? 'a sector'} above the Defense desk threshold` : h.verdict === 'WATCH' ? 'deteriorating, below materiality' : 'stoplight not current'
  return { verdict: w.word, tone: w.tone, line, lane, short }
}

export function rotateModel(r: RotateBlock | null | undefined): RotateModel | null {
  if (!r) return null
  const rows = (r.groups ?? []).map(g => ({
    key: g.key, label: g.label, rs1: fmtSignedPct(g.rs1), rs5: fmtSignedPct(g.rs5), rs1n: g.rs1 ?? null, rs5n: g.rs5 ?? null,
    desk: g.desk_state ? `desk ${g.desk_state}` : '', usd: g.usd != null ? fmtUsd(g.usd) : '—',
  }))
  return {
    rows, none: rows.length ? null : (r.none_reason ?? 'No group is beating SPY on both 1 and 5 sessions today.'),
    foot: `Relative strength vs SPY${r.as_of ? `, ${shortDay(r.as_of)} close` : ''}. Groups beating SPY on both 1 and 5 sessions — not a buy list.`,
    short: rows.length ? rows.map(x => `${x.label} ${x.rs1}/${x.rs5}`).join(' · ') : 'no group leading on both horizons',
  }
}

const VERDICT_TONE: Record<string, Tone> = { 'Still falling': 'danger', Invalidated: 'danger', Basing: 'warning', 'Early setup': 'success', Confirmed: 'success' }
const GROUP_WORD: Record<string, string> = { tech: 'technology', comm: 'communications', ai_basket: 'AI basket', semis: 'semis', real_estate: 'real estate' }

function businessDaysBetween(a: string, b: string): number {
  const d0 = new Date(`${a.slice(0, 10)}T12:00:00Z`), d1 = new Date(`${b.slice(0, 10)}T12:00:00Z`)
  if (Number.isNaN(d0.getTime()) || Number.isNaN(d1.getTime())) return 0
  let n = 0
  for (const d = new Date(d0); d < d1; d.setUTCDate(d.getUTCDate() + 1)) { const w = d.getUTCDay(); if (w !== 0 && w !== 6) n++ }
  return n
}

/** The v005 verdict line: shock type and stressed groups, how many sectors hold. Never a tier restated alone. */
export function verdictLine(mr: MarketRisk): string {
  const heat = mr.heatmap ?? []
  const stressed = heat.filter(h => STRESSED.has(h.state) && (h.kind === 'sector' || h.kind === 'theme')).map(h => h.label)
  const sectorRows = heat.filter(h => h.kind === 'sector' && h.state !== 'UNKNOWN')
  const holding = sectorRows.filter(h => !STRESSED.has(h.state)).length
  const n = mr.sectors?.sectors_measured ?? sectorRows.length
  const cls = String(mr.shock_type?.class || '').toUpperCase()
  const word = SHOCK_WORDS[cls]
  const groups = stressed.length ? stressed.join(' / ') : 'no group in stress'
  if (!word) return stressed.length ? `Stressed: ${groups}.` : 'No sector or theme in stress.'
  if (cls === 'SYSTEMIC') return `${word} — ${n - holding} of ${n} sectors down.`
  if (cls === 'SECTOR') return `${word} — ${groups}. Not market-wide: ${holding} of ${n} sectors holding.`
  return `${word} — ${groups}.`
}

export function actionableModel(mr: MarketRisk | null): ActionableModel | null {
  if (!mr || mr.state !== 'evaluated' || mr.stale) return null
  const heat = (mr.heatmap ?? []).filter(h => h.kind === 'sector' || h.kind === 'theme')
  const themeKeys = new Set(heat.filter(h => h.kind === 'theme').map(h => h.key))
  const cfg: CardConfig = mr.card_config ?? {}
  const be = mr.book_exposure ?? null
  if (!heat.length && !be) return null
  const verdict = verdictLine(mr)
  let exposure: string | null = null, exposureNote: string | null = null
  if (be && !be.reconciles) {
    exposureNote = 'Your exposure: book total does not reconcile to All accounts — dollars hidden.'
  } else if (be) {
    const lc = be.largest_contributor
    const via = lc && lc.group && lc.share != null ? ` — mostly ${lc.symbol}'s ${Math.round(lc.share * 100)}% ${GROUP_WORD[lc.group] ?? lc.group}` : ''
    exposure = be.stressed_usd > 0
      ? `Your exposure: ${fmtUsd(be.stressed_usd)} (${(be.stressed_pct_book ?? 0).toFixed(1)}% of book · ${(be.stressed_pct_invested ?? 0).toFixed(1)}% of invested) in stressed groups${via}.${be.cash_pct_book != null ? ` Cash ${Math.round(be.cash_pct_book)}%.` : ''}`
      : 'Your exposure: $0 in stressed groups.'
  } else if (mr.book_exposure_error) {
    exposureNote = 'Your exposure: holdings unavailable right now — dollars hidden.'
  }
  const groups = be?.groups ?? {}
  const rows: SectorRowModel[] = heat.map(h => {
    const unknown = h.state === 'UNKNOWN'
    // design home/v006: RESILIENT (beating SPY) and HOLDING (in line) are different chips; v005 showed HOLDING for both
    const chip: GroupChip = unknown ? 'NOT MEAS.' : h.state === 'STRESS' ? 'STRESS' : h.state === 'WEAK' ? 'WEAK' : h.state === 'RESILIENT' ? 'RESILIENT' : 'HOLDING'
    const tone: Tone = chip === 'STRESS' ? 'danger' : chip === 'WEAK' ? 'elevated' : chip === 'RESILIENT' ? 'success' : chip === 'HOLDING' ? 'neutral' : 'warning'
    const g = groups[h.key]
    return {
      key: h.key, label: h.label, theme: h.kind === 'theme', chip, tone,
      rs1: fmtSignedPct(h.rs1), rs5: fmtSignedPct(h.rs5), rs1n: h.rs1 ?? null, rs5n: h.rs5 ?? null,
      usd: g ? fmtUsd(g.usd) : be ? '$0' : '—', pctBook: g?.pct_book != null ? `${g.pct_book.toFixed(2)}%` : be ? '0.00%' : '—',
      held: !!g && g.usd > 0, unknown, reason: h.reason_unknown ?? null,
    }
  })
  const foldedKeys = new Set((mr.sectors_folded ?? []).map(f => f.key))
  const foldStressed = (mr.sectors_folded ?? []).filter(f => f.state !== 'UNKNOWN')
  const foldUnknown = (mr.sectors_folded ?? []).filter(f => f.state === 'UNKNOWN')
  const under = cfg.fold_below_usd != null ? `under ${fmtUsd(cfg.fold_below_usd)}` : 'little'
  const foldLine = [
    foldStressed.length ? `Also stressed, you hold ${under}: ${foldStressed.map(f => `${f.label} (${fmtUsd(f.usd)})`).join(', ')}.` : '',
    foldUnknown.length ? `Not measured, you hold ${under}: ${foldUnknown.map(f => `${f.label} (${fmtUsd(f.usd)})`).join(', ')}.` : '',
  ].filter(Boolean).join(' ')
  for (let i = rows.length - 1; i >= 0; i--) if (foldedKeys.has(rows[i].key)) rows.splice(i, 1)
  const rank = (r: SectorRowModel) => (r.chip === 'STRESS' || r.chip === 'WEAK') && r.held ? 0 : r.unknown && r.held ? 1 : r.held ? 2 : 3
  const usdOf = (r: SectorRowModel) => groups[r.key]?.usd ?? 0
  rows.sort((a, b) => rank(a) - rank(b) || usdOf(b) - usdOf(a))
  const unm = be?.unmapped ?? []
  const unmTotal = unm.reduce((a, u) => a + u.usd, 0)
  const foot = [
    'Funds counted by their holdings (look-through). Themes overlap sectors — never added together.',
    unm.length ? `No look-through: ${unm.map(u => `${u.symbol} ${fmtUsd(u.usd)}`).join(' · ')} (${fmtUsd(unmTotal)}).` : '',
    be ? `Cash ${fmtUsd(be.cash_usd)} (${Math.round(be.cash_pct_book ?? 0)}%).` : '',
  ].filter(Boolean).join(' ')
  const more = be?.more
  const positionsMore = [
    more && more.count ? `+${more.count} more (${fmtUsd(more.usd)} exposed)` : '',
    be?.zero_exposure_symbols?.length ? `${be.zero_exposure_symbols.join(', ')}: 0% in stressed groups` : '',
  ].filter(Boolean).join(' · ')
  // budgets: one line per account+budget, drivers by dollars
  const budgets: BudgetLine[] = (mr.budgets_detail ?? []).map(b => {
    const unit = b.unit || '%'
    const name = budgetLabel(b.budget)
    const amt = b.actual_usd != null ? ` (${fmtUsd(b.actual_usd)})` : ''
    const nDr = cfg.budget_drivers_shown ?? b.drivers.length
    const dr = b.drivers.slice(0, nDr).map(d => d.usd != null ? `${d.name} ${fmtUsd(d.usd)}` : d.name)
    return { account: b.account_label, text: `${name} ${b.actual ?? '—'}${unit}${amt} vs ${b.limit ?? '—'}${unit} limit`, drivers: dr.join(' · ') + (b.drivers.length > nDr ? ` +${b.drivers.length - nDr}` : '') }
  })
  const named = (mr.book?.budgets ?? []).filter(b => b && b.breached !== false)
  const budgetsNote = !budgets.length && named.length
    ? `${named.length} budget breach${named.length === 1 ? '' : 'es'}: ${named.map(b => budgetLabel(b.budget)).join(', ')} — budget numbers unavailable`
    : null
  // re-entry: recent exits, newest first
  // limits come from config through the API; absent, nothing is cut (review of PR 2447: no literals in the UI)
  const recent = cfg.recent_sessions ?? mr.reentry_card?.recent_sessions ?? Number.POSITIVE_INFINITY
  const maxRows = cfg.max_reentry_rows ?? mr.reentry_card?.max_rows ?? Number.POSITIVE_INFINITY
  const asOf = (mr.as_of || '').slice(0, 10)
  const cards = Object.entries(mr.reentry_watch ?? {}).filter(([k, c]) => !k.startsWith('_') && c && c.exit_date && c.stages && !c.stages.error)
  cards.sort((a, b) => String(b[1].exit_date).localeCompare(String(a[1].exit_date)))
  const isRecent = (c: ReentryCard) => !asOf || businessDaysBetween(c.exit_date, asOf) <= recent
  const shown = cards.filter(([, c]) => isRecent(c)).slice(0, maxRows)
  const older = cards.length - shown.length
  const reentry: ReentryRowModel[] = shown.map(([sym, c]) => {
    const st = c.stages as ReentryStages
    const det = (mr.reentry_detail ?? {})[sym] ?? {}
    const held = det.held_elsewhere_labels?.length ? ` · still held in ${det.held_elsewhere_labels.join(', ')}` : ''
    const unmet1 = (st.stage1?.conditions ?? []).filter(x => !x.met).map(x => x.key === 'tier_ok' ? 'market tier ORANGE or worse' : x.text)
    const unmet2 = (st.stage2?.conditions ?? []).filter(x => !x.met).map(x => x.text)
    const w = det.wash_sale ?? c.wash_sale ?? null
    let wash: ReentryRowModel['wash'] = null
    if (w?.state === 'occurred') {
      const loss = w.deferred_loss_usd != null ? `${fmtUsd(w.deferred_loss_usd)} loss` : 'the loss'
      wash = { tone: 'info', text: `${w.account_label ?? 'Taxable account'}: re-bought ${shortDay(w.rebuy_date)}${w.rebuy_price != null ? ` at ${fmtPrice(w.rebuy_price)}` : ''} — wash sale occurred, ${loss} deferred into the new basis.` }
    } else if (w?.state === 'window_open') {
      wash = { tone: 'warning', text: `Wash sale: ${w.account_label ?? 'taxable'} loss sale ${shortDay(w.loss_sale_date)} — a re-buy there through ${shortDay(w.until)} would defer it.` }
    }
    const earnCond = (c.conditions ?? []).find(x => x.key === 'earnings_clear')
    const earnings = c.status === 'PENDING_EARNINGS' || (earnCond && !earnCond.met) ? 'Earnings inside 5 sessions (or still settling)' : null
    // themes overlap sectors: name sectors only (the heat map says which keys are themes)
    const lg = Object.entries(c.look_through?.groups ?? {}).filter(([k]) => !themeKeys.has(k)).sort((a, b) => b[1] - a[1])
    const top3 = lg.slice(0, cfg.lookthrough_top_groups ?? lg.length)
    const rest = Math.max(0, 1 - top3.reduce((a, [, v]) => a + v, 0))
    const ltLine = top3.length
      ? `look-through: ${top3.map(([k, v]) => `${heat.find(h => h.key === k)?.label ?? k} ${Math.round(v * 100)}%`).join(' · ')}${rest > 0.01 ? ` · other ${Math.round(rest * 100)}%` : ''}${c.look_through?.basis ? ` (${c.look_through.basis})` : ''}`
      : 'look-through: not measured'
    const ma = st.pct_vs_sma20 != null ? `${fmtSignedPct(st.pct_vs_sma20)} vs 20-day` : st.anchored_vwap != null ? 'short history: anchored VWAP' : ''
    return {
      symbol: sym,
      head: `exit ${fmtPrice(c.exit_price ?? st.exit_price)} · ${shortDay(c.exit_date)} · ${det.exit_account_label ?? 'one account'}${held}`,
      now: fmtPrice(st.last_close), vsExit: fmtSignedPct(st.pct_vs_exit), vsExitNeg: (st.pct_vs_exit ?? 0) < 0, vsMa: ma,
      trend: st.trend === 'up' ? '↑' : st.trend === 'down' ? '↓' : st.trend === 'flat' ? '→' : '',
      verdict: st.verdict ?? 'Still falling', verdictTone: VERDICT_TONE[st.verdict ?? 'Still falling'] ?? 'neutral',
      stage1: `${st.stage1?.met ?? 0} of ${st.stage1?.of ?? st.stage1?.conditions?.length ?? 0}`,
      waiting: unmet1.length ? unmet1.join(', ') : 'all met',
      invalidates: fmtPrice(st.invalidation_level),
      stage2: st.stage2?.met ? 'met' : unmet2.length ? unmet2.join(' or ') : 'not measured',
      wash, earnings, lookThrough: ltLine,
    }
  })
  const firstOld = cards.filter(([, c]) => !isRecent(c))
  const reentryMore = older > 0
    ? `+${older} older exit${older === 1 ? '' : 's'} on watch (${shortDay(firstOld[firstOld.length - 1]?.[1].exit_date)} → ${shortDay(firstOld[0]?.[1].exit_date)})`
    : ''
  const review = (mr.review ?? []).slice(0, cfg.max_review_items ?? (mr.review ?? []).length)
  const protect = mr.protect ? {
    items: mr.protect.items.map(it => ({
      symbol: it.symbol, account: it.account_label, usd: fmtUsd(it.usd),
      pct: it.pct_account != null ? `${Math.round(it.pct_account)}% of account` : '',
      consideration: it.consideration || it.text, to: it.to,
      linkLabel: (it.kinds ?? []).some(k => k === 'stop_near' || k === 'no_stop') ? 'Review stop →' : 'Review →',
    })),
    more: mr.protect.more.length ? `+${mr.protect.more.length} more: ${mr.protect.more.map(x => `${x.symbol}${x.account_label ? ` · ${x.account_label}` : ''}${x.short ? ` (${x.short})` : ''}`).join(' · ')}` : '',
  } : null
  const segments: SegmentRowModel[] = Object.entries(mr.segments_status ?? {}).map(([sym, st]) => {
    const split = Object.entries(st.groups ?? {}).filter(([k]) => !themeKeys.has(k) && k !== 'ai_basket').sort((a, b) => b[1] - a[1])
      .map(([k, v]) => ({ label: heat.find(h => h.key === k)?.label ?? k, pct: Math.round(v * 100) }))
    const themes = Object.entries(st.groups ?? {}).filter(([k]) => themeKeys.has(k) || k === 'ai_basket')
      .map(([k, v]) => `${heat.find(h => h.key === k)?.label ?? k} theme ${Math.round(v * 100)}% (overlaps)`)
    return {
      symbol: sym, status: st.status, split,
      line: st.status === 'approved'
        ? `${[...split.map(x => `${x.label} ${x.pct}%`), ...themes].join(' · ')} — weights approved, ${st.source ?? 'source on file'}, as of ${st.as_of ?? '—'}`
        : 'segment weights pending approval — counted as its profile sector',
    }
  })
  const profileSector = (sym: string): string => {
    const g = Object.entries((mr.reentry_watch ?? {})[sym]?.look_through?.groups ?? {}).filter(([k]) => !themeKeys.has(k)).sort((a, b) => b[1] - a[1])[0]
    return g ? (heat.find(h => h.key === g[0])?.label ?? g[0]) : 'its profile sector'
  }
  for (const sg of segments) if (sg.status === 'pending') sg.line = `segment weights pending approval — counted as ${profileSector(sg.symbol)}`
  for (const r of reentry) {
    const st = (mr.segments_status ?? {})[r.symbol]
    if (st?.status === 'pending') r.lookThrough = `segment weights pending approval — counted as ${profileSector(r.symbol)}`
  }
  return {
    foldLine, protect, hedge: hedgeModel(mr.hedge), rotate: rotateModel(mr.rotate), segments, glossary: mr.glossary ?? {},
    verdict, exposure, exposureNote, topReview: review[0] ?? null,
    sectors: rows, sectorsFoot: foot,
    positions: be?.rows ?? [], positionsMore,
    review, budgets, budgetsNote, stopsKnown: be?.stops_known !== false, reentry, reentryMore,
  }
}
