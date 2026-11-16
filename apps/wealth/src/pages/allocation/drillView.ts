// Allocation drilldown — pure helpers behind the click-to-filter controls, the visible reset, the per-account
// and per-row figures, and the Holdings reconciliation line. No React, no fetch.
//
// Audit 2026-11-16 (G1, D2). Two rules this file exists to keep:
//   * a percentage always carries its value basis AND its weight basis. `WEIGHT_BASIS` is the one phrase table
//     the page and the tests share, so a bare percentage cannot be printed from here;
//   * the book total is reconciled to the Holdings page's own total by calling the Holdings summation
//     (workspaceV2/adapter `totals`) over the same served rows, or the page says why the two differ.
//
// Nothing here invents a figure. A weight is value / a denominator the caller names, and is null (printed
// "Unknown" or "—") when either side is unknown.

import type { HoldingsBook } from '../portfolio/contract'
import type { AnalyticsRow } from '../portfolio/analyticsAdapter'
import type { PortfolioView } from '../portfolio/analytics/portfolio-analytics.mjs'
import { totals } from '../portfolio/workspaceV2/adapter'

/** The value basis every amount and weight on this page shares. */
export const VALUE_BASIS =
  'published row market value in USD (stored quote clock), cash included, rows with no published value left out'

/** The two weight bases. A percentage is printed under exactly one of these names. */
export const WEIGHT_BASIS = {
  book: 'Weight of book',
  selected: 'Weight of selected view',
} as const

export interface Drill {
  /** A selector sleeve key or ''. */
  sector: string
  /** The shell scope key, or 'ALL'. */
  scope: string
  query: string
}

export const NO_DRILL: Drill = { sector: '', scope: 'ALL', query: '' }

export function isDrilled(d: Drill): boolean {
  return d.sector !== '' || d.scope !== 'ALL' || d.query.trim() !== ''
}

/** Clicking the active sleeve again lifts the filter; clicking another switches to it. */
export function toggleSector(current: string, clicked: string): string {
  return current === clicked ? '' : clicked
}

/** Clicking the active account again lifts the filter. */
export function toggleAccount(current: string, clicked: string): string {
  return current === clicked ? 'ALL' : clicked
}

export interface DrillChip {
  kind: 'sleeve' | 'account' | 'search'
  label: string
}

/** The filters currently narrowing the rows, as readable chips. `sleeveLabel`/`accountLabel` are page labels. */
export function drillChips(d: Drill, sleeveLabel: (key: string) => string, accountLabel: (key: string) => string): DrillChip[] {
  const out: DrillChip[] = []
  if (d.sector !== '') out.push({ kind: 'sleeve', label: `Sleeve: ${sleeveLabel(d.sector)}` })
  if (d.scope !== 'ALL') out.push({ kind: 'account', label: `Account: ${accountLabel(d.scope)}` })
  if (d.query.trim() !== '') out.push({ kind: 'search', label: `Search: ${d.query.trim()}` })
  return out
}

/** value / denominator, or null when either is unknown or the denominator is not positive. */
export function weightOf(value: number | null, denominator: number | null, allocationValid: boolean): number | null {
  if (value === null || denominator === null || !allocationValid || !(denominator > 0)) return null
  return value / denominator
}

export interface RowSlice {
  rowId: string
  symbol: string
  name: string
  accountId: string
  accountLabel: string
  sleeveKey: string
  isCash: boolean
  /** null = no published value (never $0). */
  value: number | null
  weightOfBook: number | null
  weightOfSelected: number | null
}

/** The rows the filters kept, each with both weights over their named denominators. `sleeveKeyOf` is the
 *  selector's own classification (`Cash & sweep` for cash), passed in so this file does not duplicate it. */
export function rowSlices(
  view: PortfolioView<AnalyticsRow>,
  bookView: PortfolioView<AnalyticsRow>,
  sleeveKeyOf: (r: AnalyticsRow) => string,
): RowSlice[] {
  return view.rows
    .map(r => ({
      rowId: r.rowId,
      symbol: r.symbol ?? r.securityId,
      name: r.name ?? '',
      accountId: r.accountId,
      accountLabel: r.accountName || r.accountId,
      sleeveKey: sleeveKeyOf(r),
      isCash: r.isCash,
      value: typeof r.marketValue === 'number' ? r.marketValue : null,
      weightOfBook: weightOf(typeof r.marketValue === 'number' ? r.marketValue : null, bookView.total, bookView.allocationValid),
      weightOfSelected: weightOf(typeof r.marketValue === 'number' ? r.marketValue : null, view.total, view.allocationValid),
    }))
    .sort((a, b) => (b.value ?? -Infinity) - (a.value ?? -Infinity) || a.symbol.localeCompare(b.symbol))
}

export interface AccountSlice {
  key: string
  label: string
  /** The account's own valued total through the same selector (no sector or search filter). null = none valued. */
  amount: number | null
  weightOfBook: number | null
  count: number
  valued: number
}

/** One line per served account, over the book denominator. `derive` is the selector with the book's snapshot. */
export function accountSlices(
  accounts: { key: string; label: string }[],
  derive: (accountKey: string) => PortfolioView<AnalyticsRow>,
  bookView: PortfolioView<AnalyticsRow>,
): AccountSlice[] {
  return accounts.map(a => {
    const v = derive(a.key)
    const amount = v.currencyValid && v.coverage.valued > 0 ? v.total : null
    return {
      key: a.key,
      label: a.label,
      amount,
      weightOfBook: weightOf(amount, bookView.total, bookView.allocationValid),
      count: v.coverage.total,
      valued: v.coverage.valued,
    }
  })
}

export interface Reconciliation {
  /** 'match' | 'differs' | 'unknown' — the verdict, computed. */
  status: 'match' | 'differs' | 'unknown'
  /** Holdings page summation (workspaceV2 `totals`) over the same rows, null when nothing is valued. */
  holdingsTotal: number | null
  allocationTotal: number | null
  difference: number | null
  holdingsCoverage: { valued: number; total: number }
  allocationCoverage: { valued: number; total: number }
  /** The sentence the page prints. Names the basis, and says why the bases differ when they do. */
  text: string
}

const TOLERANCE_USD = 0.005

/**
 * The allocation total against the Holdings total, on one basis.
 *
 * Both are sums of the served rows' published `market_value`, cash included, unvalued rows left out, so over
 * the SAME rows they must agree to the cent. When they do not, the difference is reported with both coverages
 * rather than hidden; when either side has no valued row the verdict is "unknown", never "match".
 */
export function reconcileWithHoldings(rows: AnalyticsRow[], allocationTotal: number | null, allocationCoverage: { valued: number; total: number }): Reconciliation {
  const h = totals(rows.map(r => r.holding), 'session').value
  const holdingsTotal = h.value
  const holdingsCoverage = { valued: h.n, total: h.m }
  if (holdingsTotal === null || allocationTotal === null) {
    return {
      status: 'unknown', holdingsTotal, allocationTotal, difference: null, holdingsCoverage, allocationCoverage,
      text: `Cannot reconcile: ${holdingsTotal === null ? 'the Holdings summation' : 'the allocation selector'} has no valued row on this basis (${VALUE_BASIS}).`,
    }
  }
  const difference = allocationTotal - holdingsTotal
  if (Math.abs(difference) < TOLERANCE_USD && holdingsCoverage.valued === allocationCoverage.valued) {
    return {
      status: 'match', holdingsTotal, allocationTotal, difference: 0, holdingsCoverage, allocationCoverage,
      text: `Reconciles to the Holdings total: both sum the same ${holdingsCoverage.valued} of ${holdingsCoverage.total} valued rows on one basis (${VALUE_BASIS}).`,
    }
  }
  return {
    status: 'differs', holdingsTotal, allocationTotal, difference, holdingsCoverage, allocationCoverage,
    text: `Does not reconcile to the Holdings total: allocation sums ${allocationCoverage.valued} of ${allocationCoverage.total} rows, Holdings sums ${holdingsCoverage.valued} of ${holdingsCoverage.total}. The bases differ in which rows carry a published value; the difference is shown, not adjusted.`,
  }
}

/**
 * Why the Holdings drawer's served percent is not the same figure as this page's weights. Stated, not
 * reconciled: the producer serves `portfolio_pct` without naming the value it divided (audit D2).
 */
export const SERVED_PCT_NOTE =
  'The Holdings row drawer also shows the producer’s own “percent of the cash-inclusive book”. That percent is not reconciled to the weights here: the producer does not serve the value basis it divided by (needed: portfolio_pct_basis, the value field plus its snapshot clock), so any gap between the two is unexplained, not an error on this page.'
