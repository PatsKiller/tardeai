/** Market-risk projection model for Home and the Risk page (design home/v002, risk/v002; DSN-20261031-market-risk-ui).
 *  Pure: shapes GET /api/v2/market-risk/latest into what the UI renders. No scoring here — a tier the engine did not
 *  compute is shown as NOT EVALUATED, never inferred from one source. */
import type { Tone } from './designTokens'

export type Tier = 'GREEN' | 'NONE' | 'BLUE' | 'YELLOW' | 'ORANGE' | 'RED' | 'NOT_EVALUATED'
export type MarketRiskState = 'not_evaluated' | 'evaluated' | 'stale'

export interface Contributor { name: string; points: number; detail?: string | null; as_of?: string | null }
export interface Category { name: string; state: 'CALM' | 'WARN' | 'STRESS' | 'UNKNOWN'; detail?: string | null; weight?: number | null; as_of?: string | null }
export interface Episode { id: string; tier: Tier; opened_at: string; repeats?: number; max_repeats?: number; acknowledged_at?: string | null; acknowledged_by?: string | null; status?: 'OPEN' | 'ACKED' | 'RESOLVED' }
export interface BudgetRow { budget: string; actual: number; limit: number; unit?: string; breached?: boolean }
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
