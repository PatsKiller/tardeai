import { useApi } from '../../hooks/useApi'
import { fmt$ } from '../../lib/format'

export default function OptionsJournalPanel({ account, days }: { account?: string; days: number }) {
  const q = `/api/v2/journal/options-summary?days=${days}${account ? `&account=${account}` : ''}`
  const { data } = useApi<any>(q, 120_000)
  const d = data?.data ?? data
  return (
    <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14 }}>
      <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 8 }}>Options journal lane</div>
      <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 10 }}>
        {d?.options_trades ?? 0} options-linked closed trades · net {fmt$(d?.net_pnl, 0)} · win rate {d?.win_rate ?? 0}%
      </div>
      <div style={{ fontSize: 9, color: 'var(--text3)', marginBottom: 8 }}>Full greeks desk: <a href="/v3/options" style={{ color: '#60a5fa' }}>Options Hub</a>. Multi-leg grouping is a P5 follow-up when options fills ingest to trade_instances.</div>
      {(d?.trades || []).slice(0, 15).map((t: any, i: number) => (
        <div key={i} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, padding: '3px 0', borderBottom: '1px solid var(--border)' }}>
          <span style={{ fontFamily: 'monospace' }}>{t.symbol}</span>
          <span>{t.trade_type}</span>
          <span style={{ color: (t.pnl ?? 0) >= 0 ? '#22c55e' : '#ef4444' }}>{fmt$(t.pnl, 0)}</span>
          <span style={{ color: 'var(--text3)' }}>{t.close_date}</span>
        </div>
      ))}
    </div>
  )
}