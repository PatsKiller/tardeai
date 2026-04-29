import React, { useState, useCallback, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import { fmt$, fmtPct, timeAgo } from '../lib/format'
import TaskDetailDrawer, { type TaskItem } from '../components/TaskDetailDrawer'
import { useToast } from '../components/ToastProvider'
import { DoughnutChart, BarChartJS } from '../components/charts'
import MetricTile from '../components/MetricTile'

/*
  ✅ Enhanced Morning Brief Task Cockpit — v6
  Improvements over v5:
  - Filter bar (All / Urgent / Review / Monitor) above action board
  - Inline quick-action buttons on rows → open drawer pre-filled
  - Decision history sidebar section from /api/v2/tasks/history
  - Expandable overnight intelligence section
  - Refresh all data button with last-updated timestamp
  - Toast notification after successful decisions
  - Auto-refresh tasks + chat-context after any decision
  - Better urgency highlighting (top rows glow, severity rail thicker)
  - Tighter spacing, denser information, operator language throughout
*/

// ── Types ─────────────────────────────────────────────────────────────────

type BriefSection = { priority: number; title: string; items: string[] }
type BriefData = { sections: BriefSection[]; next_actions: string[]; portfolio_summary: string; has_findings: boolean }
type StephItem = { symbol: string; category: string; reason: string; review_status: string; steph_verdict: string | null; steph_reasoning?: string | null; send_to_john: boolean; john_question: string | null }
type CoveredCall = { symbol: string; verdict: string; reasoning: string }
type Rotation = { from_symbol: string; to_symbol: string; switch_verdict: string; evidence: string }
type RecoveryItem = { symbol: string; analyst_verdict: string; analyst_confidence?: number; temp_allocation_verdict: string }
type ImprovementProposal = { id: number; category: string; title: string; status: string; created_at: string }
type JohnDecisionState = { pending_count: number; total?: number; overdue_count?: number; due_this_week?: number; by_status?: Record<string, number>; pending_items?: { id: number; symbol: string; title: string; action?: string }[]; deferred_items?: { id: number; symbol: string; title: string; revisit_on: string }[] }
type EvidenceSummary = { available?: boolean; symbols_checked: number; sufficiency: Record<string, number>; bias_flagged: number; conflicts: number }
type OutcomeTracking = { total: number; evaluated: number; pending: number; avg_score: number | null }
type ChatCtx = { morning_brief: BriefData; steph_escalations: StephItem[]; covered_calls: CoveredCall[]; rotations: Rotation[]; recovery: RecoveryItem[]; evidence_summary: EvidenceSummary; john_decisions: JohnDecisionState; outcome_tracking: OutcomeTracking; improvement_proposals?: ImprovementProposal[]; stop_coverage?: Record<string, number>; stop_briefs?: Record<string, unknown>[] }
type OverviewData = { portfolio_value: number; today_change: number; today_pct: number; as_of: string; last_repriced: string | null; pipeline_status: string; pipeline_completed: string | null; trade_ai?: { vix: number | null; breadth: string | null }; pending_approvals: number }
type RiskPos = { symbol: string; market_value: number; stop_price: number | null; current_price: number; distance_pct: number | null; max_loss: number; status?: string; triggered?: boolean }
type EscItem = { symbol: string; max_loss?: number; distance_pct?: number; market_value?: number }
type RiskData = { portfolio_heat_pct: number; total_risk_dollars: number; pct_protected: number; total_protected_mv?: number; total_unprotected_mv: number; position_count: number; positions: RiskPos[]; escalation?: { danger: EscItem[]; warning: EscItem[]; unprotected: EscItem[] } }
type ActionRow = { id: string; rank: number; severity: 'critical' | 'high' | 'medium' | 'low'; family: 'Risk' | 'Approval' | 'Steph Review' | 'Recovery' | 'Covered Call' | 'Rotation' | 'Deferred'; symbol: string; headline: string; detail: string; exposure: number | null; owner: 'John' | 'Steph' | 'Aegis' | 'Monitor' | 'Steph / John'; due: string; confidence: number | null; cta: string; route: string }
type HistoryItem = { id: number; symbol: string; category: string; title: string; priority: string; old_status: string; new_status: string; decision: string; reasoning: string; changed_at: string }
type TasksResp = { count: number; tasks: TaskItem[]; urgent: number; pending: number; failed_automation: number }
type HistoryResp = { count: number; history: HistoryItem[] }
type BoardFilter = 'all' | 'urgent' | 'review' | 'monitor'

// ── Constants & helpers ───────────────────────────────────────────────────

const F = { fontFamily: 'var(--sans)' as const }

// Glassmorphic card base — subtle depth + translucency
const glass = { background: 'rgba(16,20,28,0.92)', backdropFilter: 'blur(12px)', border: '1px solid rgba(255,255,255,0.07)', borderRadius: 12 } as const
const glassPanel = { ...glass, overflow: 'hidden' as const }
const glassStrip = { ...glass, overflow: 'hidden' as const }

const labelMap: Record<string, string> = { wait_monitor: 'Monitor for Re-entry', reentry_candidate: 'Re-entry Candidate', do_not_reenter: 'Avoid Re-entry', stay_cash: 'Stay in Cash', hold_for_reentry: 'Hold for Re-entry', rotate_existing_conviction: 'Rotate to Highest Conviction', review_needed: 'Review Required', avoid: 'Avoid', pending_review: 'Awaiting Review', resolved: 'Resolved', needs_john: 'Needs John Decision', consider: 'Under Review', not_yet: 'Not Yet', decided_action: 'Resolved', deferred: 'Deferred', rejected: 'Rejected', closed: 'Closed' }
const categoryMap: Record<string, string> = { rotation_review: 'Rotation', thesis_review: 'Thesis', stop_review: 'Stop Review', allocation_review: 'Allocation', covered_call: 'Covered Call', failed_stop_review: 'Failed Auto-Review' }
const ownerColor: Record<string, string> = { John: 'var(--amber)', Steph: 'var(--accent)', Aegis: 'var(--text2)', Monitor: 'var(--text2)', 'Steph / John': 'var(--purple)' }
const severityColor: Record<string, string> = { critical: 'var(--red)', high: 'var(--amber)', medium: 'var(--accent)', low: 'var(--text3)' }

function humanize(v?: string | null) { if (!v) return '—'; return labelMap[v] || categoryMap[v] || v.replace(/_/g, ' ').replace(/\b\w/g, s => s.toUpperCase()) }
function compactCurrency(n?: number | null) { if (n == null || Number.isNaN(n)) return '—'; const abs = Math.abs(n); if (abs >= 1e6) return `${n < 0 ? '-' : ''}$${(abs / 1e6).toFixed(1)}M`; if (abs >= 1e3) return `${n < 0 ? '-' : ''}$${(abs / 1e3).toFixed(0)}K`; return fmt$(n, 0) }
function parseUrgency(due: string) { const t = due.toLowerCase(); if (t === 'now' || t === 'overdue') return 'critical'; if (t === 'today') return 'high'; if (t.includes('week')) return 'medium'; return 'low' }
function canonicalTriggered(positions: RiskPos[]) { return positions.filter(p => p.triggered || (p.status || '').toUpperCase() === 'TRIGGERED') }
function confidenceLabel(v: number | null) { if (v == null || Number.isNaN(v)) return '—'; if (v >= 0.8) return 'High'; if (v >= 0.6) return 'Med'; return 'Low' }
type Tone = 'red' | 'amber' | 'green' | 'accent' | 'purple' | 'neutral'
function toneColor(t: Tone) { switch (t) { case 'red': return 'var(--red)'; case 'amber': return 'var(--amber)'; case 'green': return 'var(--green)'; case 'accent': return 'var(--accent)'; case 'purple': return 'var(--purple)'; default: return 'var(--text1)' } }
function toneFromDelta(v?: number | null): Tone { if (v == null) return 'neutral'; return v > 0 ? 'green' : v < 0 ? 'red' : 'neutral' }
function clampPct(v: number) { return Number.isNaN(v) ? 0 : Math.max(0, Math.min(100, v)) }
function titleCase(v: string) { return v.replace(/_/g, ' ').replace(/\b\w/g, s => s.toUpperCase()) }
function guessRouteFromAction(text: string) { const t = text.toLowerCase(); if (t.includes('risk') || t.includes('stop')) return '/risk'; if (t.includes('approval') || t.includes('steph')) return '/approvals'; if (t.includes('recovery')) return '/recovery'; return '/actions' }

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

  for (const p of triggered) rows.push({ id: `risk-${p.symbol}`, rank: ++rank, severity: 'critical', family: 'Risk', symbol: p.symbol, headline: 'Stop triggered — verify broker state', detail: p.stop_price ? `Stop ${fmt$(p.stop_price)} · Current ${fmt$(p.current_price)}` : 'Triggered', exposure: p.market_value || p.max_loss || null, owner: 'John', due: 'Now', confidence: null, cta: 'Open Risk', route: `/risk?symbol=${encodeURIComponent(p.symbol)}` })
  if (pendingApprovals > 0) rows.push({ id: 'approvals', rank: ++rank, severity: 'high', family: 'Approval', symbol: 'Queue', headline: `${pendingApprovals} approvals awaiting decision`, detail: 'Governance items need review before next cycle.', exposure: null, owner: 'John', due: 'Today', confidence: null, cta: 'Review', route: '/approvals' })
  for (const s of flaggedForJohn) rows.push({ id: `john-${s.symbol}`, rank: ++rank, severity: 'high', family: 'Steph Review', symbol: s.symbol, headline: `${humanize(s.category)} — needs John`, detail: s.john_question || s.reason || 'Steph escalated for decision.', exposure: null, owner: 'John', due: 'Today', confidence: null, cta: 'Review', route: '/approvals' })
  for (const d of danger) rows.push({ id: `danger-${d.symbol}`, rank: ++rank, severity: 'high', family: 'Risk', symbol: d.symbol, headline: 'Danger zone — near stop', detail: d.distance_pct != null ? `${d.distance_pct.toFixed(1)}% from stop` : 'Near threshold', exposure: d.market_value || d.max_loss || null, owner: 'Monitor', due: 'Today', confidence: null, cta: 'Inspect', route: `/risk?symbol=${encodeURIComponent(d.symbol)}` })
  for (const s of flaggedForSteph.slice(0, 4)) rows.push({ id: `steph-${s.symbol}`, rank: ++rank, severity: 'medium', family: 'Steph Review', symbol: s.symbol, headline: `${humanize(s.category)} — Steph reviewing`, detail: s.reason || 'Steph assessing.', exposure: null, owner: 'Steph', due: 'This week', confidence: null, cta: 'View', route: '/approvals' })
  for (const r of (ctx.recovery || []).slice(0, 3)) rows.push({ id: `recovery-${r.symbol}`, rank: ++rank, severity: 'medium', family: 'Recovery', symbol: r.symbol, headline: humanize(r.analyst_verdict), detail: `Allocation: ${humanize(r.temp_allocation_verdict)}`, exposure: null, owner: 'Aegis', due: 'Monitor', confidence: r.analyst_confidence ?? null, cta: 'Recovery', route: '/recovery' })
  for (const c of (ctx.covered_calls || []).filter(c => c.verdict === 'review_needed').slice(0, 3)) rows.push({ id: `cc-${c.symbol}`, rank: ++rank, severity: 'medium', family: 'Covered Call', symbol: c.symbol, headline: 'Covered-call candidate', detail: c.reasoning, exposure: null, owner: 'John', due: 'This week', confidence: null, cta: 'Review', route: '/actions' })
  for (const r of (ctx.rotations || []).slice(0, 3)) rows.push({ id: `rot-${r.from_symbol}-${r.to_symbol}`, rank: ++rank, severity: r.switch_verdict === 'consider' ? 'medium' : 'low', family: 'Rotation', symbol: `${r.from_symbol} → ${r.to_symbol}`, headline: humanize(r.switch_verdict), detail: r.evidence, exposure: null, owner: 'Steph / John', due: r.switch_verdict === 'consider' ? 'This week' : 'Later', confidence: null, cta: 'Review', route: '/approvals' })
  for (const d of johnDeferred.slice(0, 2)) rows.push({ id: `deferred-${d.id}`, rank: ++rank, severity: 'low', family: 'Deferred', symbol: d.symbol, headline: d.title, detail: 'Deferred — revisit on scheduled date.', exposure: null, owner: 'John', due: d.revisit_on, confidence: null, cta: 'Review', route: '/approvals' })
  for (const w of warnings.slice(0, 2)) rows.push({ id: `warn-${w.symbol}`, rank: ++rank, severity: 'low', family: 'Risk', symbol: w.symbol, headline: 'Warning zone', detail: w.distance_pct != null ? `${w.distance_pct.toFixed(1)}% from stop` : 'Risk present', exposure: w.market_value || null, owner: 'Monitor', due: 'Monitor', confidence: null, cta: 'Open Risk', route: `/risk?symbol=${encodeURIComponent(w.symbol)}` })
  if (rows.length < 10) for (const u of unprot.slice(0, 3)) rows.push({ id: `unprot-${u.symbol}`, rank: ++rank, severity: 'medium', family: 'Risk', symbol: u.symbol, headline: 'Large unprotected position', detail: 'No active stop protection.', exposure: u.market_value || null, owner: 'John', due: 'This week', confidence: null, cta: 'Review', route: `/risk?symbol=${encodeURIComponent(u.symbol)}` })

  return rows.sort((a, b) => { const s = ['critical', 'high', 'medium', 'low']; const d = s.indexOf(a.severity) - s.indexOf(b.severity); return d !== 0 ? d : a.rank - b.rank }).slice(0, 14).map((r, i) => ({ ...r, rank: i + 1 }))
}

// ── Main component ────────────────────────────────────────────────────────

export default function MorningBrief() {
  const nav = useNavigate()
  const { data: ctx } = useApi<ChatCtx>('/api/v2/aegis/chat-context')
  const { data: ov } = useApi<OverviewData>('/api/v2/overview')
  const { data: rk } = useApi<RiskData>('/api/v2/risk')
  const { data: tasksData } = useApi<TasksResp>('/api/v2/tasks')
  const { data: histData } = useApi<HistoryResp>('/api/v2/tasks/history')
  const [selectedTask, setSelectedTask] = useState<TaskItem | null>(null)
  const [decidedIds, setDecidedIds] = useState<Set<number>>(new Set())
  const [boardFilter, setBoardFilter] = useState<BoardFilter>('all')
  const [intelExpanded, setIntelExpanded] = useState(false)
  const [refreshKey, setRefreshKey] = useState(0)
  const lastRefreshed = useRef(new Date())
  const { showToast } = useToast()

  const handleTaskDecided = useCallback((taskId: number, status: string) => {
    setDecidedIds(s => new Set(s).add(taskId))
    setSelectedTask(null)
    showToast(`Decision saved: ${humanize(status)}`, 'success')
    setTimeout(() => setRefreshKey(k => k + 1), 500)
  }, [showToast])

  const handleRefresh = useCallback(() => {
    setRefreshKey(k => k + 1)
    lastRefreshed.current = new Date()
  }, [])

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

  return (
    <div style={{ ...F, paddingBottom: 24 }}>

      {/* ── Header with refresh ── */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', gap: 16, marginBottom: 14 }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 12 }}>
            <h1 style={{ ...F, fontSize: 18, fontWeight: 800, color: '#fff', letterSpacing: '-0.02em', margin: 0 }}>Daily Brief</h1>
            <span style={{ ...F, fontSize: 10, color: 'var(--text3)' }}>{ov?.as_of || 'Today'} · {ov?.pipeline_status || '—'} · repriced {ov?.last_repriced ? timeAgo(ov.last_repriced) : '—'}</span>
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <span style={{ fontSize: 8, color: 'var(--text3)' }}>Updated {lastRefreshed.current.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
          <button onClick={handleRefresh} style={{ ...F, fontSize: 9, fontWeight: 700, padding: '5px 12px', border: '1px solid var(--border)', borderRadius: 6, background: 'var(--bg3)', color: 'var(--text1)', cursor: 'pointer' }}>Refresh</button>
          {(decisions.pending_count || 0) > 0 || (ov?.pending_approvals || 0) > 0 ? (
            <button onClick={() => nav('/approvals')} style={{ ...F, fontSize: 9, fontWeight: 800, padding: '5px 14px', border: '1px solid var(--amber)', borderRadius: 6, background: `color-mix(in srgb, var(--amber) 12%, transparent)`, color: 'var(--amber)', cursor: 'pointer' }}>
              Review Items Pending
            </button>
          ) : null}
        </div>
      </div>

      {/* ── Metric Tiles ── */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 12, marginBottom: 16 }}>
        <MetricTile label="Portfolio Value" value={fmt$(ov?.portfolio_value ?? 0)} />
        <MetricTile label="Heat %" value={`${(rk?.portfolio_heat_pct ?? 0).toFixed(1)}%`} deltaColor={(rk?.portfolio_heat_pct ?? 0) >= 5 ? 'var(--amber)' : 'var(--green)'} delta={(rk?.portfolio_heat_pct ?? 0) >= 5 ? 'elevated' : 'normal'} />
        <MetricTile label="Protected" value={`${(rk?.pct_protected ?? 0).toFixed(0)}%`} deltaColor="var(--green)" delta={`${rk?.position_count || 0} positions`} />
        <MetricTile label="Pending Tasks" value={String(tasksData?.pending || 0)} deltaColor={(tasksData?.urgent || 0) > 0 ? 'var(--red)' : 'var(--text3)'} delta={`${tasksData?.urgent || 0} urgent`} />
      </div>

      {/* ── Command strip ── */}
      <div style={{ display: 'grid', gridTemplateColumns: `repeat(10, minmax(0, 1fr))`, gap: 1, ...glassStrip, marginBottom: 16 }}>
        {[
          { label: 'Portfolio', value: fmt$(ov?.portfolio_value ?? 0), tone: 'neutral' as Tone, route: '/portfolio' },
          { label: 'Today', value: fmt$(ov?.today_change ?? 0), sub: ov?.today_pct != null ? fmtPct(ov.today_pct, 2) : undefined, tone: toneFromDelta(ov?.today_change), route: '/returns' },
          { label: 'Heat', value: `${(rk?.portfolio_heat_pct ?? 0).toFixed(1)}%`, tone: (rk?.portfolio_heat_pct ?? 0) >= 5 ? 'amber' as Tone : 'neutral' as Tone, route: '/risk' },
          { label: 'Triggered', value: String(triggered.length), sub: triggered.length ? triggered.map(t => t.symbol).slice(0, 3).join(', ') : 'None', tone: triggered.length ? 'red' as Tone : 'green' as Tone, route: '/risk' },
          { label: 'Unprotected', value: `${unprotected.length} / ${compactCurrency(rk?.total_unprotected_mv ?? 0)}`, tone: (rk?.total_unprotected_mv ?? 0) > 0 ? 'amber' as Tone : 'green' as Tone, route: '/risk' },
          { label: 'Steph', value: String(stephPending.length), sub: stephPending.length ? 'Reviewing' : 'Clear', tone: stephPending.length ? 'amber' as Tone : 'green' as Tone, route: '/approvals' },
          { label: 'John', value: String(decisions.pending_count || 0), sub: (decisions.overdue_count || 0) > 0 ? `${decisions.overdue_count} overdue` : '', tone: (decisions.pending_count || 0) > 0 ? 'amber' as Tone : 'green' as Tone, route: '/approvals' },
          { label: 'Approvals', value: String(ov?.pending_approvals || 0), tone: (ov?.pending_approvals || 0) > 0 ? 'amber' as Tone : 'green' as Tone, route: '/approvals' },
          { label: 'Evidence', value: `${evidence.symbols_checked || 0} sym`, sub: evidence.bias_flagged ? `${evidence.bias_flagged} flagged` : 'clean', tone: evidence.bias_flagged ? 'amber' as Tone : 'green' as Tone, route: '/actions' },
          { label: 'Pipeline', value: titleCase(ov?.pipeline_status || 'Unknown'), sub: ov?.pipeline_completed ? timeAgo(ov.pipeline_completed) : undefined, tone: ov?.pipeline_status === 'fresh' ? 'green' as Tone : 'amber' as Tone, route: '/orchestration' },
        ].map(item => (
          <button key={item.label} onClick={() => nav(item.route)} style={{ ...F, background: 'rgba(16,20,28,0.85)', border: 0, textAlign: 'left', padding: '10px 10px 8px', cursor: 'pointer', minWidth: 0, transition: 'background 100ms' }}
            onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = 'rgba(30,40,55,0.9)' }}
            onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = 'rgba(16,20,28,0.85)' }}>
            <div style={{ fontSize: 8, textTransform: 'uppercase', letterSpacing: '.05em', color: 'var(--text3)', marginBottom: 4, fontWeight: 600 }}>{item.label}</div>
            <div style={{ fontSize: 14, fontWeight: 800, color: toneColor(item.tone), lineHeight: 1.1 }}>{item.value}</div>
            {item.sub ? <div style={{ fontSize: 8, color: item.tone === 'red' || item.tone === 'amber' ? toneColor(item.tone) : 'var(--text3)', marginTop: 2, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{item.sub}</div> : <div style={{ height: 11 }} />}
          </button>
        ))}
      </div>

      {/* ── Main grid: action board + sidebar ── */}
      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) 300px', gap: 20, alignItems: 'start', marginBottom: 16 }}>

        {/* ── Action Board ── */}
        <section style={{ ...glassPanel }}>
          {/* Board header + filter bar */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 14px', borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
              <h2 style={{ ...F, fontSize: 14, fontWeight: 700, color: '#fff', margin: 0, letterSpacing: '-0.01em' }}>Action Board</h2>
              <span style={{ ...F, fontSize: 9, color: 'var(--text3)' }}>{actionRows.length}{boardFilter !== 'all' ? ` of ${allRows.length}` : ''} items</span>
            </div>
            <div style={{ display: 'flex', gap: 2 }}>
              {(['all', 'urgent', 'review', 'monitor'] as BoardFilter[]).map(f => {
                const count = f === 'all' ? allRows.length : f === 'urgent' ? allRows.filter(r => r.severity === 'critical' || r.severity === 'high').length : f === 'review' ? allRows.filter(r => r.owner === 'John' || r.owner === 'Steph / John').length : allRows.filter(r => r.owner === 'Monitor' || r.owner === 'Aegis').length
                const active = boardFilter === f
                return (
                  <button key={f} onClick={() => setBoardFilter(f)} style={{ ...F, fontSize: 10, fontWeight: active ? 800 : 600, padding: '5px 14px', border: `1px solid ${active ? 'var(--accent)' : 'rgba(255,255,255,0.1)'}`, borderRadius: 9999, background: active ? 'var(--accent-dim)' : 'rgba(255,255,255,0.04)', color: active ? 'var(--accent)' : 'var(--text3)', cursor: 'pointer', transition: 'all 100ms' }}>
                    {f === 'all' ? 'All' : f === 'urgent' ? 'Urgent' : f === 'review' ? 'Review' : 'Monitor'} {count > 0 ? `(${count})` : ''}
                  </button>
                )
              })}
            </div>
          </div>

          {/* Board rows */}
          <div style={{ padding: '6px 0' }}>
            {actionRows.length === 0 ? (
              <div style={{ ...F, padding: '20px 12px', textAlign: 'center', color: 'var(--text3)', fontSize: 11 }}>
                {boardFilter !== 'all' ? 'No items match this filter.' : 'No actionable items. Portfolio is stable.'}
              </div>
            ) : actionRows.map((row, idx) => {
              const isTop = idx < 2 && (row.severity === 'critical' || row.severity === 'high')
              const pct = row.exposure ? Math.max(7, Math.min(100, (row.exposure / maxExposure) * 100)) : 0
              const matchingTask = johnTasks.find(t => t.symbol === row.symbol)
              return (
                <div key={row.id} onClick={() => matchingTask ? setSelectedTask(matchingTask) : nav(row.route)} style={{
                  display: 'grid', gridTemplateColumns: '5px 32px 80px minmax(0,1.3fr) 110px 70px 60px 80px',
                  alignItems: 'center', padding: '2px 0', margin: '0 8px', borderRadius: 8, cursor: 'pointer',
                  background: isTop ? `linear-gradient(90deg, ${severityColor[row.severity]}08, transparent)` : 'transparent',
                  borderBottom: '1px solid var(--border-subtle)', transition: 'background 60ms',
                }} onMouseEnter={e => { if (!isTop) (e.currentTarget as HTMLElement).style.background = 'var(--bg3)' }} onMouseLeave={e => { if (!isTop) (e.currentTarget as HTMLElement).style.background = '' }}>
                  <div style={{ width: 5, alignSelf: 'stretch', borderRadius: '3px 0 0 3px', background: severityColor[row.severity] }} />
                  <div style={{ padding: '8px 4px', textAlign: 'center', fontWeight: 800, fontSize: 11, color: row.rank <= 2 ? '#fff' : 'var(--text3)' }}>{row.rank}</div>
                  <div style={{ padding: '6px 4px', display: 'flex', flexDirection: 'column', gap: 2 }}>
                    <span style={{ ...F, fontSize: 13, fontWeight: 800, color: '#fff' }}>{row.symbol}</span>
                    <TypeMiniChip label={row.family} tone={row.severity === 'critical' ? 'red' : row.severity === 'high' ? 'amber' : row.family === 'Recovery' ? 'accent' : row.family === 'Covered Call' ? 'green' : row.family === 'Rotation' ? 'purple' : 'neutral'} />
                  </div>
                  <div style={{ padding: '6px 8px', overflow: 'hidden' }}>
                    <div style={{ ...F, fontSize: 10, fontWeight: 700, color: 'var(--text0)', lineHeight: 1.3 }}>{row.headline}</div>
                    <div style={{ ...F, fontSize: 9, color: 'var(--text2)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{row.detail}</div>
                  </div>
                  <div style={{ padding: '6px 6px' }}>
                    {row.exposure ? (<><div style={{ ...F, fontSize: 10, fontWeight: 700, color: '#fff' }}>{compactCurrency(row.exposure)}</div><div style={{ height: 3, background: 'var(--bg3)', borderRadius: 99, marginTop: 3, overflow: 'hidden' }}><div style={{ height: '100%', width: `${pct}%`, background: severityColor[row.severity] }} /></div></>) : <span style={{ fontSize: 9, color: 'var(--text3)' }}>—</span>}
                  </div>
                  <div style={{ padding: '6px 4px' }}><OwnerChip owner={row.owner} /></div>
                  <div style={{ padding: '6px 4px' }}><DueChip due={row.due} /></div>
                  <div style={{ padding: '6px 4px', display: 'flex', justifyContent: 'flex-end' }}>
                    {matchingTask ? (
                      <button onClick={e => { e.stopPropagation(); setSelectedTask(matchingTask) }} style={{ ...F, fontSize: 10, fontWeight: 800, padding: '6px 16px', border: 'none', borderRadius: 8, background: row.severity === 'critical' ? '#b91c1c' : severityColor[row.severity], color: '#fff', cursor: 'pointer', whiteSpace: 'nowrap', transition: 'opacity 100ms', letterSpacing: '0.02em' }}
                        onMouseEnter={e => { (e.currentTarget as HTMLElement).style.opacity = '0.85' }}
                        onMouseLeave={e => { (e.currentTarget as HTMLElement).style.opacity = '1' }}>Decide</button>
                    ) : (
                      <button onClick={e => { e.stopPropagation(); nav(row.route) }} style={{ ...F, fontSize: 8, fontWeight: 700, padding: '4px 8px', border: '1px solid var(--border)', borderRadius: 4, background: 'transparent', color: 'var(--text2)', cursor: 'pointer', whiteSpace: 'nowrap' }}>{row.cta}</button>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        </section>

        {/* ── Sidebar ── */}
        <div style={{ display: 'grid', gap: 12 }}>
          {/* Queue stats */}
          <Panel title="Decision Queue" action={<SmallBtn label="Approvals" onClick={() => nav('/approvals')} />}>
            <div style={{ display: 'grid', gap: 6 }}>
              <QStat label="Pending approvals" val={ov?.pending_approvals || 0} tone={(ov?.pending_approvals || 0) > 0 ? 'amber' : 'green'} onClick={() => nav('/approvals')} />
              <QStat label="Steph reviewing" val={stephPending.length} tone={stephPending.length > 0 ? 'accent' : 'green'} />
              <QStat label="Overdue" val={decisions.overdue_count || 0} tone={(decisions.overdue_count || 0) > 0 ? 'red' : 'green'} />
              <QStat label="Deferred" val={(decisions.deferred_items || []).length} tone="neutral" />
              <QStat label="Outcomes" val={`${outcomes.evaluated}/${outcomes.total}`} tone="neutral" />
              {outcomes.avg_score != null && <QStat label="Avg score" val={outcomes.avg_score.toFixed(2)} tone={outcomes.avg_score >= 0.6 ? 'green' : 'amber'} />}
            </div>

            {/* John tasks in sidebar */}
            {johnTasks.length > 0 && (
              <div style={{ marginTop: 8, borderTop: '1px solid var(--border-subtle)', paddingTop: 8 }}>
                <div style={{ ...F, fontSize: 8, fontWeight: 800, color: 'var(--text3)', textTransform: 'uppercase', marginBottom: 4 }}>John Tasks ({johnTasks.length})</div>
                {johnTasks.slice(0, 4).map(task => (
                  <button key={task.id} onClick={() => setSelectedTask(task)} style={{ ...F, width: '100%', textAlign: 'left', background: 'var(--bg1)', border: `1px solid ${task.priority === 'urgent' ? 'var(--red)' : 'var(--border)'}55`, borderLeft: `3px solid ${task.priority === 'urgent' ? 'var(--red)' : 'var(--amber)'}`, borderRadius: 6, padding: '6px 8px', cursor: 'pointer', marginBottom: 4 }}>
                    <div style={{ fontSize: 10, fontWeight: 800, color: '#fff' }}>{task.symbol}</div>
                    <div style={{ fontSize: 9, color: 'var(--text2)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{task.title}</div>
                    <div style={{ fontSize: 8, color: task.category === 'failed_stop_review' ? 'var(--red)' : 'var(--amber)', fontWeight: 700, marginTop: 2 }}>{task.category === 'failed_stop_review' ? 'Auto-review failed — Decide' : humanize(task.status)}</div>
                  </button>
                ))}
              </div>
            )}
          </Panel>

          {/* Decision history */}
          {history.length > 0 && (
            <Panel title="Recent Decisions" action={<SmallBtn label="Ops" onClick={() => nav('/ops')} />}>
              {history.slice(0, 4).map(h => (
                <div key={h.id} style={{ display: 'flex', gap: 6, padding: '4px 0', borderBottom: '1px solid var(--border-subtle)', fontSize: 9, alignItems: 'center' }}>
                  <span style={{ fontWeight: 700, padding: '1px 4px', borderRadius: 3, background: h.new_status === 'decided_action' ? 'var(--green-dim)' : h.new_status === 'deferred' ? 'var(--amber-dim)' : 'var(--red-dim)', color: h.new_status === 'decided_action' ? 'var(--green)' : h.new_status === 'deferred' ? 'var(--amber)' : 'var(--red)', fontSize: 7 }}>{humanize(h.new_status)}</span>
                  <span style={{ fontWeight: 700, color: 'var(--text0)' }}>{h.symbol || '—'}</span>
                  <span style={{ flex: 1, color: 'var(--text2)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{(h.reasoning || h.decision || '').slice(0, 30)}</span>
                  <span style={{ color: 'var(--text3)' }}>{h.changed_at ? timeAgo(h.changed_at) : ''}</span>
                </div>
              ))}
            </Panel>
          )}

          {/* Next actions */}
          {brief.next_actions.length > 0 && (
            <Panel title="Next 15 Minutes">
              {brief.next_actions.slice(0, 4).map((item, idx) => (
                <div key={idx} style={{ display: 'flex', gap: 6, alignItems: 'start', padding: '5px 0', borderBottom: '1px solid var(--border-subtle)' }}>
                  <span style={{ ...F, fontSize: 10, fontWeight: 800, color: idx === 0 ? 'var(--amber)' : 'var(--text2)', width: 14, flexShrink: 0 }}>{idx + 1}</span>
                  <span style={{ ...F, fontSize: 10, color: 'var(--text1)', lineHeight: 1.4 }}>{item}</span>
                </div>
              ))}
            </Panel>
          )}
        </div>
      </div>

      {/* ── Risk + Opportunity panels ── */}
      <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 1fr', gap: 20, marginBottom: 16 }}>
        <RiskExposurePanel ov={ov || null} rk={rk || null} triggered={triggered} danger={danger} warnings={warnings} unprotected={unprotected} protectionPct={protectionPct} unprotectedPct={unprotectedPct} onNavigate={nav} />
        <OpportunityPanel recovery={ctx.recovery || []} coveredCalls={ctx.covered_calls || []} rotations={ctx.rotations || []} onNavigate={nav} />
      </div>

      {/* ── Charts: Risk positions + Task status ── */}
      <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 1fr', gap: 20, marginBottom: 16 }}>
        {/* Top 5 risk positions by daily change */}
        {positions.length > 0 && (
          <div style={{ ...glassPanel, padding: 16 }}>
            <div style={{ ...F, fontSize: 11, fontWeight: 800, color: '#fff', marginBottom: 12 }}>Top Risk Positions (by max loss)</div>
            <BarChartJS
              labels={positions.slice().sort((a, b) => (b.max_loss || 0) - (a.max_loss || 0)).slice(0, 5).map(p => p.symbol)}
              data={positions.slice().sort((a, b) => (b.max_loss || 0) - (a.max_loss || 0)).slice(0, 5).map(p => -(p.max_loss || 0))}
              height={120}
            />
          </div>
        )}
        {/* Task status distribution */}
        {tasksData && (tasksData.count || 0) > 0 && (
          <div style={{ ...glassPanel, padding: 16, display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
            <div style={{ ...F, fontSize: 11, fontWeight: 800, color: '#fff', marginBottom: 12, alignSelf: 'flex-start' }}>Task Status</div>
            <DoughnutChart
              labels={['Pending', 'Urgent', 'Completed']}
              data={[tasksData.pending || 0, tasksData.urgent || 0, Math.max(0, (tasksData.count || 0) - (tasksData.pending || 0) - (tasksData.urgent || 0))]}
              colors={['#f0b90b', '#f6465d', '#0ecb81']}
              height={130}
            />
          </div>
        )}
      </div>

      {/* ── Trust strip ── */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6, minmax(0, 1fr))', gap: 1, ...glassStrip, marginBottom: 14 }}>
        {[
          { label: 'Evidence', value: `${evidence.symbols_checked || 0} symbols`, sub: Object.entries(evidence.sufficiency || {}).map(([k, v]) => `${k}: ${v}`).join(' · ') || '—', tone: 'neutral' as Tone },
          { label: 'Bias', value: evidence.bias_flagged ? `${evidence.bias_flagged} flagged` : 'Clean', tone: evidence.bias_flagged ? 'amber' as Tone : 'green' as Tone },
          { label: 'Conflicts', value: evidence.conflicts ? `${evidence.conflicts}` : 'None', tone: evidence.conflicts ? 'amber' as Tone : 'green' as Tone },
          { label: 'Outcomes', value: `${outcomes.evaluated}/${outcomes.total}`, sub: outcomes.avg_score != null ? `avg ${outcomes.avg_score.toFixed(2)}` : '', tone: outcomes.avg_score != null && outcomes.avg_score >= 0.6 ? 'green' as Tone : 'neutral' as Tone },
          { label: 'Pipeline', value: titleCase(ov?.pipeline_status || 'Unknown'), sub: ov?.pipeline_completed ? timeAgo(ov.pipeline_completed) : '', tone: ov?.pipeline_status === 'fresh' ? 'green' as Tone : 'amber' as Tone },
          { label: 'Stop Coverage', value: stopCov.total ? `${stopCov.fresh || 0}/${stopCov.total}` : '—', sub: stopCov.triggered ? `${stopCov.triggered} triggered` : '', tone: stopCov.fresh === stopCov.total ? 'green' as Tone : 'amber' as Tone },
        ].map(c => (
          <div key={c.label} style={{ background: 'rgba(16,20,28,0.85)', padding: '8px 10px' }}>
            <div style={{ ...F, fontSize: 7, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '.04em', marginBottom: 2 }}>{c.label}</div>
            <div style={{ ...F, fontSize: 12, fontWeight: 800, color: toneColor(c.tone) }}>{c.value}</div>
            {c.sub && <div style={{ ...F, fontSize: 8, color: 'var(--text3)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{c.sub}</div>}
          </div>
        ))}
      </div>

      {/* ── Overnight intelligence (expandable) ── */}
      {brief.has_findings && brief.sections.length > 0 && (
        <section style={{ ...glassPanel, marginBottom: 14 }}>
          <button onClick={() => setIntelExpanded(!intelExpanded)} style={{ ...F, width: '100%', display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 12px', background: 'transparent', border: 0, cursor: 'pointer', borderBottom: intelExpanded ? '1px solid var(--border-subtle)' : 'none' }}>
            <span style={{ fontSize: 11, fontWeight: 800, color: '#fff' }}>Overnight Intelligence ({brief.sections.length} sections)</span>
            <span style={{ fontSize: 10, color: 'var(--text3)' }}>{intelExpanded ? '▲ Collapse' : '▼ Expand'}</span>
          </button>
          {intelExpanded && (
            <div style={{ padding: 12, display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(250px, 1fr))', gap: 10 }}>
              {brief.sections.map((s, i) => (
                <div key={i}>
                  <div style={{ ...F, fontSize: 9, fontWeight: 700, color: s.priority === 1 ? 'var(--red)' : s.priority === 2 ? 'var(--amber)' : 'var(--text1)', textTransform: 'uppercase', marginBottom: 3 }}>{s.title}</div>
                  {s.items.slice(0, 3).map((item, j) => (
                    <div key={j} style={{ ...F, fontSize: 10, color: 'var(--text2)', lineHeight: 1.4, padding: '2px 0 2px 8px', borderLeft: `2px solid ${s.priority === 1 ? 'var(--red)' : s.priority === 2 ? 'var(--amber)' : 'var(--border)'}`, marginBottom: 2 }}>{item}</div>
                  ))}
                </div>
              ))}
            </div>
          )}
        </section>
      )}

      {/* ── Bottom nav ── */}
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        {[['Risk', '/risk'], ['Approvals', '/approvals'], ['Recovery', '/recovery'], ['Actions', '/actions'], ['Holdings', '/portfolio'], ['Journal', '/journal-analytics'], ['Ops', '/ops']].map(([l, r]) => (
          <button key={r} onClick={() => nav(r)} style={{ ...F, padding: '6px 12px', fontSize: 10, fontWeight: 600, border: '1px solid rgba(255,255,255,0.08)', borderRadius: 8, background: 'rgba(255,255,255,0.04)', color: 'var(--text2)', cursor: 'pointer', transition: 'all 100ms' }}
            onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = 'rgba(255,255,255,0.08)'; (e.currentTarget as HTMLElement).style.color = 'var(--text0)' }}
            onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = 'rgba(255,255,255,0.04)'; (e.currentTarget as HTMLElement).style.color = 'var(--text2)' }}>{l}</button>
        ))}
      </div>

      {/* ── Task drawer ── */}
      <TaskDetailDrawer task={selectedTask} onClose={() => setSelectedTask(null)} onDecided={handleTaskDecided} />
    </div>
  )
}

// ── Sub-components ────────────────────────────────────────────────────────

function Panel({ title, action, children }: { title: string; action?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section style={{ ...glassPanel }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 12px', borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
        <h2 style={{ ...F, fontSize: 11, fontWeight: 800, color: '#fff', margin: 0 }}>{title}</h2>
        {action}
      </div>
      <div style={{ padding: '8px 10px' }}>{children}</div>
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
  return <span style={{ ...F, fontSize: 8, fontWeight: 800, color: ownerColor[owner] || 'var(--text3)', background: `${ownerColor[owner] || 'var(--text3)'}15`, border: `1px solid ${ownerColor[owner] || 'var(--text3)'}55`, borderRadius: 99, padding: '2px 6px', whiteSpace: 'nowrap' }}>{owner}</span>
}

function DueChip({ due }: { due: string }) {
  const tone = parseUrgency(due)
  const c = toneColor(tone === 'critical' ? 'red' : tone === 'high' ? 'amber' : tone === 'medium' ? 'accent' : 'neutral')
  return <span style={{ ...F, fontSize: 8, fontWeight: 800, color: c, background: `${c}15`, borderRadius: 99, padding: '2px 6px', whiteSpace: 'nowrap' }}>{due}</span>
}

function TypeMiniChip({ label, tone }: { label: string; tone: Tone }) {
  return <span style={{ ...F, fontSize: 7, fontWeight: 800, color: toneColor(tone), background: `${toneColor(tone)}15`, border: `1px solid ${toneColor(tone)}55`, borderRadius: 99, padding: '1px 5px', whiteSpace: 'nowrap' }}>{label}</span>
}

// ── Risk panel ────────────────────────────────────────────────────────────

function RiskExposurePanel({ ov, rk, triggered, danger, warnings, unprotected, protectionPct, unprotectedPct, onNavigate }: { ov: OverviewData | null; rk: RiskData | null; triggered: RiskPos[]; danger: EscItem[]; warnings: EscItem[]; unprotected: EscItem[]; protectionPct: number; unprotectedPct: number; onNavigate: (r: string) => void }) {
  const topRisk = [...triggered.map(p => ({ sym: p.symbol, amt: p.market_value || p.max_loss || 0, lbl: 'Triggered' })), ...danger.map(p => ({ sym: p.symbol, amt: p.market_value || p.max_loss || 0, lbl: 'Danger' })), ...warnings.slice(0, 3).map(p => ({ sym: p.symbol, amt: p.market_value || p.max_loss || 0, lbl: 'Warning' })), ...unprotected.slice(0, 3).map(p => ({ sym: p.symbol, amt: p.market_value || 0, lbl: 'Unprotected' }))].sort((a, b) => b.amt - a.amt).slice(0, 6)
  const maxR = Math.max(1, ...topRisk.map(r => r.amt))
  return (
    <Panel title="Risk & Exposure" action={<SmallBtn label="Full Risk View" onClick={() => onNavigate('/risk')} />}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8, marginBottom: 10 }}>
        <Metric label="Total risk" val={fmt$(rk?.total_risk_dollars ?? 0)} tone="red" />
        <Metric label="Heat" val={`${(rk?.portfolio_heat_pct ?? 0).toFixed(1)}%`} tone={(rk?.portfolio_heat_pct ?? 0) >= 5 ? 'amber' : 'neutral'} />
        <Metric label="Protected" val={`${protectionPct.toFixed(0)}%`} tone={protectionPct >= 50 ? 'green' : 'amber'} />
        <Metric label="Positions" val={String(rk?.position_count || 0)} tone="neutral" />
      </div>
      <div style={{ marginBottom: 10 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 8, fontWeight: 700, marginBottom: 4, ...F }}>
          <span style={{ color: 'var(--green)' }}>Protected {protectionPct.toFixed(0)}%</span>
          <span style={{ color: 'var(--amber)' }}>Unprotected {unprotectedPct.toFixed(0)}%</span>
        </div>
        <div style={{ height: 12, background: 'var(--bg3)', borderRadius: 99, overflow: 'hidden', display: 'flex' }}>
          <div style={{ width: `${protectionPct}%`, background: 'linear-gradient(90deg, rgba(14,203,129,0.6), rgba(14,203,129,0.3))' }} />
          <div style={{ width: `${unprotectedPct}%`, background: 'linear-gradient(90deg, rgba(240,185,11,0.5), rgba(240,185,11,0.2))' }} />
        </div>
      </div>
      {topRisk.map(r => {
        const pct = Math.max(8, (r.amt / maxR) * 100)
        const tone: Tone = r.lbl === 'Triggered' ? 'red' : r.lbl === 'Danger' ? 'amber' : 'neutral'
        return (
          <div key={`${r.lbl}-${r.sym}`} onClick={() => onNavigate(`/risk?symbol=${r.sym}`)} style={{ display: 'grid', gridTemplateColumns: '50px 70px 1fr 70px', alignItems: 'center', gap: 6, padding: '3px 0', cursor: 'pointer' }}>
            <span style={{ ...F, fontSize: 10, fontWeight: 800, color: '#fff' }}>{r.sym}</span>
            <TypeMiniChip label={r.lbl} tone={tone} />
            <div style={{ height: 6, background: 'var(--bg3)', borderRadius: 99, overflow: 'hidden' }}><div style={{ width: `${pct}%`, height: '100%', background: toneColor(tone) }} /></div>
            <span style={{ ...F, fontSize: 10, fontWeight: 700, color: toneColor(tone), textAlign: 'right' }}>{compactCurrency(r.amt)}</span>
          </div>
        )
      })}
      {topRisk.length === 0 && <div style={{ ...F, fontSize: 10, color: 'var(--text3)' }}>No quantified risk items.</div>}
    </Panel>
  )
}

// ── Opportunity panel ─────────────────────────────────────────────────────

function OpportunityPanel({ recovery, coveredCalls, rotations, onNavigate }: { recovery: RecoveryItem[]; coveredCalls: CoveredCall[]; rotations: Rotation[]; onNavigate: (r: string) => void }) {
  const ccReview = coveredCalls.filter(c => c.verdict === 'review_needed')
  const ccAvoid = coveredCalls.filter(c => c.verdict === 'avoid')
  return (
    <Panel title="Opportunity & Recovery" action={<SmallBtn label="Recovery" onClick={() => onNavigate('/recovery')} />}>
      {recovery.length > 0 && <SubHead label={`Recovery (${recovery.length})`} />}
      {recovery.map(r => (
        <OppRow key={r.symbol} symbol={r.symbol} badge={humanize(r.analyst_verdict)} badgeTone={r.analyst_verdict === 'reentry_candidate' ? 'green' : 'accent'} detail={`Alloc: ${humanize(r.temp_allocation_verdict)}`} confidence={r.analyst_confidence ?? 0.5} />
      ))}
      {(ccReview.length + ccAvoid.length) > 0 && <SubHead label={`Covered Calls (${ccReview.length + ccAvoid.length})`} />}
      {[...ccReview, ...ccAvoid].map(c => (
        <OppRow key={c.symbol} symbol={c.symbol} badge={humanize(c.verdict)} badgeTone={c.verdict === 'avoid' ? 'red' : 'amber'} detail={c.reasoning} confidence={c.verdict === 'review_needed' ? 0.65 : 0.35} />
      ))}
      {rotations.length > 0 && <SubHead label={`Rotations (${rotations.length})`} />}
      {rotations.slice(0, 3).map(r => (
        <OppRow key={`${r.from_symbol}-${r.to_symbol}`} symbol={`${r.from_symbol} → ${r.to_symbol}`} badge={humanize(r.switch_verdict)} badgeTone={r.switch_verdict === 'consider' ? 'purple' : 'neutral'} detail={r.evidence} confidence={r.switch_verdict === 'consider' ? 0.6 : 0.4} />
      ))}
      {recovery.length === 0 && ccReview.length === 0 && ccAvoid.length === 0 && rotations.length === 0 && <div style={{ ...F, fontSize: 10, color: 'var(--text3)' }}>No items in scope.</div>}
    </Panel>
  )
}

function SubHead({ label }: { label: string }) { return <div style={{ ...F, fontSize: 8, fontWeight: 800, textTransform: 'uppercase', color: 'var(--text3)', marginTop: 6, marginBottom: 2 }}>{label}</div> }

function OppRow({ symbol, badge, badgeTone, detail, confidence }: { symbol: string; badge: string; badgeTone: Tone; detail: string; confidence: number }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '80px 1fr 40px', gap: 6, alignItems: 'center', padding: '4px 0', borderBottom: '1px solid var(--border-subtle)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
        <span style={{ ...F, fontSize: 11, fontWeight: 800, color: '#fff' }}>{symbol}</span>
      </div>
      <div>
        <TypeMiniChip label={badge} tone={badgeTone} />
        <div style={{ ...F, fontSize: 9, color: 'var(--text2)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', marginTop: 1 }}>{detail}</div>
      </div>
      <div style={{ height: 4, background: 'var(--bg3)', borderRadius: 99, overflow: 'hidden' }}><div style={{ width: `${Math.max(10, confidence * 100)}%`, height: '100%', background: confidence >= 0.7 ? 'var(--green)' : 'var(--amber)' }} /></div>
    </div>
  )
}

function Metric({ label, val, tone }: { label: string; val: string; tone: Tone }) {
  return (
    <div style={{ background: 'rgba(10,13,18,0.8)', border: '1px solid rgba(255,255,255,0.06)', borderRadius: 10, padding: '10px 10px 8px' }}>
      <div style={{ ...F, fontSize: 8, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '.05em', marginBottom: 4, fontWeight: 600 }}>{label}</div>
      <div style={{ ...F, fontSize: 18, fontWeight: 800, color: toneColor(tone), lineHeight: 1.1 }}>{val}</div>
    </div>
  )
}
