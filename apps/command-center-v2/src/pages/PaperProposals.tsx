import React, { useState, useCallback } from 'react'
import PageHeader from '../components/PageHeader'
import { useApi } from '../hooks/useApi'

const mono: React.CSSProperties = { fontFamily: 'monospace' }
const lbl: React.CSSProperties = { fontSize: 8, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '0.3px' }
const pill = (color: string): React.CSSProperties => ({
  fontSize: 9, padding: '2px 6px', borderRadius: 4, fontWeight: 600,
  background: color === 'green' ? 'rgba(34,197,94,0.15)' : color === 'red' ? 'rgba(239,68,68,0.15)' : color === 'blue' ? 'rgba(59,130,246,0.15)' : 'rgba(251,191,36,0.15)',
  color: color === 'green' ? 'var(--green)' : color === 'red' ? 'var(--red)' : color === 'blue' ? '#60A5FA' : 'var(--amber)',
})
const warnChip: React.CSSProperties = { fontSize: 8, padding: '1px 5px', borderRadius: 3, background: 'rgba(251,191,36,0.12)', color: '#F59E0B', fontWeight: 600, whiteSpace: 'nowrap' }
const inputStyle: React.CSSProperties = {
  width: '100%', padding: '3px 5px', fontSize: 11, ...mono,
  background: 'var(--bg0)', border: '1px solid var(--border)', borderRadius: 4,
  color: 'var(--text0)', fontWeight: 600, textAlign: 'right',
}
const secLbl: React.CSSProperties = { fontSize: 10, color: 'var(--text3)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: 6, marginTop: 14 }
const kv = (label: string, value: any, color?: string) => (
  <div key={label}>
    <div style={lbl}>{label}</div>
    <div style={{ fontSize: 11, color: color || 'var(--text0)', fontWeight: 600, ...mono }}>{value ?? '--'}</div>
  </div>
)
const btnStyle = (bg: string, color: string = '#fff'): React.CSSProperties => ({
  padding: '5px 12px', fontSize: 10, fontWeight: 600, border: 'none', borderRadius: 5, cursor: 'pointer', color, background: bg,
})

// Decision state colors
const dsColors: Record<string, { bg: string; text: string; label: string }> = {
  APPROVE_READY_PAPER_TEST: { bg: 'rgba(34,197,94,0.15)', text: 'var(--green)', label: 'APPROVE READY' },
  CAUTIOUS_PAPER_TEST: { bg: 'rgba(251,191,36,0.12)', text: '#F59E0B', label: 'CAUTIOUS TEST' },
  RESEARCH_INCOMPLETE: { bg: 'rgba(148,163,184,0.15)', text: '#94A3B8', label: 'RESEARCH INCOMPLETE' },
  AI_REVIEW_MISSING: { bg: 'rgba(59,130,246,0.15)', text: '#60A5FA', label: 'AI REVIEW MISSING' },
  DATA_STALE: { bg: 'rgba(251,191,36,0.12)', text: '#F59E0B', label: 'DATA STALE' },
  BACKTEST_INSUFFICIENT: { bg: 'rgba(148,163,184,0.15)', text: '#94A3B8', label: 'BACKTEST INSUFFICIENT' },
  REJECT_RECOMMENDED: { bg: 'rgba(239,68,68,0.15)', text: 'var(--red)', label: 'REJECT RECOMMENDED' },
  BLOCKED_BY_RISK_GATE: { bg: 'rgba(239,68,68,0.15)', text: 'var(--red)', label: 'BLOCKED — RISK GATE' },
}

function AgentReviewPanel({ votes }: { votes: Record<string, any> }) {
  if (!votes || Object.keys(votes).length === 0) {
    return (
      <div style={{ padding: '8px 10px', background: 'var(--bg0)', borderRadius: 6, fontSize: 10, color: 'var(--text3)', fontStyle: 'italic' }}>
        No agent reviews completed yet
      </div>
    )
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      {Object.entries(votes).map(([name, v]: [string, any]) => {
        const vote = v?.vote || 'not reviewed'
        const conf = v?.confidence != null ? `${Math.round(Number(v.confidence))}%` : ''
        const summary = v?.summary || ''
        const model = v?.model || ''
        const voteColor = vote === 'APPROVE_TEST' ? 'green' : vote === 'REJECT' || vote === 'BLOCK' ? 'red' : vote === 'WAIT_FOR_DATA' ? 'blue' : 'amber'
        return (
          <div key={name} style={{ padding: '4px 8px', background: 'var(--bg0)', borderRadius: 4, display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <span style={{ fontSize: 10, fontWeight: 700, color: 'var(--text1)', minWidth: 40, ...mono }}>{name}</span>
            <span style={pill(voteColor)}>{vote} {conf}</span>
            <span style={{ fontSize: 9, color: 'var(--text2)', flex: 1 }}>{summary.slice(0, 100)}</span>
            {model && <span style={{ fontSize: 8, color: 'var(--text3)' }}>{model}</span>}
          </div>
        )
      })}
    </div>
  )
}

function TechPanel({ p }: { p: any }) {
  const tc = typeof p.technical_context === 'string' ? JSON.parse(p.technical_context || '{}') : (p.technical_context || {})
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 6 }}>
      {kv('ATR', tc.atr ? `$${Number(tc.atr).toFixed(2)} / ${tc.atr_pct || '?'}%` : null, !tc.atr ? 'var(--amber)' : undefined)}
      {kv('ATR State', tc.atr_state || (tc.atr ? undefined : 'ATR missing — indicator engine has not populated'))}
      {kv('RSI', tc.rsi != null ? `${Number(tc.rsi).toFixed(1)}` : null, tc.rsi_state?.includes('overbought') ? 'var(--red)' : tc.rsi_state === 'oversold' ? 'var(--green)' : !tc.rsi ? 'var(--amber)' : undefined)}
      {kv('RSI State', tc.rsi_state || 'RSI missing — indicator engine pending')}
      {kv('VWAP', tc.vwap_distance_pct != null ? `${Number(tc.vwap_distance_pct) > 0 ? '+' : ''}${Number(tc.vwap_distance_pct).toFixed(1)}%` : null)}
      {kv('VWAP State', tc.vwap_state || 'VWAP missing')}
      {kv('ADX', tc.adx != null ? `${Number(tc.adx).toFixed(1)}` : null)}
      {kv('Trend', tc.trend_strength || 'ADX missing')}
      {kv('RVOL', tc.rvol ? `${Number(tc.rvol).toFixed(1)}x` : null, tc.rvol >= 10 ? 'var(--green)' : tc.rvol >= 5 ? '#60A5FA' : undefined)}
      {kv('RVOL State', tc.rvol_state || 'RVOL missing')}
      {kv('Float Rotation', tc.float_rotation_state || 'unavailable')}
      {kv('Gap', tc.gap_pct != null ? `${Number(tc.gap_pct).toFixed(1)}% (${tc.gap_state || '?'})` : null)}
    </div>
  )
}

function BacktestPanel({ p }: { p: any }) {
  const bt = typeof p.backtest_summary === 'string' ? JSON.parse(p.backtest_summary || '{}') : (p.backtest_summary || {})
  if (!bt.quality && !bt.sample_size) {
    return <div style={{ fontSize: 10, color: 'var(--text3)', fontStyle: 'italic' }}>Backtest not run yet</div>
  }
  const qualColor = bt.quality === 'SUFFICIENT' ? 'green' : bt.quality === 'LIMITED' ? 'amber' : 'red'
  return (
    <div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 6 }}>
        {kv('Quality', bt.quality, qualColor === 'green' ? 'var(--green)' : qualColor === 'amber' ? 'var(--amber)' : 'var(--red)')}
        {kv('Samples', bt.sample_size)}
        {kv('Win Rate', bt.win_rate != null ? `${(Number(bt.win_rate) * 100).toFixed(1)}%` : null)}
        {kv('Profit Factor', bt.profit_factor != null ? `${Number(bt.profit_factor).toFixed(2)}` : null)}
        {kv('Expectancy', bt.expectancy != null ? `$${Number(bt.expectancy).toFixed(2)}` : null)}
        {kv('Avg R', bt.avg_r != null ? `${Number(bt.avg_r).toFixed(2)}R` : null)}
        {kv('Repeat Pattern', bt.repeat_pattern ? 'Yes' : 'No')}
      </div>
      {bt.similar_summary && <div style={{ fontSize: 9, color: 'var(--text2)', marginTop: 6 }}>{bt.similar_summary}</div>}
      {bt.limitations && bt.limitations.length > 0 && (
        <div style={{ fontSize: 9, color: 'var(--amber)', marginTop: 4 }}>
          Limitations: {bt.limitations.join('; ')}
        </div>
      )}
    </div>
  )
}

function StockHistoryPanel({ p }: { p: any }) {
  const hist = typeof p.stock_history_summary === 'string' ? JSON.parse(p.stock_history_summary || '{}') : (p.stock_history_summary || {})
  if (!hist.prior_scans && hist.prior_scans !== 0) {
    return <div style={{ fontSize: 10, color: 'var(--text3)', fontStyle: 'italic' }}>No stock history available</div>
  }
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 6 }}>
      {kv('Prior Scans', hist.prior_scans)}
      {kv('GO Count', hist.go_count)}
      {kv('WAIT Count', hist.wait_count)}
      {kv('A+ Count', hist.aplus_count)}
      {kv('Paper Trades', hist.paper_trades)}
      {kv('Paper Wins', hist.paper_wins)}
      {kv('Paper PnL', hist.paper_pnl != null ? `$${Number(hist.paper_pnl).toFixed(2)}` : null)}
      {kv('Last Result', hist.last_result || 'None')}
    </div>
  )
}

function ConfirmModal({ p, onConfirm, onCancel }: { p: any; onConfirm: () => void; onCancel: () => void }) {
  const ds = dsColors[p.decision_state] || dsColors.CAUTIOUS_PAPER_TEST
  const reasons = p.approval_blocked_reason ? p.approval_blocked_reason.split(';').map((r: string) => r.trim()) : ['Non-standard approval']
  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 }}>
      <div style={{ background: 'var(--bg1)', borderRadius: 12, padding: 24, maxWidth: 420, width: '90%', border: '1px solid var(--border)' }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 12 }}>This is not an approve-ready proposal.</div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
          <span style={{ ...mono, fontSize: 11 }}>State:</span>
          <span style={{ fontSize: 10, fontWeight: 700, padding: '3px 8px', borderRadius: 4, background: ds.bg, color: ds.text }}>{ds.label}</span>
        </div>
        <div style={{ fontSize: 10, color: 'var(--text2)', marginBottom: 8, fontWeight: 600 }}>Reasons:</div>
        <ul style={{ margin: 0, paddingLeft: 16, marginBottom: 16 }}>
          {reasons.map((r: string, i: number) => <li key={i} style={{ fontSize: 10, color: 'var(--text2)', marginBottom: 4 }}>{r}</li>)}
        </ul>
        <div style={{ fontSize: 10, color: 'var(--amber)', marginBottom: 16 }}>
          Approve only if this is an intentional paper-learning test.
        </div>
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <button onClick={onCancel} style={btnStyle('var(--bg0)', 'var(--text2)')}>Cancel</button>
          <button onClick={onConfirm} style={btnStyle('var(--amber)', '#000')}>Approve as paper-learning test</button>
        </div>
      </div>
    </div>
  )
}

function ProposalCard({ p, act, acting }: { p: any; act: (id: number, action: string, overrides?: any) => void; acting: Record<number, string> }) {
  const [editing, setEditing] = useState(false)
  const [shares, setShares] = useState(p.proposed_shares || 0)
  const [entry, setEntry] = useState(p.proposed_entry || 0)
  const [stop, setStop] = useState(p.proposed_stop || 0)
  const [target, setTarget] = useState(p.proposed_target1 || 0)
  const [activeTab, setActiveTab] = useState('summary')
  const [showConfirm, setShowConfirm] = useState(false)
  const [runningAction, setRunningAction] = useState<string | null>(null)

  const riskPS = Math.abs(entry - stop)
  const computedRisk = riskPS * shares
  const computedRR = riskPS > 0 ? (target - entry) / riskPS : 0
  const computedReward = (target - entry) * shares
  const isModified = shares !== (p.proposed_shares||0) || entry !== (p.proposed_entry||0) || stop !== (p.proposed_stop||0) || target !== (p.proposed_target1||0)

  const ds = dsColors[p.decision_state] || dsColors.CAUTIOUS_PAPER_TEST
  const cd = p.minutes_remaining != null ? {
    color: p.minutes_remaining > 90 ? 'var(--green)' : p.minutes_remaining > 30 ? 'var(--amber)' : 'var(--red)',
    text: p.minutes_remaining > 60 ? `${Math.floor(p.minutes_remaining/60)}h ${p.minutes_remaining%60}m` : `${p.minutes_remaining}m`,
  } : null

  const canApprove = p.decision_state === 'APPROVE_READY_PAPER_TEST'
  const canApproveWithConfirm = ['CAUTIOUS_PAPER_TEST', 'BACKTEST_INSUFFICIENT'].includes(p.decision_state) || p.paper_ready
  const approveDisabled = !canApprove && !canApproveWithConfirm

  const handleApprove = () => {
    if (canApprove) {
      act(p.id, 'approve', isModified ? { shares, entry, stop, target, confirmed: true } : { confirmed: true })
    } else if (canApproveWithConfirm) {
      setShowConfirm(true)
    }
  }

  const handleConfirmApprove = () => {
    setShowConfirm(false)
    act(p.id, 'approve', isModified ? { shares, entry, stop, target, confirmed: true, approval_mode: 'cautious_confirmed' } : { confirmed: true, approval_mode: 'cautious_confirmed' })
  }

  const runAction = async (actionName: string, endpoint: string, extras?: Record<string, any>) => {
    setRunningAction(actionName)
    try {
      const payload: any = { proposal_id: p.id, ...extras }
      if (actionName === 'submitPaper') payload.confirmed = true
      const r = await fetch(endpoint, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })
      const d = await r.json()
      if (!d.ok) alert(d.error || `${actionName} failed`)
      window.location.reload()
    } catch { alert('Network error') }
    setRunningAction(null)
  }

  const tabs = [
    { key: 'summary', label: 'Summary' },
    { key: 'technical', label: 'Technical' },
    { key: 'tech_map', label: 'Tech Map' },
    { key: 'catalyst', label: 'Catalyst' },
    { key: 'strategy_fit', label: 'Strategy Fit' },
    { key: 'backtest', label: 'Backtest' },
    { key: 'risk', label: 'Risk / Reward' },
    { key: 'execution', label: 'Execution' },
    { key: 'agents', label: 'Agents' },
    { key: 'missing', label: 'Missing' },
  ]

  return (
    <div style={{
      background: 'var(--bg1)', borderRadius: 8, marginBottom: 14,
      border: `1px solid ${p.decision_state === 'REJECT_RECOMMENDED' || p.decision_state === 'BLOCKED_BY_RISK_GATE' ? 'rgba(239,68,68,0.3)' : isModified ? 'rgba(59,130,246,0.5)' : 'var(--border)'}`,
    }}>
      {showConfirm && <ConfirmModal p={p} onConfirm={handleConfirmApprove} onCancel={() => setShowConfirm(false)} />}

      {/* ── Header ── */}
      <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            <span style={{ fontSize: 18, fontWeight: 700, color: 'var(--text0)', ...mono }}>{p.symbol}</span>
            {p.signal_grade && <span style={pill(p.signal_grade === 'A' || p.signal_grade === 'A+' ? 'green' : p.signal_grade === 'B' ? 'amber' : 'red')}>{p.signal_grade}</span>}
            {p.signal_score && <span style={{ fontSize: 10, color: 'var(--text2)', ...mono }}>{p.signal_score}pts</span>}
            <span style={{ fontSize: 9, color: 'var(--text3)' }}>{p.strategy_id}</span>
            <span style={{ fontSize: 9, color: 'var(--text3)' }}>#{p.id}</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 10, fontWeight: 700, padding: '3px 8px', borderRadius: 4, background: ds.bg, color: ds.text }}>{ds.label}</span>
            {cd && <span style={{ fontSize: 9, fontWeight: 600, color: cd.color, ...mono }}>{cd.text}</span>}
          </div>
        </div>
        {/* Scores row */}
        <div style={{ display: 'flex', gap: 16, marginTop: 8, flexWrap: 'wrap' }}>
          {kv('Research', p.research_score != null ? `${Math.round(p.research_score)}/100` : 'not run')}
          {kv('Confidence', p.confidence_score != null ? `${Math.round(p.confidence_score)}/100` : 'not run')}
          {kv('Live Ready', `${p.live_readiness_score || 0}/100 — PAPER ONLY`)}
          {kv('Agent Review', p.agent_review_status || 'not reviewed')}
          {kv('LLM', p.local_llm_review_status || 'not run')}
          {kv('Backtest', p.backtest_status || 'not run')}
          {kv('Source', p.source_lineage?.source || p.discovery_source || '—')}
        </div>
      </div>

      {/* ── Tabs ── */}
      <div style={{ padding: '0 16px', borderBottom: '1px solid var(--border)', display: 'flex', gap: 0, overflow: 'auto' }}>
        {tabs.map(t => (
          <button key={t.key} onClick={() => setActiveTab(t.key)}
            style={{ padding: '8px 12px', fontSize: 9, fontWeight: 600, border: 'none', borderBottom: activeTab === t.key ? '2px solid var(--blue)' : '2px solid transparent', cursor: 'pointer', color: activeTab === t.key ? 'var(--text0)' : 'var(--text3)', background: 'transparent', whiteSpace: 'nowrap' }}>
            {t.label}
          </button>
        ))}
      </div>

      <div style={{ padding: '12px 16px' }}>
        {/* ── Session 24A: Lifecycle bar (always visible) ── */}
        {(() => {
          const lc = p.lifecycle_status || p.technical_snapshot?.lifecycle_status
          const ez = p.entry_zone_status || p.technical_snapshot?.entry_zone_status
          const drift = p.price_drift_pct
          const cp = p.current_price
          const tc = p.proposal_timeframe_class
          const lcColor = lc === 'ENTRY_ZONE_VALID' ? 'green' : lc === 'ACTIVE' ? 'blue'
            : lc === 'NEEDS_REVIEW' || lc === 'ENTRY_MISSED' ? 'amber'
            : lc === 'STALE' ? 'amber' : lc?.includes('EXPIRED') ? 'red' : 'blue'
          return (lc || cp) ? (
            <div style={{ display: 'flex', gap: 6, padding: '6px 16px', borderBottom: '1px solid var(--border)', alignItems: 'center', flexWrap: 'wrap', fontSize: 10 }}>
              {lc && <span style={pill(lcColor)}>{lc}</span>}
              {ez && <span style={{ color: 'var(--text3)', ...mono }}>Zone: {ez}</span>}
              {cp != null && <span style={{ color: 'var(--text1)', ...mono }}>Price: ${Number(cp).toFixed(2)}</span>}
              {drift != null && <span style={{ color: Math.abs(Number(drift)) > 5 ? 'var(--red)' : 'var(--text2)', ...mono }}>Drift: {Number(drift) > 0 ? '+' : ''}{Number(drift).toFixed(1)}%</span>}
              {tc && <span style={{ color: 'var(--text3)' }}>{tc}</span>}
              {p.expiry_extended_count > 0 && <span style={pill('blue')}>Extended x{p.expiry_extended_count}</span>}
              {p.last_price_source && <span style={{ color: 'var(--text3)' }}>via {p.last_price_source}</span>}
              <button onClick={() => runAction('monitor', '/api/v2/paper-proposals/monitor')}
                disabled={!!runningAction} style={{ ...btnStyle('rgba(59,130,246,0.15)', '#60A5FA'), padding: '2px 8px', fontSize: 9 }}>
                {runningAction === 'monitor' ? '...' : 'Refresh'}
              </button>
            </div>
          ) : null
        })()}

        {/* ── Summary Tab ── */}
        {activeTab === 'summary' && (
          <>
            {/* Rejection / Cooldown Warning */}
            {p.recently_rejected && (
              <div style={{ padding: '6px 10px', marginBottom: 8, borderRadius: 6, fontSize: 10, fontWeight: 600, background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.2)', color: '#F87171' }}>
                Recently rejected: {p.rejection_reason || 'Unknown reason'}{p.rejection_cooldown_until && ` — cooldown until ${new Date(p.rejection_cooldown_until).toLocaleString()}`}
              </div>
            )}

            {/* Intelligence Readiness + Quality Review badges */}
            <div style={{ display: 'flex', gap: 8, marginBottom: 8, flexWrap: 'wrap' }}>
              {p.intelligence ? (
                <span style={pill(p.intelligence.intelligence_readiness >= 70 ? 'green' : p.intelligence.intelligence_readiness >= 50 ? 'amber' : 'red')}>
                  Intel: {p.intelligence.intelligence_readiness}/100 ({p.intelligence.readiness_source || 'unknown'})
                </span>
              ) : (
                <span style={pill('amber')}>Intel: not computed</span>
              )}
              {p.quality_review ? (
                <span style={pill(p.quality_review.review_state === 'HIGH_QUALITY_TEST' ? 'green' : p.quality_review.review_state === 'CAUTIOUS_TEST' ? 'amber' : p.quality_review.review_state === 'REJECT_RECOMMENDED' || p.quality_review.review_state === 'BLOCKED_BY_RISK_GATE' ? 'red' : 'blue')}>
                  Quality: {p.quality_review.review_state} ({(p.quality_review.quality_score * 100).toFixed(0)}%)
                </span>
              ) : (
                <span style={pill('amber')}>Quality review not run yet</span>
              )}
            </div>

            <div style={{ fontSize: 11, color: 'var(--text1)', lineHeight: 1.6, padding: '8px 10px', background: 'var(--bg0)', borderRadius: 6, marginBottom: 8 }}>
              {p.agent_narrative || 'No narrative available.'}
              {p.narrative_source && <span style={{ fontSize: 9, color: 'var(--text3)', marginLeft: 8 }}>({p.narrative_source})</span>}
            </div>

            {/* Agent Reviews (Maria / Risk / Steph) */}
            <div style={secLbl}>Agent Reviews (Maria / Risk / Steph)</div>
            {p.agent_reviews && p.agent_reviews.length > 0 ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                {p.agent_reviews.filter((ar: any) => ['maria','risk_agent','steph','Maria','Risk','Steph'].includes(ar.agent_name)).map((ar: any, i: number) => {
                  const voteColor = ar.verdict === 'APPROVE_TEST' || ar.verdict === 'BUY' ? 'green'
                    : ar.verdict === 'REJECT' || ar.verdict === 'BLOCK' || ar.verdict === 'AVOID' || ar.verdict === 'SELL' ? 'red'
                    : ar.verdict === 'WAIT_FOR_DATA' ? 'blue' : 'amber'
                  return (
                    <div key={i} style={{ padding: '4px 8px', background: 'var(--bg0)', borderRadius: 4, display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                      <span style={{ fontSize: 10, fontWeight: 700, color: 'var(--text1)', minWidth: 70, ...mono }}>{ar.agent_name}</span>
                      <span style={pill(voteColor)}>{ar.verdict} {ar.confidence != null ? `${Math.round(Number(ar.confidence) * (Number(ar.confidence) > 1 ? 1 : 100))}%` : ''}</span>
                      <span style={{ fontSize: 9, color: 'var(--text2)', flex: 1 }}>{(ar.summary || '').slice(0, 120)}</span>
                    </div>
                  )
                })}
              </div>
            ) : (
              <div style={{ padding: '8px 10px', background: 'var(--bg0)', borderRadius: 6, fontSize: 10, color: 'var(--amber)', fontStyle: 'italic' }}>
                Agent reviews not run yet
              </div>
            )}

            {/* qwen3:14b LLM Analysis */}
            <div style={secLbl}>LLM Analysis (qwen3:14b)</div>
            {p.llm_analysis ? (
              <div style={{ padding: '8px 10px', background: 'var(--bg0)', borderRadius: 6, fontSize: 10, lineHeight: 1.5 }}>
                <div style={{ color: 'var(--text1)', marginBottom: 4 }}>{p.llm_analysis.summary}</div>
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 4 }}>
                  <span style={pill(p.llm_analysis.narrative_source === 'local_llm' ? 'green' : 'amber')}>
                    {p.llm_analysis.narrative_source === 'local_llm' ? `LLM: ${p.llm_analysis.model_used || 'qwen3:14b'}` : 'Deterministic fallback'}
                  </span>
                  {p.llm_analysis.confidence != null && (
                    <span style={{ fontSize: 9, color: 'var(--text2)', ...mono }}>conf: {(Number(p.llm_analysis.confidence) * 100).toFixed(0)}%</span>
                  )}
                </div>
              </div>
            ) : (
              <div style={{ padding: '8px 10px', background: 'var(--bg0)', borderRadius: 6, fontSize: 10, color: 'var(--amber)', fontStyle: 'italic' }}>
                LLM analysis not run yet
              </div>
            )}

            {/* Approve / Reject Cases */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginTop: 8 }}>
              <div>
                <div style={secLbl}>Approve Case</div>
                <div style={{ fontSize: 10, color: 'var(--green)', lineHeight: 1.5, padding: '6px 8px', background: 'rgba(34,197,94,0.05)', borderRadius: 4, border: '1px solid rgba(34,197,94,0.15)' }}>
                  {p.llm_analysis?.approve_case || p.approve_case || 'No approve rationale.'}
                </div>
              </div>
              <div>
                <div style={secLbl}>Reject Case</div>
                <div style={{ fontSize: 10, color: 'var(--red)', lineHeight: 1.5, padding: '6px 8px', background: 'rgba(239,68,68,0.05)', borderRadius: 4, border: '1px solid rgba(239,68,68,0.15)' }}>
                  {p.llm_analysis?.reject_case || p.reject_case || 'No rejection signals.'}
                </div>
              </div>
            </div>

            {/* Refresh Analysis button */}
            {(!p.agent_reviews?.length || !p.llm_analysis || !p.quality_review) && (
              <div style={{ marginTop: 10, textAlign: 'center' }}>
                <button onClick={() => runAction('refresh', '/api/v2/paper-proposals/refresh-data')} disabled={!!runningAction}
                  style={btnStyle('rgba(59,130,246,0.2)', '#60A5FA')}>
                  {runningAction === 'refresh' ? '...' : 'Refresh Analysis'}
                </button>
              </div>
            )}
          </>
        )}

        {/* ── Technical Tab ── */}
        {activeTab === 'technical' && (
          <>
            <div style={secLbl}>Technical Intelligence</div>
            <TechPanel p={p} />
            {p.technical_summary && (
              <div style={{ fontSize: 10, color: 'var(--text2)', marginTop: 8, padding: '6px 8px', background: 'var(--bg0)', borderRadius: 4 }}>
                {p.technical_summary}
              </div>
            )}
            {/* Session 23D: Technical grade */}
            {p.technical_snapshot?.technical_grade && (
              <div style={{ marginTop: 8, display: 'flex', gap: 8, alignItems: 'center' }}>
                <span style={pill(p.technical_snapshot.technical_grade === 'TECH_STRONG' ? 'green' : p.technical_snapshot.technical_grade === 'TECH_OK' ? 'blue' : 'amber')}>
                  {p.technical_snapshot.technical_grade}
                </span>
                {p.technical_snapshot.ohlcv_data_status && (
                  <span style={{ fontSize: 9, color: 'var(--text3)' }}>OHLCV: {p.technical_snapshot.ohlcv_data_status}</span>
                )}
              </div>
            )}
            <div style={{ display: 'flex', gap: 4, marginTop: 8, flexWrap: 'wrap' }}>
              <button onClick={() => runAction('techSnap', '/api/v2/paper-proposals/run-technical-snapshot')}
                disabled={!!runningAction} style={btnStyle('rgba(59,130,246,0.15)', '#60A5FA')}>
                {runningAction === 'techSnap' ? '...' : 'Run Technical Snapshot'}
              </button>
              <button onClick={() => runAction('runFib', '/api/v2/paper-proposals/run-fib')}
                disabled={!!runningAction} style={btnStyle('rgba(59,130,246,0.15)', '#60A5FA')}>
                {runningAction === 'runFib' ? '...' : 'Run Fib'}
              </button>
              <button onClick={() => runAction('runOrb', '/api/v2/paper-proposals/run-opening-range')}
                disabled={!!runningAction} style={btnStyle('rgba(59,130,246,0.15)', '#60A5FA')}>
                {runningAction === 'runOrb' ? '...' : 'Run Opening Range'}
              </button>
            </div>
          </>
        )}

        {/* ── Tech Map Tab (Session 23D) ── */}
        {activeTab === 'tech_map' && (
          <>
            <div style={secLbl}>EMA Stack</div>
            {(() => {
              const ts = p.technical_snapshot || {}
              const alignColor = ts.ema_alignment === 'BULL_STACKED' ? 'green'
                : ts.ema_alignment === 'BULLISH' ? 'green'
                : ts.ema_alignment === 'BEARISH' ? 'red' : 'amber'
              return (
                <>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 6, marginBottom: 8 }}>
                    {kv('EMA 8', ts.ema_8 != null ? `$${Number(ts.ema_8).toFixed(2)}` : '--')}
                    {kv('EMA 21', ts.ema_21 != null ? `$${Number(ts.ema_21).toFixed(2)}` : '--')}
                    {kv('EMA 50', ts.ema_50 != null ? `$${Number(ts.ema_50).toFixed(2)}` : '--')}
                    {kv('EMA 200', ts.ema_200 != null ? `$${Number(ts.ema_200).toFixed(2)}` : '--')}
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 6, marginBottom: 8 }}>
                    {kv('EMA 8 Dist', ts.ema_8_distance_pct != null ? `${Number(ts.ema_8_distance_pct).toFixed(1)}%` : '--')}
                    {kv('EMA 21 Dist', ts.ema_21_distance_pct != null ? `${Number(ts.ema_21_distance_pct).toFixed(1)}%` : '--')}
                    {kv('EMA 50 Dist', ts.ema_50_distance_pct != null ? `${Number(ts.ema_50_distance_pct).toFixed(1)}%` : '--')}
                    {kv('EMA 200 Dist', ts.ema_200_distance_pct != null ? `${Number(ts.ema_200_distance_pct).toFixed(1)}%` : '--')}
                  </div>
                  <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 8 }}>
                    <span style={pill(alignColor)}>{ts.ema_alignment || 'N/A'}</span>
                    <span style={{ fontSize: 9, color: 'var(--text3)' }}>EMA Alignment</span>
                  </div>
                </>
              )
            })()}

            <div style={secLbl}>Fibonacci Levels</div>
            {(() => {
              const ts = p.technical_snapshot || {}
              const fc = typeof p.fib_context === 'object' ? p.fib_context : (ts.fib_context || {})
              if (!fc || fc.available === false) {
                return <div style={{ fontSize: 10, color: 'var(--text3)', fontStyle: 'italic' }}>{fc?.summary || 'Fib data unavailable'}</div>
              }
              return (
                <>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 6, marginBottom: 8 }}>
                    {kv('Swing High', ts.swing_high != null ? `$${Number(ts.swing_high).toFixed(2)}` : fc.swing_high ? `$${Number(fc.swing_high).toFixed(2)}` : '--')}
                    {kv('Swing Low', ts.swing_low != null ? `$${Number(ts.swing_low).toFixed(2)}` : fc.swing_low ? `$${Number(fc.swing_low).toFixed(2)}` : '--')}
                    {kv('Nearest Fib', ts.nearest_fib_level || fc.nearest || '--')}
                    {kv('Fib Distance', ts.nearest_fib_distance_pct != null ? `${Number(ts.nearest_fib_distance_pct).toFixed(1)}%` : fc.distance_pct != null ? `${Number(fc.distance_pct).toFixed(1)}%` : '--')}
                  </div>
                  {fc.interpretation && <div style={{ fontSize: 10, color: 'var(--text2)', padding: '4px 8px', background: 'var(--bg0)', borderRadius: 4 }}>{fc.interpretation}</div>}
                </>
              )
            })()}

            <div style={secLbl}>Opening Range / Premarket</div>
            {(() => {
              const ts = p.technical_snapshot || {}
              const orbColor = ts.opening_range_status === 'ORB_BREAKOUT_CONFIRMED' ? 'green'
                : ts.opening_range_status === 'ORB_BREAKOUT_FAILED' ? 'red'
                : ts.opening_range_status === 'INSIDE_OPENING_RANGE' ? 'blue' : 'amber'
              return (
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 6 }}>
                  {kv('ORB 15 High', ts.opening_range_high != null ? `$${Number(ts.opening_range_high).toFixed(2)}` : '--')}
                  {kv('ORB 15 Low', ts.opening_range_low != null ? `$${Number(ts.opening_range_low).toFixed(2)}` : '--')}
                  {kv('PM High', ts.premarket_high != null ? `$${Number(ts.premarket_high).toFixed(2)}` : '--')}
                  {kv('PM Low', ts.premarket_low != null ? `$${Number(ts.premarket_low).toFixed(2)}` : '--')}
                  {kv('ORB Status', <span style={pill(orbColor)}>{ts.opening_range_status || 'N/A'}</span>)}
                  {kv('PM Status', ts.premarket_status || 'N/A')}
                  {kv('Tech Grade', ts.technical_grade || 'N/A')}
                  {kv('OHLCV', ts.ohlcv_data_status || 'N/A')}
                </div>
              )
            })()}
          </>
        )}

        {/* ── Catalyst / News Tab ── */}
        {activeTab === 'catalyst' && (
          <>
            <div style={secLbl}>Catalyst</div>
            <div style={{ fontSize: 11, color: 'var(--text1)', lineHeight: 1.4, marginBottom: 8 }}>
              {p.catalyst_verified ? <span style={{ color: 'var(--green)', marginRight: 4 }}>&#10003;</span> : <span style={{ color: 'var(--amber)', marginRight: 4 }}>?</span>}
              {p.catalyst || 'No catalyst data'}
              {p.catalyst_confidence != null && <span style={{ color: 'var(--text3)', fontSize: 9, marginLeft: 6 }}>{(p.catalyst_confidence * 100).toFixed(0)}% confidence</span>}
            </div>
            {/* Catalyst Quality Assessment */}
            {p.catalyst_quality && (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 6, marginBottom: 8, padding: '6px 8px', background: 'var(--bg0)', borderRadius: 4 }}>
                {kv('Quality', `${p.catalyst_quality.catalyst_quality_score}/100`,
                  p.catalyst_quality.catalyst_quality_score >= 70 ? 'var(--green)' : p.catalyst_quality.catalyst_quality_score >= 50 ? 'var(--amber)' : 'var(--red)')}
                {kv('Grade', p.catalyst_quality.catalyst_grade)}
                {kv('Type', p.catalyst_quality.catalyst_type)}
                {kv('Duration', p.catalyst_quality.duration_estimate)}
              </div>
            )}
            {p.critic_verdict && (
              <div style={{ marginBottom: 8 }}>
                <span style={pill(p.critic_verdict === 'PASS' ? 'green' : p.critic_verdict === 'BLOCK' ? 'red' : 'amber')}>
                  {p.critic_verdict} {p.critic_confidence != null ? `${(p.critic_confidence * 100).toFixed(0)}%` : ''}
                </span>
                {p.critic_reasoning && <div style={{ fontSize: 10, color: 'var(--text2)', marginTop: 4, lineHeight: 1.4 }}>{p.critic_reasoning}</div>}
              </div>
            )}
            <div style={secLbl}>Recent News</div>
            {p.news && Array.isArray(p.news) && p.news.length > 0 ? p.news.slice(0, 5).map((n: any, i: number) => (
              <div key={i} style={{ fontSize: 10, color: 'var(--text2)', padding: '2px 0' }}>
                {n.title} <span style={{ color: 'var(--text3)', marginLeft: 6, fontSize: 9 }}>{n.source}</span>
              </div>
            )) : <div style={{ fontSize: 10, color: 'var(--text3)', fontStyle: 'italic' }}>No recent news articles found</div>}
          </>
        )}

        {/* ── Strategy Fit Tab ── */}
        {activeTab === 'strategy_fit' && (
          <>
            <div style={secLbl}>Strategy Fit — {p.strategy_id}</div>
            {p.strategy_fit ? (
              <>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 6, marginBottom: 8 }}>
                  {kv('Fit Score', `${p.strategy_fit.fit_score}/100`,
                    p.strategy_fit.fit_score >= 80 ? 'var(--green)' : p.strategy_fit.fit_score >= 60 ? 'var(--amber)' : 'var(--red)')}
                  {kv('Grade', p.strategy_fit.fit_grade,
                    p.strategy_fit.fit_grade === 'STRONG_FIT' ? 'var(--green)' : p.strategy_fit.fit_grade === 'GOOD_FIT' ? '#60A5FA' : 'var(--amber)')}
                  {kv('Setup Class', p.strategy_fit.setup_class || 'unclassified')}
                  {kv('Strategy', p.strategy_fit.strategy_id)}
                </div>
                {p.strategy_fit.criteria_met?.length > 0 && (
                  <div style={{ marginBottom: 6 }}>
                    <div style={{ fontSize: 9, color: 'var(--text3)', fontWeight: 600, marginBottom: 4 }}>CRITERIA MET</div>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                      {p.strategy_fit.criteria_met.map((c: string, i: number) => (
                        <span key={i} style={{ ...pill('green'), fontSize: 8 }}>{c}</span>
                      ))}
                    </div>
                  </div>
                )}
                {p.strategy_fit.criteria_failed?.length > 0 && (
                  <div style={{ marginBottom: 6 }}>
                    <div style={{ fontSize: 9, color: 'var(--text3)', fontWeight: 600, marginBottom: 4 }}>CRITERIA FAILED</div>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                      {p.strategy_fit.criteria_failed.map((c: string, i: number) => (
                        <span key={i} style={{ ...pill('red'), fontSize: 8 }}>{c}</span>
                      ))}
                    </div>
                  </div>
                )}
                {p.strategy_fit.narrative && (
                  <div style={{ fontSize: 10, color: 'var(--text2)', lineHeight: 1.5, marginTop: 6, padding: '6px 8px', background: 'var(--bg0)', borderRadius: 4 }}>
                    {p.strategy_fit.narrative}
                  </div>
                )}
              </>
            ) : (
              <div style={{ fontSize: 10, color: 'var(--text3)', fontStyle: 'italic' }}>Strategy fit not computed yet</div>
            )}

            {/* Sector context inline */}
            <div style={{ ...secLbl, marginTop: 12 }}>Sector Context</div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 6 }}>
              {kv('Sector', p.sector)}
              {kv('Industry', p.industry)}
              {kv('Ticker 1M', p.ticker_perf_1m != null ? `${Number(p.ticker_perf_1m).toFixed(1)}%` : null)}
              {kv('vs Sector', p.vs_sector_pct != null ? `${Number(p.vs_sector_pct) > 0 ? '+' : ''}${Number(p.vs_sector_pct).toFixed(1)}%` : null,
                p.vs_sector_pct != null ? (Number(p.vs_sector_pct) > 0 ? 'var(--green)' : 'var(--red)') : undefined)}
            </div>
          </>
        )}

        {/* ── Backtest Tab ── */}
        {activeTab === 'backtest' && (
          <>
            <div style={secLbl}>Backtest / Historical Evidence</div>
            <BacktestPanel p={p} />
          </>
        )}

        {/* ── Risk / Reward Tab ── */}
        {activeTab === 'risk' && (
          <>
            <div style={secLbl}>Risk / Reward</div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 6, marginBottom: 6 }}>
              <div>
                <div style={lbl}>Entry</div>
                {editing ? <input type="number" step="0.01" value={entry} onChange={e => setEntry(Number(e.target.value))} style={inputStyle} />
                  : <div style={{ fontSize: 11, color: 'var(--text0)', fontWeight: 600, ...mono }}>${entry.toFixed(2)}</div>}
              </div>
              <div>
                <div style={lbl}>Stop</div>
                {editing ? <input type="number" step="0.01" value={stop} onChange={e => setStop(Number(e.target.value))} style={inputStyle} />
                  : <div style={{ fontSize: 11, color: 'var(--red)', fontWeight: 600, ...mono }}>${stop.toFixed(2)}</div>}
              </div>
              <div>
                <div style={lbl}>Target 1</div>
                {editing ? <input type="number" step="0.01" value={target} onChange={e => setTarget(Number(e.target.value))} style={inputStyle} />
                  : <div style={{ fontSize: 11, color: 'var(--green)', fontWeight: 600, ...mono }}>${target.toFixed(2)}</div>}
              </div>
              <div>
                <div style={lbl}>Shares</div>
                {editing ? <input type="number" step="1" value={shares} onChange={e => setShares(Number(e.target.value))} style={inputStyle} />
                  : <div style={{ fontSize: 11, color: 'var(--text0)', fontWeight: 600, ...mono }}>{shares}</div>}
              </div>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 6 }}>
              {kv('Risk $', `$${(isModified ? computedRisk : p.proposed_dollar_risk || 0).toFixed(0)}`, 'var(--red)')}
              {kv('Reward T1 $', `$${(isModified ? computedReward : p.target1_dollar_reward || 0).toFixed(0)}`, 'var(--green)')}
              {kv('R:R', (isModified ? computedRR : p.proposed_rr || 0).toFixed(2))}
              {kv('Risk % Portfolio', `${(p.risk_pct_portfolio || 0).toFixed(3)}%`)}
              {kv('Gate', p.risk_gate_result || '--')}
            </div>
            {isModified && <div style={{ fontSize: 9, color: '#60A5FA', marginTop: 8, fontWeight: 600 }}>Modified — will approve with overrides</div>}
          </>
        )}

        {/* ── Agent Notes Tab ── */}
        {activeTab === 'agents' && (
          <>
            <div style={secLbl}>Agent Reviews</div>
            <AgentReviewPanel votes={p.agent_votes} />
          </>
        )}

        {/* ── Execution Readiness Tab ── */}
        {activeTab === 'execution' && (
          <>
            <div style={secLbl}>Execution Readiness</div>
            {p.execution_readiness ? (() => {
              const er = p.execution_readiness
              const stateColor = er.readiness_state === 'READY_FOR_PAPER_SUBMIT' ? 'green'
                : er.readiness_state === 'CAUTION_EXECUTABLE' ? 'amber' : 'red'
              return (
                <>
                  <div style={{ display: 'flex', gap: 8, marginBottom: 8, alignItems: 'center' }}>
                    <span style={pill(stateColor)}>{er.readiness_state}</span>
                    <span style={{ fontSize: 10, color: 'var(--text2)', ...mono }}>Score: {er.readiness_score}/100</span>
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 6, marginBottom: 8 }}>
                    {kv('Quote Price', er.quote_price ? `$${Number(er.quote_price).toFixed(2)}` : null)}
                    {kv('Quote Age', er.quote_age_seconds != null ? `${Math.round(Number(er.quote_age_seconds))}s` : null,
                      Number(er.quote_age_seconds) > 300 ? 'var(--red)' : 'var(--green)')}
                    {kv('Price vs Entry', er.price_vs_entry_pct != null ? `${Number(er.price_vs_entry_pct) > 0 ? '+' : ''}${Number(er.price_vs_entry_pct).toFixed(2)}%` : null,
                      Math.abs(Number(er.price_vs_entry_pct)) > 2 ? 'var(--red)' : 'var(--green)')}
                    {kv('Spread', er.spread_pct != null ? `${Number(er.spread_pct).toFixed(3)}%` : 'N/A')}
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 6, marginBottom: 8 }}>
                    {kv('Quote Fresh', er.quote_fresh ? 'YES' : 'NO', er.quote_fresh ? 'var(--green)' : 'var(--red)')}
                    {kv('Price OK', er.price_ok ? 'YES' : 'NO', er.price_ok ? 'var(--green)' : 'var(--red)')}
                    {kv('Risk Gate', er.risk_gate_ok ? 'PASS' : 'FAIL', er.risk_gate_ok ? 'var(--green)' : 'var(--red)')}
                    {kv('No Duplicate', er.duplicate_ok ? 'OK' : 'DUP', er.duplicate_ok ? 'var(--green)' : 'var(--red)')}
                  </div>
                  {er.blockers && er.blockers.length > 0 && (
                    <div style={{ marginBottom: 6 }}>
                      <div style={{ fontSize: 9, color: 'var(--red)', fontWeight: 600, marginBottom: 4 }}>BLOCKERS</div>
                      {er.blockers.map((b: string, i: number) => (
                        <div key={i} style={{ fontSize: 10, color: 'var(--red)', padding: '2px 0' }}>{b}</div>
                      ))}
                    </div>
                  )}
                  {er.warnings && er.warnings.length > 0 && (
                    <div style={{ marginBottom: 6 }}>
                      <div style={{ fontSize: 9, color: 'var(--amber)', fontWeight: 600, marginBottom: 4 }}>WARNINGS</div>
                      {er.warnings.map((w: string, i: number) => (
                        <div key={i} style={{ fontSize: 9, color: 'var(--amber)', padding: '2px 0' }}>{w}</div>
                      ))}
                    </div>
                  )}
                  {er.execution_plan && (
                    <>
                      <div style={secLbl}>Execution Plan</div>
                      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 6 }}>
                        {kv('Order Type', er.execution_plan.order_type)}
                        {kv('Limit', er.execution_plan.limit_price ? `$${Number(er.execution_plan.limit_price).toFixed(2)}` : null)}
                        {kv('Stop', er.execution_plan.stop_price ? `$${Number(er.execution_plan.stop_price).toFixed(2)}` : null)}
                        {kv('Target', er.execution_plan.take_profit_price ? `$${Number(er.execution_plan.take_profit_price).toFixed(2)}` : null)}
                        {kv('TIF', er.execution_plan.time_in_force)}
                        {kv('Shares', er.execution_plan.shares)}
                      </div>
                    </>
                  )}
                  {/* Session 23E: Quote provider info */}
                  <div style={secLbl}>Quote Source</div>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 6, marginBottom: 8 }}>
                    {kv('Provider', er.quote_provider || 'none',
                      er.quote_provider === 'alpaca' || er.quote_provider === 'polygon' ? 'var(--green)'
                        : er.quote_provider === 'none' ? 'var(--red)' : 'var(--amber)')}
                    {kv('Exec Eligible', er.quote_execution_eligible ? 'YES' : 'NO',
                      er.quote_execution_eligible ? 'var(--green)' : 'var(--red)')}
                    {kv('Delayed', er.quote_is_delayed ? 'YES' : 'NO',
                      er.quote_is_delayed ? 'var(--amber)' : 'var(--green)')}
                    {kv('Volume Source', er.volume_source || 'N/A')}
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 6, marginBottom: 8 }}>
                    {kv('Bid', er.bid != null ? `$${Number(er.bid).toFixed(2)}` : 'N/A',
                      er.bid != null ? 'var(--green)' : 'var(--red)')}
                    {kv('Ask', er.ask != null ? `$${Number(er.ask).toFixed(2)}` : 'N/A',
                      er.ask != null ? 'var(--green)' : 'var(--red)')}
                    {kv('Spread', er.spread_pct != null ? `${Number(er.spread_pct).toFixed(3)}%` : 'N/A',
                      er.spread_pct == null ? 'var(--red)' : Number(er.spread_pct) > 1 ? 'var(--red)' : 'var(--green)')}
                    {kv('Spread Source', er.spread_source || 'N/A')}
                  </div>
                  {!er.quote_execution_eligible && er.quote_provider && er.quote_provider !== 'none' && (
                    <div style={{ fontSize: 9, color: 'var(--amber)', padding: '4px 8px', background: 'rgba(251,191,36,0.06)', borderRadius: 4, marginBottom: 8 }}>
                      Blocked: {er.quote_provider} provides display-only data. Execution-grade quote requires Alpaca or Polygon with bid/ask.
                    </div>
                  )}

                  {/* Session 23D: Bracket validation */}
                  <div style={secLbl}>Alpaca Paper Bracket</div>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 6, marginBottom: 8 }}>
                    {kv('Bracket Supported', er.bracket_order_supported ? 'YES' : 'NO',
                      er.bracket_order_supported ? 'var(--green)' : 'var(--red)')}
                    {kv('Alpaca Mode', er.alpaca_account_mode || 'N/A',
                      er.alpaca_account_mode === 'paper' ? 'var(--green)' : 'var(--red)')}
                    {kv('Market Hours', er.market_hours ? 'OPEN' : 'CLOSED',
                      er.market_hours ? 'var(--green)' : 'var(--amber)')}
                    {kv('Submit Result', er.paper_submit_test_result || 'not tested')}
                  </div>
                  {er.bracket_dry_run_payload && (
                    <details style={{ fontSize: 9, color: 'var(--text3)', marginBottom: 8 }}>
                      <summary style={{ cursor: 'pointer', fontWeight: 600 }}>Bracket Payload</summary>
                      <pre style={{ fontSize: 9, padding: 6, background: 'var(--bg0)', borderRadius: 4, overflow: 'auto', maxHeight: 120, margin: '4px 0' }}>
                        {JSON.stringify(er.bracket_dry_run_payload, null, 2)}
                      </pre>
                    </details>
                  )}
                  <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                    <button onClick={() => runAction('dryBracket', '/api/v2/paper-proposals/dry-run-alpaca-bracket')}
                      disabled={!!runningAction} style={btnStyle('rgba(59,130,246,0.15)', '#60A5FA')}>
                      {runningAction === 'dryBracket' ? '...' : 'Dry Run Alpaca Bracket'}
                    </button>
                    <button onClick={() => {
                      if (!confirm(`Submit PAPER bracket order for ${p.symbol}?`)) return
                      runAction('submitBracket', '/api/v2/paper-proposals/submit-alpaca-paper-bracket',
                        { confirmed: true })
                    }}
                      disabled={!!runningAction || er.readiness_state?.includes('BLOCKED')}
                      style={btnStyle(
                        er.readiness_state === 'READY_FOR_PAPER_SUBMIT' || er.readiness_state === 'READY_ORB_CONFIRMED'
                          ? 'rgba(34,197,94,0.2)' : 'rgba(148,163,184,0.15)',
                        er.readiness_state === 'READY_FOR_PAPER_SUBMIT' || er.readiness_state === 'READY_ORB_CONFIRMED'
                          ? 'var(--green)' : '#94A3B8'
                      )}>
                      {runningAction === 'submitBracket' ? '...' : 'Submit Alpaca Paper Bracket'}
                    </button>
                  </div>
                </>
              )
            })() : (
              <div style={{ fontSize: 10, color: 'var(--text3)', fontStyle: 'italic' }}>
                Execution readiness not checked yet.
                <button onClick={() => runAction('execReady', '/api/v2/paper-proposals/check-execution-readiness')}
                  disabled={!!runningAction} style={{ ...btnStyle('rgba(59,130,246,0.15)', '#60A5FA'), marginLeft: 8 }}>
                  {runningAction === 'execReady' ? '...' : 'Check Now'}
                </button>
              </div>
            )}
          </>
        )}

        {/* ── Missing Data Tab ── */}
        {activeTab === 'missing' && (
          <>
            <div style={secLbl}>Missing Data</div>
            {p.missing_data && p.missing_data.length > 0 ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                {p.missing_data.map((m: string, i: number) => (
                  <div key={i} style={{ fontSize: 10, color: 'var(--amber)', padding: '4px 8px', background: 'rgba(251,191,36,0.06)', borderRadius: 4 }}>{m}</div>
                ))}
              </div>
            ) : <div style={{ fontSize: 10, color: 'var(--green)' }}>All required data populated</div>}
            {p.approval_blocked_reason && (
              <>
                <div style={{ ...secLbl, color: 'var(--red)' }}>Approval Blockers</div>
                <div style={{ fontSize: 10, color: 'var(--red)', padding: '6px 8px', background: 'rgba(239,68,68,0.05)', borderRadius: 4 }}>
                  {p.approval_blocked_reason}
                </div>
              </>
            )}
          </>
        )}
      </div>

      {/* ── Actions ── */}
      <div style={{ padding: '10px 16px', borderTop: '1px solid var(--border)', display: 'flex', gap: 6, justifyContent: 'flex-end', flexWrap: 'wrap' }}>
        <button onClick={() => runAction('research', '/api/v2/paper-proposals/run-research')} disabled={!!runningAction}
          style={btnStyle('rgba(59,130,246,0.15)', '#60A5FA')}>
          {runningAction === 'research' ? '...' : 'Run Research'}
        </button>
        <button onClick={() => runAction('agent', '/api/v2/paper-proposals/run-agent-review')} disabled={!!runningAction}
          style={btnStyle('rgba(59,130,246,0.15)', '#60A5FA')}>
          {runningAction === 'agent' ? '...' : 'Run AI Review'}
        </button>
        <button onClick={() => runAction('backtest', '/api/v2/paper-proposals/run-backtest')} disabled={!!runningAction}
          style={btnStyle('rgba(59,130,246,0.15)', '#60A5FA')}>
          {runningAction === 'backtest' ? '...' : 'Run Backtest'}
        </button>
        <button onClick={() => runAction('refresh', '/api/v2/paper-proposals/refresh-packet')} disabled={!!runningAction}
          style={btnStyle('rgba(148,163,184,0.15)', '#94A3B8')}>
          {runningAction === 'refresh' ? '...' : 'Refresh Full Packet'}
        </button>
        <button onClick={() => runAction('execReady', '/api/v2/paper-proposals/check-execution-readiness')} disabled={!!runningAction}
          style={btnStyle('rgba(148,163,184,0.15)', '#94A3B8')}>
          {runningAction === 'execReady' ? '...' : 'Check Execution'}
        </button>

        <div style={{ flex: 1 }} />

        {/* Submit to Alpaca Paper */}
        <button
          onClick={() => {
            if (confirm('Submit to Alpaca PAPER trading? This is NOT a live trade.')) {
              runAction('submitPaper', '/api/v2/paper-proposals/submit-alpaca-paper')
            }
          }}
          disabled={!!runningAction || !p.execution_readiness || !['READY_FOR_PAPER_SUBMIT', 'CAUTION_EXECUTABLE'].includes(p.execution_readiness?.readiness_state)}
          title={!p.execution_readiness ? 'Run execution readiness check first' : p.execution_readiness?.readiness_state}
          style={{
            ...btnStyle(
              ['READY_FOR_PAPER_SUBMIT', 'CAUTION_EXECUTABLE'].includes(p.execution_readiness?.readiness_state) ? '#065F46' : 'rgba(34,197,94,0.1)',
              ['READY_FOR_PAPER_SUBMIT', 'CAUTION_EXECUTABLE'].includes(p.execution_readiness?.readiness_state) ? '#10B981' : '#44403C'
            ),
            opacity: !p.execution_readiness || !['READY_FOR_PAPER_SUBMIT', 'CAUTION_EXECUTABLE'].includes(p.execution_readiness?.readiness_state) ? 0.4 : 1,
            cursor: !p.execution_readiness || !['READY_FOR_PAPER_SUBMIT', 'CAUTION_EXECUTABLE'].includes(p.execution_readiness?.readiness_state) ? 'not-allowed' : 'pointer',
            border: '1px solid #047857',
          }}>
          {runningAction === 'submitPaper' ? '...' : 'Submit to Alpaca Paper'}
        </button>

        <button onClick={handleApprove} disabled={!!acting[p.id] || approveDisabled}
          title={approveDisabled ? (p.approval_blocked_reason || 'Missing data') : 'Approve for paper trading'}
          style={{ ...btnStyle(approveDisabled ? 'rgba(34,197,94,0.1)' : canApproveWithConfirm ? 'var(--amber)' : 'var(--green)'), opacity: approveDisabled ? 0.4 : 1, cursor: approveDisabled ? 'not-allowed' : 'pointer' }}>
          {acting[p.id] === 'approve' ? '...' : approveDisabled ? (p.approval_blocked_reason?.slice(0,20) || 'Cannot Approve') : canApproveWithConfirm ? 'Approve (confirm)' : isModified ? 'Approve*' : 'Approve'}
        </button>
        <button onClick={() => act(p.id, 'reject')} disabled={!!acting[p.id]}
          style={btnStyle('var(--red)')}>
          {acting[p.id] === 'reject' ? '...' : 'Reject'}
        </button>
        <button onClick={() => { if (editing) { setShares(p.proposed_shares||0); setEntry(p.proposed_entry||0); setStop(p.proposed_stop||0); setTarget(p.proposed_target1||0) } setEditing(!editing) }}
          style={{ ...btnStyle(editing ? 'rgba(251,191,36,0.15)' : 'var(--bg0)', editing ? 'var(--amber)' : 'var(--text2)'), border: `1px solid ${editing ? 'var(--amber)' : 'var(--border)'}` }}>
          {editing ? 'Reset' : 'Edit'}
        </button>
        {p.tos_order_string && (
          <button onClick={() => navigator.clipboard.writeText(p.tos_order_string)}
            style={{ ...btnStyle('var(--bg0)', 'var(--text2)'), border: '1px solid var(--border)' }}>
            Copy TOS
          </button>
        )}
      </div>
    </div>
  )
}

export default function PaperProposals() {
  const { data, refetch } = useApi<any>('/api/v2/paper-proposals', 30000)
  const [acting, setActing] = useState<Record<number, string>>({})
  const [showAll, setShowAll] = useState(false)
  const [runHealth, setRunHealth] = React.useState<any>(null)
  React.useEffect(() => {
    fetch('/api/v2/pipeline-run-health').then(r => r.json()).then(d => {
      const inner = d.data || d
      if (inner.ok) setRunHealth(inner)
    }).catch(() => {})
  }, [])

  const act = useCallback(async (id: number, action: string, overrides?: any) => {
    setActing(s => ({ ...s, [id]: action }))
    try {
      let body: any = { proposal_id: id }
      if (action === 'approve' && overrides) Object.assign(body, overrides)
      if (action === 'reject') body.reason = 'dashboard'
      const r = await fetch(`/api/v2/paper-proposals/${action}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
      const d = await r.json()
      if (!(d.data || d).ok) alert((d.data || d).error || `${action} failed`)
      refetch()
    } catch { alert('Network error') }
    setActing(s => { const n = { ...s }; delete n[id]; return n })
  }, [refetch])

  const allProposals = data?.proposals ?? []
  const pending = allProposals.filter((p: any) => p.status === 'PENDING')
  const displayed = showAll ? pending : pending.slice(0, 5)

  return (
    <>
      <PageHeader title="Paper Proposals" subtitle={`${pending.length} pending`} actions={
        <div style={{ display: 'flex', gap: 8 }}>
          <button onClick={() => setShowAll(!showAll)} style={{ padding: '4px 10px', fontSize: 10, background: showAll ? 'rgba(59,130,246,0.2)' : 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 6, color: showAll ? '#60A5FA' : 'var(--text2)', cursor: 'pointer' }}>
            {showAll ? `All (${pending.length})` : `Top 5`}
          </button>
          <button onClick={refetch} style={{ padding: '4px 10px', fontSize: 10, background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 6, color: 'var(--text2)', cursor: 'pointer' }}>Refresh</button>
        </div>
      } />

      {/* Run health banner */}
      {runHealth?.latest_run && (
        <div style={{
          padding: '6px 14px', marginBottom: 10, borderRadius: 6, fontSize: 11, fontWeight: 600,
          background: runHealth.latest_run.status === 'RUN_HEALTHY' ? 'rgba(34,197,94,0.08)' : 'rgba(245,158,11,0.08)',
          border: `1px solid ${runHealth.latest_run.status === 'RUN_HEALTHY' ? 'rgba(34,197,94,0.25)' : 'rgba(245,158,11,0.25)'}`,
          color: runHealth.latest_run.status === 'RUN_HEALTHY' ? '#4ADE80' : '#FBBF24',
        }}>
          Latest run: {runHealth.latest_run.run_label} &middot; {runHealth.latest_run.symbols_scanned} symbols &middot; {runHealth.latest_run.go_count} GO &middot; {runHealth.strategy_signals?.today_count ?? 0} signals &middot; {runHealth.trade_plans?.planned ?? 0} planned
          {runHealth.paper_proposals?.blocked_reasons?.length > 0 && (
            <span style={{ color: '#F87171', marginLeft: 8 }}>&middot; {runHealth.paper_proposals.blocked_reasons.join('; ')}</span>
          )}
        </div>
      )}
      {displayed.length === 0 ? (
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 8, padding: 24, textAlign: 'center', color: 'var(--text3)', fontSize: 12 }}>
          No pending proposals.
          {runHealth?.latest_run ? (
            <div style={{ marginTop: 8, fontSize: 10, color: '#64748B', lineHeight: 1.6 }}>
              <div>Latest run: {runHealth.latest_run.run_label} &middot; {runHealth.latest_run.status} &middot; {runHealth.latest_run.symbols_scanned} scanned &middot; {runHealth.latest_run.go_count} GO &middot; {runHealth.strategy_signals?.today_count ?? 0} signals &middot; {runHealth.trade_plans?.planned ?? 0} planned</div>
              {runHealth.auto_proposals ? (
                <div style={{ marginTop: 4 }}>
                  Auto proposal stage: {runHealth.auto_proposals.proposals_created ?? 0} created &middot; {runHealth.auto_proposals.proposals_skipped ?? 0} skipped
                  {runHealth.auto_proposals.reason_summary && Object.keys(runHealth.auto_proposals.reason_summary).length > 0 && (
                    <span> &middot; {Object.entries(runHealth.auto_proposals.reason_summary).map(([k, v]) => `${v} ${k}`).join(', ')}</span>
                  )}
                </div>
              ) : (
                <div style={{ marginTop: 4, color: '#94A3B8' }}>Auto proposal stage has not run yet. Use Strategy Desk to create proposals manually.</div>
              )}
              {runHealth.paper_proposals?.blocked_reasons?.length > 0 && (
                <div style={{ color: '#F59E0B', marginTop: 4 }}>{runHealth.paper_proposals.blocked_reasons.join('. ')}</div>
              )}
            </div>
          ) : (
            <div style={{ marginTop: 6, fontSize: 10, color: '#94A3B8' }}>
            The system generates proposals automatically when GO signals appear in the morning scan.{' '}
            <a href="/v2/strategy-desk" style={{ color: '#60A5FA' }}>View Strategy Desk</a>
          </div>
          )}
        </div>
      ) : displayed.map((p: any) => (
        <ProposalCard key={p.id} p={p} act={act} acting={acting} />
      ))}
    </>
  )
}
