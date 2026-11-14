/** Watch v002 — My List / Suggestions / Prospects (LQ-20261107-2993b).
 *
 *  Each tab reads ONE paged list (shape=list, 25 rows) with its own as_of, grades it (OK / STALE / UNKNOWN with age) and
 *  never turns an unread list into an empty one. Actions reuse the existing writes: star/add/remove →
 *  POST /api/v3/watch/commands/mine; dismiss/restore → /suggest-dismiss, /suggest-restore. Detail opens the symbol page.
 *  Watching only — no order, no size, no stop. */
import { useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import { readOnce } from '../lib/homeV010'
import WatchSubnav from '../components/watch/WatchSubnav'
import './WatchListsV002.css'
import { mineAction } from '../components/watch/MineControls'
import {
  absentRowFields, ageText, canAddToMine, clocksOf, convictionText, curationUrl, dedupeRows, dismissedSet, filterRows, gradeCuration, gradeProspects, joinLabels,
  laneOverflow, laneTabs, membershipSources, otherMembership, pagingOf, pagingText, populationText, prospectsUrl, rankingLegend, rowView, SEARCH_MIN_CHARS,
  searchGap, searchHits, symbolSearchUrl,
  type AbsentField, type Clock, type DismissedItem, type LaneTab, type ListGrade, type ListKey, type ListPaging, type ListRowView,
  type MemberSource, type SearchHit, type SymbolSearchState,
} from '../lib/watchListsV002'

const TAB_COPY: Record<ListKey, { title: string; purpose: string }> = {
  mine: { title: 'My List', purpose: 'Every name you monitor, including invalid or expired signals, until you remove it.' },
  suggests: { title: 'Suggestions', purpose: 'Ranked names not already on My List; dismiss for 30 days or add.' },
  prospects: { title: 'Prospects', purpose: 'The CIO prospect collection by lifecycle stage — review, do not enter from here.' },
}

export type ListsViewProps = {
  tab: ListKey
  grade: ListGrade | null
  rows: ListRowView[]
  paging: ListPaging
  offset: number
  loading: boolean
  error: string | null
  /** Server-declared gap for this list (payload_gap / status unavailable); never an empty list. */
  gap: string | null
  message: string
  dismissedStatus: string
  dismissedItems: DismissedItem[]
  /** Prospects only: the lane the URL selects and the server's lanes with counts. */
  lane?: string | null
  lanes?: LaneTab[]
  /** Cap overflow names for the active prospects lane (never silently dropped). */
  overflow?: string[]
  /** Client-side text filter over the fetched page (no server text search exists yet). */
  query?: string
  /** A command is in flight for this row key (`<symbol>:<action>`); its controls are disabled until it settles. */
  busy?: string | null
  /** The clocks the body itself distinguishes (composition vs source vs ranking), never a render-time age. */
  clocks?: Clock[]
  /** WL-29: what this list's header count is a count of, read from the producer's own numbers. */
  population?: string | null
  /** WL-29: rows collapsed because this read carried the same symbol more than once. */
  repeated?: number
  /** `ranking.label`: the body's own definition of what the ranked number is. */
  legend?: string | null
  /** Per-source read status of operator membership (`my_watchlist.sources`). */
  sources?: MemberSource[]
  /** WL-11: the decision fields this read does not carry, stated once instead of left as a blank column. */
  absent?: AbsentField[]
  /** WL-12 (My List only): the Add-symbol box's state. Omit to render no box. */
  search?: SymbolSearchState
  onSearch?: (q: string) => void
  onSearchSubmit?: (q: string) => void
  onAddSymbol?: (hit: SearchHit) => void
  /** WL-15: the name most recently dismissed in this view, so the undo sits next to the result that hid it. */
  undo?: { symbol: string } | null
  onUndo?: () => void
  onStar: (r: ListRowView) => void
  /** Prospects only: adopt a name the server says is not yours yet (the same membership command as the star). */
  onAdd?: (r: ListRowView) => void
  onDismiss: (r: ListRowView) => void
  onRestore: (r: ListRowView) => void
  onPage: (offset: number) => void
  onRetry: () => void
  onLane?: (lane: string) => void
  onQuery?: (q: string) => void
}

export function WatchListsV002View(p: ListsViewProps) {
  const copy = TAB_COPY[p.tab]
  const lane = p.lane ?? null
  const lanes = p.lanes ?? []
  const query = p.query ?? ''
  const overflow = p.overflow ?? []
  const busy = p.busy ?? null
  const clocks = p.clocks ?? []
  const population = p.population ?? null
  const repeated = p.repeated ?? 0
  const sources = p.sources ?? []
  const absent = p.absent ?? []
  const search = p.search
  const staleSources = sources.filter(s => s.status !== 'ok')
  const shown = filterRows(p.rows, query)
  const filtered = query.trim() ? ` · ${shown.length} of ${p.rows.length} on this page match “${query.trim()}”` : ''
  return (
    <section className="v010 wl2" data-testid="watch-lists-v002">
      {/* W-04: the shared sub-nav IS the tab bar on this page — one tab set, no duplicate row. */}
      <WatchSubnav />
      <div className="wl2-head">
        <h1 className="v010-h1">{copy.title}</h1>
        <p className="wl2-purpose">{copy.purpose}</p>
      </div>
      {p.tab === 'prospects' && lanes.length > 0 && (
        <div className="wl2-lanes" data-testid="watch-lanes" role="tablist" aria-label="Prospect stage">
          {lanes.map(t => (
            <button key={t.id} type="button" role="tab" aria-selected={t.active} data-testid={`watch-lane-${t.id}`}
              data-active={t.active ? '1' : '0'} className={`v010-btn${t.active ? ' wl2-lane-on' : ''}`}
              onClick={() => p.onLane?.(t.id)}>
              {t.label} <span className="wl2-lane-n" data-count={t.count ?? 'unknown'}>{t.count === null ? 'count unknown' : t.count}</span>
            </button>
          ))}
        </div>
      )}
      <div className="wl2-asof" data-testid="watch-list-asof" data-state={p.grade?.state ?? (p.loading ? 'LOADING' : 'UNKNOWN')}>
        <span className={`v010-pill ${p.grade?.state === 'OK' ? 'ok' : p.grade?.state === 'STALE' ? 'warn' : p.loading ? '' : 'bad'}`}>{p.loading ? 'LOADING' : p.grade?.state ?? 'UNKNOWN'}</span>
        <span>{p.loading ? 'Loading…' : p.grade ? `${p.grade.label.replace(/^[A-Z]+ · /, '')} · ${p.grade.basis.replace(/_/g, ' ')}` : 'list could not be read'}</span>
        {p.grade?.reason ? <span className="wl2-why">{p.grade.reason}</span> : null}
      </div>
      {/* WL-10/WL-16/WL-26: every clock the body carries, side by side and labelled. The age is this page's arithmetic
          against its own clock; no clock here is derived from the moment the page rendered. */}
      {clocks.length > 0 && (
        <dl className="wl2-clocks" data-testid="watch-list-clocks" aria-label="Clocks this list carries">
          {clocks.map(c => (
            <div key={c.id} className="wl2-clock">
              <dt>{c.label}</dt>
              <dd data-clock={c.id} data-age-s={c.ageS ?? 'unknown'}>
                {c.at ? `${new Date(c.at).toISOString().slice(11, 16)}Z` : 'no timestamp'} · <span className="wl2-why">{c.ageS === null ? 'age unknown' : `${ageText(c.ageS)} old`}</span>
              </dd>
            </div>
          ))}
        </dl>
      )}
      {population && (
        <div className="wl2-note" data-testid="watch-population" role="status">{population}</div>
      )}
      {repeated > 0 && (
        <div className="wl2-note warn" data-testid="watch-dedupe" role="status">
          This read carried {repeated === 1 ? 'one name' : `${repeated} names`} more than once; each is shown once and counted once.
        </div>
      )}
      {p.tab === 'mine' && sources.length > 0 && (
        <div className={`wl2-note${staleSources.length ? ' warn' : ''}`} data-testid="watch-membership-sources" role={staleSources.length ? 'alert' : 'status'}>
          Membership sources: {sources.map(s => `${s.kind.replace(/_/g, ' ')} ${s.status === 'ok' ? 'ok' : s.status}`).join(' · ')}.
          {staleSources.length > 0
            ? ` A name whose membership source could not be read may be missing from this list — this list is not complete.`
            : ' Names reach this list from any of these sources, not only the star.'}
        </div>
      )}
      {p.tab === 'suggests' && p.legend && (
        <p className="wl2-legend" data-testid="watch-ranking-legend">
          Ranked by: {p.legend}. Conviction and universe rank are two different numbers and are labelled separately below.
        </p>
      )}
      <div className="wl2-tools">
        <label className="wl2-search">
          <span className="wl2-search-l">Find on this page</span>
          <input type="search" value={query} placeholder="Symbol or company" data-testid="watch-list-search"
            onChange={e => p.onQuery?.(e.target.value)} />
        </label>
        <span className="wl2-tools-note" data-testid="watch-list-count">Filters the rows on this page only — server text search is not available yet.{filtered}</span>
      </div>
      {/* WL-12: the Add-symbol path, using the server's own read-only typeahead. Nothing is guessed: the page offers
          the registry's rows, marks the ones already on My List, and says when the read failed instead of "no match". */}
      {p.tab === 'mine' && search && (
        <div className="wl2-add" data-testid="watch-add-symbol">
          <form className="wl2-add-form" onSubmit={e => { e.preventDefault(); p.onSearchSubmit?.(search.q) }}>
            <label className="wl2-search">
              <span className="wl2-search-l">Add a symbol</span>
              <input type="search" value={search.q} placeholder="Ticker or company name" data-testid="watch-add-input"
                onChange={e => p.onSearch?.(e.target.value)} />
            </label>
            <button type="submit" className="v010-btn" data-testid="watch-add-search"
              disabled={search.q.trim().length < SEARCH_MIN_CHARS || search.loading}>
              {search.loading ? 'Searching…' : 'Search'}
            </button>
          </form>
          <span className="wl2-why">Searches the security registry and the instrument feed. Ticker or company name, {SEARCH_MIN_CHARS}+ characters; nothing is fetched from a market provider.</span>
          {search.error ? (
            <div className="wl2-note bad" data-testid="watch-add-error" role="alert">
              Symbol search could not be read: {search.error}. No ticker is guessed from what you typed.
            </div>
          ) : search.gap ? (
            <div className="wl2-note bad" data-testid="watch-add-gap" role="alert">Symbol search could not be read: {search.gap}.</div>
          ) : search.submitted && !search.loading ? (
            search.hits.length === 0 ? (
              <div className="wl2-note" data-testid="watch-add-none">No ticker or company matches “{search.submitted}”.</div>
            ) : (
              <>
                <div className="wl2-add-q" data-testid="watch-add-for">Results for “{search.submitted}”</div>
                <ul className="wl2-rows" data-testid="watch-add-hits" data-for={search.submitted}>
                  {search.hits.map(hit => (
                    <li key={hit.symbol} className="wl2-row" data-testid={`watch-hit-${hit.symbol}`}>
                      <div className="wl2-main">
                        <strong className="wl2-sym">{hit.symbol}</strong>
                        {hit.name ? <span className="wl2-co">{hit.name}</span> : <span className="v010-pill">name unknown</span>}
                        {!hit.inRegistry && <span className="v010-pill warn" title="not in the security registry">not in the registry</span>}
                        {hit.identityStatus && <span className="v010-pill" title="identity registry status">{hit.identityStatus}</span>}
                      </div>
                      {/* Duplicate-safe: the SERVER says this name is already yours, so no Add is offered at all. */}
                      {hit.onMyList
                        ? <span className="v010-pill info" data-testid={`watch-hit-onlist-${hit.symbol}`}>already on My List</span>
                        : <button type="button" className="v010-btn" data-testid={`watch-hit-add-${hit.symbol}`}
                            disabled={busy === `${hit.symbol}:add`} onClick={() => p.onAddSymbol?.(hit)}>
                            {busy === `${hit.symbol}:add` ? 'Adding…' : 'Add to My List'}
                          </button>}
                    </li>
                  ))}
                </ul>
              </>
            )
          ) : null}
        </div>
      )}
      {/* WL-11: the monitoring fields the rows do NOT carry are named once, so a row is not read as a clean bill of
          health for the name. The list is derived from the body, so it disappears the day the server sends the field. */}
      {absent.length > 0 && (
        <p className="wl2-note" data-testid="watch-row-absent" data-absent={absent.map(a => a.id).join(',')}>
          This read does not carry {joinLabels(absent.map(a => a.label))}. A row here cannot answer any of those, so treat
          it as a symbol to open — not as a monitoring verdict on whether a quote is fresh, how far it is from your level,
          or whether an alert is armed.
        </p>
      )}
      {p.error && <div className="wl2-note bad" data-testid="watch-list-error" role="alert">List could not be read: {p.error} <button type="button" className="v010-btn" onClick={p.onRetry}>Retry</button></div>}
      {p.tab === 'suggests' && !p.loading && p.dismissedStatus !== 'ok' && p.dismissedStatus !== 'absent' && (
        <div className="wl2-note warn" data-testid="watch-dismissed-unknown" role="alert">Dismissed set could not be read ({p.dismissedStatus}); dismissed names may show.</div>
      )}
      {p.message && <div className="wl2-note" data-testid="watch-list-message" role="status">{p.message}</div>}
      {/* WL-15: a dismissal hides a name for a month, so the action that undoes it sits next to the result of the action
          that caused it — not only inside the list below. It issues the same restore command as the row. */}
      {p.undo && p.onUndo && (
        <div className="wl2-note" data-testid="watch-undo">
          {p.undo.symbol} is hidden from Suggestions until the date shown below.
          <button type="button" className="v010-btn" data-testid="watch-undo-btn" disabled={busy === `${p.undo.symbol}:restore`}
            onClick={p.onUndo}>Undo — restore {p.undo.symbol}</button>
        </div>
      )}
      {p.loading || (p.error && p.rows.length === 0) ? null : p.rows.length === 0 ? (
        // An unreadable list is never an empty list (REVIEW-2993r R4): UNKNOWN / a declared gap / no total => could not be read.
        p.gap || !p.grade || p.grade.state === 'UNKNOWN' || p.paging.total === null ? (
          <div className="wl2-note bad" data-testid="watch-list-unreadable" role="alert">
            List could not be read{p.gap ? `: ${p.gap}` : ''}. <button type="button" className="v010-btn" onClick={p.onRetry}>Retry</button>
          </div>
        ) : (
          <div className="wl2-note" data-testid="watch-list-empty">{p.paging.total === 0 ? 'No names in this list.' : 'Nothing on this page.'}</div>
        )
      ) : shown.length === 0 ? (
        <div className="wl2-note" data-testid="watch-list-no-match">{p.rows.length} rows on this page, none match “{query.trim()}”. <button type="button" className="v010-btn" onClick={() => p.onQuery?.('')}>Clear</button></div>
      ) : (
        <ul className="wl2-rows" data-testid="watch-list-rows">
          {shown.map(r => (
            <li key={r.symbol} className="wl2-row" data-testid={`watch-row-${r.symbol}`} data-dismissed={r.dismissed ? '1' : '0'}>
              <div className="wl2-main">
                {p.tab !== 'prospects' && (
                  <button type="button" className="wl2-star" aria-pressed={r.starred} aria-label={r.starred ? `Remove ${r.symbol} from My List` : `Add ${r.symbol} to My List`}
                    data-testid={`watch-star-${r.symbol}`} disabled={busy === `${r.symbol}:star`} onClick={() => p.onStar(r)}>{r.starred ? '★' : '☆'}</button>
                )}
                <Link className="v010-link wl2-sym" to={r.detailHref} data-testid={`watch-detail-${r.symbol}`}>{r.symbol}</Link>
                {r.company && <span className="wl2-co">{r.company}</span>}
                {/* WL-21: "yours" is the server's `mine`, not a word in a sentence and not the star. */}
                {r.mine && <span className="v010-pill info" data-testid={`watch-yours-${r.symbol}`}>Yours</span>}
                <span className="v010-pill">{r.stage}</span>
                {r.held && <span className="v010-pill info">{r.held}</span>}
                {r.membership.filter(m => m.kind !== 'starred').map(m => (
                  <span key={m.kind} className="v010-pill info" data-testid={`watch-member-${r.symbol}-${m.kind}`} title={m.at ? `since ${m.at}` : undefined}>
                    {m.label}
                  </span>
                ))}
                {r.expiryReason && (
                  <span className="v010-pill warn" data-testid={`watch-expiry-${r.symbol}`} title={r.expiryReason}>
                    expired signal — review, not removed
                  </span>
                )}
                {/* WL-13: conviction and universe rank are different measurements from different producers; label both,
                    never let one read as the other. r5c F1: the conviction's own source is named too, because a
                    suggestion's reason quotes the ranking projection's number under the same word. */}
                <span className="wl2-conv" data-testid={`watch-conviction-${r.symbol}`}>
                  {convictionText(r)}
                </span>
              </div>
              {/* WL-08: the star is a pin, not the only route onto My List — say so on the rows where it matters. */}
              {otherMembership(r).length > 0 && (
                <div className="wl2-why" data-testid={`watch-pin-note-${r.symbol}`}>
                  {r.starred ? 'Starred (your pin). ' : ''}Also listed via {otherMembership(r).map(m => m.label).join(', ')} — unstarring keeps it on this list.
                </div>
              )}
              {r.nextAction && <div className="wl2-next" data-guidance="1">Next step (guidance — open the symbol for actions): {r.nextAction}</div>}
              {/* WL-14: on Suggestions a row must state the reason it was selected, or say the read does not carry one.
                  A rank and a stage are measurements, not a rationale — a bare row reads as "obviously useful". */}
              {r.why ? (
                <div className="wl2-why" data-testid={p.tab === 'suggests' ? `watch-rationale-${r.symbol}` : undefined}
                  data-unavailable={p.tab === 'suggests' ? '0' : undefined}>{r.why}</div>
              ) : p.tab === 'suggests' ? (
                <div className="wl2-why" data-testid={`watch-rationale-${r.symbol}`} data-unavailable="1">
                  Selection reason not stated in this read — the rank and the stage are all this row proves, and neither of
                  them says why the name is useful now.
                </div>
              ) : null}
              {/* WL-22: a setup row that states no condition says so — an empty cell must not read as "setup confirmed". */}
              {p.tab === 'prospects' && !r.why && (
                <div className="wl2-why" data-testid={`watch-condition-${r.symbol}`} data-unavailable="1">
                  Setup condition not stated in this read — this row does not prove the setup is confirmed.
                </div>
              )}
              {/* WL-20: adopt a prospect the server itself reports as not yours (`mine: false`), through the same
                  membership command the star uses. Offered only where the lane is one the CIO currently calls
                  actionable — an `expired` or `manage` name was not put forward as a new idea, so it gets no button. */}
              {p.tab === 'prospects' && p.onAdd && canAddToMine(r) && (
                <button type="button" className="v010-btn" data-testid={`watch-add-${r.symbol}`}
                  disabled={busy === `${r.symbol}:add`} onClick={() => p.onAdd?.(r)}>
                  {busy === `${r.symbol}:add` ? 'Adding…' : 'Add to My List'}
                </button>
              )}
              {p.tab === 'suggests' && !r.dismissed && (
                <button type="button" className="v010-btn" data-testid={`watch-dismiss-${r.symbol}`} disabled={busy === `${r.symbol}:dismiss`} onClick={() => p.onDismiss(r)}>Dismiss 30 d</button>)}
            </li>
          ))}
        </ul>
      )}
      {overflow.length > 0 && (
        <div className="wl2-note" data-testid="watch-lane-overflow" role="status">
          At this lane&apos;s cap: {overflow.length} more name{overflow.length === 1 ? '' : 's'} counted but not shown ({overflow.join(', ')}).
        </div>
      )}
      {p.tab === 'suggests' && p.dismissedItems.length > 0 && (
        <details className="wl2-dismissed" data-testid="watch-dismissed" open>
          <summary>Dismissed ({p.dismissedItems.length})</summary>
          <p className="wl2-why" data-testid="watch-dismissed-policy">
            A dismissed name is left out of Suggestions until the date shown. Restoring makes it eligible again — it does
            not guarantee the name ranks in the visible top set, because the ranking is the server&apos;s and this page
            does not recompute it.
          </p>
          <ul className="wl2-rows">
            {p.dismissedItems.map(d => (
              <li key={d.symbol} className="wl2-row" data-testid={`watch-dismissed-${d.symbol}`}>
                <strong>{d.symbol}</strong>{d.reason && <span>{d.reason}</span>}{d.until && <span>until {d.until.slice(0, 10)}</span>}
                <button type="button" className="v010-btn" data-testid={`watch-restore-${d.symbol}`} disabled={busy === `${d.symbol}:restore`} onClick={() => p.onRestore({ symbol: d.symbol } as ListRowView)}>Restore</button>
              </li>
            ))}
          </ul>
        </details>
      )}
      <div className="wl2-paging" data-testid="watch-list-paging">
        <span>{pagingText(p.paging, p.offset)}</span>
        <button type="button" disabled={p.offset <= 0} className="v010-btn" onClick={() => p.onPage(Math.max(0, p.offset - 25))}>Previous</button>
        <button type="button" disabled={!p.paging.hasMore || p.paging.nextOffset === null} className="v010-btn" onClick={() => p.paging.nextOffset !== null && p.onPage(p.paging.nextOffset)}>Next</button>
      </div>
    </section>
  )
}

async function post(path: string, body: unknown): Promise<void> {
  const r = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
  const j = await r.json().catch(() => ({}))
  const d = j?.data ?? j
  if (!r.ok || d?.ok === false) throw new Error(String(d?.error || d?.detail || `HTTP ${r.status}`))
}

/** Server-declared reason this list is unreadable: payload_gap (over budget / garbled) or an unavailable status. */
export function gapOf(body: any, section: any): string | null {
  const g = section?.payload_gap ?? body?.payload_gap
  if (g) return String(typeof g === 'object' ? g.reason || g.code || 'payload gap' : g).slice(0, 120)
  return body?.status === 'unavailable' ? 'the server reports this read unavailable' : null
}

const listKey = (q: string | null): ListKey => (q === 'suggests' ? 'suggests' : q === 'prospects' ? 'prospects' : 'mine')

const SEARCH_EMPTY: SymbolSearchState = { q: '', submitted: '', loading: false, error: null, hits: [], gap: null }

/** The parent keys this by tab, so a tab switch remounts it: useApi keeps its last body across a path change, and a body from
 *  another list must not be graded or parsed by this one (review 2993ab-v2r N4; same defect as 2993cr R4). */
export function WatchListsTab({ tab, lane = null, offset = 0, query = '', onLane, onPage, onQuery }: {
  tab: ListKey
  lane?: string | null
  offset?: number
  query?: string
  onLane?: (lane: string) => void
  onPage?: (offset: number) => void
  onQuery?: (q: string) => void
}) {
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const [search, setSearch] = useState<SymbolSearchState>(SEARCH_EMPTY)
  const [undo, setUndo] = useState<string | null>(null)
  const searchToken = useRef(0)
  const url = tab === 'prospects' ? prospectsUrl(lane || 'actionable', offset) : curationUrl(tab, offset)
  const { data, loading, error, refetch } = useApi<any>(url, 120_000)
  const body = useMemo(() => (data && typeof data === 'object' ? ((data as any).data ?? data) : null), [data])
  const nowMs = Date.now()
  const grade = body ? (tab === 'prospects' ? gradeProspects(body, nowMs, lane || 'actionable') : gradeCuration(body, tab, nowMs)) : null
  const dis = dismissedSet(body)
  const section = tab === 'mine' ? body?.my_watchlist : tab === 'suggests' ? body?.suggests : { rows: (body?.lanes || []).flatMap((l: any) => l?.items || []), pagination: body?.pagination }
  // WL-29: a read that repeats a name renders it once and says how many repeats it collapsed.
  const { rows, repeated } = dedupeRows((Array.isArray(section?.rows) ? section.rows : []).map((r: unknown) => rowView(r, dis.symbols)).filter(Boolean) as ListRowView[])
  /** ONE bounded read per submitted query — not a poll, and not `useApi`: a search the operator asked for must answer (or
   *  fail) once, and the body of a previous query must never be rendered as this query's answer. Each read carries a
   *  token, so a slow earlier answer cannot overwrite a newer one. */
  const runSearch = async (raw: string) => {
    const q = raw.trim()
    if (q.length < SEARCH_MIN_CHARS) {
      searchToken.current += 1
      setSearch({ q: raw, submitted: '', loading: false, error: null, hits: [], gap: null })
      return
    }
    const token = ++searchToken.current
    setSearch(s => ({ ...s, q: raw, submitted: q, loading: true, error: null, hits: [], gap: null }))
    const read = await readOnce<unknown>(symbolSearchUrl(q))
    if (token !== searchToken.current) return // a newer query owns the box
    if (read.state !== 'OK') {
      setSearch(s => ({ ...s, loading: false, error: String(read.error || (read.state === 'TIMED OUT' ? 'the search did not answer' : 'the read failed')) }))
      return
    }
    const gap = searchGap(read.data)
    setSearch(s => ({ ...s, loading: false, error: null, gap, hits: gap ? [] : searchHits(read.data) }))
  }
  const act = async (key: string, fn: () => Promise<string>) => {
    if (busy) return // one command at a time: a second click cannot race the first
    setBusy(key)
    try { setMessage(await fn()); refetch() } catch (e) { setMessage(`Failed: ${String((e as Error).message || e).slice(0, 100)}`) } finally { setBusy(null) }
  }
  return (
    <WatchListsV002View
      tab={tab} grade={grade} rows={rows} paging={pagingOf(section)} offset={offset} loading={loading && !body}
      error={error ? String(error) : null} gap={gapOf(body, section)} message={message} dismissedStatus={body?.suggests ? dis.status : 'absent'} dismissedItems={dis.items}
      lane={lane} lanes={tab === 'prospects' ? laneTabs(body, lane || 'actionable') : []}
      overflow={tab === 'prospects' ? laneOverflow(body, lane || 'actionable') : []}
      clocks={body ? clocksOf(body, tab, lane, nowMs) : []}
      population={body ? populationText(tab, body, lane) : null}
      repeated={repeated}
      legend={tab === 'suggests' ? rankingLegend(body) : null}
      sources={tab === 'mine' ? membershipSources(body) : []}
      absent={body ? absentRowFields(body, tab) : []}
      query={query} busy={busy}
      search={tab === 'mine' ? search : undefined}
      onSearch={q => setSearch(s => ({ ...s, q }))}
      onSearchSubmit={q => void runSearch(q)}
      onAddSymbol={hit => void act(`${hit.symbol}:add`, async () => {
        const res = await mineAction(hit.symbol, 'add', undefined, 'watch.v002')
        if (!res.ok) throw new Error(res.message)
        // Readback: the same search must now come back with this name marked as already yours — the proof the write landed.
        await runSearch(hit.symbol)
        return `${hit.symbol} added to My List.`
      })}
      onStar={r => void act(`${r.symbol}:star`, async () => { const res = await mineAction(r.symbol, r.starred ? 'remove' : 'add', undefined, 'watch.v002'); if (!res.ok) throw new Error(res.message); return res.message })}
      onAdd={r => void act(`${r.symbol}:add`, async () => { const res = await mineAction(r.symbol, 'add', undefined, 'watch.v002'); if (!res.ok) throw new Error(res.message); return res.message })}
      onDismiss={r => void act(`${r.symbol}:dismiss`, async () => { await post('/api/v3/watch/commands/suggest-dismiss', { symbol: r.symbol }); setUndo(r.symbol); return `${r.symbol} dismissed for 30 days.` })}
      onRestore={r => void act(`${r.symbol}:restore`, async () => { await post('/api/v3/watch/commands/suggest-restore', { symbol: r.symbol }); setUndo(u => (u === r.symbol ? null : u)); return `${r.symbol} restored.` })}
      undo={undo ? { symbol: undo } : null}
      onUndo={() => { const sym = undo; if (!sym) return; void act(`${sym}:restore`, async () => { await post('/api/v3/watch/commands/suggest-restore', { symbol: sym }); setUndo(null); return `${sym} restored.` }) }}
      onPage={o => onPage?.(o)} onRetry={() => refetch()}
      onLane={l => onLane?.(l)} onQuery={q => onQuery?.(q)}
    />
  )
}

export type ListQuery = { tab: ListKey; lane: string | null; offset: number; query: string }

/** Parse the URL into the view state. `list` picks the tab; `stage` (Prospects only) picks the lane; `offset` is the
 *  page cursor and `q` the on-page filter. All four live in the URL so Back and a deep link restore the same view
 *  (WL-23/WL-29). An unknown `stage` is passed through rather than rewritten: the server decides which lanes exist,
 *  and the page shows what the server returns instead of inventing a lane. */
export function listQuery(sp: URLSearchParams): ListQuery {
  const tab = listKey(sp.get('list'))
  const raw = Number(sp.get('offset') || 0)
  return {
    tab,
    lane: tab === 'prospects' ? sp.get('stage') || 'actionable' : null,
    offset: Number.isFinite(raw) ? Math.max(0, Math.floor(raw)) : 0,
    query: sp.get('q') || '',
  }
}

/** Write one navigation into the current params: a page change keeps lane and filter, a lane change clears the cursor,
 *  and clearing the filter deletes `q` instead of leaving `q=` behind. */
export function listParams(sp: URLSearchParams, patch: { offset?: number; stage?: string | null; query?: string }): URLSearchParams {
  const next = new URLSearchParams(sp)
  if (patch.offset !== undefined) {
    if (patch.offset > 0) next.set('offset', String(patch.offset)); else next.delete('offset')
  }
  if (patch.stage) next.set('stage', patch.stage)
  if (patch.query !== undefined) {
    if (patch.query) next.set('q', patch.query); else next.delete('q')
  }
  return next
}

/** `list` picks the tab; `stage` (Prospects), `offset` and `q` live in the URL so Back and a deep link restore the same
 *  view (WL-23/WL-29). An offset is a page cursor, never a filter. */
export default function WatchListsV002() {
  const [sp, setSp] = useSearchParams()
  const q = listQuery(sp)
  const tab = q.tab
  const go = (patch: { offset?: number; stage?: string | null; query?: string }) => setSp(listParams(sp, patch), { replace: true })
  return <WatchListsTab key={tab} tab={tab} lane={q.lane} offset={q.offset} query={q.query}
    onLane={l => go({ offset: 0, stage: l })} onPage={o => go({ offset: o })} onQuery={text => go({ query: text })} />
}
