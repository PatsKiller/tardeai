import { useState, useMemo, useEffect, useCallback, Fragment } from 'react'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import { useApi } from '../hooks/useApi'
import { StatusBadge } from '../components/StatusBadge'
import { SeverityBadge } from '../components/SeverityBadge'
import { AgentChip } from '../components/AgentChip'
import { ActionButton } from '../components/ActionButton'
import { StateCard } from '../components/StateCard'
import { RACIMatrix } from '../components/RACIMatrix'

/* ── helpers ── */
function timeAgo(ts: string | null | undefined): string {
  if (!ts) return 'never'
  const d = new Date(ts)
  if (isNaN(d.getTime())) return 'never'
  const s = Math.floor((Date.now() - d.getTime()) / 1000)
  if (s < 60) return 'now'
  if (s < 3600) return `${Math.floor(s / 60)}m ago`
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`
  return `${Math.floor(s / 86400)}d ago`
}

function fmtHours(h: number | null | undefined): string {
  if (h == null) return '--'
  if (h < 1) return `${Math.round(h * 60)}m`
  if (h < 24) return `${h.toFixed(1)}h`
  return `${(h / 24).toFixed(1)}d`
}

function accuracyColor(acc: number): string {
  if (acc >= 70) return 'var(--green)'
  if (acc >= 50) return 'var(--amber)'
  return 'var(--red)'
}

function healthColor(h: string): string {
  if (h === 'fresh') return 'var(--green)'
  if (h === 'stale') return 'var(--red)'
  return 'var(--text3)'
}

function inferTimeline(m: any): { step: string; detail: string }[] {
  const steps: { step: string; detail: string }[] = []
  if (m.primary_owner) {
    steps.push({ step: 'Detected', detail: `Assigned to ${m.primary_owner.replace(/_/g, ' ')}` })
  }
  if ((m.agents || []).length > 1) {
    const others = (m.agents as string[]).filter((a: string) => a !== m.primary_owner)
    steps.push({ step: 'Collaboration', detail: `Involved: ${others.map((a: string) => a.replace(/_/g, ' ')).join(', ')}` })
  }
  if (m.primary_blocker) {
    steps.push({ step: 'Blocked', detail: m.primary_blocker })
  }
  if (m.status === 'ready') {
    steps.push({ step: 'Ready', detail: 'Awaiting operator review' })
  } else if (m.status === 'completed') {
    steps.push({ step: 'Completed', detail: 'Mission resolved' })
  } else if (m.status === 'stale') {
    steps.push({ step: 'Stale', detail: 'No recent activity' })
  } else if (m.status === 'running' || m.status === 'waiting') {
    steps.push({ step: 'In Progress', detail: `Status: ${m.status}` })
  }
  return steps
}

type StatusFilter = 'all' | 'ready' | 'blocked' | 'waiting' | 'stale' | 'running' | 'completed'
type TaskTypeFilter = 'all' | 'risk' | 'paper_proposal' | 'research_gap' | 'system_health' | 'content_hygiene' | 'alert' | 'morning_brief' | 'ticker'
type TimeFilter = 'all' | '24h' | '7d' | '30d'
type ViewTab = 'missions' | 'flow' | 'raci' | 'quality'

const FILTER_CHIPS: { key: StatusFilter; label: string }[] = [
  { key: 'all', label: 'All' },
  { key: 'ready', label: 'Ready' },
  { key: 'blocked', label: 'Blocked' },
  { key: 'waiting', label: 'Waiting' },
  { key: 'stale', label: 'Stale' },
  { key: 'running', label: 'Running' },
  { key: 'completed', label: 'Completed' },
]

const TASK_TYPE_CHIPS: { key: TaskTypeFilter; label: string }[] = [
  { key: 'all', label: 'All Types' },
  { key: 'risk', label: 'Risk' },
  { key: 'paper_proposal', label: 'Proposals' },
  { key: 'research_gap', label: 'Research' },
  { key: 'system_health', label: 'System' },
  { key: 'alert', label: 'Alerts' },
  { key: 'ticker', label: 'Ticker' },
]

const TIME_CHIPS: { key: TimeFilter; label: string; hours: number }[] = [
  { key: 'all', label: 'All Time', hours: Infinity },
  { key: '24h', label: '24h', hours: 24 },
  { key: '7d', label: '7 Days', hours: 168 },
  { key: '30d', label: '30 Days', hours: 720 },
]

const KNOWN_AGENTS = ['maria', 'steph', 'aegis', 'alex', 'risk_agent', 'tax_agent', 'iris']

const TAB_ITEMS: { key: ViewTab; label: string }[] = [
  { key: 'missions', label: 'Missions' },
  { key: 'flow', label: 'Collaboration Flow' },
  { key: 'raci', label: 'RACI Map' },
  { key: 'quality', label: 'Outcome Quality' },
]

/* ── Flow grouping helper ── */
interface FlowEdge {
  from_agent: string
  to_agent: string
  cnt: number
  escalated: number
  latest: string | null
  completed: number
  open: number
}

function groupFlows(network: any[]): { agentToAgent: FlowEdge[]; systemToAgent: FlowEdge[]; agentToOperator: FlowEdge[] } {
  const systemNames = ['synthesis', 'auto_research', 'event_routing', 'system']
  const operatorNames = ['human_review', 'operator', 'user', 'john']
  const edges: FlowEdge[] = (network || []).map((e: any) => ({
    from_agent: e.from_agent || 'unknown',
    to_agent: e.to_agent || 'unknown',
    cnt: e.cnt || 0,
    escalated: e.escalated || 0,
    latest: e.latest || null,
    completed: Math.max(0, (e.cnt || 0) - (e.open || 0)),
    open: e.open || 0,
  }))

  return {
    agentToAgent: edges.filter(e =>
      !systemNames.includes(e.from_agent) && !operatorNames.includes(e.to_agent) && !operatorNames.includes(e.from_agent)
    ),
    systemToAgent: edges.filter(e => systemNames.includes(e.from_agent)),
    agentToOperator: edges.filter(e => operatorNames.includes(e.to_agent) || operatorNames.includes(e.from_agent)),
  }
}

export default function AgentCollaboration() {
  const [rk, setRk] = useState(0)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [filter, setFilter] = useState<StatusFilter>('all')
  const [agentFilter, setAgentFilter] = useState<string | null>(null)
  const [taskTypeFilter, setTaskTypeFilter] = useState<TaskTypeFilter>('all')
  const [timeFilter, setTimeFilter] = useState<TimeFilter>('all')
  const [viewTab, setViewTab] = useState<ViewTab>('missions')

  // RACI state for selected mission's owner
  const [raciData, setRaciData] = useState<any>(null)
  const [raciLoading, setRaciLoading] = useState(false)

  // RACI Map state (all agents)
  const [raciMapData, setRaciMapData] = useState<Record<string, any>>({})
  const [raciMapLoading, setRaciMapLoading] = useState(false)
  const [raciCollapsed, setRaciCollapsed] = useState<Record<string, boolean>>({})

  // Flow tab: expanded agent pairs for handoff drilldown
  const [expandedFlows, setExpandedFlows] = useState<Set<string>>(new Set())

  // Thread expand/collapse in mission inspector
  const [expandedThreads, setExpandedThreads] = useState<Set<number>>(new Set())

  const toggleThread = (idx: number) => {
    setExpandedThreads(prev => {
      const next = new Set(prev)
      if (next.has(idx)) next.delete(idx)
      else next.add(idx)
      return next
    })
  }

  // Quality tab: show/hide fresh products
  const [showFreshProducts, setShowFreshProducts] = useState(false)

  const { data: collab } = useApi<any>(`/api/v2/agent-collaboration?_r=${rk}`, 60000)

  const summary = collab?.summary || {}
  const johnActions: any[] = collab?.john_next_actions || []
  const allMissions: any[] = collab?.mission_groups || []
  const agentNetwork: any[] = collab?.agent_network || []
  const handoffDetails: any[] = collab?.handoff_details || []
  const agentQuality: any[] = collab?.agent_quality || []
  const staleProducts: any[] = collab?.stale_products || []
  const raciHealth: any[] = collab?.raci_health || []
  const scoring = collab?.scoring || {}

  // Derived waiting count
  const waitingCount = Math.max(0,
    (summary.active_missions ?? 0)
    - (summary.ready_for_operator ?? 0)
    - (summary.blocked_missions ?? 0)
    - (summary.stale_missions ?? 0)
  )

  // Filter missions
  const missions = useMemo(() => {
    let result = allMissions
    if (filter !== 'all') {
      if (filter === 'waiting') {
        result = result.filter(m => m.status !== 'ready' && m.status !== 'blocked' && m.status !== 'stale' && m.status !== 'completed' && m.status !== 'running')
      } else {
        result = result.filter(m => m.status === filter)
      }
    }
    if (agentFilter) {
      result = result.filter(m =>
        (m.agents || []).includes(agentFilter) || m.primary_owner === agentFilter
      )
    }
    if (taskTypeFilter !== 'all') {
      result = result.filter(m => m.mission_type === taskTypeFilter)
    }
    if (timeFilter !== 'all') {
      const maxHours = TIME_CHIPS.find(t => t.key === timeFilter)?.hours || Infinity
      const cutoff = Date.now() - maxHours * 3600000
      result = result.filter(m => {
        if (!m.updated_at) return true
        return new Date(m.updated_at).getTime() >= cutoff
      })
    }
    return result
  }, [allMissions, filter, agentFilter, taskTypeFilter, timeFilter])

  // Selected mission
  const selected = useMemo(() => {
    if (selectedId) return allMissions.find(m => m.mission_id === selectedId) || null
    return missions[0] || null
  }, [selectedId, allMissions, missions])

  // Auto-select first mission
  useEffect(() => {
    if (!selectedId && missions.length > 0) {
      setSelectedId(missions[0].mission_id)
    }
  }, [missions, selectedId])

  // Reset expanded threads when mission changes
  useEffect(() => {
    setExpandedThreads(new Set())
  }, [selectedId])

  // Fetch RACI for selected mission's owner
  useEffect(() => {
    if (!selected?.primary_owner) { setRaciData(null); return }
    const agent = selected.primary_owner
    setRaciLoading(true)
    fetch(`/api/v2/agent-detail/raci?agent=${encodeURIComponent(agent)}`)
      .then(r => r.ok ? r.json() : null)
      .then(d => { setRaciData(d); setRaciLoading(false) })
      .catch(() => { setRaciData(null); setRaciLoading(false) })
  }, [selected?.primary_owner, selected?.mission_id])

  // Fetch RACI Map for all known agents
  const loadRaciMap = useCallback(() => {
    if (raciMapLoading) return
    setRaciMapLoading(true)
    Promise.all(
      KNOWN_AGENTS.map(agent =>
        fetch(`/api/v2/agent-detail/raci?agent=${encodeURIComponent(agent)}`)
          .then(r => r.ok ? r.json() : null)
          .then(d => ({ agent, data: d }))
          .catch(() => ({ agent, data: null }))
      )
    ).then(results => {
      const map: Record<string, any> = {}
      results.forEach(r => { if (r.data) map[r.agent] = r.data })
      setRaciMapData(map)
      setRaciMapLoading(false)
    })
  }, [raciMapLoading])

  useEffect(() => {
    if (viewTab === 'raci' && Object.keys(raciMapData).length === 0) {
      loadRaciMap()
    }
  }, [viewTab]) // eslint-disable-line react-hooks/exhaustive-deps

  const trustState = (summary.system_trust_state || 'unknown').toUpperCase()

  const handleAgentClick = (agent: string) => {
    if (agentFilter === agent) {
      setAgentFilter(null)
    } else {
      setAgentFilter(agent)
      setSelectedId(null)
      setViewTab('missions')
    }
  }

  const handleStatusClick = (status: StatusFilter) => {
    setFilter(status)
    setSelectedId(null)
    setViewTab('missions')
  }

  // Flow data
  const flowGroups = useMemo(() => groupFlows(agentNetwork), [agentNetwork])

  // Toggle flow drilldown
  const toggleFlowExpand = (key: string) => {
    setExpandedFlows(prev => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  // Get handoff details for a specific agent pair
  const getHandoffsForPair = (from: string, to: string) => {
    return handoffDetails.filter(h => h.from_agent === from && h.to_agent === to)
  }

  // Check if a flow edge is stale (>48h since latest)
  const isFlowStale = (latest: string | null): boolean => {
    if (!latest) return true
    const d = new Date(latest)
    if (isNaN(d.getTime())) return true
    return (Date.now() - d.getTime()) > 48 * 3600000
  }

  // Render a single flow edge row with drilldown capability
  const renderFlowEdge = (e: FlowEdge, i: number, showFromAsChip: boolean, showToAsChip: boolean) => {
    const flowKey = `${e.from_agent}→${e.to_agent}`
    const isExpanded = expandedFlows.has(flowKey)
    const stale = isFlowStale(e.latest)
    const pairHandoffs = getHandoffsForPair(e.from_agent, e.to_agent)

    return (
      <div key={i}>
        <div style={{
          padding: '8px 12px', borderRadius: 'var(--radius)',
          background: e.open > 0 ? 'rgba(245,158,11,0.06)' : 'var(--bg1)',
          border: `1px solid ${e.open > 0 ? 'rgba(245,158,11,.2)' : stale ? 'rgba(245,158,11,.15)' : 'var(--border)'}`,
          display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap',
          cursor: 'pointer',
        }}
        onClick={() => toggleFlowExpand(flowKey)}>
          {showFromAsChip ? (
            <span onClick={(ev) => { ev.stopPropagation(); handleAgentClick(e.from_agent) }} style={{ cursor: 'pointer' }}>
              <AgentChip name={e.from_agent} />
            </span>
          ) : (
            <span style={{ fontSize: 10, fontWeight: 600, color: 'var(--text2)', minWidth: 80 }}>{e.from_agent.replace(/_/g, ' ')}</span>
          )}
          <span style={{ fontSize: 10, color: 'var(--text3)' }}>-&gt;</span>
          {showToAsChip ? (
            <span onClick={(ev) => { ev.stopPropagation(); handleAgentClick(e.to_agent) }} style={{ cursor: 'pointer' }}>
              <AgentChip name={e.to_agent} />
            </span>
          ) : (
            <span style={{ fontSize: 10, fontWeight: 600, color: 'var(--text2)' }}>{e.to_agent.replace(/_/g, ' ')}</span>
          )}
          <span style={{ fontSize: 10, color: 'var(--text2)', marginLeft: 'auto' }}>Total: {e.cnt}</span>
          <span style={{ fontSize: 10, color: 'var(--green)' }}>Done: {e.completed}</span>
          {e.open > 0 && <span style={{ fontSize: 10, color: 'var(--amber)', fontWeight: 700 }}>Open: {e.open}</span>}
          {e.escalated > 0 && <span style={{ fontSize: 10, color: 'var(--red)', fontWeight: 700 }}>Esc: {e.escalated}</span>}
          {stale && (
            <span style={{ fontSize: 9, fontWeight: 700, color: 'var(--amber)', background: 'rgba(245,158,11,0.1)', padding: '1px 6px', borderRadius: 3 }}>
              STALE
            </span>
          )}
          <span style={{ fontSize: 9, color: 'var(--text3)' }}>Last: {timeAgo(e.latest)}</span>
          <span style={{ fontSize: 10, color: 'var(--text3)' }}>{isExpanded ? '-' : '+'}</span>
        </div>

        {/* Drilldown: individual handoffs for this pair */}
        {isExpanded && (
          <div style={{ marginLeft: 20, marginTop: 4, marginBottom: 8, display: 'flex', flexDirection: 'column', gap: 2 }}>
            {pairHandoffs.length === 0 ? (
              <div style={{ fontSize: 10, color: 'var(--text3)', padding: '6px 10px', background: 'var(--bg2)', borderRadius: 4 }}>
                No detailed handoff records available for this pair.
              </div>
            ) : (
              pairHandoffs.map((h: any) => (
                <div key={h.id} style={{
                  padding: '6px 10px', borderRadius: 4, background: 'var(--bg2)',
                  borderLeft: `3px solid ${h.status === 'completed' ? 'var(--green)' : h.escalated ? 'var(--red)' : 'var(--amber)'}`,
                  display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap',
                }}>
                  <StatusBadge status={h.status || 'unknown'} />
                  {h.symbol && <span style={{ fontSize: 10, fontWeight: 700, color: 'var(--text0)' }}>{h.symbol}</span>}
                  <span style={{ fontSize: 10, color: 'var(--text2)' }}>{h.intent || 'handoff'}</span>
                  {h.confidence != null && (
                    <span style={{ fontSize: 9, color: 'var(--text3)' }}>conf: {Number(h.confidence).toFixed(2)}</span>
                  )}
                  {h.escalated && <span style={{ fontSize: 9, fontWeight: 700, color: 'var(--red)' }}>ESCALATED</span>}
                  {h.reason && <span style={{ fontSize: 9, color: 'var(--text3)', flex: 1 }}>{h.reason}</span>}
                  <span style={{ fontSize: 9, color: 'var(--text3)', marginLeft: 'auto' }}>
                    {h.age_hours != null ? fmtHours(h.age_hours) + ' ago' : timeAgo(h.created_at)}
                  </span>
                </div>
              ))
            )}
          </div>
        )}
      </div>
    )
  }

  return (
    <div style={{ padding: '16px 24px', maxWidth: 1440 }}>
      <PageHeader
        title="Agent Collaboration, RACI & Outcomes"
        subtitle="Mission ownership, handoffs, blockers, stale work, and collaboration quality"
        actions={
          <ActionButton variant="primary" onClick={() => { setRk(k => k + 1); setSelectedId(null); setRaciData(null) }}>
            Refresh
          </ActionButton>
        }
      />

      {/* OPERATOR DECISION SUMMARY */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))', gap: 8, marginBottom: 16 }}>
        <StateCard compact title="Needs John" value={summary.ready_for_operator ?? 0} status="ready"
          actionLabel={summary.ready_for_operator > 0 ? 'Show ready' : undefined}
          onClick={() => handleStatusClick('ready')} />
        <StateCard compact title="Blocked" value={summary.blocked_missions ?? 0} status="blocked"
          actionLabel={summary.blocked_missions > 0 ? 'Show blocked' : undefined}
          onClick={() => handleStatusClick('blocked')} />
        <StateCard compact title="Waiting on Agent" value={waitingCount} status="waiting"
          onClick={() => handleStatusClick('waiting')} />
        <StateCard compact title="Stale" value={summary.stale_missions ?? 0} status="stale"
          onClick={() => handleStatusClick('stale')} />
        <StateCard compact title="System Trust"
          status={summary.system_trust_state === 'fresh' ? 'fresh' : summary.system_trust_state === 'stale' ? 'stale' : 'warning'}>
          <div style={{ fontSize: 16, fontWeight: 800, marginTop: 2 }}>{trustState}</div>
          <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 1 }}>Aegis: {timeAgo(summary.last_aegis_synthesis_at)}</div>
        </StateCard>
      </div>

      {/* TAB BAR */}
      <div style={{ display: 'flex', gap: 2, marginBottom: 12, borderBottom: '1px solid var(--border)', paddingBottom: 8 }}>
        {TAB_ITEMS.map(t => (
          <ActionButton key={t.key}
            variant={viewTab === t.key ? 'primary' : 'secondary'}
            size="sm"
            onClick={() => setViewTab(t.key)}>
            {t.label}
          </ActionButton>
        ))}
      </div>

      {/* ═══════════════════════════════════════════════════════════════════ */}
      {/* TAB 1: MISSIONS                                                   */}
      {/* ═══════════════════════════════════════════════════════════════════ */}
      {viewTab === 'missions' && (
        <>
          {/* Status filter chips */}
          <div style={{ display: 'flex', gap: 4, marginBottom: 6, flexWrap: 'wrap', alignItems: 'center' }}>
            <span style={{ fontSize: 9, color: 'var(--text3)', fontWeight: 700, textTransform: 'uppercase', marginRight: 4 }}>Status</span>
            {FILTER_CHIPS.map(f => {
              const count = f.key === 'all' ? allMissions.length
                : f.key === 'waiting' ? allMissions.filter(m => m.status !== 'ready' && m.status !== 'blocked' && m.status !== 'stale' && m.status !== 'completed' && m.status !== 'running').length
                : allMissions.filter(m => m.status === f.key).length
              const isActive = filter === f.key
              return (
                <ActionButton key={f.key}
                  variant={isActive ? 'primary' : 'secondary'}
                  size="sm"
                  onClick={() => { setFilter(f.key); setSelectedId(null) }}>
                  {f.label} ({count})
                </ActionButton>
              )
            })}
          </div>

          {/* Task type filter chips */}
          <div style={{ display: 'flex', gap: 4, marginBottom: 6, flexWrap: 'wrap', alignItems: 'center' }}>
            <span style={{ fontSize: 9, color: 'var(--text3)', fontWeight: 700, textTransform: 'uppercase', marginRight: 4 }}>Type</span>
            {TASK_TYPE_CHIPS.map(f => {
              const count = f.key === 'all' ? allMissions.length : allMissions.filter(m => m.mission_type === f.key).length
              return (
                <ActionButton key={f.key}
                  variant={taskTypeFilter === f.key ? 'primary' : 'secondary'}
                  size="sm"
                  onClick={() => { setTaskTypeFilter(f.key); setSelectedId(null) }}>
                  {f.label}{f.key !== 'all' ? ` (${count})` : ''}
                </ActionButton>
              )
            })}
          </div>

          {/* Time filter chips */}
          <div style={{ display: 'flex', gap: 4, marginBottom: 8, flexWrap: 'wrap', alignItems: 'center' }}>
            <span style={{ fontSize: 9, color: 'var(--text3)', fontWeight: 700, textTransform: 'uppercase', marginRight: 4 }}>Time</span>
            {TIME_CHIPS.map(f => (
              <ActionButton key={f.key}
                variant={timeFilter === f.key ? 'primary' : 'secondary'}
                size="sm"
                onClick={() => { setTimeFilter(f.key); setSelectedId(null) }}>
                {f.label}
              </ActionButton>
            ))}
          </div>

          {/* Active filter indicators */}
          {(agentFilter || filter !== 'all' || taskTypeFilter !== 'all' || timeFilter !== 'all') && (
            <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginBottom: 8, flexWrap: 'wrap' }}>
              <span style={{ fontSize: 10, color: 'var(--text3)', fontWeight: 600 }}>Active filters:</span>
              {filter !== 'all' && (
                <span style={{ fontSize: 10, padding: '2px 8px', borderRadius: 4, background: 'var(--accent-dim)', color: 'var(--accent)', fontWeight: 600, display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                  Status: {filter}
                  <button onClick={() => { setFilter('all'); setSelectedId(null) }}
                    style={{ background: 'none', border: 'none', color: 'var(--accent)', cursor: 'pointer', fontSize: 10, padding: 0, fontWeight: 800 }}>x</button>
                </span>
              )}
              {taskTypeFilter !== 'all' && (
                <span style={{ fontSize: 10, padding: '2px 8px', borderRadius: 4, background: 'var(--accent-dim)', color: 'var(--accent)', fontWeight: 600, display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                  Type: {TASK_TYPE_CHIPS.find(t => t.key === taskTypeFilter)?.label || taskTypeFilter}
                  <button onClick={() => { setTaskTypeFilter('all'); setSelectedId(null) }}
                    style={{ background: 'none', border: 'none', color: 'var(--accent)', cursor: 'pointer', fontSize: 10, padding: 0, fontWeight: 800 }}>x</button>
                </span>
              )}
              {timeFilter !== 'all' && (
                <span style={{ fontSize: 10, padding: '2px 8px', borderRadius: 4, background: 'var(--accent-dim)', color: 'var(--accent)', fontWeight: 600, display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                  Time: {TIME_CHIPS.find(t => t.key === timeFilter)?.label || timeFilter}
                  <button onClick={() => { setTimeFilter('all'); setSelectedId(null) }}
                    style={{ background: 'none', border: 'none', color: 'var(--accent)', cursor: 'pointer', fontSize: 10, padding: 0, fontWeight: 800 }}>x</button>
                </span>
              )}
              {agentFilter && (
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                  <AgentChip name={agentFilter} size="md" />
                  <button onClick={() => { setAgentFilter(null); setSelectedId(null) }}
                    style={{ background: 'none', border: 'none', color: 'var(--accent)', cursor: 'pointer', fontSize: 10, padding: 0, fontWeight: 800 }}>x</button>
                </span>
              )}
              <ActionButton variant="ghost" size="sm" onClick={() => { setFilter('all'); setAgentFilter(null); setTaskTypeFilter('all'); setTimeFilter('all'); setSelectedId(null) }}>
                Clear all
              </ActionButton>
            </div>
          )}

          {/* Two-pane layout */}
          <div style={{ display: 'flex', gap: 14, alignItems: 'flex-start' }}>

            {/* LEFT: Mission Queue */}
            <div style={{ flex: '0 0 42%', minWidth: 0, maxHeight: 'calc(100vh - 420px)', overflowY: 'auto' }}>
              {!missions.length ? (
                <Card title="">
                  <div style={{ textAlign: 'center', padding: 32, color: 'var(--text3)' }}>
                    <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 6 }}>All Clear</div>
                    <div style={{ fontSize: 11 }}>
                      {filter === 'all' && !agentFilter && taskTypeFilter === 'all' && timeFilter === 'all'
                        ? 'All agent missions are clear. No operator decision is currently required.'
                        : agentFilter
                          ? `No missions involving ${agentFilter.replace(/_/g, ' ')}${filter !== 'all' ? ` with status "${filter}"` : ''}.`
                          : `No missions matching current filters.`}
                    </div>
                    {(filter !== 'all' || agentFilter || taskTypeFilter !== 'all' || timeFilter !== 'all') && (
                      <ActionButton variant="ghost" size="sm" onClick={() => { setFilter('all'); setAgentFilter(null); setTaskTypeFilter('all'); setTimeFilter('all') }} style={{ marginTop: 8 }}>
                        Clear all filters
                      </ActionButton>
                    )}
                  </div>
                </Card>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  {missions.map((m: any) => {
                    const isSelected = selected?.mission_id === m.mission_id
                    return (
                      <div key={m.mission_id}
                        onClick={() => setSelectedId(m.mission_id)}
                        style={{
                          padding: '10px 12px', borderRadius: 'var(--radius)', cursor: 'pointer',
                          background: isSelected ? 'var(--bg2)' : 'var(--bg1)',
                          border: isSelected ? '1px solid var(--accent)' : '1px solid var(--border)',
                          borderLeft: `3px solid ${isSelected ? 'var(--accent)' : 'var(--border)'}`,
                          transition: 'var(--transition)',
                        }}>
                        {/* Title row */}
                        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
                          <span style={{ fontWeight: 700, fontSize: 12, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                            {m.title}
                          </span>
                          <SeverityBadge severity={m.severity} />
                          <span onClick={(e) => { e.stopPropagation(); handleStatusClick(m.status) }} style={{ cursor: 'pointer' }}>
                            <StatusBadge status={m.status} />
                          </span>
                        </div>
                        {/* Meta row */}
                        <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', fontSize: 10 }}>
                          {(m.agents || []).slice(0, 3).map((a: string) => (
                            <span key={a} onClick={(e) => { e.stopPropagation(); handleAgentClick(a) }}
                              style={{ cursor: 'pointer' }}>
                              <AgentChip name={a} />
                            </span>
                          ))}
                          <span style={{ color: 'var(--text3)' }}>{m.thread_count} items</span>
                          {m.blocked_count > 0 && (
                            <span style={{ color: 'var(--red)', fontWeight: 700 }}>{m.blocked_count} blocked</span>
                          )}
                          <span style={{ color: 'var(--text3)', marginLeft: 'auto' }}>{timeAgo(m.updated_at)}</span>
                        </div>
                        {/* Action preview */}
                        {m.next_action && (
                          <div style={{ fontSize: 10, color: 'var(--green)', fontWeight: 600, marginTop: 4 }}>
                            {m.next_action.label}
                          </div>
                        )}
                      </div>
                    )
                  })}
                </div>
              )}
            </div>

            {/* RIGHT: Mission Inspector */}
            <div style={{ flex: '1 1 0', minWidth: 0, maxHeight: 'calc(100vh - 420px)', overflowY: 'auto' }}>
              {!selected ? (
                <Card title="">
                  <div style={{ textAlign: 'center', padding: 32, color: 'var(--text3)' }}>
                    <div style={{ fontSize: 13, fontWeight: 700 }}>Select a mission</div>
                    <div style={{ fontSize: 11, marginTop: 4 }}>Click a mission from the queue to inspect it.</div>
                  </div>
                </Card>
              ) : (
                <Card title="">
                  <div style={{ position: 'relative' }}>
                    <button onClick={() => setSelectedId(null)}
                      style={{ position: 'absolute', top: -4, right: 0, background: 'none', border: 'none', color: 'var(--text3)', cursor: 'pointer', fontSize: 14 }}>
                      x
                    </button>

                    {/* A. Mission Summary with timestamps */}
                    <div style={{ marginBottom: 16 }}>
                      <div style={{ fontSize: 18, fontWeight: 800, marginBottom: 6, color: 'var(--text0)' }}>
                        {selected.title}
                      </div>
                      <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
                        <SeverityBadge severity={selected.severity} size="md" />
                        <span onClick={() => handleStatusClick(selected.status)} style={{ cursor: 'pointer' }}>
                          <StatusBadge status={selected.status} size="md" />
                        </span>
                        <span style={{ fontSize: 10, color: 'var(--text2)' }}>
                          Owner:{' '}
                          <span onClick={() => handleAgentClick(selected.primary_owner || 'system')}
                            style={{ cursor: 'pointer' }}>
                            <AgentChip name={selected.primary_owner || 'system'} />
                          </span>
                        </span>
                        <span style={{ fontSize: 10, color: 'var(--text3)', marginLeft: 'auto' }}>
                          {timeAgo(selected.updated_at)}
                        </span>
                      </div>
                      {/* Timestamps row */}
                      <div style={{ display: 'flex', gap: 12, marginTop: 6, fontSize: 9, color: 'var(--text3)' }}>
                        {selected.created_at && <span>Created: {timeAgo(selected.created_at)}</span>}
                        {selected.updated_at && <span>Updated: {timeAgo(selected.updated_at)}</span>}
                        {selected.age_hours != null && <span>Age: {fmtHours(selected.age_hours)}</span>}
                      </div>
                      {/* Stale duration info */}
                      {selected.status === 'stale' && (selected.stale_duration || selected.last_successful || selected.expected_refresher) && (
                        <div style={{
                          marginTop: 6, padding: '6px 10px', borderRadius: 4,
                          background: 'rgba(245,158,11,0.06)', border: '1px solid rgba(245,158,11,.15)',
                          fontSize: 10, color: 'var(--amber)',
                        }}>
                          {selected.stale_duration && <span>Stale for: {fmtHours(selected.stale_duration)} </span>}
                          {selected.last_successful && <span>Last success: {timeAgo(selected.last_successful)} </span>}
                          {selected.expected_refresher && <span>Expected refresher: {selected.expected_refresher}</span>}
                        </div>
                      )}
                    </div>

                    {/* B. Collaboration Timeline (inferred) */}
                    <div style={{ marginBottom: 16 }}>
                      <div style={{ fontSize: 9, fontWeight: 700, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '.5px', marginBottom: 6, display: 'flex', alignItems: 'center', gap: 6 }}>
                        Collaboration Timeline
                        <span style={{ fontSize: 8, fontWeight: 400, color: 'var(--text3)', fontStyle: 'italic' }}>inferred from mission state</span>
                      </div>
                      {(() => {
                        const timeline = inferTimeline(selected)
                        if (timeline.length === 0) {
                          return (
                            <div style={{ fontSize: 11, color: 'var(--text3)', padding: '8px 12px', background: 'var(--bg2)', borderRadius: 'var(--radius)' }}>
                              No timeline available. Collaboration event history is not tracked yet.
                            </div>
                          )
                        }
                        return (
                          <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                            {timeline.map((step, i) => (
                              <div key={i} style={{
                                display: 'flex', alignItems: 'center', gap: 8, padding: '4px 10px',
                                background: 'var(--bg2)', borderRadius: 4,
                                borderLeft: `3px solid ${step.step === 'Blocked' ? 'var(--red)' : step.step === 'Ready' ? 'var(--green)' : step.step === 'Stale' ? 'var(--amber)' : 'var(--border)'}`,
                              }}>
                                <span style={{ fontSize: 10, fontWeight: 700, color: 'var(--text1)', minWidth: 80 }}>{step.step}</span>
                                <span style={{ fontSize: 10, color: 'var(--text2)' }}>{step.detail}</span>
                              </div>
                            ))}
                          </div>
                        )
                      })()}
                    </div>

                    {/* C. RACI (owner-level fallback) */}
                    <div style={{ marginBottom: 16 }}>
                      <div style={{ fontSize: 9, fontWeight: 700, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '.5px', marginBottom: 6, display: 'flex', alignItems: 'center', gap: 6 }}>
                        RACI -- {(selected.primary_owner || 'system').replace(/_/g, ' ')}
                        <span style={{ fontSize: 8, fontWeight: 400, color: 'var(--text3)', fontStyle: 'italic' }}>owner-level RACI fallback</span>
                      </div>
                      {raciLoading ? (
                        <div style={{ fontSize: 11, color: 'var(--text3)', padding: '8px 0' }}>Loading RACI data...</div>
                      ) : raciData ? (
                        <RACIMatrix data={raciData} onPeerClick={handleAgentClick} />
                      ) : (
                        <div style={{ fontSize: 11, color: 'var(--text3)', padding: '8px 12px', background: 'var(--bg2)', borderRadius: 'var(--radius)' }}>
                          RACI data unavailable for {(selected.primary_owner || 'system').replace(/_/g, ' ')}. Per-mission RACI is not available yet.
                        </div>
                      )}
                    </div>

                    {/* C2. Agent Maturity (when available) */}
                    {selected.agent_maturity && (
                      <div style={{ marginBottom: 16 }}>
                        <div style={{ fontSize: 9, fontWeight: 700, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '.5px', marginBottom: 6 }}>
                          Agent Maturity
                        </div>
                        {(() => {
                          const am = selected.agent_maturity
                          const accPct = typeof am.accuracy === 'number' ? am.accuracy * 100 : null
                          return (
                            <div style={{
                              padding: '10px 14px', borderRadius: 'var(--radius)',
                              background: 'var(--bg1)', border: '1px solid var(--border)',
                              display: 'flex', flexDirection: 'column', gap: 6,
                            }}>
                              {/* Header row */}
                              <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                                <AgentChip name={am.agent || selected.primary_owner || 'system'} size="md" />
                                {accPct != null && (
                                  <span style={{ fontSize: 13, fontWeight: 800, color: accuracyColor(accPct) }}>
                                    {accPct.toFixed(1)}% accuracy
                                  </span>
                                )}
                                {am.calibration_error != null && (
                                  <span style={{ fontSize: 10, color: 'var(--text2)' }}>
                                    Cal err: {(am.calibration_error * 100).toFixed(1)}%
                                  </span>
                                )}
                                {am.sample_size_status && (
                                  <span style={{
                                    fontSize: 9, fontWeight: 700, padding: '1px 8px', borderRadius: 3,
                                    color: am.sample_size_status === 'sufficient' ? 'var(--green)' : 'var(--amber)',
                                    background: am.sample_size_status === 'sufficient' ? 'rgba(14,203,129,0.1)' : 'rgba(245,158,11,0.1)',
                                    textTransform: 'uppercase',
                                  }}>
                                    {am.sample_size_status}
                                  </span>
                                )}
                              </div>
                              {/* Stats row */}
                              <div style={{ display: 'flex', gap: 12, fontSize: 10, flexWrap: 'wrap' }}>
                                {am.correct != null && <span style={{ color: 'var(--green)' }}>{am.correct} correct</span>}
                                {am.resolved != null && <span style={{ color: 'var(--text2)' }}>{am.resolved} resolved</span>}
                                {am.incorrect != null && am.incorrect > 0 && <span style={{ color: 'var(--red)' }}>{am.incorrect} incorrect</span>}
                              </div>
                              {/* Schedule row */}
                              <div style={{ display: 'flex', gap: 12, fontSize: 9, color: 'var(--text3)', flexWrap: 'wrap' }}>
                                {am.last_run && <span>Last run: {timeAgo(am.last_run)}</span>}
                                {am.schedule && <span>Schedule: {am.schedule}</span>}
                                {am.next_expected_pickup && <span>Next pickup: {timeAgo(am.next_expected_pickup)}</span>}
                              </div>
                            </div>
                          )
                        })()}
                      </div>
                    )}

                    {/* D. Agent Contributions */}
                    {(selected.agents || []).length > 0 && (
                      <div style={{ marginBottom: 16 }}>
                        <div style={{ fontSize: 9, fontWeight: 700, color: 'var(--text3)', textTransform: 'uppercase', marginBottom: 6 }}>
                          Agent Contributions
                        </div>
                        <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                          {(selected.agents as string[]).map((a: string) => (
                            <span key={a} onClick={() => handleAgentClick(a)} style={{ cursor: 'pointer' }}>
                              <AgentChip name={a} size="md" showRole />
                            </span>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* E. Blockers / Staleness with enriched explanation */}
                    {(selected.primary_blocker || selected.status === 'stale') && (
                      <div style={{ marginBottom: 16, display: 'flex', flexDirection: 'column', gap: 6 }}>
                        {selected.primary_blocker && (
                          <div style={{
                            padding: '10px 14px', borderRadius: 'var(--radius)',
                            background: 'var(--red-dim)', border: '1px solid rgba(246,70,93,.2)',
                          }}>
                            <div style={{ fontSize: 9, fontWeight: 700, color: 'var(--red)', textTransform: 'uppercase', marginBottom: 4 }}>Blocker</div>
                            <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--red)', marginBottom: 4 }}>{selected.primary_blocker}</div>
                            {selected.primary_owner && (
                              <div style={{ fontSize: 10, color: 'var(--text2)' }}>
                                Owner: <span onClick={() => handleAgentClick(selected.primary_owner)} style={{ cursor: 'pointer' }}><AgentChip name={selected.primary_owner} /></span>
                              </div>
                            )}
                            {selected.next_action && (
                              <div style={{ fontSize: 10, color: 'var(--green)', fontWeight: 600, marginTop: 4 }}>Action: {selected.next_action.label}</div>
                            )}
                            {/* Enriched blocker context from threads */}
                            {(() => {
                              const threads = selected.threads || []
                              if (threads.length === 0) return null
                              const triggered = threads.filter((t: any) => t.thesis === 'triggered' || t.thesis === 'danger')
                              const weakening = threads.filter((t: any) => t.thesis === 'weakening' || t.thesis === 'warning')
                              const oldest = threads.reduce((o: any, t: any) => {
                                if (!t.observed_at) return o
                                if (!o) return t
                                return new Date(t.observed_at) < new Date(o.observed_at) ? t : o
                              }, null as any)
                              const ownerLastRun = selected.agent_maturity?.last_run
                              const ownerRanSince = ownerLastRun && oldest?.observed_at
                                ? new Date(ownerLastRun) > new Date(oldest.observed_at)
                                : null
                              if (triggered.length === 0 && weakening.length === 0 && !oldest) return null
                              return (
                                <div style={{ marginTop: 6, fontSize: 10, color: 'var(--text2)', display: 'flex', flexDirection: 'column', gap: 2 }}>
                                  {(triggered.length > 0 || weakening.length > 0) && (
                                    <span>{triggered.length} triggered, {weakening.length} weakening of {threads.length} items</span>
                                  )}
                                  {oldest?.observed_at && (
                                    <span>Oldest brief observed: {timeAgo(oldest.observed_at)}</span>
                                  )}
                                  {ownerRanSince != null && (
                                    <span style={{ color: ownerRanSince ? 'var(--green)' : 'var(--amber)', fontWeight: 600 }}>
                                      {ownerRanSince
                                        ? `Owner agent has run since oldest brief`
                                        : `Owner agent has NOT run since oldest brief`}
                                    </span>
                                  )}
                                </div>
                              )
                            })()}
                          </div>
                        )}
                        {selected.status === 'stale' && (
                          <div style={{
                            padding: '10px 14px', borderRadius: 'var(--radius)',
                            background: 'rgba(245,158,11,0.08)', border: '1px solid rgba(245,158,11,.2)',
                          }}>
                            <div style={{ fontSize: 9, fontWeight: 700, color: 'var(--amber)', textTransform: 'uppercase', marginBottom: 4 }}>Stale</div>
                            <div style={{ fontSize: 12, color: 'var(--amber)' }}>
                              This mission has had no activity recently. Last update: {timeAgo(selected.updated_at)}.
                            </div>
                            {selected.primary_owner && (
                              <div style={{ fontSize: 10, color: 'var(--text2)', marginTop: 4 }}>
                                Owner: <span onClick={() => handleAgentClick(selected.primary_owner)} style={{ cursor: 'pointer' }}><AgentChip name={selected.primary_owner} /></span>
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    )}

                    {/* F. What John Should Do */}
                    {selected.next_action && (
                      <div style={{
                        marginBottom: 16, padding: '10px 14px', borderRadius: 'var(--radius)',
                        background: 'var(--green-dim)', border: '1px solid rgba(14,203,129,.2)',
                      }}>
                        <div style={{ fontSize: 9, fontWeight: 700, color: 'var(--green)', textTransform: 'uppercase', marginBottom: 4 }}>
                          What John Should Do
                        </div>
                        <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--green)', marginBottom: 4 }}>
                          {selected.next_action.label}
                        </div>
                        {selected.next_action.reason && (
                          <div style={{ fontSize: 10, color: 'var(--text2)' }}>{selected.next_action.reason}</div>
                        )}
                        {selected.next_action.url && (
                          <ActionButton variant="primary" size="sm"
                            onClick={() => window.location.href = selected.next_action.url}
                            style={{ marginTop: 8 }}>
                            Open Page
                          </ActionButton>
                        )}
                      </div>
                    )}

                    {/* G. Mission Items (enhanced with rich thread data) */}
                    {(selected.threads || []).length > 0 && (
                      <div style={{ marginBottom: 16 }}>
                        <div style={{ fontSize: 9, fontWeight: 700, color: 'var(--text3)', textTransform: 'uppercase', marginBottom: 6 }}>
                          Mission Items ({selected.threads.length})
                        </div>
                        <div style={{ maxHeight: 360, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 3 }}>
                          {(selected.threads as any[]).map((t: any, i: number) => {
                            const isOpen = expandedThreads.has(i)
                            const hasDetail = t.detail || t.escalation_reason || t.steph_last_review !== undefined
                            return (
                              <div key={i} style={{
                                borderRadius: 4, background: 'var(--bg2)',
                                borderLeft: `3px solid ${t.status === 'blocked' ? 'var(--red)' : t.status === 'ready' ? 'var(--green)' : t.thesis === 'triggered' ? 'var(--red)' : 'var(--border)'}`,
                              }}>
                                {/* Clickable header row */}
                                <div
                                  onClick={() => hasDetail && toggleThread(i)}
                                  style={{
                                    padding: '6px 10px', cursor: hasDetail ? 'pointer' : 'default',
                                    display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap',
                                  }}>
                                  <span style={{ fontWeight: 700, fontSize: 11 }}>{t.subject}</span>
                                  <StatusBadge status={t.status} />
                                  {t.thesis && (
                                    <span style={{
                                      fontSize: 9, fontWeight: 700, padding: '1px 6px', borderRadius: 3,
                                      color: t.thesis === 'triggered' || t.thesis === 'danger' ? 'var(--red)'
                                        : t.thesis === 'weakening' || t.thesis === 'warning' ? 'var(--amber)'
                                        : t.thesis === 'intact' ? 'var(--green)' : 'var(--text3)',
                                      background: t.thesis === 'triggered' || t.thesis === 'danger' ? 'rgba(246,70,93,0.1)'
                                        : t.thesis === 'weakening' || t.thesis === 'warning' ? 'rgba(245,158,11,0.1)'
                                        : t.thesis === 'intact' ? 'rgba(14,203,129,0.1)' : 'var(--bg1)',
                                    }}>{t.thesis}</span>
                                  )}
                                  {t.confidence != null && (
                                    <span style={{ fontSize: 9, color: 'var(--text3)' }}>conf: {Number(t.confidence).toFixed(2)}</span>
                                  )}
                                  {t.age_hours != null && (
                                    <span style={{ fontSize: 9, color: 'var(--text3)' }}>{fmtHours(t.age_hours)} ago</span>
                                  )}
                                  {t.escalation_reason && (
                                    <span style={{ fontSize: 9, fontWeight: 700, color: 'var(--red)' }}>ESC</span>
                                  )}
                                  {hasDetail && (
                                    <span style={{ fontSize: 9, color: 'var(--text3)', marginLeft: 'auto' }}>{isOpen ? '-' : '+'}</span>
                                  )}
                                </div>

                                {/* Expanded detail section */}
                                {isOpen && (
                                  <div style={{ padding: '4px 10px 8px 10px', display: 'flex', flexDirection: 'column', gap: 4, borderTop: '1px solid var(--border)' }}>
                                    {t.detail && (
                                      <div style={{ fontSize: 10, color: 'var(--text2)' }}>{t.detail}</div>
                                    )}
                                    {t.observed_at && (
                                      <div style={{ fontSize: 9, color: 'var(--text3)' }}>Observed: {timeAgo(t.observed_at)}</div>
                                    )}
                                    {t.escalation_reason && (
                                      <div style={{ fontSize: 10, color: 'var(--red)', fontWeight: 600 }}>
                                        Escalation: {t.escalation_reason}
                                      </div>
                                    )}
                                    {/* Steph review info */}
                                    {t.steph_last_review != null ? (
                                      <div style={{
                                        fontSize: 10, color: 'var(--text2)', padding: '4px 8px',
                                        background: 'var(--bg1)', borderRadius: 4, borderLeft: '2px solid var(--accent)',
                                      }}>
                                        <span style={{ fontWeight: 600 }}>Steph last reviewed:</span>{' '}
                                        {timeAgo(t.steph_last_review)}
                                        {t.steph_recommendation && (
                                          <span> -- rec: <span style={{ fontWeight: 700 }}>{t.steph_recommendation}</span></span>
                                        )}
                                        {t.steph_confidence != null && (
                                          <span> ({Number(t.steph_confidence).toFixed(2)})</span>
                                        )}
                                        {t.steph_next_action && (
                                          <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 2 }}>
                                            Next action: {t.steph_next_action}
                                          </div>
                                        )}
                                      </div>
                                    ) : t.steph_last_review === null ? (
                                      <div style={{ fontSize: 10, color: 'var(--text3)', fontStyle: 'italic' }}>
                                        Steph has not reviewed this item
                                      </div>
                                    ) : null}
                                  </div>
                                )}
                              </div>
                            )
                          })}
                        </div>
                      </div>
                    )}

                    {/* H. Stats footer */}
                    <div style={{
                      fontSize: 9, color: 'var(--text3)', display: 'flex', gap: 12,
                      borderTop: '1px solid var(--border)', paddingTop: 8, alignItems: 'center',
                    }}>
                      <span>Threads: {selected.thread_count}</span>
                      <span>Blocked: {selected.blocked_count}</span>
                      <span>Ready: {selected.ready_count}</span>
                      <span>Updated: {timeAgo(selected.updated_at)}</span>
                      <span style={{ marginLeft: 'auto' }}>
                        <ActionButton variant="secondary" size="sm"
                          onClick={() => { window.location.href = '/agent-pipeline' }}>
                          Request Immediate Review
                        </ActionButton>
                      </span>
                    </div>
                  </div>
                </Card>
              )}
            </div>
          </div>
        </>
      )}

      {/* ═══════════════════════════════════════════════════════════════════ */}
      {/* TAB 2: COLLABORATION FLOW with drilldown                          */}
      {/* ═══════════════════════════════════════════════════════════════════ */}
      {viewTab === 'flow' && (
        <div>
          <div style={{ fontSize: 11, color: 'var(--text3)', fontStyle: 'italic', marginBottom: 16, padding: '6px 10px', background: 'var(--bg2)', borderRadius: 'var(--radius)' }}>
            Click any flow row to expand recent handoff details. Stale flows (&gt;48h) are flagged.
          </div>

          {agentNetwork.length === 0 && handoffDetails.length === 0 ? (
            <Card title="">
              <div style={{ textAlign: 'center', padding: 32, color: 'var(--text3)' }}>
                <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 6 }}>No Handoff Data</div>
                <div style={{ fontSize: 11 }}>No agent-to-agent handoff history is available. Handoff data appears as agents collaborate on missions.</div>
              </div>
            </Card>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
              {/* Agent-to-Agent Handoffs */}
              <div>
                <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', marginBottom: 8, textTransform: 'uppercase', letterSpacing: '.5px' }}>
                  Agent-to-Agent Handoffs
                </div>
                {flowGroups.agentToAgent.length === 0 ? (
                  <div style={{ fontSize: 11, color: 'var(--text3)', padding: '8px 12px', background: 'var(--bg2)', borderRadius: 'var(--radius)' }}>
                    No direct agent-to-agent handoffs recorded.
                  </div>
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
                    {flowGroups.agentToAgent.map((e, i) => renderFlowEdge(e, i, true, true))}
                  </div>
                )}
              </div>

              {/* System-to-Agent Routing */}
              <div>
                <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', marginBottom: 8, textTransform: 'uppercase', letterSpacing: '.5px' }}>
                  System-to-Agent Routing
                </div>
                {flowGroups.systemToAgent.length === 0 ? (
                  <div style={{ fontSize: 11, color: 'var(--text3)', padding: '8px 12px', background: 'var(--bg2)', borderRadius: 'var(--radius)' }}>
                    No system-to-agent routing recorded.
                  </div>
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
                    {flowGroups.systemToAgent.map((e, i) => renderFlowEdge(e, i, false, true))}
                  </div>
                )}
              </div>

              {/* Agent-to-Operator Escalations */}
              <div>
                <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', marginBottom: 8, textTransform: 'uppercase', letterSpacing: '.5px' }}>
                  Agent-to-Operator Escalations
                </div>
                {flowGroups.agentToOperator.length === 0 ? (
                  <div style={{ fontSize: 11, color: 'var(--text3)', padding: '8px 12px', background: 'var(--bg2)', borderRadius: 'var(--radius)' }}>
                    No agent-to-operator escalations recorded.
                  </div>
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
                    {flowGroups.agentToOperator.map((e, i) => renderFlowEdge(e, i, true, false))}
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      )}

      {/* ═══════════════════════════════════════════════════════════════════ */}
      {/* TAB 3: RACI MAP with health context                               */}
      {/* ═══════════════════════════════════════════════════════════════════ */}
      {viewTab === 'raci' && (
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
            <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text0)' }}>System-Wide RACI Map</div>
            <ActionButton variant="ghost" size="sm" onClick={loadRaciMap}>Reload</ActionButton>
          </div>

          {/* RACI Health from API */}
          {raciHealth.length > 0 && (
            <div style={{ marginBottom: 20 }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', marginBottom: 8, textTransform: 'uppercase', letterSpacing: '.5px' }}>
                Process Health
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
                {raciHealth.map((proc: any) => {
                  const isStale = proc.health === 'stale'
                  const isUnknown = proc.health === 'unknown'
                  return (
                    <div key={proc.process_id || proc.process_name} style={{
                      padding: '8px 12px', borderRadius: 'var(--radius)',
                      background: isStale ? 'rgba(245,158,11,0.06)' : 'var(--bg1)',
                      border: `1px solid ${isStale ? 'rgba(245,158,11,.2)' : 'var(--border)'}`,
                      display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap',
                    }}>
                      {/* Health badge */}
                      <span style={{
                        fontSize: 9, fontWeight: 700, padding: '2px 8px', borderRadius: 3,
                        color: healthColor(proc.health),
                        background: isStale ? 'rgba(245,158,11,0.1)' : isUnknown ? 'var(--bg2)' : 'rgba(14,203,129,0.1)',
                        textTransform: 'uppercase',
                      }}>
                        {proc.health}
                      </span>
                      <span style={{ fontSize: 11, fontWeight: 700, color: 'var(--text0)' }}>
                        {(proc.process_name || proc.process_id || '').replace(/_/g, ' ')}
                      </span>
                      {proc.trigger && (
                        <span style={{ fontSize: 9, color: 'var(--text3)' }}>trigger: {proc.trigger}</span>
                      )}
                      {proc.frequency && (
                        <span style={{ fontSize: 9, color: 'var(--text3)' }}>freq: {proc.frequency}</span>
                      )}
                      {/* Agents involved */}
                      {(proc.agents || []).length > 0 && (
                        <span style={{ display: 'inline-flex', gap: 3 }}>
                          {(proc.agents as string[]).slice(0, 4).map((a: string) => (
                            <span key={a} onClick={() => handleAgentClick(a)} style={{ cursor: 'pointer' }}>
                              <AgentChip name={a} />
                            </span>
                          ))}
                        </span>
                      )}
                      <span style={{ fontSize: 9, color: 'var(--text3)', marginLeft: 'auto' }}>
                        Last activity: {timeAgo(proc.last_activity)}
                        {proc.age_hours != null ? ` (${fmtHours(proc.age_hours)})` : ''}
                      </span>
                    </div>
                  )
                })}
              </div>
              {/* Stale process explanation */}
              {raciHealth.some((p: any) => p.health === 'stale') && (
                <div style={{
                  marginTop: 8, padding: '8px 12px', borderRadius: 'var(--radius)',
                  background: 'rgba(245,158,11,0.06)', border: '1px solid rgba(245,158,11,.15)',
                  fontSize: 10, color: 'var(--amber)',
                }}>
                  Stale processes have not run within their expected frequency window. Check cron schedules and agent health.
                </div>
              )}
            </div>
          )}

          <div style={{ fontSize: 11, color: 'var(--text3)', fontStyle: 'italic', marginBottom: 16 }}>
            Process-to-mission mapping is not available yet. Showing process-level RACI per agent from config/agent_raci.yaml.
          </div>

          {raciMapLoading && Object.keys(raciMapData).length === 0 ? (
            <div style={{ textAlign: 'center', padding: 32, color: 'var(--text3)' }}>
              <div style={{ fontSize: 12 }}>Loading RACI data for all agents...</div>
            </div>
          ) : Object.keys(raciMapData).length === 0 ? (
            <Card title="">
              <div style={{ textAlign: 'center', padding: 32, color: 'var(--text3)' }}>
                <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 6 }}>No RACI Data Available</div>
                <div style={{ fontSize: 11 }}>RACI configuration not found. Edit config/agent_raci.yaml to define process ownership.</div>
              </div>
            </Card>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {Object.entries(raciMapData).map(([agent, data]) => {
                const isCollapsed = raciCollapsed[agent] ?? false
                return (
                  <div key={agent} style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', overflow: 'hidden' }}>
                    <div
                      onClick={() => setRaciCollapsed(prev => ({ ...prev, [agent]: !isCollapsed }))}
                      style={{
                        display: 'flex', alignItems: 'center', gap: 8, padding: '10px 14px', cursor: 'pointer',
                        borderBottom: isCollapsed ? 'none' : '1px solid var(--border)',
                      }}>
                      <span style={{ fontSize: 12, color: 'var(--text3)', fontWeight: 600, width: 14 }}>{isCollapsed ? '+' : '-'}</span>
                      <AgentChip name={agent} size="md" showRole />
                    </div>
                    {!isCollapsed && (
                      <div style={{ padding: '8px 14px' }}>
                        <RACIMatrix data={data} onPeerClick={handleAgentClick} />
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          )}
        </div>
      )}

      {/* ═══════════════════════════════════════════════════════════════════ */}
      {/* TAB 4: OUTCOME QUALITY                                            */}
      {/* ═══════════════════════════════════════════════════════════════════ */}
      {viewTab === 'quality' && (
        <div>
          <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text0)', marginBottom: 16 }}>Collaboration Outcome Quality</div>

          {/* Agent Quality Section */}
          <div style={{ marginBottom: 24 }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', textTransform: 'uppercase', letterSpacing: '.5px', marginBottom: 10 }}>
              Agent Quality (Accuracy & Calibration)
            </div>
            {agentQuality.length === 0 ? (
              <div style={{ fontSize: 11, color: 'var(--text3)', padding: '12px 16px', background: 'var(--bg2)', borderRadius: 'var(--radius)' }}>
                No agent quality data available. Quality metrics appear as agents produce scored outcomes.
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                {agentQuality.map((aq: any) => {
                  const acc = typeof aq.accuracy === 'number' ? aq.accuracy : null
                  const accPct = acc != null ? (acc * 100) : null
                  return (
                    <div key={aq.agent_name} style={{
                      padding: '10px 14px', borderRadius: 'var(--radius)',
                      background: 'var(--bg1)', border: '1px solid var(--border)',
                      display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap',
                    }}>
                      <span onClick={() => handleAgentClick(aq.agent_name)} style={{ cursor: 'pointer' }}>
                        <AgentChip name={aq.agent_name} size="md" />
                      </span>

                      {/* Accuracy */}
                      {accPct != null && (
                        <span style={{
                          fontSize: 12, fontWeight: 800,
                          color: accuracyColor(accPct),
                        }}>
                          {accPct.toFixed(1)}% accuracy
                        </span>
                      )}

                      {/* Calibration error */}
                      {aq.calibration_error != null && (
                        <span style={{ fontSize: 10, color: 'var(--text2)' }}>
                          Cal err: {(aq.calibration_error * 100).toFixed(1)}%
                        </span>
                      )}

                      {/* Correct / Resolved */}
                      <span style={{ fontSize: 10, color: 'var(--green)' }}>
                        {aq.correct ?? 0} correct
                      </span>
                      <span style={{ fontSize: 10, color: 'var(--text2)' }}>
                        {aq.resolved ?? 0} resolved
                      </span>
                      {aq.incorrect != null && aq.incorrect > 0 && (
                        <span style={{ fontSize: 10, color: 'var(--red)' }}>
                          {aq.incorrect} incorrect
                        </span>
                      )}

                      {/* Overconfidence / Underconfidence */}
                      {aq.overconfidence_score != null && aq.overconfidence_score > 0.1 && (
                        <span style={{ fontSize: 9, fontWeight: 700, color: 'var(--amber)', background: 'rgba(245,158,11,0.1)', padding: '1px 6px', borderRadius: 3 }}>
                          Overconf: {(aq.overconfidence_score * 100).toFixed(0)}%
                        </span>
                      )}
                      {aq.underconfidence_score != null && aq.underconfidence_score > 0.1 && (
                        <span style={{ fontSize: 9, fontWeight: 700, color: 'var(--text3)', background: 'var(--bg2)', padding: '1px 6px', borderRadius: 3 }}>
                          Underconf: {(aq.underconfidence_score * 100).toFixed(0)}%
                        </span>
                      )}

                      {/* Sample size */}
                      {aq.sample_size_status && (
                        <span style={{ fontSize: 9, color: 'var(--text3)', marginLeft: 'auto' }}>
                          {aq.sample_size_status}
                        </span>
                      )}
                      {aq.scored_at && (
                        <span style={{ fontSize: 9, color: 'var(--text3)' }}>
                          {timeAgo(aq.scored_at)}
                        </span>
                      )}
                    </div>
                  )
                })}
              </div>
            )}
          </div>

          {/* Stale Products Section */}
          <div style={{ marginBottom: 24 }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', textTransform: 'uppercase', letterSpacing: '.5px', marginBottom: 10 }}>
              Data Product Freshness
            </div>
            {staleProducts.length === 0 ? (
              <div style={{ fontSize: 11, color: 'var(--text3)', padding: '12px 16px', background: 'var(--bg2)', borderRadius: 'var(--radius)' }}>
                No data product freshness info available.
              </div>
            ) : (() => {
              const staleOnes = staleProducts.filter((p: any) => !p.ok)
              const freshOnes = staleProducts.filter((p: any) => p.ok)
              return (
                <div>
                  {/* Stale products shown prominently */}
                  {staleOnes.length > 0 && (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 3, marginBottom: 8 }}>
                      {staleOnes.map((p: any) => (
                        <div key={p.state_file} style={{
                          padding: '8px 12px', borderRadius: 'var(--radius)',
                          background: 'rgba(246,70,93,0.06)', border: '1px solid rgba(246,70,93,.2)',
                          display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap',
                        }}>
                          <span style={{ fontSize: 9, fontWeight: 700, color: 'var(--red)', background: 'rgba(246,70,93,0.1)', padding: '1px 6px', borderRadius: 3, textTransform: 'uppercase' }}>
                            STALE
                          </span>
                          <span style={{ fontSize: 11, fontWeight: 700, color: 'var(--text0)', fontFamily: 'monospace' }}>
                            {p.state_file}
                          </span>
                          <span style={{ fontSize: 10, color: 'var(--text2)' }}>
                            Age: {fmtHours(p.age_hours)} / max {fmtHours(p.max_age_hours)}
                          </span>
                          {p.hours_overdue != null && p.hours_overdue > 0 && (
                            <span style={{ fontSize: 10, color: 'var(--red)', fontWeight: 700 }}>
                              {fmtHours(p.hours_overdue)} overdue
                            </span>
                          )}
                          {p.source_script && (
                            <span style={{ fontSize: 9, color: 'var(--text3)' }}>src: {p.source_script}</span>
                          )}
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Fresh products collapsed */}
                  {freshOnes.length > 0 && (
                    <div>
                      <ActionButton variant="ghost" size="sm" onClick={() => setShowFreshProducts(!showFreshProducts)}>
                        {showFreshProducts ? 'Hide' : 'Show'} {freshOnes.length} fresh products
                      </ActionButton>
                      {showFreshProducts && (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 2, marginTop: 6 }}>
                          {freshOnes.map((p: any) => (
                            <div key={p.state_file} style={{
                              padding: '5px 10px', borderRadius: 4, background: 'var(--bg2)',
                              display: 'flex', alignItems: 'center', gap: 8,
                              borderLeft: '3px solid var(--green)',
                            }}>
                              <span style={{ fontSize: 9, fontWeight: 600, color: 'var(--green)' }}>OK</span>
                              <span style={{ fontSize: 10, color: 'var(--text1)', fontFamily: 'monospace' }}>{p.state_file}</span>
                              <span style={{ fontSize: 9, color: 'var(--text3)', marginLeft: 'auto' }}>
                                Age: {fmtHours(p.age_hours)} / max {fmtHours(p.max_age_hours)}
                              </span>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}

                  {staleOnes.length === 0 && (
                    <div style={{ fontSize: 11, color: 'var(--green)', fontWeight: 600, padding: '6px 10px', background: 'rgba(14,203,129,0.06)', borderRadius: 'var(--radius)', marginBottom: 8 }}>
                      All {freshOnes.length} data products are fresh.
                    </div>
                  )}
                </div>
              )
            })()}
          </div>

          {/* Scoring Section (from existing API) */}
          {Object.keys(scoring).length > 0 && (
            <div style={{ marginBottom: 24 }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', textTransform: 'uppercase', letterSpacing: '.5px', marginBottom: 10 }}>
                System Scoring (Aggregate)
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 8 }}>
                {Object.entries(scoring).map(([key, val]) => (
                  <StateCard compact key={key} title={key.replace(/_/g, ' ')} value={typeof val === 'number' ? (val as number).toFixed(2) : String(val ?? '--')} status="fresh" />
                ))}
              </div>
            </div>
          )}

          {/* Link to Agent Calibration */}
          <div style={{
            padding: '12px 16px', borderRadius: 'var(--radius)',
            background: 'var(--bg1)', border: '1px solid var(--border)',
            display: 'flex', alignItems: 'center', gap: 12,
          }}>
            <span style={{ fontSize: 11, color: 'var(--text2)' }}>
              For detailed per-agent calibration curves and accuracy history, see Agent Calibration.
            </span>
            <ActionButton variant="secondary" size="sm" onClick={() => window.location.href = '/agent-calibration'}>
              View Agent Calibration
            </ActionButton>
          </div>
        </div>
      )}
    </div>
  )
}
