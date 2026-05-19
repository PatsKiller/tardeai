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

const GATES = [
  { id: 'duration', label: '6 months paper trading', description: 'Minimum 6 months of paper trading history' },
  { id: 'closed_trades', label: '30+ closed trades', description: 'At least 30 closed paper trades per strategy' },
  { id: 'win_rate', label: 'Win rate >= 45%', description: 'Consistent win rate above minimum threshold' },
  { id: 'profit_factor', label: 'Profit factor >= 1.3', description: 'Profit factor demonstrates edge' },
  { id: 'expectancy', label: 'Positive expectancy (R > 0.15)', description: 'Positive expected value per trade' },
  { id: 'tca', label: 'TCA slippage acceptable', description: 'Execution quality within acceptable bounds' },
  { id: 'reconciliation', label: 'Clean reconciliation', description: 'No unresolved broker reconciliation issues' },
  { id: 'human_approval', label: 'Human approval', description: 'Manual review and sign-off by portfolio manager' },
]

export default function PaperGovernance() {
  const { data: govData, loading: gLoading } = useApi<any>('/api/v2/paper-performance-governance', 60000)
  const { data: summaryData, loading: sLoading } = useApi<any>('/api/v2/paper-dashboard-summary', 60000)
  const { data: catalogData } = useApi<any>('/api/v2/ticker-catalog/summary', 60000)
  const { data: membershipData } = useApi<any>('/api/v2/screener-membership/summary', 60000)
  const { data: lifecycleData } = useApi<any>('/api/v2/incubator-lifecycle/summary', 60000)
  const [running, setRunning] = useState(false)

  const runGovernance = async () => {
    setRunning(true)
    try {
      await fetch('/api/v2/paper-performance-governance/run', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
      window.location.reload()
    } catch { alert('Failed') }
    setRunning(false)
  }

  const gov = govData?.data || []
  const summary = summaryData?.summary || {}

  const totalTrades = gov.reduce((s: number, g: any) => s + (g.paper_trades || 0), 0)
  const totalClosed = gov.reduce((s: number, g: any) => s + (g.closed_trades || 0), 0)
  const strategiesWithData = gov.filter((g: any) => (g.paper_trades || 0) > 0).length
  const liveEligible = gov.filter((g: any) => g.live_eligible).length

  return (
    <>
      <PageHeader title="Paper Trading Governance" subtitle="Six-month paper validation gate — all strategies must pass before live trading" />
      <div style={{ padding: '0 24px 24px' }}>
        {/* LIVE TRADING DISABLED BANNER */}
        <div style={{
          padding: '14px 20px', marginBottom: 20, borderRadius: 8,
          background: 'rgba(239,68,68,0.08)', border: '2px solid rgba(239,68,68,0.4)',
          display: 'flex', alignItems: 'center', gap: 12,
        }}>
          <div style={{ fontSize: 20 }}>&#x26D4;</div>
          <div>
            <div style={{ fontSize: 14, fontWeight: 800, color: 'var(--red)', letterSpacing: '0.5px' }}>
              LIVE TRADING DISABLED
            </div>
            <div style={{ fontSize: 11, color: 'var(--text2)', marginTop: 2 }}>
              Six-month paper validation required. All governance gates must pass before any strategy is eligible for live execution.
            </div>
          </div>
        </div>

        {(gLoading || sLoading) && <div style={{ color: 'var(--text3)', fontSize: 12 }}>Loading...</div>}

        {/* Summary Tiles */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)', gap: 12, marginBottom: 16, padding: 16, background: 'var(--bg1)', borderRadius: 8, border: '1px solid var(--border)' }}>
          {kv('Open Trades', summary.open_paper_trades ?? totalTrades)}
          {kv('Closed Trades', summary.closed_paper_trades ?? totalClosed)}
          {kv('Strategies', strategiesWithData)}
          {kv('Live Eligible', liveEligible, liveEligible > 0 ? 'var(--green)' : 'var(--red)')}
          {kv('Outcome Reviews', summary.outcome_reviews ?? 0)}
          {kv('Recon Issues', summary.reconciliation_issues ?? 0, (summary.reconciliation_issues || 0) > 0 ? 'var(--red)' : 'var(--green)')}
        </div>

        {/* Run button */}
        <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
          <button onClick={runGovernance} disabled={running}
            style={{ padding: '6px 14px', fontSize: 11, fontWeight: 600, border: 'none', borderRadius: 5, cursor: 'pointer', color: '#60A5FA', background: 'rgba(59,130,246,0.15)' }}>
            {running ? 'Running...' : 'Run Governance Check'}
          </button>
        </div>

        {/* Gate Checklist */}
        <h3 style={{ fontSize: 13, color: 'var(--text1)', marginBottom: 8 }}>Governance Gate Checklist</h3>
        <div style={{ background: 'var(--bg1)', borderRadius: 8, border: '1px solid var(--border)', padding: 16, marginBottom: 24 }}>
          {GATES.map(gate => (
            <div key={gate.id} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '6px 0', borderBottom: '1px solid var(--border)' }}>
              <span style={pill('red')}>NOT MET</span>
              <div>
                <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text0)' }}>{gate.label}</div>
                <div style={{ fontSize: 9, color: 'var(--text3)' }}>{gate.description}</div>
              </div>
            </div>
          ))}
        </div>

        {/* Strategy Scorecards */}
        <h3 style={{ fontSize: 13, color: 'var(--text1)', marginBottom: 8 }}>Strategy Scorecards</h3>
        <div style={{ background: 'var(--bg1)', borderRadius: 8, border: '1px solid var(--border)', overflow: 'auto', marginBottom: 24 }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11, ...mono }}>
            <thead>
              <tr style={{ borderBottom: '2px solid var(--border)' }}>
                {['Strategy', 'Paper Trades', 'Closed', 'Win Rate', 'Profit Factor', 'Expectancy', 'State', 'Live Eligible'].map(h => (
                  <th key={h} style={{ padding: '8px 10px', textAlign: 'left', fontSize: 9, color: 'var(--text3)', fontWeight: 600, textTransform: 'uppercase' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {gov.length === 0 && (
                <tr><td colSpan={8} style={{ padding: 20, textAlign: 'center', color: 'var(--text3)', fontStyle: 'italic' }}>
                  No closed paper trades yet. Governance analytics will activate after paper trades close.
                </td></tr>
              )}
              {gov.map((g: any) => {
                const stateColor = g.governance_state === 'PAPER_ONLY' ? 'amber' : g.governance_state === 'WATCHLIST' ? 'blue' : g.governance_state === 'CANDIDATE_FOR_REVIEW' ? 'green' : 'red'
                return (
                  <tr key={g.id} style={{ borderBottom: '1px solid var(--border)' }}>
                    <td style={{ padding: '6px 10px', fontWeight: 700 }}>{g.strategy_id}</td>
                    <td style={{ padding: '6px 10px' }}>{g.paper_trades ?? 0}</td>
                    <td style={{ padding: '6px 10px' }}>{g.closed_trades ?? 0}</td>
                    <td style={{ padding: '6px 10px' }}>{g.win_rate != null ? `${Number(g.win_rate).toFixed(1)}%` : '--'}</td>
                    <td style={{ padding: '6px 10px' }}>{g.profit_factor != null ? Number(g.profit_factor).toFixed(2) : '--'}</td>
                    <td style={{ padding: '6px 10px' }}>{g.expectancy_r != null ? Number(g.expectancy_r).toFixed(2) : '--'}</td>
                    <td style={{ padding: '6px 10px' }}><span style={pill(stateColor)}>{g.governance_state}</span></td>
                    <td style={{ padding: '6px 10px', color: g.live_eligible ? 'var(--green)' : 'var(--red)', fontWeight: 700 }}>{g.live_eligible ? 'YES' : 'NO'}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>

        {/* Dashboard Summary */}
        {summaryData?.summary && (
          <>
            <h3 style={{ fontSize: 13, color: 'var(--text1)', marginBottom: 8 }}>System Summary</h3>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, padding: 16, background: 'var(--bg1)', borderRadius: 8, border: '1px solid var(--border)' }}>
              {kv('Execution Quality Rows', summary.execution_quality_rows ?? 0)}
              {kv('Strategies Learning', summary.strategies_in_learning_mode ?? 0)}
              {kv('Last Reconciliation', summary.last_reconciliation ? new Date(summary.last_reconciliation).toLocaleString() : 'Never')}
              {kv('Last TCA Run', summary.last_tca_run ? new Date(summary.last_tca_run).toLocaleString() : 'Never')}
            </div>
          </>
        )}

        {/* SCREENER-ARCH-3C: Scanner Catalog Lifecycle */}
        {(catalogData || membershipData || lifecycleData) && (
          <>
            <h3 style={{ fontSize: 13, color: 'var(--text1)', marginTop: 24, marginBottom: 8 }}>Scanner Catalog Lifecycle</h3>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 12, padding: 16, background: 'var(--bg1)', borderRadius: 8, border: '1px solid var(--border)' }}>
              {kv('Cataloged Tickers', catalogData?.cataloged_tickers ?? '--')}
              {kv('Active in Universe', catalogData?.active_in_universe ?? '--')}
              {kv('Present Memberships', membershipData?.present ?? '--', 'var(--green)')}
              {kv('Dropped', membershipData?.dropped ?? '--', membershipData?.dropped > 0 ? 'var(--amber)' : undefined)}
              {kv('Reentered', membershipData?.reentered_events ?? '--', membershipData?.reentered_events > 0 ? '#60A5FA' : undefined)}
              {kv('Source Missing', lifecycleData?.source_missing ?? '--', lifecycleData?.source_missing > 0 ? 'var(--amber)' : undefined)}
              {kv('Dropped from All', membershipData?.dropped_from_all_screeners ?? '--', membershipData?.dropped_from_all_screeners > 0 ? 'var(--red)' : undefined)}
              {kv('Data Confidence', membershipData?.dropped !== undefined ? (membershipData.dropped_from_all_screeners > membershipData.present ? 'NEEDS_REVIEW' : membershipData.dropped > 0 ? 'PARTIAL' : 'GOOD') : '--',
                membershipData?.dropped_from_all_screeners > membershipData?.present ? 'var(--red)' : membershipData?.dropped > 0 ? 'var(--amber)' : 'var(--green)')}
            </div>
          </>
        )}
      </div>
    </>
  )
}
