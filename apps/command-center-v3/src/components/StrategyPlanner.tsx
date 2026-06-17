import { useEffect, useState } from 'react'

// Interactive strategy planner: declare an intent → what-if impact → goal-aligned redeploy advice →
// approve → sync to learning + discovery (operator 2026-06-17). Advisory-only; approval seeds discovery,
// never places a trade.

const BG2 = 'var(--bg2)', BORDER = 'var(--border)', T0 = 'var(--text0)', T2 = 'var(--text2)', T3 = 'var(--text3)'
const BLUE = '#60a5fa', GREEN = '#22c55e', RED = '#ef4444', AMBER = '#f59e0b'
const card: React.CSSProperties = { background: BG2, border: `1px solid ${BORDER}`, borderRadius: 8, padding: 14 }
const input: React.CSSProperties = { background: 'var(--bg1)', border: `1px solid ${BORDER}`, borderRadius: 6, color: T0, padding: '7px 9px', fontSize: 12 }
const btn = (on: boolean, c = BLUE): React.CSSProperties => ({ background: on ? c : 'var(--bg1)', color: on ? '#0b1220' : T2, border: `1px solid ${on ? c : BORDER}`, borderRadius: 6, padding: '8px 14px', fontWeight: 800, fontSize: 12, cursor: 'pointer' })

const ACCOUNTS = ['fidelity_401k', 'schwab_rollover_ira', 'schwab_roth', 'schwab_taxable', 'alpaca_paper']
const ACTIONS = [['liquidate', 'Roll account → cash'], ['trim', 'Trim a holding'], ['add', 'Deploy new cash'], ['rebalance', 'Rebalance']]

export default function StrategyPlanner() {
  const [action, setAction] = useState('liquidate')
  const [account, setAccount] = useState('fidelity_401k')
  const [symbol, setSymbol] = useState('')
  const [amount, setAmount] = useState('all')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [res, setRes] = useState<any>(null)
  const [status, setStatus] = useState('')
  const [approved, setApproved] = useState<any>(null)

  useEffect(() => { setRes(null); setApproved(null); setStatus('') }, [action, account, symbol, amount])

  const intent = () => ({ action, account, symbol: symbol || undefined, to: 'cash', amount, note })

  const runPlan = async () => {
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
    // derive discovery directives: top candidates as ticker watches + the most underweight theme as a trend
    const cands = (res.advice?.candidates ?? []).slice(0, 4).map((c: any) => ({ kind: 'ticker', label: c.symbol, spec: c.symbol, rationale: `Strategy redeploy candidate (${c.sector ?? 'rank ' + c.rank})` }))
    const uw = (res.impact?.underweight_themes ?? [])[0]
    const dirs = uw ? [...cands, { kind: 'trend', label: uw, spec: uw, rationale: `Redeploy to underweight theme opened by this move` }] : cands
    try {
      const r = await fetch('/api/v2/strategy/approve', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ intent: intent(), impact: res.impact, advice: res.advice, directives: dirs }) })
      const j = await r.json()
      if (!j.ok) throw new Error(j.error || 'approve failed')
      setApproved(j); setStatus('')
    } catch (e: any) { setStatus(`Error: ${e.message}`) } finally { setBusy(false) }
  }

  const imp = res?.impact, adv = res?.advice

  return <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
    <div style={card}>
      <div style={{ fontSize: 16, fontWeight: 900, color: T0 }}>Strategy Planner</div>
      <div style={{ fontSize: 11, color: T3, marginBottom: 12 }}>Declare a move → see the look-through &amp; account impact → get a goal-aligned redeploy plan → approve to sync into learning &amp; discovery. Advisory-only — never places a trade.</div>
      <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 1.2fr .8fr .8fr', gap: 8, alignItems: 'end' }}>
        <label style={{ fontSize: 10, color: T3 }}>Action<select value={action} onChange={e => setAction(e.target.value)} style={{ ...input, width: '100%', marginTop: 3 }}>{ACTIONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label>
        <label style={{ fontSize: 10, color: T3 }}>Account<select value={account} onChange={e => setAccount(e.target.value)} style={{ ...input, width: '100%', marginTop: 3 }}>{ACCOUNTS.map(a => <option key={a} value={a}>{a}</option>)}</select></label>
        <label style={{ fontSize: 10, color: T3 }}>Symbol{action === 'trim' ? ' *' : ''}<input value={symbol} onChange={e => setSymbol(e.target.value.toUpperCase())} placeholder={action === 'trim' ? 'XLB' : '—'} style={{ ...input, width: '100%', marginTop: 3 }} /></label>
        <label style={{ fontSize: 10, color: T3 }}>Amount<input value={amount} onChange={e => setAmount(e.target.value)} placeholder="all / $20000" style={{ ...input, width: '100%', marginTop: 3 }} /></label>
      </div>
      <input value={note} onChange={e => setNote(e.target.value)} placeholder="note / why (optional)" style={{ ...input, width: '100%', marginTop: 8, boxSizing: 'border-box' }} />
      <div style={{ display: 'flex', gap: 8, marginTop: 10, alignItems: 'center' }}>
        <button onClick={runPlan} disabled={busy} style={{ ...btn(true), opacity: busy ? .6 : 1 }}>{busy && !approved ? 'Running…' : 'Run what-if'}</button>
        {res && <button onClick={approve} disabled={busy} style={{ ...btn(true, GREEN), opacity: busy ? .6 : 1 }}>Approve → sync to learning &amp; discovery</button>}
        {status && <span style={{ fontSize: 11, color: status.startsWith('Error') ? RED : AMBER }}>{status}</span>}
      </div>
    </div>

    {approved && <div style={{ ...card, borderColor: GREEN }}>
      <div style={{ fontSize: 13, fontWeight: 800, color: GREEN }}>✓ {approved.message}</div>
      <div style={{ fontSize: 11, color: T2, marginTop: 4 }}>Plan #{approved.plan_id} · learning observation {approved.synced?.learning ? '✓ recorded' : '—'} · {approved.synced?.discovery ?? 0} discovery directive(s) created → the discovery engine + watchlist sweep will now source candidates for these.</div>
    </div>}

    {imp && <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
      <div style={card}>
        <div style={{ fontSize: 12, fontWeight: 800, color: T0, marginBottom: 8 }}>Impact — what-if</div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 10 }}>
          <Stat label="Cash freed" value={`$${(imp.cash_freed ?? 0).toLocaleString()}`} color={BLUE} />
          <Stat label="Cash %" value={`${imp.cash_pct_before}% → ${imp.cash_pct_after}%`} color={imp.cash_pct_after > 20 ? AMBER : T0} />
          <Stat label="Account after" value={imp.account_refactor?.after} color={T0} />
          <Stat label="Income lost / yr" value={`$${(imp.income?.annual_income_lost ?? 0).toLocaleString()}`} color={RED} sub={`${imp.income?.blended_yield_pct ?? 0}% yield · target $${(imp.income?.target ?? 0).toLocaleString()}`} />
        </div>
        {(imp.income?.by_holding ?? []).length > 0 && <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap', marginBottom: 8 }}>{(imp.income.by_holding).slice(0, 8).map((b: any) => (
          <span key={b.symbol} style={{ fontSize: 10, background: 'var(--bg1)', border: `1px solid ${BORDER}`, borderRadius: 5, padding: '2px 6px', color: T2 }}>{b.symbol} <b style={{ color: RED }}>${b.annual_income.toLocaleString()}</b> <span style={{ color: T3 }}>{b.yield_pct}%</span></span>))}</div>}
        <div style={{ fontSize: 10.5, color: AMBER, lineHeight: 1.4 }}>{imp.income?.note}</div>
      </div>
      <div style={card}>
        <div style={{ fontSize: 12, fontWeight: 800, color: T0, marginBottom: 8 }}>Look-through exposure change</div>
        {(imp.lookthrough_delta ?? []).length === 0 ? <div style={{ fontSize: 11, color: T3 }}>No material theme change.</div> :
          <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>{(imp.lookthrough_delta ?? []).slice(0, 9).map((t: any) => (
            <div key={t.theme} style={{ display: 'grid', gridTemplateColumns: '1.4fr .9fr .6fr', gap: 6, fontSize: 11, alignItems: 'center' }}>
              <span style={{ color: T2 }}>{t.theme}</span>
              <span style={{ color: T3, fontFamily: 'monospace' }}>{t.before_pct}% → {t.after_pct}%</span>
              <span style={{ color: t.delta_pct < 0 ? RED : GREEN, fontWeight: 700, textAlign: 'right' }}>{t.delta_pct > 0 ? '+' : ''}{t.delta_pct}%</span>
            </div>))}</div>}
        {(imp.underweight_themes ?? []).length > 0 && <div style={{ fontSize: 10, color: T3, marginTop: 8 }}>Most underweight (redeploy gaps): {(imp.underweight_themes ?? []).join(' · ')}</div>}
      </div>
    </div>}

    {adv && <div style={card}>
      <div style={{ fontSize: 12, fontWeight: 800, color: T0, marginBottom: 6 }}>Redeploy advice — what to invest in <span style={{ color: T3, fontWeight: 400 }}>· {adv.provider}</span></div>
      <div style={{ fontSize: 12.5, color: T0, whiteSpace: 'pre-wrap', lineHeight: 1.55 }}>{adv.advice}</div>
      {(adv.candidates ?? []).length > 0 && <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 10 }}>{(adv.candidates ?? []).map((c: any) => (
        <span key={c.symbol} style={{ fontSize: 10.5, background: 'var(--bg1)', border: `1px solid ${BORDER}`, borderRadius: 5, padding: '3px 7px', color: T2 }}>{c.symbol}{c.sector ? ` · ${c.sector}` : ''}{c.rank ? ` · #${c.rank}` : ''}</span>))}</div>}
    </div>}
  </div>
}

function Stat({ label, value, color, sub }: { label: string, value: any, color: string, sub?: string }) {
  return <div><div style={{ fontSize: 9.5, color: T3, textTransform: 'uppercase', letterSpacing: .4 }}>{label}</div>
    <div style={{ fontSize: 14, fontWeight: 800, color }}>{value}</div>{sub && <div style={{ fontSize: 9, color: T3 }}>{sub}</div>}</div>
}
