import { useState } from 'react'
import { useApi } from '../hooks/useApi'

// Schwab / Fidelity proposals + manual submit (operator 2026-06-19). Same features for both brokers:
// a manual-submit form (maps to a manual proposal + strategy in the unified queue) and a proposals list
// with a Submit action — Schwab routes via gated 2FA (prepared, no live order yet), Fidelity is
// record-only (no trading API; execute at the broker).
const MUTED = '#94a3b8', TEXT0 = '#f8fafc', TEXT1 = '#dbeafe', GREEN = '#22c55e', AMBER = '#f59e0b', BLUE = '#60a5fa', PURPLE = '#a78bfa', RED = '#ef4444'
const card = { background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 12, padding: 14 } as const
const inp = { fontSize: 12, padding: '6px 9px', borderRadius: 7, border: '1px solid rgba(148,163,184,.3)', background: 'rgba(15,23,42,.55)', color: TEXT0, width: '100%' } as const
const btn = (c: string, busy = false) => ({ fontSize: 11, fontWeight: 800, padding: '6px 13px', borderRadius: 7, border: `1px solid ${c}`, background: `${c}1f`, color: c, cursor: busy ? 'not-allowed' as const : 'pointer' as const, whiteSpace: 'nowrap' as const })

export default function BrokerProposals({ focusSymbol }: { focusSymbol?: string } = {}) {
  const { data, refetch } = useApi<any>('/api/v2/broker-proposals', 30_000)
  const { data: outcomesData } = useApi<any>('/api/v2/rec-intel/outcomes', 300_000)   // purchased→sold history per symbol
  const { data: fvStrip } = useApi<any>('/api/v2/finviz-strip-map', 300_000)
  const fvMap: Record<string, any> = fvStrip?.map ?? {}
  const outMap: Record<string, any> = outcomesData?.outcomes ?? {}
  const accounts: any[] = data?.accounts ?? []
  const strategies: string[] = data?.strategies ?? []
  const proposals: any[] = data?.proposals ?? []
  const [f, setF] = useState<any>({ account: '', symbol: '', shares: '', entry: '', stop: '', target: '', strategy_id: '' })
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)
  const [routeMsg, setRouteMsg] = useState<Record<number, string>>({})
  const [heldOnly, setHeldOnly] = useState(false)
  // Deep-link focus from a Reports approval action (?symbol=NEE&modal=approval) — show JUST that symbol's
  // proposal first, with a banner to clear back to all.
  const [focus, setFocus] = useState((focusSymbol || '').toUpperCase())
  const isHeld = (sym: string) => !!outMap[String(sym).toUpperCase()]?.held
  const heldN = proposals.filter(p => isHeld(p.symbol)).length
  let shown = heldOnly ? proposals.filter(p => isHeld(p.symbol)) : proposals
  if (focus && proposals.some(p => String(p.symbol).toUpperCase() === focus)) shown = shown.filter(p => String(p.symbol).toUpperCase() === focus)
  const set = (k: string, v: any) => setF({ ...f, [k]: v })
  const brokerOf = (a: string) => (a || '').toLowerCase().startsWith('fidelity') ? 'Fidelity' : (a || '').toLowerCase().startsWith('schwab') ? 'Schwab' : '—'

  const submit = async () => {
    if (!(f.account && f.symbol && f.shares && f.entry && f.stop && f.target)) { setMsg('fill account, symbol, shares, entry, stop, target'); return }
    setBusy(true); setMsg('')
    try {
      const r = await fetch('/api/v2/broker-proposals/manual-submit', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ account: f.account, symbol: f.symbol.toUpperCase(), strategy_id: f.strategy_id || strategies[0],
          shares: Number(f.shares), entry: Number(f.entry), stop: Number(f.stop), target: Number(f.target) })
      }).then(x => x.json())
      const d = r.data ?? r
      if (d.success) { setMsg(`✅ Manual proposal #${d.proposal_id} created for ${f.symbol.toUpperCase()} (${brokerOf(f.account)})`); setF({ ...f, symbol: '', shares: '', entry: '', stop: '', target: '' }); refetch?.() }
      else setMsg(`⛔ ${d.message || d.error || 'failed'}`)
    } catch (e: any) { setMsg('⛔ ' + String(e).slice(0, 80)) } finally { setBusy(false) }
  }

  const route = async (pid: number) => {
    setRouteMsg({ ...routeMsg, [pid]: '…' })
    try {
      const r = await fetch('/api/v2/broker-proposals/route', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ proposal_id: pid }) }).then(x => x.json())
      const d = r.data ?? r
      const leg = d.order_spec?.orderLegCollection?.[0]
      const wouldSubmit = leg ? ` · would POST: ${leg.instruction} ${leg.quantity} ${leg.instrument?.symbol} ${d.order_spec.orderType} $${d.order_spec.price}` : ''
      const m = d.ok && d.record_only ? `📝 ${d.detail}` : d.gated ? `🔒 ${d.detail}${wouldSubmit}` : d.ok ? `✅ routed` : `⛔ ${d.error || d.detail || 'failed'}`
      setRouteMsg({ ...routeMsg, [pid]: m }); refetch?.()
    } catch (e: any) { setRouteMsg({ ...routeMsg, [pid]: '⛔ ' + String(e).slice(0, 60) }) }
  }

  return <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
    {focus && (
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 12px', borderRadius: 8, fontSize: 11.5, background: 'rgba(96,165,250,.1)', border: '1px solid rgba(96,165,250,.35)', color: '#93c5fd' }}>
        <span>Focused on <b style={{ fontFamily: 'monospace', color: TEXT0 }}>{focus}</b> approval (from Reports).{!proposals.some(p => String(p.symbol).toUpperCase() === focus) ? ' No matching proposal in the current queue.' : ''}</span>
        <button onClick={() => setFocus('')} style={{ marginLeft: 'auto', fontSize: 10.5, fontWeight: 700, padding: '3px 9px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg2)', color: MUTED, cursor: 'pointer' }}>show all</button>
      </div>
    )}
    <div style={{ fontSize: 10.5, color: MUTED }}>
      Schwab + Fidelity proposals share the unified queue. Manual submit maps to a manual proposal + strategy.
      <b style={{ color: AMBER }}> Schwab</b> routing is wired for 2FA submit but <b>disabled</b> (gated — no live order).
      <b style={{ color: PURPLE }}> Fidelity</b> has no trading API — submit is record-only (execute at Fidelity).
    </div>

    {/* Manual submit form */}
    <div style={card}>
      <div style={{ fontSize: 13, fontWeight: 800, color: TEXT0, marginBottom: 10 }}>Manual submit</div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10, fontSize: 11 }}>
        <label>Account
          <select style={inp} value={f.account} onChange={e => set('account', e.target.value)}>
            <option value="">— select —</option>
            {accounts.map(a => <option key={a.account_key} value={a.account_key}>{brokerOf(a.account_key)} · {a.display_name || a.account_key}</option>)}
          </select>
        </label>
        <label>Strategy
          <select style={inp} value={f.strategy_id} onChange={e => set('strategy_id', e.target.value)}>
            {strategies.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
        </label>
        <label>Symbol<input style={inp} value={f.symbol} onChange={e => set('symbol', e.target.value.toUpperCase())} placeholder="AAPL" /></label>
        <label>Shares<input style={inp} value={f.shares} onChange={e => set('shares', e.target.value.replace(/[^0-9]/g, ''))} /></label>
        <label>Entry<input style={inp} value={f.entry} onChange={e => set('entry', e.target.value)} /></label>
        <label>Stop<input style={inp} value={f.stop} onChange={e => set('stop', e.target.value)} /></label>
        <label>Target<input style={inp} value={f.target} onChange={e => set('target', e.target.value)} /></label>
        <div style={{ display: 'flex', alignItems: 'flex-end' }}>
          <button onClick={submit} disabled={busy} style={btn(GREEN, busy)}>{busy ? '…' : 'Create proposal'}</button>
        </div>
      </div>
      {msg && <div style={{ fontSize: 11, marginTop: 9, color: msg.startsWith('✅') ? GREEN : AMBER }}>{msg}</div>}
    </div>

    {/* Proposals list */}
    <div style={card}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10, flexWrap: 'wrap' }}>
        <div style={{ fontSize: 13, fontWeight: 800, color: TEXT0 }}>Schwab / Fidelity proposals ({shown.length}{heldOnly ? ` of ${proposals.length}` : ''})</div>
        <span style={{ flex: 1 }} />
        <button onClick={() => setHeldOnly(h => !h)} title="show only proposals for symbols you currently hold"
          style={{ fontSize: 10.5, fontWeight: 800, padding: '5px 11px', borderRadius: 6, cursor: 'pointer', whiteSpace: 'nowrap',
            border: `1px solid ${heldOnly ? '#60a5fa' : 'var(--border)'}`, background: heldOnly ? 'rgba(96,165,250,.14)' : 'transparent', color: heldOnly ? BLUE : MUTED }}>
          ● Held only{heldN ? ` (${heldN})` : ''}</button>
        {(heldOnly || Object.keys(routeMsg).length > 0) && (
          <button onClick={() => { setHeldOnly(false); setRouteMsg({}) }} title="clear filters + action messages"
            style={{ fontSize: 10.5, fontWeight: 700, padding: '5px 10px', borderRadius: 6, cursor: 'pointer', whiteSpace: 'nowrap', border: '1px solid var(--border)', background: 'transparent', color: MUTED }}>
            Reset all</button>
        )}
      </div>
      {proposals.length === 0 && <div style={{ fontSize: 11, color: MUTED }}>No Schwab/Fidelity proposals in the queue.</div>}
      {proposals.length > 0 && shown.length === 0 && <div style={{ fontSize: 11, color: MUTED }}>No held-symbol proposals. <span onClick={() => setHeldOnly(false)} style={{ color: BLUE, cursor: 'pointer', fontWeight: 700 }}>Show all</span></div>}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {shown.map(p => {
          const fid = brokerOf(p.account) === 'Fidelity'
          return <div key={p.id} style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap', padding: '8px 10px', borderRadius: 9, background: 'rgba(15,23,42,.5)', border: '1px solid rgba(148,163,184,.18)' }}>
            <span style={{ fontSize: 9, fontWeight: 800, padding: '2px 7px', borderRadius: 5, background: fid ? 'rgba(167,139,250,.18)' : 'rgba(245,158,11,.18)', color: fid ? PURPLE : AMBER }}>{brokerOf(p.account)}</span>
            <span style={{ fontSize: 13, fontWeight: 900, color: TEXT0 }}>{p.symbol}</span>
            {(() => { const fv = fvMap[String(p.symbol).toUpperCase()]; if (!fv) return null
              const pc = (v: any) => v == null ? MUTED : Number(v) > 0 ? GREEN : Number(v) < 0 ? RED : MUTED
              const rsiC = fv.rsi == null ? MUTED : fv.rsi >= 70 ? RED : fv.rsi <= 30 ? GREEN : TEXT1
              const c = (l: string, v: any, col: string, sfx = '') => <span style={{ fontSize: 9, color: MUTED }}>{l}<b style={{ color: col, fontFamily: 'monospace', marginLeft: 2 }}>{v == null ? '—' : `${Number(v) > 0 && sfx ? '+' : ''}${Number(v).toFixed(sfx ? 1 : 0)}${sfx}`}</b></span>
              return <span title="Finviz daily metrics" style={{ display: 'inline-flex', gap: 7, padding: '2px 7px', borderRadius: 5, background: 'rgba(96,165,250,.08)', border: '1px solid rgba(96,165,250,.18)' }}>{c('RSI ', fv.rsi, rsiC)}{c('W ', fv.perf_week, pc(fv.perf_week), '%')}{c('YTD ', fv.perf_ytd, pc(fv.perf_ytd), '%')}</span> })()}
            {(() => { const o = outMap[String(p.symbol).toUpperCase()]; return o?.origin
              ? <span title="auto-detected discovery origin — where this symbol was first surfaced in the lineage" style={{ fontSize: 8, fontWeight: 700, padding: '2px 6px', borderRadius: 4, background: 'rgba(96,165,250,.14)', color: BLUE }}>via {o.origin}</span>
              : null })()}
            {(() => { const o = outMap[String(p.symbol).toUpperCase()]; if (!o) return null
              const sold = (o.closed_trades ?? 0) > 0, up = (o.last_pnl_pct ?? 0) >= 0, hUp = (o.unrealized_pnl_pct ?? 0) >= 0
              const chip = (txt: string, c: string, tip: string) => <span title={tip} style={{ fontSize: 9, fontWeight: 800, padding: '2px 7px', borderRadius: 5, background: `${c}1f`, color: c }}>{txt}</span>
              return <>
                {o.held && chip(`● held ${hUp ? '+' : ''}${o.unrealized_pnl_pct ?? '?'}% unrl`, hUp ? BLUE : AMBER, `currently held${o.held_since ? ` since ${String(o.held_since).slice(0, 10)}` : ''}${o.origin ? ` · origin: ${o.origin}` : ''} · unrealized $${o.unrealized_pnl ?? '?'} (monitoring till sale)`)}
                {sold && chip(`✓ sold ${up ? '+' : ''}${o.last_pnl_pct ?? '?'}%${o.closed_trades > 1 ? ` ·${o.closed_trades}×` : ''}${o.journaled ? ' 📓' : ''}`, up ? GREEN : RED, `prior real closed trade(s)${o.origin ? ` · origin: ${o.origin}` : ''} · win rate ${o.win_rate_pct ?? '?'}% · total P&L $${o.total_pnl ?? '?'}${o.journaled ? ' · journaled' : ''}`)}
              </> })()}
            <span style={{ fontSize: 10.5, color: MUTED }}>{p.strategy_id} · {p.account}</span>
            <span style={{ fontSize: 10.5, color: TEXT1 }}>{p.proposed_shares} sh @ ${Number(p.proposed_entry).toFixed(2)} · stop ${Number(p.proposed_stop).toFixed(2)} · tgt ${Number(p.proposed_target1).toFixed(2)}{p.proposed_rr ? ` · R:R ${Number(p.proposed_rr).toFixed(1)}` : ''}</span>
            <span style={{ fontSize: 9, color: MUTED }}>{p.origin} · {p.routing_state}</span>
            <span style={{ flex: 1 }} />
            {routeMsg[p.id] && <span style={{ fontSize: 10, color: routeMsg[p.id].startsWith('✅') || routeMsg[p.id].startsWith('📝') ? GREEN : routeMsg[p.id].startsWith('🔒') ? PURPLE : AMBER }}>{routeMsg[p.id]}</span>}
            <button onClick={() => route(p.id)} style={btn(fid ? PURPLE : AMBER)} title={fid ? 'Record-only (no API)' : 'Schwab submit — gated 2FA, disabled'}>{fid ? 'Record' : 'Submit (2FA)'}</button>
          </div>
        })}
      </div>
    </div>
  </div>
}
