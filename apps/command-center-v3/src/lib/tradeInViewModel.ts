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
export type CalendarEvent = { id: string; type: string; symbol: string | null; title: string; date: string; source: string | null; source_ref: string | null; as_of: string | null; missing_reason: string | null; source_event_type?: string | null }
export type CalendarDay = {
  date: string; realized_pl: number | null; known_realized_pl: number | null; trade_count: number | null; known_trade_count: number
  unpriced_trade_count: number; symbols: { symbol: string; realized_pl: number | null; known_realized_pl: number | null; trade_count: number | null }[]
  trades: NormalisedTrip[]; events: CalendarEvent[]; heat_intensity: number | null; coverage: Coverage
}
export type TradeCalendarPayload = {
  schema: 'TradeCalendar@v1'; ok: boolean; as_of: string; month: string; account: string | null; names: 'held' | 'held_watch'
  summary: { realized_pl: number | null; known_realized_pl: number | null; trade_count: number | null; known_trade_count: number; green_days: number | null; active_days?: number | null; unpriced_trade_count: number; coverage: Coverage }
  days: CalendarDay[]; weeks: { start_date: string; end_date: string; days: (string | null)[]; realized_pl: number | null; known_realized_pl: number | null; trade_count: number | null; known_trade_count: number; coverage: Coverage }[]
  events: CalendarEvent[]; account_options: { id: string; label: string }[]; gaps: SourceGap[]
}
export type TradeReplayPayload = {
  schema: 'TradeReplay@v1'; trade?: NormalisedTrip | null; ok: boolean; as_of: string; trade_id: string; symbol: string; account_id: string | null; account_label: string | null
  interval: string; available_intervals: string[]; kind: 'candles' | 'closes' | 'none'
  bars: { time: string; t: number; open?: number | null; high?: number | null; low?: number | null; close: number; volume?: number | null }[]
  markers: { time: string; t: number; kind: 'buy' | 'sell' | 'stop' | 'cio'; label: string; price: number | null; source: string; at: string | null }[]
  stats: { max_gain_pct: number | null; max_drawdown_pct: number | null; metrics_basis: string; metrics_missing_reason: string | null; exit_kind: 'stop' | 'target' | 'manual' | 'unknown'; exit_label: string; exit_basis: string; coach_note: string | null }
  source: { table: string | null; as_of: string | null; stored_only: boolean; bar_basis: string }; gaps: SourceGap[]
}
export function calendarPayload(raw: any): TradeCalendarPayload | null {
  const d = raw?.data ?? raw
  return d?.schema === 'TradeCalendar@v1' && Array.isArray(d.days) && Array.isArray(d.weeks) && d.summary && Array.isArray(d.events) && Array.isArray(d.account_options) && Array.isArray(d.gaps) ? d : null
}
export function replayPayload(raw: any): TradeReplayPayload | null {
  const d = raw?.data ?? raw
  return d?.schema === 'TradeReplay@v1' && Array.isArray(d.bars) && Array.isArray(d.available_intervals) && d.stats && d.source && Array.isArray(d.gaps) ? d : null
}
export function coverageReason(coverage?: Coverage | null): string {
  return coverage?.reasons?.join(' · ') || coverage?.missing_sources?.join(' · ') || 'Source coverage unavailable'
}
