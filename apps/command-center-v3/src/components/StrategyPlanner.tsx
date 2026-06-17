import { useEffect, useMemo, useState } from 'react'
import { useApi } from '../hooks/useApi'

// Interactive strategy planner: declare an intent → what-if impact → goal-aligned redeploy advice →
// approve → sync to learning + discovery. Advisory-only; approval seeds discovery, never places a trade.
// Redesigned 2026-06-17: live account context, resolved $ amounts, before→after framing, guided steps.

const BG1 = 'var(--bg1)', BG2 = 'var(--bg2)', BORDER = 'var(--border)'
const T0 = 'var(--text0)', T2 = 'var(--text2)', T3 = 'var(--text3)'
const BLUE = '#60a5fa', GREEN = '#22c55e', RED = '#ef4444', AMBER = '#f59e0b', PURPLE = '#a855f7'
const card: React.CSSProperties = { background: BG2, border: `1px solid ${BORDER}`, borderRadius: 10, padding: 16 }
const input: React.CSSProperties = { background: BG1, border: `1px solid ${BORDER}`, borderRadius: 6, color: T0, padding: '8px 10px', fontSize: 12.5, width: '100%', boxSizing: 'border-box' }
const lbl: React.CSSProperties = { fontSize: 9.5, color: T3, textTransform: 'uppercase', letterSpacing: .5, marginBottom: 4, display: 'block', fontWeight: 700 }
const btn = (on: boolean, c = BLUE): React.CSSProperties => ({ background: on ? c : BG1, color: on ? '#0b1220' : T2, border: `1px solid ${on ? c : BORDER}`, borderRadius: 7, padding: '9px 16px', fontWeight: 800, fontSize: 12.5, cursor: 'pointer' })
const $ = (n: number) => '$' + Math.round(n || 0).toLocaleString()

const ACTIONS: [string, string, string][] = [
  ['liquidate', 'Roll account → cash', 'Move an entire account to cash and model the redeploy'],
  ['trim', 'Trim a holding', 'Sell part of one position'],
  ['add', 'Deploy new cash', 'Put fresh cash to work'],
  ['rebalance', 'Rebalance', 'Shift weight across sleeves'],
]

export default function StrategyPlanner() {
  const { data: hold } = useApi<any>('/api/v2/portfolio/holdings', 60_000)
  const holdings: any[] = hold?.data?.holdings ?? hold?.holdings ?? []

  const [action, setAction] = useState('liquidate')
  const [account, setAccount] = useState('')
  const [symbol, setSymbol] = useState('')
  const [amount, setAmount] = useState('all')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [res, setRes] = useState<any>(null)
  const [status, setStatus] = useState('')
  const [approved, setApproved] = useState<any>(null)

  const accounts = useMemo(() => [...new Set(holdings.map(h => h.account).filter(Boolean))].sort(), [holdings])
  useEffect(() => { if (!account && accounts.length) setAccount(accounts[0]) }, [accounts, account])

  // live context for the selected account
  const acctPositions = useMemo(() =>
    holdings.filter(h => h.account === account && !h.is_cash && (+h.market_value || 0) > 0)
      .sort((a, b) => (+b.market_value || 0) - (+a.market_value || 0)), [holdings, account])
  const acctValue = acctPositions.reduce((s, h) => s + (+h.market_value || 0), 0)
  const symPositions = useMemo(() => holdings.filter(h => (h.symbol || '').toUpperCase() === symbol.toUpperCase() && (!account || h.account === account)), [holdings, symbol, account])
  const symValue = symPositions.reduce((s, h) => s + (+h.market_value || 0), 0)

  const resolvedAmount = useMemo(() => {
    const num = parseFloat(String(amount).replace(/[$,]/g, ''))
    if (action === 'liquidate') return acctValue
    if (action === 'trim') return amount === 'all' || isNaN(num) ? symValue : Math.min(num, symValue)
    return isNaN(num) ? 0 : num
  }, [action, amount, acctValue, symValue])

  useEffect(() => { setRes(null); setApproved(null); setStatus('') }, [action, account, symbol, amount])

  const intent = () => ({ action, account, symbol: symbol || undefined, to: 'cash', amount, note })

  const runPlan = async () => {
    if (action === 'trim' && !symbol) { setStatus('Pick a holding to trim.'); return }
    setBusy(true); setStatus('Computing what-if impact + redeploy advice…'); setApproved(null)
    try {
      const r = await fetch('/api/v2/strategy/plan', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ intent: intent(), with_advice: true }) })
      const j = await r.json()
      if (!j.ok) throw new Error(j.error || 'plan failed')
      setRes(j); setStatus('')
    } catch (e: any) { setStatus(`Error: ${e.message}`) } finally { setBusy(false) }
  }

  const approve = async () => {
    if (!res) return
    setBusy(true); setStatus('Approving → syncing to learning + discovery…')
    const cands = (res.advice?.candidates ?? []).slice(0, 4).map((c: any) => ({ kind: 'ticker', label: c.symbol, rationale: `Strategy redeploy candidate (${c.sector ?? 'rank ' + c.rank})` }))
    const uw = (res.impact?.underweight_themes ?? [])[0]
    const dirs = uw ? [...cands, { kind: 'trend', label: uw, rationale: 'Redeploy to underweight theme opened by this move' }] : cands
    try {
      const r = await fetch('/api/v2/strategy/approve', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ intent: intent(), impact: res.impact, advice: res.advice, directives: dirs }) })
      const j = await r.json()
      if (!j.ok) throw new Error(j.error || 'approve failed')
      setApproved(j); setStatus('')
    } catch (e: any) { setStatus(`Error: ${e.message}`) } finally { setBusy(false) }
  }

  const imp = res?.impact, adv = res?.advice
  const actLabel = ACTIONS.find(a => a[0] === action)?.[1] ?? action

  // plain-English summary of the move
  const moveSummary = action === 'liquidate' ? `Sell all ${acctPositions.length} positions in ${account} (${$(acctValue)}) to cash`
    : action === 'trim' ? `Trim ${$(resolvedAmount)} of ${symbol || '—'} in ${account}`
    : action === 'add' ? `Deploy ${$(resolvedAmount)} of new cash`
    : `Rebalance ${account}`

  return <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
    {/* Header */}
    <div>
      <div style={{ fontSize: 18, fontWeight: 900, color: T0 }}>Strategy Planner</div>
      <div style={{ fontSize: 11.5, color: T3, marginTop: 2 }}>Model a portfolio move → see the look-through &amp; income impact → get a goal-aligned redeploy plan → approve to feed learning &amp; discovery. <b style={{ color: AMBER }}>Advisory only — never places a trade.</b></div>
    </div>

    {/* Step 1 — Build the move, with live account context */}
    <div style={{ display: 'grid', gridTemplateColumns: '1.15fr .85fr', gap: 14 }}>
      <div style={card}>
        <Step n={1} label="Declare the move" />
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginTop: 10 }}>
          <div><span style={lbl}>Action</span><select value={action} onChange={e => setAction(e.target.value)} style={input}>{ACTIONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></div>
          <div><span style={lbl}>Account</span><select value={account} onChange={e => setAccount(e.target.value)} style={input}>{accounts.map(a => <option key={a} value={a}>{a}</option>)}</select></div>
          {action === 'trim' && <div><span style={lbl}>Holding</span><select value={symbol} onChange={e => setSymbol(e.target.value)} style={input}><option value="">— pick —</option>{acctPositions.map(h => <option key={h.symbol} value={h.symbol}>{h.symbol} · {$(+h.market_value || 0)}</option>)}</select></div>}
          {(action === 'trim' || action === 'add') && <div><span style={lbl}>Amount {action === 'trim' && symbol ? `(max ${$(symValue)})` : ''}</span><input value={amount} onChange={e => setAmount(e.target.value)} placeholder={action === 'trim' ? 'all / $20000' : '$20000'} style={input} /></div>}
        </div>
        <div style={{ marginTop: 10 }}><span style={lbl}>Why / note (optional)</span><input value={note} onChange={e => setNote(e.target.value)} placeholder="e.g. reduce equity risk, lift income toward the $55k goal" style={input} /></div>
        <div style={{ marginTop: 12, padding: '9px 11px', background: BG1, borderRadius: 7, border: `1px solid ${BORDER}`, fontSize: 12, color: T2 }}>
          <span style={{ color: T3 }}>You're modeling:</span> <b style={{ color: T0 }}>{moveSummary}.</b>
        </div>
        <div style={{ display: 'flex', gap: 10, marginTop: 12, alignItems: 'center' }}>
          <button onClick={runPlan} disabled={busy} style={{ ...btn(true), opacity: busy ? .6 : 1 }}>{busy && !approved ? 'Running…' : 'Run what-if →'}</button>
          {status && <span style={{ fontSize: 11.5, color: status.startsWith('Error') ? RED : AMBER }}>{status}</span>}
        </div>
      </div>

      {/* Live current-state context */}
      <div style={{ ...card, background: BG1 }}>
        <div style={{ fontSize: 10, color: T3, textTransform: 'uppercase', letterSpacing: .5, fontWeight: 700 }}>Current — {account || '…'}</div>
        <div style={{ fontSize: 22, fontWeight: 900, color: T0, margin: '4px 0 2px' }}>{$(acctValue)}</div>
        <div style={{ fontSize: 11, color: T3, marginBottom: 8 }}>{acctPositions.length} positions</div>
        {acctPositions.slice(0, 6).map(h => {
          const pct = acctValue ? (+h.market_value || 0) / acctValue * 100 : 0
          return <div key={h.symbol} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, padding: '2px 0', color: T2 }}>
            <span>{h.symbol}</span><span style={{ color: T3 }}>{$(+h.market_value || 0)} · {pct.toFixed(0)}%</span>
          </div>
        })}
        {acctPositions.length > 6 && <div style={{ fontSize: 10, color: T3, marginTop: 4 }}>+{acctPositions.length - 6} more</div>}
      </div>
    </div>

    {/* Approved banner */}
    {approved && <div style={{ ...card, borderColor: GREEN, background: 'rgba(34,197,94,.06)' }}>
      <div style={{ fontSize: 13, fontWeight: 800, color: GREEN }}>✓ {approved.message}</div>
      <div style={{ fontSize: 11, color: T2, marginTop: 4 }}>Plan #{approved.plan_id} · learning {approved.synced?.learning ? '✓ recorded' : '—'} · {approved.synced?.discovery ?? 0} discovery directive(s) created → the discovery engine + watchlist sweep will now source candidates for these.</div>
    </div>}

    {/* Step 2 — Impact (before → after) */}
    {imp && <div style={card}>
      <Step n={2} label="Impact — before → after" />
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 10, marginTop: 12 }}>
        <BA label="Cash freed" after={$(imp.cash_freed)} color={BLUE} />
        <BA label="Cash weight" before={`${imp.cash_pct_before}%`} after={`${imp.cash_pct_after}%`} color={imp.cash_pct_after > 20 ? AMBER : T0} />
        <BA label="Income lost / yr" after={`−${$(imp.income?.annual_income_lost)}`} sub={`${imp.income?.blended_yield_pct ?? 0}% yield · goal ${$(imp.income?.target)}`} color={imp.income?.annual_income_lost ? RED : T0} />
        <BA label="Account after" after={imp.account_refactor?.after} color={T0} />
      </div>
      {(imp.income?.by_holding ?? []).length > 0 && <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap', marginTop: 10 }}>{imp.income.by_holding.slice(0, 8).map((b: any) => <span key={b.symbol} style={{ fontSize: 10, background: BG1, border: `1px solid ${BORDER}`, borderRadius: 5, padding: '2px 6px', color: T2 }}>{b.symbol} <b style={{ color: RED }}>−{$(b.annual_income)}</b> <span style={{ color: T3 }}>{b.yield_pct}%</span></span>)}</div>}
      <div style={{ fontSize: 10.5, color: AMBER, marginTop: 8, lineHeight: 1.4 }}>{imp.income?.note}</div>

      {(imp.lookthrough_delta ?? []).length > 0 && <>
        <div style={{ fontSize: 11, fontWeight: 700, color: T2, marginTop: 14, marginBottom: 6 }}>Look-through exposure change</div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '2px 18px' }}>{imp.lookthrough_delta.slice(0, 10).map((t: any) => (
          <div key={t.theme} style={{ display: 'grid', gridTemplateColumns: '1.5fr .9fr .5fr', gap: 6, fontSize: 11, alignItems: 'center' }}>
            <span style={{ color: T2 }}>{t.theme}</span>
            <span style={{ color: T3, fontFamily: 'monospace', fontSize: 10 }}>{t.before_pct}→{t.after_pct}%</span>
            <span style={{ color: t.delta_pct < 0 ? RED : GREEN, fontWeight: 700, textAlign: 'right' }}>{t.delta_pct > 0 ? '+' : ''}{t.delta_pct}</span>
          </div>))}</div>
        {(imp.underweight_themes ?? []).length > 0 && <div style={{ fontSize: 10, color: T3, marginTop: 8 }}>Most underweight (redeploy gaps): <span style={{ color: T2 }}>{imp.underweight_themes.join(' · ')}</span></div>}
      </>}
    </div>}

    {/* Step 3 — Advice */}
    {adv && <div style={card}>
      <Step n={3} label="Redeploy plan — what to invest in" extra={<span style={{ fontSize: 10, color: T3 }}>via {adv.provider}</span>} />
      <div style={{ fontSize: 12.5, color: T0, whiteSpace: 'pre-wrap', lineHeight: 1.55, marginTop: 10 }}>{adv.advice}</div>
      {(adv.candidates ?? []).length > 0 && <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 10 }}>{adv.candidates.map((c: any) => <span key={c.symbol} style={{ fontSize: 10.5, background: BG1, border: `1px solid ${BORDER}`, borderRadius: 5, padding: '3px 7px', color: T2 }}>{c.symbol}{c.sector ? ` · ${c.sector}` : ''}{c.rank ? ` · #${c.rank}` : ''}</span>)}</div>}
    </div>}

    {/* Step 4 — Approve */}
    {res && !approved && <div style={{ ...card, borderColor: PURPLE, background: 'rgba(168,85,247,.05)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
      <div><Step n={4} label="Approve & sync" /><div style={{ fontSize: 11, color: T2, marginTop: 4 }}>Records the plan + a learning observation, and seeds discovery (watch directives) for the redeploy targets. Does not place a trade.</div></div>
      <button onClick={approve} disabled={busy} style={{ ...btn(true, PURPLE), opacity: busy ? .6 : 1, whiteSpace: 'nowrap' }}>Approve → sync</button>
    </div>}
  </div>
}

function Step({ n, label, extra }: { n: number, label: string, extra?: React.ReactNode }) {
  return <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
    <span style={{ width: 18, height: 18, borderRadius: 9, background: BLUE, color: '#0b1220', fontSize: 11, fontWeight: 900, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>{n}</span>
    <span style={{ fontSize: 13, fontWeight: 800, color: T0 }}>{label}</span>
    <span style={{ marginLeft: 'auto' }}>{extra}</span>
  </div>
}

function BA({ label, before, after, sub, color }: { label: string, before?: string, after?: any, sub?: string, color: string }) {
  return <div>
    <div style={{ fontSize: 9.5, color: T3, textTransform: 'uppercase', letterSpacing: .4 }}>{label}</div>
    <div style={{ fontSize: 13.5, fontWeight: 800, color, marginTop: 2 }}>{before != null && <span style={{ color: T3, fontWeight: 600, fontSize: 11 }}>{before} → </span>}{after}</div>
    {sub && <div style={{ fontSize: 9, color: T3, marginTop: 1 }}>{sub}</div>}
  </div>
}
