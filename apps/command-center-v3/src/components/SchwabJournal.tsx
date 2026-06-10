import { useState } from 'react'
import { useApi } from '../hooks/useApi'
import { fmt$ } from '../lib/format'

// Real-account (Schwab) round-trips — API-authoritative ledger, 5-min fill aggregation, FIFO pairing,
// LLM strategy/grade/lesson. Separate from paper trades (the live-trading gate stays paper-only).
const GRADE: Record<string, string> = { A: '#22c55e', B: '#84cc16', C: '#f59e0b', D: '#f97316', F: '#ef4444' }

export default function SchwabJournal() {
  const { data } = useApi<any>('/api/v2/journal/schwab-round-trips', 60_000)
  const d = data ?? {}
  const trips: any[] = d.round_trips ?? []
  const [acct, setAcct] = useState('all')
  const [cls, setCls] = useState('all')
  if (!trips.length) return <div style={{ padding: 20, color: 'var(--text3)', fontSize: 12 }}>No Schwab round-trips yet — the ledger ingest + journal builder populate this (read-only).</div>

  const accts = ['all', ...Array.from(new Set(trips.map(t => t.account)))]
  const view = trips.filter(t => (acct === 'all' || t.account === acct) && (cls === 'all' || t.classification === cls))

  return (
    <div>
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 12 }}>
        {[['Round-trips', d.count], ['Win rate', (d.win_rate ?? 0) + '%'], ['Net P&L', fmt$(d.net_pnl ?? 0)]].map(([k, v]: any) => (
          <div key={k} style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 8, padding: '8px 14px' }}>
            <div style={{ fontSize: 9, color: 'var(--text3)' }}>{k}</div>
            <div style={{ fontSize: 16, fontWeight: 700, color: k === 'Net P&L' ? ((d.net_pnl ?? 0) >= 0 ? '#22c55e' : '#ef4444') : 'var(--text0)' }}>{v}</div>
          </div>
        ))}
        {Object.entries(d.by_account ?? {}).map(([a, v]: any) => (
          <div key={a} style={{ background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 8, padding: '8px 12px' }}>
            <div style={{ fontSize: 9, color: 'var(--text3)' }}>{a.replace('schwab_', '')}</div>
            <div style={{ fontSize: 13, fontWeight: 700, color: (v.net ?? 0) >= 0 ? '#22c55e' : '#ef4444' }}>{fmt$(v.net)} <span style={{ fontSize: 9, color: 'var(--text3)' }}>({v.count})</span></div>
          </div>
        ))}
      </div>
      <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 10 }}>Real Schwab trades · API-authoritative · 5-min fill aggregation · FIFO · LLM grade/lesson. Read-only — separate from the paper-only live-trading gate.</div>

      <div style={{ display: 'flex', gap: 6, marginBottom: 10 }}>
        {accts.map(a => <button key={a} onClick={() => setAcct(a)} style={{ padding: '4px 10px', fontSize: 11, borderRadius: 6, border: '1px solid var(--border)', cursor: 'pointer', background: acct === a ? 'rgba(96,165,250,.15)' : 'var(--bg2)', color: acct === a ? '#60a5fa' : 'var(--text2)' }}>{a.replace('schwab_', '') || a}</button>)}
        <span style={{ flex: 1 }} />
        {['all', 'day_trade', 'swing'].map(c => <button key={c} onClick={() => setCls(c)} style={{ padding: '4px 10px', fontSize: 11, borderRadius: 6, border: '1px solid var(--border)', cursor: 'pointer', background: cls === c ? 'rgba(96,165,250,.15)' : 'var(--bg2)', color: cls === c ? '#60a5fa' : 'var(--text2)' }}>{c}</button>)}
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 4, maxHeight: 600, overflowY: 'auto' }}>
        {view.map((t, i) => (
          <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '7px 10px', background: 'var(--bg2)', borderRadius: 7, border: '1px solid var(--border)', fontSize: 11 }}>
            <span style={{ flex: '0 0 56px', fontFamily: 'monospace', fontWeight: 700, color: 'var(--text0)' }}>{t.symbol}</span>
            <span style={{ flex: '0 0 64px', fontSize: 9, color: 'var(--text3)' }}>{t.account?.replace('schwab_', '')}</span>
            <span style={{ flex: '0 0 90px', fontSize: 9, color: 'var(--text2)' }}>{t.strategy_tag || t.classification}</span>
            <span style={{ flex: '0 0 70px', fontSize: 9, color: 'var(--text3)' }}>{t.hold_minutes < 390 ? `${t.hold_minutes}m` : `${Math.round(t.hold_minutes / 1440)}d`}</span>
            {t.entry_grade && <span style={{ flex: '0 0 80px', fontSize: 9 }}>E:<b style={{ color: GRADE[t.entry_grade] }}>{t.entry_grade}</b> X:<b style={{ color: GRADE[t.exit_grade] }}>{t.exit_grade}</b></span>}
            <span style={{ flex: '0 0 80px', textAlign: 'right', fontWeight: 700, color: (t.net_pnl ?? 0) >= 0 ? '#22c55e' : '#ef4444' }}>{fmt$(t.net_pnl)}</span>
            <span style={{ flex: '1 1 auto', fontSize: 9, color: 'var(--text3)', fontStyle: 'italic', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={t.lesson}>{t.lesson || ''}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
