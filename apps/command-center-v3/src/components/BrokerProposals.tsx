import { useCallback, useEffect, useRef, useState } from 'react'
import { useApi } from '../hooks/useApi'
import ManualExecutionModal, { type ManualExecSeed } from './ManualExecutionModal'
import BrokerPromoteModal, { type BrokerPromoteSeed } from './BrokerPromoteModal'
import BrokerIntelPanel from './BrokerIntelPanel'
import ManualExecutionLog from './ManualExecutionLog'
import ExecutionPathsStrip from './ExecutionPathsStrip'

const MUTED = '#94a3b8', TEXT0 = '#f8fafc', TEXT1 = '#dbeafe', GREEN = '#22c55e', AMBER = '#f59e0b', BLUE = '#60a5fa', PURPLE = '#a78bfa', RED = '#ef4444'
const card = { background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 12, padding: 14 } as const
const inp = { fontSize: 12, padding: '6px 9px', borderRadius: 7, border: '1px solid rgba(148,163,184,.3)', background: 'rgba(15,23,42,.55)', color: TEXT0, width: '100%' } as const
const btn = (c: string, busy = false) => ({ fontSize: 11, fontWeight: 800, padding: '6px 13px', borderRadius: 7, border: `1px solid ${c}`, background: `${c}1f`, color: c, cursor: busy ? 'not-allowed' as const : 'pointer' as const, whiteSpace: 'nowrap' as const })

export default function BrokerProposals({ focusSymbol }: { focusSymbol?: string } = {}) {
  const { data, loading, error, stale, refetch } = useApi<any>('/api/v2/broker-proposals', 30_000)
  const { data: outcomesData } = useApi<any>('/api/v2/rec-intel/outcomes', 300_000)

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
  const [focus, setFocus] = useState((focusSymbol || '').toUpperCase())
  const [modalSeed, setModalSeed] = useState<ManualExecSeed | null>(null)
  const [adjustSeed, setAdjustSeed] = useState<BrokerPromoteSeed | null>(null)
  const [destAccount, setDestAccount] = useState<Record<number, string>>({})
  const [oversightBusy, setOversightBusy] = useState<Record<number, boolean>>({})
  const [cloudBusy, setCloudBusy] = useState<Record<number, boolean>>({})
  const [oversightMsg, setOversightMsg] = useState<Record<number, string>>({})
  const [acctPreview, setAcctPreview] = useState<Record<number, { account: string; evaluation: any; activity: any; loading?: boolean }>>({})
  const [acctPreviewBusy, setAcctPreviewBusy] = useState<Record<number, boolean>>({})
  const [detailMap, setDetailMap] = useState<Record<number, any>>({})
  const [detailBusy, setDetailBusy] = useState<Record<number, boolean>>({})
  const detailLoadedRef = useRef<Set<number>>(new Set())
  const detailInflightRef = useRef<Set<number>>(new Set())

  const fetchProposalDetail = useCallback(async (pid: number) => {
    if (detailLoadedRef.current.has(pid) || detailInflightRef.current.has(pid)) return
    detailInflightRef.current.add(pid)
    setDetailBusy(b => ({ ...b, [pid]: true }))
    try {
      const r = await fetch('/api/v2/broker-proposals/detail', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ proposal_id: pid }),
      }).then(x => x.json())
      const d = r.data ?? r
      if (r.ok && d?.id) {
        detailLoadedRef.current.add(pid)
        setDetailMap(prev => ({ ...prev, [pid]: d }))
      }
    } catch { /* keep fast list row */ }
    finally {
      detailInflightRef.current.delete(pid)
      setDetailBusy(b => ({ ...b, [pid]: false }))
    }
  }, [])

  useEffect(() => {
    if (!proposals.length) return
    // Defer heavy detail enrichment so the fast list isn't blocked behind 60s+ intel/oversight work.
    const t = setTimeout(() => {
      for (const p of proposals) {
        if (p.detail_pending) fetchProposalDetail(p.id)
      }
    }, 2000)
    return () => clearTimeout(t)
  }, [proposals, fetchProposalDetail])

  const mergeProposal = (p: any) => ({ ...p, ...(detailMap[p.id] || {}) })

  useEffect(() => {
    if (!proposals.length) return
    setDestAccount(prev => {
      const next = { ...prev }
      for (const p of proposals) {
        if (!next[p.id]) next[p.id] = p.account || accounts[0]?.account_key || ''
      }
      return next
    })
  }, [proposals, accounts])

  const isHeld = (sym: string) => !!outMap[String(sym).toUpperCase()]?.held
  const heldN = proposals.filter(p => isHeld(p.symbol)).length
  let shown = heldOnly ? proposals.filter(p => isHeld(p.symbol)) : proposals
  if (focus && proposals.some(p => String(p.symbol).toUpperCase() === focus)) shown = shown.filter(p => String(p.symbol).toUpperCase() === focus)
  const set = (k: string, v: any) => setF({ ...f, [k]: v })
  const brokerOf = (a: string) => (a || '').toLowerCase().startsWith('fidelity') ? 'Fidelity' : (a || '').toLowerCase().startsWith('schwab') ? 'Schwab' : '—'
  const refreshAll = () => { refetch?.() }

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
      if (d.success) { setMsg(`✅ Manual proposal #${d.proposal_id} created for ${f.symbol.toUpperCase()} (${brokerOf(f.account)})`); setF({ ...f, symbol: '', shares: '', entry: '', stop: '', target: '' }); refreshAll() }
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

  const openManual = (p: any) => {
    const acct = destAccount[p.id] || p.account || accounts[0]?.account_key || ''
    setModalSeed({ symbol: p.symbol, account: acct, proposal_id: p.id, execution_type: 'equity' })
  }

  const gateColor = (s: string) => s === 'PASS' ? GREEN : s === 'WARN' ? AMBER : s === 'BLOCK' ? RED : MUTED

  const queueOversight = async (pid: number) => {
    setOversightBusy(m => ({ ...m, [pid]: true }))
    setOversightMsg(m => ({ ...m, [pid]: '' }))
    try {
      const r = await fetch('/api/v2/broker-proposals/queue-oversight', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ proposal_id: pid }),
      }).then(x => x.json())
      setOversightMsg(m => ({ ...m, [pid]: r.ok ? '✅ Local reviews queued' : `⛔ ${r.error || 'failed'}` }))
      if (r.ok) setTimeout(() => refetch?.(), 4000)
    } catch (e: any) {
      setOversightMsg(m => ({ ...m, [pid]: '⛔ ' + String(e).slice(0, 60) }))
    } finally {
      setOversightBusy(m => ({ ...m, [pid]: false }))
    }
  }

  const buildBrokerSizing = (ev: any, shares: number) => {
    const maxSh = Number(ev?.max_shares ?? 0)
    return {
      max_shares: maxSh,
      recommended_shares: ev?.recommended_shares,
      oversized: Boolean(shares && maxSh && shares > maxSh),
      binding: ev?.sizing?.binding,
      violations: ev?.violations || [],
      warnings: ev?.warnings || [],
    }
  }

  const tradeEconomics = (shares: number, entry: number, stop: number, target: number) => {
    const sh = Number(shares) || 0
    const en = Number(entry) || 0
    const st = Number(stop) || 0
    const tg = Number(target) || 0
    const riskPs = Math.max(0, en - st)
    const rewardPs = Math.max(0, tg - en)
    return {
      shares: sh,
      investment: sh && en ? sh * en : null,
      max_risk: sh && riskPs ? riskPs * sh : null,
      profit_at_target: sh && rewardPs ? rewardPs * sh : null,
    }
  }

  const fetchAccountPreview = useCallback(async (p: any, acct: string) => {
    if (!acct) return
    const pid = p.id
    if (acct === (p.account || '')) {
      setAcctPreview(prev => { const n = { ...prev }; delete n[pid]; return n })
      return
    }
    setAcctPreviewBusy(b => ({ ...b, [pid]: true }))
    try {
      const r = await fetch('/api/v2/broker-proposals/evaluate-promote', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          proposal_id: pid,
          account: acct,
          strategy_id: p.strategy_id,
          shares: Number(p.proposed_shares),
          entry: Number(p.proposed_entry),
          stop: Number(p.proposed_stop),
          target: Number(p.proposed_target1),
        }),
      }).then(x => x.json())
      const ev = r.data ?? r
      const meta = accounts.find(a => a.account_key === acct)
      setAcctPreview(prev => ({
        ...prev,
        [pid]: {
          account: acct,
          evaluation: ev,
          activity: meta?.activity || ev.account_activity || ev.sizing,
        },
      }))
    } catch {
      setAcctPreview(prev => ({ ...prev, [pid]: { account: acct, evaluation: null, activity: null } }))
    } finally {
      setAcctPreviewBusy(b => ({ ...b, [pid]: false }))
    }
  }, [accounts])

  const onDestAccountChange = (p: any, acct: string) => {
    setDestAccount(prev => ({ ...prev, [p.id]: acct }))
    fetchAccountPreview(p, acct)
  }

  const runCloudOversight = async (pid: number) => {
    setCloudBusy(m => ({ ...m, [pid]: true }))
    setOversightMsg(m => ({ ...m, [pid]: 'Running Grok+ChatGPT…' }))
    try {
      const r = await fetch('/api/v2/broker-proposals/run-cloud-oversight', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ proposal_id: pid, timeout: 120 }),
      }).then(x => x.json())
      const payload = r.data ?? r
      if (r.ok) {
        const v = payload.cloud?.consensus?.verdict || payload.oversight?.status || 'done'
        setOversightMsg(m => ({ ...m, [pid]: `✅ Cloud: ${v}` }))
        refetch?.()
      } else {
        setOversightMsg(m => ({ ...m, [pid]: `⛔ ${r.error || payload.error || 'failed'}` }))
      }
    } catch (e: any) {
      setOversightMsg(m => ({ ...m, [pid]: '⛔ ' + String(e).slice(0, 60) }))
    } finally {
      setCloudBusy(m => ({ ...m, [pid]: false }))
    }
  }

  return <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
    {modalSeed && (
      <ManualExecutionModal seed={modalSeed} onClose={() => setModalSeed(null)} onLogged={refreshAll} />
    )}
    {adjustSeed && (
      <BrokerPromoteModal seed={adjustSeed} mode="adjust" onClose={() => setAdjustSeed(null)} onPromoted={refreshAll} />
    )}

    {focus && (
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 12px', borderRadius: 8, fontSize: 11.5, background: 'rgba(96,165,250,.1)', border: '1px solid rgba(96,165,250,.35)', color: '#93c5fd' }}>
        <span>Focused on <b style={{ fontFamily: 'monospace', color: TEXT0 }}>{focus}</b> approval (from Reports).{!proposals.some(p => String(p.symbol).toUpperCase() === focus) ? ' No matching proposal in the current queue.' : ''}</span>
        <button onClick={() => setFocus('')} style={{ marginLeft: 'auto', fontSize: 10.5, fontWeight: 700, padding: '3px 9px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg2)', color: MUTED, cursor: 'pointer' }}>show all</button>
      </div>
    )}

    <ExecutionPathsStrip variant="live" />
    <div style={{ fontSize: 10.5, color: MUTED }}>
      <b style={{ color: TEXT0 }}>Path B — Live execution queue</b> (promoted from Proposals).
      <b style={{ color: BLUE }}> Schwab:</b> auto API submit when pilot armed (per-order 2FA) or execute manually at Schwab then log.
      <b style={{ color: GREEN }}> Fidelity:</b> place in <b>Active Trader Pro (FA)</b> — no API — then <b style={{ color: AMBER }}>Executed manually</b>.
      {' '}Use <b style={{ color: AMBER }}>✎ Edit trade</b> to adjust size/risk before routing.
    </div>

    <ManualExecutionLog mode="equity" onRefresh={refreshAll} />

    <div style={card}>
      <div style={{ fontSize: 13, fontWeight: 800, color: TEXT0, marginBottom: 10 }}>Manual submit</div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10, fontSize: 11 }}>
        <label>Destination account
          <select style={inp} value={f.account} onChange={e => set('account', e.target.value)}>
            <option value="">— select —</option>
            {accounts.map(a => <option key={a.account_key} value={a.account_key}>{brokerOf(a.account_key)} · {a.display_name || a.account_key}{a.auto_eligible ? ' (auto+manual)' : ' (manual)'}</option>)}
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

    <div style={card}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10, flexWrap: 'wrap' }}>
        <div style={{ fontSize: 13, fontWeight: 800, color: TEXT0 }}>Broker proposals queue ({shown.length}{heldOnly ? ` of ${proposals.length}` : ''})</div>
        <span style={{ flex: 1 }} />
        <button onClick={() => refetch?.()} disabled={loading} title="Reload broker queue"
          style={{ fontSize: 10.5, fontWeight: 700, padding: '5px 10px', borderRadius: 6, cursor: loading ? 'not-allowed' : 'pointer', whiteSpace: 'nowrap', border: '1px solid var(--border)', background: 'transparent', color: MUTED }}>
          {loading ? '…' : '↻ Refresh'}</button>
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
      {loading && proposals.length === 0 && !error && (
        <div style={{ fontSize: 11, color: MUTED }}>
          Loading broker queue…{stale ? ' (showing last good data when available)' : ''}
        </div>
      )}
      {error && proposals.length === 0 && (
        <div style={{ fontSize: 11, color: AMBER }}>
          Broker queue unavailable ({error}) — retrying…{' '}
          <span onClick={() => refetch?.()} style={{ color: BLUE, cursor: 'pointer', fontWeight: 700 }}>Refresh now</span>
        </div>
      )}
      {stale && proposals.length > 0 && <div style={{ fontSize: 10, color: AMBER, marginBottom: 8 }}>Showing cached queue — reconnecting…</div>}
      {!loading && !error && proposals.length === 0 && <div style={{ fontSize: 11, color: MUTED }}>No Schwab/Fidelity proposals in the queue.</div>}
      {proposals.length > 0 && shown.length === 0 && <div style={{ fontSize: 11, color: MUTED }}>No held-symbol proposals. <span onClick={() => setHeldOnly(false)} style={{ color: BLUE, cursor: 'pointer', fontWeight: 700 }}>Show all</span></div>}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {shown.map(rawP => {
          const p = mergeProposal(rawP)
          const dest = destAccount[p.id] ?? p.account ?? ''
          const detailLoading = Boolean(rawP.detail_pending && !detailMap[p.id] && detailBusy[p.id])
          const preview = acctPreview[p.id]
          const usingPreview = Boolean(preview && preview.account === dest && dest !== (p.account || ''))
          const evalData = usingPreview ? preview?.evaluation : p.evaluation
          const fid = brokerOf(dest || p.account) === 'Fidelity' || p.execution_mode === 'manual'
          const fmt = (n: number | null | undefined) => n == null ? '—' : n >= 1000 ? `$${(n / 1000).toFixed(1)}k` : `$${Math.round(n)}`
          const gate = evalData?.status || p.gate_status
          const ov = evalData?.oversight || p.oversight || p.intel?.oversight || p.evaluation?.oversight || {}
          const ovStatus = ov.status || (ov.violations?.length ? 'BLOCK' : ov.warnings?.length ? 'WARN' : null)
          const bs = usingPreview && evalData ? buildBrokerSizing(evalData, Number(p.proposed_shares)) : (p.broker_sizing || {})
          const oversized = bs.oversized
          const maxSh = bs.max_shares ?? evalData?.max_shares ?? p.evaluation?.max_shares
          const recSh = bs.recommended_shares ?? evalData?.recommended_shares
          const gateBlocked = gate === 'BLOCK' || ovStatus === 'BLOCK'
          const acctMeta = accounts.find(a => a.account_key === dest)
          const activity = usingPreview ? (preview?.activity || acctMeta?.activity) : (acctMeta?.activity || p.activity)
          const sizingViolations = bs.violations?.length ? bs.violations : (evalData?.violations || p.evaluation?.violations || [])
          const savedEcon = tradeEconomics(Number(p.proposed_shares), Number(p.proposed_entry), Number(p.proposed_stop), Number(p.proposed_target1))
          const previewSh = usingPreview && recSh != null ? Number(recSh) : null
          const showSized = previewSh != null && previewSh > 0 && previewSh !== savedEcon.shares
          const dispEcon = showSized
            ? tradeEconomics(previewSh!, Number(p.proposed_entry), Number(p.proposed_stop), Number(p.proposed_target1))
            : savedEcon
          const intel = p.intel?.ok ? {
            ...p.intel,
            oversight: { ...ov, status: ovStatus || ov.status, violations: ov.violations, warnings: ov.warnings },
          } : p.intel
          return (
            <div key={p.id} style={{ borderRadius: 12, background: 'rgba(15,23,42,.55)', border: '1px solid rgba(148,163,184,.2)', overflow: 'hidden' }}>
              <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap', padding: '10px 12px', borderBottom: '1px solid rgba(148,163,184,.12)' }}>
                <span style={{ fontSize: 9, fontWeight: 800, padding: '3px 8px', borderRadius: 5, background: fid ? 'rgba(167,139,250,.18)' : 'rgba(245,158,11,.18)', color: fid ? PURPLE : AMBER }}>{p.execution_label || (fid ? 'Manual · Fidelity' : 'Schwab · auto or manual')}</span>
                <span style={{ fontSize: 15, fontWeight: 900, color: TEXT0, fontFamily: 'monospace' }}>{p.symbol}</span>
                <span style={{ fontSize: 9, fontWeight: 700, padding: '3px 8px', borderRadius: 5, background: 'rgba(249,115,22,.14)', color: '#fb923c' }}>{p.strategy_id}</span>
                {gate && (
                  <span style={{ fontSize: 9, fontWeight: 800, padding: '3px 8px', borderRadius: 5, background: `${gateColor(gate)}22`, color: gateColor(gate) }}>
                    GATE {gate}
                  </span>
                )}
                {ovStatus && (
                  <span style={{ fontSize: 9, fontWeight: 800, padding: '3px 8px', borderRadius: 5, background: `${gateColor(ovStatus)}18`, color: ovStatus === 'PASS' ? PURPLE : gateColor(ovStatus) }}>
                    AI {ovStatus}
                  </span>
                )}
                {oversized && maxSh != null && (
                  <span style={{ fontSize: 9, fontWeight: 800, padding: '3px 8px', borderRadius: 5, background: 'rgba(239,68,68,.15)', color: RED }}>
                    OVERSIZED · max {Number(maxSh).toLocaleString()} sh
                  </span>
                )}
                {(() => { const fv = fvMap[String(p.symbol).toUpperCase()]; if (!fv) return null
                  const pc = (v: any) => v == null ? MUTED : Number(v) > 0 ? GREEN : Number(v) < 0 ? RED : MUTED
                  const rsiC = fv.rsi == null ? MUTED : fv.rsi >= 70 ? RED : fv.rsi <= 30 ? GREEN : TEXT1
                  const c = (l: string, v: any, col: string, sfx = '') => <span style={{ fontSize: 9, color: MUTED }}>{l}<b style={{ color: col, fontFamily: 'monospace', marginLeft: 2 }}>{v == null ? '—' : `${Number(v) > 0 && sfx ? '+' : ''}${Number(v).toFixed(sfx ? 1 : 0)}${sfx}`}</b></span>
                  return <span title="Finviz daily metrics" style={{ display: 'inline-flex', gap: 7, padding: '2px 7px', borderRadius: 5, background: 'rgba(96,165,250,.08)', border: '1px solid rgba(96,165,250,.18)' }}>{c('RSI ', fv.rsi, rsiC)}{c('W ', fv.perf_week, pc(fv.perf_week), '%')}{c('YTD ', fv.perf_ytd, pc(fv.perf_ytd), '%')}</span> })()}
                <span style={{ flex: 1 }} />
                {(acctPreviewBusy[p.id] || detailLoading) && <span style={{ fontSize: 9, color: MUTED }}>{detailLoading ? 'Loading gates…' : 'Sizing…'}</span>}
                <button onClick={() => setAdjustSeed({ proposal_id: p.id, symbol: p.symbol, account: dest })} style={{ ...btn(AMBER), fontSize: 12, padding: '7px 16px' }} title="Edit shares, entry, stop, target, spread-aware levels">
                  ✎ Edit trade
                </button>
              </div>

              {detailLoading && !intel?.ok && (
                <div style={{ padding: '10px 12px', fontSize: 10, color: MUTED, fontStyle: 'italic', borderBottom: '1px solid rgba(148,163,184,.12)' }}>
                  Loading decision context, sizing gates & oversight…
                </div>
              )}
              {intel?.ok && (
                <div style={{ padding: '10px 12px', borderBottom: '1px solid rgba(148,163,184,.12)', background: 'rgba(15,23,42,.35)' }}>
                  <BrokerIntelPanel
                    intel={intel}
                    compact
                    onQueueOversight={() => queueOversight(p.id)}
                    onRunCloudOversight={() => runCloudOversight(p.id)}
                    oversightBusy={!!oversightBusy[p.id]}
                    cloudBusy={!!cloudBusy[p.id]}
                  />
                  {oversightMsg[p.id] && (
                    <div style={{ fontSize: 9.5, marginTop: 6, color: oversightMsg[p.id].startsWith('✅') ? GREEN : AMBER }}>{oversightMsg[p.id]}</div>
                  )}
                </div>
              )}

              {activity && (
                <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', padding: '8px 12px', fontSize: 10, borderBottom: '1px solid rgba(148,163,184,.1)', background: usingPreview ? 'rgba(96,165,250,.06)' : 'rgba(34,197,94,.04)' }}>
                  <span style={{ color: MUTED }}>Sizing for <b style={{ color: TEXT0 }}>{dest}</b>{usingPreview ? ' (preview)' : ''}</span>
                  <span style={{ color: MUTED }}>Cash <b style={{ color: GREEN, fontFamily: 'monospace' }}>{fmt(activity.cash ?? activity.cash_available)}</b></span>
                  <span style={{ color: MUTED }}>Open <b style={{ color: TEXT0 }}>{activity.open_trades ?? '—'}</b>{activity.max_concurrent_positions != null ? ` / ${activity.max_concurrent_positions}` : ''}</span>
                  <span style={{ color: MUTED }}>New today <b style={{ color: (activity.daily_limit_reached) ? RED : TEXT0 }}>{activity.slots_used_today ?? activity.new_trades_today ?? 0}{activity.max_new_positions_per_day != null ? ` / ${activity.max_new_positions_per_day}` : ''}</b></span>
                  {recSh != null && oversized && (
                    <span style={{ color: AMBER }}>Resized cap <b style={{ fontFamily: 'monospace' }}>{Number(recSh).toLocaleString()} sh</b></span>
                  )}
                </div>
              )}

              {(gateBlocked || oversized) && (
                <div style={{ padding: '8px 12px', fontSize: 10, color: RED, background: 'rgba(239,68,68,.08)', borderBottom: '1px solid rgba(239,68,68,.2)' }}>
                  {oversized && maxSh != null && <div>⛔ {Number(p.proposed_shares).toLocaleString()} sh exceeds broker cap {Number(maxSh).toLocaleString()} — use ✎ Edit trade to resize.</div>}
                  {(ov.violations || []).map((v: string, i: number) => <div key={i}>⛔ {v}</div>)}
                  {sizingViolations.filter((v: string) => !(ov.violations || []).includes(v)).map((v: string, i: number) => <div key={`s${i}`}>⛔ {v}</div>)}
                </div>
              )}

              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))', gap: 8, padding: '10px 12px', fontSize: 10, background: showSized ? 'rgba(96,165,250,.04)' : undefined }}>
                {showSized && (
                  <div style={{ gridColumn: '1 / -1', fontSize: 9, color: BLUE, fontWeight: 700, marginBottom: -2 }}>
                    Sized for {dest} — {dispEcon.shares.toLocaleString()} sh (saved proposal {savedEcon.shares.toLocaleString()} sh)
                  </div>
                )}
                <div><div style={{ color: MUTED, fontSize: 8, textTransform: 'uppercase', marginBottom: 2 }}>Position</div>
                  <div style={{ color: showSized ? BLUE : (oversized ? RED : TEXT0), fontWeight: 700, fontFamily: 'monospace' }}>
                    {dispEcon.shares.toLocaleString()} sh @ ${Number(p.proposed_entry).toFixed(2)}
                  </div>
                  {showSized && (
                    <div style={{ color: MUTED, fontSize: 8, textDecoration: 'line-through' }}>
                      saved {savedEcon.shares.toLocaleString()} sh
                    </div>
                  )}
                  {maxSh != null && oversized && <div style={{ color: AMBER, fontSize: 8 }}>cap {Number(maxSh).toLocaleString()} sh</div>}
                  <div style={{ color: MUTED, fontSize: 9 }}>stop ${Number(p.proposed_stop).toFixed(2)} · tgt ${Number(p.proposed_target1).toFixed(2)}</div>
                </div>
                <div><div style={{ color: MUTED, fontSize: 8, textTransform: 'uppercase', marginBottom: 2 }}>Investment</div>
                  <div style={{ color: BLUE, fontWeight: 800, fontFamily: 'monospace' }}>{fmt(dispEcon.investment)}</div>
                  {showSized && savedEcon.investment != null && (
                    <div style={{ color: MUTED, fontSize: 8, textDecoration: 'line-through' }}>{fmt(savedEcon.investment)} saved</div>
                  )}
                </div>
                <div><div style={{ color: MUTED, fontSize: 8, textTransform: 'uppercase', marginBottom: 2 }}>Max risk</div>
                  <div style={{ color: RED, fontWeight: 800, fontFamily: 'monospace' }}>{fmt(dispEcon.max_risk)}</div>
                  {showSized && savedEcon.max_risk != null && (
                    <div style={{ color: MUTED, fontSize: 8, textDecoration: 'line-through' }}>{fmt(savedEcon.max_risk)} saved</div>
                  )}
                </div>
                <div><div style={{ color: MUTED, fontSize: 8, textTransform: 'uppercase', marginBottom: 2 }}>Profit @ target</div>
                  <div style={{ color: GREEN, fontWeight: 800, fontFamily: 'monospace' }}>+{fmt(dispEcon.profit_at_target)}</div>
                  {showSized && savedEcon.profit_at_target != null && (
                    <div style={{ color: MUTED, fontSize: 8, textDecoration: 'line-through' }}>+{fmt(savedEcon.profit_at_target)} saved</div>
                  )}
                </div>
                <div><div style={{ color: MUTED, fontSize: 8, textTransform: 'uppercase', marginBottom: 2 }}>R:R</div>
                  <div style={{ color: TEXT0, fontWeight: 800, fontFamily: 'monospace' }}>{p.proposed_rr ? `${Number(p.proposed_rr).toFixed(1)}:1` : '—'}</div>
                </div>
                <div><div style={{ color: MUTED, fontSize: 8, textTransform: 'uppercase', marginBottom: 2 }}>Spread</div>
                  <div style={{ color: p.quote_spread_pct != null && Number(p.quote_spread_pct) > 1 ? AMBER : TEXT1, fontWeight: 700, fontFamily: 'monospace' }}>
                    {p.quote_spread != null ? `$${Number(p.quote_spread).toFixed(2)}` : '—'}
                    {p.quote_spread_pct != null ? ` (${Number(p.quote_spread_pct).toFixed(2)}%)` : ''}
                  </div>
                  {p.quote_bid != null && <div style={{ color: MUTED, fontSize: 8 }}>bid ${Number(p.quote_bid).toFixed(2)} · ask ${Number(p.quote_ask).toFixed(2)}</div>}
                </div>
              </div>

              <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', padding: '8px 12px', background: 'rgba(0,0,0,.15)' }}>
                <select title="Destination account — re-runs sizing caps for this account" style={{ ...inp, width: 'auto', minWidth: 200, fontSize: 10 }} value={dest} onChange={e => onDestAccountChange(p, e.target.value)}>
                  {accounts.map(a => <option key={a.account_key} value={a.account_key}>{brokerOf(a.account_key)} · {a.display_name || a.account_key}</option>)}
                </select>
                {routeMsg[p.id] && <span style={{ fontSize: 10, color: routeMsg[p.id].startsWith('✅') || routeMsg[p.id].startsWith('📝') ? GREEN : routeMsg[p.id].startsWith('🔒') ? PURPLE : AMBER }}>{routeMsg[p.id]}</span>}
                <span style={{ flex: 1 }} />
                <button onClick={() => openManual(p)} style={btn(BLUE)} title="Log after you filled at broker">Executed manually</button>
                <button onClick={() => route(p.id)} disabled={gateBlocked && !fid} style={btn(fid ? PURPLE : AMBER, gateBlocked && !fid)} title={gateBlocked ? 'Blocked by sizing/AI gates — edit trade first' : (fid ? 'Record-only' : 'Schwab 2FA submit')}>{fid ? 'Record' : 'Auto (2FA)'}</button>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  </div>
}