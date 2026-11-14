/** Watch v002 list tabs (LQ-20261107-2993b): My List / Suggestions / Prospects.
 *
 *  Pure model over the curation body the server pages with `shape=list` (scripts/lib/site_payload_reads.read_curation):
 *  every list carries its own `as_of`; a list that cannot show one is UNKNOWN, an old one is STALE with its age, and a
 *  last-good body served by the stale-while-revalidate cache (`_swr`) shows that age. Nothing here is ever "green"
 *  without a timestamp. */

export const CURATION_API = '/api/v3/data-broker/watch-curation'
export const PROSPECTS_API = '/api/v3/data-broker/watch-prospects'
export const LIST_LIMIT = 25
/** Suggestions rank from a daily projection; My List / Prospects are composed per request. */
export const RANKING_MAX_AGE_S = 36 * 3600
export const COMPOSED_MAX_AGE_S = 15 * 60

export type ListKey = 'mine' | 'suggests' | 'prospects'
export type ListState = 'OK' | 'STALE' | 'UNKNOWN'
export type ListGrade = { state: ListState; ageS: number | null; label: string; basis: string; reason: string | null }
export type ListPaging = { total: number | null; returned: number; nextOffset: number | null; hasMore: boolean }

const asRec = (v: unknown): Record<string, any> | null => (v && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, any>) : null)

export function ageText(s: number | null): string {
  if (s === null || !Number.isFinite(s)) return 'age unknown'
  if (s < 90) return '<2 min'
  if (s < 5400) return `${Math.round(s / 60)} min`
  if (s < 172800) return `${Math.round(s / 3600)} h`
  return `${Math.round(s / 86400)} d`
}

/** Grade one list. `swr` is the body-level `_swr` stamp: a served last-good body is as old as the body, not as the
 *  moment it was composed. */
export function gradeList(asOf: unknown, basis: unknown, nowMs: number, opts: { maxAgeS: number; swr?: unknown } = { maxAgeS: COMPOSED_MAX_AGE_S }): ListGrade {
  const b = typeof basis === 'string' && basis ? basis : 'unspecified'
  const swr = asRec(opts.swr)
  const t = typeof asOf === 'string' ? Date.parse(asOf) : NaN
  if (!Number.isFinite(t)) return { state: 'UNKNOWN', ageS: null, label: 'UNKNOWN · no as_of', basis: b, reason: 'The list carries no usable as_of.' }
  let ageS = Math.round((nowMs - t) / 1000)
  if (ageS < -120) return { state: 'UNKNOWN', ageS: null, label: 'UNKNOWN · as_of in the future', basis: b, reason: 'as_of is later than this clock.' }
  ageS = Math.max(0, ageS)
  if (swr && typeof swr.age_s === 'number' && Number.isFinite(swr.age_s)) ageS = Math.max(ageS, Math.round(swr.age_s))
  const servedStale = !!(swr && swr.stale === true)
  if (servedStale || ageS > opts.maxAgeS) {
    return { state: 'STALE', ageS, label: `STALE · ${ageText(ageS)} old`, basis: b, reason: servedStale ? 'Last good body served while a refresh runs.' : `Older than ${ageText(opts.maxAgeS)}.` }
  }
  return { state: 'OK', ageS, label: `OK · ${ageText(ageS)} old`, basis: b, reason: null }
}

export function pagingOf(section: unknown): ListPaging {
  const p = asRec(asRec(section)?.pagination)
  const rows = asRec(section)?.rows
  const returned = typeof p?.returned === 'number' ? p.returned : Array.isArray(rows) ? rows.length : 0
  return {
    total: typeof p?.total === 'number' ? p.total : null,
    returned,
    nextOffset: typeof p?.next_offset === 'number' ? p.next_offset : null,
    hasMore: p?.has_more === true,
  }
}

export function pagingText(p: ListPaging, offset = 0): string {
  if (p.total === null) return `${p.returned} shown · total unknown`
  if (p.total === 0) return 'none'
  return `${offset + 1}–${offset + p.returned} of ${p.total}`
}

export type ListRowView = {
  symbol: string
  company: string | null
  stage: string
  conviction: number | null
  starred: boolean
  held: string | null
  why: string
  nextAction: string | null
  dismissed: boolean
  detailHref: string
}

export function detailHref(symbol: string): string {
  return `/watch/intelligence/${encodeURIComponent(symbol)}`
}

export function rowView(r: any, dismissed: ReadonlySet<string> = new Set()): ListRowView | null {
  const o = asRec(r)
  const symbol = typeof o?.symbol === 'string' ? o.symbol.trim().toUpperCase() : ''
  if (!o || !symbol) return null
  const state = o.position_state
  const held = state === 'held' ? 'Held' : state === 'formerly_held' ? 'Formerly held' : null
  const why = String(o.suggestion?.reason || o.why || o.summary || '').trim()
  return {
    symbol,
    company: typeof o.company === 'string' ? o.company : null,
    stage: String(o.stage || o.lane || ''),
    conviction: typeof o.conviction === 'number' ? o.conviction : null,
    starred: o.starred === true,
    held,
    why,
    nextAction: typeof o.next_action?.label === 'string' ? o.next_action.label : null,
    dismissed: dismissed.has(symbol),
    detailHref: detailHref(symbol),
  }
}

export function curationUrl(view: 'mine' | 'suggests', offset: number): string {
  return `${CURATION_API}?view=${view}&shape=list&limit=${LIST_LIMIT}&offset=${Math.max(0, offset)}`
}

export function prospectsUrl(lane: string, offset: number): string {
  return `${PROSPECTS_API}?lane=${encodeURIComponent(lane)}&limit=${LIST_LIMIT}&offset=${Math.max(0, offset)}`
}

/** Grade the section of a curation body. */
export function gradeCuration(body: unknown, key: 'mine' | 'suggests', nowMs: number): ListGrade {
  const b = asRec(body)
  const section = asRec(b?.[key === 'mine' ? 'my_watchlist' : 'suggests'])
  const maxAgeS = key === 'suggests' ? RANKING_MAX_AGE_S : COMPOSED_MAX_AGE_S
  return gradeList(section?.as_of, section?.as_of_basis, nowMs, { maxAgeS, swr: b?._swr })
}

export function gradeProspects(body: unknown, nowMs: number): ListGrade {
  const b = asRec(body)
  return gradeList(b?.generated_at, 'composed_at', nowMs, { maxAgeS: COMPOSED_MAX_AGE_S, swr: b?._swr })
}

export type DismissedItem = { symbol: string; reason: string | null; until: string | null }

export function dismissedSet(body: unknown): { symbols: Set<string>; items: DismissedItem[]; status: string } {
  const s = asRec(asRec(body)?.suggests)
  const list = Array.isArray(s?.dismissed) ? s!.dismissed : []
  const items = list
    .map((d: any) => ({ symbol: String(d?.symbol || '').toUpperCase(), reason: typeof d?.reason === 'string' ? d.reason : null, until: typeof d?.until === 'string' ? d.until : null }))
    .filter((d: DismissedItem) => d.symbol)
  return { symbols: new Set(items.map((d: DismissedItem) => d.symbol)), items, status: String(s?.dismissed_status || 'unknown') }
}
