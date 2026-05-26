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

const DECISION_OPTIONS = [
  { value: 'keep_open', label: 'Keep Open', color: '#4ade80' },
  { value: 'review_for_manual_close', label: 'Review for Manual Close', color: '#ef4444' },
  { value: 'review_stop_or_trailing_adjustment', label: 'Review Stop/Trailing', color: '#f59e0b' },
  { value: 'missing_data_verify_first', label: 'Missing Data — Verify', color: '#6b7280' },
  { value: 'strategy_mismatch_investigate', label: 'Strategy Mismatch', color: '#8b5cf6' },
]

const MC_DECISIONS = [
  { value: 'keep_open_after_review', label: 'Keep Open After Review', color: '#4ade80' },
  { value: 'close_manually_outside_system', label: 'Close Manually Outside System', color: '#ef4444' },
  { value: 'prepare_paper_close_preview', label: 'Prepare Close Preview', color: '#f59e0b' },
  { value: 'needs_more_data', label: 'Needs More Data', color: '#6b7280' },
  { value: 'mark_resolved_no_action', label: 'Mark Resolved', color: '#8b5cf6' },
]

export default function ATMControlRoom() {
  const { data: lc, refetch } = useApi<any>('/api/v2/atm/lifecycle', 15000)
  const { data: overdueData, refetch: refetchOD } = useApi<any>('/api/v2/atm/overdue-decisions', 15000)
  const [selectedTrade, setSelectedTrade] = useState<any>(null)
  const [tab, setTab] = useState<'positions' | 'proposals'>('positions')
  const [decisionForm, setDecisionForm] = useState<{ tradeId: number | null, symbol: string, decision: string, reason: string, note: string }>({ tradeId: null, symbol: '', decision: '', reason: '', note: '' })
  const [submitStatus, setSubmitStatus] = useState<string | null>(null)

  const submitDecision = async () => {
    if (!decisionForm.decision || !decisionForm.symbol) return
    setSubmitStatus('submitting...')
    try {
      const resp = await fetch('/api/v2/atm/overdue-decisions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          paper_trade_id: decisionForm.tradeId,
          symbol: decisionForm.symbol,
          decision: decisionForm.decision,
          decision_reason: decisionForm.reason,
          operator_note: decisionForm.note,
        }),
      })
      const data = await resp.json()
      if (data.ok) {
        setSubmitStatus(data.data?.safety_message || 'Decision recorded.')
        setDecisionForm({ tradeId: null, symbol: '', decision: '', reason: '', note: '' })
        refetchOD()
        setTimeout(() => setSubmitStatus(null), 5000)
      } else {
        setSubmitStatus(`Error: ${data.error}`)
      }
    } catch (e: any) {
      setSubmitStatus(`Error: ${e.message}`)
    }
  }

  const { data: mcData, refetch: refetchMC } = useApi<any>('/api/v2/atm/manual-close-review', 15000)
  const [mcForm, setMcForm] = useState<{ tradeId: number | null, symbol: string, strategyId: string, decision: string, reason: string, note: string }>({ tradeId: null, symbol: '', strategyId: '', decision: '', reason: '', note: '' })
  const [mcStatus, setMcStatus] = useState<string | null>(null)

  const submitMcDecision = async () => {
    if (!mcForm.decision || !mcForm.symbol) return
    setMcStatus('submitting...')
    try {
      const resp = await fetch('/api/v2/atm/manual-close-review', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ paper_trade_id: mcForm.tradeId, symbol: mcForm.symbol, strategy_id: mcForm.strategyId, decision: mcForm.decision, decision_reason: mcForm.reason, operator_note: mcForm.note }),
      })
      const data = await resp.json()
      if (data.ok) {
        setMcStatus(data.data?.safety_message || 'Decision recorded.')
        setMcForm({ tradeId: null, symbol: '', strategyId: '', decision: '', reason: '', note: '' })
        refetchMC()
        setTimeout(() => setMcStatus(null), 5000)
      } else { setMcStatus(`Error: ${data.error}`) }
    } catch (e: any) { setMcStatus(`Error: ${e.message}`) }
  }

  const mcItems = mcData?.items || []
  const mcSummary = mcData?.summary || {}
  const [mcTabState, setMcTabState] = useState<'mc_pending' | 'mc_reviewed' | 'mc_all'>('mc_pending')

  const odNeedsDecision = overdueData?.needs_decision || []
  const odReviewed = overdueData?.reviewed || []
  const odAll = overdueData?.all_overdue || []
  const odSummary = overdueData?.summary || {}
  const [odTab, setOdTab] = useState<'needs' | 'reviewed' | 'all'>('needs')

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

      {/* OVERDUE INTRADAY REVIEW QUEUE */}
      {odAll.length > 0 && (
        <div style={{ ...card, marginBottom: 16, borderColor: (odSummary.needs_decision_count || 0) > 0 ? 'rgba(239,68,68,0.3)' : 'rgba(74,222,128,0.2)', background: (odSummary.needs_decision_count || 0) > 0 ? 'rgba(239,68,68,0.03)' : 'rgba(74,222,128,0.02)' }}>
          <div style={{ ...secTitle, color: (odSummary.needs_decision_count || 0) > 0 ? '#ef4444' : '#4ade80' }}>
            Overdue Intraday Review Queue — {odSummary.total_overdue || odAll.length} positions
            {(odSummary.needs_decision_count || 0) > 0
              ? ` (${odSummary.needs_decision_count} need decisions)`
              : ` (all ${odSummary.reviewed_count || 0} reviewed)`}
          </div>
          <div style={{ display: 'flex', gap: 6, marginBottom: 10 }}>
            {([
              ['needs', `Needs Decision (${odNeedsDecision.length})`],
              ['reviewed', `Reviewed (${odReviewed.length})`],
              ['all', `All (${odAll.length})`],
            ] as const).map(([key, label]) => (
              <button key={key} onClick={() => setOdTab(key as any)}
                style={{ padding: '4px 10px', fontSize: 10, fontWeight: 600, border: 'none', borderRadius: 4, cursor: 'pointer',
                  background: odTab === key ? 'rgba(99,102,241,0.15)' : 'transparent',
                  color: odTab === key ? '#a5b4fc' : 'rgba(255,255,255,0.4)' }}>
                {label}
              </button>
            ))}
          </div>
          {(() => {
            const odVisible = odTab === 'needs' ? odNeedsDecision : odTab === 'reviewed' ? odReviewed : odAll
            return (
          <div style={{ maxHeight: 350, overflowY: 'auto' }}>
            {odVisible.length === 0 && odTab === 'needs' && (
              <div style={{ padding: '16px 12px', textAlign: 'center', color: '#4ade80', fontSize: 12, fontWeight: 600 }}>
                All overdue positions have been reviewed.
              </div>
            )}
            {odVisible.length > 0 && (
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 10, fontFamily: 'monospace' }}>
              <thead>
                <tr style={{ borderBottom: '2px solid rgba(255,255,255,0.08)' }}>
                  {['Symbol', 'Strategy', 'Days', 'Risk', 'Entry', 'Stop', 'Overdue By', 'Decision', 'Action'].map(h => (
                    <th key={h} style={{ padding: '6px', textAlign: 'left', fontSize: 8, color: 'rgba(255,255,255,0.35)', fontWeight: 600, textTransform: 'uppercase' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {odVisible.map((p: any) => {
                  const dec = p.existing_decision
                  const decOpt = dec ? DECISION_OPTIONS.find(d => d.value === dec.decision) : null
                  return (
                    <tr key={p.paper_trade_id} style={{ borderBottom: '1px solid rgba(255,255,255,0.04)', background: p.stop_missing && !dec ? 'rgba(239,68,68,0.06)' : undefined }}>
                      <td style={{ padding: '6px', fontWeight: 700, fontSize: 11 }}>{p.symbol}</td>
                      <td style={{ padding: '6px', fontSize: 9 }}>{p.strategy_id}</td>
                      <td style={{ padding: '6px', fontWeight: 600 }}>{p.days_held}d</td>
                      <td style={{ padding: '6px' }}><span style={pill(p.risk === 'HIGH' ? '#ef4444' : '#f59e0b')}>{p.risk}</span></td>
                      <td style={{ padding: '6px' }}>${p.entry_price?.toFixed(2) || '—'}</td>
                      <td style={{ padding: '6px', color: p.stop_missing ? '#ef4444' : '#4ade80' }}>{p.db_stop_loss ? `$${p.db_stop_loss.toFixed(2)}` : 'MISSING'}</td>
                      <td style={{ padding: '6px', color: '#ef4444' }}>+{p.overdue_by}d</td>
                      <td style={{ padding: '6px' }}>
                        {dec ? <span style={pill(decOpt?.color || '#4ade80')}>{decOpt?.label || dec.decision}</span> : <span style={{ color: 'rgba(255,255,255,0.25)', fontSize: 9 }}>none</span>}
                      </td>
                      <td style={{ padding: '6px' }}>
                        <button onClick={() => setDecisionForm({ tradeId: p.paper_trade_id, symbol: p.symbol, decision: '', reason: '', note: '' })}
                          style={{ fontSize: 9, padding: '3px 8px', borderRadius: 4, border: '1px solid rgba(255,255,255,0.15)', background: 'rgba(255,255,255,0.05)', color: 'rgba(255,255,255,0.6)', cursor: 'pointer' }}>
                          {dec ? 'Update' : 'Decide'}
                        </button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
            )}
          </div>
            )
          })()}

          {/* Decision form */}
          {decisionForm.tradeId && (
            <div style={{ marginTop: 12, padding: '12px 16px', background: 'rgba(255,255,255,0.03)', borderRadius: 8, border: '1px solid rgba(255,255,255,0.08)' }}>
              <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 8, color: 'rgba(255,255,255,0.7)' }}>
                Record Decision — {decisionForm.symbol} (Trade #{decisionForm.tradeId})
              </div>
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 8 }}>
                {DECISION_OPTIONS.map(opt => (
                  <button key={opt.value} onClick={() => setDecisionForm(f => ({ ...f, decision: opt.value }))}
                    style={{ padding: '5px 10px', fontSize: 10, fontWeight: 600, borderRadius: 6, cursor: 'pointer',
                      background: decisionForm.decision === opt.value ? `color-mix(in srgb, ${opt.color} 20%, transparent)` : 'rgba(255,255,255,0.04)',
                      border: decisionForm.decision === opt.value ? `1px solid ${opt.color}` : '1px solid rgba(255,255,255,0.1)',
                      color: decisionForm.decision === opt.value ? opt.color : 'rgba(255,255,255,0.5)' }}>
                    {opt.label}
                  </button>
                ))}
              </div>
              <input placeholder="Reason (required)" value={decisionForm.reason} onChange={e => setDecisionForm(f => ({ ...f, reason: e.target.value }))}
                style={{ width: '100%', padding: '6px 10px', fontSize: 11, background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 6, color: 'rgba(255,255,255,0.7)', marginBottom: 6, boxSizing: 'border-box' }} />
              <input placeholder="Operator note (optional)" value={decisionForm.note} onChange={e => setDecisionForm(f => ({ ...f, note: e.target.value }))}
                style={{ width: '100%', padding: '6px 10px', fontSize: 11, background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 6, color: 'rgba(255,255,255,0.7)', marginBottom: 8, boxSizing: 'border-box' }} />
              <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <button onClick={submitDecision} disabled={!decisionForm.decision || !decisionForm.reason}
                  style={{ padding: '6px 16px', fontSize: 11, fontWeight: 600, borderRadius: 6, cursor: 'pointer',
                    background: decisionForm.decision && decisionForm.reason ? 'rgba(99,102,241,0.2)' : 'rgba(255,255,255,0.03)',
                    border: '1px solid rgba(99,102,241,0.4)', color: decisionForm.decision && decisionForm.reason ? '#a5b4fc' : 'rgba(255,255,255,0.2)' }}>
                  Record Review Decision
                </button>
                <button onClick={() => setDecisionForm({ tradeId: null, symbol: '', decision: '', reason: '', note: '' })}
                  style={{ padding: '6px 12px', fontSize: 11, borderRadius: 6, cursor: 'pointer', background: 'transparent', border: '1px solid rgba(255,255,255,0.1)', color: 'rgba(255,255,255,0.4)' }}>
                  Cancel
                </button>
                {submitStatus && <span style={{ fontSize: 10, color: submitStatus.startsWith('Error') ? '#ef4444' : '#4ade80' }}>{submitStatus}</span>}
              </div>
            </div>
          )}
        </div>
      )}

      {/* MANUAL CLOSE REVIEW QUEUE */}
      {mcItems.length > 0 && (() => {
        const mcPending = mcData?.pending || mcItems.filter((i: any) => i.review_status === 'pending_review')
        const mcResolved = mcData?.reviewed || mcItems.filter((i: any) => i.review_status === 'reviewed')
        void 0 // tabs managed by mcTabState
        return (
        <div style={{ ...card, marginBottom: 16, borderColor: mcPending.length > 0 ? 'rgba(245,158,11,0.25)' : 'rgba(74,222,128,0.2)' }}>
          <div style={{ ...secTitle, color: '#f59e0b' }}>
            Manual Close Review Queue — No Orders Placed
          </div>
          <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.4)', marginBottom: 10, lineHeight: 1.5 }}>
            These are open paper positions you already marked for possible manual-close review.
            Review current risk, stop status, and thesis age, then record the next operator decision.
            This section does not place orders.
          </div>
          <details style={{ fontSize: 10, color: 'rgba(255,255,255,0.3)', marginBottom: 10 }}>
            <summary style={{ cursor: 'pointer', color: 'rgba(255,255,255,0.4)' }}>Workflow: How did these get here?</summary>
            <ol style={{ margin: '6px 0 0 16px', lineHeight: 1.8 }}>
              <li>Position was flagged as overdue (intraday held past session close)</li>
              <li>Operator marked it "review for manual close" in the overdue decision queue</li>
              <li>Now: review current risk, P&L, stop status, and thesis</li>
              <li>Record the next decision below</li>
              <li>Item moves to Reviewed tab</li>
              <li>No order is placed at any step</li>
            </ol>
          </details>

          <div style={{ display: 'flex', gap: 6, marginBottom: 10 }}>
            {([
              ['mc_pending', `Pending Review (${mcPending.length})`],
              ['mc_reviewed', `Reviewed (${mcResolved.length})`],
              ['mc_all', `All (${mcItems.length})`],
            ] as const).map(([key, label]) => (
              <button key={key} onClick={() => setMcTabState(key as any)}
                style={{ padding: '4px 10px', fontSize: 10, fontWeight: 600, border: 'none', borderRadius: 4, cursor: 'pointer',
                  background: mcTabState === key ? 'rgba(99,102,241,0.15)' : 'transparent',
                  color: mcTabState === key ? '#a5b4fc' : 'rgba(255,255,255,0.4)' }}>
                {label}
              </button>
            ))}
          </div>

          {(() => {
            const mcVisible = mcTabState === 'mc_reviewed' ? mcResolved : mcTabState === 'mc_all' ? mcItems : mcPending
            return (
          <div style={{ maxHeight: 300, overflowY: 'auto' }}>
            {mcVisible.length === 0 && (
              <div style={{ padding: '16px 12px', textAlign: 'center', color: '#4ade80', fontSize: 12, fontWeight: 600 }}>
                All manual-close review positions have been reviewed.
              </div>
            )}
            {mcVisible.length > 0 && (
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 10, fontFamily: 'monospace' }}>
              <thead>
                <tr style={{ borderBottom: '2px solid rgba(255,255,255,0.08)' }}>
                  {['Symbol', '#', 'Why Here', 'Days', 'Stop', 'Risk Issue', 'Recommended', 'Status', ''].map(h => (
                    <th key={h} style={{ padding: '6px', textAlign: 'left', fontSize: 8, color: 'rgba(255,255,255,0.35)', fontWeight: 600, textTransform: 'uppercase' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {mcVisible.map((p: any) => {
                  const rev = p.review_decision
                  const revOpt = rev ? MC_DECISIONS.find(d => d.value === rev.decision) : null
                  return (
                    <tr key={p.paper_trade_id} style={{ borderBottom: '1px solid rgba(255,255,255,0.04)', background: p.stop_missing ? 'rgba(239,68,68,0.04)' : undefined }}>
                      <td style={{ padding: '6px', fontWeight: 700, fontSize: 11 }}>{p.symbol}</td>
                      <td style={{ padding: '6px', fontSize: 8, color: 'rgba(255,255,255,0.3)' }}>#{p.paper_trade_id}</td>
                      <td style={{ padding: '6px', fontSize: 9, color: 'rgba(255,255,255,0.6)' }}>{p.why_here || `${p.time_stop_type} held ${p.days_held}d`}</td>
                      <td style={{ padding: '6px', fontWeight: 600 }}>{p.days_held}d</td>
                      <td style={{ padding: '6px', color: p.stop_missing ? '#ef4444' : '#4ade80' }}>{p.db_stop_loss ? `$${p.db_stop_loss.toFixed(2)}` : 'MISSING'}</td>
                      <td style={{ padding: '6px', fontSize: 9, color: p.stop_missing ? '#ef4444' : '#f59e0b' }}>{p.risk_issue || 'Review requested'}</td>
                      <td style={{ padding: '6px', fontSize: 9, color: 'rgba(255,255,255,0.5)' }}>{p.recommended_review_action || '—'}</td>
                      <td style={{ padding: '6px' }}>
                        {rev ? <span style={pill(revOpt?.color || '#4ade80')}>{revOpt?.label || rev.decision}</span> : <span style={pill('#f59e0b')}>pending</span>}
                      </td>
                      <td style={{ padding: '6px' }}>
                        <button onClick={() => setMcForm({ tradeId: p.paper_trade_id, symbol: p.symbol, strategyId: p.strategy_id, decision: '', reason: '', note: '' })}
                          style={{ fontSize: 9, padding: '3px 8px', borderRadius: 4, border: '1px solid rgba(255,255,255,0.15)', background: 'rgba(255,255,255,0.05)', color: 'rgba(255,255,255,0.6)', cursor: 'pointer' }}>
                          Review Position
                        </button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
            )}
          </div>
            )
          })()}

          {mcForm.tradeId && (
            <div style={{ marginTop: 12, padding: '12px 16px', background: 'rgba(255,255,255,0.03)', borderRadius: 8, border: '1px solid rgba(255,255,255,0.08)' }}>
              <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 4, color: 'rgba(255,255,255,0.7)' }}>
                Review Position — {mcForm.symbol} (Trade #{mcForm.tradeId})
              </div>
              <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.35)', marginBottom: 10 }}>
                Recording this review does not close, sell, cancel, replace, or submit any order.
              </div>
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 8 }}>
                {MC_DECISIONS.map(opt => (
                  <button key={opt.value} onClick={() => setMcForm(f => ({ ...f, decision: opt.value }))}
                    style={{ padding: '5px 10px', fontSize: 10, fontWeight: 600, borderRadius: 6, cursor: 'pointer',
                      background: mcForm.decision === opt.value ? `color-mix(in srgb, ${opt.color} 20%, transparent)` : 'rgba(255,255,255,0.04)',
                      border: mcForm.decision === opt.value ? `1px solid ${opt.color}` : '1px solid rgba(255,255,255,0.1)',
                      color: mcForm.decision === opt.value ? opt.color : 'rgba(255,255,255,0.5)' }}>
                    {opt.label}
                  </button>
                ))}
              </div>
              <input placeholder="Reason (required)" value={mcForm.reason} onChange={e => setMcForm(f => ({ ...f, reason: e.target.value }))}
                style={{ width: '100%', padding: '6px 10px', fontSize: 11, background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 6, color: 'rgba(255,255,255,0.7)', marginBottom: 6, boxSizing: 'border-box' }} />
              <input placeholder="Operator note (optional)" value={mcForm.note} onChange={e => setMcForm(f => ({ ...f, note: e.target.value }))}
                style={{ width: '100%', padding: '6px 10px', fontSize: 11, background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 6, color: 'rgba(255,255,255,0.7)', marginBottom: 8, boxSizing: 'border-box' }} />
              <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <button onClick={submitMcDecision} disabled={!mcForm.decision || !mcForm.reason}
                  style={{ padding: '6px 16px', fontSize: 11, fontWeight: 600, borderRadius: 6, cursor: 'pointer',
                    background: mcForm.decision && mcForm.reason ? 'rgba(99,102,241,0.2)' : 'rgba(255,255,255,0.03)',
                    border: '1px solid rgba(99,102,241,0.4)', color: mcForm.decision && mcForm.reason ? '#a5b4fc' : 'rgba(255,255,255,0.2)' }}>
                  Record Decision — No Order
                </button>
                <button onClick={() => setMcForm({ tradeId: null, symbol: '', strategyId: '', decision: '', reason: '', note: '' })}
                  style={{ padding: '6px 12px', fontSize: 11, borderRadius: 6, cursor: 'pointer', background: 'transparent', border: '1px solid rgba(255,255,255,0.1)', color: 'rgba(255,255,255,0.4)' }}>
                  Cancel
                </button>
                {mcStatus && <span style={{ fontSize: 10, color: mcStatus.startsWith('Error') ? '#ef4444' : '#4ade80' }}>{mcStatus}</span>}
              </div>
            </div>
          )}
        </div>
        )
      })()}

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
