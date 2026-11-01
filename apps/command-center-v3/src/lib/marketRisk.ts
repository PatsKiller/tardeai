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
}

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
  return mr.carried_only ? CARRIED_MARKER : ''
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
