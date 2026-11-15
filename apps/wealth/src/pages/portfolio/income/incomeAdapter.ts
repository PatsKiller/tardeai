import type { RenderState } from '../../../components/renderState.ts'
import { accountDisplayLabel } from '../accountLabel.ts'
import { record, rows, text, number, safeText, state } from '../../home/homeAdapter.ts'
import type { Read, Row } from '../../home/homeAdapter.ts'
export const INCOME_PATH = '/api/v2/dividends'
export interface IncomeLeg { ref: string; scope: string; account: string; symbol: string; yield: number | null; annual: number | null; monthly: number | null; frequency: string; tax: string; safety: string }
export interface IncomeMonth { month: number | null; name: string; total: number | null; symbols: string[] }
export interface IncomeDate { symbol: string; exDate: string; payDate: string; perShare: number | null; estimate: number | null }
export interface Income { hasData: boolean | null; built: string; method: string; annual: number | null; monthly: number | null; legs: IncomeLeg[]; accounts: { ref: string; label: string }[]; months: IncomeMonth[]; dates: IncomeDate[]; tax: string; safety: string }
export function incomeModel(r: Row): Income {
 const raw = rows(r.payers), keys: string[] = [], labels = record(r.account_labels)
 const keyOf = (p: Row) => text(p.account || p.account_key) || '_unassigned'
 for (const key of [...raw.map(keyOf), ...Object.keys(record(r.by_account))]) if (!keys.includes(key)) keys.push(key)
 const accounts = keys.map((key, i) => {
  const served = text(labels[key]), rowLabel = text(raw.find(p => keyOf(p) === key && p.account_label)?.account_label)
  const label = accountDisplayLabel(key, served || null, rowLabel || null)
  return { ref: key === '_unassigned' ? 'unassigned' : `account-${i}`, label: key === '_unassigned' ? 'Unassigned' : label === key ? `Account label unavailable (${i + 1})` : safeText(label) }
 })
 const accountFor = (p: Row) => accounts[keys.indexOf(keyOf(p))]
 const hasData = typeof r.has_data === 'boolean' ? r.has_data : null
 return {
  hasData, built: text(r.last_updated), method: text(r.account_attribution) || 'Unknown',
  annual: hasData === true && raw.length ? number(r.total_annual) : null,
  monthly: hasData === true && raw.length ? number(r.monthly_average) : null,
  // One emitted row is one leg, including repeated symbol/account pairs. No browser split or deduplication.
  legs: hasData === true ? raw.map((p, i) => ({ref:`leg-${i}`,scope:accountFor(p).ref,account:accountFor(p).label,symbol:safeText(p.symbol),yield:number(p.yield_pct),annual:number(p.annual_income),monthly:number(p.monthly_amort),frequency:safeText(p.frequency),tax:'Unknown',safety:'Unknown'})) : [],
  accounts, months: hasData === true && raw.length ? rows(r.monthly_summary).map(m => ({month:number(m.month),name:safeText(m.month_name),total:number(m.total),symbols:Array.isArray(m.symbols) ? m.symbols.map(v => safeText(v)).filter(Boolean) : []})) : [],
  dates: hasData === true && raw.length ? rows(r.ex_div_alerts).map(d => ({symbol:safeText(d.symbol),exDate:text(d.ex_date),payDate:text(d.pay_date),perShare:number(d.amount),estimate:number(d.total_income)})) : [],
  tax:'Unknown',safety:'Unknown',
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
export function incomeScope(model: Income, scope: string) {
 const household = scope === 'household', account = model.accounts.find(a => a.ref === scope)
 const legs = household ? model.legs : model.legs.filter(p => p.scope === scope)
 const annual = sum(legs,'annual'), monthly = sum(legs,'monthly')
 const roundedDifference = household && model.annual !== null && annual !== null ? Math.round((model.annual - annual) * 100) / 100 : null
 return { household, label:household ? 'Household' : account?.label || 'Selected account unavailable', legs,
  annual:household ? model.annual : annual, monthly:household ? model.monthly : monthly,
  emittedAnnual:annual, emittedMonthly:monthly,
  // The published monthly pattern and alert amounts have no account contract.
  months:household ? model.months : [], dates:household ? model.dates : [],
  difference:roundedDifference === 0 ? 0 : roundedDifference,
 }
}
export function allocationLabel(method: string): string {
 return method === 'source_calendar' ? 'Source calendar account legs' : method === 'holdings_mv_share' ? 'Producer allocation by stored holdings market-value share' : 'Allocation method unknown'
}
