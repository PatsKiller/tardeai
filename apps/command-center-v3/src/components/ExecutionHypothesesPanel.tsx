import { useApi } from '../hooks/useApi'

// Evidence-only: did an alternative entry/exit rule actually improve expectancy vs the real fills?
// Source: /api/v2/backtesting/execution-hypotheses (build_trade_execution_quality + backtest_execution_hypotheses).
const LABEL: Record<string, string> = {
  volume_confirmed_entry: 'Wait for volume confirmation before entry',
  hold_above_vwap: 'Hold while price stays above session VWAP',
  macd_rollover_exit: 'Exit on MACD histogram rollover',
}

export default function ExecutionHypothesesPanel() {
  const { data } = useApi<any>('/api/v2/backtesting/execution-hypotheses', 120_000)
  const agg: any[] = data?.aggregate ?? []
  if (!agg.length) return null
  return (
    <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14, marginBottom: 14 }}>
      <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)' }}>Execution-Rule Hypotheses — evidence only</div>
      <div style={{ fontSize: 10, color: 'var(--text3)', margin: '3px 0 10px' }}>Would an alternative rule have beaten your actual fills? Replayed on real intraday bars. Never auto-applied to live configs.</div>
      <div style={{ display: 'grid', gridTemplateColumns: '2fr 0.7fr 0.9fr 1fr 0.9fr', fontSize: 9, color: 'var(--text3)', padding: '2px 6px', borderBottom: '1px solid var(--border)' }}>
        <span>Hypothesis</span><span style={{ textAlign: 'right' }}>Sample</span><span style={{ textAlign: 'right' }}>Improved</span><span style={{ textAlign: 'right' }}>Avg Δ/sh</span><span style={{ textAlign: 'right' }}>Verdict</span>
      </div>
      {agg.map((a, i) => {
        const helps = (a.avg_delta_ps ?? 0) > 0
        return (
          <div key={i} style={{ display: 'grid', gridTemplateColumns: '2fr 0.7fr 0.9fr 1fr 0.9fr', fontSize: 10, padding: '5px 6px', borderBottom: '1px solid var(--border)', alignItems: 'center' }}>
            <span style={{ color: 'var(--text1)' }}>{LABEL[a.hypothesis] ?? a.hypothesis}</span>
            <span style={{ textAlign: 'right', color: 'var(--text3)' }}>{a.sample}</span>
            <span style={{ textAlign: 'right', color: 'var(--text2)' }}>{a.improved_pct}%</span>
            <span style={{ textAlign: 'right', fontWeight: 700, color: helps ? '#22c55e' : '#ef4444' }}>{helps ? '+' : ''}{a.avg_delta_ps}</span>
            <span style={{ textAlign: 'right', fontSize: 8 }}>{a.do_not_graft ? <span style={{ color: '#f59e0b' }}>too few</span> : helps ? <span style={{ color: '#22c55e' }}>helps</span> : <span style={{ color: '#ef4444' }}>hurts</span>}</span>
          </div>
        )
      })}
    </div>
  )
}
