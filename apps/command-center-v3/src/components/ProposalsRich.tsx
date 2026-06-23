import React, { useState, useCallback, lazy, Suspense } from 'react'
import { useApi } from '../hooks/useApi'
import { exitLadder, planWarnings, MONITOR_RULES } from '../lib/exitLadder'
import { StatusBadge } from './StatusBadge'
import { StateCard } from './StateCard'
import { ActionButton } from './ActionButton'
import BrokerPromoteModal from './BrokerPromoteModal'
import BrokerDiligenceStrip from './BrokerDiligenceStrip'
import { isBrokerRouted, routingColor, routingLabel } from '../lib/proposalRouting'
import ExecutionPathsStrip from './ExecutionPathsStrip'
import ProposalSourceBadges from './ProposalSourceBadges'
const ScreenerConfigModal = lazy(() => import('./ScreenerConfigModal'))

// Full v2-parity proposal review surface, ported into v3 (canonical).
// Same /api/v2/paper-proposals contract + write workflow as the frozen v2 page.

const mono: React.CSSProperties = { fontFamily: 'monospace' }

// -- Style helpers --
const lbl: React.CSSProperties = { fontSize: 8, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '0.3px' }
const secLbl: React.CSSProperties = { fontSize: 10, color: 'var(--text3)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: 6, marginTop: 14 }
const kv = (label: string, value: any, color?: string) => (
  <div key={label}>
    <div style={lbl}>{label}</div>
    <div style={{ fontSize: 11, color: color || 'var(--text0)', fontWeight: 600, ...mono }}>{value ?? '--'}</div>
  </div>
)

// -- Action-state color map --
const ACTION_COLORS: Record<string, { bg: string; text: string; border: string }> = {
  PAPER_READY:   { bg: 'rgba(34,197,94,0.15)',  text: 'var(--green)', border: 'rgba(34,197,94,0.35)' },
  CAUTION:       { bg: 'rgba(251,191,36,0.12)', text: '#F59E0B',     border: 'rgba(251,191,36,0.3)' },
  BLOCKED:       { bg: 'rgba(239,68,68,0.15)',  text: 'var(--red)',   border: 'rgba(239,68,68,0.3)' },
  NEEDS_REVIEW:  { bg: 'rgba(59,130,246,0.15)', text: '#60A5FA',     border: 'rgba(59,130,246,0.3)' },
  MISSING_DATA:  { bg: 'rgba(148,163,184,0.15)',text: '#94A3B8',     border: 'rgba(148,163,184,0.3)' },
  LEARNING_MODE: { bg: 'rgba(251,191,36,0.12)', text: '#F59E0B',     border: 'rgba(251,191,36,0.3)' },
}

// Status mapping for action states
const actionStateToStatus: Record<string, string> = {
  PAPER_READY: 'ready', CAUTION: 'warning', BLOCKED: 'blocked',
  NEEDS_REVIEW: 'waiting', MISSING_DATA: 'stale', LEARNING_MODE: 'paused',
}

// -- Normalizer --
const KEY_FIELDS = [
  'catalyst', 'catalyst_confidence', 'technical_context', 'technical_snapshot',
  'agent_reviews', 'llm_analysis', 'backtest_summary', 'execution_readiness',
  'strategy_fit', 'proposed_entry', 'proposed_stop', 'proposed_target1',
  'proposed_shares', 'signal_score', 'signal_grade', 'news',
]

function normalizeProposal(p: any) {
  const er = p.execution_readiness || {}
  const missingData: string[] = Array.isArray(p.missing_data) ? p.missing_data : []
  const blockers: string[] = Array.isArray(er.blockers) ? er.blockers : []

  let actionState = 'CAUTION'
  const readinessState = String(er.readiness_state || '').toUpperCase()
  if (readinessState.includes('BLOCKED')) {
    actionState = 'BLOCKED'
  } else if (missingData.length >= 4 && !readinessState.includes('BLOCKED')) {
    actionState = 'MISSING_DATA'
  } else if (readinessState === 'READY_FOR_PAPER_SUBMIT' || readinessState === 'READY_ORB_CONFIRMED') {
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

  const topBlocker = blockers.length > 0 ? blockers[0] : 'None'
  const primaryStrategy = p.strategy_id || 'unknown'
  const strategyMismatch = p.primary_strategy_id != null && p.primary_strategy_id !== p.strategy_id

  const nextActions: string[] = []
  const _nTc = typeof p.technical_context === 'string' ? JSON.parse(p.technical_context || '{}') : (p.technical_context || {})
  const _nTs = p.technical_snapshot || {}
  if (!(_nTs.rsi_14 ?? _nTc.rsi) && !(_nTs.atr_14 ?? _nTc.atr)) nextActions.push('Run Technical Snapshot')
  if (!p.agent_reviews?.length && !p.llm_analysis) nextActions.push('Run AI Review')
  if (!p.catalyst || !p.news?.length) nextActions.push('Run Research')
  if (!p.execution_readiness) nextActions.push('Check Execution Readiness')
  if (er.quote_age_seconds != null && Number(er.quote_age_seconds) > 300) nextActions.push('Check Execution during market hours')
  if (!p.backtest_summary) nextActions.push('Run Backtest')

  let filledCount = 0
  for (const f of KEY_FIELDS) {
    const v = p[f]
    if (v != null && v !== '' && !(Array.isArray(v) && v.length === 0) && !(typeof v === 'object' && !Array.isArray(v) && Object.keys(v).length === 0)) {
      filledCount++
    }
  }
  const dataCompleteness = Math.round((filledCount / KEY_FIELDS.length) * 100)

  return { actionState, topBlocker, primaryStrategy, strategyMismatch, nextActions, dataCompleteness }
}

// -- Metric tile component (read-only display) --
function MetricTile({ label, value, status, tileColor }: {
  label: string; value: string; status: string; tileColor: 'green' | 'amber' | 'red' | 'gray'
}) {
  const colors = {
    green: { bg: 'rgba(34,197,94,0.08)', border: 'rgba(34,197,94,0.25)', text: 'var(--green)' },
    amber: { bg: 'rgba(251,191,36,0.08)', border: 'rgba(251,191,36,0.25)', text: '#F59E0B' },
    red:   { bg: 'rgba(239,68,68,0.08)',  border: 'rgba(239,68,68,0.25)',  text: 'var(--red)' },
    gray:  { bg: 'rgba(148,163,184,0.06)',border: 'rgba(148,163,184,0.15)',text: '#94A3B8' },
  }
  const c = colors[tileColor]
  return (
    <div style={{ padding: '6px 8px', background: c.bg, border: `1px solid ${c.border}`, borderRadius: 6, textAlign: 'center', minWidth: 0 }}>
      <div style={{ fontSize: 7, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '0.3px', marginBottom: 2 }}>{label}</div>
      <div style={{ fontSize: 13, fontWeight: 700, color: c.text, ...mono }}>{value}</div>
      <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 2, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{status}</div>
    </div>
  )
}

// -- Confirm modal --
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
          <ActionButton variant="secondary" size="md" onClick={onCancel}>Cancel</ActionButton>
          <ActionButton variant="primary" size="md" onClick={onConfirm} style={{ background: 'var(--amber)', color: '#000' }}>Approve as paper-learning test</ActionButton>
        </div>
      </div>
    </div>
  )
}

// -- Timeframe pill colors --
const TIMEFRAME_COLORS: Record<string, { bg: string; text: string }> = {
  intraday: { bg: 'rgba(249,115,22,0.15)', text: '#F97316' },
  short_swing: { bg: 'rgba(59,130,246,0.15)', text: '#60A5FA' },
  medium_swing: { bg: 'rgba(99,102,241,0.15)', text: '#818CF8' },
  event_window: { bg: 'rgba(168,85,247,0.15)', text: '#A855F7' },
  position: { bg: 'rgba(34,197,94,0.15)', text: '#22C55E' },
}

// -- Pipeline chevron (8 stages) --
function PipelineChevron({ stages }: { stages: any[] }) {
  if (!stages || stages.length === 0) return null
  const statusIcon: Record<string, { icon: string; color: string }> = {
    DONE: { icon: '✓', color: '#22C55E' },
    ISSUE: { icon: '⚠', color: '#F59E0B' },
    PENDING: { icon: '○', color: '#14B8A6' },
    SKIPPED: { icon: '—', color: '#64748B' },
  }
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 2, padding: '6px 16px', borderBottom: '1px solid var(--border)', overflowX: 'auto' }}>
      {stages.map((s: any, i: number) => {
        const si = statusIcon[s.status] || statusIcon.PENDING
        return (
          <React.Fragment key={s.id}>
            {i > 0 && <span style={{ fontSize: 8, color: 'var(--text3)', margin: '0 1px', flexShrink: 0 }}>{'→'}</span>}
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

// -- Proposal card --
function ProposalCard({ p, act, acting, symCard, onRefetch }: { p: any; act: (id: number, action: string, overrides?: any) => void; acting: Record<number, string>; symCard?: any; onRefetch?: () => void }) {
  const { data: extIntel } = useApi<any>(`/api/v2/hermes/subject-intel?type=proposal&key=${p.symbol}`, 120_000)
  const extOpinions: any[] = extIntel?.external_intel ?? []
  const hermes = extIntel?.hermes
  // Level-2 book pressure (read-only advisory evidence from the Schwab stream capture — never a trigger)
  const { data: l2raw } = useApi<any>(`/api/v2/schwab/stream/book?symbol=${p.symbol}`, 60_000)
  const l2 = l2raw?.data ?? l2raw
  const l2p = l2?.pressure_15m
  const [shares] = useState(p.proposed_shares || 0)
  const [entry] = useState(p.proposed_entry || 0)
  const [stop] = useState(p.proposed_stop || 0)
  const [target] = useState(p.proposed_target1 || 0)
  const [showConfirm, setShowConfirm] = useState(false)
  const [showBrokerPromote, setShowBrokerPromote] = useState(false)
  const [runningAction, setRunningAction] = useState<string | null>(null)
  const bd = p.broker_diligence
  const brokerDiligenceBlocked = bd && (bd.status === 'BLOCK' || bd.status === 'PENDING')

  const norm = normalizeProposal(p)

  const computedRisk = Math.abs(entry - stop) * shares
  const riskPS = Math.abs(entry - stop)
  const computedRR = riskPS > 0 ? (target - entry) / riskPS : 0
  const isModified = false

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

  // Build metric tiles
  const er = p.execution_readiness || {}
  const bt = typeof p.backtest_summary === 'string' ? JSON.parse(p.backtest_summary || '{}') : (p.backtest_summary || {})
  const sf = p.strategy_fit || {}
  const agentReviews = (p.agent_reviews || []).filter((ar: any) => ar.verdict)
  const rr = p.proposed_rr || (riskPS > 0 ? (target - entry) / riskPS : 0)

  const ts = p.technical_snapshot || {}
  const tiles: { label: string; value: string; status: string; tileColor: 'green' | 'amber' | 'red' | 'gray' }[] = [
    {
      label: 'Strategy Fit',
      value: sf.fit_score != null ? `${sf.fit_score}` : '--',
      status: sf.fit_grade || (sf.fit_score != null ? (sf.fit_score >= 80 ? 'Strong fit' : sf.fit_score >= 60 ? 'Good fit' : 'Weak fit') : 'Run analysis'),
      tileColor: sf.fit_score >= 80 ? 'green' : sf.fit_score >= 60 ? 'amber' : sf.fit_score != null ? 'red' : 'gray',
    },
    {
      label: 'Execution',
      value: er.readiness_score != null ? `${er.readiness_score}` : '--',
      status: er.readiness_state ? er.readiness_state.replace(/^BLOCKED_/, '').replace(/_/g, ' ').slice(0, 18) : 'Check readiness',
      tileColor: er.readiness_state === 'READY_FOR_PAPER_SUBMIT' || er.readiness_state === 'READY_ORB_CONFIRMED' ? 'green' : er.readiness_state === 'CAUTION_EXECUTABLE' ? 'amber' : er.readiness_state ? 'red' : 'gray',
    },
    {
      label: 'Technical',
      value: ts.technical_grade || (ts.rsi_14 != null ? 'OK' : '--'),
      status: ts.rsi_14 != null ? `RSI ${Number(ts.rsi_14).toFixed(0)} ATR $${Number(ts.atr_14 || 0).toFixed(2)}` : 'Run snapshot',
      tileColor: ts.technical_grade === 'TECH_STRONG' ? 'green' : ts.technical_grade === 'TECH_OK' || ts.technical_grade === 'TECH_MIXED' ? 'amber' : ts.rsi_14 != null ? 'amber' : 'gray',
    },
    {
      label: 'Catalyst',
      value: p.catalyst_quality?.catalyst_quality_score != null ? `${p.catalyst_quality.catalyst_quality_score}%` : p.catalyst_verified ? 'Yes' : '--',
      status: p.catalyst_quality?.catalyst_grade || (p.catalyst_verified ? 'Verified' : 'Unverified'),
      tileColor: p.catalyst_quality?.catalyst_quality_score >= 70 ? 'green' : p.catalyst_verified ? 'green' : p.catalyst ? 'amber' : 'gray',
    },
    {
      label: 'R:R',
      value: rr > 0 ? `${Number(rr).toFixed(1)}:1` : '--',
      status: rr >= 2.5 ? 'Excellent' : rr >= 2 ? 'Meets 2:1 min' : rr > 0 ? 'Below 2:1 min' : 'Not set',
      tileColor: rr >= 2.5 ? 'green' : rr >= 2 ? 'green' : rr > 0 ? 'red' : 'gray',
    },
    {
      // LLM entry zone (operator 2026-06-12: "entry price range like the watchlist") — grok validates
      // inline at proposal creation; advisory only, the proposed entry itself is untouched.
      label: '🎯 Entry Zone',
      value: p.entry_zone_low != null ? `${Number(p.entry_zone_low).toFixed(2)}–${Number(p.entry_zone_high).toFixed(2)}` : '--',
      status: p.entry_zone_low != null
        ? `lim ${Number(p.entry_plan_limit).toFixed(2)} · ${p.entry_urgency} · ${p.entry_tag} (${p.entry_model})`
        : 'awaiting LLM validation',
      tileColor: p.entry_urgency === 'ready' ? 'green' : p.entry_urgency === 'near_entry' ? 'amber' : p.entry_zone_low != null ? 'gray' : 'gray',
    },
    {
      label: 'Agents',
      value: agentReviews.length > 0 ? `${agentReviews.length}` : '--',
      status: agentReviews.length > 0
        ? `${agentReviews.filter((a: any) => a.verdict?.includes('CAUTIOUS') || a.verdict?.includes('APPROVE')).length}/${agentReviews.length} cautious+`
        : 'Run AI review',
      tileColor: agentReviews.length >= 3 ? 'green' : agentReviews.length > 0 ? 'amber' : 'gray',
    },
    {
      label: 'Backtest',
      value: bt.sample_size ? `n=${bt.sample_size}` : '--',
      status: bt.sample_size >= 20 ? `${(Number(bt.win_rate || 0) * 100).toFixed(0)}% WR` : bt.sample_size ? 'Learning mode' : 'Run backtest',
      tileColor: bt.sample_size >= 20 && Number(bt.win_rate || 0) >= 0.55 ? 'green' : bt.sample_size ? 'amber' : 'gray',
    },
    {
      label: 'Data',
      value: `${norm.dataCompleteness}%`,
      status: (p.missing_data || []).length > 0 ? `${(p.missing_data || []).length} gaps` : 'Complete',
      tileColor: norm.dataCompleteness >= 90 ? 'green' : norm.dataCompleteness >= 70 ? 'amber' : norm.dataCompleteness > 0 ? 'red' : 'gray',
    },
  ]

  const effectiveActionState = p.action_state || norm.actionState
  const effectiveTopBlocker = p.top_blocker || norm.topBlocker
  const effectiveNextActions: string[] = p.next_actions || norm.nextActions

  let bannerText = ''
  let bannerDetail = ''
  if (effectiveActionState === 'BLOCKED') {
    bannerText = `BLOCKED -- ${effectiveTopBlocker}`
    bannerDetail = effectiveNextActions.length > 0 ? `Next: ${effectiveNextActions[0]}` : ''
  } else if (effectiveActionState === 'PAPER_READY') {
    bannerText = 'PAPER READY -- All gates pass. Review thesis before submitting.'
    bannerDetail = ''
  } else if (effectiveActionState === 'MISSING_DATA') {
    bannerText = `MISSING DATA -- ${p.action_label || `${(p.missing_data || []).length} fields missing`}`
    bannerDetail = effectiveNextActions.length > 0 ? `Next: ${effectiveNextActions.join(', ')}` : ''
  } else if (effectiveActionState === 'NEEDS_REVIEW') {
    bannerText = `NEEDS REVIEW -- ${p.action_label || 'Agent or data review pending'}`
    bannerDetail = norm.nextActions.length > 0 ? `Next: ${norm.nextActions[0]}` : ''
  } else if (norm.actionState === 'LEARNING_MODE') {
    bannerText = 'LEARNING MODE -- Cautious paper test, not fully validated'
    bannerDetail = ''
  } else {
    bannerText = `CAUTION -- ${norm.topBlocker !== 'None' ? norm.topBlocker : 'Review data before proceeding'}`
    bannerDetail = norm.nextActions.length > 0 ? `Next: ${norm.nextActions[0]}` : ''
  }

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
      {showBrokerPromote && (
        <BrokerPromoteModal
          seed={{ proposal_id: p.id, symbol: p.symbol }}
          onClose={() => setShowBrokerPromote(false)}
          onPromoted={() => { onRefetch?.(); setShowBrokerPromote(false) }}
        />
      )}

      {/* A. HEADER */}
      <div style={{ padding: '8px 14px', background: vc.bg, borderBottom: `1px solid ${vc.text}30`, display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 4, borderRadius: '6px 6px 0 0' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <StatusBadge status={actionStateToStatus[effectiveActionState] || 'warning'} label={(p.operator_verdict || 'REVIEW').replace(/_/g, ' ')} />
          <span style={{ fontSize: 15, fontWeight: 800, color: 'var(--text0)', ...mono }}>{p.symbol}</span>
          <span title="Execution route — set via Promote to Broker or approve to paper"
            style={{ fontSize: 8, fontWeight: 700, padding: '1px 6px', borderRadius: 3,
              background: `${routingColor(p)}22`, color: routingColor(p), border: `1px solid ${routingColor(p)}44` }}>
            {routingLabel(p)}
          </span>
          <ProposalSourceBadges proposal={p} size="sm" />
          {p.signal_evidence?.screener && (
            <span title={`Why this signal won (arbitration evidence)\nlist: ${p.signal_evidence.screener}${p.signal_evidence.source_weight ? ` · source weight ${p.signal_evidence.source_weight}` : ''}${p.signal_evidence.source_hit_rate ? ` · hit ${(p.signal_evidence.source_hit_rate * 100).toFixed(0)}%` : ''}\ntop pillars: ${(p.signal_evidence.top_pillars || []).map((t: any) => `${t.pillar} ${t.pts}`).join(', ') || '—'}${p.signal_evidence.outcome_scar && p.signal_evidence.outcome_scar !== 1 ? `\noutcome scar ${p.signal_evidence.outcome_scar}` : ''}`}
              style={{ fontSize: 8, fontWeight: 600, padding: '1px 5px', borderRadius: 3, cursor: 'help', background: 'var(--bg2)', color: 'var(--text2)' }}>
              ⛏ {p.signal_evidence.screener}
            </span>
          )}
          {hermes?.rank != null && (
            <span title={`Hermes watchlist intelligence (advisory)\ncomposite ${hermes.composite} · rank #${hermes.rank}\nregime: ${hermes.regime ?? '—'}`}
              style={{ fontSize: 9, fontWeight: 700, padding: '1px 6px', borderRadius: 3, cursor: 'help',
                background: hermes.rank <= 20 ? 'rgba(167,139,250,.15)' : 'var(--bg2)',
                color: hermes.rank <= 20 ? '#A78BFA' : 'var(--text3)' }}>
              H#{hermes.rank}
            </span>
          )}
          {extOpinions.map((e: any, i: number) => <span key={i} title={`${e.lane === 'grok' ? 'Grok' : e.lane === 'chatgpt' ? 'ChatGPT' : e.lane}: ${e.recommendation || ''}\n${e.at ? new Date(e.at).toLocaleString() : ''}`} style={{ fontSize: 9, fontWeight: 700, color: e.lane === 'grok' ? '#1d9bf0' : '#10a37f', cursor: 'help' }}>✦ {e.lane === 'grok' ? 'Grok' : 'ChatGPT'}</span>)}
          <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--text1)' }}>{p.strategy_display_name || p.strategy_id}</span>
          {(p.strategy_type_label || p.strategy_type || p.strategy_timeframe_class) && (
            <span title={[p.strategy_type_label || p.strategy_type, p.strategy_timeframe_display].filter(Boolean).join(' · ')}
              style={{ fontSize: 8, padding: '1px 5px', borderRadius: 3, fontWeight: 700,
                background: (TIMEFRAME_COLORS[(p.strategy_timeframe_class || p.strategy_type || '').toLowerCase()] || { bg: 'rgba(148,163,184,0.12)' }).bg,
                color: (TIMEFRAME_COLORS[(p.strategy_timeframe_class || p.strategy_type || '').toLowerCase()] || { text: '#94A3B8' }).text }}>
              {p.strategy_type_label || String(p.strategy_type || p.strategy_timeframe_class || '').replace(/_/g, ' ')}
            </span>
          )}
          {(p.sector || p.industry) && <span style={{ fontSize: 9, color: 'var(--text3)', fontWeight: 500 }}>{[p.sector, p.industry].filter(Boolean).join(' / ')}</span>}
          {!p.sector && !p.industry && <span style={{ fontSize: 9, color: '#EF4444', fontWeight: 600 }}>Sector: Missing</span>}
          {p.signal_grade && <StatusBadge status={p.signal_grade === 'A' || p.signal_grade === 'A+' ? 'ready' : p.signal_grade === 'B' ? 'warning' : 'blocked'} label={`${p.signal_grade} ${p.signal_score}pts`} />}
          {p.strategy_trade_count > 0 && <span style={{ fontSize: 9, color: (p.strategy_win_rate ?? 0) >= 50 ? '#22C55E' : '#F59E0B', fontWeight: 600 }}>{p.strategy_win_rate}% WR</span>}
          {symCard?.vs_sector_week != null && <span title={`symbol ${symCard.perf_week}% vs ${symCard.sector_etf} ${symCard.sector_perf_week}% (week)`}
            style={{ fontSize: 9, fontWeight: 700, color: symCard.vs_sector_week >= 0 ? '#22c55e' : '#ef4444' }}>
            {symCard.vs_sector_week >= 0 ? '+' : ''}{symCard.vs_sector_week}% vs sector</span>}
          {symCard?.analyst?.rating && <span title={`Yahoo consensus ${symCard.analyst.mean} · target range $${symCard.analyst.target_low}–$${symCard.analyst.target_high}${symCard.analyst.distribution ? ` · votes: ${symCard.analyst.distribution.strong_buy ?? 0} strong buy / ${symCard.analyst.distribution.buy ?? 0} buy / ${symCard.analyst.distribution.hold ?? 0} hold / ${symCard.analyst.distribution.sell ?? 0} sell` : ''}`}
            style={{ fontSize: 9, fontWeight: 600, color: String(symCard.analyst.rating).includes('buy') ? '#22c55e' : 'var(--text2)' }}>
            {String(symCard.analyst.rating).replace('_', ' ')} · {symCard.analyst.opinions} analysts · target ${symCard.analyst.target}{symCard.analyst.upside_pct != null ? ` (${symCard.analyst.upside_pct >= 0 ? '+' : ''}${symCard.analyst.upside_pct}%)` : ''}</span>}
          {l2?.imbalance != null && (
            <span title={`Level-2 book pressure (advisory evidence, never a trigger)\n15m avg imbalance: ${l2p?.avg_imbalance ?? '—'} (${l2p?.read ?? ''})\nbid depth ${l2.bid_depth} / ask depth ${l2.ask_depth}\nbest ${l2.best_bid} × ${l2.best_ask} · ${String(l2.captured_at).slice(11, 19)}`}
              style={{ fontSize: 9, fontWeight: 700, padding: '1px 6px', borderRadius: 3, cursor: 'help',
                background: (l2p?.avg_imbalance ?? l2.imbalance) > 0.2 ? 'rgba(34,197,94,.15)' : (l2p?.avg_imbalance ?? l2.imbalance) < -0.2 ? 'rgba(239,68,68,.15)' : 'var(--bg2)',
                color: (l2p?.avg_imbalance ?? l2.imbalance) > 0.2 ? '#22C55E' : (l2p?.avg_imbalance ?? l2.imbalance) < -0.2 ? '#EF4444' : 'var(--text2)' }}>
              L2 {(l2p?.avg_imbalance ?? l2.imbalance) > 0 ? '+' : ''}{Number(l2p?.avg_imbalance ?? l2.imbalance).toFixed(2)}
            </span>
          )}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          {p.staleness_policy?.is_stale && <StatusBadge status="stale" label="STALE" />}
          <span style={{ fontSize: 9, fontWeight: 600, color: p.age_color === 'green' ? '#22C55E' : p.age_color === 'red' ? '#EF4444' : '#F59E0B', ...mono }}>{p.age_display || ''}</span>
        </div>
      </div>

      {/* what the company does + top-3 news (unified card layer, operator 2026-06-12) */}
      {symCard?.description && (
        <div style={{ padding: '4px 14px 5px', borderBottom: '1px solid var(--border)' }}>
          <div style={{ fontSize: 9.5, color: 'var(--text2)', lineHeight: 1.4 }}>{symCard.description}</div>
          {(symCard.news ?? []).slice(0, 3).map((n: any, i: number) => (
            <div key={i} style={{ fontSize: 9, lineHeight: 1.4, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
              <span style={{ color: 'var(--text3)' }}>{n.source} · {n.at ? `${Math.round((Date.now() - new Date(n.at).getTime()) / 36e5)}h · ` : ''}</span>
              {n.url ? <a href={n.url} target="_blank" rel="noreferrer" style={{ color: '#93c5fd', textDecoration: 'none' }} title={n.title}>{n.title}</a>
                : <span style={{ color: 'var(--text2)' }} title={n.title}>{n.title}</span>}
            </div>
          ))}
        </div>
      )}

      {/* B. DECISION BANNER */}
      <div style={{ padding: '5px 14px 6px', background: `${vc.bg}80`, borderBottom: '1px solid var(--border)' }}>
        <div style={{ fontSize: 10, color: vc.text, fontWeight: 600 }}>{p.operator_verdict_reason || bannerText}</div>
        {(p.approval_blockers || []).length > 0 && (
          <div style={{ marginTop: 3 }}>
            {(p.approval_blockers || []).slice(0, 3).map((b: any, i: number) => (
              <div key={i} style={{ fontSize: 9, color: '#EF4444', marginTop: 1 }}>
                {'•'} {b.reason} {b.action && <span style={{ color: '#60A5FA' }}> -- {b.action}</span>}
              </div>
            ))}
          </div>
        )}
        {effectiveNextActions.length > 0 && (p.approval_blockers || []).length === 0 && bannerDetail && (
          <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 2 }}>{bannerDetail}</div>
        )}
      </div>

      {/* C. WHY THIS SETUP? */}
      {(p.strategy_description || p.catalyst) && (
        <div style={{ padding: '6px 14px', borderBottom: '1px solid var(--border)', fontSize: 10, color: 'var(--text2)', lineHeight: 1.5 }}>
          {p.strategy_description && <div><strong style={{ color: 'var(--text1)', fontSize: 9, textTransform: 'uppercase', letterSpacing: '0.3px' }}>Strategy:</strong> {p.strategy_description}</div>}
          {p.catalyst && <div style={{ marginTop: 2 }}><strong style={{ color: 'var(--text1)', fontSize: 9, textTransform: 'uppercase', letterSpacing: '0.3px' }}>Catalyst:</strong> {p.catalyst_verified ? '✅' : '⚠️'} {typeof p.catalyst === 'string' ? p.catalyst.slice(0, 200) : 'Verified'}</div>}
          {p.other_strategy_count > 0 && <span style={{ fontSize: 9, color: '#F59E0B', fontWeight: 600 }}>+{p.other_strategy_count} other {p.other_strategy_count === 1 ? 'strategy' : 'strategies'}</span>}
        </div>
      )}

      {/* D. TRADE PLAN RATIONALE */}
      <div style={{ padding: '8px 14px', borderBottom: '1px solid var(--border)' }}>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', gap: 6, fontSize: 11, ...mono }}>
          <div><div style={lbl}>Entry</div><div style={{ fontWeight: 700, color: 'var(--text0)' }}>${Number(entry).toFixed(2)}</div></div>
          <div><div style={lbl}>Current</div><div style={{ fontWeight: 700, color: driftColor }}>${curPrice ? Number(curPrice).toFixed(2) : '--'}{driftPct != null ? ` (${driftPct > 0 ? '+' : ''}${driftPct.toFixed(1)}%)` : ''}</div></div>
          <div><div style={lbl}>Stop</div><div style={{ fontWeight: 700, color: '#EF4444' }}>${Number(stop).toFixed(2)}
            {entry > 0 && stop > 0 && <span style={{ color: 'var(--text3)', fontWeight: 400 }}> (−{(Math.abs(entry - stop) / entry * 100).toFixed(1)}%)</span>}</div></div>
          <div><div style={lbl}>Target · R:R</div><div style={{ fontWeight: 700, color: '#22C55E' }}>${Number(target).toFixed(2)}
            {rr ? <span style={{ color: rr >= 2 ? '#22c55e' : rr >= 1.5 ? '#f59e0b' : '#ef4444', fontWeight: 800 }}> · {Number(rr).toFixed(2)}</span> : null}</div></div>
        </div>
        {/* layered exit ladder + plan sanity — same model as Watchlist / Open Trades (operator 2026-06-13) */}
        {(() => {
          const street = Number(symCard?.analyst?.target) > 0 ? Number(symCard.analyst.target) : null
          const ladder = exitLadder(entry || null, stop || null, target || null, street)
          const warns = planWarnings({ entry: entry || null, stop: stop || null, planTarget: target || null,
            rr: rr || null, pctCash: null, streetTarget: street,
            analystUpside: symCard?.analyst?.upside_pct != null ? Number(symCard.analyst.upside_pct) : null })
          if (!ladder && warns.length === 0) return null
          return (
            <div style={{ marginTop: 6, display: 'flex', flexDirection: 'column', gap: 3 }}>
              {warns.map((w, i) => <div key={i} style={{ fontSize: 9, color: w.color, fontWeight: 700 }}>⚠ {w.text}</div>)}
              {ladder && (
                <div style={{ background: 'rgba(15,23,42,.45)', border: '1px solid var(--border)', borderRadius: 6, padding: '6px 8px' }}>
                  <div style={{ fontSize: 8, color: 'var(--text3)', fontWeight: 900, textTransform: 'uppercase' }}>Exit ladder (advisory) · R = ${ladder.R.toFixed(2)}/sh</div>
                  {ladder.steps.map((s, i) => (
                    <div key={i} style={{ fontSize: 9.5, marginTop: 2 }}>
                      <span style={{ color: '#22c55e', fontWeight: 800, ...mono }}>{s.label} {s.px.toFixed(2)}</span>
                      <span style={{ color: 'var(--text3)' }}> — {s.action}</span>
                    </div>
                  ))}
                  <div style={{ fontSize: 8.5, color: 'var(--text3)', marginTop: 4 }}>In-trade: {MONITOR_RULES}</div>
                </div>
              )}
            </div>
          )
        })()}
        <div style={{ marginTop: 4, fontSize: 9, color: 'var(--text3)', lineHeight: 1.5 }}>
          {p.entry_rationale && <div>Entry: {p.entry_rationale}</div>}
          {p.stop_rationale && <div>Stop: {p.stop_rationale}</div>}
          {p.target_rationale && <div>Target: {p.target_rationale}</div>}
        </div>
      </div>

      {/* TRADE METRICS */}
      <div style={{ padding: '6px 14px', borderBottom: '1px solid var(--border)', display: 'flex', gap: 16, fontSize: 10, ...mono, color: 'var(--text2)', flexWrap: 'wrap' }}>
        <span>R:R <strong style={{ color: computedRR >= 2 ? '#22C55E' : computedRR >= 1.5 ? '#F59E0B' : '#EF4444' }}>{computedRR.toFixed(1)}x</strong></span>
        <span>Risk <strong>${computedRisk.toFixed(0)}</strong></span>
        <span>Shares <strong>{shares.toLocaleString()}</strong></span>
        {rvol && <span>RVOL <strong style={{ color: rvolColor }}>{Number(rvol).toFixed(1)}x</strong></span>}
        {rsiVal && (
          p.rsi_flag === 'OVERBOUGHT' ? <span style={{ color: '#EF4444', fontWeight: 700 }}>{'⚠️'} RSI {Number(rsiVal).toFixed(0)} OVERBOUGHT</span>
          : p.rsi_flag === 'ELEVATED' ? <span>RSI <strong style={{ color: '#F97316' }}>{Number(rsiVal).toFixed(0)} {'↑'}</strong></span>
          : <span>RSI <strong style={{ color: rsiColor }}>{Number(rsiVal).toFixed(0)}</strong></span>
        )}
        {p.float_m && <span>Float <strong>{Number(p.float_m).toFixed(1)}M</strong></span>}
        {p.gap_pct && <span>Gap <strong>{Number(p.gap_pct) > 0 ? '+' : ''}{Number(p.gap_pct).toFixed(1)}%</strong></span>}
      </div>

      {/* E. EVIDENCE TILES */}
      <div style={{ padding: '6px 14px', borderBottom: '1px solid var(--border)', display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(70px, 1fr))', gap: 4 }}>
        {tiles.map(t => <MetricTile key={t.label} label={t.label} value={t.value} status={t.status} tileColor={t.tileColor} />)}
      </div>

      {/* F. MISSING DATA */}
      {((p.missing_data || []).length > 0 || (p.approval_blockers || []).length > 0) && (
        <div style={{ padding: '5px 14px', borderBottom: '1px solid var(--border)', display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
          {(p.missing_data || []).map((m: string, i: number) => <StatusBadge key={i} status="blocked" label={m} size="sm" />)}
          {(p.missing_data || []).length > 0 && <span style={{ fontSize: 8, color: '#EF4444', fontWeight: 600 }}>({(p.missing_data || []).length} gaps)</span>}
        </div>
      )}

      {/* VALIDATION TIMESTAMPS */}
      <div style={{ padding: '5px 14px', borderBottom: '1px solid var(--border)', display: 'flex', gap: 14, fontSize: 9, color: 'var(--text3)', flexWrap: 'wrap' }}>
        <span>Created: <strong style={{ color: p.age_color === 'green' ? '#22C55E' : p.age_color === 'red' ? '#EF4444' : '#F59E0B' }}>{p.age_display || '--'}</strong></span>
        <span>Price check: <strong style={{ color: lpt.color === 'green' ? '#22C55E' : lpt.color === 'red' ? '#EF4444' : '#F59E0B' }}>{lpt.text}</strong></span>
        <span>AI review: <strong style={{ color: ard.color === 'green' ? '#22C55E' : ard.color === 'red' ? '#EF4444' : '#F59E0B' }}>{ard.text}</strong></span>
        <span>Risk gate: <strong style={{ color: rgd.color === 'green' ? '#22C55E' : rgd.color === 'red' ? '#EF4444' : '#F59E0B' }}>{rgd.text}</strong></span>
        {p.staleness_policy && <span>Max age: <strong style={{ color: p.staleness_policy.is_stale ? '#EF4444' : '#22C55E' }}>{p.staleness_policy.max_age_hours}h ({p.staleness_policy.is_stale ? 'STALE' : 'OK'})</strong></span>}
        {p.trust_audit?.quote_trust && <span>Quote: <strong style={{ color: p.trust_audit.quote_trust.is_execution_eligible ? '#22C55E' : '#EF4444' }}>{p.trust_audit.quote_trust.quote_source} ({p.trust_audit.quote_trust.is_execution_eligible ? 'exec' : 'display'})</strong></span>}
        {p.trust_audit?.strategy_fit && <span>Strategy fit: <strong style={{ color: p.trust_audit.strategy_fit.fit_status === 'PASS' ? '#22C55E' : p.trust_audit.strategy_fit.fit_status === 'PARTIAL' ? '#F59E0B' : '#EF4444' }}>{p.trust_audit.strategy_fit.fit_status}</strong></span>}
      </div>

      {!isBrokerRouted(p) && bd && (
        <div style={{ padding: '6px 14px', borderBottom: '1px solid var(--border)' }}>
          <BrokerDiligenceStrip summary={bd} compact />
        </div>
      )}

      {/* G. ACTION WORKFLOW */}
      <div style={{ padding: '8px 14px', display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
        <ActionButton variant="secondary" size="sm" loading={runningAction === 'refreshPrice'} disabled={runningAction !== null} onClick={() => runAction('refreshPrice', `/api/v2/paper-proposals/refresh-data`, { proposal_id: p.id })} style={{ border: '1px solid rgba(59,130,246,0.3)', color: '#60A5FA' }}>
          {runningAction === 'refreshPrice' ? 'Refreshing...' : '1. Refresh Price'}
        </ActionButton>
        <ActionButton variant="secondary" size="sm" loading={runningAction === 'checkExec'} disabled={runningAction !== null} onClick={() => runAction('checkExec', `/api/v2/paper-proposals/check-execution-readiness`, { proposal_id: p.id })} style={{ border: '1px solid rgba(168,85,247,0.3)', color: '#A855F7' }}>
          {runningAction === 'checkExec' ? 'Checking...' : '2. Check Execution'}
        </ActionButton>
        <ActionButton variant="secondary" size="sm" loading={runningAction === 'aiReview'} disabled={runningAction !== null} onClick={() => runAction('aiReview', `/api/v2/paper-proposals/run-ai-review`, { proposal_id: p.id })} style={{ border: '1px solid rgba(168,85,247,0.3)', color: '#A855F7' }}>
          {runningAction === 'aiReview' ? 'Running...' : '3. AI Review'}
        </ActionButton>
        {!isBrokerRouted(p) && (
          <ActionButton variant="secondary" size="sm" loading={runningAction === 'brokerDiligence'} disabled={runningAction !== null}
            onClick={() => runAction('brokerDiligence', `/api/v2/paper-proposals/advance-broker-diligence`, { proposal_id: p.id })}
            style={{ border: '1px solid rgba(168,85,247,0.35)', color: '#C084FC', fontWeight: 700 }}
            title="Auto-queue enrichment, agent reviews, and LLM analysis">
            {runningAction === 'brokerDiligence' ? 'Running…' : '3b. Broker diligence'}
          </ActionButton>
        )}
        <ActionButton variant="secondary" size="sm" onClick={() => setShowBrokerPromote(true)}
          disabled={brokerDiligenceBlocked || isBrokerRouted(p)}
          style={{ border: '1px solid rgba(245,158,11,0.35)', color: brokerDiligenceBlocked || isBrokerRouted(p) ? '#64748B' : '#F59E0B', fontWeight: 800 }}
          title={isBrokerRouted(p) ? 'Already routed live — open Broker Proposals tab' : (bd?.next_action || 'Path B: Schwab 2FA auto or Fidelity FA manual')}>
          {isBrokerRouted(p) ? 'Path B · routed' : bd?.promote_ready ? '4a. Promote to Broker (live)' : '4a. Promote to Broker (locked)'}
        </ActionButton>
        <div style={{ flex: 1 }} />
        {isBrokerRouted(p) ? (
          <span style={{ fontSize: 10, fontWeight: 700, color: routingColor(p), padding: '6px 10px', borderRadius: 6, background: `${routingColor(p)}18`, border: `1px solid ${routingColor(p)}44` }}
            title="Path B — execute on Broker Proposals tab (Schwab auto/manual or Fidelity FA)">
            Path B only — use Broker Proposals
          </span>
        ) : (
          <ActionButton
            variant={p.operator_verdict === 'READY' ? 'primary' : 'disabled'}
            size="md"
            loading={acting[p.id] === 'approve'}
            disabled={p.is_blocked || (approveDisabled && !canApproveWithConfirm) || (p.approval_blockers || []).some((b: any) => b.gate === 'execution' || b.gate === 'rsi')}
            title={
              (p.approval_blockers || []).length > 0
                ? `Blocked: ${(p.approval_blockers || []).map((b: any) => b.reason).join('; ')}`
                : p.operator_verdict !== 'READY' ? (p.operator_verdict_reason || 'Not ready')
                : 'Path A: Alpaca paper auto — no real money'
            }
            onClick={handleApprove}
            style={p.operator_verdict === 'READY' ? { background: '#A855F7', color: '#fff' } : {}}
          >
            {acting[p.id] === 'approve' ? 'Approving...' : '4b. Approve (paper test)'}
          </ActionButton>
        )}
        <ActionButton variant="danger" size="md" loading={acting[p.id] === 'reject'} onClick={() => act(p.id, 'reject')}>
          {acting[p.id] === 'reject' ? 'Rejecting...' : '✗ Reject'}
        </ActionButton>
        <ActionButton variant="ghost" size="sm" onClick={() => setShowDetails(!showDetails)}>
          {showDetails ? '▲ Hide' : '▼ Details'}
        </ActionButton>
      </div>

      {/* I. DETAILS DRAWER */}
      {showDetails && (
        <div style={{ padding: '10px 14px', borderTop: '1px solid var(--border)', background: 'rgba(0,0,0,0.15)' }}>
          <PipelineChevron stages={p.pipeline_stages || []} />

          {p.strategy_entry_criteria && p.strategy_entry_criteria.length > 0 && (
            <div style={{ marginTop: 8 }}>
              <div style={secLbl}>Strategy Entry Criteria</div>
              {p.strategy_entry_criteria.map((c: any, i: number) => (
                <div key={i} style={{ fontSize: 9, color: 'var(--text2)', marginBottom: 1, paddingLeft: 8 }}>{'•'} {c.description || c.id}</div>
              ))}
            </div>
          )}

          {p.strategy_disqualifiers && p.strategy_disqualifiers.length > 0 && (
            <div style={{ marginTop: 6 }}>
              <div style={secLbl}>Auto-Disqualifiers</div>
              {p.strategy_disqualifiers.map((d: any, i: number) => (
                <div key={i} style={{ fontSize: 9, color: '#F59E0B', marginBottom: 1, paddingLeft: 8 }}>{'•'} {d.description || d.id}</div>
              ))}
            </div>
          )}

          {p.strategy_risk_rules && (
            <div style={{ marginTop: 6, display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 6 }}>
              {kv('Risk/Trade', p.strategy_risk_rules.risk_per_trade_pct != null ? `${(p.strategy_risk_rules.risk_per_trade_pct * 100).toFixed(2)}%` : '--')}
              {kv('Max Size', p.strategy_risk_rules.max_position_size != null ? `$${p.strategy_risk_rules.max_position_size.toLocaleString()}` : '--')}
              {kv('Stop Method', p.strategy_risk_rules.stop_method || '--')}
              {kv('Target Method', p.strategy_risk_rules.target_method || '--')}
            </div>
          )}

          {p.approve_case && (
            <div style={{ marginTop: 8 }}><div style={secLbl}>Support Case</div><div style={{ fontSize: 10, color: 'var(--text2)', padding: '6px 8px', background: 'var(--bg0)', borderRadius: 4, lineHeight: 1.5 }}>{p.approve_case}</div></div>
          )}
          {p.reject_case && (
            <div style={{ marginTop: 8 }}><div style={secLbl}>Reject Case</div><div style={{ fontSize: 10, color: 'var(--text2)', padding: '6px 8px', background: 'var(--bg0)', borderRadius: 4, lineHeight: 1.5 }}>{p.reject_case}</div></div>
          )}

          <div style={{ marginTop: 8, display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 6 }}>
            {[
              { l: 'RSI', v: rsiVal ? Number(rsiVal).toFixed(0) : '--' },
              { l: 'ATR', v: p.atr ? `$${Number(p.atr).toFixed(2)}` : '--' },
              { l: 'RVOL', v: rvol ? `${Number(rvol).toFixed(1)}x` : '--' },
              { l: 'Confluence', v: p.confluence_tier || p.confluence_score || '--' },
            ].map(m => kv(m.l, m.v))}
          </div>

          {(p.sector || p.vs_sector_pct != null) && (
            <div style={{ marginTop: 6, display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 6 }}>
              {kv('Sector', p.sector || 'Missing', p.sector ? undefined : '#EF4444')}
              {kv('Industry', p.industry || 'Missing', p.industry ? undefined : '#EF4444')}
              {kv('vs Sector', p.vs_sector_pct != null ? `${Number(p.vs_sector_pct) > 0 ? '+' : ''}${Number(p.vs_sector_pct).toFixed(1)}%` : '--', p.vs_sector_pct != null ? (Number(p.vs_sector_pct) > 0 ? '#22C55E' : '#EF4444') : undefined)}
              {kv('Sector ETF', p.sector_etf || '--')}
            </div>
          )}

          {p.agent_reviews?.length > 0 && (
            <div style={{ marginTop: 8 }}>
              <div style={secLbl}>Agent Reviews ({p.agent_reviews.length})</div>
              {p.agent_reviews.map((ar: any, i: number) => (
                <div key={i} style={{ fontSize: 9, color: 'var(--text2)', marginBottom: 2 }}>
                  <strong>{ar.agent_name || ar.agent}</strong>: {ar.verdict || ar.vote} ({ar.confidence}%) -- {(ar.summary || ar.reasoning || '').slice(0, 100)}
                </div>
              ))}
            </div>
          )}

          {p.news?.length > 0 && (
            <div style={{ marginTop: 8 }}>
              <div style={secLbl}>Recent News ({p.news.length})</div>
              {p.news.map((n: any, i: number) => (
                <div key={i} style={{ fontSize: 9, color: 'var(--text2)', marginBottom: 2 }}>
                  {n.sentiment === 'positive' ? '↑' : n.sentiment === 'negative' ? '↓' : '•'} {n.title} <span style={{ color: 'var(--text3)' }}>({n.source})</span>
                </div>
              ))}
            </div>
          )}

          {p.trust_audit && (() => {
            const ta = p.trust_audit
            const qt = ta.quote_trust || {}
            const sf2 = ta.strategy_fit || {}
            const tb = ta.technical_backtest || {}
            const qtColor = qt.quote_trust_status === 'EXECUTION_ELIGIBLE' ? '#22C55E' : qt.quote_trust_status === 'DISPLAY_ONLY' ? '#EF4444' : qt.quote_trust_status === 'STALE' ? '#F59E0B' : '#94A3B8'
            const sfColor = sf2.fit_status === 'PASS' ? '#22C55E' : sf2.fit_status === 'PARTIAL' ? '#F59E0B' : sf2.fit_status === 'FAIL' ? '#EF4444' : '#94A3B8'
            return (
              <div style={{ marginTop: 10, padding: '8px 10px', background: 'rgba(0,0,0,0.2)', borderRadius: 6, border: '1px solid rgba(255,255,255,0.05)' }}>
                <div style={{ ...secLbl, marginTop: 0 }}>Trust Audit</div>

                <div style={{ marginTop: 6 }}>
                  <div style={{ fontSize: 9, fontWeight: 700, color: qtColor, marginBottom: 3 }}>Quote Trust: {qt.quote_trust_status || 'NOT_CHECKED'}</div>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 4 }}>
                    {kv('Source', qt.quote_source || '?')}
                    {kv('Exec Eligible', qt.is_execution_eligible ? 'YES' : 'NO', qt.is_execution_eligible ? '#22C55E' : '#EF4444')}
                    {kv('Quote Age', qt.quote_age_seconds != null ? `${Math.round(Number(qt.quote_age_seconds))}s` : '--')}
                    {kv('Session', qt.market_session || '?')}
                  </div>
                  {qt.display_only_reason && <div style={{ fontSize: 8, color: '#EF4444', marginTop: 2 }}>{qt.display_only_reason}</div>}
                  {qt.next_action && <div style={{ fontSize: 8, color: '#60A5FA', marginTop: 1 }}>Next: {qt.next_action}</div>}
                </div>

                <div style={{ marginTop: 8 }}>
                  <div style={{ fontSize: 9, fontWeight: 700, color: sfColor, marginBottom: 3 }}>
                    Strategy Fit: {sf2.fit_status || 'MISSING'}
                    {sf2.selected_match_score != null && <span style={{ fontWeight: 400, color: 'var(--text3)' }}> (score {sf2.selected_match_score})</span>}
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 4 }}>
                    {kv('Strategies Evaluated', `${sf2.evaluated_count ?? 0}/${sf2.all_strategy_count ?? 0}`)}
                    {kv('Passed', String(sf2.passed_count ?? 0))}
                    {kv('Top Alternative', sf2.top_alternative || 'none')}
                    {kv('YAML/DB Sync', sf2.db_sync_status || '?')}
                  </div>
                  {sf2.mismatch_warning && <div style={{ fontSize: 8, color: '#EF4444', marginTop: 2 }}>WARNING: {sf2.mismatch_warning}</div>}
                  {sf2.missing_route_audit && <div style={{ fontSize: 8, color: '#F59E0B', marginTop: 2 }}>No route audit data -- strategy assignment unverified</div>}
                  {sf2.selected_criteria_met?.length > 0 && <div style={{ fontSize: 8, color: '#22C55E', marginTop: 2 }}>Met: {sf2.selected_criteria_met.join(', ')}</div>}
                  {sf2.selected_criteria_failed?.length > 0 && <div style={{ fontSize: 8, color: '#EF4444', marginTop: 1 }}>Failed: {sf2.selected_criteria_failed.join(', ')}</div>}
                  {sf2.strategy_evaluations?.length > 0 && (
                    <div style={{ marginTop: 4 }}>
                      <div style={{ fontSize: 8, color: 'var(--text3)', marginBottom: 2 }}>All evaluations:</div>
                      {sf2.strategy_evaluations.map((ev: any, i: number) => (
                        <div key={i} style={{ fontSize: 8, color: ev.strategy_id === sf2.assigned_strategy_id ? '#22C55E' : ev.match_status === 'NO_MATCH' ? 'var(--text3)' : '#F59E0B' }}>
                          {ev.is_primary ? '★ ' : '• '}{ev.strategy_id}: {ev.match_status} ({ev.match_score ?? '?'})
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                <div style={{ marginTop: 8 }}>
                  <div style={{ fontSize: 9, fontWeight: 700, color: 'var(--text2)', marginBottom: 3 }}>Technical / Backtest</div>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 4 }}>
                    {kv('Tech Grade', tb.technical_grade || (tb.technical_snapshot_exists ? 'OK' : 'MISSING'), tb.technical_snapshot_exists ? undefined : '#EF4444')}
                    {kv('Fib', tb.fib_status || '?', tb.fib_status === 'available' ? '#22C55E' : tb.fib_status === 'missing_required' ? '#EF4444' : undefined)}
                    {kv('ORB', tb.orb_status || '?', tb.orb_status === 'confirmed' ? '#22C55E' : tb.orb_status === 'missing_required' ? '#EF4444' : undefined)}
                    {kv('Backtest', `${tb.backtest_quality || '?'} n=${tb.backtest_sample_count ?? 0}`, tb.backtest_quality === 'SUFFICIENT' ? '#22C55E' : tb.backtest_quality === 'LIMITED' ? '#F59E0B' : tb.backtest_quality === 'MISSING' ? '#EF4444' : undefined)}
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 4, marginTop: 4 }}>
                    {kv('EMA', tb.ema_status || '?')}
                    {kv('VWAP', tb.vwap_status || '?')}
                    {kv('Missing Sections', String((tb.missing_required_sections || []).length), (tb.missing_required_sections || []).length > 0 ? '#EF4444' : '#22C55E')}
                    {kv('Tech Snapshot', tb.technical_snapshot_exists ? 'Yes' : 'No', tb.technical_snapshot_exists ? '#22C55E' : '#EF4444')}
                  </div>
                  {(tb.missing_required_sections || []).length > 0 && (
                    <div style={{ fontSize: 8, color: '#EF4444', marginTop: 2 }}>Missing required: {(tb.missing_required_sections || []).join(', ')}</div>
                  )}
                </div>
              </div>
            )
          })()}

          <div style={{ marginTop: 10, display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            <ActionButton variant="ghost" size="sm" loading={runningAction === 'enrich'} onClick={() => runAction('enrich', `/api/v2/paper-proposals/enrich-all`, { proposal_id: p.id })}>Enrich All</ActionButton>
            <ActionButton variant="ghost" size="sm" loading={runningAction === 'research'} onClick={() => runAction('research', `/api/v2/paper-proposals/run-research`, { proposal_id: p.id })}>Run Research</ActionButton>
            <ActionButton variant="ghost" size="sm" loading={runningAction === 'backtest'} onClick={() => runAction('backtest', `/api/v2/paper-proposals/run-backtest`, { proposal_id: p.id })}>Run Backtest</ActionButton>
            <ActionButton variant="ghost" size="sm" loading={runningAction === 'indicators'} onClick={() => runAction('indicators', `/api/v2/paper-proposals/run-indicators`, { proposal_id: p.id })}>Run Indicators</ActionButton>
            {p.tos_order_string && (
              <ActionButton variant="ghost" size="sm" onClick={() => { navigator.clipboard.writeText(p.tos_order_string); alert('TOS copied') }}>Copy TOS</ActionButton>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

// -- Main proposals surface --
export default function ProposalsRich() {
  const { data, refetch, loading, error, stale } = useApi<any>('/api/v2/paper-proposals', 30000)
  const { data: scards } = useApi<any>('/api/v2/symbol-cards', 300_000)
  const cardMap: Record<string, any> = (scards as any)?.cards ?? {}
  const [acting, setActing] = useState<Record<number, string>>({})
  const [showAll, setShowAll] = useState(true)
  const [strategyFilter, setStrategyFilter] = useState('ALL')
  const [stateFilter, setStateFilter] = useState('ALL')
  const [symbolSearch, setSymbolSearch] = useState('')
  const [runHealth, setRunHealth] = useState<any>(null)

  React.useEffect(() => {
    fetch('/api/v2/pipeline-run-health').then(r => r.json()).then(d => {
      const inner = d.data || d
      if (inner.ok) setRunHealth(inner)
    }).catch(() => {})
  }, [])

  const act = useCallback(async (id: number, action: string, overrides?: any) => {
    setActing(s => ({ ...s, [id]: action }))
    try {
      const body: any = { proposal_id: id }
      if (action === 'approve' && overrides) Object.assign(body, overrides)
      if (action === 'reject') body.reason = 'dashboard'
      const r = await fetch(`/api/v2/paper-proposals/${action}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
      const d = await r.json()
      if (!d.ok) {
        const mr = d.market_revalidation
        let msg = d.message || d.error || `${action} failed`
        if (mr && mr.live_price) msg += `\n\nLive: $${mr.live_price} | Drift: ${mr.price_drift_pct ?? '?'}% | R:R: ${mr.live_rr ?? '?'} | Spread: ${mr.live_spread_pct ?? '?'}%`
        alert(msg)
      } else if (action === 'approve' && d.message) {
        const mr = d.market_revalidation || d.data?.market_revalidation
        let msg = d.message
        if (mr && mr.live_price) msg += `\n\nLive: $${mr.live_price} | Drift: ${mr.price_drift_pct ?? '?'}% | R:R: ${mr.live_rr ?? '?'}`
        if (mr && mr.warnings?.length) msg += `\nWarnings: ${mr.warnings.join(', ')}`
        alert(msg)
      } else if (d.message) {
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
  const [showScreenerConfig, setShowScreenerConfig] = useState(false)
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
  const pending = allProposals.filter((p: any) => p.status === 'PENDING' || p.status === 'APPROVED_FOR_PAPER_TEST')
  const brokerRouted = pending.filter(isBrokerRouted)

  const strategies = Array.from(new Set(pending.map((p: any) => p.strategy_id).filter(Boolean))) as string[]

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

  const sorted = [...filtered].sort((a: any, b: any) => {
    const sa = a.sort_order ?? 2
    const sb = b.sort_order ?? 2
    if (sa !== sb) return sa - sb
    const wa = a.strategy_win_rate ?? 0
    const wb = b.strategy_win_rate ?? 0
    if (wa !== wb) return wb - wa
    return Number(b.signal_score || 0) - Number(a.signal_score || 0)
  })

  const displayed = showAll ? sorted : sorted.slice(0, 5)

  const stateCounts: Record<string, number> = {}
  for (const p of pending) {
    const s = normalizeProposal(p).actionState
    stateCounts[s] = (stateCounts[s] || 0) + 1
  }

  const btnStyle: React.CSSProperties = {
    fontSize: 10, padding: '4px 10px', borderRadius: 5, border: '1px solid var(--border)',
    background: 'var(--bg2)', color: 'var(--text1)', cursor: 'pointer', fontWeight: 600,
  }

  return (
    <div style={{ overflow: 'visible', paddingBottom: 24 }}>
      <ExecutionPathsStrip variant="full" />
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 10, flexWrap: 'wrap', gap: 8 }}>
        <div>
          <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text0)' }}>Automated Trade Proposals</div>
          <div style={{ fontSize: 10, color: 'var(--text3)' }}>
            {loading && !data ? 'Loading proposals…' : `${pending.length} pending`}
            {stale ? ' · showing cached data' : ''}
            {summary.expired_today ? ` · ${summary.expired_today} expired today` : ''}{summary.incubator_ready_count ? ` · ${summary.incubator_ready_count} incubator ready` : ''}
            {brokerRouted.length ? ` · ${brokerRouted.length} broker-routed` : ''}
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <ActionButton variant="secondary" size="sm" onClick={() => setShowAll(!showAll)}>
            {showAll ? `All (${filtered.length})` : 'Top 5'}
          </ActionButton>
          <ActionButton variant="secondary" size="sm" onClick={refetch}>Refresh</ActionButton>
          <ActionButton variant={enrichState === 'done' ? 'primary' : enrichState === 'error' ? 'danger' : 'secondary'} size="sm" loading={enrichState === 'running'} disabled={enrichState === 'running'} onClick={runEnrichAll} style={{ minWidth: 90 }}>
            {enrichState === 'running' ? `Running: ${enrichStep}` : enrichState === 'done' ? 'Done' : enrichState === 'error' ? 'Issues' : 'Enrich All'}
          </ActionButton>
          <ActionButton variant="secondary" size="sm" loading={promoteState === 'running'} disabled={promoteState === 'running'} onClick={runPromote} style={{ minWidth: 140, color: '#A855F7' }}>
            {promoteState === 'running' ? 'Promoting...' : promoteState === 'done' ? promoteResult : promoteState === 'error' ? promoteResult : 'Promote from Incubator'}
          </ActionButton>
          <ActionButton variant="secondary" size="sm" onClick={() => setShowScreenerConfig(true)} style={{ color: '#06B6D4', fontWeight: 700 }}>
            Screener Config
          </ActionButton>
        </div>
      </div>

      {/* Filter bar */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 10, alignItems: 'center', flexWrap: 'wrap' }}>
        <select value={strategyFilter} onChange={e => setStrategyFilter(e.target.value)}
          style={{ ...btnStyle, ...mono }}>
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
        <select value={stateFilter} onChange={e => setStateFilter(e.target.value)} style={{ ...btnStyle, ...mono }}>
          <option value="ALL">All States</option>
          {['PAPER_READY', 'CAUTION', 'NEEDS_REVIEW', 'BLOCKED', 'MISSING_DATA', 'LEARNING_MODE'].map(s => (
            <option key={s} value={s}>{s.replace(/_/g, ' ')} ({stateCounts[s] || 0})</option>
          ))}
        </select>
        <input
          type="text" placeholder="Search symbol..."
          value={symbolSearch} onChange={e => setSymbolSearch(e.target.value)}
          style={{ ...btnStyle, ...mono, width: 110 }}
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

      {/* Run health + incubator diagnostics */}
      {(runHealth?.latest_run || summary.incubator_diagnostics) && (
        <div style={{
          padding: '8px 14px', marginBottom: 10, borderRadius: 6, fontSize: 10,
          background: runHealth?.latest_run?.status === 'RUN_HEALTHY' ? 'rgba(34,197,94,0.06)' : 'rgba(245,158,11,0.06)',
          border: `1px solid ${runHealth?.latest_run?.status === 'RUN_HEALTHY' ? 'rgba(34,197,94,0.2)' : 'rgba(245,158,11,0.2)'}`,
        }}>
          {runHealth?.latest_run && (
            <div style={{ fontWeight: 600, color: runHealth.latest_run.status === 'RUN_HEALTHY' ? '#4ADE80' : '#FBBF24', marginBottom: 4 }}>
              Latest run: {runHealth.latest_run.run_label} &middot; {runHealth.latest_run.status?.replace(/_/g, ' ')}
            </div>
          )}
          <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', color: 'var(--text2)' }}>
            {runHealth?.latest_run && <>
              <span>Scanned: <strong>{runHealth.latest_run.symbols_scanned}</strong></span>
              <span>GO: <strong>{runHealth.latest_run.go_count}</strong></span>
              <span>Signals: <strong>{runHealth.strategy_signals?.today_count ?? 0}</strong></span>
              <span>Planned: <strong>{runHealth.trade_plans?.planned ?? 0}</strong></span>
            </>}
            {summary.incubator_diagnostics && <>
              <span>Incubator ready: <strong>{summary.incubator_diagnostics.ready_count}</strong></span>
              <span>Pending: <strong>{summary.incubator_diagnostics.pending_proposals}/{summary.incubator_diagnostics.pending_limit}</strong></span>
              <span>Headroom: <strong>{summary.incubator_diagnostics.headroom}</strong></span>
            </>}
          </div>
          {runHealth?.latest_run?.status !== 'RUN_HEALTHY' && runHealth?.latest_run && (
            <div style={{ marginTop: 4, fontSize: 9, color: '#F59E0B' }}>
              Why underfilled: Only {runHealth.latest_run.go_count} GO candidates from {runHealth.latest_run.symbols_scanned} scanned symbols
            </div>
          )}
          {summary.incubator_diagnostics?.promotion_blocked_reason && (
            <div style={{ marginTop: 3, fontSize: 9, color: '#F59E0B' }}>
              Incubator promotion: {summary.incubator_diagnostics.promotion_blocked_reason}
            </div>
          )}
          {runHealth?.paper_proposals?.blocked_reasons?.length > 0 && (
            <div style={{ marginTop: 3, fontSize: 9, color: '#F87171' }}>
              {runHealth.paper_proposals.blocked_reasons.join(' | ')}
            </div>
          )}
        </div>
      )}

      {/* Operator verdict summary bar */}
      {pending.length > 0 && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(90px, 1fr))', gap: 8, marginBottom: 10 }}>
          <StateCard title="Ready" value={summary.ready_count ?? 0} status="ready" compact />
          <StateCard title="Need Action" value={summary.needs_review_count ?? 0} status="warning" compact />
          <StateCard title="Stale Quote" value={summary.stale_count ?? 0} status="stale" compact />
          <StateCard title="Entry Missed" value={summary.entry_missed_count ?? 0} status="blocked" compact />
          {(summary.entry_missed_count ?? 0) > 0 && (
            <div style={{ display: 'flex', alignItems: 'center' }}>
              <ActionButton variant="danger" size="sm" onClick={async () => {
                const missed = pending.filter((p: any) => p.operator_verdict === 'ENTRY_MISSED')
                for (const p of missed) await act(p.id, 'reject')
              }}>
                Dismiss All Entry Missed
              </ActionButton>
            </div>
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

      {/* Multi-strategy warning */}
      {(summary.multi_strategy_symbols || []).length > 0 && (
        <div style={{ padding: '6px 14px', marginBottom: 10, borderRadius: 6, fontSize: 10,
          background: 'rgba(251,191,36,0.06)', border: '1px solid rgba(251,191,36,0.2)', color: '#F59E0B' }}>
          {(summary.multi_strategy_symbols || []).map((ms: any) => (
            <span key={ms.symbol} style={{ marginRight: 12 }}>{ms.symbol} has {ms.count} proposals ({ms.strategies.join(', ')}) -- approve at most 1</span>
          ))}
        </div>
      )}

      {/* Proposal list */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 14, overflow: 'visible' }}>
        {displayed.length === 0 ? (
          <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 8, padding: 24, textAlign: 'center', color: 'var(--text3)', fontSize: 12 }}>
            {loading && !data ? (
              <>Loading proposals from /api/v2/paper-proposals… (this can take 10–15s)</>
            ) : error && !data ? (
              <>Failed to load proposals: {error}. <ActionButton variant="secondary" size="sm" onClick={refetch}>Retry</ActionButton></>
            ) : pending.length === 0 ? (
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
          <ProposalCard key={p.id} p={p} act={act} acting={acting} symCard={cardMap[(p.symbol || '').toUpperCase()]} onRefetch={refetch} />
        ))}
      </div>

      <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 10 }}>
        Source: /api/v2/paper-proposals (enriched decision packet) + /api/v2/pipeline-run-health. Full operator workflow &mdash; refresh / check execution / AI review / approve / reject route through the same audited endpoints as the legacy v2 page.
      </div>

      {showScreenerConfig && (
        <Suspense fallback={null}>
          <ScreenerConfigModal onClose={() => setShowScreenerConfig(false)} />
        </Suspense>
      )}
    </div>
  )
}
