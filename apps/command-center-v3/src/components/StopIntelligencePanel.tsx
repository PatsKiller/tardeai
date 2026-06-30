/** Trade-Detail panel: replay "what-if" — what a 2x ATR / Chandelier(22,3) trail WOULD have done vs the
 *  actual exit + the optimal, from the trade's intrabar path. Advisory/read-only.
 *  Source: /api/v2/scalp/stop-intelligence?trade_id= (scalp_stop_intelligence.py). */
import { useApi } from '../hooks/useApi'

const rCol = (r: any) => r == null ? 'var(--text3)' : Number(r) >= 0 ? '#22c55e' : '#ef4444'

export default function StopIntelligencePanel({ tradeId }: { tradeId?: number | string }) {
  const { data } = useApi<any>(`/api/v2/scalp/stop-intelligence?trade_id=${tradeId ?? ''}`, 0)
  const d = data?.data ?? data
  if (!tradeId || !d) return null
  if (d.error) return (
    <div style={{ fontSize: 10, color: 'var(--text3)', padding: '6px 0' }}>Stop Intelligence: {d.error}</div>
  )
  const v = d.variants ?? {}
  const rows: [string, any][] = [
    ['Actual exit', v.actual?.R],
    ['Fixed stop (no trail)', v.fixed_stop_no_trail?.R],
    ['2× ATR trail', v.atr_2x_trail?.R],
    ['Chandelier (22,3)', v.chandelier_22_3?.R],
    ['Optimal (replay)', d.optimal_exit?.R],
  ]
  const best = Math.max(...rows.map(([, r]) => (r == null ? -Infinity : Number(r))))

  return (
    <div style={{ background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 8, padding: 10, marginTop: 8 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
        <span style={{ fontSize: 12, fontWeight: 800, color: 'var(--text0)' }}>🔬 Stop Intelligence (replay)</span>
        <span style={{ fontSize: 9.5, color: 'var(--text3)' }}>{d.symbol} · {d.bars} bars{d.bars_dropped_corrupt ? ` · ${d.bars_dropped_corrupt} corrupt dropped` : ''}</span>
      </div>
      <div style={{ marginTop: 6, display: 'grid', gridTemplateColumns: '1fr auto', gap: '2px 12px', fontSize: 11 }}>
        {rows.map(([label, r], i) => {
          const isBest = r != null && Number(r) === best
          return [
            <span key={`l${i}`} style={{ color: isBest ? 'var(--text0)' : 'var(--text2)', fontWeight: isBest ? 800 : 600 }}>
              {label}{isBest && <span style={{ color: '#22c55e', fontSize: 9 }}> ◆ best</span>}</span>,
            <span key={`r${i}`} style={{ textAlign: 'right', fontFamily: 'monospace', fontWeight: 700, color: rCol(r) }}>
              {r == null ? '—' : `${Number(r) >= 0 ? '+' : ''}${r}R`}</span>,
          ]
        })}
      </div>
      <div style={{ fontSize: 10, color: d.verdict?.includes('LEFT MONEY') || d.verdict?.includes('keep trailing off') ? '#f59e0b' : 'var(--text2)',
        marginTop: 7, fontWeight: 600, lineHeight: 1.4 }}>
        {d.verdict}
      </div>
      <div style={{ fontSize: 8.5, color: 'var(--text3)', marginTop: 4 }}>{d.note}</div>
    </div>
  )
}
