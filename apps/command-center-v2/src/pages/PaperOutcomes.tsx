import React from 'react'
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
const resultColor = (r: string) => r === 'THESIS_CONFIRMED' ? 'green' : r === 'THESIS_PARTIAL' ? 'blue' : r === 'THESIS_INVALIDATED' ? 'red' : r === 'THESIS_ABANDONED' ? 'amber' : 'amber'

export default function PaperOutcomes() {
  const { data: thesisData, loading: tLoading } = useApi<any>('/api/v2/execution-quality', 30000)
  const { data: govData, loading: gLoading } = useApi<any>('/api/v2/paper-performance-governance', 60000)
  const { data: lcData } = useApi<any>('/api/v2/paper-proposals/lifecycle-events', 30000)

  const gov = govData?.data || []
  const events = lcData?.events || []
  const tca = thesisData?.data || []

  // Aggregate governance stats
  const totalTrades = gov.reduce((s: number, g: any) => s + (g.paper_trades || 0), 0)
  const totalClosed = gov.reduce((s: number, g: any) => s + (g.closed_trades || 0), 0)
  const strategiesWithData = gov.filter((g: any) => (g.paper_trades || 0) > 0).length
  const liveEligible = gov.filter((g: any) => g.live_eligible).length

  return (
    <>
      <PageHeader title="Paper Outcome Analytics" subtitle="Thesis outcomes, lifecycle events, and governance status" />
      <div style={{ padding: '0 24px 24px' }}>
        {(tLoading || gLoading) && <div style={{ color: 'var(--text3)', fontSize: 12 }}>Loading...</div>}

        {/* Overview */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 12, marginBottom: 16, padding: 16, background: 'var(--bg1)', borderRadius: 8, border: '1px solid var(--border)' }}>
          {kv('Total Paper Trades', totalTrades)}
          {kv('Closed Trades', totalClosed)}
          {kv('Strategies Active', strategiesWithData)}
          {kv('Live Eligible', liveEligible, liveEligible > 0 ? 'var(--green)' : 'var(--red)')}
          {kv('Governance', gov.length > 0 ? gov[0].governance_state : 'PAPER_ONLY')}
        </div>

        {/* Governance by Strategy */}
        <h3 style={{ fontSize: 13, color: 'var(--text1)', marginBottom: 8 }}>Strategy Governance</h3>
        <div style={{ background: 'var(--bg1)', borderRadius: 8, border: '1px solid var(--border)', overflow: 'auto', marginBottom: 24 }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11, ...mono }}>
            <thead>
              <tr style={{ borderBottom: '2px solid var(--border)' }}>
                {['Strategy', 'Trades', 'Closed', 'Win %', 'Avg R', 'Expect R', 'PF', 'Max DD', 'State', 'Live Block'].map(h => (
                  <th key={h} style={{ padding: '8px 10px', textAlign: 'left', fontSize: 9, color: 'var(--text3)', fontWeight: 600, textTransform: 'uppercase' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {gov.length === 0 && (
                <tr><td colSpan={10} style={{ padding: 20, textAlign: 'center', color: 'var(--text3)', fontStyle: 'italic' }}>No governance data yet. Run governance calculator after accumulating paper trades.</td></tr>
              )}
              {gov.map((g: any) => {
                const sc = g.governance_state === 'PAPER_ONLY' ? 'amber' : g.governance_state === 'WATCHLIST' ? 'blue' : g.governance_state === 'CANDIDATE_FOR_REVIEW' ? 'green' : 'red'
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
                    <td style={{ padding: '6px 10px' }}><span style={pill(sc)}>{g.governance_state}</span></td>
                    <td style={{ padding: '6px 10px', color: 'var(--text3)', fontSize: 9 }}>{g.live_block_reason || '--'}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>

        {/* Lifecycle Events */}
        <h3 style={{ fontSize: 13, color: 'var(--text1)', marginBottom: 8 }}>Recent Lifecycle Events</h3>
        <div style={{ background: 'var(--bg1)', borderRadius: 8, border: '1px solid var(--border)', overflow: 'auto', marginBottom: 24 }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11, ...mono }}>
            <thead>
              <tr style={{ borderBottom: '2px solid var(--border)' }}>
                {['Proposal', 'Symbol', 'Event', 'Status', 'Price', 'Entry', 'Drift %', 'Provider', 'News', 'Time'].map(h => (
                  <th key={h} style={{ padding: '8px 10px', textAlign: 'left', fontSize: 9, color: 'var(--text3)', fontWeight: 600, textTransform: 'uppercase' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {events.length === 0 && (
                <tr><td colSpan={10} style={{ padding: 20, textAlign: 'center', color: 'var(--text3)', fontStyle: 'italic' }}>No lifecycle events yet. Events appear after proposal monitor runs.</td></tr>
              )}
              {events.slice(0, 50).map((e: any) => {
                const evColor = e.event_type?.includes('EXTENDED') ? 'blue' : e.event_type?.includes('MISSED') ? 'red' : e.event_type?.includes('EXPIRED') ? 'red' : 'amber'
                return (
                  <tr key={e.id} style={{ borderBottom: '1px solid var(--border)' }}>
                    <td style={{ padding: '6px 10px' }}>#{e.proposal_id}</td>
                    <td style={{ padding: '6px 10px', fontWeight: 700 }}>{e.symbol}</td>
                    <td style={{ padding: '6px 10px' }}><span style={pill(evColor)}>{e.event_type}</span></td>
                    <td style={{ padding: '6px 10px', color: 'var(--text2)' }}>{e.lifecycle_status || '--'}</td>
                    <td style={{ padding: '6px 10px' }}>{e.current_price ? `$${Number(e.current_price).toFixed(2)}` : '--'}</td>
                    <td style={{ padding: '6px 10px' }}>{e.entry_price ? `$${Number(e.entry_price).toFixed(2)}` : '--'}</td>
                    <td style={{ padding: '6px 10px', color: e.price_drift_pct && Math.abs(Number(e.price_drift_pct)) > 5 ? 'var(--red)' : 'var(--text2)' }}>
                      {e.price_drift_pct != null ? `${Number(e.price_drift_pct) > 0 ? '+' : ''}${Number(e.price_drift_pct).toFixed(1)}%` : '--'}
                    </td>
                    <td style={{ padding: '6px 10px', color: 'var(--text3)' }}>{e.quote_provider || '--'}</td>
                    <td style={{ padding: '6px 10px' }}>{e.news_count ?? '--'}</td>
                    <td style={{ padding: '6px 10px', color: 'var(--text3)', fontSize: 9 }}>{e.created_at ? new Date(e.created_at).toLocaleString() : '--'}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>

        {/* TCA Summary */}
        {tca.length > 0 && (
          <>
            <h3 style={{ fontSize: 13, color: 'var(--text1)', marginBottom: 8 }}>Recent Fill Quality</h3>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              {tca.slice(0, 10).map((t: any) => (
                <div key={t.id} style={{ padding: '8px 12px', background: 'var(--bg1)', borderRadius: 6, border: '1px solid var(--border)', minWidth: 120 }}>
                  <div style={{ fontSize: 12, fontWeight: 700, ...mono }}>{t.symbol}</div>
                  <div style={{ fontSize: 10, color: 'var(--text3)' }}>{t.strategy_id}</div>
                  <span style={pill(resultColor(t.fill_quality || 'UNKNOWN'))}>{t.fill_quality || 'UNKNOWN'}</span>
                  {t.slippage_pct != null && <div style={{ fontSize: 9, color: 'var(--text2)', marginTop: 4, ...mono }}>Slip: {Number(t.slippage_pct).toFixed(3)}%</div>}
                </div>
              ))}
            </div>
          </>
        )}
      </div>
    </>
  )
}
