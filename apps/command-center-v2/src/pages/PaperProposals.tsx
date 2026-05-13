import React, { useState, useCallback } from 'react'
import PageHeader from '../components/PageHeader'
import { useApi } from '../hooks/useApi'

const mono: React.CSSProperties = { fontFamily: 'monospace' }

// ── Style helpers ──────────────────────────────────────────────────────
const lbl: React.CSSProperties = { fontSize: 8, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '0.3px' }
const secLbl: React.CSSProperties = { fontSize: 10, color: 'var(--text3)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: 6, marginTop: 14 }
const pill = (color: string): React.CSSProperties => ({
  fontSize: 9, padding: '2px 6px', borderRadius: 4, fontWeight: 600,
  background: color === 'green' ? 'rgba(34,197,94,0.15)' : color === 'red' ? 'rgba(239,68,68,0.15)' : color === 'blue' ? 'rgba(59,130,246,0.15)' : 'rgba(251,191,36,0.15)',
  color: color === 'green' ? 'var(--green)' : color === 'red' ? 'var(--red)' : color === 'blue' ? '#60A5FA' : 'var(--amber)',
})
const btnStyle = (bg: string, color: string = '#fff'): React.CSSProperties => ({
  padding: '5px 12px', fontSize: 10, fontWeight: 600, border: 'none', borderRadius: 5, cursor: 'pointer', color, background: bg,
})
const inputStyle: React.CSSProperties = {
  width: '100%', padding: '3px 5px', fontSize: 11, ...mono,
  background: 'var(--bg0)', border: '1px solid var(--border)', borderRadius: 4,
  color: 'var(--text0)', fontWeight: 600, textAlign: 'right',
}
const kv = (label: string, value: any, color?: string) => (
  <div key={label}>
    <div style={lbl}>{label}</div>
    <div style={{ fontSize: 11, color: color || 'var(--text0)', fontWeight: 600, ...mono }}>{value ?? '--'}</div>
  </div>
)

// ── Action-state color map ─────────────────────────────────────────────
const ACTION_COLORS: Record<string, { bg: string; text: string; border: string }> = {
  PAPER_READY:   { bg: 'rgba(34,197,94,0.15)',  text: 'var(--green)', border: 'rgba(34,197,94,0.35)' },
  CAUTION:       { bg: 'rgba(251,191,36,0.12)', text: '#F59E0B',     border: 'rgba(251,191,36,0.3)' },
  BLOCKED:       { bg: 'rgba(239,68,68,0.15)',  text: 'var(--red)',   border: 'rgba(239,68,68,0.3)' },
  NEEDS_REVIEW:  { bg: 'rgba(59,130,246,0.15)', text: '#60A5FA',     border: 'rgba(59,130,246,0.3)' },
  MISSING_DATA:  { bg: 'rgba(148,163,184,0.15)',text: '#94A3B8',     border: 'rgba(148,163,184,0.3)' },
  LEARNING_MODE: { bg: 'rgba(251,191,36,0.12)', text: '#F59E0B',     border: 'rgba(251,191,36,0.3)' },
}

// ── Normalizer ─────────────────────────────────────────────────────────
const KEY_FIELDS = [
  'catalyst', 'catalyst_confidence', 'technical_context', 'technical_snapshot',
  'agent_reviews', 'llm_analysis', 'backtest_summary', 'execution_readiness',
  'strategy_fit', 'proposed_entry', 'proposed_stop', 'proposed_target1',
  'proposed_shares', 'signal_score', 'signal_grade', 'news',
]

const MISSING_SECTIONS: Record<string, string> = {
  catalyst: 'Catalyst', catalyst_confidence: 'Catalyst', catalyst_quality: 'Catalyst',
  technical_context: 'Technical', technical_snapshot: 'Technical', technical_summary: 'Technical',
  agent_reviews: 'Agent/LLM', llm_analysis: 'Agent/LLM', agent_votes: 'Agent/LLM',
  backtest_summary: 'Backtest', execution_readiness: 'Execution',
  strategy_fit: 'Execution', proposed_entry: 'Critical', proposed_stop: 'Critical',
  proposed_target1: 'Critical', proposed_shares: 'Critical',
  signal_score: 'Critical', signal_grade: 'Critical', news: 'Catalyst',
}

function normalizeProposal(p: any) {
  const er = p.execution_readiness || {}
  const missingData: string[] = Array.isArray(p.missing_data) ? p.missing_data : []
  const blockers: string[] = Array.isArray(er.blockers) ? er.blockers : []

  // actionState
  let actionState = 'CAUTION'
  const readinessState = String(er.readiness_state || '').toUpperCase()
  if (readinessState.includes('BLOCKED')) {
    actionState = 'BLOCKED'
  } else if (missingData.length >= 4 && !readinessState.includes('BLOCKED')) {
    actionState = 'MISSING_DATA'
  } else if (readinessState === 'READY_FOR_PAPER_SUBMIT' || readinessState === 'READY_ORB_CONFIRMED') {
    // Check all gates
    const riskOk = er.risk_gate_ok !== false
    const priceOk = er.price_ok !== false
    const quoteOk = er.quote_fresh !== false
    const dupOk = er.duplicate_ok !== false
    if (riskOk && priceOk && quoteOk && dupOk && blockers.length === 0) {
      actionState = 'PAPER_READY'
    }
  } else if (p.lifecycle_status === 'NEEDS_REVIEW' || p.decision_state === 'AI_REVIEW_MISSING') {
    actionState = 'NEEDS_REVIEW'
  } else if (p.decision_state === 'CAUTIOUS_PAPER_TEST' && p.paper_ready) {
    actionState = 'LEARNING_MODE'
  }

  // topBlocker
  const topBlocker = blockers.length > 0 ? blockers[0] : 'None'

  // primaryStrategy: use strategy_id
  const primaryStrategy = p.strategy_id || 'unknown'
  const strategyMismatch = p.primary_strategy_id != null && p.primary_strategy_id !== p.strategy_id

  // nextActions
  const nextActions: string[] = []
  const _nTc = typeof p.technical_context === 'string' ? JSON.parse(p.technical_context || '{}') : (p.technical_context || {})
  const _nTs = p.technical_snapshot || {}
  if (!(_nTs.rsi_14 ?? _nTc.rsi) && !(_nTs.atr_14 ?? _nTc.atr)) nextActions.push('Run Technical Snapshot')
  if (!p.agent_reviews?.length && !p.llm_analysis) nextActions.push('Run AI Review')
  if (!p.catalyst || !p.news?.length) nextActions.push('Run Research')
  if (!p.execution_readiness) nextActions.push('Check Execution Readiness')
  if (er.quote_age_seconds != null && Number(er.quote_age_seconds) > 300) nextActions.push('Check Execution during market hours')
  if (!p.backtest_summary) nextActions.push('Run Backtest')

  // dataCompleteness
  let filledCount = 0
  for (const f of KEY_FIELDS) {
    const v = p[f]
    if (v != null && v !== '' && !(Array.isArray(v) && v.length === 0) && !(typeof v === 'object' && !Array.isArray(v) && Object.keys(v).length === 0)) {
      filledCount++
    }
  }
  const dataCompleteness = Math.round((filledCount / KEY_FIELDS.length) * 100)

  // missingBySection
  const missingBySection: Record<string, string[]> = {}
  for (const item of missingData) {
    // Try to match to a known section
    let section = 'Other'
    const lower = item.toLowerCase()
    if (lower.includes('catalyst') || lower.includes('news')) section = 'Catalyst'
    else if (lower.includes('technical') || lower.includes('atr') || lower.includes('rsi') || lower.includes('vwap') || lower.includes('ema')) section = 'Technical'
    else if (lower.includes('agent') || lower.includes('llm') || lower.includes('review')) section = 'Agent/LLM'
    else if (lower.includes('backtest')) section = 'Backtest'
    else if (lower.includes('execution') || lower.includes('quote') || lower.includes('readiness')) section = 'Execution'
    else if (lower.includes('entry') || lower.includes('stop') || lower.includes('target') || lower.includes('shares') || lower.includes('score') || lower.includes('grade')) section = 'Critical'
    if (!missingBySection[section]) missingBySection[section] = []
    missingBySection[section].push(item)
  }

  return { actionState, topBlocker, primaryStrategy, strategyMismatch, nextActions, dataCompleteness, missingBySection }
}

// ── Metric tile component ──────────────────────────────────────────────
function MetricTile({ label, value, status, tileColor, onClick }: {
  label: string; value: string; status: string; tileColor: 'green' | 'amber' | 'red' | 'gray'; onClick?: () => void
}) {
  const colors = {
    green: { bg: 'rgba(34,197,94,0.08)', border: 'rgba(34,197,94,0.25)', text: 'var(--green)', hover: 'rgba(34,197,94,0.14)' },
    amber: { bg: 'rgba(251,191,36,0.08)', border: 'rgba(251,191,36,0.25)', text: '#F59E0B', hover: 'rgba(251,191,36,0.14)' },
    red:   { bg: 'rgba(239,68,68,0.08)',  border: 'rgba(239,68,68,0.25)',  text: 'var(--red)', hover: 'rgba(239,68,68,0.14)' },
    gray:  { bg: 'rgba(148,163,184,0.06)',border: 'rgba(148,163,184,0.15)',text: '#94A3B8', hover: 'rgba(148,163,184,0.12)' },
  }
  const c = colors[tileColor]
  const [hovered, setHovered] = React.useState(false)
  return (
    <div
      onClick={onClick}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        padding: '6px 8px', background: hovered ? c.hover : c.bg,
        border: `1px solid ${hovered ? c.text : c.border}`,
        borderRadius: 6, textAlign: 'center', minWidth: 0,
        cursor: onClick ? 'pointer' : 'default',
        transition: 'background 0.15s, border-color 0.15s',
      }}>
      <div style={{ fontSize: 7, color: hovered ? c.text : 'var(--text3)', textTransform: 'uppercase', letterSpacing: '0.3px', marginBottom: 2, transition: 'color 0.15s' }}>{label}</div>
      <div style={{ fontSize: 13, fontWeight: 700, color: c.text, ...mono }}>{value}</div>
      <div style={{ fontSize: 8, color: hovered ? 'var(--text2)' : 'var(--text3)', marginTop: 2, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', transition: 'color 0.15s' }}>{status}</div>
    </div>
  )
}

// ── Confirm modal ──────────────────────────────────────────────────────
function ConfirmModal({ p, onConfirm, onCancel }: { p: any; onConfirm: () => void; onCancel: () => void }) {
  const reasons = p.approval_blocked_reason ? p.approval_blocked_reason.split(';').map((r: string) => r.trim()) : ['Non-standard approval']
  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 }}>
      <div style={{ background: 'var(--bg1)', borderRadius: 12, padding: 24, maxWidth: 420, width: '90%', border: '1px solid var(--border)' }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 12 }}>This is not an approve-ready proposal.</div>
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

// ── Proposal card ──────────────────────────────────────────────────────
function ProposalCard({ p, act, acting }: { p: any; act: (id: number, action: string, overrides?: any) => void; acting: Record<number, string> }) {
  const [editing, setEditing] = useState(false)
  const [shares, setShares] = useState(p.proposed_shares || 0)
  const [entry, setEntry] = useState(p.proposed_entry || 0)
  const [stop, setStop] = useState(p.proposed_stop || 0)
  const [target, setTarget] = useState(p.proposed_target1 || 0)
  const [activeTab, setActiveTab] = useState('summary')
  const [showConfirm, setShowConfirm] = useState(false)
  const [runningAction, setRunningAction] = useState<string | null>(null)
  const [showAllSetups, setShowAllSetups] = useState(false)

  const norm = normalizeProposal(p)
  const ac = ACTION_COLORS[norm.actionState] || ACTION_COLORS.CAUTION

  const riskPS = Math.abs(entry - stop)
  const computedRisk = riskPS * shares
  const computedRR = riskPS > 0 ? (target - entry) / riskPS : 0
  const computedReward = (target - entry) * shares
  const isModified = shares !== (p.proposed_shares || 0) || entry !== (p.proposed_entry || 0) || stop !== (p.proposed_stop || 0) || target !== (p.proposed_target1 || 0)

  const cd = p.minutes_remaining != null ? {
    color: p.minutes_remaining > 90 ? 'var(--green)' : p.minutes_remaining > 30 ? 'var(--amber)' : 'var(--red)',
    text: p.minutes_remaining > 60 ? `${Math.floor(p.minutes_remaining / 60)}h ${p.minutes_remaining % 60}m` : `${p.minutes_remaining}m`,
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
    { key: 'strategy', label: 'Strategy' },
    { key: 'risk', label: 'Risk/Reward' },
    { key: 'execution', label: 'Execution' },
    { key: 'agents', label: 'Agents' },
    { key: 'missing', label: 'Missing' },
  ]

  // ── Build metric tiles ──
  const er = p.execution_readiness || {}
  const _tcRaw = typeof p.technical_context === 'string' ? JSON.parse(p.technical_context || '{}') : (p.technical_context || {})
  const _tsSnap = p.technical_snapshot || {}
  // Merge: technical_snapshot has fresher data than technical_context
  const tc = {
    ..._tcRaw,
    rsi: _tsSnap.rsi_14 ?? _tcRaw.rsi,
    rsi_state: _tsSnap.rsi_14 != null ? (Number(_tsSnap.rsi_14) >= 70 ? 'overbought' : Number(_tsSnap.rsi_14) <= 30 ? 'oversold' : Number(_tsSnap.rsi_14) >= 55 ? 'bullish momentum' : 'neutral') : _tcRaw.rsi_state,
    atr: _tsSnap.atr_14 ?? _tcRaw.atr,
    atr_pct: _tsSnap.atr_pct ?? _tcRaw.atr_pct,
    vwap: _tsSnap.vwap ?? _tcRaw.vwap,
    vwap_distance_pct: _tsSnap.vwap_distance_pct ?? _tcRaw.vwap_distance_pct,
    vwap_state: _tsSnap.vwap_distance_pct != null ? (Number(_tsSnap.vwap_distance_pct) > 3 ? 'extended above VWAP' : Number(_tsSnap.vwap_distance_pct) > 0 ? 'above VWAP' : 'below VWAP') : _tcRaw.vwap_state,
    adx: _tsSnap.adx ?? _tcRaw.adx,
    adx_regime: _tsSnap.adx_regime ?? _tcRaw.adx_regime,
    trend_strength: _tsSnap.adx_regime ?? _tcRaw.trend_strength,
    rvol: _tcRaw.rvol ?? p.rvol,
    rvol_state: _tcRaw.rvol_state ?? (p.rvol ? (Number(p.rvol) >= 5 ? 'explosive' : Number(p.rvol) >= 2 ? 'high' : 'normal') : undefined),
    ema_alignment: _tsSnap.ema_alignment ?? _tcRaw.ema_alignment,
    technical_grade: _tsSnap.technical_grade ?? _tcRaw.technical_grade,
    float_rotation_state: _tcRaw.float_rotation_state,
    gap_pct: _tcRaw.gap_pct ?? p.gap_pct,
    gap_state: _tcRaw.gap_state,
  }
  const bt = typeof p.backtest_summary === 'string' ? JSON.parse(p.backtest_summary || '{}') : (p.backtest_summary || {})
  const sf = p.strategy_fit || {}
  const agentReviews = (p.agent_reviews || []).filter((ar: any) => ar.verdict)
  const rr = p.proposed_rr || (riskPS > 0 ? (target - entry) / riskPS : 0)

  const ts = p.technical_snapshot || {}
  const tiles: { label: string; value: string; status: string; tileColor: 'green' | 'amber' | 'red' | 'gray'; tab: string }[] = [
    {
      label: 'Strategy Fit',
      value: sf.fit_score != null ? `${sf.fit_score}` : '--',
      status: sf.fit_grade || (sf.fit_score != null ? (sf.fit_score >= 80 ? 'Strong fit' : sf.fit_score >= 60 ? 'Good fit' : 'Weak fit') : 'Run analysis'),
      tileColor: sf.fit_score >= 80 ? 'green' : sf.fit_score >= 60 ? 'amber' : sf.fit_score != null ? 'red' : 'gray',
      tab: 'strategy',
    },
    {
      label: 'Execution',
      value: er.readiness_score != null ? `${er.readiness_score}` : '--',
      status: er.readiness_state ? er.readiness_state.replace(/^BLOCKED_/, '').replace(/_/g, ' ').slice(0, 18) : 'Check readiness',
      tileColor: er.readiness_state === 'READY_FOR_PAPER_SUBMIT' || er.readiness_state === 'READY_ORB_CONFIRMED' ? 'green' : er.readiness_state === 'CAUTION_EXECUTABLE' ? 'amber' : er.readiness_state ? 'red' : 'gray',
      tab: 'execution',
    },
    {
      label: 'Technical',
      value: ts.technical_grade || (ts.rsi_14 != null ? 'OK' : '--'),
      status: ts.rsi_14 != null ? `RSI ${Number(ts.rsi_14).toFixed(0)} ATR $${Number(ts.atr_14 || 0).toFixed(2)}` : 'Run snapshot',
      tileColor: ts.technical_grade === 'TECH_STRONG' ? 'green' : ts.technical_grade === 'TECH_OK' || ts.technical_grade === 'TECH_MIXED' ? 'amber' : ts.rsi_14 != null ? 'amber' : 'gray',
      tab: 'technical',
    },
    {
      label: 'Catalyst',
      value: p.catalyst_quality?.catalyst_quality_score != null ? `${p.catalyst_quality.catalyst_quality_score}%` : p.catalyst_verified ? 'Yes' : '--',
      status: p.catalyst_quality?.catalyst_grade || (p.catalyst_verified ? `Verified${p.catalyst ? '' : ''}` : 'Unverified'),
      tileColor: p.catalyst_quality?.catalyst_quality_score >= 70 ? 'green' : p.catalyst_verified ? 'green' : p.catalyst ? 'amber' : 'gray',
      tab: 'catalyst',
    },
    {
      label: 'R:R',
      value: rr > 0 ? `${Number(rr).toFixed(1)}:1` : '--',
      status: rr >= 2.5 ? 'Excellent' : rr >= 2 ? 'Meets 2:1 min' : rr > 0 ? 'Below 2:1 min' : 'Not set',
      tileColor: rr >= 2.5 ? 'green' : rr >= 2 ? 'green' : rr > 0 ? 'red' : 'gray',
      tab: 'risk',
    },
    {
      label: 'Agents',
      value: agentReviews.length > 0 ? `${agentReviews.length}` : '--',
      status: agentReviews.length > 0
        ? `${agentReviews.filter((a: any) => a.verdict?.includes('CAUTIOUS') || a.verdict?.includes('APPROVE')).length}/${agentReviews.length} cautious+`
        : 'Run AI review',
      tileColor: agentReviews.length >= 3 ? 'green' : agentReviews.length > 0 ? 'amber' : 'gray',
      tab: 'agents',
    },
    {
      label: 'Backtest',
      value: bt.sample_size ? `n=${bt.sample_size}` : '--',
      status: bt.sample_size >= 20 ? `${(Number(bt.win_rate || 0) * 100).toFixed(0)}% WR` : bt.sample_size ? 'Learning mode' : 'Run backtest',
      tileColor: bt.sample_size >= 20 && Number(bt.win_rate || 0) >= 0.55 ? 'green' : bt.sample_size ? 'amber' : 'gray',
      tab: 'risk',
    },
    {
      label: 'Data',
      value: `${norm.dataCompleteness}%`,
      status: (p.missing_data || []).length > 0 ? `${(p.missing_data || []).length} gaps` : 'Complete',
      tileColor: norm.dataCompleteness >= 90 ? 'green' : norm.dataCompleteness >= 70 ? 'amber' : norm.dataCompleteness > 0 ? 'red' : 'gray',
      tab: 'missing',
    },
  ]

  // Session 26: Use server-side action_state when available
  const effectiveActionState = p.action_state || norm.actionState
  const effectiveTopBlocker = p.top_blocker || norm.topBlocker
  const effectiveNextActions: string[] = p.next_actions || norm.nextActions
  const packetPct = p.packet_completion_pct || norm.dataCompleteness

  // ── Build decision banner text ──
  let bannerText = ''
  let bannerDetail = ''
  if (effectiveActionState === 'BLOCKED') {
    bannerText = `BLOCKED — ${effectiveTopBlocker}`
    bannerDetail = effectiveNextActions.length > 0 ? `Next: ${effectiveNextActions[0]}` : ''
  } else if (effectiveActionState === 'PAPER_READY') {
    bannerText = 'PAPER READY — All gates pass. Review thesis before submitting.'
    bannerDetail = ''
  } else if (effectiveActionState === 'MISSING_DATA') {
    bannerText = `MISSING DATA — ${p.action_label || `${(p.missing_data || []).length} fields missing`}`
    bannerDetail = effectiveNextActions.length > 0 ? `Next: ${effectiveNextActions.join(', ')}` : ''
  } else if (effectiveActionState === 'NEEDS_REVIEW') {
    bannerText = `NEEDS REVIEW — ${p.action_label || 'Agent or data review pending'}`
    bannerDetail = norm.nextActions.length > 0 ? `Next: ${norm.nextActions[0]}` : ''
  } else if (norm.actionState === 'LEARNING_MODE') {
    bannerText = 'LEARNING MODE — Cautious paper test, not fully validated'
    bannerDetail = ''
  } else {
    bannerText = `CAUTION — ${norm.topBlocker !== 'None' ? norm.topBlocker : 'Review data before proceeding'}`
    bannerDetail = norm.nextActions.length > 0 ? `Next: ${norm.nextActions[0]}` : ''
  }

  return (
    <div style={{
      background: 'var(--bg1)', borderRadius: 8, marginBottom: 14,
      border: `1px solid ${ac.border}`,
      borderLeft: `4px solid ${
        p.operator_verdict_color === 'green' ? '#10B981'
        : p.operator_verdict_color === 'red' ? '#EF4444'
        : p.operator_verdict_color === 'orange' ? '#F97316'
        : p.operator_verdict_color === 'yellow' ? '#F59E0B'
        : '#334155'
      }`,
      opacity: p.operator_verdict === 'ENTRY_MISSED' ? 0.65 : 1,
    }}>
      {showConfirm && <ConfirmModal p={p} onConfirm={handleConfirmApprove} onCancel={() => setShowConfirm(false)} />}

      {/* ── Header with operator verdict ── */}
      <div style={{ padding: '10px 16px', borderBottom: '1px solid var(--border)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 6 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            {/* Operator verdict badge */}
            {p.operator_verdict && (() => {
              const vc: Record<string, { bg: string; text: string; icon: string }> = {
                READY: { bg: 'rgba(34,197,94,0.2)', text: '#22C55E', icon: '\u2705' },
                NEEDS_REVIEW: { bg: 'rgba(251,191,36,0.15)', text: '#F59E0B', icon: '\u26a0\ufe0f' },
                STALE_QUOTE: { bg: 'rgba(249,115,22,0.15)', text: '#F97316', icon: '\ud83d\udd70' },
                ENTRY_MISSED: { bg: 'rgba(239,68,68,0.15)', text: '#EF4444', icon: '\u26d4' },
              }
              const v = vc[p.operator_verdict] || vc.NEEDS_REVIEW
              return <span style={{ fontSize: 9, fontWeight: 700, padding: '3px 8px', borderRadius: 4, background: v.bg, color: v.text }}>{v.icon} {p.operator_verdict.replace(/_/g, ' ')}</span>
            })()}
            <span style={{ fontSize: 18, fontWeight: 800, color: 'var(--text0)', ...mono }}>{p.symbol}</span>
            {p.signal_grade && <span style={pill(p.signal_grade === 'A' || p.signal_grade === 'A+' ? 'green' : p.signal_grade === 'B' ? 'amber' : 'red')}>{p.signal_grade}</span>}
            {p.signal_score != null && <span style={{ fontSize: 10, color: 'var(--text2)', ...mono }}>{p.signal_score}pts</span>}
            <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)' }}>{norm.primaryStrategy}</span>
            {/* Strategy win rate */}
            {p.strategy_trade_count > 0 && (
              <span style={{ fontSize: 9, color: (p.strategy_win_rate ?? 0) >= 50 ? 'var(--green)' : 'var(--amber)', fontWeight: 600 }}>
                {p.strategy_win_rate}% WR ({p.strategy_trade_count} trades)
              </span>
            )}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            {/* Age display */}
            {p.age_display && (
              <span style={{ fontSize: 9, fontWeight: 600, ...mono,
                color: p.age_color === 'green' ? '#22C55E' : p.age_color === 'red' ? '#EF4444' : '#F59E0B'
              }}>{p.age_display}</span>
            )}
            <LifecycleBadge status={p.lifecycle_status || p.entry_zone_status || 'ACTIVE'} riskGateResult={p.risk_gate_result} />
          </div>
        </div>
        {/* Verdict reason */}
        {p.operator_verdict_reason && (
          <div style={{ fontSize: 10, color: 'var(--text2)', marginTop: 4 }}>{p.operator_verdict_reason}</div>
        )}
      </div>

      {/* ── Pipeline chevron (always visible) ── */}
      <PipelineChevron stages={p.pipeline_stages || []} />

      {/* Session 26: Packet progress bar */}
      {packetPct > 0 && (
        <div style={{ padding: '4px 16px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 8, color: 'var(--text3)', textTransform: 'uppercase', minWidth: 55 }}>Packet {packetPct}%</span>
          <div style={{ flex: 1, height: 4, background: 'var(--bg0)', borderRadius: 2, overflow: 'hidden' }}>
            <div style={{ width: `${Math.min(packetPct, 100)}%`, height: '100%', borderRadius: 2,
              background: packetPct >= 80 ? '#22C55E' : packetPct >= 50 ? '#F59E0B' : '#EF4444',
              transition: 'width 0.3s' }} />
          </div>
          {p.llm_review_status && p.llm_review_status !== 'COMPLETE' && (
            <span style={{ fontSize: 8, color: '#A855F7', fontWeight: 600 }}>LLM: {p.llm_review_status}</span>
          )}
        </div>
      )}

      {/* ── Blocker/status banner ── */}
      <BlockerBanner p={p} norm={norm} />

      {/* ── Simplified 3-badge row + full details toggle ── */}
      <div style={{ padding: '8px 16px', borderBottom: '1px solid var(--border)', display: 'flex', gap: 8, alignItems: 'center' }}>
        {/* DATA badge */}
        {(() => {
          const dc = norm.dataCompleteness
          const c = dc >= 80 ? '#22C55E' : dc >= 60 ? '#F59E0B' : '#EF4444'
          return <span style={{ fontSize: 9, fontWeight: 700, padding: '3px 8px', borderRadius: 4, background: `${c}20`, color: c }}>DATA {dc}%</span>
        })()}
        {/* ANALYSIS badge */}
        {(() => {
          const hasLLM = p.llm_review_status === 'COMPLETE'
          const hasFallback = p.agent_review_status === 'deterministic_fallback'
          const c = hasLLM ? '#22C55E' : hasFallback ? '#F59E0B' : '#EF4444'
          const t = hasLLM ? 'LLM' : hasFallback ? 'FALLBACK' : 'NONE'
          return <span style={{ fontSize: 9, fontWeight: 700, padding: '3px 8px', borderRadius: 4, background: `${c}20`, color: c }}>ANALYSIS {t}</span>
        })()}
        {/* EXECUTION badge */}
        {(() => {
          const erS = (er.readiness_state || '').toUpperCase()
          const c = erS.includes('READY') ? '#22C55E' : erS.includes('CAUTION') ? '#F59E0B' : erS ? '#EF4444' : '#64748B'
          const t = erS.includes('READY') ? 'READY' : erS.includes('BLOCKED') ? 'BLOCKED' : erS.includes('MISSED') ? 'MISSED' : erS ? 'CHECK' : 'PENDING'
          return <span style={{ fontSize: 9, fontWeight: 700, padding: '3px 8px', borderRadius: 4, background: `${c}20`, color: c }}>EXEC {t}</span>
        })()}
        <div style={{ flex: 1 }} />
        <button onClick={() => setActiveTab(activeTab === 'details_full' ? 'summary' : 'details_full')}
          style={{ fontSize: 9, padding: '2px 8px', background: 'none', border: '1px solid var(--border)', borderRadius: 4, color: 'var(--text3)', cursor: 'pointer' }}>
          {activeTab === 'details_full' ? '\u25b2 Hide Details' : '\u25bc Full Details'}
        </button>
      </div>

      {/* ── Full metric tiles (collapsible) ── */}
      {activeTab === 'details_full' && (
        <div style={{ padding: '8px 16px', borderBottom: '1px solid var(--border)', display: 'grid', gridTemplateColumns: 'repeat(8, 1fr)', gap: 4 }}>
          {tiles.map(t => <MetricTile key={t.label} label={t.label} value={t.value} status={t.status} tileColor={t.tileColor} onClick={() => setActiveTab(t.tab)} />)}
        </div>
      )}

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

        {/* ── Summary tab ── */}
        {activeTab === 'summary' && (
          <>
            {p.recently_rejected && (
              <div style={{ padding: '6px 10px', marginBottom: 8, borderRadius: 6, fontSize: 10, fontWeight: 600, background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.2)', color: '#F87171' }}>
                Recently rejected: {p.rejection_reason || 'Unknown reason'}{p.rejection_cooldown_until && ` -- cooldown until ${new Date(p.rejection_cooldown_until).toLocaleString()}`}
              </div>
            )}

            {norm.strategyMismatch && (
              <div style={{ padding: '6px 10px', marginBottom: 8, borderRadius: 6, fontSize: 10, fontWeight: 600, background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.2)', color: '#F87171' }}>
                Strategy mismatch: strategy_id="{p.strategy_id}" but primary_strategy_id="{p.primary_strategy_id}". Using strategy_id as primary.
              </div>
            )}

            {/* Decision Summary — 3 tiles */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8, marginBottom: 12 }}>
              <div style={{ padding: '10px 12px', borderRadius: 6, textAlign: 'center',
                background: (p.entry_zone_status || p.lifecycle_status || '') === 'ENTRY_ZONE_VALID' ? '#052E16' : (p.entry_zone_status || p.lifecycle_status || '') === 'ENTRY_MISSED' ? '#1C0A00' : '#0A1628',
                border: `1px solid ${(p.entry_zone_status || p.lifecycle_status || '') === 'ENTRY_ZONE_VALID' ? '#065F46' : (p.entry_zone_status || p.lifecycle_status || '') === 'ENTRY_MISSED' ? '#92400E' : '#1E293B'}` }}>
                <div style={{ color: '#64748B', fontSize: 9, textTransform: 'uppercase', letterSpacing: 1 }}>Entry Zone</div>
                <div style={{ fontSize: 14, fontWeight: 700, marginTop: 4,
                  color: (p.entry_zone_status || p.lifecycle_status || '') === 'ENTRY_ZONE_VALID' ? '#10B981' : (p.entry_zone_status || p.lifecycle_status || '') === 'ENTRY_MISSED' ? '#F59E0B' : '#60A5FA' }}>
                  {(p.entry_zone_status || p.lifecycle_status || '')?.replace(/_/g, ' ') || 'Unknown'}
                </div>
                {p.price_drift_pct != null && <div style={{ color: '#475569', fontSize: 10, marginTop: 2 }}>{p.price_drift_pct > 0 ? '+' : ''}{p.price_drift_pct.toFixed(1)}% from entry</div>}
              </div>
              <div style={{ padding: '10px 12px', borderRadius: 6, textAlign: 'center',
                background: (p.proposed_rr || 0) >= 2.0 ? '#052E16' : '#1C0A00',
                border: `1px solid ${(p.proposed_rr || 0) >= 2.0 ? '#065F46' : '#92400E'}` }}>
                <div style={{ color: '#64748B', fontSize: 9, textTransform: 'uppercase', letterSpacing: 1 }}>Risk / Reward</div>
                <div style={{ fontSize: 14, fontWeight: 700, marginTop: 4,
                  color: (p.proposed_rr || 0) >= 2.0 ? '#10B981' : '#F59E0B' }}>
                  {p.proposed_rr ? `${Number(p.proposed_rr).toFixed(1)}:1` : '--'}
                </div>
                <div style={{ color: '#475569', fontSize: 10, marginTop: 2 }}>{(p.proposed_rr || 0) < 2.0 ? 'Below 2:1 minimum' : 'Meets minimum'}</div>
              </div>
              <div style={{ padding: '10px 12px', borderRadius: 6, textAlign: 'center', background: '#0A1628', border: '1px solid #1E293B' }}>
                <div style={{ color: '#64748B', fontSize: 9, textTransform: 'uppercase', letterSpacing: 1 }}>Agent Consensus</div>
                <div style={{ fontSize: 14, fontWeight: 700, marginTop: 4, color: '#818CF8' }}>
                  {(() => {
                    const revs = (p.agent_reviews || []).filter((r: any) => r.verdict)
                    return revs.length > 0 ? `${revs.length} reviews` : 'None yet'
                  })()}
                </div>
                <div style={{ color: '#475569', fontSize: 10, marginTop: 2 }}>
                  {(p.agent_reviews || []).filter((r: any) => r.verdict?.includes('CAUTIOUS') || r.verdict?.includes('APPROVE')).length} cautious/approve
                </div>
              </div>
            </div>

            {/* AI Review Needed banner */}
            {(!p.llm_analysis?.conviction || p.narrative_source === 'deterministic_fallback') && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '6px 12px', marginBottom: 8,
                background: '#1C1917', border: '1px solid #44403C', borderRadius: 4 }}>
                <span style={{ color: '#78716C', fontSize: 11 }}>AI analysis is fallback — not yet reviewed by local LLM</span>
                <button onClick={() => runAction('agent', '/api/v2/paper-proposals/run-agent-review')}
                  disabled={!!runningAction} style={{ background: '#422006', color: '#F59E0B', border: '1px solid #92400E',
                  borderRadius: 3, padding: '2px 10px', cursor: 'pointer', fontSize: 11 }}>
                  {runningAction === 'agent' ? '...' : 'Run AI Review'}
                </button>
              </div>
            )}

            {/* Setup thesis */}
            <div style={secLbl}>Setup Thesis</div>
            <div style={{ fontSize: 11, color: 'var(--text1)', lineHeight: 1.6, padding: '8px 10px', background: 'var(--bg0)', borderRadius: 6, marginBottom: 8, position: 'relative' }}>
              {(p.agent_narrative || 'No narrative available.').replace(/\s*\(deterministic_fallback\)/g, '').replace(/\s*\(auto-generated\)/g, '')}
              <div style={{ display: 'flex', gap: 4, marginTop: 4 }}>
                {p.narrative_source === 'deterministic_fallback' && (
                  <span style={{ fontSize: 8, padding: '1px 5px', borderRadius: 3, background: 'rgba(148,163,184,0.1)', color: '#64748B', fontWeight: 600 }}>Deterministic fallback</span>
                )}
                {p.narrative_source === 'local_llm' && (
                  <span style={{ fontSize: 8, padding: '1px 5px', borderRadius: 3, background: 'rgba(34,197,94,0.1)', color: 'var(--green)', fontWeight: 600 }}>{p.llm_model_used || 'qwen3:14b'}</span>
                )}
                {p.narrative_source && p.narrative_source !== 'deterministic_fallback' && p.narrative_source !== 'local_llm' && (
                  <span style={{ fontSize: 8, padding: '1px 5px', borderRadius: 3, background: 'rgba(148,163,184,0.1)', color: '#64748B', fontWeight: 600 }}>{p.narrative_source}</span>
                )}
              </div>
            </div>

            {/* Support case / Reject case */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 8 }}>
              <div>
                <div style={secLbl}>Support Case</div>
                <div style={{ fontSize: 10, color: 'var(--green)', lineHeight: 1.5, padding: '6px 8px', background: 'rgba(34,197,94,0.05)', borderRadius: 4, border: '1px solid rgba(34,197,94,0.15)' }}>
                  {(() => {
                    const raw = p.llm_analysis?.approve_case || p.approve_case || 'No support rationale.'
                    const cleaned = raw.replace(/\s*\(deterministic_fallback\)/g, '').replace(/\s*\(auto-generated\)/g, '')
                    const bullets = cleaned.split(/[.;]/).filter((s: string) => s.trim())
                    return bullets.length > 1 ? (
                      <ul style={{ margin: 0, paddingLeft: 14 }}>
                        {bullets.map((b: string, i: number) => <li key={i} style={{ marginBottom: 2 }}>{b.trim()}</li>)}
                      </ul>
                    ) : cleaned
                  })()}
                </div>
              </div>
              <div>
                <div style={secLbl}>Reject Case</div>
                <div style={{ fontSize: 10, color: 'var(--red)', lineHeight: 1.5, padding: '6px 8px', background: 'rgba(239,68,68,0.05)', borderRadius: 4, border: '1px solid rgba(239,68,68,0.15)' }}>
                  {(() => {
                    const raw = p.llm_analysis?.reject_case || p.reject_case || 'No rejection signals.'
                    const cleaned = raw.replace(/\s*\(deterministic_fallback\)/g, '').replace(/\s*\(auto-generated\)/g, '')
                    const bullets = cleaned.split(/[.;]/).filter((s: string) => s.trim())
                    return bullets.length > 1 ? (
                      <ul style={{ margin: 0, paddingLeft: 14 }}>
                        {bullets.map((b: string, i: number) => <li key={i} style={{ marginBottom: 2 }}>{b.trim()}</li>)}
                      </ul>
                    ) : cleaned
                  })()}
                </div>
              </div>
            </div>

            {/* Intelligence + Quality badges */}
            <div style={{ display: 'flex', gap: 8, marginBottom: 8, flexWrap: 'wrap' }}>
              {p.intelligence ? (
                <span style={pill(p.intelligence.intelligence_readiness >= 70 ? 'green' : p.intelligence.intelligence_readiness >= 50 ? 'amber' : 'red')}>
                  Intel: {p.intelligence.intelligence_readiness}/100
                </span>
              ) : (
                <span style={pill('amber')}>Intel: not computed</span>
              )}
              {p.quality_review ? (
                <span style={pill(p.quality_review.review_state === 'HIGH_QUALITY_TEST' ? 'green' : p.quality_review.review_state === 'CAUTIOUS_TEST' ? 'amber' : p.quality_review.review_state === 'REJECT_RECOMMENDED' || p.quality_review.review_state === 'BLOCKED_BY_RISK_GATE' ? 'red' : 'blue')}>
                  Quality: {p.quality_review.review_state} ({(p.quality_review.quality_score * 100).toFixed(0)}%)
                </span>
              ) : (
                <span style={pill('amber')}>Quality review not run</span>
              )}
            </div>

            {/* LLM Analysis */}
            {p.llm_analysis && (
              <>
                <div style={secLbl}>LLM Analysis</div>
                <div style={{ padding: '8px 10px', background: 'var(--bg0)', borderRadius: 6, fontSize: 10, lineHeight: 1.5 }}>
                  <div style={{ color: 'var(--text1)', marginBottom: 4 }}>{p.llm_analysis.summary}</div>
                  <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 4 }}>
                    {p.llm_analysis.narrative_source === 'local_llm' ? (
                      <span style={pill('green')}>LLM: {p.llm_model_used || p.llm_analysis.model_used || 'qwen3:14b'}</span>
                    ) : p.llm_model_used && p.llm_model_used !== 'deterministic_fallback' ? (
                      <span style={pill('yellow')}>Fallback: {p.llm_model_used}</span>
                    ) : (
                      <span style={{ fontSize: 8, padding: '1px 5px', borderRadius: 3, background: 'rgba(148,163,184,0.1)', color: '#64748B', fontWeight: 600 }}>Fallback analysis</span>
                    )}
                    {p.llm_analysis.confidence != null && (
                      <span style={{ fontSize: 9, color: 'var(--text2)', ...mono }}>conf: {(Number(p.llm_analysis.confidence) * 100).toFixed(0)}%</span>
                    )}
                  </div>
                </div>
              </>
            )}

            {/* LLM Chunk Results (risk + catalyst deep-dive) */}
            {p.llm_review_chunks && (p.llm_review_chunks.risk || p.llm_review_chunks.catalyst) && (
              <>
                <div style={secLbl}>AI Deep Dive {p.llm_review_stage === 'catalyst' ? '(4/4 chunks)' : `(${Object.keys(p.llm_review_chunks).length}/4 chunks)`}</div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 8 }}>
                  {p.llm_review_chunks.risk && (
                    <div style={{ padding: '6px 8px', background: 'var(--bg0)', borderRadius: 4, fontSize: 10, lineHeight: 1.5 }}>
                      <div style={{ fontWeight: 600, color: 'var(--text2)', marginBottom: 2 }}>Risk Assessment</div>
                      <span style={pill(p.llm_review_chunks.risk.risk_grade === 'A' || p.llm_review_chunks.risk.risk_grade === 'B' ? 'green' : p.llm_review_chunks.risk.risk_grade === 'C' ? 'amber' : 'red')}>
                        Risk: {p.llm_review_chunks.risk.risk_grade}
                      </span>
                      <div style={{ color: 'var(--text2)', marginTop: 4 }}>{p.llm_review_chunks.risk.position_size_assessment}</div>
                      {p.llm_review_chunks.risk.max_drawdown_scenario && (
                        <div style={{ color: 'var(--red)', marginTop: 2, fontSize: 9 }}>DD: {p.llm_review_chunks.risk.max_drawdown_scenario}</div>
                      )}
                    </div>
                  )}
                  {p.llm_review_chunks.catalyst && (
                    <div style={{ padding: '6px 8px', background: 'var(--bg0)', borderRadius: 4, fontSize: 10, lineHeight: 1.5 }}>
                      <div style={{ fontWeight: 600, color: 'var(--text2)', marginBottom: 2 }}>AI Catalyst Review</div>
                      <span style={pill(p.llm_review_chunks.catalyst.catalyst_grade === 'A' || p.llm_review_chunks.catalyst.catalyst_grade === 'B' ? 'green' : p.llm_review_chunks.catalyst.catalyst_grade === 'C' ? 'amber' : 'red')}>
                        Catalyst: {p.llm_review_chunks.catalyst.catalyst_grade}
                      </span>
                      <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginTop: 4 }}>
                        <span style={{ fontSize: 8, padding: '1px 4px', borderRadius: 2, background: 'rgba(148,163,184,0.1)', color: 'var(--text2)' }}>{p.llm_review_chunks.catalyst.catalyst_type}</span>
                        <span style={{ fontSize: 8, padding: '1px 4px', borderRadius: 2, background: 'rgba(148,163,184,0.1)', color: 'var(--text2)' }}>{p.llm_review_chunks.catalyst.catalyst_freshness}</span>
                        <span style={{ fontSize: 8, padding: '1px 4px', borderRadius: 2, background: 'rgba(148,163,184,0.1)', color: 'var(--text2)' }}>{p.llm_review_chunks.catalyst.catalyst_timing}</span>
                      </div>
                    </div>
                  )}
                </div>
              </>
            )}

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

        {/* ── Technical tab ── */}
        {activeTab === 'technical' && (
          <>
            {/* Technical grade badge */}
            {p.technical_snapshot?.technical_grade && (
              <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 8 }}>
                <span style={pill(p.technical_snapshot.technical_grade === 'TECH_STRONG' ? 'green' : p.technical_snapshot.technical_grade === 'TECH_OK' ? 'blue' : 'amber')}>
                  {p.technical_snapshot.technical_grade}
                </span>
                {p.technical_snapshot.ohlcv_data_status && (
                  <span style={{ fontSize: 9, color: 'var(--text3)' }}>OHLCV: {p.technical_snapshot.ohlcv_data_status}</span>
                )}
              </div>
            )}

            {/* Momentum */}
            <div style={secLbl}>Momentum</div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 6, marginBottom: 8 }}>
              {kv('RSI', tc.rsi != null ? `${Number(tc.rsi).toFixed(1)}` : null,
                tc.rsi == null ? 'var(--amber)' : tc.rsi_state?.includes('overbought') ? 'var(--red)' : tc.rsi_state === 'oversold' ? 'var(--green)' : undefined)}
              {kv('RSI State', tc.rsi != null ? (tc.rsi_state || 'neutral') : 'Missing -- run technical snapshot', tc.rsi == null ? 'var(--amber)' : undefined)}
              {kv('RVOL', tc.rvol ? `${Number(tc.rvol).toFixed(1)}x` : null, tc.rvol >= 10 ? 'var(--green)' : tc.rvol >= 5 ? '#60A5FA' : undefined)}
              {kv('RVOL State', tc.rvol_state || (tc.rvol == null ? 'Missing -- run technical snapshot' : 'unknown'), tc.rvol == null ? 'var(--amber)' : undefined)}
            </div>

            {/* Trend */}
            <div style={secLbl}>Trend</div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 6, marginBottom: 8 }}>
              {kv('ADX', tc.adx != null ? `${Number(tc.adx).toFixed(1)}` : null, tc.adx == null ? 'var(--amber)' : undefined)}
              {kv('Trend Strength', tc.trend_strength || (tc.adx == null ? 'Missing -- run technical snapshot' : 'unknown'), tc.adx == null ? 'var(--amber)' : undefined)}
              {kv('VWAP', tc.vwap_distance_pct != null ? `${Number(tc.vwap_distance_pct) > 0 ? '+' : ''}${Number(tc.vwap_distance_pct).toFixed(1)}%` : null,
                tc.vwap_distance_pct == null ? 'var(--amber)' : undefined)}
              {kv('VWAP State', tc.vwap_state || (tc.vwap_distance_pct == null ? 'Missing -- run technical snapshot' : 'unknown'), tc.vwap_distance_pct == null ? 'var(--amber)' : undefined)}
            </div>

            {/* Volatility */}
            <div style={secLbl}>Volatility</div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 6, marginBottom: 8 }}>
              {kv('ATR', tc.atr ? `$${Number(tc.atr).toFixed(2)} / ${tc.atr_pct || '?'}%` : null, !tc.atr ? 'var(--amber)' : undefined)}
              {kv('ATR State', tc.atr_state || (tc.atr == null ? 'Missing -- run technical snapshot' : 'unknown'), tc.atr == null ? 'var(--amber)' : undefined)}
              {kv('Float Rotation', tc.float_rotation_state || 'unavailable')}
              {kv('Gap', tc.gap_pct != null ? `${Number(tc.gap_pct).toFixed(1)}% (${tc.gap_state || '?'})` : null)}
            </div>

            {p.technical_summary && (
              <div style={{ fontSize: 10, color: 'var(--text2)', marginTop: 4, padding: '6px 8px', background: 'var(--bg0)', borderRadius: 4 }}>
                {p.technical_summary}
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

        {/* ── Tech Map tab ── */}
        {activeTab === 'tech_map' && (
          <>
            <div style={secLbl}>EMA Stack</div>
            {(() => {
              const ts = p.technical_snapshot || {}
              const allNull = ts.ema_8 == null && ts.ema_21 == null && ts.ema_50 == null && ts.ema_200 == null
              const alignColor = ts.ema_alignment === 'BULL_STACKED' || ts.ema_alignment === 'BULLISH' ? 'green'
                : ts.ema_alignment === 'BEARISH' ? 'red' : 'amber'
              return (
                <>
                  {allNull && ts.ema_alignment ? (
                    <div style={{ fontSize: 10, color: 'var(--amber)', padding: '6px 8px', background: 'rgba(251,191,36,0.06)', borderRadius: 4, marginBottom: 8 }}>
                      EMA alignment shows {ts.ema_alignment} but individual EMA values are unavailable. Run technical snapshot to populate.
                    </div>
                  ) : (
                    <>
                      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 6, marginBottom: 8 }}>
                        {kv('EMA 8', ts.ema_8 != null ? `$${Number(ts.ema_8).toFixed(2)}` : 'Missing', ts.ema_8 == null ? 'var(--amber)' : undefined)}
                        {kv('EMA 21', ts.ema_21 != null ? `$${Number(ts.ema_21).toFixed(2)}` : 'Missing', ts.ema_21 == null ? 'var(--amber)' : undefined)}
                        {kv('EMA 50', ts.ema_50 != null ? `$${Number(ts.ema_50).toFixed(2)}` : 'Missing', ts.ema_50 == null ? 'var(--amber)' : undefined)}
                        {kv('EMA 200', ts.ema_200 != null ? `$${Number(ts.ema_200).toFixed(2)}` : 'Missing', ts.ema_200 == null ? 'var(--amber)' : undefined)}
                      </div>
                      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 6, marginBottom: 8 }}>
                        {kv('EMA 8 Dist', ts.ema_8_distance_pct != null ? `${Number(ts.ema_8_distance_pct).toFixed(1)}%` : '--')}
                        {kv('EMA 21 Dist', ts.ema_21_distance_pct != null ? `${Number(ts.ema_21_distance_pct).toFixed(1)}%` : '--')}
                        {kv('EMA 50 Dist', ts.ema_50_distance_pct != null ? `${Number(ts.ema_50_distance_pct).toFixed(1)}%` : '--')}
                        {kv('EMA 200 Dist', ts.ema_200_distance_pct != null ? `${Number(ts.ema_200_distance_pct).toFixed(1)}%` : '--')}
                      </div>
                    </>
                  )}
                  <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 8 }}>
                    <span style={pill(alignColor)}>{ts.ema_alignment || 'Unknown'}</span>
                    <span style={{ fontSize: 9, color: 'var(--text3)' }}>EMA Alignment</span>
                  </div>
                </>
              )
            })()}

            <div style={secLbl}>Fibonacci Levels</div>
            {(() => {
              const ts = p.technical_snapshot || {}
              const fc = typeof p.fib_context === 'object' ? p.fib_context : (ts.fib_context || {})
              const hasData = fc && fc.available !== false && (fc.swing_high || fc.swing_low || ts.swing_high || ts.swing_low || ts.nearest_fib_level)
              if (!hasData) {
                return <div style={{ fontSize: 10, color: 'var(--amber)', padding: '6px 8px', background: 'rgba(251,191,36,0.06)', borderRadius: 4 }}>Fib data unavailable -- run Fib analysis to populate</div>
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
                  {kv('ORB Status', <span style={pill(orbColor)}>{ts.opening_range_status || 'Unknown'}</span>)}
                  {kv('PM Status', ts.premarket_status || 'Unknown')}
                  {kv('Tech Grade', ts.technical_grade || 'Unknown')}
                  {kv('OHLCV', ts.ohlcv_data_status || 'Unknown')}
                </div>
              )
            })()}
          </>
        )}

        {/* ── Catalyst tab ── */}
        {activeTab === 'catalyst' && (
          <>
            <div style={secLbl}>Catalyst</div>
            <div style={{ fontSize: 11, color: 'var(--text1)', lineHeight: 1.4, marginBottom: 8 }}>
              {p.catalyst_verified ? <span style={{ color: 'var(--green)', marginRight: 4 }}>&#10003;</span> : <span style={{ color: 'var(--amber)', marginRight: 4 }}>?</span>}
              {p.catalyst || 'No catalyst data'}
              {p.catalyst_confidence != null && (
                <span style={{ color: 'var(--text3)', fontSize: 9, marginLeft: 6 }}>
                  {Math.min(100, Math.max(0, Math.round(p.catalyst_confidence * 100)))}% confidence
                </span>
              )}
            </div>
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
                  {p.critic_verdict} {p.critic_confidence != null ? `${Math.min(100, Math.max(0, Math.round(p.critic_confidence * 100)))}%` : ''}
                </span>
                {p.critic_reasoning && <div style={{ fontSize: 10, color: 'var(--text2)', marginTop: 4, lineHeight: 1.4 }}>{p.critic_reasoning}</div>}
              </div>
            )}
            <div style={secLbl}>Recent News ({p.news && Array.isArray(p.news) ? p.news.length : 0} articles)</div>
            {p.news && Array.isArray(p.news) && p.news.length > 0 ? p.news.slice(0, 5).map((n: any, i: number) => (
              <div key={i} style={{ fontSize: 10, color: 'var(--text2)', padding: '2px 0' }}>
                {n.title} <span style={{ color: 'var(--text3)', marginLeft: 6, fontSize: 9 }}>{n.source}</span>
              </div>
            )) : (
              <div style={{ fontSize: 10, color: 'var(--amber)', padding: '6px 8px', background: 'rgba(251,191,36,0.06)', borderRadius: 4 }}>
                No recent articles -- run research to populate news data
              </div>
            )}
          </>
        )}

        {/* ── Strategy tab ── */}
        {activeTab === 'strategy' && (
          <>
            <div style={secLbl}>Primary Strategy</div>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 8 }}>
              <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', ...mono }}>{p.strategy_id}</span>
              {p.strategy_config_hash && <span style={{ fontSize: 9, color: 'var(--text3)' }}>hash: {String(p.strategy_config_hash).slice(0, 8)}</span>}
            </div>

            {norm.strategyMismatch && (
              <div style={{ padding: '6px 10px', marginBottom: 8, borderRadius: 6, fontSize: 10, fontWeight: 600, background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.2)', color: '#F87171' }}>
                WARNING: primary_strategy_id ("{p.primary_strategy_id}") differs from strategy_id ("{p.strategy_id}"). The setup router may have assigned a different primary. Using strategy_id as canonical.
              </div>
            )}

            {/* Strategy fit details */}
            {sf.fit_score != null && (
              <>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 6, marginBottom: 8 }}>
                  {kv('Fit Score', `${sf.fit_score}/100`,
                    sf.fit_score >= 80 ? 'var(--green)' : sf.fit_score >= 60 ? 'var(--amber)' : 'var(--red)')}
                  {kv('Grade', sf.fit_grade,
                    sf.fit_grade === 'STRONG_FIT' ? 'var(--green)' : sf.fit_grade === 'GOOD_FIT' ? '#60A5FA' : 'var(--amber)')}
                  {kv('Setup Class', sf.setup_class || 'unclassified')}
                  {kv('Criteria', `${(sf.criteria_met || []).length} met / ${(sf.criteria_failed || []).length} failed`)}
                </div>
                {sf.criteria_met?.length > 0 && (
                  <div style={{ marginBottom: 6 }}>
                    <div style={{ fontSize: 9, color: 'var(--text3)', fontWeight: 600, marginBottom: 4 }}>CRITERIA MET ({sf.criteria_met.length})</div>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                      {sf.criteria_met.map((c: string, i: number) => (
                        <span key={i} style={{ ...pill('green'), fontSize: 8 }}>{c}</span>
                      ))}
                    </div>
                  </div>
                )}
                {sf.criteria_failed?.length > 0 && (
                  <div style={{ marginBottom: 6 }}>
                    <div style={{ fontSize: 9, color: 'var(--text3)', fontWeight: 600, marginBottom: 4 }}>CRITERIA FAILED ({sf.criteria_failed.length})</div>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                      {sf.criteria_failed.map((c: string, i: number) => (
                        <span key={i} style={{ ...pill('red'), fontSize: 8 }}>{c}</span>
                      ))}
                    </div>
                  </div>
                )}
                {sf.narrative && (
                  <div style={{ fontSize: 10, color: 'var(--text2)', lineHeight: 1.5, marginTop: 6, padding: '6px 8px', background: 'var(--bg0)', borderRadius: 4 }}>
                    {sf.narrative}
                  </div>
                )}
              </>
            )}

            {/* Secondary strategies */}
            {p.secondary_strategy_ids && Array.isArray(p.secondary_strategy_ids) && p.secondary_strategy_ids.length > 0 && (
              <>
                <div style={secLbl}>Secondary Setups ({p.secondary_strategy_ids.length})</div>
                <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginBottom: 8 }}>
                  {p.secondary_strategy_ids.slice(0, 8).map((s: string) => (
                    <span key={s} style={pill('blue')}>{s}</span>
                  ))}
                  {p.secondary_strategy_ids.length > 8 && <span style={{ fontSize: 9, color: 'var(--text3)' }}>+{p.secondary_strategy_ids.length - 8} more</span>}
                </div>
              </>
            )}

            {/* Setup stack: filter to STRONG + MODERATE by default */}
            {p.setup_stack && Array.isArray(p.setup_stack) && p.setup_stack.length > 0 && (
              <>
                {(() => {
                  const strongModerate = p.setup_stack.filter((m: any) => m.match_status === 'STRONG_MATCH' || m.match_status === 'MODERATE_MATCH')
                  const weakOther = p.setup_stack.filter((m: any) => m.match_status !== 'STRONG_MATCH' && m.match_status !== 'MODERATE_MATCH' && m.match_status !== 'NO_MATCH')
                  const displayed = showAllSetups ? [...strongModerate, ...weakOther] : strongModerate
                  return (
                    <>
                      <div style={secLbl}>Setup Stack ({strongModerate.length} strong/moderate{weakOther.length > 0 ? `, ${weakOther.length} other` : ''})</div>
                      {displayed.length > 0 ? (
                        <div style={{ background: 'var(--bg0)', borderRadius: 6, overflow: 'auto', marginBottom: 6 }}>
                          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 10, ...mono }}>
                            <thead>
                              <tr style={{ borderBottom: '1px solid var(--border)' }}>
                                {['Strategy', 'Score', 'Status', 'Primary', 'Met', 'Disqualified'].map(h => (
                                  <th key={h} style={{ padding: '5px 8px', textAlign: 'left', fontSize: 8, color: 'var(--text3)', fontWeight: 600 }}>{h}</th>
                                ))}
                              </tr>
                            </thead>
                            <tbody>
                              {displayed.map((m: any, i: number) => (
                                <tr key={i} style={{ borderBottom: '1px solid var(--border)', background: m.is_primary ? 'rgba(34,197,94,0.04)' : undefined }}>
                                  <td style={{ padding: '4px 8px', fontWeight: m.is_primary ? 700 : 400 }}>{m.strategy_id}</td>
                                  <td style={{ padding: '4px 8px' }}>{m.match_score}</td>
                                  <td style={{ padding: '4px 8px' }}>
                                    <span style={pill(m.match_status === 'STRONG_MATCH' ? 'green' : m.match_status === 'BLOCKED' ? 'red' : m.match_status === 'MODERATE_MATCH' ? 'blue' : 'amber')}>
                                      {m.match_status}
                                    </span>
                                  </td>
                                  <td style={{ padding: '4px 8px', color: m.is_primary ? 'var(--green)' : 'var(--text3)' }}>{m.is_primary ? 'PRIMARY' : ''}</td>
                                  <td style={{ padding: '4px 8px', color: 'var(--text3)', fontSize: 9 }}>{(m.criteria_met || []).length}</td>
                                  <td style={{ padding: '4px 8px', color: (m.disqualifiers_hit || []).length > 0 ? 'var(--red)' : 'var(--text3)', fontSize: 9 }}>
                                    {(m.disqualifiers_hit || []).length > 0 ? (m.disqualifiers_hit || []).join(', ') : '--'}
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      ) : (
                        <div style={{ fontSize: 10, color: 'var(--text3)', fontStyle: 'italic' }}>No strong or moderate matches</div>
                      )}
                      {weakOther.length > 0 && (
                        <button onClick={() => setShowAllSetups(!showAllSetups)}
                          style={{ ...btnStyle('rgba(148,163,184,0.1)', '#94A3B8'), fontSize: 9, padding: '3px 8px' }}>
                          {showAllSetups ? 'Hide weak matches' : `View all ${weakOther.length} weak matches`}
                        </button>
                      )}
                    </>
                  )
                })()}
              </>
            )}
            {(!p.setup_stack || !Array.isArray(p.setup_stack) || p.setup_stack.length === 0) && !sf.fit_score && (
              <div style={{ fontSize: 10, color: 'var(--text3)', fontStyle: 'italic', marginTop: 4 }}>
                Strategy data not computed yet. Run multi-setup router to populate.
              </div>
            )}

            {/* Sector context */}
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

        {/* ── Risk/Reward tab ── */}
        {activeTab === 'risk' && (
          <>
            {/* Three status badges */}
            <div style={{ display: 'flex', gap: 8, marginBottom: 10, flexWrap: 'wrap' }}>
              <span style={pill(p.risk_gate_result === 'PASS' ? 'green' : p.risk_gate_result === 'FAIL' ? 'red' : 'amber')}>
                Risk Gate: {p.risk_gate_result || 'Not checked'}
              </span>
              <span style={pill(sf.fit_grade === 'STRONG_FIT' ? 'green' : sf.fit_grade === 'GOOD_FIT' ? 'blue' : sf.fit_score != null ? 'amber' : 'amber')}>
                Strategy Quality: {sf.fit_grade || 'Not computed'}
              </span>
              <span style={pill(er.readiness_state === 'READY_FOR_PAPER_SUBMIT' || er.readiness_state === 'READY_ORB_CONFIRMED' ? 'green' : er.readiness_state ? 'amber' : 'amber')}>
                Execution: {er.readiness_state ? er.readiness_state.replace(/_/g, ' ') : 'Not checked'}
              </span>
            </div>

            {rr > 0 && rr < 2.0 && (
              <div style={{ padding: '6px 10px', marginBottom: 8, borderRadius: 6, fontSize: 10, fontWeight: 600, background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.2)', color: '#F87171' }}>
                R:R {Number(rr).toFixed(2)} is below strategy minimum of 2.0
              </div>
            )}

            <div style={secLbl}>Position Sizing</div>
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
              {kv('R:R', (isModified ? computedRR : rr).toFixed(2))}
              {kv('Risk % Portfolio', `${(p.risk_pct_portfolio || 0).toFixed(3)}%`)}
              {kv('Gate', p.risk_gate_result || '--')}
            </div>
            {isModified && <div style={{ fontSize: 9, color: '#60A5FA', marginTop: 8, fontWeight: 600 }}>Modified -- will approve with overrides</div>}

            {/* Backtest inline */}
            <div style={secLbl}>Backtest Evidence</div>
            {bt.quality || bt.sample_size ? (
              <div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 6 }}>
                  {kv('Quality', bt.quality, bt.quality === 'SUFFICIENT' ? 'var(--green)' : bt.quality === 'LIMITED' ? 'var(--amber)' : 'var(--red)')}
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
            ) : (
              <div style={{ fontSize: 10, color: 'var(--text3)', fontStyle: 'italic' }}>Backtest not run yet</div>
            )}
          </>
        )}

        {/* ── Execution tab ── */}
        {activeTab === 'execution' && (
          <>
            <div style={secLbl}>Execution Readiness</div>
            {p.execution_readiness ? (() => {
              const stateColor = er.readiness_state === 'READY_FOR_PAPER_SUBMIT' || er.readiness_state === 'READY_ORB_CONFIRMED' ? 'green'
                : er.readiness_state === 'CAUTION_EXECUTABLE' ? 'amber' : 'red'
              // Override quote_fresh if quote_age > 300 during market hours
              const effectiveQuoteFresh = (er.quote_age_seconds != null && Number(er.quote_age_seconds) > 300 && er.market_hours) ? false : er.quote_fresh
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
                    {kv('Spread', er.bid != null && er.ask != null ? (er.spread_pct != null ? `${Number(er.spread_pct).toFixed(3)}%` : 'Calculating') : 'Unknown',
                      er.bid == null || er.ask == null ? 'var(--amber)' : Number(er.spread_pct) > 1 ? 'var(--red)' : 'var(--green)')}
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 6, marginBottom: 8 }}>
                    {kv('Quote Fresh', effectiveQuoteFresh ? 'YES' : 'NO', effectiveQuoteFresh ? 'var(--green)' : 'var(--red)')}
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

                  <div style={secLbl}>Quote Source</div>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 6, marginBottom: 8 }}>
                    {kv('Provider', er.quote_provider || 'none',
                      er.quote_provider === 'alpaca' || er.quote_provider === 'polygon' ? 'var(--green)'
                        : er.quote_provider === 'none' ? 'var(--red)' : 'var(--amber)')}
                    {kv('Exec Eligible', er.quote_execution_eligible ? 'YES' : 'NO',
                      er.quote_execution_eligible ? 'var(--green)' : 'var(--red)')}
                    {kv('Delayed', er.quote_is_delayed ? 'YES' : 'NO',
                      er.quote_is_delayed ? 'var(--amber)' : 'var(--green)')}
                    {kv('Volume Source', er.volume_source || 'Unknown')}
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 6, marginBottom: 8 }}>
                    {kv('Bid', er.bid != null ? `$${Number(er.bid).toFixed(2)}` : 'Unavailable',
                      er.bid != null ? 'var(--green)' : 'var(--red)')}
                    {kv('Ask', er.ask != null ? `$${Number(er.ask).toFixed(2)}` : 'Unavailable',
                      er.ask != null ? 'var(--green)' : 'var(--red)')}
                    {kv('Spread', er.bid != null && er.ask != null ? (er.spread_pct != null ? `${Number(er.spread_pct).toFixed(3)}%` : 'Calculating') : 'Unknown',
                      er.bid == null || er.ask == null ? 'var(--amber)' : Number(er.spread_pct) > 1 ? 'var(--red)' : 'var(--green)')}
                    {kv('Spread Source', er.spread_source || 'Unknown')}
                  </div>
                  {!er.quote_execution_eligible && er.quote_provider && er.quote_provider !== 'none' && (
                    <div style={{ fontSize: 9, color: 'var(--amber)', padding: '4px 8px', background: 'rgba(251,191,36,0.06)', borderRadius: 4, marginBottom: 8 }}>
                      Blocked: {er.quote_provider} provides display-only data. Execution-grade quote requires Alpaca or Polygon with bid/ask.
                    </div>
                  )}

                  <div style={secLbl}>Alpaca Paper Bracket</div>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 6, marginBottom: 8 }}>
                    {kv('Bracket Supported', er.bracket_order_supported ? 'YES' : 'NO',
                      er.bracket_order_supported ? 'var(--green)' : 'var(--red)')}
                    {kv('Alpaca Mode', er.alpaca_account_mode ? (er.alpaca_account_mode === 'paper' ? 'PAPER' : er.alpaca_account_mode) : 'Not checked',
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

                  {/* Session 28: Submit Readiness */}
                  <div style={secLbl}>Submit Readiness</div>
                  <div style={{ padding: '8px 10px', background: 'var(--bg0)', borderRadius: 6, marginBottom: 8 }}>
                    <div style={{ fontSize: 10, padding: '4px 0', marginBottom: 6, display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span style={{ fontSize: 9, fontWeight: 700, padding: '2px 8px', borderRadius: 4,
                        background: p.action_state === 'PAPER_READY' ? 'rgba(34,197,94,0.15)' : p.action_state === 'BLOCKED' ? 'rgba(239,68,68,0.15)' : 'rgba(251,191,36,0.12)',
                        color: p.action_state === 'PAPER_READY' ? 'var(--green)' : p.action_state === 'BLOCKED' ? 'var(--red)' : '#F59E0B' }}>
                        {p.action_state === 'PAPER_READY' ? 'READY' : p.action_state || 'NOT_CHECKED'}
                      </span>
                      <span style={{ fontSize: 9, color: 'var(--amber)', fontWeight: 600 }}>PAPER ONLY -- LIVE TRADING DISABLED</span>
                    </div>
                    {er.blockers && er.blockers.length > 0 && (
                      <div style={{ marginBottom: 4 }}>
                        <div style={{ fontSize: 8, color: 'var(--red)', fontWeight: 600, marginBottom: 2 }}>BLOCKERS</div>
                        {er.blockers.map((b: string, i: number) => (
                          <div key={i} style={{ fontSize: 9, color: 'var(--red)', padding: '1px 0' }}>{b}</div>
                        ))}
                      </div>
                    )}
                    {er.warnings && er.warnings.length > 0 && (
                      <div style={{ marginBottom: 4 }}>
                        <div style={{ fontSize: 8, color: 'var(--amber)', fontWeight: 600, marginBottom: 2 }}>WARNINGS</div>
                        {er.warnings.map((w: string, i: number) => (
                          <div key={i} style={{ fontSize: 9, color: 'var(--amber)', padding: '1px 0' }}>{w}</div>
                        ))}
                      </div>
                    )}
                    <div style={{ display: 'flex', gap: 6, marginTop: 6, flexWrap: 'wrap' }}>
                      <button onClick={() => runAction('checkReadiness', '/api/v2/paper-proposals/check-submit-readiness')}
                        disabled={!!runningAction} style={btnStyle('rgba(59,130,246,0.15)', '#60A5FA')}>
                        {runningAction === 'checkReadiness' ? '...' : 'Check Readiness'}
                      </button>
                      <button onClick={() => runAction('dryRunSubmit', '/api/v2/paper-proposals/dry-run-submit')}
                        disabled={!!runningAction} style={btnStyle('rgba(59,130,246,0.15)', '#60A5FA')}>
                        {runningAction === 'dryRunSubmit' ? '...' : 'Dry Run Bracket'}
                      </button>
                      <button onClick={() => {
                        if (!confirm(`PAPER ONLY: Submit ${p.symbol} to Alpaca PAPER trading?\n\nThis will place a PAPER bracket order. NO real money involved.\n\nLIVE TRADING IS DISABLED.`)) return
                        runAction('submitPaperNew', '/api/v2/paper-proposals/submit-paper')
                      }}
                        disabled={!!runningAction || (p.action_state === 'BLOCKED')}
                        style={{
                          ...btnStyle('#7F1D1D', '#EF4444'),
                          border: '1px solid #DC2626',
                          opacity: p.action_state === 'BLOCKED' ? 0.4 : 1,
                          cursor: p.action_state === 'BLOCKED' ? 'not-allowed' : 'pointer',
                        }}>
                        {runningAction === 'submitPaperNew' ? '...' : 'Submit to Alpaca Paper'}
                      </button>
                    </div>
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

        {/* ── Agents tab ── */}
        {activeTab === 'agents' && (
          <>
            <div style={secLbl}>Agent Reviews</div>
            {(() => {
              const reviewed = (p.agent_reviews || []).filter((ar: any) => ar.verdict && ar.agent_name)
              if (reviewed.length === 0) {
                // Check agent_votes too
                const votes = p.agent_votes || {}
                const votedEntries = Object.entries(votes).filter(([, v]: [string, any]) => v?.vote)
                if (votedEntries.length === 0) {
                  return (
                    <div style={{ padding: '16px', background: 'var(--bg0)', borderRadius: 6, textAlign: 'center' }}>
                      <div style={{ fontSize: 12, color: 'var(--text2)', marginBottom: 6 }}>No agent reviews with verdicts</div>
                      <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 10 }}>Run AI Review to generate Maria, Risk, and Steph analyses</div>
                      <button onClick={() => runAction('agent', '/api/v2/paper-proposals/run-agent-review')} disabled={!!runningAction}
                        style={btnStyle('rgba(59,130,246,0.2)', '#60A5FA')}>
                        {runningAction === 'agent' ? '...' : 'Run AI Review'}
                      </button>
                    </div>
                  )
                }
                // Show from agent_votes
                return (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                    {votedEntries.map(([name, v]: [string, any]) => {
                      const vote = v?.vote || ''
                      const conf = v?.confidence != null ? `${Math.round(Number(v.confidence))}%` : ''
                      const summary = v?.summary || ''
                      const model = v?.model || ''
                      const voteColor = vote === 'APPROVE_TEST' ? 'green' : vote === 'REJECT' || vote === 'BLOCK' ? 'red' : vote === 'WAIT_FOR_DATA' ? 'blue' : 'amber'
                      return (
                        <div key={name} style={{ padding: '4px 8px', background: 'var(--bg0)', borderRadius: 4, display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                          <span style={{ fontSize: 10, fontWeight: 700, color: 'var(--text1)', minWidth: 40, ...mono }}>{name}</span>
                          <span style={pill(voteColor)}>{vote} {conf}</span>
                          <span style={{ fontSize: 9, color: 'var(--text2)', flex: 1 }}>{summary.slice(0, 100)}</span>
                          {model === 'deterministic_fallback' ? (
                            <span style={{ fontSize: 8, padding: '1px 5px', borderRadius: 3, background: 'rgba(148,163,184,0.1)', color: '#64748B', fontWeight: 600 }}>Fallback analysis</span>
                          ) : model ? (
                            <span style={{ fontSize: 8, color: 'var(--text3)' }}>{model}</span>
                          ) : null}
                        </div>
                      )
                    })}
                  </div>
                )
              }
              return (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  {reviewed.map((ar: any, i: number) => {
                    const voteColor = ar.verdict === 'APPROVE_TEST' || ar.verdict === 'BUY' ? 'green'
                      : ar.verdict === 'REJECT' || ar.verdict === 'BLOCK' || ar.verdict === 'AVOID' || ar.verdict === 'SELL' ? 'red'
                      : ar.verdict === 'WAIT_FOR_DATA' ? 'blue' : 'amber'
                    const isFallback = ar.model === 'deterministic_fallback' || ar.narrative_source === 'deterministic_fallback'
                    return (
                      <div key={i} style={{ padding: '4px 8px', background: 'var(--bg0)', borderRadius: 4, display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                        <span style={{ fontSize: 10, fontWeight: 700, color: 'var(--text1)', minWidth: 70, ...mono }}>{ar.agent_name}</span>
                        <span style={pill(voteColor)}>{ar.verdict} {ar.confidence != null ? `${Math.round(Number(ar.confidence) * (Number(ar.confidence) > 1 ? 1 : 100))}%` : ''}</span>
                        <span style={{ fontSize: 9, color: 'var(--text2)', flex: 1 }}>{(ar.summary || '').slice(0, 120)}</span>
                        {isFallback && (
                          <span style={{ fontSize: 8, padding: '1px 5px', borderRadius: 3, background: 'rgba(148,163,184,0.1)', color: '#64748B', fontWeight: 600 }}>Fallback analysis</span>
                        )}
                      </div>
                    )
                  })}
                </div>
              )
            })()}
          </>
        )}

        {/* ── Missing tab ── */}
        {activeTab === 'missing' && (
          <>
            <div style={secLbl}>Missing Data by Section</div>
            {Object.keys(norm.missingBySection).length > 0 ? (
              <>
                {['Critical', 'Technical', 'Catalyst', 'Execution', 'Backtest', 'Agent/LLM', 'Other'].filter(
                  sec => norm.missingBySection[sec]?.length > 0
                ).map(section => {
                  const items = norm.missingBySection[section]
                  const sectionColor = section === 'Critical' ? 'var(--red)' : section === 'Technical' ? 'var(--amber)' : 'var(--text2)'
                  const actionMap: Record<string, { label: string; action: string; endpoint: string }> = {
                    'Critical':  { label: 'Refresh Packet', action: 'refresh', endpoint: '/api/v2/paper-proposals/refresh-packet' },
                    'Technical': { label: 'Run Tech Snapshot', action: 'techSnap', endpoint: '/api/v2/paper-proposals/run-technical-snapshot' },
                    'Catalyst':  { label: 'Run Research', action: 'research', endpoint: '/api/v2/paper-proposals/run-research' },
                    'Execution': { label: 'Check Execution', action: 'execReady', endpoint: '/api/v2/paper-proposals/check-execution-readiness' },
                    'Backtest':  { label: 'Run Backtest', action: 'backtest', endpoint: '/api/v2/paper-proposals/run-backtest' },
                    'Agent/LLM': { label: 'Run AI Review', action: 'agent', endpoint: '/api/v2/paper-proposals/run-agent-review' },
                  }
                  const sectionAction = actionMap[section]
                  return (
                    <div key={section} style={{ marginBottom: 10 }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                        <div style={{ fontSize: 10, fontWeight: 700, color: sectionColor, textTransform: 'uppercase' }}>{section} ({items.length})</div>
                        {sectionAction && (
                          <button onClick={() => runAction(sectionAction.action, sectionAction.endpoint)}
                            disabled={!!runningAction} style={{ ...btnStyle('rgba(59,130,246,0.15)', '#60A5FA'), fontSize: 9, padding: '2px 8px' }}>
                            {runningAction === sectionAction.action ? '...' : sectionAction.label}
                          </button>
                        )}
                      </div>
                      {items.map((m: string, i: number) => (
                        <div key={i} style={{ fontSize: 10, color: 'var(--amber)', padding: '3px 8px', marginBottom: 2, background: 'rgba(251,191,36,0.06)', borderRadius: 4 }}>{m}</div>
                      ))}
                    </div>
                  )
                })}
              </>
            ) : (p.missing_data || []).length > 0 ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                {p.missing_data.map((m: string, i: number) => (
                  <div key={i} style={{ fontSize: 10, color: 'var(--amber)', padding: '4px 8px', background: 'rgba(251,191,36,0.06)', borderRadius: 4 }}>{m}</div>
                ))}
              </div>
            ) : (
              <div style={{ fontSize: 10, color: 'var(--green)' }}>All required data populated</div>
            )}
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

      {/* ── Actions footer ── */}
      <div style={{ padding: '10px 16px', borderTop: '1px solid var(--border)', display: 'flex', gap: 6, justifyContent: 'flex-end', flexWrap: 'wrap' }}>
        <button onClick={() => runAction('enrich', '/api/v2/paper-proposals/enrich', { proposal_id: p.id })} disabled={!!runningAction}
          style={btnStyle('rgba(168,85,247,0.15)', '#A855F7')}>
          {runningAction === 'enrich' ? '...' : 'Enrich'}
        </button>
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
        <button onClick={() => runAction('monitor', '/api/v2/paper-proposals/monitor')} disabled={!!runningAction}
          style={btnStyle('rgba(148,163,184,0.15)', '#94A3B8')}>
          {runningAction === 'monitor' ? '...' : 'Refresh Price'}
        </button>

        <div style={{ flex: 1 }} />

        <button
          onClick={() => {
            if (confirm('Submit to Alpaca PAPER trading? This is NOT a live trade.')) {
              runAction('submitPaper', '/api/v2/paper-proposals/submit-alpaca-paper')
            }
          }}
          disabled={!!runningAction || p.status === 'PENDING'}
          title={p.paper_submit_state === 'SUBMITTED' ? 'Already submitted to Alpaca' : p.status === 'PENDING' ? 'Approve first — Alpaca submission is automatic on approval' : 'Submit to Alpaca paper trading'}
          style={{
            ...btnStyle(
              p.paper_submit_state === 'SUBMITTED' ? '#065F46' : p.status !== 'PENDING' ? '#065F46' : 'rgba(34,197,94,0.1)',
              p.paper_submit_state === 'SUBMITTED' ? '#10B981' : p.status !== 'PENDING' ? '#10B981' : '#44403C'
            ),
            opacity: p.status === 'PENDING' ? 0.4 : 1,
            cursor: p.status === 'PENDING' ? 'not-allowed' : 'pointer',
            border: '1px solid #047857',
          }}>
          {runningAction === 'submitPaper' ? '...' : p.paper_submit_state === 'SUBMITTED' ? 'Submitted' : 'Submit to Alpaca Paper'}
        </button>

        <button onClick={handleApprove} disabled={!!acting[p.id] || approveDisabled}
          title={approveDisabled ? (p.approval_blocked_reason || 'Missing data') : 'Approve for paper trading'}
          style={{ ...btnStyle(approveDisabled ? 'rgba(34,197,94,0.1)' : canApproveWithConfirm ? 'var(--amber)' : 'var(--green)'), opacity: approveDisabled ? 0.4 : 1, cursor: approveDisabled ? 'not-allowed' : 'pointer' }}>
          {acting[p.id] === 'approve' ? '...' : approveDisabled ? (p.approval_blocked_reason?.slice(0, 20) || 'Cannot Approve') : canApproveWithConfirm ? 'Approve (confirm)' : isModified ? 'Approve*' : 'Approve'}
        </button>
        <button onClick={() => act(p.id, 'reject')} disabled={!!acting[p.id]}
          style={btnStyle('var(--red)')}>
          {acting[p.id] === 'reject' ? '...' : 'Reject'}
        </button>
        <button onClick={() => { if (editing) { setShares(p.proposed_shares || 0); setEntry(p.proposed_entry || 0); setStop(p.proposed_stop || 0); setTarget(p.proposed_target1 || 0) } setEditing(!editing) }}
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

// ── Lifecycle sort priority (IN ZONE first, ENTRY MISSED last) ─────────
const LIFECYCLE_PRIORITY: Record<string, number> = {
  ENTRY_ZONE_VALID: 1, ACTIVE: 2, ACTIVE_MONITORING: 2,
  NEEDS_REVIEW: 3, ENTRY_MISSED: 4, STALE: 5, EXPIRED: 6, UNKNOWN: 7,
}
const ACTION_SORT: Record<string, number> = {
  PAPER_READY: 1, CAUTION: 2, LEARNING_MODE: 3,
  NEEDS_REVIEW: 4, MISSING_DATA: 5, BLOCKED: 6,
}

// ── Timeframe pill colors ─────────────────────────────────────────────
const TIMEFRAME_COLORS: Record<string, { bg: string; text: string }> = {
  intraday: { bg: 'rgba(249,115,22,0.15)', text: '#F97316' },
  short_swing: { bg: 'rgba(59,130,246,0.15)', text: '#60A5FA' },
  event_window: { bg: 'rgba(168,85,247,0.15)', text: '#A855F7' },
  position: { bg: 'rgba(34,197,94,0.15)', text: '#22C55E' },
}

// ── Lifecycle badge ───────────────────────────────────────────────────
function LifecycleBadge({ status, riskGateResult, isBlocked }: { status: string; riskGateResult?: string; isBlocked?: boolean }) {
  // Red BLOCKED only when risk gate rejected or explicit is_blocked
  if (riskGateResult === 'REJECTED' || riskGateResult === 'FAIL' || isBlocked) {
    return <span style={{ fontSize: 9, fontWeight: 700, padding: '2px 8px', borderRadius: 4, background: 'rgba(239,68,68,0.15)', color: '#EF4444' }}>BLOCKED</span>
  }
  const map: Record<string, { label: string; bg: string; color: string }> = {
    ENTRY_ZONE_VALID: { label: 'IN ZONE', bg: 'rgba(34,197,94,0.15)', color: '#22C55E' },
    ACTIVE: { label: 'ACTIVE', bg: 'rgba(20,184,166,0.15)', color: '#14B8A6' },
    ACTIVE_MONITORING: { label: 'ACTIVE', bg: 'rgba(20,184,166,0.15)', color: '#14B8A6' },
    ENTRY_MISSED: { label: 'ENTRY MISSED', bg: 'rgba(251,191,36,0.15)', color: '#F59E0B' },
    NEEDS_REVIEW: { label: 'NEEDS REVIEW', bg: 'rgba(251,191,36,0.15)', color: '#F59E0B' },
    STALE: { label: 'STALE', bg: 'rgba(148,163,184,0.12)', color: '#94A3B8' },
    EXPIRED: { label: 'EXPIRED', bg: 'rgba(148,163,184,0.12)', color: '#94A3B8' },
  }
  const m = map[status] || { label: status?.replace(/_/g, ' ') || 'UNKNOWN', bg: 'rgba(148,163,184,0.12)', color: '#94A3B8' }
  return <span style={{ fontSize: 9, fontWeight: 700, padding: '2px 8px', borderRadius: 4, background: m.bg, color: m.color }}>{m.label}</span>
}

// ── Pipeline chevron (8 stages) ───────────────────────────────────────
function PipelineChevron({ stages }: { stages: any[] }) {
  if (!stages || stages.length === 0) return null
  const statusIcon: Record<string, { icon: string; color: string }> = {
    DONE: { icon: '\u2713', color: '#22C55E' },
    ISSUE: { icon: '\u26A0', color: '#F59E0B' },
    PENDING: { icon: '\u25CB', color: '#14B8A6' },
    SKIPPED: { icon: '\u2014', color: '#64748B' },
  }
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 2, padding: '6px 16px', borderBottom: '1px solid var(--border)', overflowX: 'auto' }}>
      {stages.map((s: any, i: number) => {
        const si = statusIcon[s.status] || statusIcon.PENDING
        return (
          <React.Fragment key={s.id}>
            {i > 0 && <span style={{ fontSize: 8, color: 'var(--text3)', margin: '0 1px', flexShrink: 0 }}>{'\u2192'}</span>}
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', minWidth: 60, flexShrink: 0, padding: '2px 4px', borderRadius: 4, border: `1px solid ${si.color}30` }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 3 }}>
                <span style={{ fontSize: 10, color: si.color }}>{si.icon}</span>
                <span style={{ fontSize: 9, fontWeight: 600, color: si.color }}>{s.label}</span>
              </div>
              {s.detail && <span style={{ fontSize: 8, color: 'var(--text3)', marginTop: 1, whiteSpace: 'nowrap', maxWidth: 80, overflow: 'hidden', textOverflow: 'ellipsis' }}>{s.detail}</span>}
            </div>
          </React.Fragment>
        )
      })}
    </div>
  )
}

// ── Blocker banner ────────────────────────────────────────────────────
function BlockerBanner({ p, norm }: { p: any; norm: any }) {
  const lc = p.lifecycle_status || p.entry_zone_status || ''
  const rg = p.risk_gate_result
  if (rg === 'REJECTED' || rg === 'FAIL') {
    return (
      <div style={{ padding: '6px 16px', background: 'rgba(239,68,68,0.08)', borderBottom: '1px solid rgba(239,68,68,0.2)', fontSize: 10, fontWeight: 600, color: '#EF4444' }}>
        RISK GATE REJECTED — {p.risk_gate_codes ? JSON.stringify(p.risk_gate_codes) : 'Review risk parameters'}
      </div>
    )
  }
  if (lc === 'ENTRY_MISSED') {
    return (
      <div style={{ padding: '6px 16px', background: 'rgba(251,191,36,0.08)', borderBottom: '1px solid rgba(251,191,36,0.2)', fontSize: 10, fontWeight: 600, color: '#F59E0B' }}>
        ENTRY MISSED — price moved {p.price_drift_pct != null ? `${Math.abs(p.price_drift_pct).toFixed(1)}%` : '?'} from zone (${p.proposed_entry?.toFixed(2)} entry, ${p.current_price?.toFixed(2) || '?'} current). Review or dismiss.
      </div>
    )
  }
  if (lc === 'ENTRY_ZONE_VALID' && norm.actionState !== 'BLOCKED') {
    return (
      <div style={{ padding: '6px 16px', background: 'rgba(34,197,94,0.06)', borderBottom: '1px solid rgba(34,197,94,0.15)', fontSize: 10, fontWeight: 600, color: '#22C55E' }}>
        IN ENTRY ZONE — current price ${p.current_price?.toFixed(2) || '?'} is within range
      </div>
    )
  }
  return null
}

// ── Age display ───────────────────────────────────────────────────────
function ageStr(createdAt: string | null): string {
  if (!createdAt) return ''
  const ms = Date.now() - new Date(createdAt).getTime()
  const h = Math.floor(ms / 3600000)
  if (h >= 24) return `${Math.floor(h / 24)}d ${h % 24}h`
  return `${h}h`
}

// ── Main page ──────────────────────────────────────────────────────────
export default function PaperProposals() {
  const { data, refetch } = useApi<any>('/api/v2/paper-proposals', 30000)
  const [acting, setActing] = useState<Record<number, string>>({})
  const [showAll, setShowAll] = useState(true)
  const [strategyFilter, setStrategyFilter] = useState('ALL')
  const [stateFilter, setStateFilter] = useState('ALL')
  const [symbolSearch, setSymbolSearch] = useState('')
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
      if (!d.ok) {
        alert(d.message || d.error || `${action} failed`)
      } else if (d.message) {
        // Show success message for approve (e.g. "Approved for paper test")
        console.log(`[${action}] ${d.message}`)
      }
      refetch()
    } catch { alert('Network error') }
    setActing(s => { const n = { ...s }; delete n[id]; return n })
  }, [refetch])

  const [enrichState, setEnrichState] = useState<'idle' | 'running' | 'done' | 'error'>('idle')
  const [enrichResult, setEnrichResult] = useState<any>(null)
  const [enrichStep, setEnrichStep] = useState<string>('')

  const runEnrichAll = async () => {
    setEnrichState('running')
    setEnrichResult(null)
    setEnrichStep('starting...')
    try {
      await fetch('/api/v2/paper-proposals/enrich-all', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}'
      })
      const poll = setInterval(async () => {
        try {
          const sr = await fetch('/api/v2/paper-proposals/enrich-status')
          const sd = await sr.json()
          if (sd.state === 'running') {
            setEnrichStep(sd.current_step || 'processing...')
          } else if (sd.state === 'done' || sd.state === 'done_with_issues') {
            clearInterval(poll)
            setEnrichResult(sd)
            setEnrichState(sd.all_passed ? 'done' : 'error')
            setEnrichStep(sd.all_passed ? 'Complete' : 'Issues found')
            refetch()
            setTimeout(() => setEnrichState('idle'), 5000)
          }
        } catch { /* keep polling */ }
      }, 3000)
      setTimeout(() => { clearInterval(poll); if (enrichState === 'running') { setEnrichState('idle'); refetch() } }, 300000)
    } catch {
      setEnrichState('error')
      setEnrichStep('Failed to start')
      setTimeout(() => setEnrichState('idle'), 5000)
    }
  }

  const [promoteState, setPromoteState] = useState<'idle' | 'running' | 'done' | 'error'>('idle')
  const [promoteResult, setPromoteResult] = useState<string>('')

  const runPromote = async () => {
    setPromoteState('running')
    try {
      const r = await fetch('/api/v2/paper-proposals/promote-from-incubator', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
      const d = await r.json()
      if (d.ok) {
        setPromoteState('done')
        setPromoteResult(`Promoted ${d.promoted_count} symbols`)
        refetch()
        setTimeout(() => setPromoteState('idle'), 5000)
      } else {
        setPromoteState('error')
        setPromoteResult(d.error || 'Failed')
        setTimeout(() => setPromoteState('idle'), 5000)
      }
    } catch {
      setPromoteState('error')
      setPromoteResult('Network error')
      setTimeout(() => setPromoteState('idle'), 5000)
    }
  }

  const summary = data?.summary || {}
  const allProposals = data?.proposals ?? []
  const pending = allProposals

  // Collect unique strategies for filter dropdown
  const strategies = Array.from(new Set(pending.map((p: any) => p.strategy_id).filter(Boolean))) as string[]

  // Apply filters
  let filtered = pending
  if (strategyFilter !== 'ALL') {
    filtered = filtered.filter((p: any) => p.strategy_id === strategyFilter)
  }
  if (stateFilter !== 'ALL') {
    filtered = filtered.filter((p: any) => normalizeProposal(p).actionState === stateFilter)
  }
  if (symbolSearch.trim()) {
    const q = symbolSearch.trim().toUpperCase()
    filtered = filtered.filter((p: any) => (p.symbol || '').toUpperCase().includes(q))
  }

  // Sort by operator verdict priority, then strategy win rate, then score
  const sorted = [...filtered].sort((a, b) => {
    const sa = a.sort_order ?? 2
    const sb = b.sort_order ?? 2
    if (sa !== sb) return sa - sb
    const wa = a.strategy_win_rate ?? 0
    const wb = b.strategy_win_rate ?? 0
    if (wa !== wb) return wb - wa
    return Number(b.signal_score || 0) - Number(a.signal_score || 0)
  })

  const displayed = showAll ? sorted : sorted.slice(0, 5)

  // Count by state for filter labels
  const stateCounts: Record<string, number> = {}
  for (const p of pending) {
    const s = normalizeProposal(p).actionState
    stateCounts[s] = (stateCounts[s] || 0) + 1
  }

  return (
    <div style={{ minHeight: '100vh', overflowY: 'auto', paddingBottom: 40 }}>
      <PageHeader title="Paper Proposals" subtitle={`${pending.length} pending${summary.expired_today ? ` \u00b7 ${summary.expired_today} expired today` : ''}${summary.incubator_ready_count ? ` \u00b7 ${summary.incubator_ready_count} incubator ready` : ''}`} actions={
        <div style={{ display: 'flex', gap: 8 }}>
          <button onClick={() => setShowAll(!showAll)} style={{ padding: '4px 10px', fontSize: 10, background: showAll ? 'rgba(59,130,246,0.2)' : 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 6, color: showAll ? '#60A5FA' : 'var(--text2)', cursor: 'pointer' }}>
            {showAll ? `All (${filtered.length})` : 'Top 5'}
          </button>
          <button onClick={refetch} style={{ padding: '4px 10px', fontSize: 10, background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 6, color: 'var(--text2)', cursor: 'pointer' }}>Refresh</button>
          <button onClick={runEnrichAll} disabled={enrichState === 'running'}
            style={{ padding: '4px 10px', fontSize: 10, fontWeight: 600, borderRadius: 6, cursor: enrichState === 'running' ? 'wait' : 'pointer',
              background: enrichState === 'running' ? 'rgba(59,130,246,0.2)' : enrichState === 'done' ? 'rgba(34,197,94,0.2)' : enrichState === 'error' ? 'rgba(239,68,68,0.15)' : 'rgba(34,197,94,0.15)',
              border: `1px solid ${enrichState === 'running' ? 'rgba(59,130,246,0.4)' : enrichState === 'done' ? 'rgba(34,197,94,0.4)' : enrichState === 'error' ? 'rgba(239,68,68,0.3)' : 'rgba(34,197,94,0.3)'}`,
              color: enrichState === 'running' ? '#60A5FA' : enrichState === 'done' ? 'var(--green)' : enrichState === 'error' ? 'var(--red)' : 'var(--green)',
              minWidth: 90 }}>
            {enrichState === 'running' ? `Running: ${enrichStep}` : enrichState === 'done' ? 'Done' : enrichState === 'error' ? 'Issues' : 'Enrich All'}
          </button>
          <button onClick={runPromote} disabled={promoteState === 'running'}
            style={{ padding: '4px 10px', fontSize: 10, fontWeight: 600, borderRadius: 6, cursor: promoteState === 'running' ? 'wait' : 'pointer',
              background: promoteState === 'running' ? 'rgba(168,85,247,0.2)' : promoteState === 'done' ? 'rgba(34,197,94,0.2)' : promoteState === 'error' ? 'rgba(239,68,68,0.15)' : 'rgba(168,85,247,0.15)',
              border: `1px solid ${promoteState === 'running' ? 'rgba(168,85,247,0.4)' : promoteState === 'done' ? 'rgba(34,197,94,0.4)' : promoteState === 'error' ? 'rgba(239,68,68,0.3)' : 'rgba(168,85,247,0.3)'}`,
              color: promoteState === 'running' ? '#A855F7' : promoteState === 'done' ? 'var(--green)' : promoteState === 'error' ? 'var(--red)' : '#A855F7',
              minWidth: 140 }}>
            {promoteState === 'running' ? 'Promoting...' : promoteState === 'done' ? promoteResult : promoteState === 'error' ? promoteResult : 'Promote from Incubator'}
          </button>
        </div>
      } />

      {/* Filter bar */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 10, alignItems: 'center', flexWrap: 'wrap' }}>
        <select value={strategyFilter} onChange={e => setStrategyFilter(e.target.value)}
          style={{ fontSize: 10, padding: '4px 8px', background: 'var(--bg1)', color: 'var(--text1)', border: '1px solid var(--border)', borderRadius: 4, ...mono }}>
          <option value="ALL">All Strategies</option>
          {(summary.by_strategy || []).map((s: any) => (
            <option key={s.strategy_id} value={s.strategy_id}>
              {s.strategy_id} ({s.proposal_count} props{s.win_rate != null ? `, ${s.win_rate}% WR` : ''}{s.trade_count ? `, ${s.trade_count} trades` : ''})
            </option>
          ))}
          {strategies.filter(s => !(summary.by_strategy || []).some((bs: any) => bs.strategy_id === s)).sort().map(s => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
        <select value={stateFilter} onChange={e => setStateFilter(e.target.value)}
          style={{ fontSize: 10, padding: '4px 8px', background: 'var(--bg1)', color: 'var(--text1)', border: '1px solid var(--border)', borderRadius: 4, ...mono }}>
          <option value="ALL">All States</option>
          {['PAPER_READY', 'CAUTION', 'NEEDS_REVIEW', 'BLOCKED', 'MISSING_DATA', 'LEARNING_MODE'].map(s => (
            <option key={s} value={s}>{s.replace(/_/g, ' ')} ({stateCounts[s] || 0})</option>
          ))}
        </select>
        <input
          type="text" placeholder="Search symbol..."
          value={symbolSearch} onChange={e => setSymbolSearch(e.target.value)}
          style={{ fontSize: 10, padding: '4px 8px', background: 'var(--bg1)', color: 'var(--text1)', border: '1px solid var(--border)', borderRadius: 4, width: 110, ...mono }}
        />
        <span style={{ fontSize: 9, color: 'var(--text3)' }}>
          Showing {displayed.length} of {pending.length}
        </span>
      </div>

      {/* Enrichment status bar */}
      {enrichState !== 'idle' && (
        <div style={{ padding: '6px 14px', marginBottom: 8, borderRadius: 6, fontSize: 11, fontWeight: 600,
          background: enrichState === 'running' ? 'rgba(59,130,246,0.08)' : enrichState === 'done' ? 'rgba(34,197,94,0.08)' : 'rgba(239,68,68,0.08)',
          border: `1px solid ${enrichState === 'running' ? 'rgba(59,130,246,0.25)' : enrichState === 'done' ? 'rgba(34,197,94,0.25)' : 'rgba(239,68,68,0.25)'}`,
          color: enrichState === 'running' ? '#60A5FA' : enrichState === 'done' ? '#4ADE80' : '#F87171' }}>
          {enrichState === 'running' && `Running enrichment pipeline... current step: ${enrichStep}`}
          {enrichState === 'done' && enrichResult && (
            <>Pipeline complete: {Object.entries(enrichResult.steps || {}).map(([k, v]) => `${k}=${v}`).join(' | ')}</>
          )}
          {enrichState === 'error' && enrichResult && (
            <>Pipeline finished with issues: {Object.entries(enrichResult.steps || {}).filter(([, v]) => v !== 'ok').map(([k, v]) => `${k}=${v}`).join(' | ')}</>
          )}
        </div>
      )}

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

      {/* Operator verdict summary bar */}
      {pending.length > 0 && (
        <div style={{ display: 'flex', gap: 8, marginBottom: 10, flexWrap: 'wrap', padding: '6px 0', alignItems: 'center' }}>
          {[
            { label: 'Ready', value: summary.ready_count ?? 0, color: '#22C55E', icon: '\u2705' },
            { label: 'Need Action', value: summary.needs_review_count ?? 0, color: '#F59E0B', icon: '\u26a0\ufe0f' },
            { label: 'Stale Quote', value: summary.stale_count ?? 0, color: '#F97316', icon: '\ud83d\udd70' },
            { label: 'Entry Missed', value: summary.entry_missed_count ?? 0, color: '#EF4444', icon: '\u26d4' },
          ].map(m => (
            <div key={m.label} style={{ padding: '4px 10px', borderRadius: 6, background: 'var(--bg1)', border: '1px solid var(--border)', textAlign: 'center', minWidth: 70 }}>
              <div style={{ fontSize: 7, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '0.3px' }}>{m.icon} {m.label}</div>
              <div style={{ fontSize: 14, fontWeight: 700, color: m.color, fontFamily: 'monospace' }}>{m.value}</div>
            </div>
          ))}
          {/* Dismiss All Entry Missed button */}
          {(summary.entry_missed_count ?? 0) > 0 && (
            <button onClick={async () => {
              const missed = pending.filter((p: any) => p.operator_verdict === 'ENTRY_MISSED')
              for (const p of missed) await act(p.id, 'reject')
            }} style={{ padding: '5px 10px', fontSize: 9, fontWeight: 600, borderRadius: 5, cursor: 'pointer', color: 'var(--red)', background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.3)' }}>
              Dismiss All Entry Missed
            </button>
          )}
        </div>
      )}

      {/* Pipeline health message */}
      {summary.pipeline_health_message && (
        <div style={{ padding: '8px 14px', marginBottom: 10, borderRadius: 6, fontSize: 11,
          background: 'rgba(251,191,36,0.08)', border: '1px solid rgba(251,191,36,0.25)', color: '#F59E0B' }}>
          {summary.pipeline_health_message}
        </div>
      )}

      {/* Proposal list */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 14, overflow: 'visible' }}>
        {displayed.length === 0 ? (
          <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 8, padding: 24, textAlign: 'center', color: 'var(--text3)', fontSize: 12 }}>
            {pending.length === 0 ? (
              <>
                No pending proposals.
                {runHealth?.latest_run ? (
                  <div style={{ marginTop: 8, fontSize: 10, color: '#64748B', lineHeight: 1.6 }}>
                    <div>Latest run: {runHealth.latest_run.run_label} &middot; {runHealth.latest_run.status} &middot; {runHealth.latest_run.symbols_scanned} scanned &middot; {runHealth.latest_run.go_count} GO</div>
                  </div>
                ) : (
                  <div style={{ marginTop: 6, fontSize: 10, color: '#94A3B8' }}>
                    The system generates proposals automatically when GO signals appear in the morning scan.
                  </div>
                )}
              </>
            ) : (
              <>No proposals match current filters. {pending.length} pending total.</>
            )}
          </div>
        ) : displayed.map((p: any) => (
          <ProposalCard key={p.id} p={p} act={act} acting={acting} />
        ))}
      </div>
    </div>
  )
}
