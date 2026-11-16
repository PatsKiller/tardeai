// C-PERF-A: presentation contract only. A future adapter owns financial eligibility,
// raw-field selection, account membership and clock validation (parity-v2 §3/§7A).
// No return calculation, source selection, request-time clock or fixture fallback.
import { accountDisplayLabel } from './accountLabel'
import { moneyTone, signedMoney, signedPct, toneClass } from './format'

export const PERFORMANCE_WINDOWS = ['Latest session', '1W', '1M', '3M', '6M', 'YTD', '1Y'] as const
export type PerformanceWindow = typeof PERFORMANCE_WINDOWS[number]
export type PerformanceQualifier = 'estimated' | 'partial' | 'stale'

export interface PerformanceNumber {
  /** Percent inputs are already percentages, never fractions. Amount inputs are USD. */
  value: number | null
  unknownReason: string | null
}

export interface PerformanceClock {
  label: string
  /** Source timestamps only, normalized to explicit UTC by the future adapter. */
  asOf: string | null
  ageSeconds: number | null
  freshness: 'fresh' | 'stale' | 'unknown'
}

interface MeasureEvidence {
  amount: PerformanceNumber
  percent: PerformanceNumber
  qualifiers: readonly PerformanceQualifier[]
  owner: string
  source: string
  clocks: readonly PerformanceClock[]
  /** Actual contributing/eligible account counts, never count(non-null period cells). */
  coverage: { included: number | null; total: number | null }
  startAt: string | null
  endAt: string | null
  /** Explicit attributed session only; neither observation date nor reference session. */
  attributedSession: string | null
  note: string | null
}

export interface PerformanceObservation extends MeasureEvidence {
  method: 'raw-nav' | 'holdings-price-move' | 'flow-adjusted'
}

export interface HouseholdEstimate extends MeasureEvidence {
  method: 'household-estimate'
  /** Preserve the producer's qualifications; this is not an account return. */
  methodNote: string
}

export type PerformanceMeasure = PerformanceObservation | HouseholdEstimate
export interface PerformanceHouseholdPeriod {
  observation: PerformanceObservation | null
  estimate: HouseholdEstimate | null
}

export interface PerformanceAccount {
  key: string
  /** Position in this source response, retained when scoped; display placeholder only. */
  sourceOrdinal?: number
  availablePeriods?: readonly PerformanceWindow[]
  label: string | null
  /** Caller supplies the actual membership/eligibility qualification; never inferred from keys. */
  scopeNote: string
  periods: Partial<Record<PerformanceWindow, PerformanceObservation>>
}

/** Portfolio audit 2026-11-16 (E): which accounts that hold positions have no performance row at all. */
export interface PerformanceAccountCoverage {
  /** Distinct accounts with stored holding rows in this response; null when the response does not serve them. */
  holdingAccounts: number | null
  /** Accounts with a performance row. */
  withResults: number
  /** Holding accounts with no performance row, by display label only (never an account key). */
  missing: string[]
}

export interface PerformancePageProps {
  /** Already scoped by the caller. This component neither filters nor re-aggregates accounts. */
  accounts: readonly PerformanceAccount[]
  household: Partial<Record<PerformanceWindow, PerformanceHouseholdPeriod>>
  gapOwner: string
  /** Literal windows present in the response, supplied by the adapter. */
  availablePeriods?: readonly PerformanceWindow[]
  /** Undefined permits fixture comparison; live always supplies a selected period or null. */
  selectedPeriod?: PerformanceWindow | null
  onPeriodChange?: (period: PerformanceWindow) => void
  showHousehold?: boolean
  /** Household view only; undefined for fixtures and single-account scope. */
  accountCoverage?: PerformanceAccountCoverage | null
}

export function performanceAccountLabel(account: PerformanceAccount): string {
  const label = accountDisplayLabel(account.key, account.label, null)
  if (label !== account.key && label.trim() !== '') return label
  const ordinal = account.sourceOrdinal ?? 0
  return Number.isSafeInteger(ordinal) && ordinal > 0 ? `Account ${ordinal} · label not served` : 'Account label not served'
}

export function numberIsKnown(number: PerformanceNumber): boolean {
  return number.value !== null && Number.isFinite(number.value)
}

export function numberText(number: PerformanceNumber, unit: 'amount' | 'percent', owner: string): string {
  if (!numberIsKnown(number)) return `Unknown — ${number.unknownReason?.trim() || `not served — owner: ${owner}`}`
  return unit === 'amount' ? signedMoney(number.value) : signedPct(number.value)
}

export function clockHasEvidence(clock: PerformanceClock): boolean {
  return clock.asOf !== null && /Z$/.test(clock.asOf) && Number.isFinite(Date.parse(clock.asOf))
    && clock.ageSeconds !== null && Number.isFinite(clock.ageSeconds) && clock.ageSeconds >= 0
}

export function measureWarnings(measure: PerformanceMeasure): string[] {
  const warnings: string[] = [...measure.qualifiers]
  const { included, total } = measure.coverage
  if (included !== null && total !== null && included < total) warnings.push('partial')
  if (measure.method === 'holdings-price-move' || measure.method === 'household-estimate') warnings.push('estimated')
  if (measure.clocks.some(clock => clock.freshness === 'stale')) warnings.push('stale')
  if (measure.clocks.length === 0 || measure.clocks.some(clock => clock.freshness === 'unknown' || !clockHasEvidence(clock))) warnings.push('freshness unknown')
  return [...new Set(warnings)]
}

export function numberClass(number: PerformanceNumber, measure: PerformanceMeasure): string {
  if (!numberIsKnown(number)) return 'money-unknown'
  // A measured zero stays neutral; the adjacent warning label still reports partial/stale/estimated.
  if (number.value === 0) return 'money-unknown'
  if (measureWarnings(measure).length > 0) return 'text-warn'
  return toneClass(moneyTone(number.value))
}

export function methodText(measure: PerformanceMeasure): string {
  switch (measure.method) {
    case 'raw-nav': return 'Raw NAV change — includes deposits/withdrawals'
    case 'holdings-price-move': return 'Estimated price movement of current holdings'
    case 'flow-adjusted': return 'Flow-adjusted change — supplied by the source'
    case 'household-estimate': return 'Approximate household estimate'
  }
}

export function coverageText(measure: PerformanceMeasure): string {
  const { included, total } = measure.coverage
  if (included === null || total === null || !Number.isInteger(included) || !Number.isInteger(total)
    || included < 0 || total < included) return `Account coverage unknown — owner: ${measure.owner}`
  return `${included} of ${total} accounts`
}

export function missingMeasure(window: PerformanceWindow, owner: string): PerformanceObservation {
  return {
    method: window === 'Latest session' ? 'holdings-price-move' : 'raw-nav',
    amount: { value: null, unknownReason: `not served — owner: ${owner}` },
    percent: { value: null, unknownReason: `not served — owner: ${owner}` },
    owner, source: 'not served', qualifiers: [], clocks: [],
    coverage: { included: null, total: null }, startAt: null, endAt: null,
    attributedSession: null, note: null,
  }
}

export function pageState(props: PerformancePageProps): 'empty' | 'unknown' | 'partial' | 'available' {
  if (props.accounts.length === 0) return 'empty'
  const measures: (PerformanceMeasure | undefined | null)[] = (props.selectedPeriod === undefined ? PERFORMANCE_WINDOWS : props.selectedPeriod === null ? [] : [props.selectedPeriod]).flatMap(window => [
    ...(props.showHousehold === false ? [] : [props.household[window]?.observation]),
    ...props.accounts.map(account => account.periods[window]),
  ])
  const estimates = (props.selectedPeriod === undefined ? PERFORMANCE_WINDOWS : props.selectedPeriod === null ? [] : [props.selectedPeriod]).map(window => props.showHousehold === false ? null : props.household[window]?.estimate).filter(m => m != null)
  const known = (m: PerformanceMeasure | undefined | null) => !!m && (numberIsKnown(m.amount) || numberIsKnown(m.percent))
  if (![...measures, ...estimates].some(known)) return 'unknown'
  if (measures.some(m => !m || !numberIsKnown(m.amount) || !numberIsKnown(m.percent) || measureWarnings(m).length > 0)
    || estimates.some(m => !!m && measureWarnings(m).length > 0)) return 'partial'
  return 'available'
}

// Synthetic render inputs only: invented round values and fake identities. Never an automatic page default.
const SYNTHETIC_CLOCK: PerformanceClock = {
  label: 'NAV observations', asOf: '2040-06-01T16:00:00Z', ageSeconds: 60, freshness: 'fresh',
}
const syntheticObservation = (value: number | null, percent: number | null): PerformanceObservation => ({
  method: 'raw-nav', amount: { value, unknownReason: 'insufficient history' },
  percent: { value: percent, unknownReason: 'insufficient history' }, qualifiers: [],
  owner: 'Performance source team', source: 'Synthetic NAV observations', clocks: [SYNTHETIC_CLOCK],
  coverage: { included: 2, total: 3 }, startAt: '2040-05-25T16:00:00Z', endAt: '2040-06-01T16:00:00Z',
  attributedSession: null, note: 'Synthetic example; actual snapshot bounds may be shorter than the requested window.',
})

export const SYNTHETIC_PERFORMANCE_PROPS: PerformancePageProps = {
  gapOwner: 'Performance source team',
  household: {
    'Latest session': { observation: { ...syntheticObservation(100, 1), method: 'holdings-price-move',
      clocks: [{ ...SYNTHETIC_CLOCK, label: 'Holdings marks' }], startAt: null }, estimate: null },
    '1W': { observation: syntheticObservation(200, 2), estimate: { ...syntheticObservation(100, 1),
      method: 'household-estimate', methodNote: 'Household residual approximation; external flows are not reconciled.',
      qualifiers: ['estimated', 'partial'] } },
    '1M': { observation: syntheticObservation(-100, -1), estimate: null },
    '3M': { observation: syntheticObservation(0, 0), estimate: null },
    '6M': { observation: syntheticObservation(null, null), estimate: null },
    YTD: { observation: { ...syntheticObservation(300, 3), qualifiers: ['stale'],
      clocks: [{ ...SYNTHETIC_CLOCK, label: 'YTD pin', freshness: 'stale', ageSeconds: 86400 }],
      startAt: '2040-01-01T00:00:00Z', note: 'Synthetic pinned snapshot A; pin source: synthetic NAV observations.' }, estimate: null },
    '1Y': { observation: { ...syntheticObservation(400, 4), qualifiers: ['partial'] }, estimate: null },
  },
  accounts: [
    { key: 'synthetic-a', label: 'Account A', scopeNote: 'Synthetic account membership', periods: {
      'Latest session': { ...syntheticObservation(100, 1), method: 'holdings-price-move', coverage: { included: 1, total: 1 } },
      '1W': { ...syntheticObservation(100, 1), coverage: { included: 1, total: 1 } },
      '1M': { ...syntheticObservation(-100, -1), coverage: { included: 1, total: 1 } },
      '3M': { ...syntheticObservation(0, 0), coverage: { included: 1, total: 1 } },
    } },
    { key: 'synthetic-b', label: 'Account B', scopeNote: 'Eligibility not established — owner: Account source team', periods: {} },
    { key: 'synthetic-c', label: 'Account C', scopeNote: 'Synthetic account membership; history not served', periods: {} },
  ],
}

/** E: plain disclosure of missing account results. Counts only; names are display labels from the adapter. */
export function accountCoverageText(c: PerformanceAccountCoverage): string {
  if (c.holdingAccounts === null) {
    return `${c.withResults} account${c.withResults === 1 ? '' : 's'} with performance rows. Accounts holding positions are not served in this response, so missing account results cannot be counted.`
  }
  const base = `${c.withResults} account${c.withResults === 1 ? '' : 's'} with performance rows; ${c.holdingAccounts} account${c.holdingAccounts === 1 ? '' : 's'} hold positions.`
  return c.missing.length
    ? `${base} No performance result for ${c.missing.length}: ${c.missing.join(', ')}. Their change is unknown, not zero, and is not in any account row below.`
    : `${base} Every account holding positions has a performance row.`
}
