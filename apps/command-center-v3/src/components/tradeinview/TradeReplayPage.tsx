/** Historical review reads the store-only replay projection. No provider fallback or client performance math. */
import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useApi } from '../../hooks/useApi'
import { FONT, RADIUS, TOKENS, TYPE, chipStyle, numStyle } from '../../lib/designTokens'
import { buildReplayTrade } from '../../lib/replayTrade'
import { etShort, pct, plText, px, type Journey, type JourneysPayload } from '../../lib/tradeJourneyModel'
import { replayPayload, responseReason, serverMoney, serverNumber, storedReplayPath } from '../../lib/tradeInViewModel'
import TradeReplayChart from '../TradeReplayChart'
import TradeCompareReplay from './TradeCompareReplay'
import './TradeInViewLayout.css'

export default function TradeReplayPage({ payload, loading, error }: { payload: JourneysPayload | null; loading?: boolean; error?: string | null }) {
  const [params, setParams] = useSearchParams()
  const [search, setSearch] = useState(''), [compare, setCompare] = useState(false)
  const journeys = payload?.journeys || []
  const id = params.get('trade') || journeys[0]?.trade_id || ''
  const interval = params.get('interval') || '1D'
  const api = useApi<any>(storedReplayPath(id, interval), undefined, { enabled: !!id })
  const data = replayPayload(api.data, { trade_id: id, interval }), journey = journeys.find(j => j.trade_id === id)
  const trip = data?.trade
  const found = journeys.filter(j => `${j.symbol} ${j.account_label || ''}`.toLowerCase().includes(search.toLowerCase()))
  const pick = (tradeId: string) => { const n = new URLSearchParams(params); n.set('trade', tradeId); n.delete('interval'); setParams(n, { replace: true }) }
  const trade = buildReplayTrade({ symbol: data?.symbol || journey?.symbol || '', trade_id: id, account: data?.account_id || journey?.account || undefined,
    entry_date: trip?.entry_date || journey?.entry.at, exit_date: trip?.exit_date || journey?.exit?.at,
    entry_price: trip?.entry_price ?? journey?.entry.price_ref, exit_price: trip?.exit_price ?? journey?.exit?.price_ref,
    entry_time: trip?.entry_at || journey?.entry.at, exit_time: trip?.exit_at || journey?.exit?.at })
  return <section className="tradeinview-replay-layout" data-testid="trade-replay-page">
    <aside className="tradeinview-panel tradeinview-replay-picker">
      <label style={{ color: TOKENS.text[2], fontSize: TYPE.base }}>Find a trade<input aria-label="Find a trade" placeholder="Symbol or account name" value={search} onChange={e => setSearch(e.target.value)} style={{ ...input, width: '100%', boxSizing: 'border-box', marginTop: 6 }} /></label>
      {found.map(j => <button type="button" key={j.trade_id} data-trade-id={j.trade_id} aria-pressed={id === j.trade_id} onClick={() => pick(j.trade_id)} style={{ background: id === j.trade_id ? TOKENS.bg[3] : 'transparent', border: `1px solid ${id === j.trade_id ? TOKENS.info : TOKENS.border}`, borderRadius: RADIUS.md, color: TOKENS.text[0] }}><span style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}><b style={{ fontFamily: FONT.mono }}>{j.symbol}</b><span style={numStyle}>{plText(j)}</span></span><span style={{ display: 'block', color: TOKENS.text[2], fontSize: TYPE.sm }}>{j.entry.at ? etShort(j.entry.at) : 'Entry time unavailable'} → {j.exit?.at ? etShort(j.exit.at) : j.status === 'open' ? 'Open' : 'Exit time unavailable'}</span><span style={{ color: TOKENS.text[2], fontSize: TYPE.sm }}>{j.account_label || 'Unlabelled account'}</span></button>)}
      {!found.length && <div className="tradeinview-gap">{loading ? 'Loading trade picker…' : error ? `Journeys unavailable — ${error}` : 'No trades match this view. Older trade links can still resolve by recorded trade ID.'}</div>}
    </aside>
    <section className="tradeinview-panel" style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 12, fontSize: TYPE.base }}>
      <div className="tradeinview-heading"><h2 style={{ margin: 0, fontSize: TYPE.lg }}><span style={{ fontFamily: FONT.mono }}>{data?.symbol || journey?.symbol || 'Select a trade'}</span>{data?.account_label || journey?.account_label ? ` · ${data?.account_label || journey?.account_label}` : ''}</h2>
        <div className="tradeinview-controls">{data?.available_intervals.filter(i => ['1D', '15m', '5m'].includes(i)).map(i => <button type="button" key={i} aria-pressed={data.interval === i} onClick={() => { const n = new URLSearchParams(params); n.set('interval', i); setParams(n, { replace: true }) }} style={{ ...chipStyle(data.interval === i ? 'warning' : 'neutral', data.interval === i ? 'soft' : 'outline', 'md'), cursor: 'pointer' }}>{i}</button>)}<button type="button" onClick={() => setCompare(true)} disabled={!journeys.some(j => j.trade_id !== id && j.pl.amount != null && j.pl.amount > 0)} title="Compare against another recorded winning trade in the loaded Journeys window; unavailable when no such trade is supplied." style={{ ...chipStyle('info', 'soft', 'md'), cursor: 'pointer' }}>⇄ Compare with a win</button></div>
      </div>
      {trip ? <div className="tradeinview-gap">Bought {px(trip.entry_price)} {trip.entry_at ? etShort(trip.entry_at) : trip.entry_date || 'date unavailable'} → {trip.exit_price == null ? 'Exit unavailable' : `sold ${px(trip.exit_price)}`} {trip.exit_at ? etShort(trip.exit_at) : trip.exit_date || ''} · {serverMoney(trip.realized_pl)} · held {serverNumber(trip.hold_days)} days{trip.hold_days_basis ? ` (${trip.hold_days_basis})` : ''}{trip.basis_unknown ? ` · ${trip.basis_reason || 'Basis unknown'}` : ''}</div>
        : journey ? <div className="tradeinview-gap">Bought {px(journey.entry.price_ref)} {journey.entry.at ? etShort(journey.entry.at) : 'date unavailable'} → {journey.status === 'closed' ? `sold ${px(journey.exit?.price_ref)}` : 'Open'} · {plText(journey)} · held {serverNumber(journey.hold_days)} days</div>
          : !!id && <div className="tradeinview-gap">Summary unavailable in the loaded Journeys window.</div>}
      {!id ? <div className="tradeinview-gap">Choose a recorded trade to replay.</div> : !data ? <div role="status" className="tradeinview-gap">{api.loading ? 'Loading stored bars…' : `Stored replay unavailable — ${api.error || responseReason(api.data) || 'response schema unavailable'}`}</div> : <>
        {api.stale && <div role="status" style={{ color: TOKENS.warning }}>Refresh unavailable — last successful replay snapshot.</div>}
        <TradeReplayChart key={`${id}:${data.interval}`} trade={trade} embedded providedData={data} onClose={() => {}} />
        <div className="tradeinview-replay-stats">
          <Stat label={data.stats.metrics_basis.toLowerCase().includes('proxy') ? 'Max gain · session-range proxy' : 'Max gain while held'} value={pct(data.stats.max_gain_pct)} reason={data.stats.max_gain_pct == null ? data.stats.metrics_missing_reason : data.stats.metrics_basis} />
          <Stat label={data.stats.metrics_basis.toLowerCase().includes('proxy') ? 'Max drawdown · session-range proxy' : 'Max drawdown while held'} value={pct(data.stats.max_drawdown_pct)} reason={data.stats.max_drawdown_pct == null ? data.stats.metrics_missing_reason : data.stats.metrics_basis} />
          <Stat label="Exit type" value={data.stats.exit_label || 'Unknown'} reason={data.stats.exit_basis} />
          {data.stats.coach_note && <Stat label="Coach note · stored advisory" value={data.stats.coach_note} reason="Matched stored coaching note." />}
        </div>
        <div className="tradeinview-gap" style={{ fontSize: TYPE.sm }}>Source {data.source.table || 'unavailable'} · observed {data.source.as_of || 'time unavailable'} · {data.source.bar_basis} · collection {data.as_of}</div>
        {data.markers.length > 0 && <details><summary>Recorded fills, stops and CIO annotations</summary>{data.markers.map((m, i) => <div key={`${m.kind}-${m.at}-${i}`} style={{ padding: '4px 0' }}>{m.label} · {m.source} · {m.at || 'time unavailable'}</div>)}</details>}
        {data.gaps.map((g, i) => <div key={`${g.source}-${i}`} role="note" className="tradeinview-gap">{g.source}: {g.reason}</div>)}
      </>}
      {compare && <TradeCompareReplay trades={journeys.map(replayChoice)} initialTradeId={id} storedOnly onClose={() => setCompare(false)} />}
    </section>
  </section>
}
function replayChoice(j: Journey) { return { ...buildReplayTrade({ symbol: j.symbol, trade_id: j.trade_id, account: j.account || undefined, entry_date: j.entry.at, exit_date: j.exit?.at, entry_price: j.entry.price_ref, exit_price: j.exit?.price_ref, entry_time: j.entry.at, exit_time: j.exit?.at }), pnl: j.pl.amount, account_label: j.account_label } }
function Stat({ label, value, reason }: { label: string; value: string; reason?: string | null }) { return <div style={{ padding: 10, background: TOKENS.bg[2], borderRadius: RADIUS.md, minWidth: 0, overflowWrap: 'anywhere' }}><div style={{ color: TOKENS.text[2], fontSize: TYPE.sm }}>{label}</div><div style={{ ...numStyle, marginTop: 6 }}>{value}</div>{reason && <div className="tradeinview-gap" style={{ fontSize: TYPE.sm, marginTop: 4 }}>{reason}</div>}</div> }
const input = { padding: '8px 10px', background: TOKENS.bg[0], color: TOKENS.text[0], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.sm, fontSize: TYPE.base }
