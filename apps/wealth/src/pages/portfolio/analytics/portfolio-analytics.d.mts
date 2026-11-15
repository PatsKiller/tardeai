// Types for the APPROVED v0.5 selector module (`portfolio-analytics.mjs`, sha256 98b826d3…a33f).
//
// The module is copied byte-for-byte from the approved package
// (`campaign-8h2-20261114/handoff/SOURCE-PORTFOLIO-ANALYTICS-V05-20261115T0340Z/portfolio-analytics.mjs`)
// and is not edited here — this declaration file is the only thing that lets a TypeScript page import it.
// The shape below is read off the module's `derivePortfolioView` return, not invented: if the module is
// ever re-approved at a different sha, re-derive this file against it.

/** Scope keys the selector accepts. An empty/absent member means "no filter on that axis". */
export interface AnalyticsScope {
  account?: string
  sector?: string
  query?: string
  /** One currency only; the module does no FX. `null` means "not chosen". */
  currency?: string | null
}

/** The snapshot identity and its served freshness fields (INTEGRATION.md §Required normalized row contract). */
export interface AnalyticsSnapshot {
  id: string
  currency?: string | null
  session?: string
  observedAt?: string
  /** fresh | last-good | stale | unavailable | unproven */
  status?: string
  reason?: string
}

/**
 * The minimum a row must carry for `validateRows` to accept it. Additional row fields pass through
 * untouched (the port adds `holding`, the underlying `HoldingsRow`, for the table and the drawer).
 */
export interface AnalyticsRowInput {
  rowId: string
  accountId: string
  accountName?: string
  securityId: string
  symbol?: string
  name?: string
  snapshotId: string
  currency: string
  isCash: boolean
  sector: string | null
  marketValue: number | null
  unrealizedPnl: number | null
}

export interface SectorBucket {
  key: string
  label: string
  value: number
  known: number
  count: number
  color: string
  weight: number | null
}

export interface HoldingBucket {
  key: string
  label: string
  value: number
  known: number
  count: number
  pnl: number
  pnlKnown: number
  nonCash: boolean
  rowIds: string[]
  weight: number | null
}

export interface AnalyticsCoverage {
  valued: number
  total: number
  pnl: number
  nonCash: number
  cash: number
  cashTotal: number
}

export interface PortfolioView<R extends AnalyticsRowInput = AnalyticsRowInput> {
  snapshot: AnalyticsSnapshot
  scope: { account: string; sector: string; query: string; currency: string | null }
  currencies: string[]
  sectorOptions: string[]
  rows: R[]
  total: number | null
  pnl: number | null
  cash: number | null
  currencyValid: boolean
  allocationValid: boolean
  negative: boolean
  sectors: SectorBucket[]
  holdings: HoldingBucket[]
  contributions: HoldingBucket[]
  coverage: AnalyticsCoverage
  securityCount: number
}

export function validateRows(rows: unknown, snapshotId: string): void

export function derivePortfolioView<R extends AnalyticsRowInput>(
  rows: R[],
  scope: AnalyticsScope,
  snapshot: AnalyticsSnapshot,
): PortfolioView<R>

export function escapeHTML(x: unknown): string

export function createPortfolioAnalytics(
  root: HTMLElement,
  options: {
    rows: AnalyticsRowInput[]
    snapshot: AnalyticsSnapshot
    scope?: AnalyticsScope
    onSelection?: (selection: { rows: AnalyticsRowInput[]; scope: AnalyticsScope; snapshotId: string; view: PortfolioView }) => void
  },
): {
  getView(): PortfolioView
  setScope(next: AnalyticsScope): void
  setData(rows: AnalyticsRowInput[], snapshot: AnalyticsSnapshot): void
  destroy(): void
}
