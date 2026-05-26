# Source Export: apps/command-center-v2/src/pages/ExecutionQuality.tsx

| Field | Value |
|-------|-------|
| **Original Path** | `apps/command-center-v2/src/pages/ExecutionQuality.tsx` |
| **Git Branch** | `main` |
| **Git Commit** | `c1286d314deb377df49713e1646f139db7f43643` |
| **Export Timestamp** | `2026-05-26T15:49:17Z` |
| **SHA256** | `c208127ba5c3e7768039c7297ae00ced36ff4eddbe70e4922fde77db25af82de` |
| **File Size** | 9072 bytes |

## Full Source

```tsx
import React, { useState } from 'react'
import PageHeader from '../components/PageHeader'
import { useApi } from '../hooks/useApi'

const mono: React.CSSProperties = { fontFamily: 'monospace' }
const lbl: React.CSSProperties = { fontSize: 8, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '0.3px' }
const pill = (color: string): React.CSSProperties => ({
  fontSize: 9, padding: '2px 6px', borderRadius: 4, fontWeight: 600,
  background: color === 'green' ? 'rgba(34,197,94,0.15)' : color === 'red' ? 'rgba(239,68,68,0.15)' : color === 'blue' ? 'rgba(59,130,246,0.15)' : 'rgba(251,191,36,0.15)',
  color: color === 'green' ? 'var(--green)' : color === 'red' ? 'var(--red)' : color === 'blue' ? '#60A5FA' : 'var(--amber)',
})
const kv = (label: string, value: any, color?: string) => (
  <div key={label}>
    <div style={lbl}>{label}</div>
    <div style={{ fontSize: 11, color: color || 'var(--text0)', fontWeight: 600, ...mono }}>{value ?? '--'}</div>
  </div>
)
const qualColor = (q: string) => q === 'EXCELLENT' ? 'green' : q === 'GOOD' ? 'green' : q === 'ACCEPTABLE' ? 'blue' : q === 'POOR' ? 'red' : 'amber'

export default function ExecutionQuality() {
  const { data, loading } = useApi<any>('/api/v2/execution-quality', 30000)
  const { data: govData } = useApi<any>('/api/v2/paper-performance-governance', 60000)
  const [running, setRunning] = useState(false)

  const runTCA = async () => {
    setRunning(true)
    try {
      await fetch('/api/v2/execution-quality/run', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
      window.location.reload()
    } catch { alert('Failed') }
    setRunning(false)
  }

  const rows = data?.data || []
  const gov = govData?.data || []

  // Aggregate stats
  const filled = rows.filter((r: any) => r.fill_quality && r.fill_quality !== 'UNKNOWN')
  const avgSlippage = filled.length > 0 ? filled.reduce((s: number, r: any) => s + (Number(r.slippage_pct) || 0), 0) / filled.length : null
  const qualCounts: Record<string, number> = {}
  rows.forEach((r: any) => { qualCounts[r.fill_quality || 'UNKNOWN'] = (qualCounts[r.fill_quality || 'UNKNOWN'] || 0) + 1 })

  return (
    <>
      <PageHeader title="Execution Quality (TCA)" subtitle="Paper trade fill quality and slippage analysis" />
      <div style={{ padding: '0 24px 24px' }}>
        {loading && <div style={{ color: 'var(--text3)', fontSize: 12 }}>Loading...</div>}

        {/* Summary */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 12, marginBottom: 16, padding: 16, background: 'var(--bg1)', borderRadius: 8, border: '1px solid var(--border)' }}>
          {kv('Total Fills', rows.length)}
          {kv('Avg Slippage', avgSlippage != null ? `${avgSlippage.toFixed(3)}%` : '--')}
          {kv('Excellent', qualCounts['EXCELLENT'] || 0, 'var(--green)')}
          {kv('Good', qualCounts['GOOD'] || 0, 'var(--green)')}
          {kv('Poor/Unknown', (qualCounts['POOR'] || 0) + (qualCounts['UNKNOWN'] || 0), (qualCounts['POOR'] || 0) > 0 ? 'var(--red)' : undefined)}
        </div>

        <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
          <button onClick={runTCA} disabled={running}
            style={{ padding: '6px 14px', fontSize: 11, fontWeight: 600, border: 'none', borderRadius: 5, cursor: 'pointer', color: '#60A5FA', background: 'rgba(59,130,246,0.15)' }}>
            {running ? 'Running...' : 'Run TCA Analysis'}
          </button>
        </div>

        {/* Table */}
        <div style={{ background: 'var(--bg1)', borderRadius: 8, border: '1px solid var(--border)', overflow: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11, ...mono }}>
            <thead>
              <tr style={{ borderBottom: '2px solid var(--border)' }}>
                {['Symbol', 'Strategy', 'Intended', 'Fill', 'Slippage %', 'Slippage $', 'Bid', 'Ask', 'Spread %', 'Quality', 'Date'].map(h => (
                  <th key={h} style={{ padding: '8px 10px', textAlign: 'left', fontSize: 9, color: 'var(--text3)', fontWeight: 600, textTransform: 'uppercase' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 && (
                <tr><td colSpan={11} style={{ padding: 20, textAlign: 'center', color: 'var(--text3)', fontStyle: 'italic' }}>No execution quality data yet. Run TCA analysis after paper trades fill.</td></tr>
              )}
              {rows.map((r: any) => (
                <tr key={r.id} style={{ borderBottom: '1px solid var(--border)' }}>
                  <td style={{ padding: '6px 10px', fontWeight: 700 }}>{r.symbol}</td>
                  <td style={{ padding: '6px 10px', color: 'var(--text2)' }}>{r.strategy_id || '--'}</td>
                  <td style={{ padding: '6px 10px' }}>{r.intended_entry ? `$${Number(r.intended_entry).toFixed(2)}` : '--'}</td>
                  <td style={{ padding: '6px 10px' }}>{r.fill_price ? `$${Number(r.fill_price).toFixed(2)}` : '--'}</td>
                  <td style={{ padding: '6px 10px', color: Number(r.slippage_pct) > 0.5 ? 'var(--red)' : 'var(--green)' }}>{r.slippage_pct != null ? `${Number(r.slippage_pct).toFixed(3)}%` : '--'}</td>
                  <td style={{ padding: '6px 10px' }}>{r.slippage_dollars != null ? `$${Number(r.slippage_dollars).toFixed(2)}` : '--'}</td>
                  <td style={{ padding: '6px 10px', color: 'var(--text2)' }}>{r.quote_bid ? `$${Number(r.quote_bid).toFixed(2)}` : '--'}</td>
                  <td style={{ padding: '6px 10px', color: 'var(--text2)' }}>{r.quote_ask ? `$${Number(r.quote_ask).toFixed(2)}` : '--'}</td>
                  <td style={{ padding: '6px 10px' }}>{r.spread_pct != null ? `${Number(r.spread_pct).toFixed(3)}%` : '--'}</td>
                  <td style={{ padding: '6px 10px' }}><span style={pill(qualColor(r.fill_quality || 'UNKNOWN'))}>{r.fill_quality || 'UNKNOWN'}</span></td>
                  <td style={{ padding: '6px 10px', color: 'var(--text3)', fontSize: 9 }}>{r.created_at ? new Date(r.created_at).toLocaleDateString() : '--'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Governance Summary */}
        {gov.length > 0 && (
          <>
            <h3 style={{ fontSize: 13, color: 'var(--text1)', marginTop: 24, marginBottom: 8 }}>Paper Performance Governance</h3>
            <div style={{ background: 'var(--bg1)', borderRadius: 8, border: '1px solid var(--border)', overflow: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11, ...mono }}>
                <thead>
                  <tr style={{ borderBottom: '2px solid var(--border)' }}>
                    {['Strategy', 'Trades', 'Closed', 'Win Rate', 'Avg R', 'Expectancy', 'PF', 'Drawdown', 'TCA Slip', 'State', 'Live'].map(h => (
                      <th key={h} style={{ padding: '8px 10px', textAlign: 'left', fontSize: 9, color: 'var(--text3)', fontWeight: 600, textTransform: 'uppercase' }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {gov.map((g: any) => {
                    const stateColor = g.governance_state === 'PAPER_ONLY' ? 'amber' : g.governance_state === 'WATCHLIST' ? 'blue' : g.governance_state === 'CANDIDATE_FOR_REVIEW' ? 'green' : 'red'
                    return (
                      <tr key={g.id} style={{ borderBottom: '1px solid var(--border)' }}>
                        <td style={{ padding: '6px 10px', fontWeight: 700 }}>{g.strategy_id}</td>
                        <td style={{ padding: '6px 10px' }}>{g.paper_trades ?? 0}</td>
                        <td style={{ padding: '6px 10px' }}>{g.closed_trades ?? 0}</td>
                        <td style={{ padding: '6px 10px' }}>{g.win_rate != null ? `${Number(g.win_rate).toFixed(1)}%` : '--'}</td>
                        <td style={{ padding: '6px 10px' }}>{g.avg_r != null ? Number(g.avg_r).toFixed(2) : '--'}</td>
                        <td style={{ padding: '6px 10px' }}>{g.expectancy_r != null ? Number(g.expectancy_r).toFixed(2) : '--'}</td>
                        <td style={{ padding: '6px 10px' }}>{g.profit_factor != null ? Number(g.profit_factor).toFixed(2) : '--'}</td>
                        <td style={{ padding: '6px 10px' }}>{g.max_drawdown_r != null ? Number(g.max_drawdown_r).toFixed(2) : '--'}</td>
                        <td style={{ padding: '6px 10px' }}>{g.tca_avg_slippage_pct != null ? `${Number(g.tca_avg_slippage_pct).toFixed(3)}%` : '--'}</td>
                        <td style={{ padding: '6px 10px' }}><span style={pill(stateColor)}>{g.governance_state}</span></td>
                        <td style={{ padding: '6px 10px', color: g.live_eligible ? 'var(--green)' : 'var(--red)' }}>{g.live_eligible ? 'YES' : 'NO'}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>
    </>
  )
}
```
