import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import AgentChip from '../components/AgentChip'
import StatusBadge from '../components/StatusBadge'
import ActionButton from '../components/ActionButton'
import { useApi } from '../hooks/useApi'
import { timeAgo } from '../lib/format'

/* ── Types ── */
interface Job { id: number; symbol: string; requested_agent: string; request_type: string; status: string; priority: number; submitted_from: string; created_at: string; started_at: string | null; completed_at: string | null; payload_text: string | null }
interface Result { symbol: string; agent: string; recommendation: string; confidence: number; summary: string; created_at: string; model_used: string; status: string; rag_sources_used: any; peer_notes_symbols: string | null }
interface Handoff { symbol: string; from_agent: string; to_agent: string; reason: string; escalated: boolean; created_at: string }
interface Event { id: number; event_type: string; symbol: string; priority: number; status: string; agents_to_notify: string; trigger_text: string | null; created_at: string; processed_at: string | null }
interface Summary { queued: number; processing: number; completed: number; failed: number; total_24h: number; events_pending: number; events_done: number; handoffs_24h: number; analyses_24h: number; proposals_pending: number; debates_24h: number }
interface PipelineData { jobs: Job[]; results: Result[]; handoffs: Handoff[]; events: Event[]; proposals: any[]; debates: any[]; summary: Summary }
interface LlmProvider { available: boolean; model?: string }
interface SystemHealth { llm: { local: LlmProvider; grok: LlmProvider; claude: LlmProvider; openai: LlmProvider; daily_spend: number; daily_budget: number; budget_remaining: number } }
interface AgentHealthEntry { agent: string; total_analyses: number; avg_confidence: number; last_run: string; low_conf_count: number }
interface AgentHealthData { agents: AgentHealthEntry[] }

/* ── Helpers ── */
const sKey = (s: string) => s === 'completed' || s === 'done' ? 'green' : s === 'processing' || s === 'running' ? 'info' : s === 'queued' ? 'amber' : s === 'failed' ? 'red' : 'muted'
const priColor = (p: number) => p >= 8 ? '#f6465d' : p >= 5 ? '#f0b90b' : p >= 3 ? '#4a90f4' : 'var(--text3)'
const recColor = (r: string) => { const l = (r||'').toLowerCase(); return l.includes('sell') || l.includes('trim') || l.includes('avoid') ? '#f6465d' : l.includes('buy') || l.includes('add') ? '#0ecb81' : 'var(--text1)' }

const Dot = ({ color }: { color: string }) => <span style={{ display: 'inline-block', width: 7, height: 7, borderRadius: '50%', background: color, flexShrink: 0 }} />

const Metric = ({ label, value, alert, sub }: { label: string; value: string | number; alert?: boolean; sub?: string }) => (
  <div style={{ padding: '12px 14px', background: 'var(--bg1)', borderRadius: 8, border: alert ? '1px solid #f6465d' : '1px solid var(--border1, #2a2a3a)', flex: 1, minWidth: 100 }}>
    <div style={{ fontSize: 9, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text3)', marginBottom: 3 }}>{label}</div>
    <div style={{ fontSize: 18, fontWeight: 700, color: alert ? '#f6465d' : 'var(--text0)' }}>{value}</div>
    {sub && <div style={{ fontSize: 9, color: alert ? '#f6465d80' : 'var(--text3)', marginTop: 1 }}>{sub}</div>}
  </div>
)

type Tab = 'overview' | 'jobs' | 'events'

export default function AgentPipeline() {
  const { data, error } = useApi<PipelineData>('/api/v2/agent-pipeline?limit=50', 30000)
  const { data: healthData } = useApi<SystemHealth>('/api/v2/system-health', 60000)
  const { data: agentHealthData } = useApi<AgentHealthData>('/api/v2/agent-health', 60000)
  const [tab, setTab] = useState<Tab>('overview')
  const [jobLimit, setJobLimit] = useState(30)
  const nav = useNavigate()

  if (error) return <div style={{ color: '#f6465d', padding: 40, fontSize: 12 }}>Error loading pipeline: {error}</div>
  if (!data) return <div style={{ color: 'var(--text3)', padding: 40, fontSize: 12 }}>Loading agent pipeline...</div>

  const { jobs, results, handoffs, events, summary } = data
  const llm = healthData?.llm
  const agents = agentHealthData?.agents || []
  const budgetPct = llm ? (llm.daily_spend / llm.daily_budget) * 100 : 0
  const staleAgents = agents.filter(a => { const ms = a.last_run ? Date.now() - new Date(a.last_run.replace(/\s+[A-Z]{2,4}$/, '')).getTime() : Infinity; return ms > 3 * 86400000 })
  const urgentEvents = events.filter(e => e.event_type === 'STOP_TRIGGERED')
  const failedJobs = jobs.filter(j => j.status === 'failed')

  // Group results by symbol for consensus view
  const resultsBySymbol = new Map<string, Result[]>()
  for (const r of results) {
    const arr = resultsBySymbol.get(r.symbol) || []
    arr.push(r)
    resultsBySymbol.set(r.symbol, arr)
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <PageHeader title="Agent Pipeline" subtitle={`${summary.total_24h} jobs (24h) · ${results.length} results · ${handoffs.length} handoffs`} />

      {/* ═══ URGENT: Stop triggers ═══ */}
      {urgentEvents.length > 0 && (
        <div style={{ padding: '10px 14px', background: 'rgba(246,70,93,.08)', border: '1px solid rgba(246,70,93,.3)', borderRadius: 8, display: 'flex', alignItems: 'center', gap: 10 }}>
          <Dot color="#f6465d" />
          <span style={{ fontSize: 12, fontWeight: 600, color: '#f6465d', flex: 1 }}>
            {urgentEvents.length} stop(s) triggered: {urgentEvents.map(e => e.symbol).join(', ')}
          </span>
          <span onClick={() => nav('/risk')} style={{ fontSize: 10, color: '#f6465d', cursor: 'pointer', opacity: 0.7 }}>Review →</span>
        </div>
      )}

      {/* ═══ METRICS STRIP ═══ */}
      <div style={{ display: 'flex', gap: 8 }}>
        <Metric label="Queued" value={summary.queued} alert={summary.queued > 200} sub={summary.queued > 100 ? 'Backlog building' : 'Normal'} />
        <Metric label="Processing" value={summary.processing} sub="Active now" />
        <Metric label="Completed" value={summary.completed} sub="Last 24h" />
        <Metric label="Failed" value={summary.failed} alert={summary.failed > 10} sub={failedJobs.length > 0 ? `${failedJobs.length} need review` : 'All clear'} />
        <Metric label="Events" value={summary.events_pending + summary.events_done} sub={`${summary.events_pending} pending`} />
      </div>

      {/* ═══ LLM BUDGET + AGENT HEALTH STRIP ═══ */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 2fr', gap: 10 }}>
        {/* LLM Budget */}
        <Card compact>
          <div style={{ fontSize: 9, fontWeight: 700, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '.5px', marginBottom: 6 }}>LLM Budget</div>
          {llm ? (
            <>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                <span style={{ fontSize: 14, fontWeight: 700, color: budgetPct > 80 ? '#f6465d' : 'var(--text0)' }}>
                  ${llm.daily_spend.toFixed(2)} / ${llm.daily_budget.toFixed(2)}
                </span>
                <div style={{ flex: 1, height: 5, background: 'rgba(255,255,255,.06)', borderRadius: 3, overflow: 'hidden' }}>
                  <div style={{ width: `${Math.min(budgetPct, 100)}%`, height: '100%', background: budgetPct > 80 ? '#f6465d' : '#4a90f4', borderRadius: 3 }} />
                </div>
                <span style={{ fontSize: 9, color: 'var(--text3)' }}>{budgetPct.toFixed(0)}%</span>
              </div>
              <div style={{ display: 'flex', gap: 10, fontSize: 9, color: 'var(--text2)' }}>
                <span>Local {llm.local.model || 'ollama'} {llm.local.available ? <span style={{ color: '#0ecb81' }}>● ON</span> : <span style={{ color: '#f0b90b' }}>● OFF</span>}</span>
                <span>Claude {llm.claude.available ? '✓' : '✗'}</span>
                <span>Grok {llm.grok.available ? '✓' : '✗'}</span>
                <span>OpenAI {llm.openai.available ? '✓' : '✗'}</span>
              </div>
            </>
          ) : <div style={{ fontSize: 10, color: 'var(--text3)' }}>Loading...</div>}
        </Card>

        {/* Agent Health */}
        <Card compact style={staleAgents.length > 0 ? { border: '1px solid rgba(246,70,93,.3)' } : undefined}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
            <span style={{ fontSize: 9, fontWeight: 700, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '.5px' }}>Agent Health</span>
            {staleAgents.length > 0 && <span style={{ fontSize: 9, color: '#f6465d' }}>{staleAgents.length} stale</span>}
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            {agents.map(a => {
              const ms = a.last_run ? Date.now() - new Date(a.last_run.replace(/\s+[A-Z]{2,4}$/, '')).getTime() : Infinity
              const stale = ms > 3 * 86400000
              return (
                <div key={a.agent} onClick={() => nav(`/agent-dashboard/${a.agent}`)}
                  style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '4px 8px', borderRadius: 5, cursor: 'pointer',
                    background: stale ? 'rgba(246,70,93,.06)' : 'transparent', border: `1px solid ${stale ? 'rgba(246,70,93,.2)' : 'var(--border-subtle)'}` }}>
                  <Dot color={stale ? '#f6465d' : a.avg_confidence >= 0.65 ? '#0ecb81' : '#f0b90b'} />
                  <span style={{ fontSize: 10, fontWeight: 600, color: stale ? '#f6465d' : 'var(--text0)' }}>{a.agent}</span>
                  <span style={{ fontSize: 8, color: 'var(--text3)' }}>{a.last_run ? timeAgo(a.last_run) : 'never'}</span>
                </div>
              )
            })}
          </div>
        </Card>
      </div>

      {/* ═══ TAB SWITCHER ═══ */}
      <div style={{ display: 'flex', gap: 4, borderBottom: '1px solid var(--border1, #2a2a3a)', paddingBottom: 0 }}>
        {([['overview', 'Intelligence'], ['jobs', `Jobs (${jobs.length})`], ['events', `Events (${events.length})`]] as [Tab, string][]).map(([t, label]) => (
          <button key={t} onClick={() => setTab(t)} style={{ padding: '6px 14px', fontSize: 11, fontWeight: tab === t ? 700 : 400,
            color: tab === t ? 'var(--accent, #4a90f4)' : 'var(--text3)', background: 'transparent', border: 'none',
            borderBottom: tab === t ? '2px solid var(--accent, #4a90f4)' : '2px solid transparent', cursor: 'pointer', fontFamily: 'monospace' }}>
            {label}
          </button>
        ))}
      </div>

      {/* ═══ TAB: INTELLIGENCE (default) ═══ */}
      {tab === 'overview' && (
        <>
          {/* Agent Consensus by Symbol */}
          <Card>
            <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', marginBottom: 10 }}>Agent Intelligence — Recent Analyses</div>
            {resultsBySymbol.size === 0 ? (
              <div style={{ fontSize: 11, color: 'var(--text3)' }}>No results in window</div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                {Array.from(resultsBySymbol.entries()).slice(0, 15).map(([sym, recs]) => {
                  const consensus = recs.reduce((a, r) => a + (recColor(r.recommendation) === '#f6465d' ? -1 : recColor(r.recommendation) === '#0ecb81' ? 1 : 0), 0)
                  const avgConf = recs.reduce((a, r) => a + r.confidence, 0) / recs.length
                  return (
                    <div key={sym} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '5px 8px', borderBottom: '1px solid var(--border-subtle)', fontSize: 11 }}>
                      <span style={{ fontWeight: 700, color: 'var(--text0)', minWidth: 55 }}>{sym}</span>
                      <div style={{ display: 'flex', gap: 4, flex: 1 }}>
                        {recs.map((r, i) => (
                          <span key={i} style={{ display: 'inline-flex', alignItems: 'center', gap: 3, padding: '1px 6px', borderRadius: 4,
                            background: recColor(r.recommendation) === '#f6465d' ? 'rgba(246,70,93,.1)' : recColor(r.recommendation) === '#0ecb81' ? 'rgba(14,203,129,.1)' : 'rgba(255,255,255,.04)',
                            fontSize: 9 }}>
                            <span style={{ color: 'var(--text3)' }}>{r.agent.replace('_agent', '')}</span>
                            <span style={{ color: recColor(r.recommendation), fontWeight: 600 }}>{r.recommendation}</span>
                          </span>
                        ))}
                      </div>
                      <span style={{ fontSize: 9, color: avgConf >= 70 ? '#0ecb81' : '#f0b90b', fontWeight: 600 }}>{avgConf.toFixed(0)}%</span>
                      <span style={{ fontSize: 8, color: 'var(--text3)' }}>{timeAgo(recs[0].created_at)}</span>
                    </div>
                  )
                })}
              </div>
            )}
          </Card>

          {/* Two-column: Handoffs + Events summary */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
            <Card>
              <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Handoffs & Escalations ({handoffs.length})</div>
              {handoffs.length === 0 ? <div style={{ fontSize: 10, color: 'var(--text3)' }}>No handoffs in 24h</div> : (
                <div style={{ maxHeight: 200, overflow: 'auto' }}>
                  {handoffs.slice(0, 10).map((h, i) => (
                    <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '4px 0', borderBottom: '1px solid var(--border-subtle)', fontSize: 10 }}>
                      <span style={{ fontWeight: 600, color: 'var(--text0)', minWidth: 40 }}>{h.symbol}</span>
                      <AgentChip name={h.from_agent} /> <span style={{ color: 'var(--text3)' }}>→</span> <AgentChip name={h.to_agent} />
                      {h.escalated && <StatusBadge status="red" label="ESC" />}
                      <span style={{ marginLeft: 'auto', fontSize: 8, color: 'var(--text3)' }}>{timeAgo(h.created_at)}</span>
                    </div>
                  ))}
                </div>
              )}
            </Card>

            <Card>
              <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Active Events ({events.filter(e => e.status !== 'done').length})</div>
              {events.filter(e => e.status !== 'done').length === 0 ? <div style={{ fontSize: 10, color: 'var(--text3)' }}>All events processed</div> : (
                <div style={{ maxHeight: 200, overflow: 'auto' }}>
                  {events.filter(e => e.status !== 'done').slice(0, 10).map(e => (
                    <div key={e.id} style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '4px 0', borderBottom: '1px solid var(--border-subtle)', fontSize: 10 }}>
                      {e.event_type === 'STOP_TRIGGERED' && <Dot color="#f6465d" />}
                      <span style={{ color: e.event_type === 'STOP_TRIGGERED' ? '#f6465d' : 'var(--text1)', fontWeight: 500, fontSize: 9 }}>{e.event_type.replace(/_/g, ' ')}</span>
                      <span style={{ fontWeight: 600, color: 'var(--text0)' }}>{e.symbol}</span>
                      <StatusBadge status={sKey(e.status)} label={e.status} />
                      <span style={{ marginLeft: 'auto', fontSize: 8, color: 'var(--text3)' }}>{timeAgo(e.created_at)}</span>
                    </div>
                  ))}
                </div>
              )}
            </Card>
          </div>
        </>
      )}

      {/* ═══ TAB: JOBS ═══ */}
      {tab === 'jobs' && (
        <Card>
          <div style={{ display: 'flex', gap: 6, marginBottom: 10 }}>
            {['all', 'queued', 'processing', 'completed', 'failed'].map(f => (
              <ActionButton key={f} onClick={() => setJobLimit(30)} variant="ghost" size="sm"
                style={f === 'all' ? { borderColor: 'var(--accent)' } : undefined}>
                {f} ({f === 'all' ? jobs.length : jobs.filter(j => j.status === f).length})
              </ActionButton>
            ))}
          </div>
          <div style={{ overflow: 'auto', maxHeight: 500 }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 10 }}>
              <thead>
                <tr>{['Symbol', 'Agent', 'Type', 'Status', 'Pri', 'Source', 'Age', 'Duration'].map(h => (
                  <th key={h} style={{ padding: '5px 8px', textAlign: 'left', color: 'var(--text3)', fontSize: 9, fontWeight: 600, borderBottom: '1px solid var(--border)', background: 'var(--bg1)', position: 'sticky', top: 0, zIndex: 1 }}>{h}</th>
                ))}</tr>
              </thead>
              <tbody>
                {jobs.slice(0, jobLimit).map(j => (
                  <tr key={j.id}>
                    <td style={{ padding: '4px 8px', borderBottom: '1px solid var(--border-subtle)', fontWeight: 600, color: 'var(--text0)' }}>{j.symbol}</td>
                    <td style={{ padding: '4px 8px', borderBottom: '1px solid var(--border-subtle)' }}><AgentChip name={j.requested_agent} /></td>
                    <td style={{ padding: '4px 8px', borderBottom: '1px solid var(--border-subtle)', color: 'var(--text2)' }}>{j.request_type}</td>
                    <td style={{ padding: '4px 8px', borderBottom: '1px solid var(--border-subtle)' }}><StatusBadge status={sKey(j.status)} label={j.status} /></td>
                    <td style={{ padding: '4px 8px', borderBottom: '1px solid var(--border-subtle)' }}><span style={{ color: priColor(j.priority), fontWeight: 600 }}>{j.priority}</span></td>
                    <td style={{ padding: '4px 8px', borderBottom: '1px solid var(--border-subtle)', color: 'var(--text3)', fontSize: 9 }}>{j.submitted_from}</td>
                    <td style={{ padding: '4px 8px', borderBottom: '1px solid var(--border-subtle)', color: 'var(--text2)', fontSize: 9 }}>{timeAgo(j.created_at)}</td>
                    <td style={{ padding: '4px 8px', borderBottom: '1px solid var(--border-subtle)', color: 'var(--text3)', fontSize: 9 }}>
                      {j.started_at && j.completed_at ? (() => { const ms = new Date(j.completed_at!).getTime() - new Date(j.started_at!).getTime(); return ms > 60000 ? `${(ms/60000).toFixed(0)}m` : `${(ms/1000).toFixed(0)}s` })() : j.started_at ? 'running...' : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {jobs.length > jobLimit && (
            <div style={{ textAlign: 'center', marginTop: 8 }}>
              <ActionButton onClick={() => setJobLimit(l => l + 30)} variant="ghost" size="sm">Show more ({jobs.length - jobLimit} remaining)</ActionButton>
            </div>
          )}
        </Card>
      )}

      {/* ═══ TAB: EVENTS ═══ */}
      {tab === 'events' && (
        <Card>
          <div style={{ overflow: 'auto', maxHeight: 500 }}>
            {events.length === 0 ? <div style={{ padding: 14, color: 'var(--text3)', fontSize: 11 }}>No events</div> : (
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 10 }}>
                <thead>
                  <tr>{['Type', 'Symbol', 'Priority', 'Status', 'Agents', 'Age'].map(h => (
                    <th key={h} style={{ padding: '5px 8px', textAlign: 'left', color: 'var(--text3)', fontSize: 9, fontWeight: 600, borderBottom: '1px solid var(--border)', background: 'var(--bg1)', position: 'sticky', top: 0, zIndex: 1 }}>{h}</th>
                  ))}</tr>
                </thead>
                <tbody>
                  {events.map(e => (
                    <tr key={e.id}>
                      <td style={{ padding: '4px 8px', borderBottom: '1px solid var(--border-subtle)', color: e.event_type === 'STOP_TRIGGERED' ? '#f6465d' : 'var(--text1)' }}>
                        {e.event_type === 'STOP_TRIGGERED' && <span style={{ marginRight: 4 }}>●</span>}{e.event_type}
                      </td>
                      <td style={{ padding: '4px 8px', borderBottom: '1px solid var(--border-subtle)', fontWeight: 600, color: 'var(--text0)' }}>{e.symbol}</td>
                      <td style={{ padding: '4px 8px', borderBottom: '1px solid var(--border-subtle)', color: priColor(e.priority) }}>{e.priority >= 8 ? 'urgent' : e.priority >= 5 ? 'high' : 'normal'}</td>
                      <td style={{ padding: '4px 8px', borderBottom: '1px solid var(--border-subtle)' }}><StatusBadge status={sKey(e.status)} label={e.status} /></td>
                      <td style={{ padding: '4px 8px', borderBottom: '1px solid var(--border-subtle)', color: 'var(--text3)', fontSize: 9 }}>{e.agents_to_notify}</td>
                      <td style={{ padding: '4px 8px', borderBottom: '1px solid var(--border-subtle)', color: 'var(--text2)', fontSize: 9 }}>{timeAgo(e.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </Card>
      )}
    </div>
  )
}
