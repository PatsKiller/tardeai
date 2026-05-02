import { useState, useCallback, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import SectionHeader from '../components/SectionHeader'
import TaskDetailDrawer, { type TaskItem } from '../components/TaskDetailDrawer'
import { useApi } from '../hooks/useApi'
import { fmt$, timeAgo } from '../lib/format'
import AccountBadge from '../components/AccountBadge'
import ProposalDetailDrawer from '../components/ProposalDetailDrawer'

interface JohnTask { id: number; source: string; category: string; symbol: string; title: string; description: string; priority: string; status: string; recommendation: string; confidence: number; due_by: string; linked_route: string; followup: string; decided_at: string; created_at: string; provenance: Record<string, unknown> }
interface TasksData { count: number; tasks: JohnTask[]; urgent: number; pending: number; failed_automation: number }

interface RiskPos { symbol: string; name?: string; current_price: number; stop_price: number | null; distance_pct: number | null; max_loss: number; market_value: number; triggered: boolean; status: string; rsi?: number | null; sma200_pct?: number | null; beta?: number | null; pnl_if_stopped?: number | null; shares?: number; total_position_value?: number }
interface Evidence { severity?: number; trigger_rule?: string; escalation_summary?: string; yahoo_analyst?: { current_price?: string; target_mean_price?: string; recommendation_key?: string; number_of_analyst_opinions?: number }; article_context?: { article_count_7d?: number; analyst_article_count?: number; categories?: string[]; top_titles?: { title: string; source: string }[] } }
interface RiskContext { triggered?: RiskPos[]; danger?: RiskPos[]; total_positions?: number; total_with_stops?: number; position?: RiskPos; warning?: string | string[] }
interface QueueItem {
  id: number; recommendation_id: number; symbol: string | null; action: string
  rationale: string; confidence: number; urgency: string; status: string
  expires_at: string | null; dedupe_key: string; created_at: string
  rec_date?: string; rec_symbol?: string; rec_action?: string; rec_rationale?: string
  rec_confidence?: number; rec_model?: string; rec_expires?: string
  evidence?: Evidence; risk_context?: RiskContext
  decision_summary?: { what: string; why: string; risk: string; exposure?: string | null; next_action?: string; followup: string; positions_affected: number; total_monitored: number }
}
interface ApprovalData { count: number; pending: QueueItem[] }
interface DecisionItem { id: number; action_queue_id: number; decision: string; decision_reason: string; decided_by: string; decided_at: string; notes: string; symbol: string | null; action: string; rationale: string; confidence: number }
interface HistoryData { count: number; decisions: DecisionItem[] }

const urgencyColor: Record<string, string> = { urgent: 'var(--red)', normal: 'var(--amber)', low: 'var(--text3)' }
const urgencyBg: Record<string, string> = { urgent: 'var(--red-dim)', normal: 'var(--amber-dim)', low: 'var(--bg3)' }
const ACTION_ICON: Record<string, string> = { STOP_REVIEW: '\u{1f6d1}', ALLOCATION_REVIEW: '\u2696', REBALANCE: '\u2696', TRIM: '\u2702', ADD: '\u2795', BUY: '\u{1f4b0}' }
const lbl: React.CSSProperties = { fontSize: 8, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '0.3px' }

export default function Approvals() {
  const navigate = useNavigate()
  const { data: resp } = useApi<ApprovalData>('/api/v2/approvals/pending')
  const { data: histResp } = useApi<HistoryData>('/api/v2/approvals/history')
  const { data: statesResp } = useApi<{ total: number; by_status: Record<string, number>; items: QueueItem[] }>('/api/v2/approvals/states', 30000)
  const { data: tasksResp } = useApi<TasksData>('/api/v2/tasks', 30000)
  const pending = resp?.pending ?? []
  const allQueueItems = statesResp?.items ?? []
  const history = histResp?.decisions ?? []
  const johnTasks = (tasksResp?.tasks ?? []).filter(t => t.source === 'john_decision_queue')
  const [statusFilter, setStatusFilter] = useState<string>('pending')
  const [notes, setNotes] = useState<Record<number, string>>({})
  const [deciding, setDeciding] = useState<Record<number, string>>({})
  const [decided, setDecided] = useState<Set<number>>(new Set())
  const [taskDecided, setTaskDecided] = useState<Set<number>>(new Set())
  const [selectedDrawerTask, setSelectedDrawerTask] = useState<TaskItem | null>(null)
  const [selectedProposalId, setSelectedProposalId] = useState<number | null>(null)

  const handleDecision = useCallback(async (queueId: number, decision: 'approved' | 'rejected') => {
    const note = (notes[queueId] || '').trim()
    if (!note) { alert('A note/rationale is required for all decisions.'); return }
    setDeciding(s => ({ ...s, [queueId]: decision }))
    try {
      const r = await fetch('/api/v2/approvals/decision', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ queue_id: queueId, decision, note }) })
      const d = await r.json()
      if (d.ok) setDecided(s => new Set(s).add(queueId))
      else alert(d.error || 'Decision failed')
    } catch { alert('Network error') }
    setDeciding(s => { const n = { ...s }; delete n[queueId]; return n })
  }, [notes])

  const handleDrawerDecided = useCallback((taskId: number) => {
    setTaskDecided(s => new Set(s).add(taskId))
    setSelectedDrawerTask(null)
  }, [])

  // Use allQueueItems for non-pending filters, pending list for pending
  const filteredQueue = statusFilter === 'pending'
    ? pending.filter(item => !decided.has(item.id))
    : statusFilter === 'all'
      ? allQueueItems
      : allQueueItems.filter(item => item.status === statusFilter)

  // John tasks: filter by mapped status
  const statusMap: Record<string, string[]> = {
    pending: ['pending_john'], approved: ['decided_action'], rejected: ['rejected'],
    deferred: ['deferred'], resolved: ['closed', 'revisit_later'], all: [],
  }
  const activeJohnTasks = johnTasks.filter(t => {
    if (taskDecided.has(t.id)) return false
    if (statusFilter === 'all') return true
    const allowed = statusMap[statusFilter] || []
    return allowed.length === 0 || allowed.includes(t.status)
  })
  const activePending = filteredQueue

  return (
    <>
      <PageHeader title="Approvals & Tasks" subtitle={(() => {
        const total = activePending.length + activeJohnTasks.length
        if (statusFilter !== 'all' && statusFilter !== 'pending') {
          if (total === 0) return `No ${statusFilter} items`
          return `Showing ${total} ${statusFilter} item${total !== 1 ? 's' : ''}`
        }
        if (total === 0) return 'All caught up'
        const parts = []
        if (activeJohnTasks.length > 0) parts.push(`${activeJohnTasks.length} task${activeJohnTasks.length !== 1 ? 's' : ''}`)
        if (activePending.length > 0) parts.push(`${activePending.length} approval${activePending.length !== 1 ? 's' : ''}`)
        return `${parts.join(' + ')} awaiting your decision`
      })()} />

      <div style={{ padding: '6px 12px', marginBottom: 10, background: 'var(--amber-dim)', border: '1px solid var(--amber)', borderRadius: 8, fontSize: 10, color: 'var(--amber)' }}>
        Advisory only — execute all trades at your broker. Decision Tasks = items from pipeline runs requiring yes/no. Approvals = agent recommendations requiring your action. "Auto-review failed" = AI couldn't decide automatically, needs your judgment.
      </div>
      {/* Quick nav */}
      <div style={{ display: 'flex', gap: 6, marginBottom: 12, flexWrap: 'wrap' }}>
        <button onClick={() => navigate('/morning-brief')} style={linkStyle}>Morning Brief</button>
        <button onClick={() => navigate('/risk')} style={linkStyle}>Risk</button>
        <button onClick={() => navigate('/recovery')} style={linkStyle}>Recovery</button>
        <button onClick={() => navigate('/actions')} style={linkStyle}>Actions</button>
      </div>

      {/* Status filter tabs */}
      {statesResp && (
        <div style={{ display: 'flex', gap: 6, marginBottom: 12 }}>
          {([['pending', 'var(--amber)'], ['approved', 'var(--green)'], ['rejected', 'var(--red)'], ['deferred', 'var(--accent)'], ['resolved', 'var(--text3)']] as const).map(([st, color]) => {
            const cnt = statesResp.by_status[st] || 0
            if (cnt === 0 && st !== 'pending') return null
            const active = statusFilter === st
            return (
              <button key={st} onClick={() => setStatusFilter(active ? 'all' : st)} style={{ padding: '4px 12px', background: active ? `color-mix(in srgb, ${color} 15%, transparent)` : 'var(--bg3)', border: `1px solid ${active ? color : 'transparent'}`, borderRadius: 'var(--radius)', fontSize: 10, cursor: 'pointer', color: 'inherit' }}>
                <span style={{ color: color as string, fontWeight: 700 }}>{cnt}</span>
                <span style={{ color: active ? 'var(--text0)' : 'var(--text3)', marginLeft: 4 }}>{st}</span>
              </button>
            )
          })}
          <button onClick={() => setStatusFilter('all')} style={{ padding: '4px 12px', background: statusFilter === 'all' ? 'var(--bg-card)' : 'var(--bg3)', border: `1px solid ${statusFilter === 'all' ? 'var(--accent)' : 'transparent'}`, borderRadius: 'var(--radius)', fontSize: 10, cursor: 'pointer', color: 'inherit' }}>
            <span style={{ fontWeight: 700, color: 'var(--text0)' }}>{statesResp.total}</span>
            <span style={{ color: statusFilter === 'all' ? 'var(--text0)' : 'var(--text3)', marginLeft: 4 }}>all</span>
          </button>
        </div>
      )}

      {/* ═══ JOHN DECISION TASKS ═══ */}
      {(activeJohnTasks.length > 0 || statusFilter !== 'pending') && (
        <>
          <SectionHeader title="Decision Tasks" count={activeJohnTasks.length} />
          <Card>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              {activeJohnTasks.map(task => {
                const isUrgent = task.priority === 'urgent'
                const isFailed = task.category === 'failed_stop_review'
                const priColor = isUrgent ? 'var(--red)' : task.priority === 'high' ? 'var(--amber)' : 'var(--accent)'
                return (
                  <div key={task.id} onClick={() => setSelectedDrawerTask(task)} style={{
                    display: 'flex', gap: 8, padding: '8px 10px', alignItems: 'center', cursor: 'pointer',
                    borderBottom: '1px solid var(--border-subtle)', borderLeft: `3px solid ${priColor}`,
                    transition: 'background 80ms',
                  }}
                  onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = 'var(--bg3)' }}
                  onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = '' }}>
                    <span style={{ fontSize: 8, fontWeight: 700, padding: '1px 5px', borderRadius: 3, textTransform: 'uppercase', background: `color-mix(in srgb, ${priColor} 15%, transparent)`, color: priColor }}>{task.priority}</span>
                    {isFailed && <span style={{ fontSize: 7, fontWeight: 700, padding: '1px 4px', borderRadius: 2, background: 'var(--red-dim)', color: 'var(--red)' }}>FAILED AUTO</span>}
                    <span style={{ fontWeight: 800, color: 'var(--text0)', fontSize: 12 }}>{task.symbol}</span>
                    <span style={{ flex: 1, fontSize: 10, color: 'var(--text2)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{task.title}</span>
                    {task.due_by && <span style={{ fontSize: 9, color: priColor, fontWeight: 600 }}>{task.due_by}</span>}
                    <span style={{ fontSize: 9, color: priColor, fontWeight: 700 }}>Review →</span>
                  </div>
                )
              })}
            </div>
          </Card>
        </>
      )}

      {/* ═══ DECIDED TASKS ═══ */}
      {taskDecided.size > 0 && (
        <>
          <SectionHeader title="Just Decided" count={taskDecided.size} />
          <Card compact>
            {johnTasks.filter(t => taskDecided.has(t.id)).map(t => (
              <div key={t.id} style={{ display: 'flex', gap: 8, fontSize: 10, color: 'var(--text2)', padding: '4px 0', borderBottom: '1px solid var(--border-subtle)' }}>
                <span style={{ fontWeight: 700, color: 'var(--green)' }}>Decided</span>
                <span>{t.symbol}</span>
              </div>
            ))}
          </Card>
        </>
      )}

      {/* ═══ APPROVAL QUEUE ═══ */}
      {(activePending.length > 0 || statusFilter !== 'pending') && <SectionHeader title="Approval Queue" count={activePending.length} />}
      {activePending.length === 0 && activeJohnTasks.length === 0 ? (
        <Card><div style={{ color: 'var(--text3)', textAlign: 'center', padding: 40 }}>
          {statusFilter !== 'all' && statusFilter !== 'pending'
            ? `No ${statusFilter} items found.`
            : 'No pending items. Aegis will queue new recommendations after overnight analysis.'}
        </div></Card>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          {activePending.map(item => {
            const ev = item.evidence || {}
            const rc = item.risk_context
            const sym = item.rec_symbol || item.symbol || ''
            const icon = ACTION_ICON[item.action] || '\u{1f4cb}'
            const isStale = item.expires_at && new Date(item.expires_at) < new Date()
            const daysUntilExpiry = item.rec_expires ? Math.round((new Date(item.rec_expires).getTime() - Date.now()) / 86400000) : null

            return (
              <div key={item.id} style={{
                background: 'var(--bg2)', border: `1px solid ${item.urgency === 'urgent' ? 'var(--red)' : 'var(--border)'}`,
                borderRadius: 'var(--radius-lg)', padding: '16px 20px',
                borderLeft: `4px solid ${urgencyColor[item.urgency] || 'var(--border)'}`,
              }}>
                {/* Header */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
                  <span style={{ fontSize: 20 }}>{icon}</span>
                  <div style={{ flex: 1 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span style={{ fontSize: 9, fontWeight: 700, padding: '2px 8px', borderRadius: 3, textTransform: 'uppercase', background: urgencyBg[item.urgency], color: urgencyColor[item.urgency] }}>{item.urgency}</span>
                      <span style={{ fontSize: 15, fontWeight: 700, color: 'var(--text0)' }}>{item.action.replace(/_/g, ' ')}</span>
                      {sym && <span style={{ fontSize: 14, fontWeight: 700, color: 'var(--accent)' }}>{sym}</span>}
                      <AccountBadge account={(item as any).account} />
                      {isStale && <span style={{ fontSize: 8, fontWeight: 700, padding: '1px 6px', borderRadius: 3, background: 'var(--red-dim)', color: 'var(--red)' }}>STALE</span>}
                    </div>
                    <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 2 }}>
                      Queue #{item.id} | {item.rec_model === 'aegis' ? <span style={{ color: 'var(--accent)', fontWeight: 700 }}>Aegis</span> : `Source: ${item.rec_model || 'rule'}`} | {timeAgo(item.created_at)}
                      {daysUntilExpiry != null && ` | Expires in ${daysUntilExpiry}d`}
                    </div>
                    {(ev.escalation_summary || ev.trigger_rule) && (
                      <div style={{ fontSize: 9, color: 'var(--text2)', marginTop: 2 }}>
                        Escalated because: {ev.escalation_summary || ev.trigger_rule?.replace(/_/g, ' ')}
                      </div>
                    )}
                  </div>
                  <div style={{ textAlign: 'right' }}>
                    <div style={{ fontSize: 22, fontWeight: 800, color: item.confidence >= 0.9 ? 'var(--green)' : item.confidence >= 0.7 ? 'var(--amber)' : 'var(--text2)' }}>{(item.confidence * 100).toFixed(0)}%</div>
                    <div style={lbl}>Confidence</div>
                  </div>
                </div>

                {/* Decision summary */}
                {item.decision_summary && (
                  <div style={{ padding: '10px 12px', background: 'var(--bg1)', border: '1px solid var(--accent)', borderRadius: 'var(--radius)', marginBottom: 10, borderLeft: '3px solid var(--accent)' }}>
                    <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', marginBottom: 4 }}>{item.decision_summary.what}</div>
                    <div style={{ fontSize: 10, color: 'var(--text1)', marginBottom: 4 }}>{item.decision_summary.why}</div>
                    {item.decision_summary.risk !== 'No specific risk detail available' && (
                      <div style={{ fontSize: 10, color: 'var(--amber)', marginBottom: 4 }}>Risk: {item.decision_summary.risk}</div>
                    )}
                    {item.decision_summary.exposure && (
                      <div style={{ fontSize: 10, color: 'var(--text1)', marginBottom: 4 }}>{item.decision_summary.exposure}</div>
                    )}
                    {item.decision_summary.next_action && (
                      <div style={{ fontSize: 10, color: 'var(--green)', marginBottom: 4, fontWeight: 600 }}>Next: {item.decision_summary.next_action}</div>
                    )}
                    <div style={{ fontSize: 9, color: 'var(--text3)' }}>{item.decision_summary.followup}</div>
                  </div>
                )}

                {/* What is being recommended */}
                <div style={{ padding: '10px 12px', background: 'var(--bg3)', borderRadius: 'var(--radius)', marginBottom: 10 }}>
                  <div style={{ ...lbl, marginBottom: 4, fontWeight: 600 }}>Recommendation</div>
                  <div style={{ fontSize: 12, color: 'var(--text0)', lineHeight: 1.5 }}>
                    {item.rec_rationale || item.rationale || 'No detailed rationale available.'}
                  </div>
                </div>

                {/* Evidence pack */}
                {(ev.severity || ev.trigger_rule || ev.escalation_summary || ev.yahoo_analyst || ev.article_context) && (
                  <div style={{ padding: '10px 12px', background: 'var(--bg1)', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius)', marginBottom: 10 }}>
                    <div style={{ ...lbl, marginBottom: 6, fontWeight: 600 }}>Evidence</div>
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8, fontSize: 10 }}>
                      {ev.severity != null && (
                        <div><div style={lbl}>Severity</div><div style={{ fontWeight: 700, color: ev.severity >= 2 ? 'var(--red)' : 'var(--amber)' }}>{ev.severity}</div></div>
                      )}
                      {ev.trigger_rule && (
                        <div><div style={lbl}>Trigger Rule</div><div style={{ color: 'var(--text1)' }}>{ev.trigger_rule.replace(/_/g, ' ')}</div></div>
                      )}
                      {ev.escalation_summary && (
                        <div style={{ gridColumn: ev.severity != null && ev.trigger_rule ? '3' : 'auto' }}><div style={lbl}>Summary</div><div style={{ color: 'var(--text1)' }}>{ev.escalation_summary}</div></div>
                      )}
                    </div>
                    {ev.yahoo_analyst && (
                      <div style={{ marginTop: 8, padding: '6px 8px', background: 'var(--bg3)', borderRadius: 'var(--radius)', fontSize: 10 }}>
                        <div style={lbl}>Analyst Consensus</div>
                        <div style={{ display: 'flex', gap: 12, marginTop: 3 }}>
                          <span>Target: <strong style={{ color: 'var(--green)' }}>${ev.yahoo_analyst.target_mean_price}</strong></span>
                          <span>Current: <strong>${ev.yahoo_analyst.current_price}</strong></span>
                          <span>Rating: <strong style={{ color: 'var(--green)' }}>{ev.yahoo_analyst.recommendation_key?.replace(/_/g, ' ')}</strong></span>
                          <span>Analysts: <strong>{ev.yahoo_analyst.number_of_analyst_opinions}</strong></span>
                        </div>
                      </div>
                    )}
                    {ev.article_context && ev.article_context.article_count_7d != null && (
                      <div style={{ marginTop: 6, fontSize: 9, color: 'var(--text2)' }}>
                        {ev.article_context.article_count_7d} articles in 7d ({ev.article_context.analyst_article_count || 0} analyst)
                        {ev.article_context.categories && ` — ${ev.article_context.categories.join(', ')}`}
                      </div>
                    )}
                  </div>
                )}

                {/* Risk context for STOP_REVIEW */}
                {item.action === 'STOP_REVIEW' && rc && (
                  <div style={{ padding: '10px 12px', background: 'var(--bg1)', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius)', marginBottom: 10 }}>
                    <div style={{ ...lbl, marginBottom: 6, fontWeight: 600 }}>Live Risk Context</div>
                    {(rc.triggered?.length ?? 0) > 0 ? (
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                        {(rc.triggered || []).map((p, i) => (
                          <div key={i} style={{ padding: '8px 10px', background: 'var(--red-dim)', borderRadius: 'var(--radius)', borderLeft: '3px solid var(--red)' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                              <span style={{ fontSize: 13, fontWeight: 800, color: 'var(--red)' }}>{p.symbol}</span>
                              {p.name && <span style={{ fontSize: 9, color: 'var(--text2)' }}>{p.name}</span>}
                              <span style={{ marginLeft: 'auto', fontSize: 8, fontWeight: 700, padding: '1px 6px', borderRadius: 3, background: 'var(--red)', color: '#fff' }}>TRIGGERED</span>
                            </div>
                            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 6, fontSize: 10 }}>
                              <div><div style={lbl}>Current Price</div><div style={{ fontWeight: 700, color: 'var(--text0)' }}>{p.current_price ? fmt$(p.current_price, 2) : 'N/A'}</div></div>
                              <div><div style={lbl}>Stop Price</div><div style={{ fontWeight: 700, color: 'var(--red)' }}>{p.stop_price ? fmt$(p.stop_price, 2) : '—'}</div></div>
                              <div><div style={lbl}>Distance</div><div style={{ fontWeight: 700, color: p.distance_pct != null && p.distance_pct < 0 ? 'var(--red)' : 'var(--amber)' }}>{p.distance_pct != null ? `${p.distance_pct.toFixed(1)}%` : '—'}</div></div>
                              <div><div style={lbl}>Shares Held</div><div style={{ fontWeight: 700 }}>{p.shares ? p.shares.toFixed(1) : '—'}</div></div>
                            </div>
                            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 6, fontSize: 10, marginTop: 6 }}>
                              <div><div style={lbl}>Total Position</div><div style={{ fontWeight: 700 }}>{p.total_position_value ? fmt$(p.total_position_value) : fmt$(p.market_value)}</div></div>
                              <div><div style={lbl}>P&L If Stopped Out</div><div style={{ fontWeight: 700, color: p.pnl_if_stopped != null && p.pnl_if_stopped > 0 ? 'var(--green)' : 'var(--red)' }}>{p.pnl_if_stopped != null ? `${p.pnl_if_stopped >= 0 ? '+' : ''}${fmt$(p.pnl_if_stopped)}` : '—'}</div></div>
                              <div><div style={lbl}>Value At Stop</div><div style={{ fontWeight: 700, color: 'var(--text2)' }}>{p.stop_price && p.shares ? fmt$(p.stop_price * p.shares) : '—'}</div></div>
                            </div>
                            {(p.rsi != null || p.sma200_pct != null || p.beta != null) && (
                              <div style={{ display: 'flex', gap: 12, marginTop: 6, fontSize: 9, color: 'var(--text2)' }}>
                                {p.rsi != null && <span>RSI: <strong style={{ color: p.rsi > 70 ? 'var(--red)' : p.rsi < 30 ? 'var(--green)' : 'var(--text1)' }}>{p.rsi.toFixed(0)}</strong></span>}
                                {p.sma200_pct != null && <span>SMA200: <strong style={{ color: p.sma200_pct > 0 ? 'var(--green)' : 'var(--red)' }}>{p.sma200_pct > 0 ? '+' : ''}{p.sma200_pct.toFixed(1)}%</strong></span>}
                                {p.beta != null && <span>Beta: <strong>{p.beta.toFixed(2)}</strong></span>}
                              </div>
                            )}
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div style={{ fontSize: 10, color: 'var(--green)', padding: '4px 0' }}>No stops currently triggered. Prior trigger may have resolved.</div>
                    )}
                    {(rc.danger?.length ?? 0) > 0 && (
                      <div style={{ marginTop: 8 }}>
                        <div style={{ ...lbl, marginBottom: 4, color: 'var(--amber)' }}>Danger Zone ({rc.danger?.length})</div>
                        {(rc.danger || []).map((p, i) => (
                          <div key={i} style={{ display: 'flex', gap: 10, padding: '4px 8px', background: 'var(--amber-dim)', borderRadius: 'var(--radius)', fontSize: 10, marginBottom: 3 }}>
                            <strong style={{ color: 'var(--amber)', width: 40 }}>{p.symbol}</strong>
                            <span>{p.current_price ? fmt$(p.current_price, 2) : '—'}</span>
                            <span>stop {p.stop_price ? fmt$(p.stop_price, 2) : '—'}</span>
                            <span>{p.distance_pct != null ? `${p.distance_pct.toFixed(1)}%` : '—'}</span>
                            <span>{p.shares ? `${p.shares.toFixed(1)} sh` : ''}</span>
                            {p.pnl_if_stopped != null && <span style={{ color: p.pnl_if_stopped >= 0 ? 'var(--green)' : 'var(--red)' }}>P&L: {p.pnl_if_stopped >= 0 ? '+' : ''}{fmt$(p.pnl_if_stopped)}</span>}
                          </div>
                        ))}
                      </div>
                    )}
                    {Array.isArray(rc.warning) && rc.warning.length > 0 && (
                      <div style={{ marginTop: 6 }}>
                        <div style={{ ...lbl, marginBottom: 4, color: 'var(--text3)' }}>Warning ({rc.warning.length})</div>
                        {rc.warning.map((p: any, i: number) => (
                          <div key={i} style={{ fontSize: 9, color: 'var(--text2)', padding: '2px 0' }}>{p.symbol} — {p.current_price ? fmt$(p.current_price, 2) : '—'} / stop {p.stop_price ? fmt$(p.stop_price, 2) : '—'}</div>
                        ))}
                      </div>
                    )}
                    <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 6 }}>{rc.total_with_stops || 0} positions with stops / {rc.total_positions || 0} total monitored</div>
                  </div>
                )}

                {/* Risk context for ALLOCATION_REVIEW */}
                {item.action === 'ALLOCATION_REVIEW' && rc?.position && (
                  <div style={{ padding: '10px 12px', background: 'var(--bg1)', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius)', marginBottom: 10 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                      <div style={{ ...lbl, fontWeight: 600 }}>Position Context</div>
                      <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--accent)' }}>{sym}</span>
                      {rc.position.name && <span style={{ fontSize: 9, color: 'var(--text2)' }}>{rc.position.name}</span>}
                    </div>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 8, fontSize: 10 }}>
                      <div><div style={lbl}>Current Price</div><div style={{ fontWeight: 700 }}>{rc.position.current_price ? fmt$(rc.position.current_price, 2) : '—'}</div></div>
                      <div><div style={lbl}>Market Value</div><div style={{ fontWeight: 700 }}>{fmt$(rc.position.market_value)}</div></div>
                      <div><div style={lbl}>Stop</div><div>{rc.position.stop_price ? fmt$(rc.position.stop_price, 2) : 'None'}</div></div>
                      <div><div style={lbl}>Distance</div><div>{rc.position.distance_pct != null ? `${rc.position.distance_pct.toFixed(1)}%` : '—'}</div></div>
                      <div><div style={lbl}>Max Loss</div><div style={{ color: 'var(--red)' }}>{fmt$(rc.position.max_loss)}</div></div>
                    </div>
                    {(rc.position.rsi != null || rc.position.sma200_pct != null || rc.position.beta != null) && (
                      <div style={{ display: 'flex', gap: 12, marginTop: 6, fontSize: 9, color: 'var(--text2)' }}>
                        {rc.position.rsi != null && <span>RSI: <strong style={{ color: rc.position.rsi > 70 ? 'var(--red)' : rc.position.rsi < 30 ? 'var(--green)' : 'var(--text1)' }}>{rc.position.rsi.toFixed(0)}</strong></span>}
                        {rc.position.sma200_pct != null && <span>SMA200: <strong style={{ color: rc.position.sma200_pct > 0 ? 'var(--green)' : 'var(--red)' }}>{rc.position.sma200_pct > 0 ? '+' : ''}{rc.position.sma200_pct.toFixed(1)}%</strong></span>}
                        {rc.position.beta != null && <span>Beta: <strong>{rc.position.beta.toFixed(2)}</strong></span>}
                      </div>
                    )}
                  </div>
                )}

                {/* Impact comparison */}
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginBottom: 10 }}>
                  <div style={{ padding: '8px 10px', background: 'var(--green-dim)', border: '1px solid var(--green)', borderRadius: 'var(--radius)', fontSize: 10 }}>
                    <div style={{ fontWeight: 600, color: 'var(--green)', marginBottom: 3 }}>If Approved</div>
                    <div style={{ color: 'var(--text1)' }}>
                      {item.action === 'STOP_REVIEW' ? 'Stop levels validated. Queue item moves to reviewed. Risk acknowledged.' :
                       item.action === 'ALLOCATION_REVIEW' ? `${sym} concentration accepted at current level. Monitoring continues.` :
                       'Action proceeds as recommended.'}
                    </div>
                  </div>
                  <div style={{ padding: '8px 10px', background: 'var(--red-dim)', border: '1px solid var(--red)', borderRadius: 'var(--radius)', fontSize: 10 }}>
                    <div style={{ fontWeight: 600, color: 'var(--red)', marginBottom: 3 }}>If Rejected</div>
                    <div style={{ color: 'var(--text1)' }}>
                      {item.action === 'STOP_REVIEW' ? `Risk remains unresolved. ${(rc?.triggered?.length ?? 0) > 0 ? `${rc!.triggered![0].symbol} stays below stop.` : ''} Will re-escalate on next pipeline run.` :
                       item.action === 'ALLOCATION_REVIEW' ? `${sym} concentration remains elevated. No trim action taken. Risk persists.` :
                       'Recommendation dismissed. May re-escalate if conditions persist.'}
                    </div>
                  </div>
                </div>
                {/* Related risk */}
                {(rc?.danger?.length ?? 0) + (rc?.warning?.length ?? 0) > 0 && (
                  <div style={{ fontSize: 9, color: 'var(--text3)', marginBottom: 10 }}>
                    Related risk: {[...(rc?.danger || []).map((d: any) => d.symbol), ...(Array.isArray(rc?.warning) ? rc.warning.slice(0, 2).map((w: any) => w.symbol) : [])].filter(Boolean).join(', ')} also in danger/warning tier
                  </div>
                )}

                {/* Supporting links */}
                <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 10 }}>
                  <span style={{ fontSize: 9, color: 'var(--text3)', alignSelf: 'center' }}>Review in:</span>
                  <button onClick={() => navigate(`/risk${sym ? `?symbol=${sym}` : ''}`)} style={linkStyle}>Risk</button>
                  <button onClick={() => navigate(`/portfolio${sym ? `?symbol=${sym}` : ''}`)} style={linkStyle}>Holdings</button>
                  {sym && <button onClick={() => navigate(`/research?symbol=${sym}`)} style={linkStyle}>Research</button>}
                  <button onClick={() => navigate('/alerts')} style={linkStyle}>Alerts</button>
                  <button onClick={() => navigate('/notifications')} style={linkStyle}>Notifications</button>
                  <button onClick={() => navigate('/recovery')} style={linkStyle}>Recovery Watch</button>
                  {item.action === 'ALLOCATION_REVIEW' && <button onClick={() => navigate('/rebalance')} style={linkStyle}>Rebalance</button>}
                  {sym && <a href={`https://finviz.com/quote.ashx?t=${sym}`} target="_blank" rel="noreferrer" style={{ ...linkStyle, textDecoration: 'none' }}>Finviz</a>}
                  <button onClick={() => setSelectedProposalId(item.id)} style={{ ...linkStyle, border: '1px solid var(--accent)', color: 'var(--accent)', fontWeight: 700 }}>Full Context</button>
                </div>

                {/* Decision controls */}
                <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end', padding: '10px 0 0', borderTop: '1px solid var(--border-subtle)' }}>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 9, color: 'var(--text3)', marginBottom: 3 }}>Your rationale (required)</div>
                    <textarea value={notes[item.id] || ''} onChange={e => setNotes(s => ({ ...s, [item.id]: e.target.value }))}
                      placeholder="What did you verify? Why approve or reject?"
                      rows={2} style={{ width: '100%', padding: '6px 8px', fontSize: 10, background: 'var(--bg3)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', color: 'var(--text1)', fontFamily: 'var(--mono)', resize: 'vertical', outline: 'none' }} />
                  </div>
                  <button onClick={() => handleDecision(item.id, 'approved')} disabled={!!deciding[item.id]}
                    style={{ padding: '6px 14px', fontSize: 10, fontWeight: 700, border: '1px solid var(--green)', borderRadius: 'var(--radius)', background: 'var(--green-dim)', color: 'var(--green)', cursor: 'pointer', fontFamily: 'var(--mono)', opacity: deciding[item.id] ? 0.5 : 1 }}>
                    {deciding[item.id] === 'approved' ? 'Saving...' : 'Approve'}
                  </button>
                  <button onClick={() => handleDecision(item.id, 'rejected')} disabled={!!deciding[item.id]}
                    style={{ padding: '6px 14px', fontSize: 10, fontWeight: 700, border: '1px solid var(--red)', borderRadius: 'var(--radius)', background: 'var(--red-dim)', color: 'var(--red)', cursor: 'pointer', fontFamily: 'var(--mono)', opacity: deciding[item.id] ? 0.5 : 1 }}>
                    {deciding[item.id] === 'rejected' ? 'Saving...' : 'Reject'}
                  </button>
                </div>
              </div>
            )
          })}
        </div>
      )}

      {/* Just decided */}
      {decided.size > 0 && (
        <>
          <SectionHeader title="Just Decided" count={decided.size} />
          <Card compact>
            {pending.filter(item => decided.has(item.id)).map(item => (
              <div key={item.id} style={{ display: 'flex', gap: 8, fontSize: 10, color: 'var(--text2)', padding: '4px 0', borderBottom: '1px solid var(--border-subtle)' }}>
                <span style={{ fontWeight: 700, color: 'var(--green)' }}>Decided</span>
                <span>{item.action.replace(/_/g, ' ')}</span>
                {(item.rec_symbol || item.symbol) && <span style={{ color: 'var(--accent)' }}>{item.rec_symbol || item.symbol}</span>}
                <span style={{ color: 'var(--text3)' }}>— {(notes[item.id] || '').slice(0, 50)}</span>
              </div>
            ))}
          </Card>
        </>
      )}

      {/* Decision history */}
      <SectionHeader title="Decision History" count={history.length} />
      {history.length === 0 ? (
        <Card><div style={{ color: 'var(--text3)', fontSize: 11, padding: 16, textAlign: 'center' }}>No decisions yet. Approve or reject items above to build history.</div></Card>
      ) : (
        <Card>
          {history.map(d => (
            <div key={d.id} style={{ display: 'flex', gap: 8, padding: '6px 0', borderBottom: '1px solid var(--border-subtle)', fontSize: 10, alignItems: 'center' }}>
              <span style={{ fontSize: 8, fontWeight: 700, padding: '1px 6px', borderRadius: 3, textTransform: 'uppercase', background: d.decision === 'approved' ? 'var(--green-dim)' : 'var(--red-dim)', color: d.decision === 'approved' ? 'var(--green)' : 'var(--red)' }}>{d.decision}</span>
              <span style={{ fontWeight: 600, color: 'var(--text0)' }}>{d.action?.replace(/_/g, ' ') || '—'}</span>
              {d.symbol && <span style={{ color: 'var(--accent)' }}>{d.symbol}</span>}
              <span style={{ flex: 1, color: 'var(--text2)' }}>{d.notes || d.decision_reason || '—'}</span>
              <span style={{ color: 'var(--text3)' }}>{d.decided_by}</span>
              <span style={{ color: 'var(--text3)' }}>{d.decided_at ? timeAgo(d.decided_at) : '—'}</span>
            </div>
          ))}
        </Card>
      )}

      {/* Task detail drawer */}
      <TaskDetailDrawer task={selectedDrawerTask} onClose={() => setSelectedDrawerTask(null)} onDecided={handleDrawerDecided} />
      <ProposalDetailDrawer proposalId={selectedProposalId} onClose={() => setSelectedProposalId(null)} />
    </>
  )
}

const linkStyle: React.CSSProperties = { fontSize: 9, padding: '3px 8px', border: '1px solid var(--border)', borderRadius: 'var(--radius)', background: 'var(--bg3)', color: 'var(--accent)', cursor: 'pointer', fontFamily: 'var(--mono)' }
