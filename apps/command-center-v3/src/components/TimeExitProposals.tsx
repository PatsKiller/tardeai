import { useState } from 'react'
import { useApi } from '../hooks/useApi'

// Max-hold time-exit proposals — advisory, approval-gated. Positions held past their strategy's
// max_hold_days surface here; APPROVE closes via the paper-only interlock + close_paper_trade (no
// silent auto-close). REJECT dismisses.
export default function TimeExitProposals() {
  const { data, refetch } = useApi<any>('/api/v2/time-exit-proposals', 60_000)
  const props: any[] = data?.proposals ?? []
  const [busy, setBusy] = useState<number | null>(null)
  const [msg, setMsg] = useState('')

  const decide = async (id: number, action: 'approve' | 'reject') => {
    if (busy) return
    if (action === 'approve' && !confirm('Close this position now (paper)? It is past its strategy max-hold.')) return
    setBusy(id); setMsg('')
    try {
      const r = await fetch('/api/v2/time-exit-proposals/decide', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ proposal_id: id, action }) })
      const j = await r.json(); const d = j?.data ?? j
      setMsg(action === 'reject' ? '✓ dismissed' : (d?.ok ? '✓ closed' : `✗ ${d?.status || d?.error || 'failed'}`))
      setTimeout(refetch, 1200)
    } catch { setMsg('✗ request failed') }
    setBusy(null)
  }

  if (!props.length) return null
  return (
    <div style={{ background: 'rgba(245,158,11,.06)', border: '1px solid rgba(245,158,11,.3)', borderRadius: 10, padding: 14, marginBottom: 12 }}>
      <div style={{ fontSize: 12, fontWeight: 700, color: '#f59e0b', marginBottom: 2 }}>⏳ Time-exit proposals ({props.length}) — held past strategy max-hold</div>
      <div style={{ fontSize: 9, color: 'var(--text3)', marginBottom: 10 }}>Advisory · approval closes via the paper-only interlock + close path · no auto-close</div>
      {msg && <div style={{ fontSize: 11, color: msg.startsWith('✓') ? '#22c55e' : '#ef4444', marginBottom: 8 }}>{msg}</div>}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {props.map((p: any) => (
          <div key={p.id} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '7px 10px', background: 'var(--bg2)', borderRadius: 7, border: '1px solid var(--border)' }}>
            <span style={{ flex: '0 0 60px', fontFamily: 'monospace', fontWeight: 700, color: 'var(--text0)', fontSize: 12 }}>{p.symbol}</span>
            <span style={{ flex: '0 0 130px', fontSize: 10, color: 'var(--text2)' }}>{p.strategy_id}</span>
            <span style={{ flex: '0 0 120px', fontSize: 10, color: 'var(--text2)' }}>held {p.hold_days}d &gt; {p.max_hold_days}d <b style={{ color: '#f59e0b' }}>(+{p.overdue_by_days})</b></span>
            <span style={{ flex: '0 0 70px', fontSize: 10, color: p.unrealized_pnl_pct >= 0 ? '#22c55e' : '#ef4444' }}>{p.unrealized_pnl_pct != null ? `${p.unrealized_pnl_pct}%` : ''}</span>
            <span style={{ flex: '1 1 auto', textAlign: 'right', display: 'flex', gap: 6, justifyContent: 'flex-end' }}>
              <button onClick={() => decide(p.id, 'reject')} disabled={busy === p.id} style={{ padding: '4px 10px', fontSize: 11, borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg1)', color: 'var(--text2)', cursor: 'pointer' }}>Dismiss</button>
              <button onClick={() => decide(p.id, 'approve')} disabled={busy === p.id} style={{ padding: '4px 12px', fontSize: 11, fontWeight: 700, borderRadius: 6, border: 'none', background: '#f59e0b', color: '#0a0a0a', cursor: 'pointer' }}>{busy === p.id ? '…' : 'Close now'}</button>
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}
