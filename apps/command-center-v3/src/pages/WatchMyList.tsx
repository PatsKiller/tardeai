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
import { armedBySymbol, askCioReview, positionQuery, unwrapAny, withQuery, type ListRow } from '../lib/watchListsModel'
import { Detail, GRID, Row } from './WatchProspects'
import PositionFilterBar from '../components/watch/PositionFilterBar'
import WatchlistProposeModal, { type WatchlistProposeSeed } from '../components/WatchlistProposeModal'
import ReEntryAlertArmModal from '../components/reentry/ReEntryAlertArmModal'

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
  const { data: raw, loading, error, refetch } = useApi<any>(withQuery('/api/v3/data-broker/watch-curation', pq), 120_000)
  const { data: alertsRaw } = useApi<any>('/api/v2/watch/alerts/list', 120_000)
  const c = useMemo(() => unwrapAny<any>(raw), [raw])
  const armed = useMemo(() => armedBySymbol(alertsRaw), [alertsRaw])
  const [sel, setSel] = useState<string | null>(null)
  const [proposeFor, setProposeFor] = useState<WatchlistProposeSeed | null>(null)
  const [alertFor, setAlertFor] = useState<ProspectRow | null>(null)
  const [toast, setToast] = useState('')
  const [cioMsg, setCioMsg] = useState('')
  const kind = sp.get('mine') || ''
  const mw = c?.my_watchlist
  const rows: ListRow[] = (mw?.rows || []).filter((r: ListRow) => !kind || (kind === 'starred' ? r.starred : (r.membership || []).some(m => m.kind === kind)))
  const selected = rows.find(r => r.symbol === sel) || null
  const onStep = (r: ProspectRow) => {
    setSel(r.symbol)
    if (r.next_action.kind === 'propose') setProposeFor(proposeSeed(r) as WatchlistProposeSeed)
    else if (r.next_action.kind === 'set_alert') setAlertFor(r)
  }
  if (!c) {
    return <div data-testid="watch-my-list" style={{ ...panel, padding: 16, color: TOKENS.text[2] }}>
      {loading ? 'Loading your watchlist…' : `Your watchlist is unavailable${error ? ` — ${String(error)}` : ''}.`}
      {!loading && <button type="button" onClick={() => refetch()} style={{ marginLeft: 8, ...chipStyle('info', 'outline', 'md'), cursor: 'pointer' }}>Retry</button>}
    </div>
  }
  const srcCount = (k: string) => (mw?.sources?.[k]?.count ?? 0)
  const kindCount = (k: string) => k === '' ? (mw?.rows || []).length : k === 'starred' ? (mw?.rows || []).filter((r: ListRow) => r.starred).length
    : (mw?.rows || []).filter((r: ListRow) => (r.membership || []).some(m => m.kind === k)).length
  const failed = Object.entries(mw?.sources || {}).filter(([, v]: any) => v?.status !== 'ok')
  return (
    <div data-testid="watch-my-list" style={{ display: 'flex', flexDirection: 'column', gap: 8, fontSize: TYPE.md, color: TOKENS.text[0] }}>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center' }}>
        <span style={{ fontSize: TYPE.base + 1, color: TOKENS.text[1] }}
          title="Your names are never dropped by a cap or by expiry. When a signal expires the row says so and suggests a review; only you remove a name.">
          <b>{mw?.unfiltered_count ?? rows.length}</b> names are yours · <b>{mw?.starred ?? 0}</b> starred · never capped, never expired
        </span>
        {KINDS.map(([k, l, tip]) => (
          <button key={k || 'all'} type="button" aria-pressed={kind === k} data-testid={`mine-kind-${k || 'all'}`}
            title={`${tip} Narrows this list in the browser (${k ? srcCount(k) : (mw?.unfiltered_count ?? 0)} from the source).`}
            onClick={() => { const n = new URLSearchParams(sp); if (k) n.set('mine', k); else n.delete('mine'); setSp(n, { replace: true }) }}
            style={{ ...chipStyle(kind === k ? 'info' : 'neutral', kind === k ? 'soft' : 'outline', 'sm'), cursor: 'pointer' }}>
            {l} <b>{kindCount(k)}</b>
          </button>
        ))}
        {c.interim && <span title={TOOLTIPS.source({ interim: true } as any)} style={{ fontFamily: FONT.mono, fontSize: TYPE.xs, color: TOKENS.warning }}>{c.source_label}</span>}
      </div>
      {failed.length > 0 && <div style={{ color: TOKENS.warning, fontSize: TYPE.base }}>Could not read: {failed.map(([k, v]: any) => `${k} (${v.error || v.status})`).join(', ')} — names from that source are missing, not removed.</div>}
      <PositionFilterBar specs={mw?.position_filters} facets={mw?.position_facets} testId="mine-position-filters" />
      {toast && <div role="status" style={{ ...chipStyle('success', 'soft', 'md'), alignSelf: 'flex-start' }}>{toast}</div>}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, alignItems: 'flex-start' }}>
        <section aria-label="My Watchlist" style={{ ...panel, flex: '999 1 700px', overflowX: 'auto' }}>
          <div style={{ minWidth: 760 }}>
            <div style={{ display: 'grid', gridTemplateColumns: GRID, gap: 8, padding: '6px 12px', borderBottom: `1px solid ${TOKENS.borderSubtle}`, ...head }}>
              <span>Symbol</span><span title={TOOLTIPS.conviction}>Conviction</span><span title={TOOLTIPS.stance}>Stance</span>
              <span title="Stage and why · the last trade and re-entry for names you sold · what is missing">Stage · last trade · missing</span>
              <span title={TOOLTIPS.trigger}>Next trigger</span><span title={TOOLTIPS.step}>Next step</span>
            </div>
            {rows.length === 0 && <div style={{ padding: 12, color: TOKENS.text[2] }}>{mw?.filters && Object.keys(mw.filters).length ? 'None of your names match these filters.' : 'No names yet — star a name or add one from System Suggests.'}</div>}
            {rows.map(r => (
              <div key={r.symbol} data-testid="mine-row" data-symbol={r.symbol}>
                <Row r={{ ...r, why: `${laneWord(r.lane)} · ${r.why}` }} selected={sel === r.symbol} onSelect={() => setSel(r.symbol)} onStep={onStep} alerts={armed[r.symbol] || 0} />
              </div>
            ))}
          </div>
        </section>
        <aside aria-label="Record" style={{ ...panel, flex: '1 1 300px', maxWidth: 440, padding: 12 }}>
          <Detail r={selected} cioMsg={cioMsg} onAskCio={async r => { setCioMsg('Queuing…'); setCioMsg(await askCioReview(r.symbol, `Watch conflict: ${r.conflicts.map(x => x.summary).join(' | ')}`)) }} />
        </aside>
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
