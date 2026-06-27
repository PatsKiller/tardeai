import { useState, useEffect } from 'react'
import { fmt$ } from '../../lib/format'

export default function SessionRecapPanel({ sessionDate }: { sessionDate?: string }) {
  const sd = sessionDate || new Date().toISOString().slice(0, 10)
  const [plan, setPlan] = useState('')
  const [eod, setEod] = useState('')
  const [msg, setMsg] = useState('')

  useEffect(() => {
    fetch(`/api/v2/journal/session-recap?date=${sd}`).then(r => r.json()).then(d => {
      const rec = d?.recap || d?.data?.recap
      if (rec) { setPlan(rec.pre_market_plan || ''); setEod(rec.eod_reflection || '') }
    })
  }, [sd])

  const save = async () => {
    const r = await fetch('/api/v2/journal/session-recap', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_date: sd, pre_market_plan: plan, eod_reflection: eod }),
    }).then(x => x.json())
    setMsg(r.ok ? '✓ saved' : '⛔ failed')
  }

  return (
    <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14 }}>
      <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 8 }}>Session recap — {sd}</div>
      <div style={{ fontSize: 9, color: 'var(--text3)', marginBottom: 8 }}>Pre-market plan vs end-of-day reflection</div>
      <div style={{ fontSize: 9, color: 'var(--text3)', marginBottom: 4 }}>Pre-market plan</div>
      <textarea value={plan} onChange={e => setPlan(e.target.value)} placeholder="What I plan to trade, rules, max loss…"
        style={{ width: '100%', minHeight: 70, marginBottom: 10, fontSize: 11, padding: 8, borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text0)' }} />
      <div style={{ fontSize: 9, color: 'var(--text3)', marginBottom: 4 }}>EOD reflection</div>
      <textarea value={eod} onChange={e => setEod(e.target.value)} placeholder="What happened vs plan, lessons…"
        style={{ width: '100%', minHeight: 70, marginBottom: 10, fontSize: 11, padding: 8, borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text0)' }} />
      <button onClick={save} style={{ fontSize: 10, padding: '6px 14px', borderRadius: 5, border: 'none', background: '#60a5fa', color: '#fff', fontWeight: 700, cursor: 'pointer' }}>Save recap</button>
      {msg && <span style={{ marginLeft: 10, fontSize: 9, color: msg.startsWith('✓') ? '#22c55e' : '#ef4444' }}>{msg}</span>}
    </div>
  )
}