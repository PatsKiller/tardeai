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

type StatusFilter = 'all' | 'ready' | 'blocked' | 'waiting' | 'stale' | 'running' | 'completed'
type TaskTypeFilter = 'all' | 'risk' | 'paper_proposal' | 'research_gap' | 'system_health' | 'content_hygiene' | 'alert' | 'morning_brief' | 'ticker'
type TimeFilter = 'all' | '24h' | '7d' | '30d'
type ViewTab = 'missions' | 'raci'

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

const KNOWN_AGENTS = ['maria', 'steph', 'aegis', 'alex', 'risk_agent', 'tax_agent', 'iris', 'social_scalp', 'scalp_critic']

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

  const { data: collab } = useApi<any>(`/api/v2/agent-collaboration?_r=${rk}`, 60000)

  const summary = collab?.summary || {}
  const johnActions: any[] = collab?.john_next_actions || []
  const allMissions: any[] = collab?.mission_groups || []

  // Filter missions by status, agent, task type, and time
  const missions = useMemo(() => {
    let result = allMissions
    if (filter !== 'all') {
      result = result.filter(m => m.status === filter)
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

  // Auto-select first mission on data load
  useEffect(() => {
    if (!selectedId && missions.length > 0) {
      setSelectedId(missions[0].mission_id)
    }
  }, [missions, selectedId])

  // Fetch RACI data when selected mission changes
  useEffect(() => {
    if (!selected?.primary_owner) { setRaciData(null); return }
    const agent = selected.primary_owner
    setRaciLoading(true)
    fetch(`/api/v2/agent-detail/raci?agent=${encodeURIComponent(agent)}`)
      .then(r => r.ok ? r.json() : null)
      .then(d => { setRaciData(d); setRaciLoading(false) })
      .catch(() => { setRaciData(null); setRaciLoading(false) })
  }, [selected?.primary_owner, selected?.mission_id])

  // Fetch RACI Map data for all known agents
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

  // Load RACI map when switching to that tab
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

  return (
    <div style={{ padding: '16px 24px', maxWidth: 1440 }}>
      <PageHeader
        title="Agent Collaboration & Outcomes"
        subtitle="How agents coordinate, where work is blocked, and which collaborations helped or hurt decisions"
        actions={
          <ActionButton variant="primary" onClick={() => { setRk(k => k + 1); setSelectedId(null); setRaciData(null) }}>
            Refresh
          </ActionButton>
        }
      />

      {/* ═══ SUMMARY SCORECARD ═══ */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))', gap: 8, marginBottom: 16 }}>
        <StateCard compact title="Ready for John" value={summary.ready_for_operator ?? 0} status="ready"
          actionLabel={summary.ready_for_operator > 0 ? 'Show ready' : undefined}
          onClick={() => { setFilter('ready'); setSelectedId(null) }} />
        <StateCard compact title="Blocked" value={summary.blocked_missions ?? 0} status="blocked"
          actionLabel={summary.blocked_missions > 0 ? 'Show blocked' : undefined}
          onClick={() => { setFilter('blocked'); setSelectedId(null) }} />
        <StateCard compact title="Waiting on Agent"
          value={summary.waiting_missions ?? Math.max(0, (summary.active_missions ?? 0) - (summary.ready_for_operator ?? 0) - (summary.blocked_missions ?? 0))}
          status="waiting"
          onClick={() => { setFilter('waiting'); setSelectedId(null) }} />
        <StateCard compact title="Stale" value={summary.stale_missions ?? 0} status="stale"
          onClick={() => { setFilter('stale'); setSelectedId(null) }} />
        <StateCard compact title="System Trust"
          status={summary.system_trust_state === 'fresh' ? 'fresh' : summary.system_trust_state === 'stale' ? 'stale' : 'warning'}>
          <div style={{ fontSize: 16, fontWeight: 800, marginTop: 2 }}>{trustState}</div>
          <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 1 }}>Aegis: {timeAgo(summary.last_aegis_synthesis_at)}</div>
        </StateCard>
      </div>

      {/* ═══ JOHN'S NEXT ACTIONS ═══ */}
      {johnActions.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--green)', textTransform: 'uppercase', letterSpacing: '.5px', marginBottom: 6 }}>
            What John Should Do
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {johnActions.map((a, i) => (
              <div key={i}
                onClick={() => {
                  const m = allMissions.find((m: any) => m.mission_id === a.mission_id)
                  if (m) { setSelectedId(m.mission_id); setFilter('all'); setViewTab('missions') }
                }}
                style={{
                  padding: '8px 12px', borderRadius: 'var(--radius)', cursor: 'pointer',
                  background: 'var(--bg1)', border: '1px solid var(--border)',
                  borderLeft: '3px solid var(--green)',
                  transition: 'var(--transition)',
                }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <SeverityBadge severity={a.severity} />
                  <span style={{ fontWeight: 700, fontSize: 12, flex: 1 }}>{a.label}</span>
                  {a.url && (
                    <ActionButton variant="ghost" size="sm" onClick={(e) => { e.stopPropagation(); window.location.href = a.url }}>
                      Open
                    </ActionButton>
                  )}
                </div>
                {a.reason && <div style={{ fontSize: 10, color: 'var(--text2)', marginTop: 2 }}>{a.reason}</div>}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ═══ VIEW TAB TOGGLE ═══ */}
      <div style={{ display: 'flex', gap: 2, marginBottom: 12, borderBottom: '1px solid var(--border)', paddingBottom: 8 }}>
        <ActionButton
          variant={viewTab === 'missions' ? 'primary' : 'secondary'}
          size="sm"
          onClick={() => setViewTab('missions')}>
          Missions
        </ActionButton>
        <ActionButton
          variant={viewTab === 'raci' ? 'primary' : 'secondary'}
          size="sm"
          onClick={() => setViewTab('raci')}>
          RACI Map
        </ActionButton>
      </div>

      {/* ═══ MISSIONS TAB ═══ */}
      {viewTab === 'missions' && (
        <>
          {/* Status filter chips */}
          <div style={{ display: 'flex', gap: 4, marginBottom: 6, flexWrap: 'wrap', alignItems: 'center' }}>
            <span style={{ fontSize: 9, color: 'var(--text3)', fontWeight: 700, textTransform: 'uppercase', marginRight: 4 }}>Status</span>
            {FILTER_CHIPS.map(f => {
              const count = f.key === 'all' ? allMissions.length : allMissions.filter(m => m.status === f.key).length
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

          {/* Active agent filter indicator */}
          {agentFilter && (
            <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginBottom: 8 }}>
              <span style={{ fontSize: 10, color: 'var(--text3)', fontWeight: 600 }}>Filtered by agent:</span>
              <AgentChip name={agentFilter} size="md" />
              <ActionButton variant="ghost" size="sm" onClick={() => { setAgentFilter(null); setSelectedId(null) }}>
                Clear
              </ActionButton>
            </div>
          )}

          {/* Two-pane cockpit */}
          <div style={{ display: 'flex', gap: 14, alignItems: 'flex-start' }}>

            {/* LEFT: Mission Queue */}
            <div style={{ flex: '0 0 42%', minWidth: 0, maxHeight: 'calc(100vh - 380px)', overflowY: 'auto' }}>
              {!missions.length ? (
                <Card title="">
                  <div style={{ textAlign: 'center', padding: 32, color: 'var(--text3)' }}>
                    <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 6 }}>All Clear</div>
                    <div style={{ fontSize: 11 }}>
                      {filter === 'all' && !agentFilter
                        ? 'All agent missions are clear. No operator decision is currently required.'
                        : agentFilter
                          ? `No missions involving ${agentFilter.replace(/_/g, ' ')}${filter !== 'all' ? ` with status "${filter}"` : ''}.`
                          : `No missions with status "${filter}".`}
                    </div>
                    {(filter !== 'all' || agentFilter) && (
                      <ActionButton variant="ghost" size="sm" onClick={() => { setFilter('all'); setAgentFilter(null) }} style={{ marginTop: 8 }}>
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
                          <StatusBadge status={m.status} />
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
            <div style={{ flex: '1 1 0', minWidth: 0, maxHeight: 'calc(100vh - 380px)', overflowY: 'auto' }}>
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
                        <StatusBadge status={selected.status} size="md" />
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

                    {/* B. RACI for this Mission */}
                    <div style={{ marginBottom: 16 }}>
                      <div style={{ fontSize: 9, fontWeight: 700, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '.5px', marginBottom: 6 }}>
                        RACI — {(selected.primary_owner || 'system').replace(/_/g, ' ')}
                      </div>
                      {raciLoading ? (
                        <div style={{ fontSize: 11, color: 'var(--text3)', padding: '8px 0' }}>
                          Loading RACI data...
                        </div>
                      ) : raciData ? (
                        <RACIMatrix data={raciData} onPeerClick={handleAgentClick} />
                      ) : (
                        <div style={{
                          fontSize: 11, color: 'var(--text3)', padding: '8px 12px',
                          background: 'var(--bg2)', borderRadius: 'var(--radius)',
                        }}>
                          RACI data unavailable for this mission.
                        </div>
                      )}
                    </div>

                    {/* C. Why This Matters */}
                    {selected.why_this_matters && (
                      <div style={{
                        marginBottom: 16, padding: '10px 14px', borderRadius: 'var(--radius)',
                        background: 'var(--bg2)', border: '1px solid var(--border)',
                      }}>
                        <div style={{ fontSize: 9, fontWeight: 700, color: 'var(--text3)', textTransform: 'uppercase', marginBottom: 4 }}>
                          Why This Matters
                        </div>
                        <div style={{ fontSize: 12, color: 'var(--text1)' }}>{selected.why_this_matters}</div>
                      </div>
                    )}

                    {/* D. Current Blockers */}
                    {selected.primary_blocker && (
                      <div style={{
                        marginBottom: 16, padding: '10px 14px', borderRadius: 'var(--radius)',
                        background: 'var(--red-dim)', border: '1px solid rgba(246,70,93,.2)',
                      }}>
                        <div style={{ fontSize: 9, fontWeight: 700, color: 'var(--red)', textTransform: 'uppercase', marginBottom: 4 }}>
                          Blocker
                        </div>
                        <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--red)' }}>
                          {selected.primary_blocker}
                        </div>
                      </div>
                    )}

                    {/* E. Agent Contributions */}
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
                                  <span style={{ fontSize: 9, color: 'var(--text3)' }}>
                                    conf: {Number(t.confidence).toFixed(2)}
                                  </span>
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

              {/* Collaboration Quality */}
              <div style={{
                marginTop: 12, padding: '12px 16px', borderRadius: 'var(--radius)',
                background: 'var(--bg1)', border: '1px solid var(--border)',
              }}>
                <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '.5px', marginBottom: 6 }}>
                  Collaboration Quality
                </div>
                <div style={{ fontSize: 11, color: 'var(--text2)', marginBottom: 8 }}>
                  Collaboration scoring requires outcome event history. Current view shows mission state only.
                  For detailed agent accuracy, see Agent Calibration.
                </div>
                <ActionButton variant="secondary" size="sm" onClick={() => window.location.href = '/agent-calibration'}>
                  View Agent Calibration
                </ActionButton>
              </div>
            </div>
          </div>
        </>
      )}

      {/* ═══ RACI MAP TAB ═══ */}
      {viewTab === 'raci' && (
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16 }}>
            <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text0)' }}>System-Wide RACI Map</div>
            <ActionButton variant="ghost" size="sm" onClick={loadRaciMap}>
              Reload
            </ActionButton>
          </div>

          {raciMapLoading && Object.keys(raciMapData).length === 0 ? (
            <div style={{ textAlign: 'center', padding: 32, color: 'var(--text3)' }}>
              <div style={{ fontSize: 12 }}>Loading RACI data for all agents...</div>
            </div>
          ) : Object.keys(raciMapData).length === 0 ? (
            <Card title="">
              <div style={{ textAlign: 'center', padding: 32, color: 'var(--text3)' }}>
                <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 6 }}>No RACI Data Available</div>
                <div style={{ fontSize: 11 }}>
                  RACI configuration not found. Edit config/agent_raci.yaml to define process ownership.
                </div>
              </div>
            </Card>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              {Object.entries(raciMapData).map(([agent, data]) => (
                <div key={agent}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                    <AgentChip name={agent} size="md" showRole />
                  </div>
                  <RACIMatrix data={data} onPeerClick={handleAgentClick} />
                </div>
              ))}
              <div style={{
                fontSize: 11, color: 'var(--text3)', padding: '8px 0',
                borderTop: '1px solid var(--border)',
              }}>
                For per-agent RACI details, visit the Agent Dashboard.
                <ActionButton variant="ghost" size="sm"
                  onClick={() => window.location.href = '/agent-dashboard'}
                  style={{ marginLeft: 8 }}>
                  Agent Dashboard
                </ActionButton>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
