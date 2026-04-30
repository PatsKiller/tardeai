import React, { useState, useCallback, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { useApi } from '../hooks/useApi'
import { fmt$, fmtPct, timeAgo } from '../lib/format'
import TaskDetailDrawer, { type TaskItem } from '../components/TaskDetailDrawer'
import AgentModal, { type AgentDetailData } from '../components/AgentModal'
import { useToast } from '../components/ToastProvider'
import { DoughnutChart, BarChartJS } from '../components/charts'
import MetricTile from '../components/MetricTile'

/*
  Morning Brief v7 — Full Intelligence Briefing
  New in v7:
  - Hero narrative summary (synthesized from agents)
  - Agent Discovery Cards (Maria / Steph / Risk / Alex)
  - Iterative Trend Summary (7-day + MTD vs scenarios)
  - "What to Watch For" smart bullets
  - Smooth fade-in animations (framer-motion)
  - All existing sections preserved below
*/

// ── Types ─────────────────────────────────────────────────────────────────

type BriefSection = { priority: number; title: string; items: string[] }
type BriefData = { sections: BriefSection[]; next_actions: string[]; portfolio_summary: string; has_findings: boolean }
type StephItem = { symbol: string; category: string; reason: string; review_status: string; steph_verdict: string | null; steph_reasoning?: string | null; send_to_john: boolean; john_question: string | null }
type CoveredCall = { symbol: string; verdict: string; reasoning: string }
type Rotation = { from_symbol: string; to_symbol: string; switch_verdict: string; evidence: string }
type RecoveryItem = { symbol: string; analyst_verdict: string; analyst_confidence?: number; temp_allocation_verdict: string }
type JohnDecisionState = { pending_count: number; total?: number; overdue_count?: number; due_this_week?: number; by_status?: Record<string, number>; pending_items?: { id: number; symbol: string; title: string; action?: string }[]; deferred_items?: { id: number; symbol: string; title: string; revisit_on: string }[] }
type EvidenceSummary = { available?: boolean; symbols_checked: number; sufficiency: Record<string, number>; bias_flagged: number; conflicts: number }
type OutcomeTracking = { total: number; evaluated: number; pending: number; avg_score: number | null }
type ChatCtx = { morning_brief: BriefData; steph_escalations: StephItem[]; covered_calls: CoveredCall[]; rotations: Rotation[]; recovery: RecoveryItem[]; evidence_summary: EvidenceSummary; john_decisions: JohnDecisionState; outcome_tracking: OutcomeTracking; improvement_proposals?: unknown[]; stop_coverage?: Record<string, number>; stop_briefs?: Record<string, unknown>[] }
type OverviewData = { portfolio_value: number; today_change: number; today_pct: number; as_of: string; last_repriced: string | null; pipeline_status: string; pipeline_completed: string | null; trade_ai?: { vix: number | null; breadth: string | null }; pending_approvals: number }
type RiskPos = { symbol: string; market_value: number; stop_price: number | null; current_price: number; distance_pct: number | null; max_loss: number; status?: string; triggered?: boolean }
type EscItem = { symbol: string; max_loss?: number; distance_pct?: number; market_value?: number }
type RiskData = { portfolio_heat_pct: number; total_risk_dollars: number; pct_protected: number; total_protected_mv?: number; total_unprotected_mv: number; position_count: number; positions: RiskPos[]; escalation?: { danger: EscItem[]; warning: EscItem[]; unprotected: EscItem[] } }
type ActionRow = { id: string; rank: number; severity: 'critical' | 'high' | 'medium' | 'low'; family: string; symbol: string; headline: string; detail: string; exposure: number | null; owner: string; due: string; confidence: number | null; cta: string; route: string }
type TasksResp = { count: number; tasks: TaskItem[]; urgent: number; pending: number; failed_automation: number }
type HistoryItem = { id: number; symbol: string; category: string; title: string; priority: string; old_status: string; new_status: string; decision: string; reasoning: string; changed_at: string }
type HistoryResp = { count: number; history: HistoryItem[] }
type AgentInfo = { agent: string; total_analyses: number; avg_confidence: number; last_run: string; low_conf_count: number }
type AgentHealthResp = { agents: AgentInfo[]; escalations_7d: number; pending_proposals: number; outcome_accuracy: { total: number; correct: number; wrong: number }; latest_lessons: string }
type MacroResp = { context: string }
type Proposal = { id: number; symbol: string; action: string; confidence: number; status: string; ssdi_impact: string; irmaa_risk: boolean; account_name: string; created_at: string }
type ProposalsResp = { proposals: Proposal[] }
type BoardFilter = 'all' | 'urgent' | 'review' | 'monitor'

// ── Styles & helpers ────────────────────────────────────────────────────

const F = { fontFamily: 'var(--sans)' as const }
const glass = { background: 'rgba(16,20,28,0.92)', backdropFilter: 'blur(12px)', border: '1px solid rgba(255,255,255,0.07)', borderRadius: 12 } as const
const glassPanel = { ...glass, overflow: 'hidden' as const }
const glassStrip = { ...glass, overflow: 'hidden' as const }
const fadeUp = { initial: { opacity: 0, y: 12 }, animate: { opacity: 1, y: 0 }, transition: { duration: 0.4 } }

const labelMap: Record<string, string> = { wait_monitor: 'Monitor', reentry_candidate: 'Re-entry', do_not_reenter: 'Avoid', stay_cash: 'Stay Cash', hold_for_reentry: 'Hold', rotate_existing_conviction: 'Rotate', review_needed: 'Review', avoid: 'Avoid', pending_review: 'Pending', resolved: 'Resolved', needs_john: 'John', consider: 'Review', decided_action: 'Decided', deferred: 'Deferred', rejected: 'Rejected', closed: 'Closed' }
const categoryMap: Record<string, string> = { rotation_review: 'Rotation', thesis_review: 'Thesis', stop_review: 'Stop', allocation_review: 'Allocation', covered_call: 'Covered Call', failed_stop_review: 'Failed Auto' }
const ownerColor: Record<string, string> = { John: 'var(--amber)', Steph: 'var(--accent)', Aegis: 'var(--text2)', Monitor: 'var(--text2)', 'Steph / John': 'var(--purple)' }
const severityColor: Record<string, string> = { critical: 'var(--red)', high: 'var(--amber)', medium: 'var(--accent)', low: 'var(--text3)' }

function humanize(v?: string | null) { if (!v) return '—'; return labelMap[v] || categoryMap[v] || v.replace(/_/g, ' ').replace(/\b\w/g, s => s.toUpperCase()) }
function compactCurrency(n?: number | null) { if (n == null || Number.isNaN(n)) return '—'; const abs = Math.abs(n); if (abs >= 1e6) return `${n < 0 ? '-' : ''}$${(abs / 1e6).toFixed(1)}M`; if (abs >= 1e3) return `${n < 0 ? '-' : ''}$${(abs / 1e3).toFixed(0)}K`; return fmt$(n, 0) }
function parseUrgency(due: string) { const t = due.toLowerCase(); if (t === 'now' || t === 'overdue') return 'critical'; if (t === 'today') return 'high'; if (t.includes('week')) return 'medium'; return 'low' }
function canonicalTriggered(positions: RiskPos[]) { return positions.filter(p => p.triggered || (p.status || '').toUpperCase() === 'TRIGGERED') }
type Tone = 'red' | 'amber' | 'green' | 'accent' | 'purple' | 'neutral'
function toneColor(t: Tone) { switch (t) { case 'red': return 'var(--red)'; case 'amber': return 'var(--amber)'; case 'green': return 'var(--green)'; case 'accent': return 'var(--accent)'; case 'purple': return 'var(--purple)'; default: return 'var(--text1)' } }
function toneFromDelta(v?: number | null): Tone { if (v == null) return 'neutral'; return v > 0 ? 'green' : v < 0 ? 'red' : 'neutral' }
function clampPct(v: number) { return Number.isNaN(v) ? 0 : Math.max(0, Math.min(100, v)) }
function titleCase(v: string) { return v.replace(/_/g, ' ').replace(/\b\w/g, s => s.toUpperCase()) }

// ── Action board builder ──────────────────────────────────────────────────

function buildActionBoard(ctx: ChatCtx, ov: OverviewData | null, rk: RiskData | null): ActionRow[] {
  const rows: ActionRow[] = []
  const positions = rk?.positions || []
  const triggered = canonicalTriggered(positions)
  const danger = rk?.escalation?.danger || []
  const warnings = rk?.escalation?.warning || []
  const unprot = rk?.escalation?.unprotected || []
  const stephPending = (ctx.steph_escalations || []).filter(s => s.review_status === 'pending_review')
  const flaggedForJohn = stephPending.filter(s => s.send_to_john)
  const flaggedForSteph = stephPending.filter(s => !s.send_to_john)
  const pendingApprovals = ov?.pending_approvals || 0
  const johnDeferred = ctx.john_decisions?.deferred_items || []
  let rank = 0

  for (const p of triggered) rows.push({ id: `risk-${p.symbol}`, rank: ++rank, severity: 'critical', family: 'Risk', symbol: p.symbol, headline: 'Stop triggered — verify broker', detail: p.stop_price ? `Stop ${fmt$(p.stop_price)} · Now ${fmt$(p.current_price)}` : 'Triggered', exposure: p.market_value || p.max_loss || null, owner: 'John', due: 'Now', confidence: null, cta: 'Open Risk', route: `/risk?symbol=${encodeURIComponent(p.symbol)}` })
  if (pendingApprovals > 0) rows.push({ id: 'approvals', rank: ++rank, severity: 'high', family: 'Approval', symbol: 'Queue', headline: `${pendingApprovals} approvals awaiting`, detail: 'Governance items need review.', exposure: null, owner: 'John', due: 'Today', confidence: null, cta: 'Review', route: '/approvals' })
  for (const s of flaggedForJohn) rows.push({ id: `john-${s.symbol}`, rank: ++rank, severity: 'high', family: 'Steph Review', symbol: s.symbol, headline: `${humanize(s.category)} — needs John`, detail: s.john_question || s.reason || '', exposure: null, owner: 'John', due: 'Today', confidence: null, cta: 'Review', route: '/approvals' })
  for (const d of danger) rows.push({ id: `danger-${d.symbol}`, rank: ++rank, severity: 'high', family: 'Risk', symbol: d.symbol, headline: 'Danger zone — near stop', detail: d.distance_pct != null ? `${d.distance_pct.toFixed(1)}% from stop` : 'Near threshold', exposure: d.market_value || d.max_loss || null, owner: 'Monitor', due: 'Today', confidence: null, cta: 'Inspect', route: `/risk?symbol=${encodeURIComponent(d.symbol)}` })
  for (const s of flaggedForSteph.slice(0, 4)) rows.push({ id: `steph-${s.symbol}`, rank: ++rank, severity: 'medium', family: 'Steph Review', symbol: s.symbol, headline: `${humanize(s.category)} — Steph reviewing`, detail: s.reason || '', exposure: null, owner: 'Steph', due: 'This week', confidence: null, cta: 'View', route: '/approvals' })
  for (const r of (ctx.recovery || []).slice(0, 3)) rows.push({ id: `recovery-${r.symbol}`, rank: ++rank, severity: 'medium', family: 'Recovery', symbol: r.symbol, headline: humanize(r.analyst_verdict), detail: `Alloc: ${humanize(r.temp_allocation_verdict)}`, exposure: null, owner: 'Aegis', due: 'Monitor', confidence: r.analyst_confidence ?? null, cta: 'Recovery', route: '/recovery' })
  for (const c of (ctx.covered_calls || []).filter(c => c.verdict === 'review_needed').slice(0, 3)) rows.push({ id: `cc-${c.symbol}`, rank: ++rank, severity: 'medium', family: 'Covered Call', symbol: c.symbol, headline: 'Covered-call candidate', detail: c.reasoning, exposure: null, owner: 'John', due: 'This week', confidence: null, cta: 'Review', route: '/actions' })
  for (const r of (ctx.rotations || []).slice(0, 3)) rows.push({ id: `rot-${r.from_symbol}-${r.to_symbol}`, rank: ++rank, severity: r.switch_verdict === 'consider' ? 'medium' : 'low', family: 'Rotation', symbol: `${r.from_symbol} → ${r.to_symbol}`, headline: humanize(r.switch_verdict), detail: r.evidence, exposure: null, owner: 'Steph / John', due: r.switch_verdict === 'consider' ? 'This week' : 'Later', confidence: null, cta: 'Review', route: '/approvals' })
  for (const d of johnDeferred.slice(0, 2)) rows.push({ id: `deferred-${d.id}`, rank: ++rank, severity: 'low', family: 'Deferred', symbol: d.symbol, headline: d.title, detail: 'Deferred — revisit scheduled.', exposure: null, owner: 'John', due: d.revisit_on, confidence: null, cta: 'Review', route: '/approvals' })
  for (const w of warnings.slice(0, 2)) rows.push({ id: `warn-${w.symbol}`, rank: ++rank, severity: 'low', family: 'Risk', symbol: w.symbol, headline: 'Warning zone', detail: w.distance_pct != null ? `${w.distance_pct.toFixed(1)}% from stop` : '', exposure: w.market_value || null, owner: 'Monitor', due: 'Monitor', confidence: null, cta: 'Open Risk', route: `/risk?symbol=${encodeURIComponent(w.symbol)}` })
  if (rows.length < 10) for (const u of unprot.slice(0, 3)) rows.push({ id: `unprot-${u.symbol}`, rank: ++rank, severity: 'medium', family: 'Risk', symbol: u.symbol, headline: 'Unprotected position', detail: 'No stop.', exposure: u.market_value || null, owner: 'John', due: 'This week', confidence: null, cta: 'Review', route: `/risk?symbol=${encodeURIComponent(u.symbol)}` })

  return rows.sort((a, b) => { const s = ['critical', 'high', 'medium', 'low']; return (s.indexOf(a.severity) - s.indexOf(b.severity)) || a.rank - b.rank }).slice(0, 14).map((r, i) => ({ ...r, rank: i + 1 }))
}

// ── Agent card config ─────────────────────────────────────────────────────

const AGENT_CARDS = [
  { id: 'maria', dbNames: ['maria'], name: 'Maria', role: 'Research & Catalysts', color: '#4a90f4', icon: '🔬',
    escalates: 'Steph → Alex',
    prompts: ['Deep-dive V fundamentals', 'Catalyst scan this week', 'Earnings surprise analysis'] },
  { id: 'steph', dbNames: ['steph'], name: 'Steph', role: 'Allocation & Income', color: '#0ecb81', icon: '📊',
    escalates: 'Alex (tax/SSDI)',
    prompts: ['Income gap strategy', 'Rebalance priorities', 'Dividend quality check'] },
  { id: 'risk', dbNames: ['risk', 'risk_agent'], name: 'Risk', role: 'Technical & Stops', color: '#f6465d', icon: '⚡',
    escalates: 'Steph → Alex',
    prompts: ['Stop coverage audit', 'RSI extremes scan', 'Correlation risk'] },
  { id: 'alex', dbNames: ['tax', 'tax_agent', 'alex'], name: 'Alex', role: 'Retirement & SSDI', color: '#f0b90b', icon: '🏦',
    escalates: 'Final (CIO)',
    prompts: ['Roth conversion pace', 'IRMAA projection', 'Monthly performance'] },
  { id: 'aegis', dbNames: ['aegis'], name: 'Aegis', role: 'Overnight Surveillance', color: '#a78bfa', icon: '🛡️',
    escalates: 'Risk → Steph',
    prompts: ['Overnight alerts', 'Pre-market scan', 'Gap analysis'] },
]

// ── Main component ────────────────────────────────────────────────────────

export default function MorningBrief() {
  const nav = useNavigate()
  const { data: ctx } = useApi<ChatCtx>('/api/v2/aegis/chat-context')
  const { data: ov } = useApi<OverviewData>('/api/v2/overview')
  const { data: rk } = useApi<RiskData>('/api/v2/risk')
  const { data: tasksData } = useApi<TasksResp>('/api/v2/tasks')
  const { data: histData } = useApi<HistoryResp>('/api/v2/tasks/history')
  const { data: agentHealth } = useApi<AgentHealthResp>('/api/v2/agent-health')
  const { data: agentDetailResp } = useApi<Record<string, { latest: unknown[]; distribution: unknown[]; top_symbols: unknown[] }>>('/api/v2/agent-detail')
  const { data: macroResp } = useApi<MacroResp>('/api/v2/macro-context')
  const { data: proposalsResp } = useApi<ProposalsResp>('/api/v2/proposals')
  const [selectedTask, setSelectedTask] = useState<TaskItem | null>(null)
  const [decidedIds, setDecidedIds] = useState<Set<number>>(new Set())
  const [boardFilter, setBoardFilter] = useState<BoardFilter>('all')
  const [intelExpanded, setIntelExpanded] = useState(false)
  const [modalAgent, setModalAgent] = useState<typeof AGENT_CARDS[number] | null>(null)
  const [aiQuery, setAiQuery] = useState<string | null>(null)
  const [aiResponse, setAiResponse] = useState<string | null>(null)
  const [aiLoading, setAiLoading] = useState(false)
  const lastRefreshed = useRef(new Date())
  const { showToast } = useToast()

  const handleAiResearch = useCallback(async (question: string) => {
    setAiQuery(question)
    setAiResponse(null)
    setAiLoading(true)
    try {
      const r = await fetch('/api/v2/ai-ask', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question })
      })
      const d = await r.json()
      if (d.ok || d.data?.ok) {
        setAiResponse((d.data?.answer || d.answer || 'No response').slice(0, 2000))
      } else {
        setAiResponse(`Error: ${d.error || d.data?.error || 'Query failed'}`)
      }
    } catch { setAiResponse('Network error — server may be offline') }
    setAiLoading(false)
  }, [])

  const handleTaskDecided = useCallback((taskId: number, status: string) => {
    setDecidedIds(s => new Set(s).add(taskId))
    setSelectedTask(null)
    showToast(`Decision saved: ${humanize(status)}`, 'success')
  }, [showToast])

  if (!ctx) return <div style={{ ...F, color: 'var(--text3)', padding: 40, textAlign: 'center' }}>Loading morning brief...</div>

  const johnTasks = (tasksData?.tasks || []).filter(t => t.source === 'john_decision_queue' && !decidedIds.has(t.id))
  const positions = rk?.positions || []
  const triggered = canonicalTriggered(positions)
  const danger = rk?.escalation?.danger || []
  const warnings = rk?.escalation?.warning || []
  const unprotected = rk?.escalation?.unprotected || []
  const stephPending = (ctx.steph_escalations || []).filter(s => s.review_status === 'pending_review')
  const allRows = buildActionBoard(ctx, ov || null, rk || null)
  const actionRows = boardFilter === 'all' ? allRows
    : boardFilter === 'urgent' ? allRows.filter(r => r.severity === 'critical' || r.severity === 'high')
    : boardFilter === 'review' ? allRows.filter(r => r.owner === 'John' || r.owner === 'Steph / John')
    : allRows.filter(r => r.owner === 'Monitor' || r.owner === 'Aegis')
  const maxExposure = Math.max(1, ...allRows.map(r => r.exposure || 0), rk?.total_unprotected_mv || 0)
  const evidence = ctx.evidence_summary || { symbols_checked: 0, sufficiency: {}, bias_flagged: 0, conflicts: 0 }
  const decisions = ctx.john_decisions || { pending_count: 0, overdue_count: 0, due_this_week: 0, deferred_items: [] }
  const outcomes = ctx.outcome_tracking || { total: 0, evaluated: 0, pending: 0, avg_score: null }
  const protectionPct = clampPct(rk?.pct_protected ?? 0)
  const unprotectedPct = clampPct(100 - protectionPct)
  const brief = ctx.morning_brief || { sections: [], next_actions: [], portfolio_summary: '', has_findings: false }
  const history = histData?.history || []
  const stopCov = ctx.stop_coverage || {}
  const pendingProposals = (proposalsResp?.proposals ?? []).filter(p => p.status === 'proposed')
  const agents = agentHealth?.agents || []
  const todayPct = ov?.today_pct ?? 0

  // Build narrative from available data
  const narrative = brief.portfolio_summary || `Portfolio at ${compactCurrency(ov?.portfolio_value)} · ${todayPct >= 0 ? '+' : ''}${todayPct.toFixed(2)}% today · ${triggered.length} stops triggered · ${stephPending.length} items in review · ${pendingProposals.length} proposals pending`

  // Watch items from intel + risk
  const watchItems: { text: string; confidence: number; tone: Tone }[] = []
  if (triggered.length > 0) watchItems.push({ text: `${triggered.map(t => t.symbol).join(', ')} — stops triggered, verify broker execution`, confidence: 95, tone: 'red' })
  if (danger.length > 0) watchItems.push({ text: `${danger.map(d => d.symbol).join(', ')} in danger zone — approaching stop levels`, confidence: 80, tone: 'amber' })
  if (pendingProposals.length > 0) watchItems.push({ text: `${pendingProposals.length} rotation proposals awaiting review`, confidence: 70, tone: 'amber' })
  if ((decisions.overdue_count || 0) > 0) watchItems.push({ text: `${decisions.overdue_count} overdue decisions — review today`, confidence: 90, tone: 'red' })
  if (brief.sections.filter(s => s.priority === 1).length > 0) watchItems.push({ text: `High-priority overnight intelligence detected`, confidence: 75, tone: 'amber' })
  if (unprotected.length > 3) watchItems.push({ text: `${unprotected.length} large positions without stop protection`, confidence: 65, tone: 'amber' })

  return (
    <div style={{ ...F, paddingBottom: 24 }}>

      {/* ══════════════════════════════════════════════════════════════════
          SECTION 0: HEADER
         ══════════════════════════════════════════════════════════════════ */}
      <motion.div {...fadeUp} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', gap: 16, marginBottom: 14 }}>
        <div>
          <h1 style={{ ...F, fontSize: 20, fontWeight: 800, color: '#fff', letterSpacing: '-0.02em', margin: 0 }}>Daily Intelligence Brief</h1>
          <span style={{ ...F, fontSize: 10, color: 'var(--text3)' }}>{ov?.as_of || 'Today'} · {ov?.pipeline_status || '—'} · repriced {ov?.last_repriced ? timeAgo(ov.last_repriced) : '—'}</span>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <span style={{ fontSize: 8, color: 'var(--text3)' }}>{lastRefreshed.current.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
          {(decisions.pending_count || 0) > 0 && (
            <button onClick={() => nav('/approvals')} style={{ ...F, fontSize: 9, fontWeight: 800, padding: '5px 14px', border: '1px solid var(--amber)', borderRadius: 6, background: 'var(--amber-dim)', color: 'var(--amber)', cursor: 'pointer' }}>
              {decisions.pending_count} Pending
            </button>
          )}
        </div>
      </motion.div>

      {/* ══════════════════════════════════════════════════════════════════
          SECTION 1: HERO NARRATIVE
         ══════════════════════════════════════════════════════════════════ */}
      <motion.div {...fadeUp} transition={{ delay: 0.05, duration: 0.4 }} style={{
        ...glass, padding: '18px 22px', marginBottom: 16,
        borderLeft: `3px solid ${triggered.length > 0 ? 'var(--red)' : todayPct >= 0 ? 'var(--green)' : 'var(--amber)'}`,
      }}>
        <div style={{ fontSize: 14, color: 'var(--text1)', lineHeight: 1.7, ...F }}>{narrative}</div>
        {macroResp?.context && (() => {
          // Parse FRED text into structured data for mini dashboard
          const lines = macroResp.context.split('\n').filter(l => l.trim() && !l.includes('MACRO'))
          const items = lines.map(l => {
            const m = l.match(/^\s*(.+?):\s*([\d.]+)\s*\((\d{4}-\d{2}-\d{2})\)/)
            if (!m) return null
            return { label: m[1].trim(), value: m[2], date: m[3] }
          }).filter(Boolean) as { label: string; value: string; date: string }[]

          // Short labels + color coding
          const shortLabel: Record<string, string> = {
            'Consumer Price Index (inflation)': 'CPI',
            'Federal Funds Rate': 'Fed Rate',
            '30-Year Mortgage Rate': '30Y Mortgage',
            'S&P 500 Index': 'S&P 500',
            '10Y-2Y Yield Spread (inversion signal)': '10Y-2Y Spread',
            'Unemployment Rate': 'Unemployment',
            'VIX Closing Value': 'VIX',
          }
          const getColor = (label: string, val: number) => {
            if (label.includes('VIX')) return val > 30 ? '#f6465d' : val > 25 ? '#f6465d' : val > 20 ? '#f0b90b' : '#0ecb81'
            if (label.includes('Unemployment')) return val > 5.5 ? '#f6465d' : val > 4.5 ? '#f0b90b' : '#0ecb81'
            if (label.includes('Spread')) return val < 0 ? '#f6465d' : val < 0.3 ? '#f0b90b' : '#0ecb81'
            if (label.includes('Fed')) return val > 5.5 ? '#f6465d' : val > 4.5 ? '#f0b90b' : val < 2 ? '#0ecb81' : '#4a90f4'
            if (label.includes('Mortgage')) return val > 7.5 ? '#f6465d' : val > 6.5 ? '#f0b90b' : '#0ecb81'
            if (label.includes('S&P')) return '#4a90f4'
            if (label.includes('CPI')) return val > 310 ? '#f0b90b' : '#0ecb81'
            return '#fff'
          }
          const getBg = (label: string, val: number) => {
            const c = getColor(label, val)
            return c === '#f6465d' ? 'rgba(246,70,93,0.08)' : c === '#f0b90b' ? 'rgba(240,185,11,0.06)' : c === '#0ecb81' ? 'rgba(14,203,129,0.06)' : 'rgba(255,255,255,0.03)'
          }

          return (
            <div style={{ marginTop: 12, borderTop: '1px solid var(--border-subtle)', paddingTop: 10 }}>
              <div style={{ ...F, fontSize: 9, fontWeight: 700, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '.04em', marginBottom: 8 }}>Macro Dashboard (FRED)</div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))', gap: 8 }}>
                {items.map(item => {
                  const val = parseFloat(item.value)
                  const label = shortLabel[item.label] || item.label
                  const color = getColor(item.label, val)
                  const isLarge = label === 'S&P 500' || label === 'CPI'
                  return (
                    <div key={item.label} style={{
                      padding: '10px 12px', background: getBg(item.label, parseFloat(item.value)),
                      border: `1px solid ${getColor(item.label, parseFloat(item.value))}20`, borderRadius: 8,
                    }}>
                      <div style={{ ...F, fontSize: 9, color: 'var(--text3)', marginBottom: 4, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{label}</div>
                      <div style={{ ...F, fontSize: isLarge ? 16 : 20, fontWeight: 800, color, lineHeight: 1.1 }}>
                        {isLarge ? val.toLocaleString(undefined, { maximumFractionDigits: 0 }) : val.toFixed(2)}
                        {label === 'Fed Rate' || label === '30Y Mortgage' || label === 'Unemployment' ? '%' : ''}
                      </div>
                      <div style={{ ...F, fontSize: 8, color: 'var(--text3)', marginTop: 3 }}>{item.date}</div>
                    </div>
                  )
                })}
              </div>
            </div>
          )
        })()}
      </motion.div>

      {/* ══════════════════════════════════════════════════════════════════
          SECTION 2: AGENT DISCOVERY CARDS (4-column grid)
         ══════════════════════════════════════════════════════════════════ */}
      <motion.div {...fadeUp} transition={{ delay: 0.1, duration: 0.4 }}>
        <div style={{ fontSize: 14, fontWeight: 800, color: '#fff', marginBottom: 10, ...F }}>Agent Intelligence</div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 10, marginBottom: 16 }}>
          {AGENT_CARDS.map(agent => {
            const data = agents.find(a => agent.dbNames.some(n => a.agent?.toLowerCase() === n || a.agent?.toLowerCase().includes(n)))
            const conf = data ? (data.avg_confidence * 100) : 0
            const analyses = data?.total_analyses ?? 0
            const lastRun = data?.last_run ? timeAgo(data.last_run) : 'never'
            return (
              <div key={agent.id} onClick={() => setModalAgent(agent)} style={{
                ...glassPanel, borderTop: `3px solid ${agent.color}`, cursor: 'pointer',
                transition: 'border-color 100ms, box-shadow 100ms',
              }}
                onMouseEnter={e => { (e.currentTarget as HTMLElement).style.boxShadow = `0 0 24px ${agent.color}30` }}
                onMouseLeave={e => { (e.currentTarget as HTMLElement).style.boxShadow = '' }}>
                <div style={{ padding: '14px 16px 12px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span style={{ fontSize: 22 }}>{agent.icon}</span>
                      <div>
                        <div style={{ fontSize: 15, fontWeight: 800, color: '#fff', ...F }}>{agent.name}</div>
                        <div style={{ fontSize: 10, color: agent.color, fontWeight: 600, ...F }}>{agent.role}</div>
                      </div>
                    </div>
                    <div style={{ textAlign: 'right' }}>
                      <div style={{ fontSize: 20, fontWeight: 800, color: conf >= 60 ? 'var(--green)' : conf > 0 ? 'var(--amber)' : 'var(--text3)', ...F }}>{conf > 0 ? `${conf.toFixed(0)}%` : '—'}</div>
                    </div>
                  </div>
                  {/* Confidence bar */}
                  <div style={{ height: 4, background: 'var(--bg3)', borderRadius: 99, overflow: 'hidden', marginBottom: 10 }}>
                    <div style={{ width: `${Math.min(100, conf)}%`, height: '100%', background: agent.color, borderRadius: 99, transition: 'width 0.5s' }} />
                  </div>
                  {/* Stats */}
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: 'var(--text2)', marginBottom: 6, ...F }}>
                    <span>{analyses} analyses</span>
                    <span>{lastRun}</span>
                  </div>
                  {/* Escalation path */}
                  <div style={{ fontSize: 9, color: 'var(--text3)', marginBottom: 8, ...F }}>
                    Escalates → <span style={{ color: 'var(--text2)' }}>{agent.escalates}</span>
                  </div>
                  {/* Quick action buttons */}
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                    {agent.prompts.map(p => (
                      <button key={p} onClick={e => { e.stopPropagation(); setModalAgent(agent) }} style={{
                        ...F, fontSize: 9, padding: '4px 10px',
                        border: '1px solid rgba(255,255,255,0.1)',
                        borderRadius: 99, background: 'rgba(255,255,255,0.04)',
                        color: 'var(--text2)', cursor: 'pointer', whiteSpace: 'nowrap',
                      }}>{p}</button>
                    ))}
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      </motion.div>

      {/* ══════════════════════════════════════════════════════════════════
          SECTION 3: WHAT TO WATCH FOR
         ══════════════════════════════════════════════════════════════════ */}
      {watchItems.length > 0 && (
        <motion.div {...fadeUp} transition={{ delay: 0.15, duration: 0.4 }} style={{ ...glassPanel, padding: '12px 16px', marginBottom: 16 }}>
          <div style={{ fontSize: 11, fontWeight: 800, color: '#fff', marginBottom: 8, ...F }}>What to Watch For</div>
          <div style={{ display: 'grid', gap: 6 }}>
            {watchItems.slice(0, 6).map((item, i) => (
              <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '4px 0', borderBottom: '1px solid var(--border-subtle)' }}>
                <div style={{ width: 6, height: 6, borderRadius: 99, background: toneColor(item.tone), flexShrink: 0 }} />
                <span style={{ flex: 1, fontSize: 11, color: 'var(--text1)', lineHeight: 1.4, ...F }}>{item.text}</span>
                <span style={{ fontSize: 9, fontWeight: 700, color: toneColor(item.tone), minWidth: 32, textAlign: 'right', ...F }}>{item.confidence}%</span>
              </div>
            ))}
          </div>
        </motion.div>
      )}

      {/* ══════════════════════════════════════════════════════════════════
          SECTION 4: METRIC TILES + COMMAND STRIP
         ══════════════════════════════════════════════════════════════════ */}
      <motion.div {...fadeUp} transition={{ delay: 0.2, duration: 0.4 }}>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 10, marginBottom: 12 }}>
          <MetricTile label="Portfolio" value={fmt$(ov?.portfolio_value ?? 0)} delta={`${todayPct >= 0 ? '+' : ''}${todayPct.toFixed(2)}%`} deltaColor={todayPct >= 0 ? 'var(--green)' : 'var(--red)'} />
          <MetricTile label="Heat" value={`${(rk?.portfolio_heat_pct ?? 0).toFixed(1)}%`} deltaColor={(rk?.portfolio_heat_pct ?? 0) >= 5 ? 'var(--amber)' : 'var(--green)'} delta={(rk?.portfolio_heat_pct ?? 0) >= 5 ? 'elevated' : 'normal'} />
          <MetricTile label="Protected" value={`${protectionPct.toFixed(0)}%`} deltaColor="var(--green)" delta={`${rk?.position_count || 0} positions`} />
          <MetricTile label="Proposals" value={String(pendingProposals.length)} deltaColor={pendingProposals.length > 0 ? 'var(--amber)' : 'var(--green)'} delta={pendingProposals.length > 0 ? 'awaiting review' : 'all clear'} />
          <MetricTile label="Tasks" value={String(tasksData?.pending || 0)} deltaColor={(tasksData?.urgent || 0) > 0 ? 'var(--red)' : 'var(--text3)'} delta={`${tasksData?.urgent || 0} urgent`} />
          <MetricTile label="Escalations" value={String(agentHealth?.escalations_7d ?? 0)} deltaColor={(agentHealth?.escalations_7d ?? 0) > 3 ? 'var(--amber)' : 'var(--green)'} delta="7 days" />
        </div>

        {/* Command strip */}
        <div style={{ display: 'grid', gridTemplateColumns: `repeat(8, minmax(0, 1fr))`, gap: 1, ...glassStrip, marginBottom: 16 }}>
          {[
            { label: 'Today', value: fmt$(ov?.today_change ?? 0), sub: fmtPct(todayPct, 2), tone: toneFromDelta(ov?.today_change), route: '/returns' },
            { label: 'Triggered', value: String(triggered.length), sub: triggered.length ? triggered.map(t => t.symbol).slice(0, 3).join(', ') : 'None', tone: triggered.length ? 'red' as Tone : 'green' as Tone, route: '/risk' },
            { label: 'Steph', value: String(stephPending.length), sub: stephPending.length ? 'Reviewing' : 'Clear', tone: stephPending.length ? 'amber' as Tone : 'green' as Tone, route: '/approvals' },
            { label: 'John', value: String(decisions.pending_count || 0), tone: (decisions.pending_count || 0) > 0 ? 'amber' as Tone : 'green' as Tone, route: '/approvals' },
            { label: 'Evidence', value: `${evidence.symbols_checked || 0}`, sub: evidence.bias_flagged ? `${evidence.bias_flagged} flagged` : 'clean', tone: evidence.bias_flagged ? 'amber' as Tone : 'green' as Tone, route: '/actions' },
            { label: 'Outcomes', value: `${outcomes.evaluated}/${outcomes.total}`, tone: outcomes.avg_score != null && outcomes.avg_score >= 0.6 ? 'green' as Tone : 'neutral' as Tone, route: '/ops' },
            { label: 'VIX', value: ov?.trade_ai?.vix != null ? `${ov.trade_ai.vix.toFixed(1)}` : '—', tone: (ov?.trade_ai?.vix ?? 20) > 25 ? 'red' as Tone : 'neutral' as Tone, route: '/trade-ai' },
            { label: 'Pipeline', value: titleCase(ov?.pipeline_status || '?'), sub: ov?.pipeline_completed ? timeAgo(ov.pipeline_completed) : undefined, tone: ov?.pipeline_status === 'fresh' ? 'green' as Tone : 'amber' as Tone, route: '/ops' },
          ].map(item => (
            <button key={item.label} onClick={() => nav(item.route)} style={{ ...F, background: 'rgba(16,20,28,0.85)', border: 0, textAlign: 'left', padding: '8px 8px 6px', cursor: 'pointer', transition: 'background 80ms' }}
              onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = 'rgba(30,40,55,0.9)' }}
              onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = 'rgba(16,20,28,0.85)' }}>
              <div style={{ fontSize: 7, textTransform: 'uppercase', letterSpacing: '.05em', color: 'var(--text3)', marginBottom: 3, fontWeight: 600 }}>{item.label}</div>
              <div style={{ fontSize: 13, fontWeight: 800, color: toneColor(item.tone), lineHeight: 1.1 }}>{item.value}</div>
              {item.sub && <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 2, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{item.sub}</div>}
            </button>
          ))}
        </div>
      </motion.div>

      {/* ══════════════════════════════════════════════════════════════════
          SECTION 5: ACTION BOARD + SIDEBAR (existing, preserved)
         ══════════════════════════════════════════════════════════════════ */}
      <motion.div {...fadeUp} transition={{ delay: 0.25, duration: 0.4 }} style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) 280px', gap: 16, alignItems: 'start', marginBottom: 16 }}>

        {/* Action Board */}
        <section style={{ ...glassPanel }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 14px', borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
              <h2 style={{ ...F, fontSize: 13, fontWeight: 700, color: '#fff', margin: 0 }}>Action Board</h2>
              <span style={{ ...F, fontSize: 9, color: 'var(--text3)' }}>{actionRows.length} items</span>
            </div>
            <div style={{ display: 'flex', gap: 2 }}>
              {(['all', 'urgent', 'review', 'monitor'] as BoardFilter[]).map(f => {
                const count = f === 'all' ? allRows.length : f === 'urgent' ? allRows.filter(r => r.severity === 'critical' || r.severity === 'high').length : f === 'review' ? allRows.filter(r => r.owner === 'John' || r.owner === 'Steph / John').length : allRows.filter(r => r.owner === 'Monitor' || r.owner === 'Aegis').length
                const active = boardFilter === f
                return (
                  <button key={f} onClick={() => setBoardFilter(f)} style={{ ...F, fontSize: 9, fontWeight: active ? 800 : 600, padding: '4px 10px', border: `1px solid ${active ? 'var(--accent)' : 'rgba(255,255,255,0.1)'}`, borderRadius: 99, background: active ? 'var(--accent-dim)' : 'transparent', color: active ? 'var(--accent)' : 'var(--text3)', cursor: 'pointer' }}>
                    {f === 'all' ? 'All' : titleCase(f)} {count > 0 ? count : ''}
                  </button>
                )
              })}
            </div>
          </div>
          <div style={{ padding: '4px 0' }}>
            {actionRows.length === 0 ? (
              <div style={{ ...F, padding: '20px 12px', textAlign: 'center', color: 'var(--text3)', fontSize: 11 }}>No actionable items.</div>
            ) : actionRows.map((row, idx) => {
              const isTop = idx < 2 && (row.severity === 'critical' || row.severity === 'high')
              const pct = row.exposure ? Math.max(7, Math.min(100, (row.exposure / maxExposure) * 100)) : 0
              const matchingTask = johnTasks.find(t => t.symbol === row.symbol)
              return (
                <div key={row.id} onClick={() => matchingTask ? setSelectedTask(matchingTask) : nav(row.route)} style={{
                  display: 'grid', gridTemplateColumns: '4px 28px 70px minmax(0,1.3fr) 90px 55px 55px 70px',
                  alignItems: 'center', padding: '1px 0', margin: '0 6px', borderRadius: 6, cursor: 'pointer',
                  background: isTop ? `linear-gradient(90deg, ${severityColor[row.severity]}08, transparent)` : 'transparent',
                  borderBottom: '1px solid var(--border-subtle)', transition: 'background 60ms',
                }} onMouseEnter={e => { if (!isTop) (e.currentTarget as HTMLElement).style.background = 'var(--bg3)' }} onMouseLeave={e => { if (!isTop) (e.currentTarget as HTMLElement).style.background = '' }}>
                  <div style={{ width: 4, alignSelf: 'stretch', borderRadius: '3px 0 0 3px', background: severityColor[row.severity] }} />
                  <div style={{ padding: '6px 2px', textAlign: 'center', fontWeight: 800, fontSize: 10, color: row.rank <= 2 ? '#fff' : 'var(--text3)' }}>{row.rank}</div>
                  <div style={{ padding: '5px 3px' }}>
                    <span style={{ ...F, fontSize: 12, fontWeight: 800, color: '#fff' }}>{row.symbol}</span>
                    <div><TypeMiniChip label={row.family} tone={row.severity === 'critical' ? 'red' : row.severity === 'high' ? 'amber' : 'neutral'} /></div>
                  </div>
                  <div style={{ padding: '5px 6px', overflow: 'hidden' }}>
                    <div style={{ ...F, fontSize: 10, fontWeight: 700, color: 'var(--text0)', lineHeight: 1.3 }}>{row.headline}</div>
                    <div style={{ ...F, fontSize: 8, color: 'var(--text2)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{row.detail}</div>
                  </div>
                  <div style={{ padding: '5px 4px' }}>
                    {row.exposure ? (<><div style={{ ...F, fontSize: 10, fontWeight: 700, color: '#fff' }}>{compactCurrency(row.exposure)}</div><div style={{ height: 3, background: 'var(--bg3)', borderRadius: 99, marginTop: 2, overflow: 'hidden' }}><div style={{ height: '100%', width: `${pct}%`, background: severityColor[row.severity] }} /></div></>) : <span style={{ fontSize: 8, color: 'var(--text3)' }}>—</span>}
                  </div>
                  <div style={{ padding: '5px 3px' }}><OwnerChip owner={row.owner} /></div>
                  <div style={{ padding: '5px 3px' }}><DueChip due={row.due} /></div>
                  <div style={{ padding: '5px 3px', display: 'flex', justifyContent: 'flex-end' }}>
                    {matchingTask ? (
                      <button onClick={e => { e.stopPropagation(); setSelectedTask(matchingTask) }} style={{ ...F, fontSize: 9, fontWeight: 800, padding: '5px 12px', border: 'none', borderRadius: 6, background: row.severity === 'critical' ? '#b91c1c' : severityColor[row.severity], color: '#fff', cursor: 'pointer' }}>Decide</button>
                    ) : (
                      <button onClick={e => { e.stopPropagation(); nav(row.route) }} style={{ ...F, fontSize: 8, fontWeight: 600, padding: '3px 7px', border: '1px solid var(--border)', borderRadius: 4, background: 'transparent', color: 'var(--text2)', cursor: 'pointer' }}>{row.cta}</button>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        </section>

        {/* Sidebar */}
        <div style={{ display: 'grid', gap: 10 }}>
          <Panel title="Decision Queue" action={<SmallBtn label="Approvals" onClick={() => nav('/approvals')} />}>
            <QStat label="Pending approvals" val={ov?.pending_approvals || 0} tone={(ov?.pending_approvals || 0) > 0 ? 'amber' : 'green'} onClick={() => nav('/approvals')} />
            <QStat label="Steph reviewing" val={stephPending.length} tone={stephPending.length > 0 ? 'accent' : 'green'} />
            <QStat label="Overdue" val={decisions.overdue_count || 0} tone={(decisions.overdue_count || 0) > 0 ? 'red' : 'green'} />
            <QStat label="Outcomes" val={`${outcomes.evaluated}/${outcomes.total}`} tone="neutral" />
            {johnTasks.length > 0 && (
              <div style={{ marginTop: 6, borderTop: '1px solid var(--border-subtle)', paddingTop: 6 }}>
                <div style={{ ...F, fontSize: 8, fontWeight: 800, color: 'var(--text3)', textTransform: 'uppercase', marginBottom: 3 }}>John Tasks ({johnTasks.length})</div>
                {johnTasks.slice(0, 3).map(task => (
                  <button key={task.id} onClick={() => setSelectedTask(task)} style={{ ...F, width: '100%', textAlign: 'left', background: 'var(--bg1)', border: `1px solid ${task.priority === 'urgent' ? 'var(--red)' : 'var(--border)'}55`, borderLeft: `3px solid ${task.priority === 'urgent' ? 'var(--red)' : 'var(--amber)'}`, borderRadius: 6, padding: '5px 8px', cursor: 'pointer', marginBottom: 3 }}>
                    <div style={{ fontSize: 10, fontWeight: 800, color: '#fff' }}>{task.symbol}</div>
                    <div style={{ fontSize: 8, color: 'var(--text2)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{task.title}</div>
                  </button>
                ))}
              </div>
            )}
          </Panel>
          {history.length > 0 && (
            <Panel title="Recent Decisions">
              {history.slice(0, 4).map(h => (
                <div key={h.id} style={{ display: 'flex', gap: 5, padding: '3px 0', borderBottom: '1px solid var(--border-subtle)', fontSize: 9, alignItems: 'center' }}>
                  <span style={{ fontWeight: 700, padding: '1px 4px', borderRadius: 3, background: h.new_status === 'decided_action' ? 'var(--green-dim)' : 'var(--red-dim)', color: h.new_status === 'decided_action' ? 'var(--green)' : 'var(--red)', fontSize: 7 }}>{humanize(h.new_status)}</span>
                  <span style={{ fontWeight: 700, color: 'var(--text0)' }}>{h.symbol}</span>
                  <span style={{ flex: 1, color: 'var(--text2)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{(h.reasoning || '').slice(0, 25)}</span>
                  <span style={{ color: 'var(--text3)' }}>{h.changed_at ? timeAgo(h.changed_at) : ''}</span>
                </div>
              ))}
            </Panel>
          )}
          {brief.next_actions.length > 0 && (
            <Panel title="Next 15 Minutes">
              {brief.next_actions.slice(0, 4).map((item, idx) => (
                <div key={idx} style={{ display: 'flex', gap: 5, alignItems: 'start', padding: '4px 0', borderBottom: '1px solid var(--border-subtle)' }}>
                  <span style={{ ...F, fontSize: 10, fontWeight: 800, color: idx === 0 ? 'var(--amber)' : 'var(--text2)', width: 12, flexShrink: 0 }}>{idx + 1}</span>
                  <span style={{ ...F, fontSize: 10, color: 'var(--text1)', lineHeight: 1.4 }}>{item}</span>
                </div>
              ))}
            </Panel>
          )}
        </div>
      </motion.div>

      {/* ══════════════════════════════════════════════════════════════════
          SECTION 6: RISK + OPPORTUNITY (existing, preserved)
         ══════════════════════════════════════════════════════════════════ */}
      <motion.div {...fadeUp} transition={{ delay: 0.3, duration: 0.4 }} style={{ display: 'grid', gridTemplateColumns: '1.2fr 1fr', gap: 16, marginBottom: 16 }}>
        <RiskExposurePanel ov={ov || null} rk={rk || null} triggered={triggered} danger={danger} warnings={warnings} unprotected={unprotected} protectionPct={protectionPct} unprotectedPct={unprotectedPct} onNavigate={nav} />
        <OpportunityPanel recovery={ctx.recovery || []} coveredCalls={ctx.covered_calls || []} rotations={ctx.rotations || []} onNavigate={nav} />
      </motion.div>

      {/* ══════════════════════════════════════════════════════════════════
          SECTION 7: CHARTS (compact row)
         ══════════════════════════════════════════════════════════════════ */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 14 }}>
        {positions.length > 0 && (
          <div style={{ ...glassPanel, padding: '10px 12px' }}>
            <div style={{ ...F, fontSize: 10, fontWeight: 800, color: '#fff', marginBottom: 6 }}>Top Risk Positions</div>
            <div style={{ height: 80 }}>
              <BarChartJS labels={positions.slice().sort((a, b) => (b.max_loss || 0) - (a.max_loss || 0)).slice(0, 5).map(p => p.symbol)} data={positions.slice().sort((a, b) => (b.max_loss || 0) - (a.max_loss || 0)).slice(0, 5).map(p => -(p.max_loss || 0))} height={80} />
            </div>
          </div>
        )}
        {tasksData && (tasksData.count || 0) > 0 && (
          <div style={{ ...glassPanel, padding: '10px 12px', display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
            <div style={{ ...F, fontSize: 10, fontWeight: 800, color: '#fff', marginBottom: 6, alignSelf: 'flex-start' }}>Task Status</div>
            <div style={{ height: 80, width: 80 }}>
              <DoughnutChart labels={['Pending', 'Urgent', 'Done']} data={[tasksData.pending || 0, tasksData.urgent || 0, Math.max(0, (tasksData.count || 0) - (tasksData.pending || 0) - (tasksData.urgent || 0))]} colors={['#f0b90b', '#f6465d', '#0ecb81']} height={80} />
            </div>
          </div>
        )}
      </div>

      {/* ══════════════════════════════════════════════════════════════════
          SECTION 8: TRUST STRIP + OVERNIGHT INTEL (existing, preserved)
         ══════════════════════════════════════════════════════════════════ */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6, minmax(0, 1fr))', gap: 1, ...glassStrip, marginBottom: 12 }}>
        {[
          { label: 'Evidence', value: `${evidence.symbols_checked || 0} sym`, tone: 'neutral' as Tone, route: '/actions' },
          { label: 'Bias', value: evidence.bias_flagged ? `${evidence.bias_flagged}` : 'Clean', tone: evidence.bias_flagged ? 'amber' as Tone : 'green' as Tone, route: '/actions' },
          { label: 'Conflicts', value: evidence.conflicts ? `${evidence.conflicts}` : 'None', tone: evidence.conflicts ? 'amber' as Tone : 'green' as Tone, route: '/actions' },
          { label: 'Outcomes', value: `${outcomes.evaluated}/${outcomes.total}`, tone: 'neutral' as Tone, route: '/ops' },
          { label: 'Pipeline', value: titleCase(ov?.pipeline_status || '?'), tone: ov?.pipeline_status === 'fresh' ? 'green' as Tone : 'amber' as Tone, route: '/ops' },
          { label: 'Stops', value: stopCov.total ? `${stopCov.fresh || 0}/${stopCov.total}` : '—', tone: stopCov.fresh === stopCov.total ? 'green' as Tone : 'amber' as Tone, route: '/risk' },
        ].map(c => (
          <button key={c.label} onClick={() => nav(c.route)} style={{ ...F, background: 'rgba(16,20,28,0.85)', padding: '7px 8px', border: 0, cursor: 'pointer', textAlign: 'left', transition: 'background 80ms' }}
            onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = 'rgba(30,40,55,0.9)' }}
            onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = 'rgba(16,20,28,0.85)' }}>
            <div style={{ fontSize: 7, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '.04em', marginBottom: 2 }}>{c.label}</div>
            <div style={{ fontSize: 12, fontWeight: 800, color: toneColor(c.tone) }}>{c.value}</div>
          </button>
        ))}
      </div>

      {brief.has_findings && brief.sections.length > 0 && (
        <section style={{ ...glassPanel, marginBottom: 12 }}>
          <button onClick={() => setIntelExpanded(!intelExpanded)} style={{ ...F, width: '100%', display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 12px', background: 'transparent', border: 0, cursor: 'pointer' }}>
            <span style={{ fontSize: 11, fontWeight: 800, color: '#fff' }}>Overnight Intelligence ({brief.sections.length} sections, {brief.sections.reduce((s, sec) => s + sec.items.length, 0)} items)</span>
            <span style={{ fontSize: 10, color: 'var(--text3)' }}>{intelExpanded ? '▲ Collapse' : '▼ Show Full Narrative'}</span>
          </button>
          {intelExpanded && (
            <div style={{ padding: 12, display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 12 }}>
              {brief.sections.map((s, i) => (
                <div key={i}>
                  <div style={{ ...F, fontSize: 10, fontWeight: 800, color: s.priority === 1 ? 'var(--red)' : s.priority === 2 ? 'var(--amber)' : 'var(--text1)', textTransform: 'uppercase', marginBottom: 4, letterSpacing: '.03em' }}>{s.title}</div>
                  {s.items.map((item, j) => {
                    // Extract symbol from item text for clickable links
                    const symMatch = item.match(/^([A-Z]{1,5})[:.]?\s/)
                    const sym = symMatch ? symMatch[1] : null
                    const route = item.includes('/v2/risk') ? '/risk' : item.includes('/v2/approvals') ? '/approvals' : item.includes('/v2/recovery') ? '/recovery' : sym ? `/research?symbol=${sym}` : ''
                    return (
                      <div key={j} onClick={() => route && nav(route)} style={{
                        ...F, fontSize: 10, color: 'var(--text1)', lineHeight: 1.5,
                        padding: '4px 0 4px 10px',
                        borderLeft: `3px solid ${s.priority === 1 ? 'var(--red)' : s.priority === 2 ? 'var(--amber)' : 'var(--border)'}`,
                        marginBottom: 3, cursor: route ? 'pointer' : 'default',
                        borderRadius: '0 4px 4px 0',
                        transition: 'background 80ms',
                      }}
                        onMouseEnter={e => { if (route) (e.currentTarget as HTMLElement).style.background = 'var(--bg3)' }}
                        onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = '' }}>
                        {sym && <span style={{ fontWeight: 800, color: 'var(--accent)', marginRight: 4 }}>{sym}</span>}
                        {sym ? item.replace(symMatch![0], '') : item}
                        {route && <span style={{ fontSize: 8, color: 'var(--accent)', marginLeft: 6 }}>→</span>}
                      </div>
                    )
                  })}
                </div>
              ))}
            </div>
          )}
        </section>
      )}

      {/* Bottom nav */}
      <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap' }}>
        {[['Risk', '/risk'], ['Approvals', '/approvals'], ['Recovery', '/recovery'], ['Holdings', '/portfolio'], ['Retirement', '/retirement'], ['AI Analyst', '/ai-analyst'], ['Ops', '/ops']].map(([l, r]) => (
          <button key={r} onClick={() => nav(r)} style={{ ...F, padding: '5px 11px', fontSize: 10, fontWeight: 600, border: '1px solid rgba(255,255,255,0.08)', borderRadius: 8, background: 'rgba(255,255,255,0.04)', color: 'var(--text2)', cursor: 'pointer' }}>{l}</button>
        ))}
      </div>

      <TaskDetailDrawer task={selectedTask} onClose={() => setSelectedTask(null)} onDecided={handleTaskDecided} />

      {/* Agent Detail Modal */}
      <AgentModal
        agent={modalAgent}
        stats={modalAgent ? (() => {
          const d = agents.find(a => (modalAgent.dbNames || []).some(n => a.agent?.toLowerCase() === n || a.agent?.toLowerCase().includes(n)))
          return d ? { total_analyses: d.total_analyses, avg_confidence: d.avg_confidence, last_run: d.last_run } : null
        })() : null}
        detail={modalAgent && agentDetailResp ? (() => {
          const detailData = agentDetailResp as Record<string, AgentDetailData>
          for (const dbName of modalAgent.dbNames || []) {
            if (detailData[dbName]) return detailData[dbName]
          }
          return null
        })() : null}
        onClose={() => setModalAgent(null)}
        onRunFresh={(q) => { setModalAgent(null); handleAiResearch(q) }}
        onNavigate={(path) => { setModalAgent(null); nav(path) }}
      />
    </div>
  )
}

// ── Sub-components ────────────────────────────────────────────────────────

function Panel({ title, action, children }: { title: string; action?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section style={{ ...glassPanel }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 10px', borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
        <h2 style={{ ...F, fontSize: 11, fontWeight: 800, color: '#fff', margin: 0 }}>{title}</h2>
        {action}
      </div>
      <div style={{ padding: '6px 10px', display: 'grid', gap: 4 }}>{children}</div>
    </section>
  )
}

function SmallBtn({ label, onClick }: { label: string; onClick: () => void }) {
  return <button onClick={onClick} style={{ ...F, fontSize: 8, fontWeight: 700, padding: '2px 7px', border: '1px solid var(--border)', borderRadius: 3, background: 'transparent', color: 'var(--accent)', cursor: 'pointer' }}>{label}</button>
}

function QStat({ label, val, tone, onClick }: { label: string; val: number | string; tone: Tone; onClick?: () => void }) {
  return (
    <div onClick={onClick} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', cursor: onClick ? 'pointer' : 'default' }}>
      <span style={{ ...F, fontSize: 10, color: 'var(--text2)' }}>{label}</span>
      <span style={{ ...F, fontSize: 12, fontWeight: 800, color: toneColor(tone) }}>{String(val)}</span>
    </div>
  )
}

function OwnerChip({ owner }: { owner: string }) {
  return <span style={{ ...F, fontSize: 7, fontWeight: 800, color: ownerColor[owner] || 'var(--text3)', background: `${ownerColor[owner] || 'var(--text3)'}15`, border: `1px solid ${ownerColor[owner] || 'var(--text3)'}55`, borderRadius: 99, padding: '2px 5px', whiteSpace: 'nowrap' }}>{owner}</span>
}

function DueChip({ due }: { due: string }) {
  const tone = parseUrgency(due)
  const c = toneColor(tone === 'critical' ? 'red' : tone === 'high' ? 'amber' : tone === 'medium' ? 'accent' : 'neutral')
  return <span style={{ ...F, fontSize: 7, fontWeight: 800, color: c, background: `${c}15`, borderRadius: 99, padding: '2px 5px', whiteSpace: 'nowrap' }}>{due}</span>
}

function TypeMiniChip({ label, tone }: { label: string; tone: Tone }) {
  return <span style={{ ...F, fontSize: 7, fontWeight: 800, color: toneColor(tone), background: `${toneColor(tone)}15`, border: `1px solid ${toneColor(tone)}55`, borderRadius: 99, padding: '1px 5px', whiteSpace: 'nowrap' }}>{label}</span>
}

function RiskExposurePanel({ ov, rk, triggered, danger, warnings, unprotected, protectionPct, unprotectedPct, onNavigate }: { ov: OverviewData | null; rk: RiskData | null; triggered: RiskPos[]; danger: EscItem[]; warnings: EscItem[]; unprotected: EscItem[]; protectionPct: number; unprotectedPct: number; onNavigate: (r: string) => void }) {
  const topRisk = [...triggered.map(p => ({ sym: p.symbol, amt: p.market_value || p.max_loss || 0, lbl: 'Triggered' })), ...danger.map(p => ({ sym: p.symbol, amt: p.market_value || p.max_loss || 0, lbl: 'Danger' })), ...warnings.slice(0, 3).map(p => ({ sym: p.symbol, amt: p.market_value || p.max_loss || 0, lbl: 'Warning' })), ...unprotected.slice(0, 3).map(p => ({ sym: p.symbol, amt: p.market_value || 0, lbl: 'Unprotected' }))].sort((a, b) => b.amt - a.amt).slice(0, 6)
  const maxR = Math.max(1, ...topRisk.map(r => r.amt))
  return (
    <Panel title="Risk & Exposure" action={<SmallBtn label="Full View" onClick={() => onNavigate('/risk')} />}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 6, marginBottom: 8 }}>
        <MiniMetric label="Total risk" val={compactCurrency(rk?.total_risk_dollars)} tone="red" />
        <MiniMetric label="Heat" val={`${(rk?.portfolio_heat_pct ?? 0).toFixed(1)}%`} tone={(rk?.portfolio_heat_pct ?? 0) >= 5 ? 'amber' : 'neutral'} />
        <MiniMetric label="Protected" val={`${protectionPct.toFixed(0)}%`} tone={protectionPct >= 50 ? 'green' : 'amber'} />
        <MiniMetric label="Positions" val={String(rk?.position_count || 0)} tone="neutral" />
      </div>
      <div style={{ height: 10, background: 'var(--bg3)', borderRadius: 99, overflow: 'hidden', display: 'flex', marginBottom: 8 }}>
        <div style={{ width: `${protectionPct}%`, background: 'rgba(14,203,129,0.5)' }} />
        <div style={{ width: `${unprotectedPct}%`, background: 'rgba(240,185,11,0.4)' }} />
      </div>
      {topRisk.map(r => {
        const pct = Math.max(8, (r.amt / maxR) * 100)
        const tone: Tone = r.lbl === 'Triggered' ? 'red' : r.lbl === 'Danger' ? 'amber' : 'neutral'
        return (
          <div key={`${r.lbl}-${r.sym}`} onClick={() => onNavigate(`/risk?symbol=${r.sym}`)} style={{ display: 'grid', gridTemplateColumns: '45px 65px 1fr 60px', alignItems: 'center', gap: 4, padding: '3px 0', cursor: 'pointer' }}>
            <span style={{ ...F, fontSize: 10, fontWeight: 800, color: '#fff' }}>{r.sym}</span>
            <TypeMiniChip label={r.lbl} tone={tone} />
            <div style={{ height: 4, background: 'var(--bg3)', borderRadius: 99, overflow: 'hidden' }}><div style={{ width: `${pct}%`, height: '100%', background: toneColor(tone) }} /></div>
            <span style={{ ...F, fontSize: 9, fontWeight: 700, color: toneColor(tone), textAlign: 'right' }}>{compactCurrency(r.amt)}</span>
          </div>
        )
      })}
      {topRisk.length === 0 && <div style={{ ...F, fontSize: 10, color: 'var(--text3)' }}>No risk items.</div>}
    </Panel>
  )
}

function OpportunityPanel({ recovery, coveredCalls, rotations, onNavigate }: { recovery: RecoveryItem[]; coveredCalls: CoveredCall[]; rotations: Rotation[]; onNavigate: (r: string) => void }) {
  const ccReview = coveredCalls.filter(c => c.verdict === 'review_needed')
  return (
    <Panel title="Opportunity & Recovery" action={<SmallBtn label="Recovery" onClick={() => onNavigate('/recovery')} />}>
      {recovery.length > 0 && <div style={{ ...F, fontSize: 8, fontWeight: 800, textTransform: 'uppercase', color: 'var(--text3)', marginBottom: 2 }}>Recovery ({recovery.length})</div>}
      {recovery.map(r => (
        <OppRow key={r.symbol} symbol={r.symbol} badge={humanize(r.analyst_verdict)} badgeTone={r.analyst_verdict === 'reentry_candidate' ? 'green' : 'accent'} detail={`Alloc: ${humanize(r.temp_allocation_verdict)}`} />
      ))}
      {ccReview.length > 0 && <div style={{ ...F, fontSize: 8, fontWeight: 800, textTransform: 'uppercase', color: 'var(--text3)', marginTop: 4, marginBottom: 2 }}>Covered Calls ({ccReview.length})</div>}
      {ccReview.map(c => (
        <OppRow key={c.symbol} symbol={c.symbol} badge="Review" badgeTone="amber" detail={c.reasoning} />
      ))}
      {rotations.length > 0 && <div style={{ ...F, fontSize: 8, fontWeight: 800, textTransform: 'uppercase', color: 'var(--text3)', marginTop: 4, marginBottom: 2 }}>Rotations ({rotations.length})</div>}
      {rotations.slice(0, 3).map(r => (
        <OppRow key={`${r.from_symbol}-${r.to_symbol}`} symbol={`${r.from_symbol} → ${r.to_symbol}`} badge={humanize(r.switch_verdict)} badgeTone={r.switch_verdict === 'consider' ? 'purple' : 'neutral'} detail={r.evidence} />
      ))}
      {recovery.length === 0 && ccReview.length === 0 && rotations.length === 0 && <div style={{ ...F, fontSize: 10, color: 'var(--text3)' }}>No items in scope.</div>}
    </Panel>
  )
}

function OppRow({ symbol, badge, badgeTone, detail }: { symbol: string; badge: string; badgeTone: Tone; detail: string }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '75px 1fr', gap: 5, alignItems: 'center', padding: '3px 0', borderBottom: '1px solid var(--border-subtle)' }}>
      <span style={{ ...F, fontSize: 10, fontWeight: 800, color: '#fff' }}>{symbol}</span>
      <div>
        <TypeMiniChip label={badge} tone={badgeTone} />
        <div style={{ ...F, fontSize: 8, color: 'var(--text2)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', marginTop: 1 }}>{detail}</div>
      </div>
    </div>
  )
}

function MiniMetric({ label, val, tone }: { label: string; val: string; tone: Tone }) {
  return (
    <div style={{ background: 'rgba(10,13,18,0.8)', border: '1px solid rgba(255,255,255,0.06)', borderRadius: 8, padding: '8px 8px 6px' }}>
      <div style={{ ...F, fontSize: 7, color: 'var(--text3)', textTransform: 'uppercase', marginBottom: 3, fontWeight: 600 }}>{label}</div>
      <div style={{ ...F, fontSize: 15, fontWeight: 800, color: toneColor(tone), lineHeight: 1.1 }}>{val}</div>
    </div>
  )
}
