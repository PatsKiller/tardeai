import { useState } from 'react'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import { useApi } from '../hooks/useApi'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell, PieChart, Pie } from 'recharts'

interface OverviewData {
  maturity: string; level7: string
  hermes: { total: number; staged: number; promoted: number; backlog: number; ops_backlog: number }
  embeddings: number; cache_sections: number
  events: { total: number; pending: number; completed: number; skipped: number }
  llm_queue: { total: number; completed: number; failed: number }
  age_buckets: Array<{ bucket: string; c: number }>
  agents: Array<{ hermes_agent_name: string; c: number; last: string }>
  promotion_lanes: Record<string, number>
  feed_health: { status: string; symbols: number }
  last_observation: string | null
}

interface DrillItem {
  id: number; symbol: string | null; research_type: string; hermes_agent_name: string
  confidence_score: number; status: string; topic: string; summary: string
  source_urls_json: string; created_at: string; embedded: boolean; promoted_audit: boolean
}

interface TLEvent { type: string; id: number; symbol?: string; detail?: string; at: string }

const laneConfig: Record<string, { color: string; bg: string; icon: string }> = {
  BATCH_APPROVE_ELIGIBLE: { color: 'var(--green)', bg: 'rgba(14,203,129,.08)', icon: '✓' },
  READY_FOR_OPERATOR_REVIEW: { color: 'var(--accent)', bg: 'rgba(74,144,244,.06)', icon: '👁' },
  NEEDS_RESEARCH: { color: 'var(--amber)', bg: 'rgba(246,190,0,.06)', icon: '🔍' },
  AUTO_REJECT: { color: 'var(--red)', bg: 'rgba(234,57,67,.06)', icon: '✕' },
  DEFER_OBSERVE: { color: 'var(--text3)', bg: 'rgba(100,100,100,.06)', icon: '⏳' },
}

const flowStages = ['Source Discovery', 'Research Backlog', 'Staged Research', 'Advisory Cache', 'Embeddings', 'Promotion Review', 'Promoted']

function ScoreBar({ label, value, max = 1 }: { label: string; value: number; max?: number }) {
  const pct = Math.min(100, (value / max) * 100)
  const color = pct >= 75 ? 'var(--green)' : pct >= 50 ? 'var(--amber)' : 'var(--red)'
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 10, marginBottom: 3 }}>
      <span style={{ width: 80, color: 'var(--text3)' }}>{label}</span>
      <div style={{ flex: 1, height: 6, background: 'var(--bg2)', borderRadius: 3, overflow: 'hidden' }}>
        <div style={{ width: `${pct}%`, height: '100%', background: color, borderRadius: 3 }} />
      </div>
      <span style={{ width: 30, textAlign: 'right', color: 'var(--text2)', fontSize: 9 }}>{(value * 100).toFixed(0)}%</span>
    </div>
  )
}

export default function SelfLearningOverview() {
  const [rk, setRk] = useState(0)
  const [filter, setFilter] = useState<string | null>(null)
  const [detail, setDetail] = useState<DrillItem | null>(null)
  const { data } = useApi<OverviewData>(`/api/v2/hermes/self-learning-overview?_r=${rk}`)
  const drillQ = filter ? `&${filter}` : ''
  const { data: drillData } = useApi<{ items: DrillItem[] }>(filter ? `/api/v2/hermes/self-learning/drilldown?_r=${rk}${drillQ}` : null)
  const { data: tlData } = useApi<{ events: TLEvent[] }>(`/api/v2/hermes/self-learning/timeline?_r=${rk}`)

  if (!data) return <div style={{ padding: 24, color: 'var(--text2)' }}>Loading...</div>

  const h = data.hermes
  const maxAge = Math.max(...(data.age_buckets.map(b => b.c) || [1]), 1)

  return (
    <div style={{ display: 'flex', gap: 12 }}>
      {/* Main Content */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <PageHeader title="Self-Learning Overview" subtitle="Hermes advisory automation cockpit" actions={
          <div style={{ display: 'flex', gap: 6 }}>
            {filter && <button onClick={() => { setFilter(null); setDetail(null) }} style={{ fontSize: 10, padding: '3px 10px', border: '1px solid var(--amber)', borderRadius: 4, background: 'transparent', color: 'var(--amber)', cursor: 'pointer' }}>← Back</button>}
            <button onClick={() => setRk(k => k + 1)} style={{ fontSize: 10, padding: '3px 10px', border: '1px solid var(--border)', borderRadius: 4, background: 'var(--bg2)', color: 'var(--text1)', cursor: 'pointer' }}>Refresh</button>
          </div>
        } />

        {/* Status Strip */}
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 10 }}>
          <span style={{ fontSize: 9, padding: '2px 8px', borderRadius: 10, background: 'rgba(14,203,129,.15)', color: 'var(--green)', fontWeight: 700 }}>{data.maturity}</span>
          <span style={{ fontSize: 9, padding: '2px 8px', borderRadius: 10, background: 'rgba(234,57,67,.1)', color: 'var(--red)' }}>Level 7: {data.level7}</span>
          <span style={{ fontSize: 9, padding: '2px 8px', borderRadius: 10, background: data.feed_health.status === 'RUN_HEALTHY' ? 'rgba(14,203,129,.1)' : 'rgba(246,190,0,.15)', color: data.feed_health.status === 'RUN_HEALTHY' ? 'var(--green)' : 'var(--amber)' }}>Feed: {data.feed_health.status}</span>
        </div>

        {/* Filter Chips */}
        <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginBottom: 10 }}>
          {[
            { label: 'All', q: null },
            { label: `Staged (${h.staged})`, q: 'status=staged' },
            { label: `Promoted (${h.promoted})`, q: 'status=promoted' },
            { label: `Backlog (${h.backlog})`, q: 'type=research_backlog' },
            { label: 'Needs Review', q: 'status=staged' },
          ].map((f, i) => (
            <button key={i} onClick={() => setFilter(f.q)} style={{
              fontSize: 9, padding: '2px 8px', borderRadius: 10, cursor: 'pointer',
              border: `1px solid ${filter === f.q ? 'var(--accent)' : 'var(--border)'}`,
              background: filter === f.q ? 'rgba(74,144,244,.1)' : 'var(--bg2)',
              color: filter === f.q ? 'var(--accent)' : 'var(--text2)',
            }}>{f.label}</button>
          ))}
        </div>

        {/* Flow Diagram */}
        {!filter && (
          <Card title="Self-Learning Flow">
            <div style={{ display: 'flex', alignItems: 'center', gap: 4, flexWrap: 'wrap', padding: '4px 0' }}>
              {flowStages.map((stage, i) => {
                const counts: Record<string, number> = { 'Source Discovery': 8, 'Research Backlog': h.backlog, 'Staged Research': h.staged - h.backlog, 'Advisory Cache': data.cache_sections, 'Embeddings': data.embeddings, 'Promotion Review': data.promotion_lanes.READY_FOR_OPERATOR_REVIEW || 0, 'Promoted': h.promoted }
                const c = counts[stage] || 0
                return (
                  <div key={stage} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                    <div style={{ padding: '6px 10px', background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 6, textAlign: 'center', minWidth: 60 }}>
                      <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text0)' }}>{c}</div>
                      <div style={{ fontSize: 8, color: 'var(--text3)', lineHeight: 1.2 }}>{stage}</div>
                    </div>
                    {i < flowStages.length - 1 && <span style={{ color: 'var(--text3)', fontSize: 12 }}>→</span>}
                  </div>
                )
              })}
            </div>
          </Card>
        )}

        {/* Promotion Lanes as Cards */}
        {!filter && (
          <Card title="Promotion Review Lanes">
            <div style={{ fontSize: 9, color: 'var(--amber)', marginBottom: 6 }}>Advisory Only — Click lane to drill down</div>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              {Object.entries(data.promotion_lanes).filter(([, c]) => c > 0).map(([lane, count]) => {
                const cfg = laneConfig[lane] || { color: 'var(--text3)', bg: 'rgba(100,100,100,.05)', icon: '?' }
                return (
                  <div key={lane} onClick={() => setFilter('status=staged')} style={{ padding: '8px 14px', background: cfg.bg, border: `1px solid ${cfg.color}40`, borderRadius: 8, cursor: 'pointer', minWidth: 100 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 4, marginBottom: 4 }}>
                      <span style={{ fontSize: 14 }}>{cfg.icon}</span>
                      <span style={{ fontSize: 18, fontWeight: 700, color: cfg.color }}>{count}</span>
                    </div>
                    <div style={{ fontSize: 8, color: 'var(--text3)', lineHeight: 1.2 }}>{lane.replace(/_/g, ' ')}</div>
                  </div>
                )
              })}
            </div>
          </Card>
        )}

        {/* Queue Aging — Recharts */}
        {!filter && data.age_buckets.length > 0 && (
          <Card title="Queue Aging">
            <ResponsiveContainer width="100%" height={120}>
              <BarChart data={data.age_buckets} margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
                <XAxis dataKey="bucket" tick={{ fontSize: 10, fill: '#888' }} axisLine={false} tickLine={false} />
                <YAxis hide />
                <Tooltip contentStyle={{ fontSize: 11, background: '#1a1a2e', border: '1px solid #333', borderRadius: 4 }} />
                <Bar dataKey="c" radius={[4, 4, 0, 0]}>
                  {data.age_buckets.map((b, i) => (
                    <Cell key={i} fill={b.bucket === '8d+' ? '#ea3943' : b.bucket === '4-7d' ? '#f6be00' : '#4a90f4'} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </Card>
        )}

        {/* Agent Touch */}
        {!filter && (
          <Card title="Agent Activity">
            {data.agents.slice(0, 6).map((a, i) => (
              <div key={i} onClick={() => setFilter(`agent=${a.hermes_agent_name}`)} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '4px 0', borderBottom: '1px solid var(--border)', cursor: 'pointer' }}>
                <div style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--green)' }} />
                <span style={{ flex: 1, fontSize: 11, color: 'var(--text1)' }}>{a.hermes_agent_name?.replace(/_/g, ' ')}</span>
                <span style={{ fontSize: 10, color: 'var(--text3)' }}>{a.c} rows</span>
                <span style={{ fontSize: 9, color: 'var(--text3)' }}>{a.last ? new Date(a.last).toLocaleDateString() : ''}</span>
              </div>
            ))}
          </Card>
        )}

        {/* Agent Distribution — Recharts */}
        {!filter && data.agents.length > 0 && (
          <Card title="Agent Distribution">
            <ResponsiveContainer width="100%" height={140}>
              <BarChart data={data.agents.slice(0, 6).map(a => ({ name: a.hermes_agent_name?.replace(/_/g, ' ').substring(0, 15), rows: a.c }))} layout="vertical" margin={{ top: 0, right: 10, left: 80, bottom: 0 }}>
                <XAxis type="number" hide />
                <YAxis type="category" dataKey="name" tick={{ fontSize: 9, fill: '#888' }} axisLine={false} tickLine={false} width={80} />
                <Tooltip contentStyle={{ fontSize: 10, background: '#1a1a2e', border: '1px solid #333' }} />
                <Bar dataKey="rows" fill="#4a90f4" radius={[0, 4, 4, 0]} barSize={12} />
              </BarChart>
            </ResponsiveContainer>
          </Card>
        )}

        {/* Timeline */}
        {!filter && tlData && (
          <Card title="Timeline">
            {tlData.events.slice(0, 12).map((e, i) => {
              const colors: Record<string, string> = { staged: 'var(--text3)', promoted: 'var(--accent)', embedded: 'var(--green)', event: 'var(--amber)' }
              return (
                <div key={i} style={{ display: 'flex', gap: 6, padding: '3px 0', borderBottom: '1px solid var(--border)', alignItems: 'center', fontSize: 10 }}>
                  <div style={{ width: 8, height: 8, borderRadius: '50%', background: colors[e.type] || 'var(--text3)', flexShrink: 0 }} />
                  <span style={{ color: colors[e.type] || 'var(--text3)', fontWeight: 600, minWidth: 55 }}>{e.type}</span>
                  <span style={{ color: 'var(--text2)' }}>id={e.id}</span>
                  {e.symbol && <span style={{ color: 'var(--text0)', fontWeight: 600 }}>{e.symbol}</span>}
                  <span style={{ color: 'var(--text3)', marginLeft: 'auto', fontSize: 9 }}>{e.at ? new Date(e.at).toLocaleString() : ''}</span>
                </div>
              )
            })}
          </Card>
        )}

        {/* Drill-Down */}
        {filter && drillData && (
          <Card title={`Results (${drillData.items.length})`}>
            {drillData.items.slice(0, 20).map(r => (
              <div key={r.id} onClick={() => setDetail(r)} style={{ display: 'flex', gap: 8, padding: '6px 0', borderBottom: '1px solid var(--border)', cursor: 'pointer', alignItems: 'center' }}>
                <span style={{ fontFamily: 'monospace', fontSize: 10, color: 'var(--text3)', width: 24 }}>{r.id}</span>
                <span style={{ fontWeight: 600, color: 'var(--text0)', width: 50 }}>{r.symbol || 'SYS'}</span>
                <span style={{ fontSize: 9, padding: '1px 5px', borderRadius: 3, background: r.status === 'promoted' ? 'rgba(74,144,244,.1)' : 'rgba(246,190,0,.1)', color: r.status === 'promoted' ? 'var(--accent)' : 'var(--amber)' }}>{r.status}</span>
                {r.embedded && <span style={{ fontSize: 8, color: 'var(--green)' }}>RAG</span>}
                <span style={{ flex: 1, fontSize: 10, color: 'var(--text2)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.topic}</span>
                <span style={{ fontSize: 9, color: 'var(--text3)' }}>{r.confidence_score}</span>
              </div>
            ))}
          </Card>
        )}

        {/* Infrastructure */}
        {!filter && (
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 8, fontSize: 10, color: 'var(--text3)' }}>
            <span>LLM: {data.llm_queue.total} jobs ({data.llm_queue.completed} done, {data.llm_queue.failed} fail)</span>
            <span>|</span>
            <span>Feed: {data.feed_health.symbols} symbols</span>
            <span>|</span>
            <span>Obs: {data.last_observation ? new Date(data.last_observation).toLocaleString() : 'N/A'}</span>
          </div>
        )}
      </div>

      {/* Persistent Detail Drawer */}
      {detail && (
        <div style={{ width: 320, flexShrink: 0, background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 8, padding: 16, maxHeight: '85vh', overflowY: 'auto', position: 'sticky', top: 12 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
            <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)' }}>{detail.symbol || 'SYSTEM'}</span>
            <button onClick={() => setDetail(null)} style={{ fontSize: 10, padding: '2px 8px', border: '1px solid var(--border)', borderRadius: 4, background: 'var(--bg2)', color: 'var(--text3)', cursor: 'pointer' }}>✕</button>
          </div>
          <div style={{ fontSize: 9, color: 'var(--amber)', marginBottom: 8, padding: '2px 6px', background: 'rgba(246,190,0,.06)', borderRadius: 3 }}>Advisory Only — Read-Only</div>

          <div style={{ fontSize: 11, color: 'var(--text1)', marginBottom: 6, lineHeight: 1.4 }}>{detail.topic}</div>
          <div style={{ fontSize: 10, color: 'var(--text2)', marginBottom: 10, lineHeight: 1.4 }}>{detail.summary}</div>

          <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginBottom: 10 }}>
            <span style={{ fontSize: 8, padding: '1px 5px', borderRadius: 3, background: detail.status === 'promoted' ? 'rgba(74,144,244,.1)' : 'rgba(246,190,0,.08)', color: detail.status === 'promoted' ? 'var(--accent)' : 'var(--amber)' }}>{detail.status}</span>
            {detail.embedded && <span style={{ fontSize: 8, padding: '1px 5px', borderRadius: 3, background: 'rgba(14,203,129,.1)', color: 'var(--green)' }}>Embedded</span>}
            {detail.promoted_audit && <span style={{ fontSize: 8, padding: '1px 5px', borderRadius: 3, background: 'rgba(74,144,244,.08)', color: 'var(--accent)' }}>Audit ✓</span>}
          </div>

          <div style={{ marginBottom: 10 }}>
            <div style={{ fontSize: 10, fontWeight: 600, color: 'var(--text2)', marginBottom: 4 }}>Quality</div>
            <ScoreBar label="Confidence" value={detail.confidence_score} />
            <ScoreBar label="Evidence" value={detail.source_urls_json && detail.source_urls_json !== '[]' ? 0.9 : 0.5} />
            <ScoreBar label="Freshness" value={0.9} />
          </div>

          <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 4 }}>
            <div>ID: {detail.id}</div>
            <div>Type: {detail.research_type?.replace(/_/g, ' ')}</div>
            <div>Agent: {detail.hermes_agent_name?.replace(/_/g, ' ')}</div>
            <div>Created: {detail.created_at ? new Date(detail.created_at).toLocaleString() : '?'}</div>
          </div>
        </div>
      )}
    </div>
  )
}
