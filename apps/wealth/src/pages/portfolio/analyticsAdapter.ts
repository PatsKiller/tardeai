// The v0.5 adapter: a served `HoldingsBook` → the APPROVED selector's normalized-row contract.
//
// This file is the ONLY place the port decides what a row's sector is, and every decision cites a served field.
// It imports no React and no DOM — the tests drive it directly — and it imports the selector module only for
// TYPES, so node can load this file without a bundler.
//
// THE SECTOR RULE (contract r6 §5, operator addendum 2026-11-15T1500Z), in this order:
//   1. a cash row is cash — it is bucketed with funds (see below), never read for a label;
//   2. `profile_source == "unavailable"` ⇒ "Sector unavailable for this symbol". The carried `sector` text is
//      NOT used (R6e): provenance says the classification could not be sourced, so printing the old label
//      would pass it off as classified. This is also §4's classifier order — the provenance check runs
//      before any fund/curated mapping;
//   3. a fund row (served `asset_type` ETF or MUTUAL_FUND) ⇒ "Funds & Cash". The classification is the fund
//      itself, never invented constituent look-through;
//   4. the served `sector` label when it is non-empty;
//   5. otherwise "Unclassified" — null/empty is an absence, not a category the provider chose.
//
// `sector_kind` and `sector_freshness` are deliberately NOT bound: r6 §5 says they do not ship yet, and this
// read does not serve them. Freshness is not part of the label (r6 §5 item 2) — an old label is still a label,
// and the row's own clocks are shown elsewhere.
//
// WHY CASH AND FUNDS SHARE ONE INTERNAL KEY. The approved selector hardcodes its cash bucket as
// 'Cash & sweep' (`sectorOf` in portfolio-analytics.mjs, copied byte-for-byte and not edited). The operator's
// rule puts funds and cash in one displayed bucket, "Funds & Cash". So a fund row is normalized to that same
// key, the selector merges the two populations into one bucket, and the DISPLAY label for the key is
// "Funds & Cash" everywhere the reader sees it (legend, sector select, row label). The internal key is used
// only to filter — the same one selector feeds the table, every chart, the KPI strip and the CSV.

import type { ClockRole, HoldingsBook, HoldingsRow } from './contract'
import { notCurrent } from './format'
import { accountFallbackLabel, stableAccountRef } from './accountLabel'
import type { AnalyticsRowInput, AnalyticsSnapshot, SnapshotClock } from './analytics/portfolio-analytics.mjs'

/** The page's declared contract currency (the table foot says so, and the adapter formats dollars). */
export const SERVED_CURRENCY = 'USD'

/** The approved selector's own cash bucket key. Internal: the reader never sees this string. */
export const CASH_BUCKET_KEY = 'Cash & sweep'

/** The displayed bucket for fund and cash rows. */
export const SECTOR_FUNDS = 'Funds & Cash'

/** Provenance said the classification could not be sourced — never the carried label (r6 §5/R6e). */
export const SECTOR_UNAVAILABLE = 'Sector unavailable for this symbol'

/** Null or empty classification. */
export const SECTOR_UNCLASSIFIED = 'Unclassified'

type SectorRow = Pick<HoldingsRow, 'kind' | 'assetType' | 'profileSource' | 'fundamentals'>

/** A fund is decided from the served asset type only — the row's own kind, never a guess from the name. */
export function isFundRow(row: Pick<HoldingsRow, 'assetType'>): boolean {
  return row.assetType === 'ETF' || row.assetType === 'MUTUAL_FUND'
}

/** The label a reader sees for this row's sector. Never a derived classification. */
export function sectorDisplayLabel(row: SectorRow): string {
  if (row.kind === 'CASH') return SECTOR_FUNDS
  if (row.profileSource === 'unavailable') return SECTOR_UNAVAILABLE
  if (isFundRow(row)) return SECTOR_FUNDS
  const label = row.fundamentals?.sector?.trim() ?? ''
  return label === '' ? SECTOR_UNCLASSIFIED : label
}

/** The key the approved selector buckets and filters on. Differs from the display label only for funds/cash. */
export function selectorSector(row: SectorRow): string {
  if (row.kind === 'CASH') return CASH_BUCKET_KEY
  if (row.profileSource === 'unavailable') return SECTOR_UNAVAILABLE
  if (isFundRow(row)) return CASH_BUCKET_KEY
  const label = row.fundamentals?.sector?.trim() ?? ''
  return label === '' ? SECTOR_UNCLASSIFIED : label
}

/** A selector bucket key as the reader sees it. The one place 'Cash & sweep' becomes 'Funds & Cash'. */
export function displaySectorKey(key: string): string {
  return key === CASH_BUCKET_KEY ? SECTOR_FUNDS : key
}

/** Where the displayed sector label came from, in words the reader can check. */
export function sectorSource(row: SectorRow): string {
  if (row.kind === 'CASH') return 'served asset type CASH — one bucket with funds'
  if (row.profileSource === 'unavailable') {
    return 'wire profile_source reports the classification could not be sourced; the carried sector text is not shown'
  }
  if (isFundRow(row)) return `served asset type ${row.assetType} — a fund is classified as the fund, not by constituent look-through`
  return 'wire sector'
}

/**
 * A normalized row plus the served row it came from. The selector returns the identical objects it was
 * given, so the table and the drawer read `holding` and no field is copied twice.
 */
export interface AnalyticsRow extends AnalyticsRowInput {
  holding: HoldingsRow
}

/** One account as the panel's select lists it: the served key plus the display label. */
export interface AccountChoice {
  key: string
  label: string
}

/**
 * The accounts served in a normalized book, label-sorted — the same set and order the top bar's scope lists
 * (scope.ts `scopeOptions`). A key with no served label falls back to the key and says so on the page, not here.
 */
export function accountOptions(rows: AnalyticsRow[]): AccountChoice[] {
  const seen = new Map<string, string>()
  for (const r of rows) {
    if (r.accountId !== '' && !seen.has(r.accountId)) seen.set(r.accountId, r.accountName || accountFallbackLabel(stableAccountRef(r.accountId)))
  }
  return [...seen.entries()]
    .map(([key, label]) => ({ key, label }))
    .sort((a, b) => a.label.localeCompare(b.label))
}

/**
 * The served book in the selector's required row contract.
 *
 * Three adaptations, each forced by a field this read does not serve and each stated in the READY note:
 *   * `currency` is the page's declared contract currency. The wire publishes NO currency field on a row
 *     (measured 30/30 rows, 2026-11-15), and the table foot already declares USD; the selector rejects a
 *     row without an ISO-3 currency, so inventing a per-row one is not an option and a second currency
 *     cannot arise on this read. `derivePortfolioView` still validates and would withhold totals if one did;
 *   * `securityId` is the symbol. No CUSIP or security-id field is served on this route; the symbol is the
 *     only identity the read has. It is used to group a security ACROSS accounts and for `securityCount`;
 *     row identity stays the account-scoped `rowId` below, so nothing is merged for the table or the drawer;
 *   * `unrealizedPnl` is the served `gainLoss`, passed through — never recomputed from price and basis.
 *
 * `rowId` is `${accountKey}:${symbol}`, the contract's own stable row key (contract.ts `HoldingsRow`) and the
 * key the table and the drawer already use. A row without an account or symbol therefore fails
 * `validateRows` — the page states that instead of charting an identity it cannot keep.
 */
export function normalizeBook(book: HoldingsBook): AnalyticsRow[] {
  return book.rows.map(r => ({
    rowId: `${r.accountKey}:${r.symbol}`,
    accountId: r.accountKey,
    accountName: r.accountLabel,
    securityId: r.symbol,
    symbol: r.symbol,
    name: r.name,
    snapshotId: book.asOf,
    currency: SERVED_CURRENCY,
    isCash: r.kind === 'CASH',
    sector: selectorSector(r),
    marketValue: r.marketValue,
    unrealizedPnl: r.gainLoss,
    holding: r,
  }))
}

/**
 * A validated last-success receipt: the ONLY evidence that lets a page say "last known good".
 *
 * `portfolio-holdings@2` serves no such receipt today (measured 2026-11-15: `data.metrics[]` carries
 * `verified:false, receipt:null` for all four governed measures, and `freshness` carries a verdict, not a
 * stored snapshot receipt). The page-read time, the document BUILD clock and a quote instant are all
 * DIFFERENT facts and none of them is a last-success receipt, so none of them may stand in for one.
 */
export interface LastSuccessReceipt {
  at: string
  source: string
}

/**
 * The four domain clocks the page shows, each with the clock role that may date it.
 *
 * `role: null` means the wire has NO clock for that domain, and the page says so with a fixed reason instead of
 * borrowing one. Basis is that case (review R1): the wire serves no basis clock — basis coverage is per-row
 * `basis_truth` — and the VALUATION role is the document's `generated_at`, which says when the document was
 * generated, not when the basis inputs were observed. Mapping basis to VALUATION printed a substituted clock
 * under the basis's name on a book where one non-cash row has no basis at all. §K forbids that: unknown beats
 * wrong, and a clock is never borrowed from another role.
 */
const DOMAIN_SPECS: { domain: SnapshotClock['domain']; label: string; role: ClockRole | null; staticReason?: string }[] = [
  { domain: 'quote', label: 'Quote', role: 'QUOTE' },
  { domain: 'positions', label: 'Positions', role: 'POSITIONS' },
  { domain: 'basis', label: 'Basis', role: null,
    staticReason: 'no basis clock is served on this read (basis coverage is per-row basis_truth)' },
  { domain: 'protection', label: 'Protection (stop read)', role: 'STOPS' },
]

/**
 * The book's four domain clocks, in view order. A role the wire does not declare is UNKNOWN with that reason —
 * never omitted (an absent clock is a fact about the read, and the operator asked to see it) and never borrowed
 * from another role: the stop read's gap is not the quote clock's fault and vice versa.
 */
export function snapshotClocks(book: HoldingsBook): SnapshotClock[] {
  return DOMAIN_SPECS.map(spec => {
    if (spec.role === null) {
      return { domain: spec.domain, label: spec.label, status: 'UNKNOWN', at: null, source: null,
        reason: spec.staticReason ?? `no ${spec.domain} clock is served on this read` }
    }
    const clock = book.clocks.find(c => c.role === spec.role) ?? null
    if (clock === null) {
      return { domain: spec.domain, label: spec.label, status: 'UNKNOWN', at: null, source: null,
        reason: `no ${spec.role} clock declared on this read` }
    }
    if (clock.at === null) {
      return { domain: spec.domain, label: spec.label, status: 'UNKNOWN', at: null, source: clock.source ?? null,
        reason: `${spec.role} clock declared without an instant` }
    }
    return { domain: spec.domain, label: spec.label, status: 'KNOWN', at: clock.at, source: clock.source ?? null, reason: '' }
  })
}

/**
 * "Data as of <instant> (<clock> clock)", or "Unknown (<reason>)". The instant is the book's served as-of; the
 * clock that dates it is the one `asOfClock` names, read from the book's OWN clocks — not from the four display
 * domains, because a book may be dated by a role the page does not display (VALUATION) and that instant is still
 * a served fact. An as-of that no declared clock dates is labelled so, with the reason.
 */
export function dataAsOfText(book: HoldingsBook): string {
  if (!book.asOf) return 'Unknown (the book served no as-of instant)'
  const clock = book.clocks.find(c => c.role === book.asOfClock) ?? null
  if (clock !== null && clock.at !== null) return `${book.asOf} (${book.asOfClock} clock)`
  return `Unknown (${clock === null
    ? `no ${book.asOfClock} clock declared on this read`
    : `${book.asOfClock} clock declared without an instant`})`
}

/**
 * The snapshot the selector carries. `status` is 'fresh' only when this page's own verdict says the book is
 * current (`notCurrent`, which reads the producer's verdict first). Passing 'fresh' is never independent proof —
 * it is the page's existing verdict.
 *
 * `last-good` is reachable ONLY with a validated receipt. Without one the status is 'unverified' and the page
 * prints "Last available snapshot · freshness unverified" — it never dresses an unverified read as last-good.
 */
export function snapshotFor(book: HoldingsBook, receipt: LastSuccessReceipt | null = null): AnalyticsSnapshot {
  const current = !notCurrent(book.freshness)
  const session = book.session.status === 'KNOWN' ? (book.session.phase ?? 'Session known') : 'Session unknown'
  const clocks = snapshotClocks(book)
  const dataAsOf = dataAsOfText(book)
  const overall = current && clocks.every(c => c.status === 'KNOWN') ? 'COMPLETE' : 'PARTIAL'
  const base: AnalyticsSnapshot = {
    id: book.asOf,
    currency: SERVED_CURRENCY,
    session,
    observedAt: book.asOf,
    clocks,
    dataAsOf,
    overall,
  }
  if (current) return { ...base, status: 'fresh' }
  if (receipt !== null) {
    return { ...base, status: 'last-good', receipt, reason: `Last known good ${receipt.at} · ${receipt.source}` }
  }
  return { ...base, status: 'unverified', reason: 'freshness unverified' }
}

/**
 * The one line the page may print about freshness, and the evidence behind it.
 *
 * `last-good` copy is produced from the receipt OBJECT, never from the status string: a snapshot whose status
 * says last-good but carries no receipt still renders "freshness unverified". That is the fail-closed behaviour
 * the route asks for, and the test that removes the receipt fails here.
 */
export interface FreshnessCopy {
  /** One concise warning, or '' when the read is current. */
  line: string
  overall: 'PARTIAL' | 'COMPLETE'
  dataAsOf: string
  clocks: SnapshotClock[]
}

export function freshnessCopy(snapshot: AnalyticsSnapshot): FreshnessCopy {
  const clocks = snapshot.clocks ?? []
  const overall = snapshot.overall ?? 'PARTIAL'
  const dataAsOf = snapshot.dataAsOf ?? 'Unknown (the snapshot does not say which clock dates it)'
  if (snapshot.status === 'fresh') return { line: '', overall, dataAsOf, clocks }
  if (snapshot.status === 'last-good' && snapshot.receipt !== undefined) {
    return { line: `Last known good ${snapshot.receipt.at} · ${snapshot.receipt.source}`, overall, dataAsOf, clocks }
  }
  return { line: 'Last available snapshot · freshness unverified', overall, dataAsOf, clocks }
}

// ---- L: the open-position gain/loss measure's own label ------------------------------------------------
// The KPI is "open-position gain/loss vs. cost", and it is PARTIAL whenever some held row has no published
// gain/loss. N and M are counted from the rows in the CURRENT filter (the selector's own coverage block), never
// constants: the same function feeds every filter state, which is what the test that changes the filter proves.
// It is not today's P&L, not YTD profit and not account profit; legacy rows stay in the subtotal.

export interface ExcludedGainLossRow {
  /** The row's stable identity, so the page can link the name to that row's own detail. */
  rowId: string
  label: string
  /** From the row's own coverage: no cost basis is a different absence from no published gain/loss. */
  reason: string
}

export interface GainLossCopy {
  title: string
  subtext: string
  partial: boolean
  published: number
  held: number
  excluded: ExcludedGainLossRow[]
}

/**
 * The §L measure label — ONE definition for every surface that names this measure: the reviewed panel's KPI
 * (`gainLossMeasureCopy().title`) and the Allocation route's KPI. `— partial` is part of the label, not a
 * separator a caller appends, so the two surfaces cannot drift into different names for the same number.
 */
export function gainLossMeasureLabel(partial: boolean): string {
  return `Open-position gain/loss vs. cost${partial ? ' — partial' : ''}`
}

export function gainLossMeasureCopy(view: {
  rows: AnalyticsRow[]
  coverage: { pnl: number; nonCash: number }
}): GainLossCopy {
  const published = view.coverage.pnl
  const held = view.coverage.nonCash
  const partial = published < held
  const excluded = view.rows
    .filter(r => !r.isCash && r.unrealizedPnl === null)
    .map(r => ({
      rowId: r.rowId,
      label: r.symbol || r.name || r.securityId,
      reason: r.holding.avgCost === null ? 'no basis served' : 'no gain/loss served',
    }))
  return {
    title: gainLossMeasureLabel(partial),
    subtext: `Unrealized on currently held positions · ${published} of ${held} have published gain/loss · legacy included · not today/YTD profit`,
    partial,
    published,
    held,
    excluded,
  }
}

/** `${valued}/${total} position rows valued` — the selector's own coverage phrase, ported verbatim. */
export function coverageText(valued: number, total: number): string {
  return `${valued}/${total} position rows valued`
}

// ---- Number formatting ---------------------------------------------------------------------------------------
// These three reproduce portfolio-analytics.mjs's own `money` / `pct` / `signed` exactly (same Intl options,
// same 'Unknown' fallback), so the React port prints the approved reference's strings. They are NOT
// format.ts's money()/pct(): that module formats an already-percent field and a dollar amount in cents, and
// the selector's formatters take a currency code and a 0..1 fraction. Two different instruments; kept apart.

/** "Unknown" for null. Compact form is the 1-digit notation the reference uses inside charts. */
export function moneyText(value: number | null, currency: string | null, compact = false): string {
  if (value === null || !Number.isFinite(value) || currency === null) return 'Unknown'
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency,
    notation: compact ? 'compact' : 'standard',
    maximumFractionDigits: compact ? 1 : 2,
  }).format(value)
}

/** The module's pct: input is a 0..1 FRACTION, output is a percent. Null is an em dash, never 0. */
export function percentText(fraction: number | null): string {
  if (fraction === null || !Number.isFinite(fraction)) return '—'
  return new Intl.NumberFormat('en-US', { style: 'percent', maximumFractionDigits: 1 }).format(fraction)
}

/** A signed compact dollar amount: "+$50K". The sign is explicit; zero carries none. */
export function signedMoneyText(value: number | null, currency: string | null): string {
  if (value === null || !Number.isFinite(value) || currency === null) return 'Unknown'
  return `${value > 0 ? '+' : ''}${moneyText(value, currency, true)}`
}
