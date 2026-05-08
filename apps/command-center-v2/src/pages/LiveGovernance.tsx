import React from 'react'
import PageHeader from '../components/PageHeader'
import { useApi } from '../hooks/useApi'

const mono: React.CSSProperties = { fontFamily: 'monospace' }
const pill = (color: string): React.CSSProperties => ({
  fontSize: 9, padding: '2px 6px', borderRadius: 4, fontWeight: 600,
  background: color === 'green' ? 'rgba(34,197,94,0.15)' : color === 'red' ? 'rgba(239,68,68,0.15)' : color === 'blue' ? 'rgba(59,130,246,0.15)' : 'rgba(251,191,36,0.15)',
  color: color === 'green' ? 'var(--green)' : color === 'red' ? 'var(--red)' : color === 'blue' ? '#60A5FA' : 'var(--amber)',
})

const GATE_LABELS: Record<string, { label: string; threshold: string }> = {
  min_closed_paper_trades: { label: 'Paper Trades', threshold: '30 closed' },
  min_win_rate: { label: 'Win Rate', threshold: '55%' },
  min_profit_factor: { label: 'Profit Factor', threshold: '1.30' },
  min_calendar_months: { label: 'Calendar Months', threshold: '6 months' },
  tca_slippage: { label: 'TCA Slippage', threshold: 'Acceptable' },
  broker_recon: { label: 'Broker Recon', threshold: '0 issues' },
  human_approval: { label: 'Human Approval', threshold: 'Required' },
}

function GateCheck({ label, threshold, actual, passed }: { label: string; threshold: string; actual: string; passed: boolean }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '4px 0', borderBottom: '1px solid var(--border)' }}>
      <span style={{ width: 12, height: 12, borderRadius: '50%', background: passed ? 'var(--green)' : 'var(--red)', flexShrink: 0 }} />
      <span style={{ fontSize: 11, color: 'var(--text1)', flex: 1 }}>{label}</span>
      <span style={{ fontSize: 10, color: 'var(--text3)', ...mono }}>{threshold}</span>
      <span style={{ fontSize: 10, color: passed ? 'var(--green)' : 'var(--red)', fontWeight: 600, ...mono, minWidth: 60, textAlign: 'right' }}>{actual}</span>
    </div>
  )
}

export default function LiveGovernance() {
  const { data: govData } = useApi<any>('/api/v2/paper-performance-governance', 60000)
  const { data: stratData } = useApi<any>('/api/v2/strategy-configs', 60000)
  const { data: reconData } = useApi<any>('/api/v2/broker-reconciliation', 60000)
  const { data: tcaData } = useApi<any>('/api/v2/execution-quality', 60000)

  const gov = govData?.data || []
  const strategies = stratData?.strategies ? Object.values(stratData.strategies) as any[] : []
  const reconRuns = reconData?.runs || []
  const tca = tcaData?.data || []

  const totalTrades = gov.reduce((s: number, g: any) => s + (g.paper_trades || 0), 0)
  const totalClosed = gov.reduce((s: number, g: any) => s + (g.closed_trades || 0), 0)
  const liveEligible = gov.filter((g: any) => g.live_eligible).length
  const stratCount = strategies.length

  // Calculate days since first paper trade
  const firstTradeDate = gov.length > 0 ? gov.reduce((earliest: string, g: any) => {
    const d = g.window_start || g.created_at
    return d && (!earliest || d < earliest) ? d : earliest
  }, '') : null
  const daysSinceFirst = firstTradeDate ? Math.floor((Date.now() - new Date(firstTradeDate).getTime()) / 86400000) : 0

  return (
    <div style={{ minHeight: '100vh' }}>
      <PageHeader title="Live Trading Governance" subtitle="Paper validation path to live eligibility" />

      {/* Global Status Banner */}
      <div style={{ padding: 16, marginBottom: 16, background: 'rgba(239,68,68,0.05)', border: '1px solid rgba(239,68,68,0.2)', borderRadius: 8 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 8 }}>
          <span style={{ fontSize: 14, fontWeight: 700, color: 'var(--red)' }}>LIVE TRADING: DISABLED</span>
          <span style={pill('red')}>PAPER_ONLY</span>
        </div>
        <div style={{ fontSize: 11, color: 'var(--text2)', lineHeight: 1.5 }}>
          All strategies require six months of validated paper results before live eligibility review.
          Live trading cannot be enabled without human governance approval.
        </div>
      </div>

      {/* Progress Overview */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 12, marginBottom: 20, padding: 16, background: 'var(--bg1)', borderRadius: 8, border: '1px solid var(--border)' }}>
        <div>
          <div style={{ fontSize: 8, color: 'var(--text3)', textTransform: 'uppercase' }}>Total Strategies</div>
          <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--text0)', ...mono }}>{stratCount}</div>
        </div>
        <div>
          <div style={{ fontSize: 8, color: 'var(--text3)', textTransform: 'uppercase' }}>Paper Trades</div>
          <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--text0)', ...mono }}>{totalTrades}</div>
        </div>
        <div>
          <div style={{ fontSize: 8, color: 'var(--text3)', textTransform: 'uppercase' }}>Closed Trades</div>
          <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--text0)', ...mono }}>{totalClosed}</div>
        </div>
        <div>
          <div style={{ fontSize: 8, color: 'var(--text3)', textTransform: 'uppercase' }}>Days Tracking</div>
          <div style={{ fontSize: 18, fontWeight: 700, color: daysSinceFirst >= 180 ? 'var(--green)' : 'var(--amber)', ...mono }}>{daysSinceFirst}</div>
        </div>
        <div>
          <div style={{ fontSize: 8, color: 'var(--text3)', textTransform: 'uppercase' }}>Live Eligible</div>
          <div style={{ fontSize: 18, fontWeight: 700, color: liveEligible > 0 ? 'var(--green)' : 'var(--red)', ...mono }}>{liveEligible}/{stratCount}</div>
        </div>
      </div>

      {/* Per-Strategy Governance */}
      <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text1)', marginBottom: 8 }}>Strategy Governance Status</div>
      <div style={{ background: 'var(--bg1)', borderRadius: 8, border: '1px solid var(--border)', overflow: 'auto', marginBottom: 20 }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11, ...mono }}>
          <thead>
            <tr style={{ borderBottom: '2px solid var(--border)' }}>
              {['Strategy', 'State', 'Trades', 'Closed', 'Win %', 'Avg R', 'PF', 'Max DD', 'Slippage', 'Recon', 'Live', 'Block Reason'].map(h => (
                <th key={h} style={{ padding: '8px 10px', textAlign: 'left', fontSize: 9, color: 'var(--text3)', fontWeight: 600, textTransform: 'uppercase' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {gov.length === 0 && (
              <tr><td colSpan={12} style={{ padding: 20, textAlign: 'center', color: 'var(--text3)', fontStyle: 'italic' }}>No governance data yet. Run governance calculator to populate.</td></tr>
            )}
            {gov.map((g: any) => {
              const sc = g.governance_state === 'PAPER_ONLY' ? 'amber' : g.governance_state === 'WATCHLIST' ? 'blue' : g.governance_state === 'CANDIDATE_FOR_REVIEW' ? 'green' : 'red'
              return (
                <tr key={g.id} style={{ borderBottom: '1px solid var(--border)' }}>
                  <td style={{ padding: '6px 10px', fontWeight: 700 }}>{g.strategy_id}</td>
                  <td style={{ padding: '6px 10px' }}><span style={pill(sc)}>{g.governance_state}</span></td>
                  <td style={{ padding: '6px 10px' }}>{g.paper_trades ?? 0}</td>
                  <td style={{ padding: '6px 10px' }}>{g.closed_trades ?? 0}</td>
                  <td style={{ padding: '6px 10px' }}>{g.win_rate != null ? `${Number(g.win_rate).toFixed(1)}%` : '--'}</td>
                  <td style={{ padding: '6px 10px' }}>{g.avg_r != null ? Number(g.avg_r).toFixed(2) : '--'}</td>
                  <td style={{ padding: '6px 10px' }}>{g.profit_factor != null ? Number(g.profit_factor).toFixed(2) : '--'}</td>
                  <td style={{ padding: '6px 10px' }}>{g.max_drawdown_r != null ? Number(g.max_drawdown_r).toFixed(2) : '--'}</td>
                  <td style={{ padding: '6px 10px' }}>{g.tca_avg_slippage_pct != null ? `${Number(g.tca_avg_slippage_pct).toFixed(3)}%` : '--'}</td>
                  <td style={{ padding: '6px 10px' }}>{g.broker_recon_issues ?? '--'}</td>
                  <td style={{ padding: '6px 10px' }}><span style={pill(g.live_eligible ? 'green' : 'red')}>{g.live_eligible ? 'YES' : 'NO'}</span></td>
                  <td style={{ padding: '6px 10px', color: 'var(--text3)', fontSize: 9 }}>{(g.live_block_reason || '').slice(0, 40)}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {/* Validation Gates Checklist */}
      <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text1)', marginBottom: 8 }}>Live Eligibility Gates</div>
      <div style={{ background: 'var(--bg1)', borderRadius: 8, border: '1px solid var(--border)', padding: 16, marginBottom: 20 }}>
        <GateCheck label="Paper Trade History" threshold="30+ closed per strategy" actual={`${totalClosed} total`} passed={totalClosed >= 30} />
        <GateCheck label="Calendar Duration" threshold="6+ months" actual={`${daysSinceFirst} days`} passed={daysSinceFirst >= 180} />
        <GateCheck label="Positive Expectancy" threshold="All strategies" actual={gov.filter((g: any) => Number(g.expectancy_r || 0) > 0).length + '/' + gov.length} passed={gov.length > 0 && gov.every((g: any) => Number(g.expectancy_r || 0) > 0)} />
        <GateCheck label="Profit Factor" threshold=">= 1.25" actual={gov.filter((g: any) => Number(g.profit_factor || 0) >= 1.25).length + '/' + gov.length} passed={gov.length > 0 && gov.every((g: any) => Number(g.profit_factor || 0) >= 1.25)} />
        <GateCheck label="Broker Reconciliation" threshold="0 unresolved issues" actual={`${reconRuns.length > 0 ? (reconRuns[0].unmatched_broker_orders || 0) + (reconRuns[0].unmatched_local_trades || 0) : '?'} issues`} passed={reconRuns.length > 0 && (reconRuns[0].unmatched_broker_orders || 0) === 0 && (reconRuns[0].unmatched_local_trades || 0) === 0} />
        <GateCheck label="TCA Slippage" threshold="Acceptable avg" actual={tca.length > 0 ? `${tca.length} fills analyzed` : 'No data'} passed={tca.length > 0} />
        <GateCheck label="Human Governance Review" threshold="Required" actual="NOT SUBMITTED" passed={false} />
      </div>

      <div style={{ padding: 12, background: 'rgba(251,191,36,0.05)', border: '1px solid rgba(251,191,36,0.2)', borderRadius: 8, fontSize: 11, color: 'var(--amber)' }}>
        Live trading enablement requires all gates to pass AND manual human governance review. This system is currently in paper-only validation mode.
      </div>
    </div>
  )
}
