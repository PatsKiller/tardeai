import type { RenderState } from '../../../components/renderState.ts'
import { accountDisplayLabel } from '../accountLabel.ts'
import { record, rows, text, number, safeText, state } from '../../home/homeAdapter.ts'
import type { Read, Row } from '../../home/homeAdapter.ts'
export const INCOME_PATH = '/api/v2/dividends'
export interface IncomeLeg { ref: string; scope: string; account: string; symbol: string; yield: number | null; annual: number | null; monthly: number | null; frequency: string; tax: string; safety: string; placed: boolean | null; months: number[] | null }
export interface IncomeMonth { month: number | null; name: string; total: number | null; symbols: string[] }
export interface IncomeDate { symbol: string; exDate: string; payDate: string; perShare: number | null; estimate: number | null }
/** Where an account name came from. Only `registry` is a resolved name; `served` is a name the producer sent without
 * saying where it came from; `fallback` prints the stable ref because no usable name was served. */
export type AccountNameSource = 'registry' | 'served' | 'fallback'
export interface IncomeAccount { ref: string; label: string; nameSource: AccountNameSource }
export interface Income { hasData: boolean | null; built: string; method: string; annual: number | null; monthly: number | null; legs: IncomeLeg[]; accounts: IncomeAccount[]; months: IncomeMonth[]; dates: IncomeDate[]; tax: string; safety: string; unplacedAnnual: number | null; unplacedSymbols: string[] | null; monthsBasis: string }
// Portfolio audit 2026-11-16 (F): accounts were "Account label unavailable (1)/(2)/(3)" — positional numbers that
// change with payer order. The ref is now a stable digest of the served key (the key itself is never printed). The
// label comes only from this read (`account_labels` or the payer row): Income is one GET by contract, so naming the
// accounts is producer work on /api/v2/dividends. Until then the unavailable label carries the stable ref.
export function stableAccountRef(key: string): string {
 let h = 0x811c9dc5
 for (let i = 0; i < key.length; i++) { h ^= key.charCodeAt(i); h = Math.imul(h, 0x01000193) >>> 0 }
 return 'acct-' + h.toString(16).padStart(8, '0')
}
/** Frequencies with a stated schedule; anything else (missing, Unknown) is unscheduled and totalled separately. */
export const SCHEDULED_FREQUENCIES = ['monthly', 'quarterly', 'semiannual', 'semi-annual', 'annual']
export const isScheduled = (l: IncomeLeg) => SCHEDULED_FREQUENCIES.includes(l.frequency.trim().toLowerCase())
export function incomeModel(r: Row): Income {
 const raw = rows(r.payers), keys: string[] = [], labels = record(r.account_labels)
 // F2: `account_label_source` says whether a served name is the registry's. A `derived` or `unlabelled` label is
 // only the key re-cased (or the number-safe placeholder), so it is printed as the stable fallback ref instead.
 const sources = r.account_label_source && typeof r.account_label_source === 'object' ? record(r.account_label_source) : null
 const keyOf = (p: Row) => text(p.account || p.account_key) || '_unassigned'
 for (const key of [...raw.map(keyOf), ...Object.keys(record(r.by_account))]) if (!keys.includes(key)) keys.push(key)
 const accounts: IncomeAccount[] = keys.map(key => {
  const ref = stableAccountRef(key)
  if (key === '_unassigned') return { ref: 'unassigned', label: 'Unassigned', nameSource: 'fallback' }
  const source = sources ? text(sources[key]) : ''
  const fallback: IncomeAccount = { ref, label: `Account label unavailable · ${ref}`, nameSource: 'fallback' }
  if (sources && source !== 'registry') return fallback
  const served = text(labels[key]), rowLabel = sources ? '' : text(raw.find(p => keyOf(p) === key && p.account_label)?.account_label)
  const label = accountDisplayLabel(key, served || null, rowLabel || null)
  return label === key ? fallback : { ref, label: safeText(label), nameSource: source === 'registry' ? 'registry' : 'served' }
 })
 const accountFor = (p: Row) => accounts[keys.indexOf(keyOf(p))]
 const hasData = typeof r.has_data === 'boolean' ? r.has_data : null
 return {
  hasData, built: text(r.last_updated), method: text(r.account_attribution) || 'Unknown',
  annual: hasData === true && raw.length ? number(r.total_annual) : null,
  monthly: hasData === true && raw.length ? number(r.monthly_average) : null,
  // One emitted row is one leg, including repeated symbol/account pairs. No browser split or deduplication.
  legs: hasData === true ? raw.map((p, i) => ({ref:`leg-${i}`,scope:accountFor(p).ref,account:accountFor(p).label,symbol:safeText(p.symbol),yield:number(p.yield_pct),annual:number(p.annual_income),monthly:number(p.monthly_amort),frequency:safeText(p.frequency),tax:'Unknown',safety:'Unknown',placed:Array.isArray(p.months) ? p.months.length > 0 : null,months:Array.isArray(p.months) ? p.months.map(v => number(v)).filter((v): v is number => v !== null && v >= 1 && v <= 12) : null})) : [],
  accounts, months: hasData === true && raw.length ? rows(r.monthly_summary).map(m => ({month:number(m.month),name:safeText(m.month_name),total:number(m.total),symbols:Array.isArray(m.symbols) ? m.symbols.map(v => safeText(v)).filter(Boolean) : []})) : [],
  dates: hasData === true && raw.length ? rows(r.ex_div_alerts).map(d => ({symbol:safeText(d.symbol),exDate:text(d.ex_date),payDate:text(d.pay_date),perShare:number(d.amount),estimate:number(d.total_income)})) : [],
  tax:'Unknown',safety:'Unknown',
  // F3: months are placed by observed ex-date months. Unplaced payers are served apart (null = not served).
  unplacedAnnual: hasData === true ? number(r.unplaced_annual) : null,
  unplacedSymbols: hasData === true && Array.isArray(r.unplaced) ? rows(r.unplaced).map(u => safeText(u.symbol)) : null,
  monthsBasis: text(r.monthly_summary_basis),
 }
}
export function incomeState(read: Read, now: number): RenderState<Income> {
 const result = state(read, incomeModel, now)
 // The shared client caches HTTP success, which is not an acceptance receipt. Never label it last-good.
 const out = {...result,lastGood:null,lastGoodAgeSeconds:null}
 if (out.data?.hasData === null) return {...out,status:'UNKNOWN',reason:'Forecast availability is not supplied. No income amount can be confirmed.',data:null}
 return out
}
const sum = (legs: IncomeLeg[], key: 'annual' | 'monthly'): number | null => legs.length && legs.every(l => l[key] !== null) ? legs.reduce((total, l) => total + (l[key] as number), 0) : null
export interface IncomeAccountRow { ref: string; label: string; nameSource: AccountNameSource; legs: number; annual: number | null; scheduledAnnual: number | null; unscheduledAnnual: number | null; placedAnnual: number | null; unplacedAnnual: number | null; months: (number | null)[] | null; monthsSum: number | null; expectedPlaced: number | null; gap: number | null }
const r2 = (v: number) => Math.round(v * 100) / 100
/** Account x month grid. The producer serves months only for the household; each leg serves its observed months, so a
 * leg's annual is spread equally over them (the calendar's stated rule). Null whenever any leg's months are not served. */
export function accountMonthRow(legs: IncomeLeg[]): (number | null)[] | null {
 if (!legs.length || legs.some(l => l.months === null || l.annual === null)) return null
 const out = Array.from({length: 12}, () => 0)
 for (const l of legs) if (l.months!.length) for (const m of l.months!) out[m - 1] += (l.annual as number) / l.months!.length
 return out.map(v => r2(v))
}
export function incomeAccountRows(model: Income): IncomeAccountRow[] {
 return model.accounts.filter(a => model.legs.some(l => l.scope === a.ref)).map(a => {
  const legs = model.legs.filter(l => l.scope === a.ref), placed = legs.filter(l => l.placed === true), un = legs.filter(l => l.placed === false)
  const months = accountMonthRow(legs), monthsSum = months ? r2(months.reduce((t: number, v) => t + (v as number), 0)) : null
  const placedAnnual = sum(placed, 'annual') ?? (placed.length ? null : 0), unplacedAnnual = sum(un, 'annual') ?? (un.length ? null : 0)
  const known = legs.every(l => l.placed !== null)
  const expectedPlaced = known ? placedAnnual : null
  return { ref: a.ref, label: a.label, nameSource: a.nameSource, legs: legs.length, annual: sum(legs, 'annual'),
   scheduledAnnual: sum(legs.filter(isScheduled), 'annual') ?? (legs.some(isScheduled) ? null : 0), unscheduledAnnual: sum(legs.filter(l => !isScheduled(l)), 'annual') ?? (legs.some(l => !isScheduled(l)) ? null : 0),
   placedAnnual: known ? placedAnnual : null, unplacedAnnual: known ? unplacedAnnual : null, months, monthsSum, expectedPlaced,
   gap: monthsSum !== null && expectedPlaced !== null ? r2(monthsSum - expectedPlaced) + 0 : null }
 })
}
/** Largest per-month gap between the account rows (summed) and the served household months; null if either is not served. */
export function gridVsServed(model: Income): number | null {
 const rowsAll = incomeAccountRows(model)
 if (!rowsAll.length || rowsAll.some(r => r.months === null) || model.months.length !== 12 || model.months.some(m => m.total === null || m.month === null)) return null
 let worst = 0
 for (const m of model.months) { const col = rowsAll.reduce((t: number, r) => t + ((r.months as number[])[(m.month as number) - 1]), 0); worst = Math.max(worst, Math.abs(r2(col - (m.total as number)))) }
 return r2(worst)
}
export function incomeScope(model: Income, scope: string) {
 const household = scope === 'household', account = model.accounts.find(a => a.ref === scope)
 const legs = household ? model.legs : model.legs.filter(p => p.scope === scope)
 const annual = sum(legs,'annual'), monthly = sum(legs,'monthly')
 const roundedDifference = household && model.annual !== null && annual !== null ? Math.round((model.annual - annual) * 100) / 100 : null
 const placedLegs = legs.filter(l => l.placed === true), unplacedLegs = legs.filter(l => l.placed === false)
 // Household month reconciliation: twelve months = annual − unplaced, up to one cent per placed payer-month of
 // producer rounding. The gap is printed, never normalized away. Null when any input is not served.
 const monthsSum = household && model.months.length && model.months.every(m => m.total !== null) ? Math.round(model.months.reduce((t, m) => t + (m.total as number), 0) * 100) / 100 : null
 const placedExpected = household && model.annual !== null && model.unplacedAnnual !== null ? Math.round((model.annual - model.unplacedAnnual) * 100) / 100 : null
 const monthsGap = monthsSum !== null && placedExpected !== null ? Math.round((monthsSum - placedExpected) * 100) / 100 : null
 return { household, label:household ? 'Household' : account?.label || 'Selected account unavailable', nameSource:household ? null : account?.nameSource ?? null, legs,
  annual:household ? model.annual : annual, monthly:household ? model.monthly : monthly,
  emittedAnnual:annual, emittedMonthly:monthly,
  // The published monthly pattern and alert amounts have no account contract.
  months:household ? model.months : [], dates:household ? model.dates : [],
  difference:roundedDifference === 0 ? 0 : roundedDifference,
  // Audit F: legs with an unknown frequency cannot be placed in a month, so the twelve-month pattern cannot hold
  // them; they are totalled apart instead of disappearing from the monthly view.
  scheduled:legs.filter(isScheduled), unscheduled:legs.filter(l => !isScheduled(l)),
  scheduledAnnual:sum(legs.filter(isScheduled),'annual'), unscheduledAnnual:sum(legs.filter(l => !isScheduled(l)),'annual'),
  // Placement (the producer's real month rule) wins over frequency when every leg in scope says whether it is placed.
  placementKnown: legs.length > 0 && legs.every(l => l.placed !== null),
  placed: placedLegs, unplaced: unplacedLegs,
  placedAnnual: sum(placedLegs,'annual') ?? (placedLegs.length ? null : 0), unplacedAnnual: sum(unplacedLegs,'annual') ?? (unplacedLegs.length ? null : 0),
  monthsSum, placedExpected, monthsGap: monthsGap === 0 ? 0 : monthsGap,
  accountRows: household ? incomeAccountRows(model) : incomeAccountRows(model).filter(r => r.ref === scope),
  gridVsServed: household ? gridVsServed(model) : null,
 }
}
export function allocationLabel(method: string): string {
 return method === 'source_calendar' ? 'Source calendar account legs' : method === 'holdings_mv_share' ? 'Producer allocation by stored holdings market-value share' : 'Allocation method unknown'
}
