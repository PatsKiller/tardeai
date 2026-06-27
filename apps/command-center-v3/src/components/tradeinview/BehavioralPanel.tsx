import { useApi } from '../../hooks/useApi'
import { fmt$ } from '../../lib/format'

export default function BehavioralPanel({ account, days }: { account?: string; days: number }) {
  const q = `/api/v2/journal/behavioral?days=${days}${account ? `&account=${account}` : ''}`
  const { data, loading } = useApi<any>(q, 120_000)
  const d = data?.data ?? data
  if (loading) return <div style={{ color: 'var(--text3)', padding: 20 }}>Loading behavioral analytics…</div>
  if (!d?.ok) return null

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
      <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14 }}>
        <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 8 }}>Tilt / emotional trades</div>
        <div style={{ fontSize: 20, fontWeight: 700, color: (d.tilt?.net_pnl ?? 0) >= 0 ? '#22c55e' : '#ef4444' }}>{fmt$(d.tilt?.net_pnl, 0)}</div>
        <div style={{ fontSize: 10, color: 'var(--text3)' }}>{d.tilt?.trades ?? 0} trades tagged tilt/greed/fear</div>
        <div style={{ fontSize: 10, color: '#f59e0b', marginTop: 8 }}>Revenge-tagged: {d.revenge_tags ?? 0}</div>
      </div>
      <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14 }}>
        <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 8 }}>Performance after streaks</div>
        <div style={{ fontSize: 10, padding: '4px 0' }}>After winning day: {d.after_winning_day?.trades ?? 0}t · {d.after_winning_day?.win_rate ?? 0}% · {fmt$(d.after_winning_day?.net_pnl, 0)}</div>
        <div style={{ fontSize: 10, padding: '4px 0' }}>After losing day: {d.after_losing_day?.trades ?? 0}t · {d.after_losing_day?.win_rate ?? 0}% · {fmt$(d.after_losing_day?.net_pnl, 0)}</div>
      </div>
      {(d.ai_critique?.coaching_bullets?.length > 0 || d.ai_critique?.top_improvements?.length > 0) && (
        <div style={{ gridColumn: '1 / -1', background: 'rgba(167,139,250,.06)', border: '1px solid rgba(167,139,250,.35)', borderRadius: 10, padding: 14 }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: '#c4b5fd', marginBottom: 8 }}>
            AI critique patterns ({d.ai_critique?.critique_count ?? 0} trades)
          </div>
          {(d.ai_critique?.coaching_bullets ?? []).map((b: string, i: number) => (
            <div key={i} style={{ fontSize: 10, color: 'var(--text2)', padding: '2px 0' }}>• {b}</div>
          ))}
          {(d.ai_critique?.top_improvements ?? []).slice(0, 5).map((m: any) => (
            <div key={m.text} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, padding: '3px 0', borderBottom: '1px solid var(--border)' }}>
              <span style={{ color: '#fca5a5' }}>{m.text.slice(0, 80)}</span>
              <span style={{ color: 'var(--text3)' }}>{m.count}×</span>
            </div>
          ))}
        </div>
      )}
      <div style={{ gridColumn: '1 / -1', background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14 }}>
        <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 8 }}>Mistake frequency & $ impact</div>
        {(d.mistake_cost || []).slice(0, 12).map((m: any) => (
          <div key={m.tag} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, padding: '3px 0', borderBottom: '1px solid var(--border)' }}>
            <span style={{ color: '#ef4444' }}>{m.tag}</span>
            <span>{m.count}×</span>
            <span style={{ color: m.avg_pnl >= 0 ? '#22c55e' : '#ef4444' }}>avg {fmt$(m.avg_pnl, 0)}</span>
            <span>{fmt$(m.pnl, 0)} total</span>
          </div>
        ))}
        {(d.mistake_cost || []).length === 0 && <div style={{ fontSize: 10, color: 'var(--text3)' }}>Tag trades with mistakes to populate this report.</div>}
      </div>
    </div>
  )
}