import { useState } from 'react'
import { useApi } from '../hooks/useApi'

const card: React.CSSProperties = { background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)', borderRadius: 12, padding: '16px 20px' }
const secTitle: React.CSSProperties = { fontSize: 11, fontWeight: 600, letterSpacing: '.08em', textTransform: 'uppercase' as const, color: 'rgba(255,255,255,0.4)', marginBottom: 12 }
const pill = (color: string): React.CSSProperties => ({ fontSize: 9, padding: '2px 6px', borderRadius: 4, fontWeight: 600, background: `color-mix(in srgb, ${color} 15%, transparent)`, color })
const metricBox: React.CSSProperties = { textAlign: 'center' as const, padding: '8px 4px' }
const metricVal: React.CSSProperties = { fontSize: 22, fontWeight: 700, lineHeight: 1.2 }
const metricLbl: React.CSSProperties = { fontSize: 9, color: 'rgba(255,255,255,0.4)', marginTop: 2 }

const STAGES = ['Universe', 'Candidates', 'Scoring', 'Signals', 'Proposals', 'Risk Gate', 'Approval', 'Execution', 'Stops', 'Trailing', 'TCA', 'Exit', 'Learning']

const tsColor = (s: string) => s === 'overdue' ? '#ef4444' : s === 'review_due' || s === 'approaching' ? '#f59e0b' : s === 'ok' ? '#4ade80' : '#6b7280'
const gateColor = (s: string) => s === 'pass' ? '#4ade80' : s === 'fail' ? '#ef4444' : s === 'bypassed' ? '#f59e0b' : '#6b7280'

export default function ATMControlRoom() {
  const { data: lc, refetch } = useApi<any>('/api/v2/atm/lifecycle', 15000)
  const [selectedTrade, setSelectedTrade] = useState<any>(null)
  const [tab, setTab] = useState<'positions' | 'proposals'>('positions')

  const s = lc?.summary || {}
  const positions = lc?.positions || []
  const proposals = lc?.recent_proposals || []

  const m = (val: any, label: string, color?: string) => (
    <div style={metricBox}>
      <div style={{ ...metricVal, color: color || 'rgba(255,255,255,0.85)' }}>{val ?? 'N/A'}</div>
      <div style={metricLbl}>{label}</div>
    </div>
  )

  return (
    <div style={{ padding: '20px 24px', maxWidth: 1500, margin: '0 auto' }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16, paddingBottom: 12, borderBottom: '1px solid rgba(255,255,255,0.08)' }}>
        <div>
          <h1 style={{ fontSize: 20, fontWeight: 600, margin: 0, color: 'rgba(255,255,255,0.9)' }}>ATM Control Room</h1>
          <p style={{ fontSize: 12, color: 'rgba(255,255,255,0.4)', margin: '4px 0 0' }}>End-to-end lifecycle visibility. Read-only. No order actions.</p>
        </div>
        <button onClick={() => refetch()} style={{ padding: '7px 16px', borderRadius: 8, fontSize: 12, fontWeight: 500, cursor: 'pointer', background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.1)', color: 'rgba(255,255,255,0.5)' }}>Refresh</button>
      </div>

      {/* 1. Trust Strip */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(10, 1fr)', gap: 6, marginBottom: 16 }}>
        {m(s.signals_today, 'Signals Today')}
        {m(s.proposals_today, 'Proposals')}
        {m(s.open_positions, 'Open Positions')}
        {m(s.time_stop_overdue, 'Time-Stop Overdue', (s.time_stop_overdue || 0) > 0 ? '#ef4444' : '#4ade80')}
        {m(s.stop_missing_count, 'Missing Stops', (s.stop_missing_count || 0) > 0 ? '#ef4444' : '#4ade80')}
        {m(s.stale_proposals, 'Stale Proposals', (s.stale_proposals || 0) > 0 ? '#f59e0b' : '#4ade80')}
        {m(s.safe_flock_skips_24h, 'Flock Skips 24h', (s.safe_flock_skips_24h || 0) > 0 ? '#f59e0b' : '#4ade80')}
        {m(s.traceability_gap_count, 'Trace Gaps', (s.traceability_gap_count || 0) > 0 ? '#f59e0b' : '#4ade80')}
        {m(s.classifier_gate_disabled ? 'OFF' : 'ON', 'Classifier Gate', s.classifier_gate_disabled ? '#f59e0b' : '#4ade80')}
        {m(s.lifecycle_events_24h, 'Events 24h')}
      </div>

      {/* 2. Lifecycle Pipeline Stages */}
      <div style={{ ...card, marginBottom: 16 }}>
        <div style={secTitle}>Lifecycle Pipeline</div>
        <div style={{ display: 'flex', gap: 2, overflowX: 'auto' }}>
          {STAGES.map((stage, i) => {
            const count = s.stage_counts_7d?.[stage.toLowerCase().replace(/ /g, '_')] || 0
            return (
              <div key={stage} style={{ flex: 1, textAlign: 'center', padding: '8px 4px', background: count > 0 ? 'rgba(74,222,128,0.06)' : 'rgba(255,255,255,0.02)', borderRadius: 6, position: 'relative' }}>
                <div style={{ fontSize: 16, fontWeight: 700, color: count > 0 ? '#4ade80' : 'rgba(255,255,255,0.2)' }}>{count}</div>
                <div style={{ fontSize: 8, color: 'rgba(255,255,255,0.4)', marginTop: 2 }}>{stage}</div>
                {i < STAGES.length - 1 && <div style={{ position: 'absolute', right: -4, top: '50%', transform: 'translateY(-50%)', color: 'rgba(255,255,255,0.15)', fontSize: 10 }}>→</div>}
              </div>
            )
          })}
        </div>
      </div>

      {/* Tab selector */}
      <div style={{ display: 'flex', gap: 6, marginBottom: 12 }}>
        {(['positions', 'proposals'] as const).map(t => (
          <button key={t} onClick={() => setTab(t)} style={{ padding: '6px 14px', fontSize: 11, fontWeight: 600, border: 'none', borderRadius: 6, cursor: 'pointer', background: tab === t ? 'rgba(99,102,241,0.15)' : 'transparent', color: tab === t ? '#a5b4fc' : 'rgba(255,255,255,0.4)' }}>
            {t === 'positions' ? `Open Positions (${positions.length})` : `Recent Proposals (${proposals.length})`}
          </button>
        ))}
      </div>

      {/* 3. Open Position Management */}
      {tab === 'positions' && (
        <div style={{ ...card, marginBottom: 16, padding: 0, overflow: 'hidden' }}>
          <div style={{ maxHeight: 500, overflowY: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 10, fontFamily: 'monospace' }}>
              <thead>
                <tr style={{ borderBottom: '2px solid rgba(255,255,255,0.08)', background: 'rgba(255,255,255,0.02)' }}>
                  {['Symbol', 'Strategy', 'Family', 'Days', 'Entry', 'DB Stop', 'Trailing', 'Time-Stop', 'Gates', 'Account'].map(h => (
                    <th key={h} style={{ padding: '8px 6px', textAlign: 'left', fontSize: 8, color: 'rgba(255,255,255,0.35)', fontWeight: 600, textTransform: 'uppercase' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {positions.length === 0 && <tr><td colSpan={10} style={{ padding: 20, textAlign: 'center', color: 'rgba(255,255,255,0.3)', fontStyle: 'italic' }}>No open positions</td></tr>}
                {positions.map((p: any) => (
                  <tr key={p.paper_trade_id} onClick={() => setSelectedTrade(selectedTrade?.paper_trade_id === p.paper_trade_id ? null : p)} style={{ borderBottom: '1px solid rgba(255,255,255,0.04)', cursor: 'pointer', background: selectedTrade?.paper_trade_id === p.paper_trade_id ? 'rgba(99,102,241,0.08)' : p.time_stop?.status === 'overdue' ? 'rgba(239,68,68,0.04)' : undefined }}>
                    <td style={{ padding: '6px', fontWeight: 700, fontSize: 11 }}>{p.symbol}</td>
                    <td style={{ padding: '6px', fontSize: 9 }}>{p.strategy_id}</td>
                    <td style={{ padding: '6px' }}><span style={pill(p.strategy_family === 'momentum' ? '#f59e0b' : p.strategy_family === 'swing' ? '#3b82f6' : p.strategy_family === 'income' ? '#4ade80' : '#6b7280')}>{p.strategy_family || 'unknown'}</span></td>
                    <td style={{ padding: '6px', fontWeight: 600 }}>{p.days_held}d</td>
                    <td style={{ padding: '6px' }}>${p.entry_price?.toFixed(2) || '—'}</td>
                    <td style={{ padding: '6px', color: p.db_stop_loss ? '#4ade80' : '#ef4444' }}>{p.db_stop_loss ? `$${p.db_stop_loss.toFixed(2)}` : 'MISSING'}</td>
                    <td style={{ padding: '6px', fontSize: 8 }}>{p.trailing_tier || '—'}</td>
                    <td style={{ padding: '6px' }}><span style={pill(tsColor(p.time_stop?.status))}>{p.time_stop?.status || 'unknown'}{p.time_stop?.overdue_by > 0 ? ` +${p.time_stop.overdue_by}d` : ''}</span></td>
                    <td style={{ padding: '6px' }}>
                      {Object.entries(p.gate_audit || {}).map(([g, v]: any) => (
                        <span key={g} style={{ ...pill(gateColor(v.status)), marginRight: 2, fontSize: 7 }}>{g.replace(/_/g, ' ').slice(0, 8)}</span>
                      ))}
                    </td>
                    <td style={{ padding: '6px', fontSize: 8, color: 'rgba(255,255,255,0.4)' }}>{p.account}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* 4. Proposals Queue */}
      {tab === 'proposals' && (
        <div style={{ ...card, marginBottom: 16, padding: 0, overflow: 'hidden' }}>
          <div style={{ maxHeight: 500, overflowY: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 10, fontFamily: 'monospace' }}>
              <thead>
                <tr style={{ borderBottom: '2px solid rgba(255,255,255,0.08)', background: 'rgba(255,255,255,0.02)' }}>
                  {['ID', 'Symbol', 'Strategy', 'Score', 'Decision', 'Entry', 'Stop', 'Target', 'Created'].map(h => (
                    <th key={h} style={{ padding: '8px 6px', textAlign: 'left', fontSize: 8, color: 'rgba(255,255,255,0.35)', fontWeight: 600, textTransform: 'uppercase' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {proposals.length === 0 && <tr><td colSpan={9} style={{ padding: 20, textAlign: 'center', color: 'rgba(255,255,255,0.3)', fontStyle: 'italic' }}>No recent proposals</td></tr>}
                {proposals.map((p: any) => (
                  <tr key={p.id} style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
                    <td style={{ padding: '6px', color: 'rgba(255,255,255,0.4)' }}>#{p.id}</td>
                    <td style={{ padding: '6px', fontWeight: 700 }}>{p.symbol}</td>
                    <td style={{ padding: '6px', fontSize: 9 }}>{p.strategy_id}</td>
                    <td style={{ padding: '6px', fontWeight: 600 }}>{p.signal_score ?? '—'}</td>
                    <td style={{ padding: '6px' }}><span style={pill(p.signal_decision === 'approved' ? '#4ade80' : p.signal_decision === 'rejected' ? '#ef4444' : '#6b7280')}>{p.signal_decision || 'pending'}</span></td>
                    <td style={{ padding: '6px' }}>${Number(p.proposed_entry || 0).toFixed(2)}</td>
                    <td style={{ padding: '6px' }}>${Number(p.proposed_stop || 0).toFixed(2)}</td>
                    <td style={{ padding: '6px' }}>${Number(p.proposed_target1 || 0).toFixed(2)}</td>
                    <td style={{ padding: '6px', fontSize: 8, color: 'rgba(255,255,255,0.4)' }}>{p.created_at ? new Date(p.created_at).toLocaleString() : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* 5. Lifecycle Inspector (when a position is selected) */}
      {selectedTrade && (
        <div style={{ ...card, marginBottom: 16, borderColor: 'rgba(99,102,241,0.3)' }}>
          <div style={secTitle}>Lifecycle Inspector — {selectedTrade.symbol} ({selectedTrade.strategy_id})</div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, fontSize: 11 }}>
            <div>
              <div style={{ color: 'rgba(255,255,255,0.4)', fontSize: 9, marginBottom: 4 }}>Position</div>
              <div>Account: {selectedTrade.account}</div>
              <div>Shares: {selectedTrade.shares}</div>
              <div>Entry: ${selectedTrade.entry_price?.toFixed(2) || '—'}</div>
              <div>Days held: {selectedTrade.days_held}</div>
            </div>
            <div>
              <div style={{ color: 'rgba(255,255,255,0.4)', fontSize: 9, marginBottom: 4 }}>Stop Management</div>
              <div>DB Stop: {selectedTrade.db_stop_loss ? `$${selectedTrade.db_stop_loss.toFixed(2)}` : <span style={{ color: '#ef4444' }}>MISSING</span>}</div>
              <div>Trailing tier: {selectedTrade.trailing_tier || 'None'}</div>
              <div>Broker proof: <span style={{ color: '#6b7280' }}>Unavailable</span></div>
            </div>
            <div>
              <div style={{ color: 'rgba(255,255,255,0.4)', fontSize: 9, marginBottom: 4 }}>Time Stop</div>
              <div>Type: {selectedTrade.time_stop?.type || 'unknown'}</div>
              <div>Status: <span style={{ color: tsColor(selectedTrade.time_stop?.status), fontWeight: 600 }}>{selectedTrade.time_stop?.status}</span></div>
              <div>Max hold: {selectedTrade.time_stop?.max_hold_days || selectedTrade.time_stop?.review_at_days || 'intraday'}</div>
              {selectedTrade.time_stop?.overdue_by > 0 && <div style={{ color: '#ef4444', fontWeight: 600 }}>Overdue by {selectedTrade.time_stop.overdue_by} days</div>}
            </div>
            <div>
              <div style={{ color: 'rgba(255,255,255,0.4)', fontSize: 9, marginBottom: 4 }}>Gate Audit</div>
              {Object.entries(selectedTrade.gate_audit || {}).map(([g, v]: any) => (
                <div key={g} style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                  <span style={{ width: 8, height: 8, borderRadius: 4, background: gateColor(v.status), display: 'inline-block' }} />
                  <span>{g.replace(/_/g, ' ')}: {v.status}</span>
                  {v.detail && <span style={{ color: 'rgba(255,255,255,0.3)', fontSize: 9 }}>({v.detail})</span>}
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* 6. Control Gaps Summary */}
      <div style={{ ...card }}>
        <div style={secTitle}>Control Gaps & Alerts</div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 16, fontSize: 11 }}>
          <div>
            <div style={{ fontWeight: 600, marginBottom: 6, color: (s.time_stop_overdue || 0) > 0 ? '#ef4444' : '#4ade80' }}>Time-Stop Overdue: {s.time_stop_overdue || 0}</div>
            {positions.filter((p: any) => p.time_stop?.status === 'overdue').map((p: any) => (
              <div key={p.paper_trade_id} style={{ fontSize: 10, color: 'rgba(255,255,255,0.5)', marginBottom: 2 }}>
                {p.symbol} · {p.strategy_id} · {p.days_held}d ({p.time_stop?.type})
              </div>
            ))}
          </div>
          <div>
            <div style={{ fontWeight: 600, marginBottom: 6, color: (s.stop_missing_count || 0) > 0 ? '#ef4444' : '#4ade80' }}>Missing Stops: {s.stop_missing_count || 0}</div>
            {positions.filter((p: any) => !p.db_stop_loss).map((p: any) => (
              <div key={p.paper_trade_id} style={{ fontSize: 10, color: 'rgba(255,255,255,0.5)', marginBottom: 2 }}>
                {p.symbol} · {p.strategy_id}
              </div>
            ))}
          </div>
          <div>
            <div style={{ fontWeight: 600, marginBottom: 6 }}>System</div>
            <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.5)' }}>Flock skips 24h: {s.safe_flock_skips_24h ?? 'N/A'}</div>
            <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.5)' }}>Traceability gaps: {s.traceability_gap_count ?? 'N/A'}</div>
            <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.5)' }}>Lifecycle events 24h: {s.lifecycle_events_24h ?? 'N/A'}</div>
            <div style={{ fontSize: 10, color: s.classifier_gate_disabled ? '#f59e0b' : '#4ade80' }}>Classifier gate: {s.classifier_gate_disabled ? 'DISABLED (burn-in)' : 'Active'}</div>
          </div>
        </div>
      </div>
    </div>
  )
}
