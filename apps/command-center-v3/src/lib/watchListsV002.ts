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
  /** Where the server says `conviction` came from (`cio_truth` = the canonical CIO record). One read can carry two
   *  source-scored numbers both called "conviction"; the page names this one instead of letting the word stand for
   *  both (review r5c F1: ANRO shows 68 here and 86 in the suggestion's own reason). */
  convictionSource: string | null
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
  /** The server's own membership answer for this row (`mine`), which is not the same as `starred`. */
  mine: boolean
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

/** The server's machine name for where a row's conviction came from, in the operator's words. An unknown name is shown
 *  verbatim rather than guessed, so a source the page has not met yet is visible instead of silently mislabelled. */
export function convictionSourceLabel(raw: string | null): string | null {
  if (!raw) return null
  if (raw === 'cio_truth' || raw === 'cio_prospect') return 'CIO record'
  if (raw === 'cio_opportunity_projection') return 'curator projection'
  return raw
}

/** A suggestion's own reason quotes the RANKING PROJECTION's conviction ("#2 · conviction 86"), while the row's
 *  `conviction` is the canonical CIO record's (live ANRO: 68 on the row, 86 in the reason). Two sources, one word: when
 *  the two disagree the reason's number is named by its source, so no row shows one label over two different values
 *  (review r5c F1). Agreement, or no record number to compare against, leaves the server's wording untouched. */
export function nameProjectionConviction(reason: string, recordConviction: number | null): string {
  if (recordConviction === null) return reason
  return reason.replace(/\bconviction (\d+(?:\.\d+)?)/, (m, num: string) =>
    Math.round(Number(num)) === Math.round(recordConviction) ? m : `ranking-projection conviction ${num}`,
  )
}

/** The conviction cell's text: the number, the source the server names for it, and the universe rank kept visibly
 *  separate (WL-13). A row with no conviction says so; it never borrows the projection's number. */
export function convictionText(r: ListRowView): string {
  const src = convictionSourceLabel(r.convictionSource)
  const conv = r.conviction === null ? 'no score' : `conviction ${Math.round(r.conviction)}${src ? ` · ${src}` : ''}`
  return r.rank === null ? conv : `${conv} · universe rank #${r.rank}`
}

export function rowView(r: any, dismissed: ReadonlySet<string> = new Set()): ListRowView | null {
  const o = asRec(r)
  const symbol = typeof o?.symbol === 'string' ? o.symbol.trim().toUpperCase() : ''
  if (!o || !symbol) return null
  const state = o.position_state
  const held = state === 'held' ? 'Held' : state === 'formerly_held' ? 'Formerly held' : null
  const conviction = typeof o.conviction === 'number' ? o.conviction : null
  const sug = asRec(o.suggestion)
  const reason = typeof sug?.reason === 'string' ? sug.reason.trim() : ''
  const why = reason
    ? nameProjectionConviction(reason, conviction)
    : String(o.why || o.summary || '').trim()
  const raw = Array.isArray(o.membership) ? o.membership : []
  return {
    symbol,
    company: typeof o.company === 'string' ? o.company : null,
    stage: String(o.stage || o.lane || ''),
    conviction,
    rank: typeof o.universe_rank === 'number' ? o.universe_rank : null,
    convictionSource: typeof o.conviction_source === 'string' && o.conviction_source ? o.conviction_source : null,
    starred: o.starred === true,
    held,
    why,
    nextAction: typeof o.next_action?.label === 'string' ? o.next_action.label : null,
    dismissed: dismissed.has(symbol),
    detailHref: detailHref(symbol),
    membership: raw.map(badgeOf).filter((b): b is MemberBadge => b !== null),
    expiryReason: typeof o.expiry_suggestion?.reason === 'string' && o.expiry_suggestion.reason ? o.expiry_suggestion.reason : null,
    mine: o.mine === true,
  }
}

/** Lanes whose names may be added to My List from Prospects: a stage the CIO currently considers actionable. An
 *  `expired` or `manage` name was not offered as a new idea, so the page does not offer to adopt it (WL-20). */
const ADDABLE_LANES = new Set(['actionable', 'forming', 'reentry'])

export function canAddToMine(r: ListRowView): boolean {
  return !r.mine && ADDABLE_LANES.has(r.stage.trim().toLowerCase())
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
    // NEEDS BACKEND: the live lane dict has no `as_of` (see gradeProspects), so today this clock is omitted and the
    // block shows only "Page composed" — absence is said by omission, never by a stand-in clock.
    if (laneRow) out.push(clock('source_as_of', `Lane ${String(laneRow.id)} source`, laneRow.as_of, nowMs))
  } else {
    const section = asRec(b[tab === 'mine' ? 'my_watchlist' : 'suggests'])
    if (section) {
      const basis = section.as_of_basis === 'ranking_projection' ? 'Ranking projection' : 'List source'
      out.push(clock('source_as_of', basis, section.as_of, nowMs))
    }
  }
  const ranking = asRec(b.ranking)
  if (tab === 'suggests' && ranking) {
    // The list section's clock IS the ranking projection's clock when the server says so (`as_of_basis`), and the two
    // are the same stamp — printing both under the same label showed the ranking clock twice (review r5c F1). Emit the
    // ranking clock only when the section clock did not already carry it (e.g. the section sent no `as_of`).
    const sectionIsRanking = asRec(b.suggests)?.as_of_basis === 'ranking_projection'
    const emitted = out.some(c => c.id === 'source_as_of' && c.at !== null)
    if (!sectionIsRanking || !emitted) out.push(clock('ranking_as_of', 'Ranking projection', ranking.as_of, nowMs))
  }
  const seen = new Set<string>()
  return out.filter(c => {
    if (c.at === null) return false
    const key = `${c.label}\u0000${c.at}`
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
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
 *  payload without a source clock is still honestly labelled `composed_at`.
 *
 *  NEEDS BACKEND, stated plainly: the prospects payload does NOT carry a per-lane `as_of` today. `watch_prospects`
 *  builds a lane as `{id, label, hint, count, cap, items, overflow, mine}` and `prospects_page` passes the lanes
 *  through unchanged, so in production this always grades `generated_at` and labels it `composed_at` — honest, and the
 *  only clock the read offers. The source-clock branch below is the contract a lane `as_of` would satisfy the day the
 *  server sends one. Review F2 (cc-deepseek-9) found an earlier fixture INVENTING that field, which proved the branch
 *  against a payload shape that does not exist; the fixture now uses the real lane shape.
 *
 *  For whoever adds the field: a real lane `as_of` is a SOURCE clock and must not inherit `COMPOSED_MAX_AGE_S`, which
 *  is a composition timeout. A legitimately older source clock graded against it would read STALE for being exactly
 *  as old as a source is allowed to be. */
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

/** Keep one row per canonical symbol, in arrival order. The server is meant to dedupe by symbol identity, but a read
 *  that repeats a name must never render it twice or count it twice: the caller shows how many repeats were collapsed
 *  instead of hiding them (WL-29). */
export function dedupeRows(rows: ListRowView[]): { rows: ListRowView[]; repeated: number } {
  const seen = new Set<string>()
  const kept: ListRowView[] = []
  for (const r of rows) {
    if (seen.has(r.symbol)) continue
    seen.add(r.symbol)
    kept.push(r)
  }
  return { rows: kept, repeated: rows.length - kept.length }
}

/** What each list's count is a count OF, in the producer's own numbers. WL-29's residue was a header count with no
 *  named population; every count below is read from the body, and a field the body does not carry is left out rather
 *  than estimated. Returns null when the body carries nothing to name. */
export function populationText(tab: ListKey, body: unknown, lane: string | null = null): string | null {
  const b = asRec(body)
  if (!b) return null
  if (tab === 'mine') {
    const s = asRec(b.my_watchlist)
    const count = typeof s?.count === 'number' ? s.count : null
    const unfiltered = typeof s?.unfiltered_count === 'number' ? s.unfiltered_count : null
    if (count === null) return null
    const f = asRec(s?.filters) ?? {}
    const filters = Object.keys(f).filter(k => Boolean(f[k]))
    const scope = filters.length
      ? `Filtered by ${filters.join(', ')}; ${unfiltered ?? 'an unstated number of'} names before filters.`
      : 'No position filters are applied.'
    return `Counts every name on My List from every membership source (star, personal watchlist, directives, operator adds): ${count} names. ${scope}`
  }
  if (tab === 'suggests') {
    const s = asRec(b.suggests)
    const eligible = typeof s?.eligible === 'number' ? s.eligible : null
    const ranked = typeof s?.ranked === 'number' ? s.ranked : null
    const note = typeof s?.universe_note === 'string' && s.universe_note ? s.universe_note : null
    if (!note && eligible === null) return null
    const counts = eligible !== null ? ` ${eligible}${ranked !== null ? ` of ${ranked} ranked` : ''} names are eligible today.` : ''
    return `${note || 'Names from the ranked research universe.'}${counts} Names already on My List, held names and names dismissed in the last 30 days are excluded here by the server, so this count never includes them.`
  }
  const tabs = laneTabs(b, lane)
  const t = tabs.find(x => x.active) ?? tabs[0]
  if (!t || t.count === null) return null
  // The lane's cap/overflow is stated once by the page's own overflow note; this sentence only names the population.
  return `Counts the names the prospect collection currently holds in lane “${t.label}”: ${t.count}.`
}

/** Case-insensitive symbol/company filter over the rows already fetched for this page. Client-side by design: it is
 *  labelled as filtering this page, because no server text-search read exists yet (WL-12/WL-23). */
export function filterRows(rows: ListRowView[], query: string): ListRowView[] {
  const q = query.trim().toUpperCase()
  if (!q) return rows
  return rows.filter(r => r.symbol.includes(q) || (r.company ?? '').toUpperCase().includes(q))
}

/** A decision field WL-11 names that this list read does not carry. The page states the absence once, in the body's
 *  terms, instead of leaving a blank column that reads as "nothing to see" — an unknown may never be rendered as a
 *  value, and a missing column may never be rendered as a clean one. */
export type AbsentField = { id: string; label: string }

/** Row keys that would prove the field IS in the read. Deliberately a list of candidates, not a contract: when the
 *  server starts sending any of them, the disclosure for that field disappears on its own. */
const FIELD_KEYS: { id: string; label: string; keys: string[] }[] = [
  { id: 'quote', label: 'last price and quote age', keys: ['last_price', 'price', 'quote', 'quote_age_s', 'close', 'last'] },
  { id: 'entry', label: 're-entry level and distance', keys: ['entry_level', 'entry_zone', 'entry_distance_pct', 'distance_pct', 'reentry_level'] },
  { id: 'alert', label: 'alert condition and armed/fired/paused state', keys: ['alert', 'alert_state', 'alert_condition', 'armed'] },
]

/** Every row of the section currently on screen, so the check runs over what was actually read. */
function sectionRows(body: unknown, key: ListKey): Record<string, any>[] {
  const b = asRec(body)
  if (!b) return []
  const section = key === 'prospects'
    ? { rows: (Array.isArray(b.lanes) ? b.lanes : []).flatMap((l: unknown) => (asRec(l)?.items as unknown[]) ?? []) }
    : asRec(b[key === 'mine' ? 'my_watchlist' : 'suggests'])
  const rows = Array.isArray(section?.rows) ? (section!.rows as unknown[]) : []
  return rows.map(asRec).filter((r): r is Record<string, any> => !!r)
}

export function absentRowFields(body: unknown, key: ListKey): AbsentField[] {
  const rows = sectionRows(body, key)
  if (!rows.length) return [] // nothing was read: a missing list is a different defect, not a missing column
  return FIELD_KEYS
    .filter(f => !rows.some(r => f.keys.some(k => r[k] !== undefined && r[k] !== null)))
    .map(f => ({ id: f.id, label: f.label }))
}

/** "a, b, and c" for the disclosure sentence. */
export function joinLabels(labels: string[]): string {
  if (labels.length <= 1) return labels[0] ?? ''
  return `${labels.slice(0, -1).join(', ')} and ${labels[labels.length - 1]}`
}

/** The server's own typeahead for the Add-symbol box (`GET /api/v3/data-broker/watch-symbol-search?q=`,
 *  `WatchSymbolSearch@v1`, read-only — `list_symbol_search`). The page never guesses a ticker: it offers what the
 *  security registry and the instrument feed return, and marks the ones already on My List (WL-12). */
export const SYMBOL_SEARCH_API = '/api/v3/data-broker/watch-symbol-search'
export const SEARCH_MIN_CHARS = 2

export function symbolSearchUrl(q: string): string {
  return `${SYMBOL_SEARCH_API}?q=${encodeURIComponent(q.trim())}`
}

export type SearchHit = {
  symbol: string
  name: string | null
  /** The registry's own identity answer for this security; null when the row is not in the registry. */
  identityStatus: string | null
  inRegistry: boolean
  /** The server's duplicate-safe answer: this name is already on My List. */
  onMyList: boolean
  match: 'ticker' | 'name' | 'unknown'
}

export function searchHits(body: unknown): SearchHit[] {
  const results = asRec(body)?.results
  if (!Array.isArray(results)) return []
  return results
    .map(asRec)
    .filter((r): r is Record<string, any> => !!r && typeof r.symbol === 'string' && r.symbol.trim() !== '')
    .map(r => ({
      symbol: String(r.symbol).trim().toUpperCase(),
      name: typeof r.name === 'string' && r.name.trim() ? r.name.trim() : null,
      identityStatus: typeof r.identity_status === 'string' && r.identity_status ? r.identity_status : null,
      inRegistry: r.in_registry === true,
      onMyList: r.on_my_list === true,
      match: r.match === 'ticker' || r.match === 'name' ? r.match : 'unknown',
    }))
}

/** A search body that cannot be trusted: wrong schema, ok:false, or a shape without `results`. `results: []` on a valid
 *  body is a real "nothing matched" — a different answer than a search that could not be read at all. */
export function searchGap(body: unknown): string | null {
  const b = asRec(body)
  if (!b) return null // not read yet
  if (b.ok === false) return typeof b.reason === 'string' && b.reason ? b.reason : 'the search refused the read'
  if (b.schema !== undefined && b.schema !== 'WatchSymbolSearch@v1') return `unexpected schema ${String(b.schema)}`
  if (!Array.isArray(b.results)) return 'the search body carries no results list'
  return null
}

/** What the Add-symbol box knows: what was typed, what was actually submitted (a read is issued per intent, not per
 *  keystroke), and the state of that read. */
export type SymbolSearchState = {
  q: string
  submitted: string
  loading: boolean
  error: string | null
  hits: SearchHit[]
  gap: string | null
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
