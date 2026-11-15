// WB-1: the fundamentals workspace view model — grouping, ordering and counts over SERVED rows, nothing else.
//
// The layout this feeds is the operator's approved reference (local only: `Main.dc.html`, WB-1 amendment
// LEAD-AMEND-WB1-EXACT-LAYOUT-NOW-20261115T1936Z), and the rules below are the binding ones from
// RULING-FUNDAMENTALS-WORKSPACE-TIER2-20261115T1934Z / T1936Z / T1938Z:
//
//   * NO PERCENTAGE IS SUMMED. A security held in several accounts is ONE group whose accounts appear as
//     sublines, each with its own served weight and value; the group's weight cell states the account count
//     instead of an invented total. This is the ruling's "accounts/quantities in sublines, no summing
//     percentages" applied literally — a merged weight would be a derived figure the review never saw.
//   * NO RATIO IS AVERAGED. The lead row (the largest served weight in the group) supplies the P/E, PEG, beta,
//     yield and gain cells; the sublines still carry every account, so nothing is hidden by the choice.
//   * Grouping key is the SELECTOR'S stable security identity — `securityId`, which `normalizeBook` documents
//     as the symbol because this route serves no CUSIP — scoped by the declared contract currency (one currency
//     on this read, so the key reduces to the symbol). Row identity stays `${accountKey}:${symbol}`; grouping
//     never merges rows for the drawer, only for display.
//   * Ordering is by weight, largest first: a single-row group by its served `portfolioPct`, a multi-account
//     group by its largest served row weight (a selection, never a sum).
//   * Shares of the book are computed on served VALUES (Σ market value of the section / Σ market value in
//     view), never on percentages, and the page tags them `derived` — the same D2 rule the rollup cards obey.
//   * No Tier 2 formula lives here. The three rollup cards that need one print Unknown in WB-1; WB-2 owns the
//     formulas (implied EPS, value-weighted P/E, book beta) and their tests.
//   * The ▲ mark is the ruling's D7 rule and nothing more: a record clock OLDER than the quote clock, shown as a
//     relative-date flag with the record's date. No age threshold, no colour verdict.

import type { HoldingsRow } from '../portfolio/contract'
import { isFundRow, sectorDisplayLabel } from '../portfolio/analyticsAdapter'

/** The three lenses the reference draws. The default is the reference's own (Valuation). */
export type Lens = 'valuation' | 'income' | 'risk'

export const LENSES: { key: Lens; label: string }[] = [
  { key: 'valuation', label: 'Valuation' },
  { key: 'income', label: 'Income' },
  { key: 'risk', label: 'Risk & ownership' },
]

/** How the tables are grouped. `security` is the reference's default. */
export type GroupBy = 'security' | 'account'

export const GROUPS: { key: GroupBy; label: string }[] = [
  { key: 'security', label: 'Security' },
  { key: 'account', label: 'Account' },
]

/** One table column. `identity` is always first; the rest vary by lens. */
export type ColumnKey =
  | 'identity'
  | 'weight'
  | 'pe'
  | 'peg'
  | 'ytd'
  | 'trend'
  | 'beta'
  | 'yield'
  | 'gain'
  | 'protection'
  | 'expense'
  | 'shortFloat'
  | 'ownership'

/** The reference's own header wording, character for character where the column exists there. */
export const COLUMN_LABEL: Record<ColumnKey, string> = {
  identity: 'Security · account',
  weight: 'Weight · value',
  pe: 'P/E trailing → fwd',
  peg: 'PEG',
  ytd: 'YTD',
  trend: 'Trend',
  beta: 'Beta',
  yield: 'Yield',
  gain: 'Gain / loss',
  protection: 'Protection',
  expense: 'Expense ratio',
  shortFloat: 'Short float',
  ownership: 'Insider / inst.',
}

/**
 * The equity column sets. Valuation is the reference's own ten columns, in its order and wording. The other
 * two lenses were not drawn in the reference, so each one shows a SUBSET of those same columns plus the served
 * ownership fields the lens names — no column is invented that has no served field behind it.
 */
export function equityColumns(lens: Lens): ColumnKey[] {
  switch (lens) {
    case 'income':
      return ['identity', 'weight', 'yield', 'gain', 'protection']
    case 'risk':
      return ['identity', 'weight', 'trend', 'beta', 'shortFloat', 'ownership', 'protection']
    case 'valuation':
      return ['identity', 'weight', 'pe', 'peg', 'ytd', 'trend', 'beta', 'yield', 'gain', 'protection']
  }
}

/** The fund column sets: the reference's fund table is the Valuation set — funds have no P/E columns to empty. */
export function fundColumns(lens: Lens): ColumnKey[] {
  switch (lens) {
    case 'income':
      return ['identity', 'weight', 'yield', 'expense', 'ytd', 'gain', 'protection']
    case 'risk':
      return ['identity', 'weight', 'ytd', 'trend', 'protection']
    case 'valuation':
      return ['identity', 'weight', 'yield', 'expense', 'ytd', 'trend', 'gain', 'protection']
  }
}

/** The reference gives each table its own minimum width: the fund table carries three fewer columns. */
export const EQUITY_MIN_WIDTH = 1180
export const FUND_MIN_WIDTH = 980

/** One account's line inside a group: the account label, the served quantity and price, this row's weight. */
export interface AccountLine {
  row: HoldingsRow
  accountLabel: string
  /** Serveds only — never a total of several accounts. */
  weightPct: number
  valueUsd: number | null
}

/** One displayed row. With `security` grouping this can hold several accounts; with `account` grouping, one. */
export interface Group {
  /** The selector's stable identity for display: the symbol (its `securityId`), or the row key in account mode. */
  key: string
  symbol: string
  name: string
  assetType: string | null
  /** The reference's `· [sector / industry]` text; null for funds, whose asset type replaces it. */
  sectorText: string | null
  /** Every served row behind this display row, in the book's order. Never merged for the drawer. */
  rows: HoldingsRow[]
  /** The row that supplies the ratio cells: the one with the largest served weight (a selection, not an average). */
  lead: HoldingsRow
  /** The group's served weight — present only when one account holds it. Never a sum of percentages. */
  weightPct: number | null
  /** Ordering only: the largest served row weight in the group. Not printed. */
  sortWeight: number
  /** Σ served market value over the group; null when any account's value is not served. */
  valueUsd: number | null
  lines: AccountLine[]
}

/**
 * A dollar total over the rows whose value IS served, with its own denominator on the face of it. The page prints
 * the count beside the share (`valuedText`) so a share can never read as covering a row it silently skipped — an
 * unpriced row is unknown, not zero, and a denominator that hid it would be a lie of omission.
 */
export interface ValueTotal {
  usd: number
  valued: number
  rows: number
}

export interface Section {
  kind: 'equity' | 'fund'
  groups: Group[]
  /** Served rows behind the groups (a security held twice counts twice). */
  rowCount: number
  /** Σ served market value over this section's valued rows, with the counts behind it. */
  value: ValueTotal
  /** This section's share of the view's valued total, percent. Null when either side has no served value. */
  sharePct: number | null
  /** Largest group order weight, for the reference's 44 px weight bars. Null when the section is empty. */
  maxWeight: number | null
}

export interface CashLine {
  rows: HoldingsRow[]
  value: ValueTotal
  sharePct: number | null
}

export interface Coverage {
  /** Rows in the population counted. */
  rows: number
  /** Non-cash rows carrying a served TRAILING P/E — a count of served fields, never an estimate. */
  withMultiple: number
  /** Rows whose profile record clock is older than their quote clock (D7). */
  staleRecords: number
}

/**
 * The Coverage card's three counts, over ONE population. The card's denominator is the book, so its numerator is
 * the book too: call this with every row the book served, never with a filtered view's rows — a filtered
 * numerator over a book denominator would read "3 of 30 rows" for a view of three.
 */
export function coverageOf(rows: HoldingsRow[]): Coverage {
  return {
    rows: rows.length,
    withMultiple: rows.filter(r => r.kind !== 'CASH' && (r.fundamentals?.peTrailing ?? null) !== null).length,
    staleRecords: rows.filter(r => recordOlderThanQuote(r)).length,
  }
}

export interface Workspace {
  equities: Section
  funds: Section
  cash: CashLine
  /** Σ served market value over every valued row in view; the denominator of each section's share. */
  value: ValueTotal
}

/** Σ served market value over the rows whose value is served — the counts travel with the sum, never hidden. */
export function valueTotal(rows: HoldingsRow[]): ValueTotal {
  let usd = 0
  let valued = 0
  for (const r of rows) {
    if (r.marketValue === null || !Number.isFinite(r.marketValue)) continue
    usd += r.marketValue
    valued += 1
  }
  return { usd, valued, rows: rows.length }
}

/** Σ served market value of ONE group; null when any account's value is not served (the sublines carry each). */
function groupValue(rows: HoldingsRow[]): number | null {
  let total = 0
  for (const r of rows) {
    if (r.marketValue === null || !Number.isFinite(r.marketValue)) return null
    total += r.marketValue
  }
  return rows.length === 0 ? null : total
}

/** A served instant, or null. `Date.parse` on the wire's ISO stamps only; never a guessed timezone. */
export function instantOf(iso: string | null): number | null {
  if (iso === null || iso.trim() === '') return null
  const t = Date.parse(iso)
  return Number.isFinite(t) ? t : null
}

/**
 * D7, and only D7: the row's record clock is OLDER than its quote clock. Both clocks must be served; a missing
 * clock is "not stated", never "stale".
 */
export function recordOlderThanQuote(row: Pick<HoldingsRow, 'profileUpdatedAt' | 'priceAsOf'>): boolean {
  const record = instantOf(row.profileUpdatedAt)
  const quote = instantOf(row.priceAsOf)
  return record !== null && quote !== null && record < quote
}

/** `MM-DD` (UTC) of a served instant — the reference's short record/protection stamp. Null when not served. */
export function shortStamp(iso: string | null): string | null {
  const t = instantOf(iso)
  if (t === null) return null
  const d = new Date(t)
  const mm = String(d.getUTCMonth() + 1).padStart(2, '0')
  const dd = String(d.getUTCDate()).padStart(2, '0')
  return `${mm}-${dd}`
}

/** The fund row's own asset type, in the reference's lowercase idiom ("ETF", "mutual fund"). */
export function assetTypeText(assetType: string | null): string {
  if (assetType === null || assetType.trim() === '') return 'asset type not served'
  if (assetType === 'MUTUAL_FUND') return 'mutual fund'
  return assetType
}

/** The reference's `· [sector / industry]` text for an equity row; a fund shows its asset type instead. */
export function sectorText(row: HoldingsRow): string | null {
  if (row.kind === 'CASH') return null
  if (isFundRow(row)) return assetTypeText(row.assetType)
  const label = sectorDisplayLabel(row)
  const industry = row.fundamentals?.industry?.trim() ?? ''
  // An unavailable classification is a provenance verdict: the carried industry text is not shown beside a
  // label that says the classification could not be sourced.
  if (row.profileSource === 'unavailable') return label
  return industry === '' ? label : `${label} / ${industry}`
}

function groupRows(rows: HoldingsRow[], groupBy: GroupBy): Map<string, HoldingsRow[]> {
  const out = new Map<string, HoldingsRow[]>()
  for (const r of rows) {
    const key = groupBy === 'account' ? `${r.accountKey}:${r.symbol}` : r.symbol
    const list = out.get(key)
    if (list === undefined) out.set(key, [r])
    else list.push(r)
  }
  return out
}

function toGroup(key: string, rows: HoldingsRow[]): Group {
  let lead = rows[0]
  for (const r of rows) if (r.portfolioPct > lead.portfolioPct) lead = r
  return {
    key,
    symbol: lead.symbol,
    name: lead.name,
    assetType: lead.assetType,
    sectorText: sectorText(lead),
    rows,
    lead,
    weightPct: rows.length === 1 ? lead.portfolioPct : null,
    sortWeight: lead.portfolioPct,
    valueUsd: groupValue(rows),
    lines: rows.map(r => ({
      row: r,
      accountLabel: r.accountLabel,
      weightPct: r.portfolioPct,
      valueUsd: r.marketValue,
    })),
  }
}

/** Order by weight, largest first; ties break on the symbol so the order is stable between renders. */
function byWeight(a: Group, b: Group): number {
  if (b.sortWeight !== a.sortWeight) return b.sortWeight - a.sortWeight
  return a.symbol.localeCompare(b.symbol)
}

function section(kind: 'equity' | 'fund', rows: HoldingsRow[], groupBy: GroupBy): Section {
  const groups = [...groupRows(rows, groupBy).entries()].map(([key, rs]) => toGroup(key, rs)).sort(byWeight)
  return {
    kind,
    groups,
    rowCount: rows.length,
    value: valueTotal(rows),
    sharePct: null,
    maxWeight: groups.length === 0 ? null : groups[0].sortWeight,
  }
}

/**
 * Build the workspace from the rows a filter kept. Pure: same rows + same mode ⇒ same display rows, and every
 * value in the result is either a served field, a sum of served dollar VALUES, or a count of served fields.
 */
export function buildWorkspace(rows: HoldingsRow[], groupBy: GroupBy): Workspace {
  const cash = rows.filter(r => r.kind === 'CASH')
  const funds = rows.filter(r => r.kind !== 'CASH' && isFundRow(r))
  const equities = rows.filter(r => r.kind !== 'CASH' && !isFundRow(r))
  const value = valueTotal(rows)
  const equitySection = section('equity', equities, groupBy)
  const fundSection = section('fund', funds, groupBy)
  const cashValue = valueTotal(cash)
  equitySection.sharePct = shareOfValue(equitySection.value, value)
  fundSection.sharePct = shareOfValue(fundSection.value, value)
  return {
    equities: equitySection,
    funds: fundSection,
    cash: { rows: cash, value: cashValue, sharePct: shareOfValue(cashValue, value) },
    value,
  }
}

/**
 * A part's share of the view's valued total, percent. Null when the part has no valued row or the view's valued
 * total is zero — never 0 for "no value to divide by".
 */
export function shareOfValue(part: ValueTotal, whole: ValueTotal): number | null {
  if (part.valued === 0 || whole.valued === 0 || whole.usd <= 0) return null
  return (part.usd / whole.usd) * 100
}

/** The denominator sentence a share carries: "over N of M rows whose value is served". */
export function valuedText(whole: ValueTotal): string {
  return `over ${whole.valued} of ${whole.rows} rows whose value is served`
}

/**
 * The reference's 44 px weight bar, drawn from the served weight and the largest weight in the section. The
 * bar is a second rendering of the same number, not a new one; a 2 px floor keeps a held position visible.
 */
export function barWidth(weightPct: number, maxWeight: number | null, track = 44): number {
  if (maxWeight === null || !Number.isFinite(maxWeight) || maxWeight <= 0) return 2
  const w = Math.round((track * weightPct) / maxWeight)
  return Math.max(2, Math.min(track, w))
}
