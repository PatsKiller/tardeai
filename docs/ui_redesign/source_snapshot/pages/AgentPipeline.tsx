import { useState } from 'react'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import SectionHeader from '../components/SectionHeader'
import Tooltip from '../components/Tooltip'
import { useApi } from '../hooks/useApi'
import { timeAgo } from '../lib/format'

interface Job { id: number; symbol: string; requested_agent: string; request_type: string; status: string; priority: number; submitted_from: string; created_at: string; started_at: string | null; completed_at: string | null; payload_text: string | null }
interface RagSource { source_type: string; title: string; rag_score: number }
interface Result { symbol: string; agent: string; recommendation: string; confidence: number; summary: string; created_at: string; model_used: string; status: string; rag_sources_used: RagSource[] | number | null; peer_notes_symbols: string | null }
interface Handoff { symbol: string; from_agent: string; to_agent: string; reason: string; escalated: boolean; created_at: string }
interface Event { id: number; event_type: string; symbol: string; priority: number; status: string; agents_to_notify: string; trigger_text: string | null; created_at: string; processed_at: string | null }
interface Proposal { symbol: string; action: string; strategy_type: string; confidence: number; status: string; created_at: string }
interface Debate { symbol: string; consensus_recommendation: string; consensus_score: number; participants: string; created_at: string; provider: string }
interface Summary { queued: number; processing: number; completed: number; failed: number; total_24h: number; events_pending: number; events_done: number; handoffs_24h: number; analyses_24h: number; proposals_pending: number; debates_24h: number }
interface PipelineData { jobs: Job[]; results: Result[]; handoffs: Handoff[]; events: Event[]; proposals: Proposal[]; debates: Debate[]; summary: Summary }

interface LlmProvider { available: boolean; model?: string }
interface SystemHealth { llm: { local: LlmProvider; grok: LlmProvider; claude: LlmProvider; openai: LlmProvider; daily_spend: number; daily_budget: number; budget_remaining: number } }

interface AgentHealthEntry { agent: string; total_analyses: number; avg_confidence: number; last_run: string; low_conf_count: number }
interface AgentHealthData { agents: AgentHealthEntry[] }

const statusColor = (s: string) => s === 'completed' || s === 'done' ? 'var(--green)' : s === 'processing' || s === 'running' ? 'var(--accent)' : s === 'queued' ? 'var(--amber)' : s === 'failed' ? 'var(--red)' : 'var(--text3)'

function Badge({ label, color }: { label: string; color: string }) {
  return <span style={{ fontSize: 8, fontWeight: 700, padding: '1px 5px', borderRadius: 3, color, background: `color-mix(in srgb, ${color} 15%, transparent)` }}>{label}</span>
}

function parsePeerNotes(raw: string | null): string[] {
  if (!raw || raw === '[]' || raw === 'null') return []
  try {
    const parsed = JSON.parse(raw.replace(/'/g, '"'))
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

function getRagDisplay(rag: RagSource[] | number | null): { text: string; color: string; tooltipContent: React.ReactNode } {
  if (Array.isArray(rag)) {
    if (rag.length === 0) return { text: '\u2014', color: 'var(--text3)', tooltipContent: 'No RAG sources' }
    return {
      text: String(rag.length),
      color: rag.length >= 5 ? 'var(--green)' : 'var(--text1)',
      tooltipContent: (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 2, whiteSpace: 'pre' }}>
          {rag.map((s, i) => (
            <div key={i} style={{ fontSize: 9 }}>
              <span style={{ color: 'var(--accent)' }}>{s.source_type}</span>
              <span style={{ color: 'var(--text3)' }}> {s.title}</span>
            </div>
          ))}
        </div>
      ),
    }
  }
  if (typeof rag === 'number') {
    if (rag === 0) return { text: '\u2014', color: 'var(--text3)', tooltipContent: 'Pre-RAG result' }
    return {
      text: String(rag),
      color: rag >= 5 ? 'var(--green)' : 'var(--text1)',
      tooltipContent: 'Pre-RAG result',
    }
  }
  return { text: '\u2014', color: 'var(--text3)', tooltipContent: 'Pre-RAG result' }
}

function getTierBadge(job: Job): React.ReactNode {
  if (job.submitted_from === 'event_router') return <Badge label="EVENT" color="var(--accent)" />
  if (job.submitted_from === 'command_center' && job.priority === 1) return <Badge label="HOLDINGS" color="var(--green)" />
  if (job.submitted_from === 'command_center' && job.priority === 2) return <Badge label="SCREENER" color="var(--text3)" />
  return <span style={{ fontSize: 8, color: 'var(--text3)' }}>{job.submitted_from}</span>
}

function getErrorBadge(payloadText: string | null): { label: string; color: string } {
  const lower = (payloadText || '').toLowerCase()
  if (lower.includes('budget')) return { label: 'BUDGET', color: 'var(--red)' }
  if (lower.includes('timeout')) return { label: 'TIMEOUT', color: 'var(--amber)' }
  return { label: 'ERROR', color: 'var(--text3)' }
}

function getEventTypeStyle(eventType: string): { color: string; dot: boolean } {
  if (eventType === 'STOP_TRIGGERED') return { color: 'var(--red)', dot: true }
  if (eventType === 'CONTENT_GAP') return { color: 'var(--amber)', dot: false }
  if (eventType === 'PORTFOLIO_FRESH_NEEDED') return { color: 'var(--accent)', dot: false }
  return { color: 'var(--text1)', dot: false }
}

function parseContentGapSymbol(symbol: string, triggerText: string | null): string {
  // Try to parse trigger_text JSON for category info
  if (triggerText) {
    try {
      const parsed = JSON.parse(triggerText)
      if (parsed?.trigger_data?.category) {
        const cat = parsed.trigger_data.category
        const agent = parsed?.trigger_data?.agent || 'agent'
        const articles = parsed?.trigger_data?.articles ?? 0
        const days = parsed?.trigger_data?.days ?? 30
        return `${cat} \u2192 ${agent} (${articles} articles/${days}d)`
      }
    } catch { /* not JSON, fall through */ }
  }
  // Fallback: parse CATEGORY:xxx symbol format
  if (symbol && symbol.startsWith('CATEGORY:')) {
    return symbol.replace('CATEGORY:', '')
  }
  return symbol
}

type JobFilter = 'all' | 'completed' | 'failed' | 'queued'

export default function AgentPipeline() {
  const { data, error } = useApi<PipelineData>('/api/v2/agent-pipeline?limit=50', 30000)
  const { data: healthData } = useApi<SystemHealth>('/api/v2/system-health', 60000)
  const { data: agentHealthData } = useApi<AgentHealthData>('/api/v2/agent-health', 60000)
  const [jobLimit, setJobLimit] = useState(50)
  const [jobFilter, setJobFilter] = useState<JobFilter>('all')
  const [showFailed, setShowFailed] = useState(false)

  if (error) return <div style={{ color: 'var(--red)', padding: 40 }}>Error loading pipeline: {error}</div>
  if (!data) return <div style={{ color: 'var(--text3)', padding: 40 }}>Loading agent pipeline...</div>

  const { jobs, results, handoffs, events, proposals, debates, summary } = data

  const filteredJobs = jobFilter === 'all' ? jobs : jobs.filter(j => j.status === jobFilter)
  const failedJobs = jobs.filter(j => j.status === 'failed')

  // LLM budget calculations
  const llm = healthData?.llm
  const budgetPct = llm ? (llm.daily_spend / llm.daily_budget) * 100 : 0
  const localOffline = llm && !llm.local.available
  const budgetCritical = budgetPct > 80

  // Agent health: merge API agents with static aegis/iris
  const agentCards = agentHealthData?.agents || []
  const now = Date.now()

  const thStyle = { padding: '5px 8px', textAlign: 'left' as const, color: 'var(--text3)', fontSize: 9, fontWeight: 600, borderBottom: '1px solid var(--border)', position: 'sticky' as const, top: 0, background: 'var(--bg1)', zIndex: 1 }
  const tdStyle = { padding: '4px 8px', borderBottom: '1px solid var(--border-subtle)' }

  return (
    <>
      <PageHeader title="Agent Pipeline" subtitle={`${summary.total_24h} jobs (24h) \u00b7 ${results.length} results \u00b7 ${handoffs.length} handoffs \u00b7 ${events.length} events`} />

      {/* A. LLM Budget Tile */}
      {llm && (
        <Card compact>
          <div style={{ display: 'flex', alignItems: 'center', gap: 16, flexWrap: 'wrap' }}>
            <span style={{ fontSize: 9, fontWeight: 700, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '.5px' }}>LLM Budget</span>
            <span style={{ fontSize: 13, fontWeight: 700, color: budgetCritical ? 'var(--red)' : 'var(--text0)' }}>
              ${llm.daily_spend.toFixed(2)} / ${llm.daily_budget.toFixed(2)} today
            </span>
            <div style={{ flex: '0 0 120px', height: 6, background: 'var(--bg1)', borderRadius: 3, overflow: 'hidden' }}>
              <div style={{ width: `${Math.min(budgetPct, 100)}%`, height: '100%', background: budgetCritical ? 'var(--red)' : 'var(--accent)', borderRadius: 3, transition: 'width 300ms ease' }} />
            </div>
            <span style={{ fontSize: 9, color: 'var(--text3)' }}>{budgetPct.toFixed(1)}%</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 6, flexWrap: 'wrap' }}>
            <span style={{ fontSize: 9, color: 'var(--text2)' }}>
              Local {llm.local.model || 'ollama'} {llm.local.available
                ? <span style={{ color: 'var(--green)' }}>{'\u25cf'} ONLINE</span>
                : <span style={{ color: 'var(--amber)' }}>{'\u25cf'} OFFLINE</span>}
            </span>
            <span style={{ fontSize: 9, color: 'var(--text2)' }}>Claude {llm.claude.available ? <span style={{ color: 'var(--green)' }}>{'\u2713'}</span> : <span style={{ color: 'var(--red)' }}>{'\u2717'}</span>}</span>
            <span style={{ fontSize: 9, color: 'var(--text2)' }}>OpenAI {llm.openai.available ? <span style={{ color: 'var(--green)' }}>{'\u2713'}</span> : <span style={{ color: 'var(--red)' }}>{'\u2717'}</span>}</span>
            <span style={{ fontSize: 9, color: 'var(--text2)' }}>Grok {llm.grok.available ? <span style={{ color: 'var(--green)' }}>{'\u2713'}</span> : <span style={{ color: 'var(--red)' }}>{'\u2717'}</span>}</span>
            <span style={{ fontSize: 8, color: 'var(--text3)', marginLeft: 'auto' }}>Routing: local {'\u2192'} grok {'\u2192'} claude {'\u2192'} openai</span>
          </div>
          {localOffline && (
            <div style={{ fontSize: 9, color: 'var(--amber)', marginTop: 4, display: 'flex', alignItems: 'center', gap: 4 }}>
              {'\u26a0'} Local Ollama offline — cloud fallback active
            </div>
          )}
          {budgetCritical && (
            <div style={{ fontSize: 9, color: 'var(--red)', marginTop: 4, display: 'flex', alignItems: 'center', gap: 4 }}>
              {'\u26a0'} Budget nearly exhausted — failures likely
            </div>
          )}
        </Card>
      )}

      {/* B. Agent Health Cards */}
      {agentHealthData && (
        <div style={{ marginTop: 12, marginBottom: 4 }}>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            {agentCards.map(a => {
              const lastRunMs = a.last_run ? now - new Date(a.last_run.replace(/\s+[A-Z]{2,4}$/, '').trim()).getTime() : Infinity
              const stale = lastRunMs > 3 * 24 * 3600000
              const underused = a.total_analyses < 10
              const borderColor = stale ? 'var(--red)' : underused ? 'var(--amber)' : 'var(--border-subtle)'
              return (
                <div key={a.agent} style={{ padding: '6px 10px', background: 'var(--bg2)', border: `1px solid ${borderColor}`, borderRadius: 8, fontSize: 10 }}>
                  <span style={{ fontWeight: 700, color: 'var(--accent)' }}>{a.agent}</span>
                  <span style={{ color: 'var(--text3)', margin: '0 4px' }}>:</span>
                  <span style={{ color: 'var(--text2)' }}>{a.total_analyses} analyses</span>
                  <span style={{ color: 'var(--text3)', margin: '0 4px' }}>|</span>
                  <span style={{ color: a.avg_confidence >= 0.7 ? 'var(--green)' : 'var(--amber)' }}>conf:{a.avg_confidence.toFixed(2)}</span>
                  <span style={{ color: 'var(--text3)', margin: '0 4px' }}>|</span>
                  <span style={{ color: stale ? 'var(--red)' : 'var(--text2)', fontSize: 9 }}>{a.last_run ? timeAgo(a.last_run) : 'never'}</span>
                </div>
              )
            })}
            {/* Static aegis card */}
            <div style={{ padding: '6px 10px', background: 'var(--bg2)', border: '1px solid var(--border-subtle)', borderRadius: 8, fontSize: 10 }}>
              <span style={{ fontWeight: 700, color: 'var(--accent)' }}>aegis</span>
              <span style={{ color: 'var(--text3)', margin: '0 4px' }}>:</span>
              <span style={{ color: 'var(--text2)' }}>nightly synthesis</span>
            </div>
            {/* Static iris card */}
            <div style={{ padding: '6px 10px', background: 'var(--bg2)', border: '1px solid var(--border-subtle)', borderRadius: 8, fontSize: 10 }}>
              <span style={{ fontWeight: 700, color: 'var(--accent)' }}>iris</span>
              <span style={{ color: 'var(--text3)', margin: '0 4px' }}>:</span>
              <span style={{ color: 'var(--text2)' }}>library audit</span>
            </div>
          </div>
        </div>
      )}

      {/* Summary badges */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 16, marginTop: 12, flexWrap: 'wrap' }}>
        {[
          { label: 'Queued', val: summary.queued, color: 'var(--amber)' },
          { label: 'Processing', val: summary.processing, color: 'var(--accent)' },
          { label: 'Completed', val: summary.completed, color: 'var(--green)' },
          { label: 'Failed', val: summary.failed, color: 'var(--red)' },
        ].map(s => (
          <div key={s.label} style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '6px 12px', background: 'var(--bg2)', border: '1px solid var(--border-subtle)', borderRadius: 8 }}>
            <div style={{ width: 8, height: 8, borderRadius: 999, background: s.color }} />
            <span style={{ fontSize: 10, color: 'var(--text2)' }}>{s.label}</span>
            <span style={{ fontSize: 13, fontWeight: 700, color: s.color }}>{s.val}</span>
          </div>
        ))}
      </div>

      {/* F. Filter chips */}
      <SectionHeader title="Agent Jobs (24h)" count={filteredJobs.length} />
      <div style={{ display: 'flex', gap: 6, marginBottom: 8 }}>
        {(['all', 'completed', 'failed', 'queued'] as JobFilter[]).map(f => (
          <button
            key={f}
            onClick={() => { setJobFilter(f); setJobLimit(50) }}
            style={{
              fontSize: 9, fontWeight: 600, padding: '3px 10px', borderRadius: 4, cursor: 'pointer',
              border: `1px solid ${jobFilter === f ? 'var(--accent)' : 'var(--border)'}`,
              background: jobFilter === f ? 'rgba(74,144,244,0.15)' : 'var(--bg3)',
              color: jobFilter === f ? 'var(--accent)' : 'var(--text3)',
              textTransform: 'capitalize',
            }}
          >
            {f}
          </button>
        ))}
      </div>

      {/* Jobs table */}
      <Card>
        <div style={{ overflow: 'auto', maxHeight: 400 }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 10 }}>
            <thead>
              <tr style={{ background: 'var(--bg1)' }}>
                {['Symbol', 'Agent', 'Type', 'Status', 'Priority', 'Source', 'Tier', 'Created', 'Duration'].map(h => (
                  <th key={h} style={thStyle}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filteredJobs.slice(0, jobLimit).map(j => (
                <tr key={j.id}>
                  <td style={{ ...tdStyle, fontWeight: 600, color: 'var(--text0)' }}>{j.symbol}</td>
                  <td style={{ ...tdStyle, color: 'var(--accent)' }}>{j.requested_agent}</td>
                  <td style={{ ...tdStyle, color: 'var(--text2)' }}>{j.request_type}</td>
                  <td style={tdStyle}><Badge label={j.status} color={statusColor(j.status)} /></td>
                  <td style={{ ...tdStyle, color: 'var(--text2)' }}>{j.priority}</td>
                  <td style={{ ...tdStyle, color: 'var(--text3)', fontSize: 9 }}>{j.submitted_from}</td>
                  <td style={tdStyle}>{getTierBadge(j)}</td>
                  <td style={{ ...tdStyle, color: 'var(--text2)', fontSize: 9 }}>{timeAgo(j.created_at)}</td>
                  <td style={{ ...tdStyle, color: 'var(--text3)', fontSize: 9 }}>
                    {j.started_at && j.completed_at ? (() => { const ms = new Date(j.completed_at!).getTime() - new Date(j.started_at!).getTime(); return ms > 60000 ? `${(ms/60000).toFixed(0)}m` : `${(ms/1000).toFixed(0)}s` })() : j.started_at ? 'running...' : '\u2014'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {filteredJobs.length > jobLimit && (
          <div style={{ textAlign: 'center', marginTop: 8 }}>
            <button onClick={() => setJobLimit(l => l + 50)} style={{ fontSize: 9, padding: '4px 12px', border: '1px solid var(--border)', borderRadius: 4, background: 'var(--bg3)', color: 'var(--accent)', cursor: 'pointer' }}>Show more ({filteredJobs.length - jobLimit} remaining)</button>
          </div>
        )}
      </Card>

      {/* F. Failed Jobs collapsible section */}
      {failedJobs.length > 0 && (
        <>
          <div
            style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 18, marginBottom: 10, cursor: 'pointer', userSelect: 'none' }}
            onClick={() => setShowFailed(v => !v)}
          >
            <span style={{ fontSize: 10, color: 'var(--text3)', transform: showFailed ? 'rotate(90deg)' : 'rotate(0deg)', transition: 'transform 150ms' }}>{'\u25b6'}</span>
            <h2 style={{ fontFamily: 'var(--sans)', fontSize: 12, fontWeight: 700, color: 'var(--red)', margin: 0, textTransform: 'uppercase', letterSpacing: '.5px' }}>Failed Jobs ({failedJobs.length})</h2>
            <div style={{ flex: 1, height: 1, background: 'var(--border)', marginLeft: 4 }} />
          </div>
          {showFailed && (
            <Card>
              <div style={{ overflow: 'auto', maxHeight: 250 }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 10 }}>
                  <thead>
                    <tr style={{ background: 'var(--bg1)' }}>
                      {['Symbol', 'Agent', 'Time', 'Error'].map(h => (
                        <th key={h} style={thStyle}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {failedJobs.map(j => {
                      const err = getErrorBadge(j.payload_text)
                      return (
                        <tr key={j.id}>
                          <td style={{ ...tdStyle, fontWeight: 600, color: 'var(--text0)' }}>{j.symbol}</td>
                          <td style={{ ...tdStyle, color: 'var(--accent)' }}>{j.requested_agent}</td>
                          <td style={{ ...tdStyle, color: 'var(--text2)', fontSize: 9 }}>{timeAgo(j.created_at)}</td>
                          <td style={tdStyle}><Badge label={err.label} color={err.color} /></td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
              <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 6, padding: '2px 0' }}>
                Budget failures retry at midnight reset
              </div>
            </Card>
          )}
        </>
      )}

      {/* Results */}
      <SectionHeader title="Agent Results" count={results.length} />
      <Card>
        <div style={{ overflow: 'auto', maxHeight: 350 }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 10 }}>
            <thead>
              <tr style={{ background: 'var(--bg1)' }}>
                {['Symbol', 'Agent', 'Recommendation', 'Confidence', 'Model', 'RAG', 'Peers', 'Age'].map(h => (
                  <th key={h} style={thStyle}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {results.map((r, i) => {
                const rag = getRagDisplay(r.rag_sources_used)
                const peers = parsePeerNotes(r.peer_notes_symbols)
                return (
                  <tr key={`${r.symbol}-${r.agent}-${i}`}>
                    <td style={{ ...tdStyle, fontWeight: 600, color: 'var(--text0)' }}>{r.symbol}</td>
                    <td style={{ ...tdStyle, color: 'var(--accent)' }}>{r.agent}</td>
                    <td style={{ ...tdStyle, color: r.recommendation?.toLowerCase().includes('buy') ? 'var(--green)' : r.recommendation?.toLowerCase().includes('sell') ? 'var(--red)' : 'var(--text1)' }}>{r.recommendation}</td>
                    <td style={{ ...tdStyle, color: r.confidence >= 70 ? 'var(--green)' : r.confidence >= 50 ? 'var(--amber)' : 'var(--text2)' }}>{r.confidence}%</td>
                    <td style={{ ...tdStyle, color: 'var(--text3)', fontSize: 9 }}>{r.model_used}</td>
                    <td style={{ ...tdStyle, fontSize: 9 }}>
                      <Tooltip content={rag.tooltipContent} position="top">
                        <span style={{ color: rag.color, cursor: 'default' }}>{rag.text}</span>
                      </Tooltip>
                    </td>
                    <td style={{ ...tdStyle, fontSize: 9 }}>
                      {peers.length === 0 ? (
                        <span style={{ color: 'var(--text3)' }}>{'\u2014'}</span>
                      ) : (
                        <Tooltip content={<div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>{peers.map((p, pi) => <span key={pi} style={{ color: 'var(--accent)', fontSize: 9 }}>{p}</span>)}</div>} position="top">
                          <span style={{ cursor: 'default' }}>
                            <Badge label={peers[0]} color="var(--accent)" />
                            {peers.length > 1 && <span style={{ fontSize: 8, color: 'var(--text3)', marginLeft: 2 }}>+{peers.length - 1}</span>}
                          </span>
                        </Tooltip>
                      )}
                    </td>
                    <td style={{ ...tdStyle, color: 'var(--text2)', fontSize: 9 }}>{timeAgo(r.created_at)}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </Card>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        {/* Handoffs */}
        <div>
          <SectionHeader title="Handoffs & Escalations" count={handoffs.length} />
          <Card>
            <div style={{ maxHeight: 250, overflow: 'auto' }}>
              {handoffs.length === 0 && <div style={{ color: 'var(--text3)', fontSize: 10, padding: 8 }}>No handoffs in last 24h</div>}
              {handoffs.map((h, i) => (
                <div key={i} style={{ display: 'flex', gap: 8, padding: '5px 0', borderBottom: '1px solid var(--border-subtle)', fontSize: 10, alignItems: 'center' }}>
                  <span style={{ fontWeight: 600, color: 'var(--text0)', width: 50 }}>{h.symbol}</span>
                  <span style={{ color: 'var(--text2)' }}>{h.from_agent}</span>
                  <span style={{ color: 'var(--text3)' }}>&rarr;</span>
                  <span style={{ color: 'var(--accent)' }}>{h.to_agent}</span>
                  {h.escalated && <Badge label="ESCALATED" color="var(--red)" />}
                  <span style={{ marginLeft: 'auto', color: 'var(--text3)', fontSize: 9 }}>{timeAgo(h.created_at)}</span>
                </div>
              ))}
            </div>
          </Card>
        </div>

        {/* H. Debates with enhanced empty state */}
        <div>
          <SectionHeader title="Agent Debates" count={debates.length} />
          <Card>
            <div style={{ maxHeight: 250, overflow: 'auto' }}>
              {debates.length === 0 && (
                <div style={{ color: 'var(--text3)', fontSize: 10, padding: 8, display: 'flex', alignItems: 'center', gap: 6 }}>
                  No debates today — all agents reached consensus
                  <Tooltip content="Debates trigger when Risk and Steph disagree on the same symbol" position="right">
                    <span style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: 14, height: 14, borderRadius: 999, border: '1px solid var(--border)', color: 'var(--text3)', fontSize: 9, cursor: 'help' }}>i</span>
                  </Tooltip>
                </div>
              )}
              {debates.map((d, i) => (
                <div key={i} style={{ display: 'flex', gap: 8, padding: '5px 0', borderBottom: '1px solid var(--border-subtle)', fontSize: 10, alignItems: 'center' }}>
                  <span style={{ fontWeight: 600, color: 'var(--text0)', width: 50 }}>{d.symbol}</span>
                  <span style={{ color: d.consensus_recommendation?.toLowerCase().includes('buy') ? 'var(--green)' : 'var(--text1)' }}>{d.consensus_recommendation}</span>
                  <span style={{ color: d.consensus_score >= 70 ? 'var(--green)' : 'var(--amber)', fontWeight: 600 }}>{d.consensus_score}%</span>
                  <span style={{ marginLeft: 'auto', color: 'var(--text3)', fontSize: 9 }}>{d.provider}</span>
                </div>
              ))}
            </div>
          </Card>
        </div>
      </div>

      {/* G. Events with enhanced styling */}
      <SectionHeader title="Event Queue" count={events.length} />
      <Card>
        <div style={{ overflow: 'auto', maxHeight: 250 }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 10 }}>
            <thead>
              <tr style={{ background: 'var(--bg1)' }}>
                {['Type', 'Symbol', 'Priority', 'Status', 'Agents', 'Created'].map(h => (
                  <th key={h} style={{ padding: '5px 8px', textAlign: 'left', color: 'var(--text3)', fontSize: 9, fontWeight: 600, borderBottom: '1px solid var(--border)' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {events.map(e => {
                const evStyle = getEventTypeStyle(e.event_type)
                const displaySymbol = e.event_type === 'CONTENT_GAP'
                  ? parseContentGapSymbol(e.symbol, e.trigger_text)
                  : e.symbol
                return (
                  <tr key={e.id}>
                    <td style={{ ...tdStyle, color: evStyle.color }}>
                      {evStyle.dot && <span style={{ color: 'var(--red)', marginRight: 4 }}>{'\u25cf'}</span>}
                      {e.event_type}
                    </td>
                    <td style={{ ...tdStyle, fontWeight: 600, color: 'var(--text0)' }}>{displaySymbol}</td>
                    <td style={{ ...tdStyle, color: e.priority >= 8 ? 'var(--red)' : e.priority >= 5 ? 'var(--amber)' : 'var(--text2)' }}>{e.priority}</td>
                    <td style={tdStyle}><Badge label={e.status} color={statusColor(e.status)} /></td>
                    <td style={{ ...tdStyle, color: 'var(--text3)', fontSize: 9 }}>{e.agents_to_notify}</td>
                    <td style={{ ...tdStyle, color: 'var(--text2)', fontSize: 9 }}>{timeAgo(e.created_at)}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </Card>

      {/* Pending Proposals */}
      {proposals.length > 0 && (
        <>
          <SectionHeader title="Pending Proposals" count={proposals.length} />
          <Card>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              {proposals.map((p, i) => (
                <div key={i} style={{ display: 'flex', gap: 8, padding: '5px 0', borderBottom: '1px solid var(--border-subtle)', fontSize: 10, alignItems: 'center' }}>
                  <span style={{ fontWeight: 600, color: 'var(--text0)', width: 50 }}>{p.symbol}</span>
                  <Badge label={p.action} color={p.action === 'BUY' ? 'var(--green)' : p.action === 'SELL' ? 'var(--red)' : 'var(--accent)'} />
                  <span style={{ color: 'var(--text2)' }}>{p.strategy_type}</span>
                  <span style={{ color: p.confidence >= 70 ? 'var(--green)' : 'var(--amber)', fontWeight: 600 }}>{p.confidence}%</span>
                  <span style={{ marginLeft: 'auto', color: 'var(--text3)', fontSize: 9 }}>{timeAgo(p.created_at)}</span>
                </div>
              ))}
            </div>
          </Card>
        </>
      )}
    </>
  )
}
