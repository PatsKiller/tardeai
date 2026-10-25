/** HoldingHistory@v1 read-only presentation. Financial aggregates belong to the server. */
export const HISTORY_API = '/api/v3/data-broker/holding-history'
export const HISTORY_SORTS = [
  { id: 'round_trips', label: 'Most round trips' },
  { id: 'realized', label: 'Most realized' },
  { id: 'held_now', label: 'Held now' },
] as const
export type HistorySort = typeof HISTORY_SORTS[number]['id']
export type Gap = { source?: string | null; reason?: string | null; symbol?: string | null; date?: string | null; account_id?: string | null; account_label?: string | null; as_of?: string | null; [key: string]: unknown }
export type Coverage = { status?: string; reasons?: (string | Gap)[]; missing_sources?: string[]; missing_reasons?: Record<string, string> }
export type HistoryAccount = { account_id?: string | null; account_label?: string | null; held_quantity?: number | null; as_of?: string | null }
export type HistorySymbol = {
  symbol: string; company_name: string | null; company_missing_reason?: string | null; account_count: number | null
  accounts: HistoryAccount[]; round_trip_count: number | null; realized_pl: number | null; known_realized_pl: number | null
  held_now: boolean | null; basis_unknown: boolean; gaps: Gap[]
}
export type HistoryStats = {
  times_held: number | null; known_holding_stretches: number | null; round_trip_count: number | null
  win_rate_pct: number | null; realized_pl: number | null; known_realized_pl: number | null
  avg_hold_days: number | null; median_hold_days: number | null; best_trip_pct: number | null; worst_trip_pct: number | null; coverage?: Coverage
}
export type HoldingSegment = {
  start_date?: string | null; end_date?: string | null; start_at?: string | null; end_at?: string | null
  status?: string | null; source?: string | null; precision?: string | null; gaps?: Gap[]
}
export type AccountSegments = { account_id?: string | null; account_label?: string | null; as_of?: string | null; segments: HoldingSegment[] }
export type HistoryTrip = {
  trade_id: string | null; symbol?: string; account_id?: string | null; account_label: string | null
  entry_at?: string | null; exit_at?: string | null; entry_date?: string | null; exit_date?: string | null
  entry_price: number | null; exit_price: number | null; shares: number | null; realized_pl: number | null; return_pct: number | null
  hold_days: number | null; hold_days_basis?: string | null; basis_unknown?: boolean; basis_reason?: string | null
  source: string | null; provenance?: unknown; gaps?: Gap[]
}
export type HistoryDetail = { symbol: string; company_name: string | null; company_missing_reason?: string | null; stats: HistoryStats; account_segments: AccountSegments[]; trips: HistoryTrip[]; gaps: Gap[] }
export type HoldingHistoryPayload = {
  schema: 'HoldingHistory@v1'; ok: boolean; as_of: string | null
  range: { start_date: string | null; end_date: string | null; basis?: string; coverage?: Coverage }
  symbols: HistorySymbol[]; detail: HistoryDetail | null; account_options?: { id: string; label: string }[]; gaps: Gap[]
  provider_calls: number; writes: number; read_only: boolean
}
const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v)
export const finite = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v)
const optionalNumber = (v: unknown) => v === null || finite(v)
const textOrNull = (v: unknown) => v == null || typeof v === 'string'
const gapRows = (v: unknown): boolean => Array.isArray(v) && v.every(g => object(g) && textOrNull(g.reason) && textOrNull(g.source))
const coverageShape = (v: unknown): boolean => v == null || (object(v)
  && (v.reasons == null || (Array.isArray(v.reasons) && v.reasons.every(r => typeof r === 'string' || (object(r) && textOrNull(r.reason)))))
  && (v.missing_sources == null || (Array.isArray(v.missing_sources) && v.missing_sources.every(r => typeof r === 'string')))
  && (v.missing_reasons == null || (object(v.missing_reasons) && Object.values(v.missing_reasons).every(r => typeof r === 'string'))))
export function sortFrom(value: string | null): HistorySort { return HISTORY_SORTS.find(s => s.id === value)?.id || 'round_trips' }
export function historyUrl(symbol: string | null, sort: HistorySort) {
  const q = new URLSearchParams({ range: 'all', sort })
  if (symbol?.trim()) q.set('symbol', symbol.trim().toUpperCase())
  return `${HISTORY_API}?${q}`
}
export function decodeHistory(raw: unknown): HoldingHistoryPayload | null {
  const x = object(raw) && object(raw.data) ? raw.data : raw
  if (!object(x) || x.schema !== 'HoldingHistory@v1' || typeof x.ok !== 'boolean' || !Array.isArray(x.symbols)
    || !object(x.range) || !textOrNull(x.as_of) || !textOrNull(x.range.start_date) || !textOrNull(x.range.end_date) || !coverageShape(x.range.coverage) || !gapRows(x.gaps) || x.read_only !== true || x.provider_calls !== 0 || x.writes !== 0) return null
  if (x.account_options != null && (!Array.isArray(x.account_options) || !x.account_options.every(a => object(a) && typeof a.id === 'string' && typeof a.label === 'string'))) return null
  if (!x.symbols.every(s => object(s) && typeof s.symbol === 'string' && textOrNull(s.company_name) && optionalNumber(s.account_count)
    && optionalNumber(s.round_trip_count) && optionalNumber(s.realized_pl) && optionalNumber(s.known_realized_pl)
    && (s.held_now === null || typeof s.held_now === 'boolean') && Array.isArray(s.accounts)
    && s.accounts.every(a => object(a) && textOrNull(a.account_label) && optionalNumber(a.held_quantity)) && gapRows(s.gaps))) return null
  if (x.detail !== null && (!object(x.detail) || typeof x.detail.symbol !== 'string' || !object(x.detail.stats)
    || !Array.isArray(x.detail.account_segments) || !x.detail.account_segments.every(a => object(a) && textOrNull(a.account_label) && Array.isArray(a.segments)
      && a.segments.every(g => object(g) && ['start_date', 'end_date', 'start_at', 'end_at', 'status', 'source', 'precision'].every(k => textOrNull(g[k])) && (g.gaps == null || gapRows(g.gaps))))
    || !coverageShape(x.detail.stats.coverage) || !Array.isArray(x.detail.trips) || !x.detail.trips.every(t => object(t) && textOrNull(t.account_label) && textOrNull(t.source) && (t.gaps == null || gapRows(t.gaps))) || !gapRows(x.detail.gaps))) return null
  if (object(x.detail) && object(x.detail.stats) && !['times_held', 'known_holding_stretches', 'round_trip_count', 'win_rate_pct', 'realized_pl', 'known_realized_pl', 'avg_hold_days', 'median_hold_days', 'best_trip_pct', 'worst_trip_pct'].every(k => optionalNumber((x.detail as Record<string, unknown> & { stats: Record<string, unknown> }).stats[k]))) return null
  if (object(x.detail) && Array.isArray(x.detail.trips) && !x.detail.trips.every(t => object(t) && (t.trade_id === null || typeof t.trade_id === 'string') && ['entry_price', 'exit_price', 'shares', 'realized_pl', 'return_pct', 'hold_days'].every(k => optionalNumber(t[k])))) return null
  return x as unknown as HoldingHistoryPayload
}
export function numberText(v: unknown, digits = 2): string { return finite(v) ? new Intl.NumberFormat('en-US', { maximumFractionDigits: digits }).format(v) : '—' }
export function money(v: unknown): string { return finite(v) ? new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 2 }).format(v) : '—' }
export function percent(v: unknown): string { return finite(v) ? `${numberText(v)}%` : '—' }
export function dateText(v: unknown): string {
  if (typeof v !== 'string' || !v) return 'Date unavailable'
  if (/^\d{4}-\d{2}-\d{2}$/.test(v)) return Number.isFinite(Date.parse(v)) && new Date(v).toISOString().slice(0, 10) === v ? v : 'Invalid source date'
  if (!/(Z|[+-]\d{2}:\d{2})$/i.test(v) || !Number.isFinite(Date.parse(v))) return `${v} · timezone unavailable`
  return new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', year: 'numeric', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', timeZoneName: 'short' }).format(new Date(v))
}
export const reasonText = (value: unknown) => typeof value === 'string' && value ? value.replace(/_/g, ' ') : 'Reason not supplied by the source'
export function gapText(g: Gap | string): string { return typeof g === 'string' ? reasonText(g) : [g.symbol, g.account_label, g.date ? dateText(g.date) : null, g.source, reasonText(g.reason), g.as_of ? `as of ${dateText(g.as_of)}` : null].filter(Boolean).join(' · ') }
/** Resolve display names only through the server's public account-label map. */
export function namedGaps(gaps: Gap[], accounts: { id: string; label: string }[] = []): Gap[] {
  return gaps.map(g => ({ ...g, account_label: g.account_label || accounts.find(a => a.id === g.account_id)?.label || (g.account_id ? 'Account name unavailable' : null) }))
}
export function missingReason(coverage?: Coverage, key?: string): string {
  if (key && coverage?.missing_reasons?.[key]) return reasonText(coverage.missing_reasons[key])
  const reasons = coverage?.reasons?.map(gapText).filter(Boolean) || []
  return reasons.join(' · ') || (coverage?.missing_sources?.length ? `Missing source: ${coverage.missing_sources.join(', ')}` : 'Not supplied by holding history')
}
/** Geometry only: no financial/statistical calculation and no inferred observation dates. */
export function segmentGeometry(range: HoldingHistoryPayload['range'], segment: HoldingSegment) {
  const time = (v?: string | null) => v && (/^\d{4}-\d{2}-\d{2}$/.test(v) || /(Z|[+-]\d{2}:\d{2})$/i.test(v)) && dateText(v) !== 'Invalid source date' ? Date.parse(v) : NaN
  const start = time(range.start_date), end = time(range.end_date)
  const a = time(segment.start_date || segment.start_at), b = time(segment.end_date || segment.end_at)
  if (![start, end, a, b].every(Number.isFinite) || end <= start || b < a || b < start || a > end) return null
  const left = Math.max(0, Math.min(100, (a - start) / (end - start) * 100))
  const right = Math.max(left, Math.min(100, (b - start) / (end - start) * 100))
  return { left, width: right - left }
}
/** Expose only public provenance fields; never dump account identifiers or raw objects. */
export function provenanceText(value: unknown): string[] {
  const rows = Array.isArray(value) ? value : object(value) ? [value] : []
  return rows.filter(object).map(r => [r.source, r.table, typeof r.record_id === 'string' ? `Record ${r.record_id}` : null, r.writer, r.observed_at ? `Observed ${dateText(r.observed_at)}` : (r.as_of ? `As of ${dateText(r.as_of)}` : null)].filter(x => typeof x === 'string' && x).join(' · ')).filter(Boolean)
}
