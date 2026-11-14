/** Watch v002 — My List / Suggestions / Prospects (LQ-20261107-2993b).
 *
 *  Each tab reads ONE paged list (shape=list, 25 rows) with its own as_of, grades it (OK / STALE / UNKNOWN with age) and
 *  never turns an unread list into an empty one. Actions reuse the existing writes: star/add/remove →
 *  POST /api/v3/watch/commands/mine; dismiss/restore → /suggest-dismiss, /suggest-restore. Detail opens the symbol page.
 *  Watching only — no order, no size, no stop. */
import { useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import './WatchListsV002.css'
import { mineAction } from '../components/watch/MineControls'
import {
  curationUrl, dismissedSet, gradeCuration, gradeProspects, pagingOf, pagingText, prospectsUrl, rowView,
  type DismissedItem, type ListGrade, type ListKey, type ListPaging, type ListRowView,
} from '../lib/watchListsV002'

const TABS: { key: ListKey; label: string }[] = [
  { key: 'mine', label: 'My List' }, { key: 'suggests', label: 'Suggestions' }, { key: 'prospects', label: 'Prospects' },
]

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
  onTab: (k: ListKey) => void
  onStar: (r: ListRowView) => void
  onDismiss: (r: ListRowView) => void
  onRestore: (r: ListRowView) => void
  onPage: (offset: number) => void
  onRetry: () => void
}

export function WatchListsV002View(p: ListsViewProps) {
  return (
    <section className="v010 wl2" data-testid="watch-lists-v002">
      <nav className="wl2-tabs" role="tablist" aria-label="Watch lists">
        {TABS.map(t => (
          <button key={t.key} type="button" role="tab" aria-selected={p.tab === t.key} data-testid={`watch-tab-${t.key}`}
            className="wl2-tab" onClick={() => p.onTab(t.key)}>{t.label}</button>
        ))}
      </nav>
      <div className="wl2-asof" data-testid="watch-list-asof" data-state={p.grade?.state ?? (p.loading ? 'LOADING' : 'UNKNOWN')}>
        <span className={`v010-pill ${p.grade?.state === 'OK' ? 'ok' : p.grade?.state === 'STALE' ? 'warn' : p.loading ? '' : 'bad'}`}>{p.loading ? 'LOADING' : p.grade?.state ?? 'UNKNOWN'}</span>
        <span>{p.loading ? 'Loading…' : p.grade ? `${p.grade.label.replace(/^[A-Z]+ · /, '')} · ${p.grade.basis.replace(/_/g, ' ')}` : 'list could not be read'}</span>
        {p.grade?.reason ? <span className="wl2-why">{p.grade.reason}</span> : null}
      </div>
      {p.error && <div className="wl2-note bad" data-testid="watch-list-error" role="alert">List could not be read: {p.error} <button type="button" className="v010-btn" onClick={p.onRetry}>Retry</button></div>}
      {p.tab === 'suggests' && !p.loading && p.dismissedStatus !== 'ok' && p.dismissedStatus !== 'absent' && (
        <div className="wl2-note warn" data-testid="watch-dismissed-unknown" role="alert">Dismissed set could not be read ({p.dismissedStatus}); dismissed names may show.</div>
      )}
      {p.message && <div className="wl2-note" data-testid="watch-list-message" role="status">{p.message}</div>}
      {p.loading || (p.error && p.rows.length === 0) ? null : p.rows.length === 0 ? (
        // An unreadable list is never an empty list (REVIEW-2993r R4): UNKNOWN / a declared gap / no total => could not be read.
        p.gap || !p.grade || p.grade.state === 'UNKNOWN' || p.paging.total === null ? (
          <div className="wl2-note bad" data-testid="watch-list-unreadable" role="alert">
            List could not be read{p.gap ? `: ${p.gap}` : ''}. <button type="button" className="v010-btn" onClick={p.onRetry}>Retry</button>
          </div>
        ) : (
          <div className="wl2-note" data-testid="watch-list-empty">{p.paging.total === 0 ? 'No names in this list.' : 'Nothing on this page.'}</div>
        )
      ) : (
        <ul className="wl2-rows" data-testid="watch-list-rows">
          {p.rows.map(r => (
            <li key={r.symbol} className="wl2-row" data-testid={`watch-row-${r.symbol}`} data-dismissed={r.dismissed ? '1' : '0'}>
              <div className="wl2-main">
                {p.tab !== 'prospects' && (
                  <button type="button" className="wl2-star" aria-pressed={r.starred} aria-label={r.starred ? `Remove ${r.symbol} from My List` : `Add ${r.symbol} to My List`}
                    data-testid={`watch-star-${r.symbol}`} onClick={() => p.onStar(r)}>{r.starred ? '★' : '☆'}</button>
                )}
                <Link className="v010-link wl2-sym" to={r.detailHref} data-testid={`watch-detail-${r.symbol}`}>{r.symbol}</Link>
                {r.company && <span className="wl2-co">{r.company}</span>}
                <span className="v010-pill">{r.stage}</span>
                {r.held && <span className="v010-pill info">{r.held}</span>}
                <span className="wl2-conv">{r.conviction === null ? 'no score' : `conviction ${Math.round(r.conviction)}`}</span>
              </div>
              {r.nextAction && <div className="wl2-next">{r.nextAction}</div>}
              {r.why && <div className="wl2-why">{r.why}</div>}
              {p.tab === 'suggests' && !r.dismissed && (
                <button type="button" className="v010-btn" data-testid={`watch-dismiss-${r.symbol}`} onClick={() => p.onDismiss(r)}>Dismiss 30 d</button>)}
            </li>
          ))}
        </ul>
      )}
      {p.tab === 'suggests' && p.dismissedItems.length > 0 && (
        <details className="wl2-dismissed" data-testid="watch-dismissed" open>
          <summary>Dismissed ({p.dismissedItems.length})</summary>
          <ul className="wl2-rows">
            {p.dismissedItems.map(d => (
              <li key={d.symbol} className="wl2-row" data-testid={`watch-dismissed-${d.symbol}`}>
                <strong>{d.symbol}</strong>{d.reason && <span>{d.reason}</span>}{d.until && <span>until {d.until.slice(0, 10)}</span>}
                <button type="button" className="v010-btn" data-testid={`watch-restore-${d.symbol}`} onClick={() => p.onRestore({ symbol: d.symbol } as ListRowView)}>Restore</button>
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

/** The parent keys this by tab, so a tab switch remounts it: useApi keeps its last body across a path change, and a body from
 *  another list must not be graded or parsed by this one (review 2993ab-v2r N4; same defect as 2993cr R4). */
export function WatchListsTab({ tab, onTab }: { tab: ListKey; onTab: (k: ListKey) => void }) {
  const [offset, setOffset] = useState(0)
  const [message, setMessage] = useState('')
  const url = tab === 'prospects' ? prospectsUrl('forming', offset) : curationUrl(tab, offset)
  const { data, loading, error, refetch } = useApi<any>(url, 120_000)
  const body = useMemo(() => (data && typeof data === 'object' ? ((data as any).data ?? data) : null), [data])
  const nowMs = Date.now()
  const grade = body ? (tab === 'prospects' ? gradeProspects(body, nowMs) : gradeCuration(body, tab, nowMs)) : null
  const dis = dismissedSet(body)
  const section = tab === 'mine' ? body?.my_watchlist : tab === 'suggests' ? body?.suggests : { rows: (body?.lanes || []).flatMap((l: any) => l?.items || []), pagination: body?.pagination }
  const rows = (Array.isArray(section?.rows) ? section.rows : []).map((r: unknown) => rowView(r, dis.symbols)).filter(Boolean) as ListRowView[]
  const act = async (fn: () => Promise<string>) => {
    try { setMessage(await fn()); refetch() } catch (e) { setMessage(`Failed: ${String((e as Error).message || e).slice(0, 100)}`) }
  }
  return (
    <WatchListsV002View
      tab={tab} grade={grade} rows={rows} paging={pagingOf(section)} offset={offset} loading={loading && !body}
      error={error ? String(error) : null} gap={gapOf(body, section)} message={message} dismissedStatus={body?.suggests ? dis.status : 'absent'} dismissedItems={dis.items}
      onTab={onTab}
      onStar={r => void act(async () => { const res = await mineAction(r.symbol, r.starred ? 'remove' : 'add', undefined, 'watch.v002'); if (!res.ok) throw new Error(res.message); return res.message })}
      onDismiss={r => void act(async () => { await post('/api/v3/watch/commands/suggest-dismiss', { symbol: r.symbol }); return `${r.symbol} dismissed for 30 days.` })}
      onRestore={r => void act(async () => { await post('/api/v3/watch/commands/suggest-restore', { symbol: r.symbol }); return `${r.symbol} restored.` })}
      onPage={setOffset} onRetry={() => refetch()}
    />
  )
}

export default function WatchListsV002() {
  const [sp, setSp] = useSearchParams()
  const tab = listKey(sp.get('list'))
  return <WatchListsTab key={tab} tab={tab} onTab={k => setSp({ list: k })} />
}
