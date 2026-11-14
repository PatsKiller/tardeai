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
  /** The curator's full-universe rank — a different number from conviction, never merged with it (WL-13). */
  rank: number | null
  starred: boolean
  held: string | null
  why: string
  nextAction: string | null
  dismissed: boolean
  detailHref: string
  /** Every reason the operator owns this name, as the server states them (`starred`, `personal_watchlist`, …). */
  membership: MemberBadge[]
  /** A signal that expired on a name that is yours: the server says review, never auto-remove (WL-08). */
  expiryReason: string | null
}

/** One operator-membership reason for a row. `label` is the server's own wording when it sends one. */
export type MemberBadge = { kind: string; label: string; at: string | null }

export function detailHref(symbol: string): string {
  return `/watch/intelligence/${encodeURIComponent(symbol)}`
}

const badgeOf = (v: unknown): MemberBadge | null => {
  const o = asRec(v)
  const kind = typeof o?.kind === 'string' ? o.kind : ''
  if (!kind) return null
  return {
    kind,
    label: typeof o?.label === 'string' && o.label ? o.label : kind.replace(/_/g, ' '),
    at: typeof o?.at === 'string' ? o.at : null,
  }
}

export function rowView(r: any, dismissed: ReadonlySet<string> = new Set()): ListRowView | null {
  const o = asRec(r)
  const symbol = typeof o?.symbol === 'string' ? o.symbol.trim().toUpperCase() : ''
  if (!o || !symbol) return null
  const state = o.position_state
  const held = state === 'held' ? 'Held' : state === 'formerly_held' ? 'Formerly held' : null
  const why = String(o.suggestion?.reason || o.why || o.summary || '').trim()
  const raw = Array.isArray(o.membership) ? o.membership : []
  return {
    symbol,
    company: typeof o.company === 'string' ? o.company : null,
    stage: String(o.stage || o.lane || ''),
    conviction: typeof o.conviction === 'number' ? o.conviction : null,
    rank: typeof o.universe_rank === 'number' ? o.universe_rank : null,
    starred: o.starred === true,
    held,
    why,
    nextAction: typeof o.next_action?.label === 'string' ? o.next_action.label : null,
    dismissed: dismissed.has(symbol),
    detailHref: detailHref(symbol),
    membership: raw.map(badgeOf).filter((b): b is MemberBadge => b !== null),
    expiryReason: typeof o.expiry_suggestion?.reason === 'string' && o.expiry_suggestion.reason ? o.expiry_suggestion.reason : null,
  }
}

/** Membership reasons other than the star: these keep a name on My List when the star is turned off (WL-08). */
export function otherMembership(r: ListRowView): MemberBadge[] {
  return r.membership.filter(m => m.kind !== 'starred')
}

/** One operator-membership source's read status (`my_watchlist.sources`). A failed source means the list may be
 *  missing names — the page has to say so instead of showing a short list as complete (WL-25). */
export type MemberSource = { kind: string; status: string; count: number | null }

export function membershipSources(body: unknown): MemberSource[] {
  const s = asRec(asRec(body)?.my_watchlist?.sources)
  if (!s) return []
  return Object.keys(s).map(kind => {
    const v = asRec(s[kind])
    return {
      kind,
      status: typeof v?.status === 'string' ? v.status : 'unknown',
      count: typeof v?.count === 'number' ? v.count : null,
    }
  })
}

/** One clock the payload carries. `at` is the server's timestamp; the age is this page's arithmetic against its own
 *  clock, which is why the label says so — the page never advances or invents a source clock (WL-10/WL-16/WL-26). */
export type Clock = { id: string; label: string; at: string | null; ageS: number | null }

function clock(id: string, label: string, at: unknown, nowMs: number): Clock {
  const t = typeof at === 'string' ? Date.parse(at) : NaN
  if (!Number.isFinite(t)) return { id, label, at: null, ageS: null }
  return { id, label, at: at as string, ageS: Math.max(0, Math.round((nowMs - t) / 1000)) }
}

/** Every clock the list body distinguishes, side by side: when the page was composed, when the list's own source was
 *  written, and (Suggestions) when the ranking projection ran. Absent clocks are omitted, never defaulted to now. */
export function clocksOf(body: unknown, tab: ListKey, lane: string | null, nowMs: number): Clock[] {
  const b = asRec(body)
  if (!b) return []
  const out: Clock[] = [clock('composed_at', 'Page composed', b.generated_at, nowMs)]
  if (tab === 'prospects') {
    const lanes = Array.isArray(b.lanes) ? b.lanes.map(asRec) : []
    const laneRow = lanes.find(l => l?.id === (lane ?? b.lane)) ?? null
    if (laneRow) out.push(clock('source_as_of', `Lane ${String(laneRow.id)} source`, laneRow.as_of, nowMs))
  } else {
    const section = asRec(b[tab === 'mine' ? 'my_watchlist' : 'suggests'])
    if (section) {
      const basis = section.as_of_basis === 'ranking_projection' ? 'Ranking projection' : 'List source'
      out.push(clock('source_as_of', basis, section.as_of, nowMs))
    }
  }
  const ranking = asRec(b.ranking)
  if (tab === 'suggests' && ranking) out.push(clock('ranking_as_of', 'Ranking projection', ranking.as_of, nowMs))
  return out.filter(c => c.at !== null)
}

/** The curation body's own sentence defining what the ranked number is (`ranking.label`), shown once above the rows
 *  so a conviction value and a universe rank are never read as the same measurement (WL-13/WL-14). */
export function rankingLegend(body: unknown): string | null {
  const label = asRec(asRec(body)?.ranking)?.label
  return typeof label === 'string' && label ? label : null
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

/** Grade Prospects on the **source** clock, not the composition clock (WL-19). The payload's `generated_at` is when
 *  the adapter composed the page; each lane carries the opportunity projection's own `as_of`. Grading the composition
 *  time let a fresh wrapper certify a 16-hour-old CIO prospect. The basis string says which clock was used, so a
 *  payload without a source clock is still honestly labelled `composed_at`. */
export function gradeProspects(body: unknown, nowMs: number, lane?: string): ListGrade {
  const b = asRec(body)
  const lanes = Array.isArray(b?.lanes) ? (b!.lanes as unknown[]) : []
  const find = (id: unknown) => lanes.map(asRec).find(l => l?.id === id) ?? null
  const selected = find(lane) ?? find(b?.lane)
  const sourceAsOf = selected?.as_of
  const useSource = typeof sourceAsOf === 'string' && Number.isFinite(Date.parse(sourceAsOf))
  return gradeList(useSource ? sourceAsOf : b?.generated_at, useSource ? 'source_as_of' : 'composed_at', nowMs, {
    maxAgeS: COMPOSED_MAX_AGE_S,
    swr: b?._swr,
  })
}

/** One prospects lane as a navigable tab: the server's own id/label/count, its cap overflow names, and whether it is
 *  the lane on screen (WL-18: the page used to hard-code `lane=forming`, so every row was Setup forming by
 *  construction and the other four lanes were unreachable). */
export type LaneTab = { id: string; label: string; count: number | null; overflow: string[]; active: boolean }

export function laneTabs(body: unknown, activeLane: string | null): LaneTab[] {
  const lanes = Array.isArray(asRec(body)?.lanes) ? (asRec(body)!.lanes as unknown[]) : []
  return lanes
    .map(asRec)
    .filter((l): l is Record<string, any> => !!l && typeof l.id === 'string' && l.id !== '')
    .map(l => ({
      id: String(l.id),
      label: typeof l.label === 'string' && l.label ? l.label : String(l.id),
      count: typeof l.count === 'number' ? l.count : null,
      overflow: Array.isArray(l.overflow) ? l.overflow.map(String) : [],
      active: l.id === activeLane,
    }))
}

/** The active lane's cap overflow: names the server counted but did not return on this page (WL-18: never silently
 *  dropped). Empty when the lane is not at its cap or the payload does not say. */
export function laneOverflow(body: unknown, lane: string | null): string[] {
  return laneTabs(body, lane).find(t => t.active)?.overflow ?? []
}

/** Case-insensitive symbol/company filter over the rows already fetched for this page. Client-side by design: it is
 *  labelled as filtering this page, because no server text-search read exists yet (WL-12/WL-23). */
export function filterRows(rows: ListRowView[], query: string): ListRowView[] {
  const q = query.trim().toUpperCase()
  if (!q) return rows
  return rows.filter(r => r.symbol.includes(q) || (r.company ?? '').toUpperCase().includes(q))
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
