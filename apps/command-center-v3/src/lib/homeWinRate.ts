/**
 * homeWinRate.ts — single-source win-rate selection for the Home header.
 *
 * Two distinct win-rate concepts existed under the Home "PAPER WIN RATE" label
 * and coalesced into one number (`journal?.win_rate ?? readiness?.win_rate`),
 * so the numerator and denominator could come from different producers and the
 * tile implied a single coherent measurement that never existed. This module
 * removes the coalescing: each metric comes from exactly one named source with
 * its own basis, window, account scope and observation time, and neither ever
 * falls back to the other.
 *
 *   paperWinRate  → /api/v2/paper-trade-readiness.win_rate (paper statistics)
 *   journalWinRate → /api/v2/overview.journal.win_rate (broker round-trips)
 *
 * Pure functions. No network, no React, no side effects.
 */

export type WinRateMetric = {
  value: number | null
  trades: number | null
  source: string
  basis: string | null
  scope: string | null
  window: string | null
  asOf: string | null
}

/**
 * Paper-trading win rate. From paper_trade_statistics only. Never the broker
 * journal, which is REALIZED trading under a different basis.
 */
export function paperWinRate(readiness: Record<string, unknown> | null | undefined): WinRateMetric {
  return {
    value: typeof readiness?.win_rate === 'number' ? readiness.win_rate : null,
    trades: typeof readiness?.closed_usable === 'number' ? readiness.closed_usable : null,
    source: 'paper-trade-readiness.win_rate',
    basis: 'paper_trade_statistics',
    scope: 'paper',
    window: 'all_time',
    asOf: typeof readiness?.timestamp === 'string' ? readiness.timestamp : null,
  }
}

/**
 * Broker-verified trading win rate. From overview.journal only (the local
 * broker round-trips journal). Never the paper-readiness metric.
 */
export function journalWinRate(journal: Record<string, unknown> | null | undefined): WinRateMetric {
  return {
    value: typeof journal?.win_rate === 'number' ? journal.win_rate : null,
    trades: typeof journal?.trade_count === 'number' ? journal.trade_count : null,
    source: 'overview.journal.win_rate',
    basis: typeof journal?.basis === 'string' ? journal.basis : null,
    scope: typeof journal?.account_scope === 'string' ? journal.account_scope : null,
    window: typeof journal?.time_window === 'string' ? journal.time_window : null,
    asOf: typeof journal?.as_of === 'string' ? journal.as_of : null,
  }
}
