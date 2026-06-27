import { useApi } from '../../hooks/useApi'

export default function ZellaScoreCard({ account, days }: { account?: string; days: number }) {
  const q = `/api/v2/journal/zella-score?days=${days}${account ? `&account=${account}` : ''}`
  const { data } = useApi<any>(q, 120_000)
  const d = data?.data ?? data
  if (!d?.ok) return null
  const comps = d.components || {}
  const color = (v: number) => v >= 70 ? '#22c55e' : v >= 50 ? '#f59e0b' : '#ef4444'
  return (
    <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
        <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)' }}>TradeInView Score</span>
        <span style={{ fontSize: 28, fontWeight: 800, color: color(d.score), fontFamily: 'monospace' }}>{d.score}</span>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 6 }}>
        {Object.entries(comps).map(([k, v]) => (
          <div key={k} style={{ textAlign: 'center', padding: 6, background: 'var(--bg2)', borderRadius: 6 }}>
            <div style={{ fontSize: 14, fontWeight: 700, color: color(v as number) }}>{v as number}</div>
            <div style={{ fontSize: 7, color: 'var(--text3)', textTransform: 'capitalize' }}>{k.replace(/_/g, ' ')}</div>
          </div>
        ))}
      </div>
      <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 8 }}>{d.trades} trades · {d.reviewed} reviewed</div>
    </div>
  )
}