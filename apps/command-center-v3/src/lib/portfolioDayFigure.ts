/** The portfolio page's TODAY figure, taken from the backend and from nothing else.
 *
 * One source with the header TODAY tile: lib/todayPnlState decides whether a proven economic total exists, and
 * otherwise whether the backend reports a market-day move. The page must never derive the figure again from the
 * rows it happens to hold: on 2026-11-06 the header read +$5,576 (overview.today_move) while the portfolio
 * subtitle summed the 34 rows on screen to +$5,592 and the stored holdings total said $10,409, with
 * /api/v2/overview reporting today_change null because economic day P&L is unproven (OI-044). Four numbers for
 * one day, none of them labelled.
 *
 * A filter may only narrow to a figure the backend attributes to it: today_move.by_account carries the account
 * attribution. A signal filter has no backend attribution at all, and "no number" is the honest answer there —
 * summing a subset of rows would invent a figure the backend never states.
 */
import { deriveTodayPnlState } from './todayPnlState.ts'
import { canonicalAccountKey } from './accountLabels.ts'

export type PortfolioDayFigure = {
  /** The figure the page may show. null means the page shows no number. */
  change: number | null
  pct: number | null
  /** Provenance the reader must see BESIDE the figure (e.g. that economic day P&L is unproven). */
  note: string | null
  /** Why no figure is shown. null whenever a figure is shown. */
  reason: string | null
}

export type PortfolioDayOpts = {
  /** The account chip the reader selected, if any. */
  account?: string | null
  /** A signal sub-tab is active (the backend attributes day P&L per account, never per signal). */
  signalFiltered?: boolean
}

const ECONOMIC_UNPROVEN = 'holdings move · economic P&L unproven'

function finite(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

/** The backend's own words for why there is no proven day P&L, never a sentence this page invents. */
function reasonForUnproven(overview: Record<string, unknown>): string {
  const pnl = overview.today_pnl && typeof overview.today_pnl === 'object'
    ? overview.today_pnl as { coverage_reason?: string | null; gap?: { reason?: string | null } | null }
    : null
  const backend = pnl?.gap?.reason || pnl?.coverage_reason
  if (backend) return backend
  const state = deriveTodayPnlState(overview)
  if (state.economicUnknown) return 'economic day P&L is unproven and the backend reports no market-day move'
  return 'the backend reports no day P&L'
}

export function portfolioDayFigure(
  overview: Record<string, unknown> | null | undefined,
  opts: PortfolioDayOpts = {},
): PortfolioDayFigure {
  // No overview on this tab means the figure was not loaded — not that it is unproven, and certainly not zero.
  if (!overview) return { change: null, pct: null, note: null, reason: 'day P&L is not loaded on this view' }
  const state = deriveTodayPnlState(overview)
  if (opts.signalFiltered) {
    return { change: null, pct: null, note: null,
      reason: 'the backend attributes day P&L per account and for the whole book, never per signal' }
  }
  const account = opts.account ?? null
  if (account) {
    const move = overview.today_move && typeof overview.today_move === 'object'
      ? overview.today_move as { status?: string; by_account?: Record<string, { change?: number | null; change_pct?: number | null }> }
      : null
    const row = move?.status === 'REPORTED'
      ? (move.by_account?.[canonicalAccountKey(account)] ?? move.by_account?.[account]) : undefined
    const change = finite(row?.change)
    if (change == null) {
      return { change: null, pct: null, note: null,
        reason: `the backend attributes no day P&L to ${account.replace(/_/g, ' ')}` }
    }
    const pct = finite(row?.change_pct)
    return { change, pct: pct == null ? null : Math.round(pct * 100) / 100,
      note: state.economicUnknown ? ECONOMIC_UNPROVEN : null, reason: null }
  }
  if (state.change == null) {
    return { change: null, pct: null, note: null, reason: reasonForUnproven(overview) }
  }
  return { change: state.change, pct: state.pct,
    note: state.reportedMove ? ECONOMIC_UNPROVEN : null, reason: null }
}
