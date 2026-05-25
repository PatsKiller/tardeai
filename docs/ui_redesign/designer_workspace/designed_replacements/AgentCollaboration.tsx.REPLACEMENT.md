# Replacement: AgentCollaboration.tsx — Decision Operations Cockpit

- **Target repo path:** apps/command-center-v2/src/pages/AgentCollaboration.tsx
- **Original SHA256:** a66c80ecb949df08bdd875cca161824de32e2c4efa9a92a9b686b19047758e98
- **Replacement timestamp:** 2026-05-25
- **Design summary:** Redesign from raw mission dump to Decision Operations Cockpit. Uses shared primitives (StatusBadge, SeverityBadge, AgentChip, ActionButton, StateCard). Adds client-side status filtering. Auto-selects highest-priority mission. Cleaner two-pane layout with inspector. Same API endpoint, no backend changes.

## Acceptance Checklist

- [ ] Uses shared primitives (StatusBadge, SeverityBadge, AgentChip, ActionButton, StateCard)
- [ ] Same API: /api/v2/agent-collaboration
- [ ] No backend changes
- [ ] Client-side filter chips
- [ ] Auto-selects first mission
- [ ] Empty state when no missions
- [ ] No inline color constants — uses theme.css vars + shared components
- [ ] No trading/approval execution
- [ ] Build passes

```tsx
import { useState, useMemo, useEffect } from 'react'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import { useApi } from '../hooks/useApi'
import { StatusBadge } from '../components/StatusBadge'
import { SeverityBadge } from '../components/SeverityBadge'
import { AgentChip } from '../components/AgentChip'
import { ActionButton } from '../components/ActionButton'
import { StateCard } from '../components/StateCard'

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

type StatusFilter = 'all' | 'ready' | 'blocked' | 'waiting' | 'stale' | 'running'

const FILTER_CHIPS: { key: StatusFilter; label: string }[] = [
  { key: 'all', label: 'All' },
  { key: 'ready', label: 'Ready' },
  { key: 'blocked', label: 'Blocked' },
  { key: 'waiting', label: 'Waiting' },
  { key: 'stale', label: 'Stale' },
  { key: 'running', label: 'Running' },
]

export default function AgentCollaboration() {
  const [rk, setRk] = useState(0)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [filter, setFilter] = useState<StatusFilter>('all')

  const { data: collab } = useApi<any>(`/api/v2/agent-collaboration?_r=${rk}`, 60000)

  const summary = collab?.summary || {}
  const johnActions: any[] = collab?.john_next_actions || []
  const allMissions: any[] = collab?.mission_groups || []

  // Filter missions
  const missions = useMemo(() => {
    if (filter === 'all') return allMissions
    return allMissions.filter(m => m.status === filter)
  }, [allMissions, filter])

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

  const trustState = (summary.system_trust_state || 'unknown').toUpperCase()

  return (
    <div style={{ padding: '16px 24px', maxWidth: 1440 }}>
      <PageHeader
        title="Decision Operations"
        subtitle="Agent mission control — blockers, decisions, and evidence"
        actions={
          <ActionButton variant="primary" onClick={() => { setRk(k => k + 1); setSelectedId(null) }}>
            Refresh
          </ActionButton>
        }
      />

      {/* ═══ SUMMARY STRIP ═══ */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', gap: 8, marginBottom: 16 }}>
        <StateCard compact title="Ready for Decision" value={summary.ready_for_operator ?? 0} status="ready"
          actionLabel={summary.ready_for_operator > 0 ? 'Show ready' : undefined}
          onClick={summary.ready_for_operator > 0 ? () => setFilter('ready') : undefined} />
        <StateCard compact title="Blocked" value={summary.blocked_missions ?? 0} status="blocked"
          actionLabel={summary.blocked_missions > 0 ? 'Show blocked' : undefined}
          onClick={summary.blocked_missions > 0 ? () => setFilter('blocked') : undefined} />
        <StateCard compact title="Active Missions" value={summary.active_missions ?? 0} status="running" />
        <StateCard compact title="Stale" value={summary.stale_missions ?? 0} status="stale" />
        <StateCard compact title="System Trust" status={summary.system_trust_state === 'fresh' ? 'fresh' : summary.system_trust_state === 'stale' ? 'stale' : 'warning'}>
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
                  if (m) { setSelectedId(m.mission_id); setFilter('all') }
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
                      Open →
                    </ActionButton>
                  )}
                </div>
                {a.reason && <div style={{ fontSize: 10, color: 'var(--text2)', marginTop: 2 }}>{a.reason}</div>}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ═══ FILTER CHIPS ═══ */}
      <div style={{ display: 'flex', gap: 4, marginBottom: 12 }}>
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

      {/* ═══ TWO-PANE COCKPIT ═══ */}
      <div style={{ display: 'flex', gap: 14, alignItems: 'flex-start' }}>

        {/* ── LEFT: Mission Queue ── */}
        <div style={{ flex: '0 0 42%', minWidth: 0, maxHeight: 'calc(100vh - 320px)', overflowY: 'auto' }}>
          {!missions.length ? (
            <Card title="">
              <div style={{ textAlign: 'center', padding: 32, color: 'var(--text3)' }}>
                <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 6 }}>All Clear</div>
                <div style={{ fontSize: 11 }}>
                  {filter === 'all'
                    ? 'All agent missions are clear. No operator decision is currently required.'
                    : `No missions with status "${filter}".`}
                </div>
                {filter !== 'all' && (
                  <ActionButton variant="ghost" size="sm" onClick={() => setFilter('all')} style={{ marginTop: 8 }}>
                    Show all missions
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
                      {(m.agents || []).slice(0, 3).map((a: string) => <AgentChip key={a} name={a} />)}
                      <span style={{ color: 'var(--text3)' }}>{m.thread_count} items</span>
                      {m.blocked_count > 0 && <span style={{ color: 'var(--red)', fontWeight: 700 }}>{m.blocked_count} blocked</span>}
                      <span style={{ color: 'var(--text3)', marginLeft: 'auto' }}>{timeAgo(m.updated_at)}</span>
                    </div>
                    {/* Action preview */}
                    {m.next_action && (
                      <div style={{ fontSize: 10, color: 'var(--green)', fontWeight: 600, marginTop: 4 }}>
                        → {m.next_action.label}
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          )}
        </div>

        {/* ── RIGHT: Mission Inspector ── */}
        <div style={{ flex: '1 1 0', minWidth: 0, maxHeight: 'calc(100vh - 320px)', overflowY: 'auto' }}>
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
                  ✕
                </button>

                {/* Header */}
                <div style={{ marginBottom: 16 }}>
                  <div style={{ fontSize: 18, fontWeight: 800, marginBottom: 6, color: 'var(--text0)' }}>{selected.title}</div>
                  <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
                    <SeverityBadge severity={selected.severity} size="md" />
                    <StatusBadge status={selected.status} size="md" />
                    <span style={{ fontSize: 10, color: 'var(--text2)' }}>
                      Owner: <AgentChip name={selected.primary_owner || 'system'} />
                    </span>
                    <span style={{ fontSize: 10, color: 'var(--text3)', marginLeft: 'auto' }}>{timeAgo(selected.updated_at)}</span>
                  </div>
                </div>

                {/* Next Action */}
                {selected.next_action && (
                  <div style={{ marginBottom: 16, padding: '10px 14px', borderRadius: 'var(--radius)', background: 'var(--green-dim)', border: '1px solid rgba(14,203,129,.2)' }}>
                    <div style={{ fontSize: 9, fontWeight: 700, color: 'var(--green)', textTransform: 'uppercase', marginBottom: 4 }}>Next Action</div>
                    <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--green)', marginBottom: 4 }}>{selected.next_action.label}</div>
                    {selected.next_action.reason && (
                      <div style={{ fontSize: 10, color: 'var(--text2)' }}>{selected.next_action.reason}</div>
                    )}
                    {selected.next_action.url && (
                      <ActionButton variant="primary" size="sm" onClick={() => window.location.href = selected.next_action.url} style={{ marginTop: 8 }}>
                        Open Page →
                      </ActionButton>
                    )}
                  </div>
                )}

                {/* Blocker */}
                {selected.primary_blocker && (
                  <div style={{ marginBottom: 16, padding: '10px 14px', borderRadius: 'var(--radius)', background: 'var(--red-dim)', border: '1px solid rgba(246,70,93,.2)' }}>
                    <div style={{ fontSize: 9, fontWeight: 700, color: 'var(--red)', textTransform: 'uppercase', marginBottom: 4 }}>Blocker</div>
                    <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--red)' }}>{selected.primary_blocker}</div>
                  </div>
                )}

                {/* Agents */}
                {(selected.agents || []).length > 0 && (
                  <div style={{ marginBottom: 16 }}>
                    <div style={{ fontSize: 9, fontWeight: 700, color: 'var(--text3)', textTransform: 'uppercase', marginBottom: 6 }}>Agents Involved</div>
                    <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                      {(selected.agents as string[]).map((a: string) => (
                        <AgentChip key={a} name={a} size="md" showRole />
                      ))}
                    </div>
                  </div>
                )}

                {/* Items */}
                {(selected.threads || []).length > 0 && (
                  <div style={{ marginBottom: 16 }}>
                    <div style={{ fontSize: 9, fontWeight: 700, color: 'var(--text3)', textTransform: 'uppercase', marginBottom: 6 }}>
                      Items ({selected.threads.length})
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
                                color: t.thesis === 'triggered' || t.thesis === 'danger' ? 'var(--red)' : t.thesis === 'warning' ? 'var(--amber)' : t.thesis === 'intact' ? 'var(--green)' : 'var(--text3)',
                              }}>{t.thesis}</span>
                            )}
                            {t.confidence != null && (
                              <span style={{ fontSize: 9, color: 'var(--text3)' }}>conf: {Number(t.confidence).toFixed(2)}</span>
                            )}
                          </div>
                          {t.detail && <div style={{ fontSize: 10, color: 'var(--text2)', marginTop: 2 }}>{t.detail}</div>}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Stats */}
                <div style={{ fontSize: 9, color: 'var(--text3)', display: 'flex', gap: 12, borderTop: '1px solid var(--border)', paddingTop: 8 }}>
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
    </div>
  )
}
```
