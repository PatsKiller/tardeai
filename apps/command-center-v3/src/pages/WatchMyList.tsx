import ListPager, { useListOffset } from '../components/ListPager'
/** Watch › My Watchlist (default tab) — the operator's own names (operator 2026-10-23: "I don't see stuff that I had
 *  starred that I was watching ... where is my traditional watch list").
 *
 *  Reads GET /api/v3/data-broker/watch-curation (scripts/lib/data_broker/watch_curation.py): every name you starred,
 *  your personal watchlist, your watch directives and names you added or proposed — starred first, never dropped by a
 *  lane cap or by expiry (an expired signal only suggests a review). Each row is the SAME row the Prospects lanes show
 *  (one composition, watch_prospects.gather), plus the position facts: held / formerly held, the last trade and the
 *  re-entry advice. Position filters are URL parameters applied on the server. Actions reuse existing flows only. */
import { useMemo, useState, type CSSProperties } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import { FONT, RADIUS, TOKENS, TYPE, chipStyle } from '../lib/designTokens'
import { TOOLTIPS, alertIntel, proposeSeed, type ProspectRow } from '../lib/watchProspectsModel'
import { armedBySymbol, positionQuery, unwrapAny, withQuery, type ListRow } from '../lib/watchListsModel'
import { Detail, Row, WatchConflictDetail, askFromRow, conflictSection } from './WatchProspects'
import { useCioReview } from '../components/watch/CioReview'
import { asksCio } from '../lib/watchProspectsModel'
import {useConflictSheet} from '../components/conflicts/ConflictSheet'
import {MobileDetailSheet, useMobilePageDetail} from '../components/MobileDetailSheet'
import './W9Mobile.css'
import PositionFilterBar from '../components/watch/PositionFilterBar'
import { AddSymbolBox, MINE_TIPS, RemoveButton } from '../components/watch/MineControls'
import WatchlistProposeModal, { type WatchlistProposeSeed } from '../components/WatchlistProposeModal'
import ReEntryAlertArmModal from '../components/reentry/ReEntryAlertArmModal'
import { WatchCardHeader } from '../components/watch/WatchRecordCard'

const panel: CSSProperties = { background: TOKENS.bg[1], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.lg, minWidth: 0 }
const head: CSSProperties = { fontSize: TYPE.xs, fontWeight: 700, letterSpacing: '.06em', textTransform: 'uppercase', color: TOKENS.text[2] }
const KINDS: [string, string, string][] = [
  ['', 'All', 'Every name that is yours, for any reason.'],
  ['starred', '★ Starred', 'Names you starred (operator_starred_symbols).'],
  ['personal_watchlist', 'Personal list', 'Your traditional personal watchlist (watchlist_items source personal_watchlist).'],
  ['directive', 'Directives', 'Your active ticker watch directives (watch_directives created by you).'],
  ['operator_added', 'Added / proposed', 'Names you added or proposed (watchlist_items with operator origin).'],
]

export default function WatchMyList() {
  const [sp, setSp] = useSearchParams()
  const pq = positionQuery(sp)
  const paging = useListOffset(JSON.stringify(pq) + (sp.get('mine') || ''))
  const { data: raw, loading, error, stale: snapshotStale, refetch } = useApi<any>(withQuery('/api/v3/data-broker/watch-curation', { ...pq, mine: sp.get('mine') || '', view: 'mine', offset: String(paging.offset), limit: '25' }), 120_000)
  const { data: alertsRaw } = useApi<any>('/api/v2/watch/alerts/list', 120_000)
  const c = useMemo(() => unwrapAny<any>(raw), [raw])
  const armed = useMemo(() => armedBySymbol(alertsRaw), [alertsRaw])
  const detail = useMobilePageDetail('symbol')
  const sheet = useConflictSheet()
  const sel = detail.id
  const setSel = (symbol: string | null) => symbol ? detail.open(symbol) : detail.close()
  const openConflict = (row: ProspectRow, key = conflictSection(row).findings[0]?.key) => {
    if (!key) {detail.open(row.symbol); return}
    const next = new URLSearchParams(sp); next.set('symbol', row.symbol); next.set('conflict', key)
    setSp(next, {state: {w9DetailOpened: true}})
  }
  const [proposeFor, setProposeFor] = useState<WatchlistProposeSeed | null>(null)
  const [alertFor, setAlertFor] = useState<ProspectRow | null>(null)
  const [toast, setToast] = useState('')
  const cio = useCioReview(refetch)
  const kind = sp.get('mine') || ''
  const mw = c?.my_watchlist
  const refreshUnavailable = snapshotStale || Boolean(error)
  const rows: ListRow[] = (mw?.rows || []).filter((r: ListRow) => !kind || (kind === 'starred' ? r.starred : (r.membership || []).some(m => m.kind === kind)))
  const selected = rows.find(r => r.symbol === sel) || null
  const onStep = (r: ProspectRow) => {
    if (asksCio(r.next_action.kind)) {askFromRow(r, cio, openConflict, setSel); return}
    setSel(r.symbol)
    if (r.next_action.kind === 'propose') setProposeFor(proposeSeed(r) as WatchlistProposeSeed)
    else if (r.next_action.kind === 'set_alert') setAlertFor(r)
  }
  const changed = (m: string) => { setToast(m); refetch() }
  if (!c) {
    return <div className="w9-page" data-testid="watch-my-list" style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <AddSymbolBox onAdded={changed} />
      <div style={{ ...panel, padding: 16, color: TOKENS.text[2] }}>
        {loading ? 'Loading your watchlist…' : `Your watchlist is unavailable${error ? ` — ${String(error)}` : ''}.`}
        {!loading && <button type="button" onClick={() => refetch()} style={{ marginLeft: 8, ...chipStyle('info', 'outline', 'md'), cursor: 'pointer' }}>Retry</button>}
      </div>
    </div>
  }
  const srcCount = (k: string) => (mw?.sources?.[k]?.count ?? 0)
  // Server counts cover the full filtered list (W2). A response without paging carries the complete list,
  // so its rows can be counted exactly; a paged response without kind_counts stays unknown ('—').
  const completeRows: ListRow[] | null = mw && !mw.pagination && Array.isArray(mw.rows) ? mw.rows : null
  const rowCount = (k: string) => completeRows == null ? null : k === '' ? completeRows.length
    : k === 'starred' ? completeRows.filter(r => r.starred).length
      : completeRows.filter(r => (r.membership || []).some(m => m.kind === k)).length
  const kindCount = (k: string) => mw?.kind_counts?.[k || 'all'] ?? (k === '' ? mw?.count : null) ?? rowCount(k) ?? '—'
  const failed = Object.entries(mw?.sources || {}).filter(([, v]: any) => v?.status !== 'ok')
  return (
    <div className="w9-page" data-testid="watch-my-list" style={{ display: 'flex', flexDirection: 'column', gap: 8, fontSize: TYPE.md, color: TOKENS.text[0] }}>
      <AddSymbolBox onAdded={changed} />
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center' }}>
        <span style={{ fontSize: TYPE.base + 1, color: TOKENS.text[1] }}
          title="Your names are never dropped by a cap or by expiry. When a signal expires the row says so and suggests a review; only you remove a name.">
          {['conv', 'stance', 'stage'].some(k => sp.get(k)) ? <><b>{rows.length} of {mw?.unfiltered_count ?? rows.length}</b> · {sp.get('conv') ? `conviction ${sp.get('conv') === 'none' ? 'no score' : sp.get('conv') === 'lt60' ? '< 60' : `≥ ${sp.get('conv')}`}` : ''}{sp.get('stance') ? ` · stance ${sp.get('stance')}` : ''}{sp.get('stage') ? ` · setup ${sp.get('stage')}` : ''}</>
            : <><b>{mw?.unfiltered_count ?? rows.length}</b> names are yours</>} · <b>{mw?.starred ?? 0}</b> starred · never capped, never expired
        </span>
        {KINDS.map(([k, l, tip]) => (
          <button key={k || 'all'} type="button" aria-pressed={kind === k} data-testid={`mine-kind-${k || 'all'}`}
            title={`${tip} Filters your complete list on the server (${k ? srcCount(k) : (mw?.unfiltered_count ?? 0)} from the source).`}
            onClick={() => { paging.reset(); const n = new URLSearchParams(sp); if (k) n.set('mine', k); else n.delete('mine'); setSp(n, { replace: true }) }}
            style={{ ...chipStyle(kind === k ? 'info' : 'neutral', kind === k ? 'soft' : 'outline', 'sm'), cursor: 'pointer' }}>
            {l} <b>{kindCount(k)}</b>
          </button>
        ))}
        {c.interim && <span title={TOOLTIPS.source({ interim: true } as any)} style={{ fontFamily: FONT.mono, fontSize: TYPE.xs, color: TOKENS.warning }}>{c.source_label}</span>}
      </div>
      {failed.length > 0 && <div style={{ color: TOKENS.warning, fontSize: TYPE.base }}>Could not read: {failed.map(([k, v]: any) => `${k} (${v.error || v.status})`).join(', ')} — names from that source are missing, not removed.</div>}
      <PositionFilterBar specs={mw?.position_filters} facets={mw?.position_facets} testId="mine-position-filters" />
      {toast && <div role="status" style={{ ...chipStyle('success', 'soft', 'md'), alignSelf: 'flex-start' }}>{toast}</div>}
      {refreshUnavailable && <div role="status" data-testid="watch-market-refresh-warning" style={{ color: TOKENS.warning, fontSize: TYPE.base }}>
        Refresh unavailable — showing the last successful snapshot. Values and observation times have not been refreshed.
      </div>}
      <ListPager page={mw?.pagination} previous={paging.previous} next={paging.next} busy={loading} gap={mw?.payload_gap} />
      <div className="watch-card-list-viewport">
        <section className="watch-record-panel" aria-label="My Watchlist" style={{ minWidth: 0 }}>
          <div className="watch-record-table watch-card-list">
            <WatchCardHeader />
            {rows.length === 0 && <div data-testid="mine-empty" style={{ padding: 12, color: TOKENS.text[2] }}>{(mw?.filters && Object.keys(mw.filters).length) || kind ? `None of your names match these filters. ${MINE_TIPS.empty}` : MINE_TIPS.empty}</div>}
            {rows.map(r => (
              <div key={r.symbol} className="watch-my-list-market-record" data-testid="mine-row" data-symbol={r.symbol}>
                <Row r={r} selected={sel === r.symbol} onSelect={() => setSel(r.symbol)} onStep={onStep} onOpenConflict={openConflict} cio={cio} alerts={armed[r.symbol] || 0}
                  retained={refreshUnavailable} onAlert={r => setAlertFor(r)} onMineChanged={changed} extra={<RemoveButton symbol={r.symbol} onChanged={changed} />} />
              </div>
            ))}
          </div>
        </section>
        {selected && !sheet.key && !detail.mobile && <aside className="watch-card-detail" aria-label="Record" style={panel}>
          <button type="button" autoFocus onClick={() => setSel(null)} style={{ ...chipStyle('neutral', 'outline', 'md'), minHeight: 44, cursor: 'pointer' }}>Back to list</button>
          <Detail r={selected} cio={cio} onOpenConflict={key => openConflict(selected, key)} />
        </aside>}
        {selected && !sheet.key && detail.mobile && <MobileDetailSheet title={`${selected.symbol} · watch record`} onBack={detail.close}>
          <Detail r={selected} cio={cio} onOpenConflict={key => openConflict(selected, key)} />
        </MobileDetailSheet>}
        {selected && sheet.key && <WatchConflictDetail row={selected} onBack={sheet.close} onRefresh={refetch} />}
      </div>
      {proposeFor && <WatchlistProposeModal seed={proposeFor} onClose={() => setProposeFor(null)}
        onProposed={res => { setToast(res.message || `${res.symbol} queued as proposal #${res.proposal_id}`); refetch() }} />}
      {alertFor && <ReEntryAlertArmModal symbol={alertFor.symbol} intel={alertIntel(alertFor)} noteTag="watch-my-list"
        onClose={() => setAlertFor(null)} onArmed={summary => { setToast(`${alertFor.symbol}: armed ${summary}`); setAlertFor(null) }} />}
    </div>
  )
}

export function laneWord(lane: string): string {
  return ({ actionable: 'Actionable', forming: 'Forming', reentry: 'Re-entry near', manage: 'Held', expired: 'Expired' } as Record<string, string>)[lane] || lane
}
