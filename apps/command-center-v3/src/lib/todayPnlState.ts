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
  const missing = Array.isArray(pnl.missing_accounts) ? pnl.missing_accounts : null
  const partial = Array.isArray(pnl.partial_accounts) ? pnl.partial_accounts : null
  const incompleteCoverage = (missing?.length ?? 0) > 0 || (partial?.length ?? 0) > 0
  const market = (Object.prototype.hasOwnProperty.call(pnl, 'market_session') ? pnl.market_session : overview?.market_session) as TodayPnlPayload['market_session']
  const latest = market?.status === 'KNOWN' ? sessionDate(market.latest_open_session) : null
  const session = sessionDate(pnl.session_date)
  const sessionUnknown = latest == null || session == null || session > latest
  const agedSource = latest != null && session != null && session < latest
  const bits: string[] = []
  if (economicUnknown) bits.push([pnl.gap?.reason ?? pnl.coverage_reason ?? 'Economic day proof unavailable', pnl.gap?.ticket].filter(Boolean).join(' · '))
  if (incompleteCoverage) bits.push(missing?.length ? `${missing.length} funded acct(s) did not report` : `partial: ${pnl.unknown_rows ?? 'unknown'} row(s) without a day change`)
  if (sessionUnknown) bits.push(session && latest && session > latest ? 'P&L session exceeds the latest proven open session' : 'P&L session or backend market-session reference is unknown')
  if (agedSource) bits.push(`P&L session ${session} predates latest opened session ${latest}`)
  const label = [economicUnknown ? 'ECONOMIC UNKNOWN' : null, incompleteCoverage ? 'INCOMPLETE COVERAGE' : null,
    !economicUnknown && sessionUnknown ? 'SESSION UNKNOWN' : null, agedSource ? 'AGED SOURCE' : null].filter(Boolean).join(' · ') || null
  return { tone: label ? 'warn' : 'ok', label, reason: bits.join(' · ') || null,
    incompleteCoverage, agedSource, economicUnknown, sessionUnknown, latestOpenSession: latest }
}
