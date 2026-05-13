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

  // Compact computed values
  const curPrice = p.current_price_display || p.current_price || p.scan_price || p.live_price_at_execution
  const driftPct = p.price_drift_display ?? (curPrice && entry > 0 ? Math.round((curPrice - entry) / entry * 1000) / 10 : null)
  const driftColor = Math.abs(driftPct || 0) < 2 ? '#22C55E' : Math.abs(driftPct || 0) < 5 ? '#F59E0B' : '#EF4444'
  const rsiVal = p.rsi ?? (p.technical_snapshot || {}).rsi_14
  const rsiColor = rsiVal ? (rsiVal < 60 ? '#22C55E' : rsiVal < 72 ? '#F59E0B' : '#EF4444') : '#64748B'
  const rvol = p.rvol || p.scan_rvol
  const rvolColor = rvol ? (rvol >= 3 ? '#22C55E' : rvol >= 1.5 ? '#F59E0B' : '#EF4444') : '#64748B'
  const verdictColors: Record<string, { bg: string; text: string }> = {
    green: { bg: 'rgba(34,197,94,0.15)', text: '#22C55E' },
    yellow: { bg: 'rgba(251,191,36,0.12)', text: '#F59E0B' },
    orange: { bg: 'rgba(249,115,22,0.12)', text: '#F97316' },
    red: { bg: 'rgba(239,68,68,0.12)', text: '#EF4444' },
  }
  const vc = verdictColors[p.operator_verdict_color] || verdictColors.yellow
  const thesis = p.agent_narrative || p.approve_case || ''
  const thesisLine = thesis.split('.').slice(0, 2).join('.').slice(0, 160) || `Score ${p.signal_score || '?'}, ${p.catalyst_verified ? 'verified catalyst' : 'unverified catalyst'}. ${p.sector || ''}`
  const lpt = p.live_price_timestamp_display || { text: 'Never', color: 'red' }
  const ard = p.ai_review_completed_at_display || { text: 'Never', color: 'red' }
  const rgd = p.risk_gate_display || { text: 'Not checked', color: 'red' }

  const [showDetails, setShowDetails] = useState(false)

  return (
    <div style={{
      background: 'var(--bg1)', borderRadius: 8, marginBottom: 12,
      border: `1px solid rgba(255,255,255,0.07)`,
      borderLeft: `4px solid ${vc.text}`,
      opacity: p.operator_verdict === 'ENTRY_MISSED' ? 0.6 : 1,
    }}>
      {showConfirm && <ConfirmModal p={p} onConfirm={handleConfirmApprove} onCancel={() => setShowConfirm(false)} />}

      {/* ROW 1 — STATUS BAR (colored by verdict) */}
      <div style={{ padding: '8px 14px', background: vc.bg, borderBottom: `1px solid ${vc.text}30`, display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 4, borderRadius: '6px 6px 0 0' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <span style={{ fontSize: 10, fontWeight: 700, color: vc.text }}>{p.operator_verdict === 'READY' ? '\u2705' : p.operator_verdict === 'ENTRY_MISSED' ? '\u26d4' : p.operator_verdict === 'STALE_QUOTE' ? '\ud83d\udd70' : '\u26a0\ufe0f'} {(p.operator_verdict || 'REVIEW').replace(/_/g, ' ')}</span>
          <span style={{ fontSize: 15, fontWeight: 800, color: 'var(--text0)', ...mono }}>{p.symbol}</span>
          <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--text1)' }}>{p.strategy_id}</span>
          {p.signal_grade && <span style={pill(p.signal_grade === 'A' || p.signal_grade === 'A+' ? 'green' : p.signal_grade === 'B' ? 'amber' : 'red')}>{p.signal_grade} {p.signal_score}pts</span>}
          {p.strategy_trade_count > 0 && <span style={{ fontSize: 9, color: (p.strategy_win_rate ?? 0) >= 50 ? '#22C55E' : '#F59E0B', fontWeight: 600 }}>{p.strategy_win_rate}% WR</span>}
        </div>
        <span style={{ fontSize: 9, fontWeight: 600, color: p.age_color === 'green' ? '#22C55E' : p.age_color === 'red' ? '#EF4444' : '#F59E0B', ...mono }}>{p.age_display || ''}</span>
      </div>
      {/* Verdict reason */}
      <div style={{ padding: '4px 14px 6px', fontSize: 10, color: vc.text, background: `${vc.bg}80` }}>{p.operator_verdict_reason || bannerText}</div>

      {/* ROW 2 — KEY NUMBERS */}
      <div style={{ padding: '8px 14px', borderBottom: '1px solid var(--border)', display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', gap: 6, fontSize: 11, ...mono }}>
        <div><div style={lbl}>Entry</div><div style={{ fontWeight: 700, color: 'var(--text0)' }}>${Number(entry).toFixed(2)}</div></div>
        <div><div style={lbl}>Current</div><div style={{ fontWeight: 700, color: driftColor }}>${curPrice ? Number(curPrice).toFixed(2) : '--'}{driftPct != null ? ` (${driftPct > 0 ? '+' : ''}${driftPct.toFixed(1)}%)` : ''}</div></div>
        <div><div style={lbl}>Stop</div><div style={{ fontWeight: 700, color: '#EF4444' }}>${Number(stop).toFixed(2)}</div></div>
        <div><div style={lbl}>Target</div><div style={{ fontWeight: 700, color: '#22C55E' }}>${Number(target).toFixed(2)}</div></div>
      </div>

      {/* ROW 3 — TRADE METRICS */}
      <div style={{ padding: '6px 14px', borderBottom: '1px solid var(--border)', display: 'flex', gap: 16, fontSize: 10, ...mono, color: 'var(--text2)', flexWrap: 'wrap' }}>
        <span>R:R <strong style={{ color: computedRR >= 2 ? '#22C55E' : computedRR >= 1.5 ? '#F59E0B' : '#EF4444' }}>{computedRR.toFixed(1)}x</strong></span>
        <span>Risk <strong>${computedRisk.toFixed(0)}</strong></span>
        <span>Shares <strong>{shares.toLocaleString()}</strong></span>
        {rvol && <span>RVOL <strong style={{ color: rvolColor }}>{Number(rvol).toFixed(1)}x</strong></span>}
        {rsiVal && <span>RSI <strong style={{ color: rsiColor }}>{Number(rsiVal).toFixed(0)}</strong></span>}
      </div>

      {/* ROW 4 — VALIDATION TIMESTAMPS */}
      <div style={{ padding: '5px 14px', borderBottom: '1px solid var(--border)', display: 'flex', gap: 14, fontSize: 9, color: 'var(--text3)', flexWrap: 'wrap' }}>
        <span>Created: <strong style={{ color: p.age_color === 'green' ? '#22C55E' : p.age_color === 'red' ? '#EF4444' : '#F59E0B' }}>{p.age_display || '--'}</strong></span>
        <span>Price check: <strong style={{ color: lpt.color === 'green' ? '#22C55E' : lpt.color === 'red' ? '#EF4444' : '#F59E0B' }}>{lpt.text}</strong></span>
        <span>AI review: <strong style={{ color: ard.color === 'green' ? '#22C55E' : ard.color === 'red' ? '#EF4444' : '#F59E0B' }}>{ard.text}</strong></span>
        <span>Risk gate: <strong style={{ color: rgd.color === 'green' ? '#22C55E' : rgd.color === 'red' ? '#EF4444' : '#F59E0B' }}>{rgd.text}</strong></span>
      </div>

      {/* ROW 5 — ONE LINE THESIS */}
      <div style={{ padding: '6px 14px', borderBottom: '1px solid var(--border)', fontSize: 10, color: 'var(--text2)', lineHeight: 1.4, maxHeight: 36, overflow: 'hidden' }}>{thesisLine}</div>

      {/* ROW 6 — ACTION BUTTONS */}
      <div style={{ padding: '8px 14px', display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
        <button onClick={() => runAction('refreshPrice', `/api/v2/paper-proposals/refresh-data`, { proposal_id: p.id })} disabled={runningAction !== null}
          style={{ ...btnStyle('rgba(59,130,246,0.15)', '#60A5FA'), border: '1px solid rgba(59,130,246,0.3)', fontSize: 9 }}>
          {runningAction === 'refreshPrice' ? 'Refreshing...' : '\u21bb Refresh Price'}
        </button>
        <button onClick={() => runAction('checkExec', `/api/v2/paper-proposals/check-execution-readiness`, { proposal_id: p.id })} disabled={runningAction !== null}
          style={{ ...btnStyle('rgba(168,85,247,0.15)', '#A855F7'), border: '1px solid rgba(168,85,247,0.3)', fontSize: 9 }}>
          {runningAction === 'checkExec' ? 'Checking...' : '\u2699 Check Execution'}
        </button>
        <button onClick={() => runAction('aiReview', `/api/v2/paper-proposals/run-ai-review`, { proposal_id: p.id })} disabled={runningAction !== null}
          style={{ ...btnStyle('rgba(168,85,247,0.15)', '#A855F7'), border: '1px solid rgba(168,85,247,0.3)', fontSize: 9 }}>
          {runningAction === 'aiReview' ? 'Running...' : '\ud83e\udde0 AI Review'}
        </button>
        <div style={{ flex: 1 }} />
        <button onClick={handleApprove} disabled={approveDisabled && !canApproveWithConfirm}
          title={p.operator_verdict !== 'READY' ? (p.operator_verdict_reason || 'Not ready') : 'Approve for paper test'}
          style={{ ...btnStyle(p.operator_verdict === 'READY' ? '#22C55E' : 'rgba(148,163,184,0.2)', p.operator_verdict === 'READY' ? '#fff' : '#94A3B8'), fontSize: 10, padding: '5px 14px', border: p.operator_verdict === 'READY' ? 'none' : '1px solid rgba(148,163,184,0.3)' }}>
          {acting[p.id] === 'approve' ? 'Approving...' : '\u2713 Approve'}
        </button>
        <button onClick={() => act(p.id, 'reject')} style={{ ...btnStyle('rgba(239,68,68,0.12)', '#EF4444'), fontSize: 10, border: '1px solid rgba(239,68,68,0.3)' }}>
          {acting[p.id] === 'reject' ? 'Rejecting...' : '\u2717 Reject'}
        </button>
        <button onClick={() => setShowDetails(!showDetails)}
          style={{ fontSize: 9, padding: '4px 8px', background: 'none', border: '1px solid var(--border)', borderRadius: 4, color: 'var(--text3)', cursor: 'pointer' }}>
          {showDetails ? '\u25b2 Hide' : '\u25bc Details'}
        </button>
      </div>

      {/* FULL DETAILS DRAWER (collapsed by default) */}
      {showDetails && (
        <div style={{ padding: '10px 14px', borderTop: '1px solid var(--border)', background: 'rgba(0,0,0,0.15)' }}>
          {/* Pipeline step badges */}
          <PipelineChevron stages={p.pipeline_stages || []} />

          {/* Support / Reject case */}
          {p.approve_case && (
            <div style={{ marginTop: 8 }}><div style={secLbl}>Support Case</div><div style={{ fontSize: 10, color: 'var(--text2)', padding: '6px 8px', background: 'var(--bg0)', borderRadius: 4, lineHeight: 1.5 }}>{p.approve_case}</div></div>
          )}
          {p.reject_case && (
            <div style={{ marginTop: 8 }}><div style={secLbl}>Reject Case</div><div style={{ fontSize: 10, color: 'var(--text2)', padding: '6px 8px', background: 'var(--bg0)', borderRadius: 4, lineHeight: 1.5 }}>{p.reject_case}</div></div>
          )}

          {/* Technical context */}
          <div style={{ marginTop: 8, display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 6 }}>
            {[
              { l: 'RSI', v: rsiVal ? Number(rsiVal).toFixed(0) : '--' },
              { l: 'ATR', v: p.atr ? `$${Number(p.atr).toFixed(2)}` : '--' },
              { l: 'RVOL', v: rvol ? `${Number(rvol).toFixed(1)}x` : '--' },
              { l: 'Confluence', v: p.confluence_tier || p.confluence_score || '--' },
            ].map(m => kv(m.l, m.v))}
          </div>

          {/* Agent reviews */}
          {p.agent_reviews?.length > 0 && (
            <div style={{ marginTop: 8 }}>
              <div style={secLbl}>Agent Reviews ({p.agent_reviews.length})</div>
              {p.agent_reviews.map((ar: any, i: number) => (
                <div key={i} style={{ fontSize: 9, color: 'var(--text2)', marginBottom: 2 }}>
                  <strong>{ar.agent_name || ar.agent}</strong>: {ar.verdict || ar.vote} ({ar.confidence}%) — {(ar.summary || ar.reasoning || '').slice(0, 100)}
                </div>
              ))}
            </div>
          )}

          {/* Missing data */}
          {(p.missing_data || []).length > 0 && (
            <div style={{ marginTop: 8 }}><div style={secLbl}>Missing ({(p.missing_data || []).length})</div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>{(p.missing_data || []).map((m: string, i: number) => <span key={i} style={{ ...pill('red'), fontSize: 8 }}>{m}</span>)}</div>
            </div>
          )}

          {/* Enrichment actions */}
          <div style={{ marginTop: 10, display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            <button onClick={() => runAction('enrich', `/api/v2/paper-proposals/enrich-all`, { proposal_id: p.id })} style={{ ...btnStyle('rgba(148,163,184,0.1)', '#94A3B8'), fontSize: 9, border: '1px solid var(--border)' }}>Enrich All</button>
            <button onClick={() => runAction('research', `/api/v2/paper-proposals/run-research`, { proposal_id: p.id })} style={{ ...btnStyle('rgba(148,163,184,0.1)', '#94A3B8'), fontSize: 9, border: '1px solid var(--border)' }}>Run Research</button>
            <button onClick={() => runAction('backtest', `/api/v2/paper-proposals/run-backtest`, { proposal_id: p.id })} style={{ ...btnStyle('rgba(148,163,184,0.1)', '#94A3B8'), fontSize: 9, border: '1px solid var(--border)' }}>Run Backtest</button>
            <button onClick={() => runAction('indicators', `/api/v2/paper-proposals/run-indicators`, { proposal_id: p.id })} style={{ ...btnStyle('rgba(148,163,184,0.1)', '#94A3B8'), fontSize: 9, border: '1px solid var(--border)' }}>Run Indicators</button>
            {p.tos_order_string && (
              <button onClick={() => { navigator.clipboard.writeText(p.tos_order_string); alert('TOS copied') }}
                style={{ ...btnStyle('var(--bg0)', 'var(--text2)'), border: '1px solid var(--border)', fontSize: 9 }}>Copy TOS</button>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

// NOTE: Old ProposalCard content replaced with compact 6-row layout.
// PipelineChevron, LifecycleBadge, BlockerBanner still used in details drawer.
// All removed from previous code below this marker. Functions kept for compatibility.
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
