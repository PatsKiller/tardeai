/** TODAY presentation follows declared economic proof and the backend session reference.
 * No money/count calculation, position clock, client calendar or extra request. */
export type TodayPnlPayload = {
  status?: string | null
  complete?: boolean | null
  scope?: string | null
  coverage_reason?: string | null
  gap?: { reason?: string | null; ticket?: string | null; owner?: string | null } | null
  missing_accounts?: string[] | null
  partial_accounts?: string[] | null
  unknown_rows?: number | null
  calculated_at?: string | null
  session_date?: string | null
  session_source?: string | null
  market_session?: { status?: string; latest_open_session?: string | null } | null
}
export type TodayPnlState = {
  tone: 'ok' | 'warn'
  label: string | null
  reason: string | null
  incompleteCoverage: boolean
  agedSource: boolean
  economicUnknown: boolean
  sessionUnknown: boolean
  latestOpenSession: string | null
  /** The figure TODAY shows. Economic total when proven; else the reported market-day move
   *  (today_move = /portfolio/performance periods.1D, the Home Accounts 1D). Never invented. */
  change: number | null
  pct: number | null
  sessionDate: string | null
  sessionSource: string | null
  /** true when the value is the reported market-day move rather than proven economic P&L. */
  reportedMove: boolean
  moveNote: string | null
}
export type TodayMovePayload = {
  status?: string | null
  change?: number | null
  change_pct?: number | null
  session_date?: string | null
  session_source?: string | null
  complete?: boolean | null
  missing_accounts?: string[] | null
  partial_accounts?: string[] | null
  unknown_rows?: number | null
  coverage_reason?: string | null
  note?: string | null
}
function finite(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}
function sessionDate(value: unknown): string | null {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null
  const parsed = new Date(value + 'T00:00:00Z')
  return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value ? value : null
}
export function deriveTodayPnlState(overview: Record<string, unknown> | null | undefined, now = new Date()): TodayPnlState {
  // Keep the call signature; the backend owns which market session has opened.
  void now
  const pnl: TodayPnlPayload = overview?.today_pnl && typeof overview.today_pnl === 'object' ? overview.today_pnl as TodayPnlPayload : {}
  const economicUnknown = pnl.status !== 'KNOWN' || pnl.complete !== true
  // LIVEFIX-H 2026-11-06: while economic day P&L is unproven (OI-044) the backend still reports the
  // book's market-day move — the SAME figure as Home Accounts 1D. Show it with its own session and
  // coverage; hiding it made TODAY read "ECONOMIC UNKNOWN / session UNDATED" beside a dated 1D.
  const move: TodayMovePayload = overview?.today_move && typeof overview.today_move === 'object' ? overview.today_move as TodayMovePayload : {}
  const moveChange = move.status === 'REPORTED' ? finite(move.change) : null
  const reportedMove = economicUnknown && moveChange != null
  const src: TodayPnlPayload & TodayMovePayload = reportedMove ? move : pnl
  const missing = Array.isArray(src.missing_accounts) ? src.missing_accounts : null
  const partial = Array.isArray(src.partial_accounts) ? src.partial_accounts : null
  const incompleteCoverage = (missing?.length ?? 0) > 0 || (partial?.length ?? 0) > 0
  const market = (Object.prototype.hasOwnProperty.call(pnl, 'market_session') ? pnl.market_session : overview?.market_session) as TodayPnlPayload['market_session']
  const latest = market?.status === 'KNOWN' ? sessionDate(market.latest_open_session) : null
  const session = sessionDate(src.session_date)
  const sessionUnknown = latest == null || session == null || session > latest
  const agedSource = latest != null && session != null && session < latest
  const bits: string[] = []
  if (economicUnknown && !reportedMove) bits.push([pnl.gap?.reason ?? pnl.coverage_reason ?? 'Economic day proof unavailable', pnl.gap?.ticket].filter(Boolean).join(' · '))
  if (incompleteCoverage) bits.push(missing?.length ? `${missing.length} funded acct(s) did not report` : `partial: ${src.unknown_rows ?? 'unknown'} row(s) without a day change`)
  if (sessionUnknown) bits.push(session && latest && session > latest ? 'P&L session exceeds the latest proven open session' : 'P&L session or backend market-session reference is unknown')
  if (agedSource) bits.push(`P&L session ${session} predates latest opened session ${latest}`)
  const label = [economicUnknown && !reportedMove ? 'ECONOMIC UNKNOWN' : null, incompleteCoverage ? 'INCOMPLETE COVERAGE' : null,
    (!economicUnknown || reportedMove) && sessionUnknown ? 'SESSION UNKNOWN' : null, agedSource ? 'AGED SOURCE' : null].filter(Boolean).join(' · ') || null
  return { tone: label ? 'warn' : 'ok', label, reason: bits.join(' · ') || null,
    incompleteCoverage, agedSource, economicUnknown, sessionUnknown, latestOpenSession: latest,
    change: reportedMove ? moveChange : economicUnknown ? null : finite(overview?.today_change),
    pct: reportedMove ? (finite(move.change_pct) == null ? null : Math.round((move.change_pct as number) * 100) / 100) : economicUnknown ? null : finite(overview?.today_pct),
    sessionDate: session, sessionSource: (reportedMove ? move.session_source : pnl.session_source as string | undefined) ?? null,
    reportedMove, moveNote: reportedMove ? (move.note ?? 'market-day move; economic day P&L unproven') : null }
}
