// The Fundamentals page's filter: the SAME selector the Allocation page and the reviewed v0.5 view use, applied
// to the one served book. It computes nothing and derives nothing — it only decides which SERVED rows remain.
//
// Reuse, not a second definition: `normalizeBook` (analyticsAdapter) is the selector's row contract and
// `derivePortfolioView` (analytics/portfolio-analytics.mjs) is the approved filter, so account, sector and search
// mean here exactly what they mean on Allocation and on the reviewed AnalyticsPanel:
//   * account — the shell's one selection (`useBookScope`), never a page-local copy;
//   * sector  — the selector's own bucket (`selectorSector`: cash and fund rows share the Funds & Cash bucket);
//   * search  — symbol, name, account label or account key, case-insensitive (the selector's rule).
//
// The returned `rows` are the original `HoldingsRow` objects (`AnalyticsRow.holding`), untouched: this page prints
// served fields, so a filter must not become a place where a value is transformed. No fetch, no timer, no store.

import type { HoldingsBook, HoldingsRow } from '../portfolio/contract'
import type { AccountChoice, AnalyticsRow } from '../portfolio/analyticsAdapter'
import { SERVED_CURRENCY, accountOptions, normalizeBook, snapshotFor } from '../portfolio/analyticsAdapter'
import { derivePortfolioView } from '../portfolio/analytics/portfolio-analytics.mjs'
import type { Scope } from '../portfolio/scope'

export interface FundamentalsFilter {
  /** The shell's one selection: `'ALL'` or a served `accountKey`. */
  scope: Scope
  /** The selector's bucket key, `''` for every bucket. */
  sector: string
  query: string
}

export interface FundamentalsView {
  /** The served rows the filters keep, in the book's own order — the same objects the table renders. */
  rows: HoldingsRow[]
  /** The buckets the selected account serves, in the selector's order (the options the page may offer). */
  sectorOptions: string[]
  accounts: AccountChoice[]
  /** Rows in the whole book, the denominator the page states beside the filtered count. */
  bookRows: number
  /** The selector's refusal, stated instead of an empty table. Null when the view is valid. */
  refused: string | null
}

/**
 * Filter the one book. Pure: same book + same filter ⇒ same rows; the rows keep their identity (`===`), so the
 * table can be proven to print served fields and not re-derived copies.
 */
export function filterFundamentals(book: HoldingsBook, filter: FundamentalsFilter): FundamentalsView {
  const analytics: AnalyticsRow[] = normalizeBook(book)
  const accounts = accountOptions(analytics)
  const base: Omit<FundamentalsView, 'rows' | 'sectorOptions' | 'refused'> = {
    accounts,
    bookRows: book.rows.length,
  }
  try {
    const view = derivePortfolioView(
      analytics,
      { account: filter.scope === 'ALL' ? '' : filter.scope, sector: filter.sector, query: filter.query, currency: SERVED_CURRENCY },
      snapshotFor(book),
    )
    return {
      ...base,
      rows: view.rows.map(r => r.holding),
      sectorOptions: view.sectorOptions,
      refused: null,
    }
  } catch (e: unknown) {
    // A selector refusal is a state, not a blank table: the page prints this sentence and no rows.
    return { ...base, rows: [], sectorOptions: [], refused: e instanceof Error ? e.message : String(e) }
  }
}

/** The sentence the page prints when the filters leave no row — the reviewed selector's own copy, verbatim. */
export const EMPTY_NO_MATCH = 'No holdings match this view. Clear a filter to continue.'
