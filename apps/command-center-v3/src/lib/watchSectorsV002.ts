/** OBS-W6-a — the Watch › Sectors tab reads the sector momentum/strength projection, not a taxonomy count.
 *
 *  Operator (11:43 ET, R6 91135d7fb): "Sectors currently only raw taxonomy counts, no measured momentum projection
 *  ('UNKNOWN No sector momentum/strength projection exists'), 5 alphabetical names per group, no industries/research/
 *  universe mapping navigation."
 *
 *  Producer: `GET /api/v2/sectors/monitor` (scripts/lib/sectors_monitor.py), provider-free on GET. The tab used to read
 *  `/api/v2/watch/sectors`, which is a constituent-count helper for a dropdown — its "sample" is five alphabetical
 *  symbols per provider label, which is exactly what the operator saw. Nothing here composes a number: every field is
 *  read from the projection, and a field the read does not state is "not stated", never 0, never "neutral".
 *
 *  The one trap this unit exists to encode: the payload has TWO clocks. The envelope `as_of`/`age_hours` is the MARKET
 *  QUOTE envelope (minutes old); the sector momentum/RS clock is `rs_as_of` (a daily close, typically a day old). A fresh
 *  quote must never make the momentum look fresh, and a stale quote must not make the momentum look stale.
 */

import { ageText, closeInstantMs, etText } from './watchSetupsV002.ts'

/** The momentum/strength projection. `/api/v2/watch/sectors` is NOT this: it lists provider labels and counts. */
export const SECTORS_MONITOR_API = '/api/v2/sectors/monitor'

export const SECTORS_TWO_CLOCKS =
  'Two clocks: the envelope time is the market-quote clock; sector momentum and relative strength run on the daily '
  + 'close (rs_as_of). A fresh quote does not make the momentum fresh.'

/** The industries/names descent lives on the Defense desk. It takes no sector in the URL today, so the sector cannot be
 *  preselected from here — said on the surface rather than hidden behind a link that silently lands on the first sector. */
export const INDUSTRIES_LINK_NOTE =
  'Industries and names for a sector are on the Defense desk. That page does not accept a sector in its address today, '
  + 'so this link opens it at its default sector.'

const rec = (v: unknown): Record<string, any> | null => (v && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, any>) : null)
const num = (v: unknown): number | null => (v === null || v === undefined || v === '' || !Number.isFinite(Number(v)) ? null : Number(v))
const str = (v: unknown): string | null => (typeof v === 'string' && v.trim() ? v.trim() : null)

export type SectorLeader = { symbol: string; rs20: number | null }
export type SectorSignal = {
  sector: string
  etf: string | null
  /** The projection's own state word (leading / neutral / lagging / weakening). Null when the read does not state one. */
  momentum: string | null
  /** The sector momentum/RS date for THIS row — never the envelope's quote clock. */
  momentumAsOf: string | null
  rs5: number | null; rs20: number | null; rs60: number | null
  changePct: number | null
  /** The row's own quote time. The monitor states quote age per row, not per payload. */
  quoteAsOf: string | null
  relStrength: number | null
  constituents: number | null
  /** Screened setups after the canonical CIO avoid filter. Null when the read states a gap — never rendered as 0. */
  setups: number | null
  setupsGap: string | null
  leaders: SectorLeader[]
  leadersBasis: string | null
  leadersGap: string | null
  bookWeightPct: number | null
  bookFlag: string | null
  watched: boolean
  directive: string | null
  stale: boolean
  sourceAgeDays: number | null
  /** Recommendation eligibility as the producer states it. Null = the read did not state it. */
  eligible: boolean | null
  freshnessGap: string | null
}

export function sectorSignals(body: unknown): SectorSignal[] {
  const rows = (body as any)?.sectors
  if (!Array.isArray(rows)) return []
  return rows.flatMap((r: any) => {
    const sector = str(r?.sector)
    if (!sector) return []
    const leaders = Array.isArray(r?.leaders)
      ? r.leaders.flatMap((l: any) => (str(l?.symbol) ? [{ symbol: String(l.symbol), rs20: num(l.rs20) }] : []))
      : []
    return [{
      sector,
      etf: str(r?.etf),
      momentum: str(r?.momentum),
      momentumAsOf: str(r?.as_of),
      rs5: num(r?.rs5), rs20: num(r?.rs20), rs60: num(r?.rs60),
      changePct: num(r?.etf_change_pct),
      quoteAsOf: str(r?.quote_as_of),
      relStrength: num(r?.rel_strength),
      constituents: num(r?.constituent_count),
      setups: num(r?.setup_count),
      setupsGap: str(r?.candidate_gap),
      leaders,
      leadersBasis: str(r?.leaders_basis),
      leadersGap: str(r?.leaders_gap),
      bookWeightPct: num(r?.book_weight_pct),
      bookFlag: str(r?.book_flag),
      watched: r?.is_watched === true,
      // REVIEW-OBS-W6 F2: the producer states a directive as an OBJECT ({id, label}) for 11/11 watched rows in the
      // measured read; `str()` returned null for it, so every watching chip lost its label. The label is read first,
      // and a bare string is still accepted for shape drift.
      directive: str(rec(r?.directive)?.label) ?? str(r?.directive),
      stale: r?.stale === true,
      sourceAgeDays: num(r?.source_age_days),
      eligible: typeof r?.recommendation_eligible === 'boolean' ? r.recommendation_eligible : null,
      freshnessGap: str(r?.freshness_gap),
    }]
  })
}

export type FeedClock = { asOf: string | null; ageS: number | null; stale: boolean | null; staleAfterH: number | null; gap: string | null }
export type SectorClock = {
  /** The sector momentum/RS date — the clock the momentum numbers actually run on. */
  momentumAsOf: string | null
  /** The market-quote envelope time. Print it with the quotes, never as "sector data updated". */
  quotesAsOf: string | null
  quotes: FeedClock
  rs: FeedClock
  postureBasis: string | null
}
/** The producer renders a daily-close date as THAT DATE'S UTC MIDNIGHT (`feeds.sector_rs_daily.as_of =
 *  "2026-11-13T00:00:00+00:00"`, measured 2026-11-14). Parsed as an instant that is 20–21 h before the 16:00 ET close
 *  the tab grades, so the printed momentum age (43 h) exceeded the tab's own 36 h SLA under a chip graded OK · 22 h —
 *  REVIEW-OBS-W6 F1. A daily-close feed's date is read as that session's close, the same instant ``gradeSectors`` uses. */
const UTC_MIDNIGHT = /^\d{4}-\d{2}-\d{2}T00:00:00(?:\.0+)?(?:Z|\+00:00)$/
function dailyCloseMs(asOf: string | null): number {
  if (!asOf) return NaN
  const day = DATE_ONLY.test(asOf) ? asOf : (UTC_MIDNIGHT.test(asOf) ? asOf.slice(0, 10) : '')
  return day ? closeInstantMs(day) : NaN
}
function feedClock(feed: unknown, nowMs: number, dailyClose = false): FeedClock {
  const f = rec(feed)
  const asOf = str(f?.as_of)
  const closeT = dailyClose ? dailyCloseMs(asOf) : NaN
  const t = Number.isFinite(closeT) ? closeT : (asOf ? Date.parse(asOf) : NaN)
  const hours = num(f?.age_hours)
  return {
    asOf,
    ageS: Number.isFinite(t) ? Math.max(0, Math.round((nowMs - t) / 1000)) : (hours === null ? null : Math.round(hours * 3600)),
    stale: typeof f?.stale === 'boolean' ? f.stale : null,
    staleAfterH: num(f?.stale_after_hours),
    gap: str(f?.gap),
  }
}
export function sectorClock(body: unknown, nowMs: number): SectorClock {
  const b = body as any
  const feeds = rec(b?.feeds)
  return {
    momentumAsOf: str(b?.rs_as_of),
    quotesAsOf: str(b?.as_of),
    quotes: feedClock(feeds?.market_quotes ?? b, nowMs),
    rs: feedClock(feeds?.sector_rs_daily, nowMs, true),
    postureBasis: str(b?.posture_basis),
  }
}

/** The payload's own field ledger. Only what the read states is returned; nothing is reconstructed from the rows. */
export type SectorLedger = {
  total: number | null
  staleTotal: number | null
  staleSlaDays: number | null
  coverageN: number | null
  coverageTotal: number | null
  /** The read's own quality verdict word, when the ledger carries one. */
  quality: string | null
  /** Named when the ledger block itself failed to build — the read then says nothing about coverage. */
  error: string | null
  rowsInRead: number
  /** A row count that disagrees with the ledger's own total. The country guard: a consumer must not count its own rows
   *  as "the sectors" when the projection says otherwise. */
  rowDisagreement: string | null
  gap: string | null
  legend: string | null
}
export function sectorLedger(body: unknown): SectorLedger {
  const b = body as any
  const q = rec(b?.data_quality)
  const led = rec(q?.ledger)
  const qq = rec(led?.quality) ?? rec(q?.quality)
  const quality = str(qq?.level) ?? str(qq?.state) ?? (typeof q?.quality === 'string' ? q.quality : null)
  const total = num(q?.sectors_total)
  const rowsInRead = Array.isArray(b?.sectors) ? b.sectors.length : 0
  return {
    total,
    staleTotal: num(q?.sectors_stale),
    staleSlaDays: num(q?.stale_sla_days),
    coverageN: num(led?.coverage_n),
    coverageTotal: num(led?.coverage_total),
    quality,
    error: str(q?.error),
    rowsInRead,
    rowDisagreement: total !== null && total !== rowsInRead
      ? `the ledger counts ${total} sectors, this read carries ${rowsInRead} rows`
      : null,
    gap: str(b?.gap),
    legend: str(b?.legend),
  }
}

/** Formatting helpers. Pure strings from stated fields only. */
const signed = (v: number | null): string => (v === null ? '' : v > 0 ? `+${v}` : String(v))
/** Signed relative-strength label, exported so a linked leader name carries the same number the text does. */
export const signedNum = (v: number | null): string => signed(v)
/** Two decimals at most, and no padding: a stated 13.6 is printed 13.6, not 13.60. */
const num2 = (v: number): string => String(Math.round(v * 100) / 100)

const DATE_ONLY = /^\d{4}-\d{2}-\d{2}$/
/** A date-only stamp has no clock. Parsing it as an instant would put it at UTC midnight and print "7:00 PM the previous
 *  day" in ET — a time the producer never stated. So a date is printed as a date, and its basis (daily close) is named. */
export function dayText(v: string | null): string | null {
  if (!v) return null
  if (DATE_ONLY.test(v)) {
    const t = Date.parse(`${v}T12:00:00Z`)
    return Number.isFinite(t)
      ? new Intl.DateTimeFormat('en-US', { timeZone: 'UTC', month: 'short', day: 'numeric', year: 'numeric' }).format(new Date(t))
      : null
  }
  return etText(v)
}
export function momentumText(r: Pick<SectorSignal, 'momentum' | 'momentumAsOf'>): string {
  if (!r.momentum) return 'momentum not stated in this read'
  const when = dayText(r.momentumAsOf)
  return when
    ? `${r.momentum} · as of ${when}${r.momentumAsOf && DATE_ONLY.test(r.momentumAsOf) ? ' (daily close, no clock stated)' : ''}`
    : `${r.momentum} · momentum time not stated`
}
export function rsText(r: Pick<SectorSignal, 'rs5' | 'rs20' | 'rs60'>): string {
  const parts: string[] = []
  if (r.rs5 !== null) parts.push(`5d ${signed(r.rs5)}`)
  if (r.rs20 !== null) parts.push(`20d ${signed(r.rs20)}`)
  if (r.rs60 !== null) parts.push(`60d ${signed(r.rs60)}`)
  return parts.length ? `RS vs SPY ${parts.join(' / ')}` : 'relative strength not stated'
}
export function quoteText(r: Pick<SectorSignal, 'changePct' | 'quoteAsOf' | 'etf'>, nowMs: number): string {
  if (r.changePct === null) return 'ETF move not stated'
  const pct = `${signed(Math.round(r.changePct * 100) / 100)} %`
  const t = r.quoteAsOf ? Date.parse(r.quoteAsOf) : NaN
  if (!Number.isFinite(t)) return `ETF ${pct} · quote time not stated (age unknown)`
  const age = Math.max(0, Math.round((nowMs - t) / 1000))
  return `ETF ${pct} at ${etText(r.quoteAsOf)} (${ageText(age)} old)`
}
export function setupsText(r: Pick<SectorSignal, 'setups' | 'setupsGap'>): string {
  if (r.setups !== null) return `${r.setups} screened setup${r.setups === 1 ? '' : 's'}`
  return r.setupsGap ? `setups unavailable — ${r.setupsGap}` : 'setups not stated in this read'
}
export function leadersText(r: Pick<SectorSignal, 'leaders' | 'leadersBasis' | 'leadersGap'>): string {
  if (r.leaders.length) {
    const names = r.leaders.map(l => (l.rs20 === null ? l.symbol : `${l.symbol} ${signed(l.rs20)}`)).join(', ')
    return `leaders ${names}${r.leadersBasis ? ` (${r.leadersBasis})` : ''}`
  }
  return r.leadersGap ? `leaders not measured — ${r.leadersGap}` : 'leaders not stated in this read'
}
export function bookText(r: Pick<SectorSignal, 'bookWeightPct' | 'bookFlag'>): string {
  if (r.bookWeightPct === null) return 'book weight not stated'
  const heavy = r.bookFlag === 'overweight_lagging'
    ? ' · overweight a lagging sector'
    : ''
  return `book ${num2(r.bookWeightPct)} %${heavy}`
}
export function eligibilityText(r: Pick<SectorSignal, 'eligible' | 'stale' | 'sourceAgeDays' | 'freshnessGap'>): string {
  const age = r.sourceAgeDays !== null ? ` (${num2(r.sourceAgeDays)} d old)` : ''
  if (r.eligible === false) return `not eligible to originate a recommendation${age}${r.freshnessGap ? ` — ${r.freshnessGap}` : ''}`
  if (r.eligible === true) return r.stale ? `eligible, but flagged stale${age}` : 'eligible to originate a recommendation'
  return r.stale ? `flagged stale${age}` : 'eligibility not stated in this read'
}

/** One row, one line, for a reader who does not open anything. */
export function sectorLine(r: SectorSignal, nowMs: number): string {
  return [
    r.etf ? `${r.sector} (${r.etf})` : r.sector,
    momentumText(r), rsText(r), quoteText(r, nowMs), setupsText(r), bookText(r), eligibilityText(r),
  ].join(' · ')
}
