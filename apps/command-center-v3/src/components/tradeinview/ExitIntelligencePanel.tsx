import { useApi } from '../../hooks/useApi'
import { fmt$ } from '../../lib/format'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts'

export default function ExitIntelligencePanel({ account, days }: { account?: string; days: number }) {
  const q = `/api/v2/journal/exit-intelligence?days=${days}${account ? `&account=${account}` : ''}`
  const { data, loading } = useApi<any>(q, 120_000)
  const d = data?.data ?? data
  if (loading) return <div style={{ color: 'var(--text3)', padding: 20 }}>Loading exit intelligence…</div>
  if (!d?.ok) return <div style={{ color: 'var(--text3)', padding: 20 }}>No exit data</div>

  const hours = d.exit_timing_by_hour || []
  return (
    <div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8, marginBottom: 14 }}>
        {[
          { l: 'Measurable trades', v: d.measurable, c: 'var(--text0)' },
          { l: 'Avg capture', v: d.avg_capture_ratio != null ? `${Math.round(d.avg_capture_ratio * 100)}%` : '—', c: '#22c55e' },
          { l: 'Avg giveback', v: d.avg_giveback_pct != null ? `${d.avg_giveback_pct}%` : '—', c: '#f59e0b' },
          { l: 'Money left', v: fmt$(d.money_left_total, 0), c: '#ef4444' },
        ].map(k => (
          <div key={k.l} style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 8, padding: 10, textAlign: 'center' }}>
            <div style={{ fontSize: 18, fontWeight: 700, color: k.c }}>{k.v}</div>
            <div style={{ fontSize: 9, color: 'var(--text3)' }}>{k.l}</div>
          </div>
        ))}
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14, marginBottom: 14 }}>
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14 }}>
          <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 8 }}>EOD vs Intraday exits</div>
          {Object.entries(d.eod_vs_intraday || {}).map(([k, v]: [string, any]) => (
            <div key={k} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, padding: '4px 0', borderBottom: '1px solid var(--border)' }}>
              <span style={{ textTransform: 'capitalize' }}>{k}</span>
              <span>{v.trades}t · {v.win_rate}% · {fmt$(v.net_pnl, 0)}</span>
            </div>
          ))}
        </div>
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14 }}>
          <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 8 }}>Exit timing by hour (ET)</div>
          {hours.length > 0 ? (
            <ResponsiveContainer width="100%" height={140}>
              <BarChart data={hours}>
                <XAxis dataKey="label" tick={{ fontSize: 8 }} />
                <YAxis tick={{ fontSize: 8 }} width={40} />
                <Tooltip />
                <Bar dataKey="net_pnl">{hours.map((r: any, i: number) => <Cell key={i} fill={r.net_pnl >= 0 ? '#22c55e' : '#ef4444'} />)}</Bar>
              </BarChart>
            </ResponsiveContainer>
          ) : <div style={{ fontSize: 10, color: 'var(--text3)' }}>No hour data</div>}
        </div>
      </div>
      <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14 }}>
        <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 8 }}>Top giveback trades (best-exit vs actual)</div>
        {(d.top_giveback || []).slice(0, 8).map((t: any, i: number) => (
          <div key={i} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, padding: '4px 0', borderBottom: '1px solid var(--border)' }}>
            <span style={{ fontFamily: 'monospace', fontWeight: 700 }}>{t.symbol}</span>
            <span style={{ color: '#ef4444' }}>left {fmt$(t.money_left_usd, 0)}</span>
            <span style={{ color: 'var(--text3)' }}>{t.failure_class || '—'}</span>
          </div>
        ))}
      </div>
    </div>
  )
}