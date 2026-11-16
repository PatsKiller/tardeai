// Retirement — adapter for what /api/v2/retirement and /api/v2/retirement/planning-research actually serve.
//
// Pure: no React, no fetch. Audit rules kept here:
//   * unknown beats wrong. The producer builds `accounts`, `loan` and `dividend_income` with `or 0` defaults, so a
//     served 0 cannot be told from a missing value. A 0 is therefore rendered Unknown, with the reason, never $0;
//   * no figure is derived. Projected balances are withheld because the response does not carry the rate
//     assumptions they were built under; the narrative `intelligence_brief` is withheld because the producer
//     writes a fixed growth rate and a fixed monthly spending need into its text;
//   * every section names its clock, or says none is served.
import type { Envelope } from '../../../api/client'

export const RETIREMENT_PATH = '/api/v2/retirement'
export const RESEARCH_PATH = '/api/v2/retirement/planning-research'

export type Field<T> = { state: 'served'; value: T } | { state: 'unknown'; reason: string }
const ZERO_REASON = 'served as 0, which this producer cannot tell from a missing value'
const MISSING = 'not served'
// api_v2 retirement() substitutes these when the roadmap stores none, and does not say which it did (FE review L2-2).
const DEFAULTED = 'withheld: the producer substitutes a fixed default when no plan value is stored and does not say which this is'
// accounts.total is holdings.json portfolio_totals.total_value when one exists, else the roadmap total (FE review L2-1).
const NOT_COMPARABLE = 'withheld: the producer computes this as the holdings total minus a total that already is the holdings total whenever one exists, so nothing was compared'

type Obj = Record<string, unknown>
const isObj = (v: unknown): v is Obj => v !== null && typeof v === 'object' && !Array.isArray(v)

function money(v: unknown): Field<number> {
  if (typeof v !== 'number' || !Number.isFinite(v)) return { state: 'unknown', reason: MISSING }
  if (v === 0) return { state: 'unknown', reason: ZERO_REASON }
  return { state: 'served', value: v }
}
function num(v: unknown): Field<number> {
  return typeof v === 'number' && Number.isFinite(v) ? { state: 'served', value: v } : { state: 'unknown', reason: MISSING }
}
/** A count or measure the producer zero-fills when absent (`or 0` / `.get(k, 0)`): a 0 is Unknown, never 0 (L2-3). */
function zeroFilled(v: unknown): Field<number> {
  const f = num(v)
  return f.state === 'served' && f.value === 0 ? { state: 'unknown', reason: ZERO_REASON } : f
}
/** End age falls back to key_dates.golden_window_end, a date string: render what was served, as served (L2-4). */
function ageOrDate(v: unknown): Field<number | string> {
  if (typeof v === 'number' && Number.isFinite(v)) return v === 0 ? { state: 'unknown', reason: ZERO_REASON } : { state: 'served', value: v }
  if (typeof v === 'string' && v.trim() !== '') return { state: 'served', value: `${v.trim()} (served as a date, not an age)` }
  return { state: 'unknown', reason: MISSING }
}
const withheld = (reason: string): Field<never> => ({ state: 'unknown', reason })
function text(v: unknown): Field<string> {
  return typeof v === 'string' && v.trim() !== '' ? { state: 'served', value: v.trim() } : { state: 'unknown', reason: MISSING }
}

export interface Milestone { year: Field<number>; age: Field<number>; milestone: Field<string> }

export interface Retirement {
  asOf: Field<string>
  generated: Field<string>
  ageDays: number | null
  currentAge: Field<number>
  accounts: { total: Field<number>; roth: Field<number>; traditional: Field<number>; taxable: Field<number> }
  canonicalTotal: Field<number>
  snapshotDelta: Field<number>
  loan: { balance: Field<number>; deadline: Field<string>; storedDaysRemaining: Field<number>; monthlyToPayoff: Field<number> }
  goldenWindow: { startAge: Field<number>; endAge: Field<number | string>; yearsAvailable: Field<number>; annualConversion: Field<number>; bracketCeiling: Field<string> }
  dividend: { annualTotal: Field<number>; monthlyAvg: Field<number>; yieldPct: Field<number> }
  timeline: Milestone[]
  withheld: string[]
}

export interface ResearchTheme {
  theme: string
  /** null when not served (L2-5): never 0. */
  count: number | null
  items: { topic: string; status: string | null; confidence: number | null; at: string | null; sourceCount: number | null }[]
}
export interface Research { asOf: Field<string>; advisoryOnly: boolean; total: number | null; themes: ResearchTheme[] }

export type Section<T> =
  | { kind: 'loading' }
  | { kind: 'error'; message: string; lastGoodAt: string | null }
  | { kind: 'ok'; model: T; fetchedAt: string }

/** The producer answers {ok, data:{...}}; a bare object is also accepted. A declared `ok:false` is an error. */
function unwrap(body: unknown): Obj | null {
  if (!isObj(body)) return null
  if (body.ok === false) return null
  return isObj(body.data) ? body.data : body
}

function fail<T>(env: Envelope<unknown>, why?: string): Section<T> {
  return { kind: 'error', message: why ?? env.error ?? 'the read failed', lastGoodAt: env.lastGoodAt }
}

export function adaptRetirement(env: Envelope<unknown> | null, now: number): Section<Retirement> {
  if (env === null) return { kind: 'loading' }
  if (!env.ok) return fail(env)
  const d = unwrap(env.data)
  if (d === null) return fail(env, 'the producer declared the read unavailable or answered with no body')
  const acc = isObj(d.accounts) ? d.accounts : {}
  const loan = isObj(d.loan) ? d.loan : {}
  const gw = isObj(d.golden_window) ? d.golden_window : {}
  const div = isObj(d.dividend_income) ? d.dividend_income : {}
  const asOf = text(d.as_of)
  const gen = typeof d.snapshot_source === 'string' ? /generated (\S[^)]*)\)/.exec(d.snapshot_source) : null
  const generated: Field<string> = gen !== null && gen[1] !== 'unknown' ? { state: 'served', value: gen[1] } : { state: 'unknown', reason: MISSING }
  let ageDays: number | null = null
  if (generated.state === 'served') {
    const t = Date.parse(generated.value)
    if (Number.isFinite(t)) ageDays = Math.max(0, Math.floor((now - t) / 86_400_000))
  }
  const timeline: Milestone[] = (Array.isArray(d.timeline) ? d.timeline : []).filter(isObj).map(t => ({
    year: num(t.year), age: num(t.age), milestone: text(t.milestone),
  }))
  return {
    kind: 'ok',
    fetchedAt: env.fetchedAt,
    model: {
      asOf, generated, ageDays,
      currentAge: money(d.current_age),
      accounts: { total: money(acc.total), roth: money(acc.roth), traditional: money(acc.traditional), taxable: money(acc.taxable) },
      canonicalTotal: money(d.canonical_total),
      // L2-1: the served difference is structurally 0 (or -total when holdings.json is absent); never shown.
      snapshotDelta: withheld(NOT_COMPARABLE),
      loan: { balance: money(loan.balance), deadline: text(loan.deadline), storedDaysRemaining: zeroFilled(loan.days_remaining), monthlyToPayoff: money(loan.monthly_to_payoff) },
      goldenWindow: { startAge: withheld(DEFAULTED), endAge: ageOrDate(gw.end_age), yearsAvailable: zeroFilled(gw.years_available), annualConversion: withheld(DEFAULTED), bracketCeiling: text(gw.bracket_ceiling) },
      // L2-3: annual_total is zero-filled when dividend_calendar.json is missing, and yield_pct is then 0.0: both Unknown.
      dividend: { annualTotal: money(div.annual_total), monthlyAvg: money(div.monthly_avg), yieldPct: money(div.annual_total).state === 'served' ? zeroFilled(div.yield_pct) : { state: 'unknown', reason: 'the annual total it divides is not served' } },
      timeline,
      withheld: [
        'Projected balances (conservative / base / aggressive): the response does not carry the rate assumptions they were computed under.',
        'The intelligence brief: the producer writes a fixed growth rate and a fixed monthly spending need into that text; neither is a stored assumption of yours.',
        'Roth ladder, income floor, mortgage and rate assumptions: held in the stored roadmap but not in this response.',
        'Golden-window start age and annual conversion: the producer substitutes fixed defaults when none is stored and does not say which it served.',
        'Roadmap minus holdings total: the producer\'s "roadmap" total is the holdings total whenever one exists, so the served difference compares a number with itself.',
      ],
    },
  }
}

export function adaptResearch(env: Envelope<unknown> | null): Section<Research> {
  if (env === null) return { kind: 'loading' }
  if (!env.ok) return fail(env)
  const d = unwrap(env.data)
  if (d === null) return fail(env, 'the producer declared the read unavailable or answered with no body')
  const themes: ResearchTheme[] = (Array.isArray(d.themes) ? d.themes : []).filter(isObj).map(t => ({
    theme: typeof t.theme === 'string' ? t.theme : 'Unnamed theme',
    count: typeof t.count === 'number' ? t.count : null,
    items: (Array.isArray(t.items) ? t.items : []).filter(isObj).map(i => ({
      topic: typeof i.topic === 'string' ? i.topic : 'Untitled',
      status: typeof i.status === 'string' ? i.status : null,
      confidence: typeof i.confidence === 'number' ? i.confidence : null,
      at: typeof i.at === 'string' ? i.at : null,
      sourceCount: typeof i.source_count === 'number' ? i.source_count : null,
    })),
  }))
  return {
    kind: 'ok', fetchedAt: env.fetchedAt,
    model: { asOf: text(d.as_of), advisoryOnly: d.advisory_only === true, total: typeof d.total === 'number' ? d.total : null, themes },
  }
}
