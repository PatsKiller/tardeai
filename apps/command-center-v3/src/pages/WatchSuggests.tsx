/** Watch › System Suggests — what the system proposes for your list (operator 2026-10-23: "where is the automated
 *  watch list, the stuff that the system is proposing for me?").
 *
 *  GET /api/v3/data-broker/watch-curation?n=20 (scripts/lib/data_broker/watch_curation.py): the top N (default 20,
 *  max 30) of the SAME ranked list Watch › Full universe shows (the CIO curator's rank), minus what you hold, what is
 *  already yours and what you dismissed — every skip and every entry / exit named. Rows are the same rows Prospects
 *  shows. "Add to my watchlist" and the ★ on each row → POST /api/v3/watch/commands/mine (the operator star + a
 *  logged watchlist_events row); "Dismiss" → POST /api/v3/watch/commands/suggest-dismiss (recorded in the
 *  watchlist_events log with who and why; 30 days; "Restore" undoes it). Nothing here sizes or orders. */
import { useMemo, useState, type CSSProperties } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import { FONT, RADIUS, TOKENS, TYPE, chipStyle } from '../lib/designTokens'
import { TOOLTIPS, alertIntel, proposeSeed, type ProspectRow } from '../lib/watchProspectsModel'
import { armedBySymbol, askCioReview, unwrapAny, type ListRow } from '../lib/watchListsModel'
import { Detail, GRID, Row } from './WatchProspects'
import { laneWord } from './WatchMyList'
import { MINE_TIPS, mineAction } from '../components/watch/MineControls'
import WatchlistProposeModal, { type WatchlistProposeSeed } from '../components/WatchlistProposeModal'
import ReEntryAlertArmModal from '../components/reentry/ReEntryAlertArmModal'

const panel: CSSProperties = { background: TOKENS.bg[1], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.lg, minWidth: 0 }
const head: CSSProperties = { fontSize: TYPE.xs, fontWeight: 700, letterSpacing: '.06em', textTransform: 'uppercase', color: TOKENS.text[2] }
const btn = (tone: 'success' | 'neutral' | 'info'): CSSProperties => ({ ...chipStyle(tone, 'outline', 'sm'), cursor: 'pointer', whiteSpace: 'nowrap' })

async function post(path: string, body: unknown): Promise<any> {
  const r = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
  const j = await r.json().catch(() => ({}))
  const d = j?.data ?? j
  if (!r.ok || d?.ok === false) throw new Error(d?.error || d?.detail || `HTTP ${r.status}`)
  return d
}

export default function WatchSuggests() {
  const [sp, setSp] = useSearchParams()
  const n = Math.max(1, Math.min(30, Number(sp.get('n') || 20) || 20))
  const [bump, setBump] = useState(0)
  const { data: raw, loading, error, refetch } = useApi<any>(`/api/v3/data-broker/watch-curation?n=${n}${bump ? `&fresh=1&_=${bump}` : ''}`, 120_000)
  const { data: alertsRaw } = useApi<any>('/api/v2/watch/alerts/list', 120_000)
  const c = useMemo(() => unwrapAny<any>(raw), [raw])
  const armed = useMemo(() => armedBySymbol(alertsRaw), [alertsRaw])
  const [sel, setSel] = useState<string | null>(null)
  const [msg, setMsg] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState('')
  const [proposeFor, setProposeFor] = useState<WatchlistProposeSeed | null>(null)
  const [alertFor, setAlertFor] = useState<ProspectRow | null>(null)
  const [cioMsg, setCioMsg] = useState('')
  const s = c?.suggests
  const rows: ListRow[] = s?.rows || []
  const selected = rows.find(r => r.symbol === sel) || null
  const say = (sym: string, text: string) => setMsg(m => ({ ...m, [sym]: text }))

  const add = async (r: ListRow) => {
    setBusy(r.symbol)
    const res = await mineAction(r.symbol, 'add', `From System Suggests (#${r.universe_rank ?? '?'} in the Full universe)`, 'watch.system_suggests')
    say(r.symbol, res.message)
    if (res.ok) setBump(b => b + 1)
    setBusy('')
  }
  const dismiss = async (r: ListRow) => {
    const reason = window.prompt(`Dismiss ${r.symbol} from System Suggests for 30 days. Reason (optional):`, '')
    if (reason === null) return
    setBusy(r.symbol)
    try {
      await post('/api/v3/watch/commands/suggest-dismiss', { symbol: r.symbol, reason, universe_rank: r.universe_rank, conviction: r.conviction })
      say(r.symbol, 'Dismissed for 30 days.')
      setBump(b => b + 1)
    } catch (e) { say(r.symbol, `Could not dismiss: ${String((e as Error).message || e).slice(0, 100)}`) }
    setBusy('')
  }
  const restore = async (sym: string) => {
    setBusy(sym)
    try { await post('/api/v3/watch/commands/suggest-restore', { symbol: sym }); setBump(b => b + 1) }
    catch (e) { say(sym, `Could not restore: ${String((e as Error).message || e).slice(0, 100)}`) }
    setBusy('')
  }
  const onStep = (r: ProspectRow) => {
    setSel(r.symbol)
    if (r.next_action.kind === 'propose') setProposeFor(proposeSeed(r) as WatchlistProposeSeed)
    else if (r.next_action.kind === 'set_alert') setAlertFor(r)
  }

  if (!c) {
    return <div data-testid="watch-suggests" style={{ ...panel, padding: 16, color: TOKENS.text[2] }}>
      {loading ? 'Loading suggestions…' : `Suggestions unavailable${error ? ` — ${String(error)}` : ''}.`}
      {!loading && <button type="button" onClick={() => refetch()} style={{ marginLeft: 8, ...btn('info') }}>Retry</button>}
    </div>
  }
  const rot = s?.rotation || {}
  const skipped = s?.skipped || {}
  return (
    <div data-testid="watch-suggests" style={{ display: 'flex', flexDirection: 'column', gap: 8, fontSize: TYPE.md, color: TOKENS.text[0] }}>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center' }}>
        <span style={{ fontSize: TYPE.base + 1, color: TOKENS.text[1] }} title={`Ranking: ${c.ranking?.label} — curator run ${c.ranking?.as_of || '—'}. Same list as Watch › Full universe.`}>
          Top <b>{s?.n}</b> of <b>{s?.eligible}</b> eligible from the Full universe ranking ({s?.ranked} ranked)
        </span>
        <label style={{ fontSize: TYPE.sm, color: TOKENS.text[2] }} title="How many suggestions to keep (default 20, max 30). Kept in the URL.">
          Show{' '}
          <select value={n} onChange={e => { const x = new URLSearchParams(sp); x.set('n', e.target.value); setSp(x, { replace: true }) }}
            style={{ fontSize: TYPE.sm, background: TOKENS.bg[2], color: TOKENS.text[0], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.sm }}>
            {[10, 20, 30].map(v => <option key={v} value={v}>{v}</option>)}
          </select>
        </label>
        <span style={{ fontSize: TYPE.sm, color: TOKENS.text[3] }}
          title="Names the ranking reaches that are not suggested: you hold them (see Prospects › Manage), they are already yours (My Watchlist), or you dismissed them.">
          skipped: {skipped.held?.length ?? 0} held · {skipped.mine?.length ?? 0} yours · {skipped.dismissed?.length ?? 0} dismissed
        </span>
        <span style={{ fontSize: TYPE.sm, color: rot.available ? TOKENS.text[2] : TOKENS.warning }} title={rot.rule}>
          {rot.available ? `rotation vs the curator run of ${String(rot.previous_run_at || '').slice(11, 16)} UTC` : rot.unavailable_reason}
        </span>
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, alignItems: 'flex-start' }}>
        <section aria-label="System Suggests" style={{ ...panel, flex: '999 1 700px', overflowX: 'auto' }}>
          <div style={{ minWidth: 760 }}>
            <div style={{ display: 'grid', gridTemplateColumns: GRID, gap: 8, padding: '6px 12px', borderBottom: `1px solid ${TOKENS.borderSubtle}`, ...head }}>
              <span title="★ = on your watchlist. The # is the rank in the Full universe (the curator's conviction order).">★ Symbol · #</span>
              <span title={TOOLTIPS.conviction}>Conviction</span><span title={TOOLTIPS.stance}>Stance</span>
              <span title="Why it is suggested (entered / steady / holding, with the reason) · stage">Why suggested · stage</span>
              <span title={TOOLTIPS.trigger}>Next trigger</span>
              <span title={`${TOOLTIPS.step} Add puts it on My Watchlist; Dismiss hides it for 30 days.`}>Next step · your call</span>
            </div>
            {rows.length === 0 && <div style={{ padding: 12, color: TOKENS.text[2] }}>Nothing to suggest right now.</div>}
            {rows.map(r => {
              const sg = r.suggestion!
              return (
                <div key={r.symbol} data-testid="suggest-row" data-symbol={r.symbol}>
                  <Row r={{ ...r, why: `${sg.status === 'listed' ? sg.reason : `#${sg.universe_rank} · ${sg.status}: ${sg.reason}`}${sg.top_factor ? ` · ${sg.top_factor}` : ''} · ${laneWord(r.lane)}` }}
                    selected={sel === r.symbol} onSelect={() => setSel(r.symbol)} onStep={onStep} alerts={armed[r.symbol] || 0}
                    onMineChanged={m => { say(r.symbol, m); setBump(b => b + 1) }}
                    extra={<>
                      <button type="button" disabled={busy === r.symbol} onClick={() => add(r)} data-testid="suggest-add" style={btn('success')}
                        title={`${MINE_TIPS.starOff} It then leaves Suggests with the reason “added to your watchlist”.`}>Add</button>
                      <button type="button" disabled={busy === r.symbol} onClick={() => dismiss(r)} data-testid="suggest-dismiss" style={btn('neutral')}
                        title="Hides it from Suggests for 30 days. Recorded with who, when and why (watchlist_events). Restore any time below.">Dismiss</button>
                      {msg[r.symbol] && <span role="status" style={{ fontSize: TYPE.xs, color: TOKENS.text[2], width: '100%' }}>{msg[r.symbol]}</span>}
                    </>} />
                </div>
              )
            })}
          </div>
        </section>
        <aside aria-label="Record" style={{ ...panel, flex: '1 1 300px', maxWidth: 440, padding: 12 }}>
          <Detail r={selected} cioMsg={cioMsg} onAskCio={async r => { setCioMsg('Queuing…'); setCioMsg(await askCioReview(r.symbol, `Watch conflict: ${r.conflicts.map(x => x.summary).join(' | ')}`)) }} />
        </aside>
      </div>
      {(s?.left || []).length > 0 && (
        <div style={{ ...panel, padding: '8px 12px' }} data-testid="suggest-left">
          <span style={head} title={rot.rule}>Left the list since the last curator run</span>
          {(s.left as any[]).map(l => <div key={l.symbol} style={{ fontSize: TYPE.base }}><b style={{ fontFamily: FONT.mono }}>{l.symbol}</b> — {l.reason}</div>)}
        </div>
      )}
      {(s?.dismissed || []).length > 0 && (
        <div style={{ ...panel, padding: '8px 12px' }} data-testid="suggest-dismissed">
          <span style={head}>Dismissed by you ({s.dismissed.length})</span>
          {(s.dismissed as any[]).map(d => (
            <div key={d.symbol} style={{ fontSize: TYPE.base, display: 'flex', gap: 6, alignItems: 'center' }}>
              <b style={{ fontFamily: FONT.mono }}>{d.symbol}</b>
              <span style={{ color: TOKENS.text[2] }}>{String(d.at || '').slice(0, 10)}{d.reason ? ` — ${d.reason}` : ''} · until {String(d.until || '').slice(0, 10)}</span>
              <button type="button" onClick={() => restore(d.symbol)} style={btn('info')} title="Undo the dismissal (recorded as a restore in watchlist_events).">Restore</button>
            </div>
          ))}
        </div>
      )}
      {proposeFor && <WatchlistProposeModal seed={proposeFor} onClose={() => setProposeFor(null)} onProposed={() => refetch()} />}
      {alertFor && <ReEntryAlertArmModal symbol={alertFor.symbol} intel={alertIntel(alertFor)} noteTag="watch-suggests"
        onClose={() => setAlertFor(null)} onArmed={() => setAlertFor(null)} />}
    </div>
  )
}
