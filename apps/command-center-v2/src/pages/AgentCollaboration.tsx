import { useState, useMemo, useEffect, useCallback } from 'react'
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

  const { data: collab } = useApi<any>(`/api/v2/agent-collaboration?_r=${rk}`, 60000)

  const summary = collab?.summary || {}
  const johnActions: any[] = collab?.john_next_actions || []
  const allMissions: any[] = collab?.mission_groups || []
  const agentNetwork: any[] = collab?.agent_network || []

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

  // Quality signals
  const qualitySignals = useMemo(() => {
    const completed = allMissions.filter(m => m.status === 'completed').length
    const stale = summary.stale_missions ?? 0
    const blocked = summary.blocked_missions ?? 0
    const ready = summary.ready_for_operator ?? 0
    const totalHandoffs = agentNetwork.reduce((acc: number, e: any) => acc + (e.cnt || 0), 0)
    const completedHandoffs = agentNetwork.reduce((acc: number, e: any) => acc + Math.max(0, (e.cnt || 0) - (e.open || 0)), 0)
    const openHandoffs = totalHandoffs - completedHandoffs
    const escalations = agentNetwork.reduce((acc: number, e: any) => acc + (e.escalated || 0), 0)
    const agentsWithRaci = Object.keys(raciMapData).length
    const agentsMissingRaci = KNOWN_AGENTS.length - agentsWithRaci
    return { completed, stale, blocked, ready, totalHandoffs, completedHandoffs, openHandoffs, escalations, agentsWithRaci, agentsMissingRaci }
  }, [allMissions, summary, agentNetwork, raciMapData])

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

      {/* ═══ OPERATOR DECISION SUMMARY ═══ */}
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

      {/* ═══ TAB BAR ═══ */}
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

                    {/* A. Mission Summary */}
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

                    {/* E. Blockers / Staleness */}
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

                    {/* G. Mission Items */}
                    {(selected.threads || []).length > 0 && (
                      <div style={{ marginBottom: 16 }}>
                        <div style={{ fontSize: 9, fontWeight: 700, color: 'var(--text3)', textTransform: 'uppercase', marginBottom: 6 }}>
                          Mission Items ({selected.threads.length})
                        </div>
                        <div style={{ maxHeight: 280, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 3 }}>
                          {(selected.threads as any[]).map((t: any, i: number) => (
                            <div key={i} style={{
                              padding: '6px 10px', borderRadius: 4, background: 'var(--bg2)',
                              borderLeft: `3px solid ${t.status === 'blocked' ? 'var(--red)' : t.status === 'ready' ? 'var(--green)' : 'var(--border)'}`,
                            }}>
                              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                                <span style={{ fontWeight: 700, fontSize: 11 }}>{t.subject}</span>
                                <StatusBadge status={t.status} />
                                {t.thesis && (
                                  <span style={{
                                    fontSize: 9, fontWeight: 600,
                                    color: t.thesis === 'triggered' || t.thesis === 'danger' ? 'var(--red)'
                                      : t.thesis === 'warning' ? 'var(--amber)'
                                      : t.thesis === 'intact' ? 'var(--green)' : 'var(--text3)',
                                  }}>{t.thesis}</span>
                                )}
                                {t.confidence != null && (
                                  <span style={{ fontSize: 9, color: 'var(--text3)' }}>conf: {Number(t.confidence).toFixed(2)}</span>
                                )}
                              </div>
                              {t.detail && (
                                <div style={{ fontSize: 10, color: 'var(--text2)', marginTop: 2 }}>{t.detail}</div>
                              )}
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* H. Stats footer */}
                    <div style={{
                      fontSize: 9, color: 'var(--text3)', display: 'flex', gap: 12,
                      borderTop: '1px solid var(--border)', paddingTop: 8,
                    }}>
                      <span>Threads: {selected.thread_count}</span>
                      <span>Blocked: {selected.blocked_count}</span>
                      <span>Ready: {selected.ready_count}</span>
                      <span>Updated: {timeAgo(selected.updated_at)}</span>
                    </div>
                  </div>
                </Card>
              )}
            </div>
          </div>
        </>
      )}

      {/* ═══════════════════════════════════════════════════════════════════ */}
      {/* TAB 2: COLLABORATION FLOW                                         */}
      {/* ═══════════════════════════════════════════════════════════════════ */}
      {viewTab === 'flow' && (
        <div>
          <div style={{ fontSize: 11, color: 'var(--text3)', fontStyle: 'italic', marginBottom: 16, padding: '6px 10px', background: 'var(--bg2)', borderRadius: 'var(--radius)' }}>
            Derived from handoff history, not full collaboration events. Open handoffs are highlighted as actionable.
          </div>

          {agentNetwork.length === 0 ? (
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
                    {flowGroups.agentToAgent.map((e, i) => (
                      <div key={i} style={{
                        padding: '8px 12px', borderRadius: 'var(--radius)',
                        background: e.open > 0 ? 'rgba(245,158,11,0.06)' : 'var(--bg1)',
                        border: `1px solid ${e.open > 0 ? 'rgba(245,158,11,.2)' : 'var(--border)'}`,
                        display: 'flex', alignItems: 'center', gap: 8,
                      }}>
                        <span onClick={() => handleAgentClick(e.from_agent)} style={{ cursor: 'pointer' }}>
                          <AgentChip name={e.from_agent} />
                        </span>
                        <span style={{ fontSize: 10, color: 'var(--text3)' }}>-&gt;</span>
                        <span onClick={() => handleAgentClick(e.to_agent)} style={{ cursor: 'pointer' }}>
                          <AgentChip name={e.to_agent} />
                        </span>
                        <span style={{ fontSize: 10, color: 'var(--text2)', marginLeft: 'auto' }}>
                          Total: {e.cnt}
                        </span>
                        <span style={{ fontSize: 10, color: 'var(--green)' }}>Done: {e.completed}</span>
                        {e.open > 0 && <span style={{ fontSize: 10, color: 'var(--amber)', fontWeight: 700 }}>Open: {e.open}</span>}
                        {e.escalated > 0 && <span style={{ fontSize: 10, color: 'var(--red)', fontWeight: 700 }}>Esc: {e.escalated}</span>}
                        <span style={{ fontSize: 9, color: 'var(--text3)' }}>{timeAgo(e.latest)}</span>
                      </div>
                    ))}
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
                    {flowGroups.systemToAgent.map((e, i) => (
                      <div key={i} style={{
                        padding: '8px 12px', borderRadius: 'var(--radius)',
                        background: e.open > 0 ? 'rgba(245,158,11,0.06)' : 'var(--bg1)',
                        border: `1px solid ${e.open > 0 ? 'rgba(245,158,11,.2)' : 'var(--border)'}`,
                        display: 'flex', alignItems: 'center', gap: 8,
                      }}>
                        <span style={{ fontSize: 10, fontWeight: 600, color: 'var(--text2)', minWidth: 80 }}>{e.from_agent.replace(/_/g, ' ')}</span>
                        <span style={{ fontSize: 10, color: 'var(--text3)' }}>-&gt;</span>
                        <span onClick={() => handleAgentClick(e.to_agent)} style={{ cursor: 'pointer' }}>
                          <AgentChip name={e.to_agent} />
                        </span>
                        <span style={{ fontSize: 10, color: 'var(--text2)', marginLeft: 'auto' }}>Total: {e.cnt}</span>
                        <span style={{ fontSize: 10, color: 'var(--green)' }}>Done: {e.completed}</span>
                        {e.open > 0 && <span style={{ fontSize: 10, color: 'var(--amber)', fontWeight: 700 }}>Open: {e.open}</span>}
                        {e.escalated > 0 && <span style={{ fontSize: 10, color: 'var(--red)', fontWeight: 700 }}>Esc: {e.escalated}</span>}
                        <span style={{ fontSize: 9, color: 'var(--text3)' }}>{timeAgo(e.latest)}</span>
                      </div>
                    ))}
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
                    {flowGroups.agentToOperator.map((e, i) => (
                      <div key={i} style={{
                        padding: '8px 12px', borderRadius: 'var(--radius)',
                        background: e.open > 0 ? 'rgba(245,158,11,0.06)' : 'var(--bg1)',
                        border: `1px solid ${e.open > 0 ? 'rgba(245,158,11,.2)' : 'var(--border)'}`,
                        display: 'flex', alignItems: 'center', gap: 8,
                      }}>
                        <span onClick={() => handleAgentClick(e.from_agent)} style={{ cursor: 'pointer' }}>
                          <AgentChip name={e.from_agent} />
                        </span>
                        <span style={{ fontSize: 10, color: 'var(--text3)' }}>-&gt;</span>
                        <span style={{ fontSize: 10, fontWeight: 600, color: 'var(--text2)' }}>{e.to_agent.replace(/_/g, ' ')}</span>
                        <span style={{ fontSize: 10, color: 'var(--text2)', marginLeft: 'auto' }}>Total: {e.cnt}</span>
                        <span style={{ fontSize: 10, color: 'var(--green)' }}>Done: {e.completed}</span>
                        {e.open > 0 && <span style={{ fontSize: 10, color: 'var(--amber)', fontWeight: 700 }}>Open: {e.open}</span>}
                        {e.escalated > 0 && <span style={{ fontSize: 10, color: 'var(--red)', fontWeight: 700 }}>Esc: {e.escalated}</span>}
                        <span style={{ fontSize: 9, color: 'var(--text3)' }}>{timeAgo(e.latest)}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      )}

      {/* ═══════════════════════════════════════════════════════════════════ */}
      {/* TAB 3: RACI MAP                                                   */}
      {/* ═══════════════════════════════════════════════════════════════════ */}
      {viewTab === 'raci' && (
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
            <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text0)' }}>System-Wide RACI Map</div>
            <ActionButton variant="ghost" size="sm" onClick={loadRaciMap}>Reload</ActionButton>
          </div>
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

          {/* Observable Good Signals */}
          <div style={{ marginBottom: 20 }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--green)', textTransform: 'uppercase', letterSpacing: '.5px', marginBottom: 8 }}>
              Observable Good Signals
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 8 }}>
              <StateCard compact title="Ready Missions" value={qualitySignals.ready} status="ready" />
              <StateCard compact title="Completed Missions" value={qualitySignals.completed} status="fresh" />
              <StateCard compact title="Handoffs Completed" value={qualitySignals.completedHandoffs} status="fresh" />
            </div>
          </div>

          {/* Observable Bad Signals */}
          <div style={{ marginBottom: 20 }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--red)', textTransform: 'uppercase', letterSpacing: '.5px', marginBottom: 8 }}>
              Observable Bad Signals
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 8 }}>
              <StateCard compact title="Stale Missions" value={qualitySignals.stale} status={qualitySignals.stale > 0 ? 'stale' : 'fresh'} />
              <StateCard compact title="Blocked Missions" value={qualitySignals.blocked} status={qualitySignals.blocked > 0 ? 'blocked' : 'fresh'} />
              <StateCard compact title="Open Handoffs" value={qualitySignals.openHandoffs} status={qualitySignals.openHandoffs > 0 ? 'warning' : 'fresh'} />
              <StateCard compact title="Escalations" value={qualitySignals.escalations} status={qualitySignals.escalations > 10 ? 'warning' : 'fresh'} />
              <StateCard compact title="Agents Missing RACI" value={qualitySignals.agentsMissingRaci} status={qualitySignals.agentsMissingRaci > 0 ? 'warning' : 'fresh'} />
            </div>
          </div>

          {/* Missing Fields for True Scoring */}
          <div style={{
            padding: '14px 18px', borderRadius: 'var(--radius)',
            background: 'var(--bg1)', border: '1px solid var(--border)',
          }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '.5px', marginBottom: 8 }}>
              Missing API Fields for True Collaboration Scoring
            </div>
            <div style={{ fontSize: 11, color: 'var(--text2)', marginBottom: 10 }}>
              True collaboration scoring requires outcome event history. The following fields are not yet available in the API:
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              {[
                { field: 'collaboration_outcome', desc: 'Success/partial/failure per mission' },
                { field: 'handoff_resolution_time', desc: 'Time between agent handoffs' },
                { field: 'agent_agreement_score', desc: 'How often agents agree on recommendations' },
                { field: 'evidence_completeness', desc: 'Whether evidence was gathered before decision' },
                { field: 'per_mission_raci', desc: 'Dynamic RACI role assignment per mission' },
                { field: 'collaboration_event_timeline', desc: 'Full event log of collaboration steps' },
                { field: 'decision_accuracy_tracking', desc: 'Agent recommendation vs actual outcome' },
              ].map(item => (
                <div key={item.field} style={{
                  display: 'flex', alignItems: 'center', gap: 8, padding: '4px 10px',
                  background: 'var(--bg2)', borderRadius: 4,
                }}>
                  <code style={{ fontSize: 10, fontWeight: 700, color: 'var(--amber)', fontFamily: 'monospace', minWidth: 200 }}>{item.field}</code>
                  <span style={{ fontSize: 10, color: 'var(--text3)' }}>{item.desc}</span>
                </div>
              ))}
            </div>
            <div style={{ fontSize: 11, color: 'var(--text2)', marginTop: 12, display: 'flex', alignItems: 'center', gap: 8 }}>
              For per-agent accuracy data, see Agent Calibration.
              <ActionButton variant="secondary" size="sm" onClick={() => window.location.href = '/agent-calibration'}>
                View Agent Calibration
              </ActionButton>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
