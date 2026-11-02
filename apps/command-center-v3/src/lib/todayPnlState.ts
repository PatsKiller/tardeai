/**
 * TODAY tile state: the P&L's OWN clock and the P&L census — never the
 * position-observation clock.
 *
 * The tile used to take its tone and colour from `overviewSurfaceFreshness()`,
 * which ages `overview.data_as_of`, the POSITION observation. Positions being
 * old says nothing about whether today's P&L is old: on the 2026-11-02 snapshot
 * the P&L quote and valuation clocks were current (14:15:02 ET) while the
 * position surface read stale, and the tile painted amber for the wrong clock.
 *
 * Two different conditions must never collapse into one word:
 *
 *   INCOMPLETE COVERAGE  a funded account or a holding row reported no day
 *                        change, so the sum covers only the known rows.
 *   AGED SOURCE          the P&L's own clock (calculated_at / session_date)
 *                        predates the latest session that has OPENED.
 *
 * Only fields TodayPnl@v1 already carries are read. No new producer, receipt,
 * payload field or numeric threshold is introduced. The session comparison uses
 * the same `latestSessionDate` helper the scanner surface uses to mean "prior
 * session", so a weekend or pre-open cannot make a fresh Friday P&L read aged.
 */

import { latestSessionDate } from './observationEnvelope.ts'
import { parseTimestamp } from './surfaceFreshness.ts'
import { fmtAsOf } from './asOfDisplay.ts'

export type TodayPnlPayload = {
  complete?: boolean | null
  missing_accounts?: string[] | null
  partial_accounts?: string[] | null
  unknown_rows?: number | null
  calculated_at?: string | null
  session_date?: string | null
}

export type TodayPnlState = {
  tone: 'ok' | 'warn'
  /** Condition name shown on the tile chip; null when nothing is wrong. */
  label: string | null
  /** Operator-facing detail for the tooltip/drill; null when nothing is wrong. */
  reason: string | null
  /** A funded account or holding row did not report a day change. */
  incompleteCoverage: boolean
  /** The P&L's own clock is older than the latest open session. */
  agedSource: boolean
}

const BARE_DATE = /^(\d{4}-\d{2}-\d{2})/

/** The completion session(s) named by the P&L's own clocks. */
function pnlClockSessions(todayPnl: TodayPnlPayload, now: Date): string[] {
  const sessions: string[] = []
  const calculated = parseTimestamp(todayPnl.calculated_at, now.getTime())
  if (calculated) sessions.push(latestSessionDate(calculated))
  if (typeof todayPnl.session_date === 'string') {
    const m = todayPnl.session_date.match(BARE_DATE)
    if (m) sessions.push(m[1])
  }
  return sessions
}

/**
 * Derive every presentation decision the TODAY tile makes about freshness.
 *
 * Reads `overview.today_pnl` only. `overview.data_as_of`, `portfolio_aggregate`
 * and every other position clock are deliberately out of scope: they answer a
 * different question and must not decide TODAY's tone.
 */
export function deriveTodayPnlState(
  overview: Record<string, unknown> | null | undefined,
  now: Date = new Date(),
): TodayPnlState {
  const todayPnl = (overview?.today_pnl && typeof overview.today_pnl === 'object')
    ? (overview.today_pnl as TodayPnlPayload)
    : {}

  const missing = Array.isArray(todayPnl.missing_accounts) ? todayPnl.missing_accounts : []
  const partial = Array.isArray(todayPnl.partial_accounts) ? todayPnl.partial_accounts : []
  const unknownRows = Number(todayPnl.unknown_rows ?? 0)
  const incompleteCoverage = missing.length > 0 || partial.length > 0

  const latest = latestSessionDate(now)
  const agedSource = pnlClockSessions(todayPnl, now).some(session => session < latest)

  if (!incompleteCoverage && !agedSource) {
    return { tone: 'ok', label: null, reason: null, incompleteCoverage: false, agedSource: false }
  }

  const bits: string[] = []
  if (incompleteCoverage) {
    bits.push(missing.length
      ? `${missing.length} funded acct(s) did not report`
      : `partial: ${unknownRows} row(s) without a day change`)
  }
  if (agedSource) {
    const clock = fmtAsOf(todayPnl.calculated_at)
      ?? (typeof todayPnl.session_date === 'string' ? todayPnl.session_date : null)
    bits.push(clock
      ? `P&L clock ${clock} predates the latest open session`
      : 'P&L clock predates the latest open session')
  }

  // Distinct condition names. When both hold, both are stated; neither is
  // folded into the other or into a bare "STALE".
  const label = [
    incompleteCoverage ? 'INCOMPLETE COVERAGE' : null,
    agedSource ? 'AGED SOURCE' : null,
  ].filter(Boolean).join(' · ')

  return {
    tone: 'warn',
    label,
    reason: bits.join(' · '),
    incompleteCoverage,
    agedSource,
  }
}
