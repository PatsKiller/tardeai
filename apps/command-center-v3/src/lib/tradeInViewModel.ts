/** Navigation and formatting over server facts. No business statistics or source lookups. */
export const TRADE_TABS = [
  ['journeys', 'Journeys'], ['calendar', 'Calendar'], ['replay', 'Replay'],
  ['history', 'Holding history'], ['classic', 'Journal (classic tabs)'],
] as const
export type TradeTab = typeof TRADE_TABS[number][0]

export function tradeTab(params: URLSearchParams, handoff = false): TradeTab {
  if (params.get('view') === 'classic') return 'classic'
  const tab = params.get('tab')
  if (TRADE_TABS.some(([key]) => key === tab)) return tab as TradeTab
  // Unknown tab names are the established Classic journal deep links (Options, Trades, ...).
  return tab || handoff ? 'classic' : 'journeys'
}
export function tabParams(params: URLSearchParams, tab: TradeTab): URLSearchParams {
  const next = new URLSearchParams(params)
  next.delete('view'); next.set('tab', tab)
  return next
}
export function tradeLink(tab: TradeTab, input: { trade_id?: string; symbol?: string } = {}): string {
  const params = new URLSearchParams({ tab })
  if (input.trade_id) params.set('trade', input.trade_id)
  if (input.symbol) params.set('symbol', input.symbol)
  return `/journal?${params}`
}
export function monthShift(month: string, delta: number): string {
  if (!/^\d{4}-(0[1-9]|1[0-2])$/.test(month)) return month
  const [year, m] = month.split('-').map(Number)
  const d = new Date(Date.UTC(year, m - 1 + delta, 1))
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}`
}
export function etMonth(now: Date): string {
  const parts = new Intl.DateTimeFormat('en-CA', { timeZone: 'America/New_York', year: 'numeric', month: '2-digit' }).formatToParts(now)
  return `${parts.find(p => p.type === 'year')?.value}-${parts.find(p => p.type === 'month')?.value}`
}
export function monthLabel(month: string): string {
  return /^\d{4}-(0[1-9]|1[0-2])$/.test(month) ? new Intl.DateTimeFormat('en-US', { timeZone: 'UTC', year: 'numeric', month: 'long' }).format(new Date(`${month}-01T12:00:00Z`)) : 'Month unavailable'
}
export function serverNumber(value: number | null | undefined, suffix = ''): string {
  return value == null || !Number.isFinite(value) ? '—' : `${value.toLocaleString('en-US')}${suffix}`
}
export function serverMoney(value: number | null | undefined): string {
  return value == null || !Number.isFinite(value) ? '—' : new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', signDisplay: 'exceptZero', maximumFractionDigits: 2 }).format(value)
}

/** New TradeInView replay is always addressed by recorded identity and reads stored bars only. */
export function storedReplayPath(tradeId: string, interval: string): string {
  return `/api/v2/trade-chart?${new URLSearchParams({ trade_id: tradeId, stored_only: '1', interval })}`
}

export type SourceGap = { source: string; reason: string }
export type Coverage = { status: string; missing_sources?: string[]; reasons?: string[] }
export type NormalisedTrip = {
  trade_id: string; symbol: string; account_id: string | null; account_label: string | null
  entry_at: string | null; exit_at: string | null; entry_date: string | null; exit_date: string | null
  entry_price: number | null; exit_price: number | null; shares: number | null; realized_pl: number | null
  return_pct: number | null; hold_days: number | null; hold_days_basis: string | null; basis_unknown: boolean; basis_reason: string | null
  source: string; provenance: unknown[]
}
export type CalendarEvent = { id: string; type: string; symbol: string | null; title: string; date: string; source: string | null; source_ref: string | null; as_of: string | null; missing_reason: string | null; source_event_type?: string | null; date_basis?: string | null }
export type CalendarDay = {
  date: string; realized_pl: number | null; known_realized_pl: number | null; trade_count: number | null; known_trade_count: number
  unpriced_trade_count: number; symbols: { symbol: string; realized_pl: number | null; known_realized_pl: number | null; trade_count: number | null }[]
  trades: NormalisedTrip[]; events: CalendarEvent[]; heat_intensity: number | null; coverage: Coverage
}
export type TradeCalendarPayload = {
  schema: 'TradeCalendar@v1'; ok: boolean; as_of: string; month: string; account: string | null; names: 'held' | 'held_watch'
  summary: { realized_pl: number | null; known_realized_pl: number | null; trade_count: number | null; known_trade_count: number; green_days: number | null; active_days?: number | null; unpriced_trade_count: number; coverage: Coverage }
  days: CalendarDay[]; weeks: { start_date: string; end_date: string; days: (string | null)[]; realized_pl: number | null; known_realized_pl: number | null; trade_count: number | null; known_trade_count: number; coverage: Coverage }[]
  non_grid_days?: CalendarDay[]; events: CalendarEvent[]; account_options: { id: string; label: string }[]; gaps: SourceGap[]
}
export type TradeReplayPayload = {
  schema: 'TradeReplay@v1'; trade?: NormalisedTrip | null; ok: boolean; as_of: string; trade_id: string; symbol: string; account_id: string | null; account_label: string | null
  interval: string; available_intervals: string[]; kind: 'candles' | 'closes' | 'none'
  bars: { time: string; t: number; open?: number | null; high?: number | null; low?: number | null; close: number; volume?: number | null }[]
  markers: { time: string; t: number; kind: 'buy' | 'sell' | 'stop' | 'cio'; label: string; price: number | null; source: string; at: string | null }[]
  stats: { max_gain_pct: number | null; max_drawdown_pct: number | null; metrics_basis: string; metrics_missing_reason: string | null; exit_kind: 'stop' | 'target' | 'manual' | 'unknown'; exit_label: string; exit_basis: string; coach_note: string | null }
  source: { table: string | null; as_of: string | null; stored_only: boolean; bar_basis: string }; gaps: SourceGap[]
}
const object = (v: unknown): v is Record<string, any> => !!v && typeof v === 'object' && !Array.isArray(v)
const numeric = (v: unknown) => v === null || typeof v === 'number' && Number.isFinite(v)
const objects = (v: unknown): v is Record<string, any>[] => Array.isArray(v) && v.every(object)
const coverage = (v: unknown) => object(v) && typeof v.status === 'string'
  && (v.reasons === undefined || Array.isArray(v.reasons) && v.reasons.every((x: unknown) => typeof x === 'string'))
  && (v.missing_sources === undefined || Array.isArray(v.missing_sources) && v.missing_sources.every((x: unknown) => typeof x === 'string'))
const gapList = (v: unknown) => objects(v) && v.every(g => typeof g.source === 'string' && typeof g.reason === 'string')
export function calendarPayload(raw: any, expected?: { month: string; account: string; names: string }): TradeCalendarPayload | null {
  const d = raw?.data ?? raw
  if (!object(d) || d.schema !== 'TradeCalendar@v1' || !object(d.summary) || !coverage(d.summary.coverage)
      || !objects(d.days) || !objects(d.weeks) || !objects(d.events) || !objects(d.account_options) || !gapList(d.gaps)) return null
  if (expected && (d.month !== expected.month || (d.account ?? '') !== expected.account || d.names !== expected.names)) return null
  if (!['realized_pl','trade_count','green_days'].every(k => numeric(d.summary[k]))) return null
  if (!d.days.every(day => typeof day.date === 'string' && numeric(day.realized_pl) && numeric(day.trade_count)
      && objects(day.symbols) && objects(day.trades) && objects(day.events) && coverage(day.coverage))) return null
  if (!d.weeks.every(week => typeof week.start_date === 'string' && Array.isArray(week.days) && week.days.length === 5
      && week.days.every((day: unknown) => day === null || typeof day === 'string') && numeric(week.realized_pl) && coverage(week.coverage))) return null
  if (!d.events.every(e => typeof e.id === 'string' && typeof e.type === 'string' && typeof e.title === 'string' && typeof e.date === 'string')
      || !d.account_options.every(a => typeof a.id === 'string' && typeof a.label === 'string')) return null
  return d as TradeCalendarPayload
}
export function replayPayload(raw: any, expected?: { trade_id: string; interval: string }): TradeReplayPayload | null {
  const d = raw?.data ?? raw
  if (!object(d) || d.schema !== 'TradeReplay@v1' || !objects(d.bars) || !objects(d.markers)
      || !Array.isArray(d.available_intervals) || !d.available_intervals.every((x: unknown) => typeof x === 'string')
      || !object(d.stats) || !object(d.source) || d.source.stored_only !== true || !gapList(d.gaps)
      || !['candles','closes','none'].includes(d.kind)) return null
  if (expected && (d.trade_id !== expected.trade_id || d.interval !== expected.interval)) return null
  if (d.trade != null && (!object(d.trade) || d.trade.trade_id !== d.trade_id)) return null
  if (!['max_gain_pct','max_drawdown_pct'].every(k => numeric(d.stats[k])) || typeof d.stats.metrics_basis !== 'string'
      || typeof d.stats.exit_label !== 'string' || typeof d.stats.exit_basis !== 'string'
      || !['stop','target','manual','unknown'].includes(d.stats.exit_kind)
      || d.stats.coach_note !== null && typeof d.stats.coach_note !== 'string') return null
  // Chart libraries require numeric source points. Missing OHLC is never back-filled from a close.
  if (!d.bars.every(bar => typeof bar.time === 'string' && typeof bar.close === 'number' && Number.isFinite(bar.close) && bar.close > 0
      && (d.kind !== 'candles' || ['open','high','low'].every(k => typeof bar[k] === 'number' && Number.isFinite(bar[k]) && bar[k] > 0)))) return null
  if (!d.markers.every(m => typeof m.time === 'string' && ['buy','sell','stop','cio'].includes(m.kind) && typeof m.label === 'string' && numeric(m.price))) return null
  return d as TradeReplayPayload
}
export function responseReason(raw: any): string | null {
  const d = raw?.data ?? raw
  return typeof d?.reason === 'string' ? d.reason : typeof d?.error === 'string' ? d.error : null
}
export function coverageReason(coverage?: Coverage | null): string {
  return coverage?.reasons?.join(' · ') || coverage?.missing_sources?.join(' · ')
    || (coverage?.status.toUpperCase() === 'COMPLETE' ? 'Source coverage: complete (server declaration)' : 'Source coverage unavailable')
}

/** Axis formatting only; retain stored price precision without manufacturing OHLC or performance metrics. */
export function replayPriceFormat(values: (number | null | undefined)[]): { type: 'price'; precision: number; minMove: number } {
  let precision = 2
  for (const value of values) {
    if (value == null || !Number.isFinite(value) || value <= 0) continue
    const [coefficient, exponent = '0'] = String(value).toLowerCase().split('e')
    precision = Math.max(precision, Math.min(16, (coefficient.split('.')[1]?.length || 0) - Number(exponent)))
  }
  return { type: 'price', precision, minMove: 10 ** -precision }
}

/** "Compare with a win" partners: CLOSED trips with a server-realized P/L above zero only. An open position's
 * unrealized gain is never a win, and there is no fallback to one when no closed winner exists. */
export const NO_CLOSED_WIN = 'No closed winning trip yet'
export function isClosedWin(t: { status?: string | null; pnl?: number | null } | null | undefined): boolean {
  return !!t && t.status === 'closed' && typeof t.pnl === 'number' && Number.isFinite(t.pnl) && t.pnl > 0
}
export function closedWinPartners<T extends { trade_id?: string | null; status?: string | null; pnl?: number | null }>(trades: T[], excludeId?: string | null): T[] {
  return trades.filter(t => isClosedWin(t) && t.trade_id !== excludeId)
}
