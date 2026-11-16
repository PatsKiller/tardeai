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
  goldenWindow: { startAge: Field<number>; endAge: Field<number>; yearsAvailable: Field<number>; annualConversion: Field<number>; bracketCeiling: Field<string> }
  dividend: { annualTotal: Field<number>; monthlyAvg: Field<number>; yieldPct: Field<number> }
  timeline: Milestone[]
  withheld: string[]
}

export interface ResearchTheme {
  theme: string
  count: number
  items: { topic: string; status: string | null; confidence: number | null; at: string | null; sourceCount: number }[]
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
      snapshotDelta: num(d.snapshot_delta),
      loan: { balance: money(loan.balance), deadline: text(loan.deadline), storedDaysRemaining: num(loan.days_remaining), monthlyToPayoff: money(loan.monthly_to_payoff) },
      goldenWindow: { startAge: num(gw.start_age), endAge: num(gw.end_age), yearsAvailable: num(gw.years_available), annualConversion: money(gw.annual_conversion), bracketCeiling: text(gw.bracket_ceiling) },
      dividend: { annualTotal: money(div.annual_total), monthlyAvg: money(div.monthly_avg), yieldPct: num(div.yield_pct) },
      timeline,
      withheld: [
        'Projected balances (conservative / base / aggressive): the response does not carry the rate assumptions they were computed under.',
        'The intelligence brief: the producer writes a fixed growth rate and a fixed monthly spending need into that text; neither is a stored assumption of yours.',
        'Roth ladder, income floor, mortgage and rate assumptions: held in the stored roadmap but not in this response.',
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
    count: typeof t.count === 'number' ? t.count : 0,
    items: (Array.isArray(t.items) ? t.items : []).filter(isObj).map(i => ({
      topic: typeof i.topic === 'string' ? i.topic : 'Untitled',
      status: typeof i.status === 'string' ? i.status : null,
      confidence: typeof i.confidence === 'number' ? i.confidence : null,
      at: typeof i.at === 'string' ? i.at : null,
      sourceCount: typeof i.source_count === 'number' ? i.source_count : 0,
    })),
  }))
  return {
    kind: 'ok', fetchedAt: env.fetchedAt,
    model: { asOf: text(d.as_of), advisoryOnly: d.advisory_only === true, total: typeof d.total === 'number' ? d.total : null, themes },
  }
}
