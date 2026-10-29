/** Pure labels over shared stored evidence. No prices, calendars, fetches or records are created here. */
import { businessDateToSessionInstant, etCalendarDate, latestSessionDate } from './observationEnvelope.ts'
import type { WatchMarketField } from './watchListsModel.ts'

export function marketAmount(value: number | null): string {
  if (value == null || !Number.isFinite(value) || value <= 0) return '—'
  if (value >= 1) return `$${value.toFixed(2)}`
  const text = value.toLocaleString('en-US', { useGrouping: false, minimumFractionDigits: 2, maximumFractionDigits: 20 })
  return `$${Number(text) === 0 ? value.toExponential(3) : text}`
}

function instant(value: string | null): Date | null {
  if (!value || !/T.*(?:Z|[+-]\d\d:\d\d)$/.test(value)) return null
  const at = new Date(value)
  return Number.isFinite(at.getTime()) ? at : null
}

export function marketObserved(value: string | null): string {
  if (!value) return 'Observation time unknown'
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return `As of ${value} · closed session`
  const at = instant(value)
  if (!at) return 'Observation time unknown'
  return `As of ${new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', year: 'numeric', month: 'short',
    day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit', timeZoneName: 'short' }).format(at)}`
}

export function pricePresentation(field: WatchMarketField, now: Date, retained = false): { state: string; qualification: string | null } {
  if (field.value == null || !Number.isFinite(field.value) || field.value <= 0) return { state: 'Missing', qualification: null }
  if (retained) return { state: 'Last snapshot', qualification: null }
  const at = instant(field.as_of)
  // A latest-session label describes the stored observation, never upgrades its
  // backend freshness verdict or claims that an intraday LAST is an official close.
  if (at && at <= now && field.source && field.stale != null && field.freshness !== 'UNKNOWN' && field.freshness !== 'MISSING'
      && Number.isFinite(now.getTime())) {
    const latest = latestSessionDate(now)
    const close = businessDateToSessionInstant(latest)
    if (close && now >= close && etCalendarDate(at) === latest) {
      const identifiedClose = field.as_of_basis === 'session close'
      return { state: `Closed session · ${latest}${identifiedClose ? ' close' : ''}`,
        qualification: identifiedClose ? null : at < close ? 'Intraday observation' : 'After-hours observation' }
    }
  }
  return { state: !at || at > now || !field.source || field.freshness === 'UNKNOWN' || field.freshness === 'MISSING'
      || field.stale == null || !Number.isFinite(now.getTime()) ? 'Time / freshness unknown'
    : field.stale ? 'Stale' : 'Current', qualification: null }
}

export function levelSourceTag(field: WatchMarketField): string {
  if (field.source === 'watchlist_symbol_master') return 'Master'
  if (field.source === 'watchlist_strategy_cards') return 'Strategy'
  if (field.source?.startsWith('ui_prefs:portfolio.reentry.resistance')) return 'Closed session'
  return field.source_label || 'No reference'
}

export function levelText(kind: 'support' | 'resistance', field: WatchMarketField): string {
  if (field.broken_reference) return field.value != null
    ? `${marketAmount(field.broken_reference.value)} broken — nearest valid level: ${marketAmount(field.value)}`
    : `${marketAmount(field.broken_reference.value)} broken — none ${kind === 'support' ? 'below' : 'above'} price`
  return marketAmount(field.value)
}

function knownLevelTime(field: WatchMarketField): boolean {
  if (field.as_of_basis === 'observation timestamp') return instant(field.as_of) != null
  if (field.as_of_basis !== 'last closed session' || !field.as_of) return false
  const at = businessDateToSessionInstant(field.as_of)
  return at != null && etCalendarDate(at) === field.as_of
}

export function levelTimeUnknown(fields: WatchMarketField[]): boolean {
  return fields.some(field => (field.value != null || field.broken_reference != null) && !knownLevelTime(field))
}

/** The observation time for the stored levels, or the honest reason it is absent. The master source
 *  exposes no per-level timestamp, so a master level is "not timestamped by source" — never presented
 *  as a generic "time unknown" bug when the truth is that the source never carried one. */
export function levelTimeLabel(fields: WatchMarketField[]): string {
  const valued = fields.filter(f => (f.value != null || f.broken_reference != null))
  if (valued.length === 0) return 'not measured'
  if (valued.some(f => !knownLevelTime(f) && f.as_of_basis === 'not exposed by source')) return 'not timestamped by source'
  if (valued.some(f => !knownLevelTime(f))) return 'time unknown'
  return Array.from(new Set(valued.map(f => f.as_of).filter(Boolean))).join(' / ')
}
