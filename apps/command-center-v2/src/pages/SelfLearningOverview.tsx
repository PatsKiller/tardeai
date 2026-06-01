import { useState, useMemo } from 'react'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import { useApi } from '../hooks/useApi'

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

interface TimelineEvent { type: string; id: number; symbol?: string; detail?: string; at: string }

const laneColors: Record<string, string> = {
  BATCH_APPROVE_ELIGIBLE: 'var(--green)', READY_FOR_OPERATOR_REVIEW: 'var(--accent)',
  NEEDS_RESEARCH: 'var(--amber)', AUTO_REJECT: 'var(--red)', DEFER_OBSERVE: 'var(--text3)',
}

export default function SelfLearningOverview() {
  const [rk, setRk] = useState(0)
  const [drill, setDrill] = useState<{ type: string; filter?: string } | null>(null)
  const [detail, setDetail] = useState<DrillItem | null>(null)
  const { data, loading, error } = useApi<OverviewData>(`/api/v2/hermes/self-learning-overview?_r=${rk}`)

  // Drill-down data
  const drillQ = drill ? `&status=${drill.filter || ''}` : ''
  const { data: drillData } = useApi<{ items: DrillItem[]; total: number }>(
    drill ? `/api/v2/hermes/self-learning/drilldown?_r=${rk}${drill.type === 'status' ? `&status=${drill.filter}` : ''}${drill.type === 'type' ? `&type=${drill.filter}` : ''}${drill.type === 'agent' ? `&agent=${drill.filter}` : ''}` : null
  )
  const { data: tlData } = useApi<{ events: TimelineEvent[] }>(`/api/v2/hermes/self-learning/timeline?_r=${rk}`)

  if (loading && !data) return <div style={{ padding: 24, color: 'var(--text2)' }}>Loading...</div>
  if (error) return <div style={{ padding: 24, color: 'var(--red)' }}>Error: {error}</div>
  if (!data) return null

  const cardStyle = (active?: boolean) => ({
    padding: '8px 14px', background: active ? 'var(--bg2)' : 'var(--bg1)',
    border: `1px solid ${active ? 'var(--accent)' : 'var(--border)'}`, borderRadius: 6,
    textAlign: 'center' as const, minWidth: 70, cursor: 'pointer',
  })

  return (
    <>
      <PageHeader title="Self-Learning Overview" subtitle="Hermes advisory automation cockpit — click any card to drill down" actions={
        <div style={{ display: 'flex', gap: 6 }}>
          {drill && <button onClick={() => { setDrill(null); setDetail(null) }} style={{ fontSize: 11, padding: '4px 12px', border: '1px solid var(--amber)', borderRadius: 4, background: 'transparent', color: 'var(--amber)', cursor: 'pointer' }}>← Back</button>}
          <button onClick={() => setRk(k => k + 1)} style={{ fontSize: 11, padding: '4px 12px', border: '1px solid var(--border)', borderRadius: 4, background: 'var(--bg2)', color: 'var(--text1)', cursor: 'pointer' }}>Refresh</button>
        </div>
      } />

      {/* Executive Status Strip */}
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 12 }}>
        <span style={{ fontSize: 10, padding: '3px 8px', borderRadius: 4, background: 'rgba(14,203,129,.15)', color: 'var(--green)', fontWeight: 700 }}>{data.maturity}</span>
        <span style={{ fontSize: 10, padding: '3px 8px', borderRadius: 4, background: 'rgba(234,57,67,.1)', color: 'var(--red)', fontWeight: 600 }}>Level 7: {data.level7}</span>
        <span style={{ fontSize: 10, padding: '3px 8px', borderRadius: 4, background: data.feed_health.status === 'RUN_HEALTHY' ? 'rgba(14,203,129,.1)' : 'rgba(246,190,0,.15)', color: data.feed_health.status === 'RUN_HEALTHY' ? 'var(--green)' : 'var(--amber)' }}>Feed: {data.feed_health.status} ({data.feed_health.symbols})</span>
      </div>

      {/* Clickable Summary Cards */}
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 12 }}>
        {[
          { label: 'Total', value: data.hermes.total, color: 'var(--text0)', click: { type: 'all' } },
          { label: 'Staged', value: data.hermes.staged, color: 'var(--text3)', click: { type: 'status', filter: 'staged' } },
          { label: 'Promoted', value: data.hermes.promoted, color: 'var(--accent)', click: { type: 'status', filter: 'promoted' } },
          { label: 'Backlog', value: data.hermes.backlog, color: 'var(--amber)', click: { type: 'type', filter: 'research_backlog' } },
          { label: 'Embeddings', value: data.embeddings, color: 'var(--green)' },
          { label: 'Cache', value: data.cache_sections, color: 'var(--text1)' },
          { label: 'LLM Queue', value: data.llm_queue.total, color: 'var(--accent)' },
          { label: 'Events', value: data.events.total, color: 'var(--text2)' },
        ].map((m, i) => (
          <div key={i} onClick={() => m.click && setDrill(m.click as any)} style={cardStyle(drill?.filter === m.click?.filter)}>
            <div style={{ fontSize: 18, fontWeight: 700, color: m.color }}>{m.value}</div>
            <div style={{ fontSize: 9, color: 'var(--text3)' }}>{m.label}</div>
          </div>
        ))}
      </div>

      {/* Drill-Down Panel */}
      {drill && drillData && (
        <Card title={`Drill-Down: ${drill.filter || 'all'} (${drillData.total} items)`}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
            <thead>
              <tr style={{ borderBottom: '1px solid var(--border)' }}>
                {['ID', 'Symbol', 'Type', 'Agent', 'Conf', 'Status', 'Topic', ''].map(h => (
                  <th key={h} style={{ textAlign: 'left', padding: '4px 6px', color: 'var(--text3)', fontSize: 10 }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {drillData.items.slice(0, 20).map(r => (
                <tr key={r.id} style={{ borderBottom: '1px solid var(--border)' }}>
                  <td style={{ padding: '4px 6px', fontFamily: 'monospace', color: 'var(--text3)' }}>{r.id}</td>
                  <td style={{ padding: '4px 6px', fontWeight: 600, color: 'var(--text0)' }}>{r.symbol || 'SYS'}</td>
                  <td style={{ padding: '4px 6px', color: 'var(--text2)', fontSize: 10 }}>{r.research_type?.replace(/_/g, ' ')}</td>
                  <td style={{ padding: '4px 6px', color: 'var(--text3)', fontSize: 9 }}>{r.hermes_agent_name?.replace(/_/g, ' ')}</td>
                  <td style={{ padding: '4px 6px' }}>{r.confidence_score}</td>
                  <td style={{ padding: '4px 6px' }}>
                    <span style={{ fontSize: 9, padding: '1px 5px', borderRadius: 3, background: r.status === 'promoted' ? 'rgba(74,144,244,.1)' : 'rgba(246,190,0,.1)', color: r.status === 'promoted' ? 'var(--accent)' : 'var(--amber)' }}>{r.status}</span>
                    {r.embedded && <span style={{ fontSize: 8, marginLeft: 4, color: 'var(--green)' }}>RAG</span>}
                  </td>
                  <td style={{ padding: '4px 6px', color: 'var(--text2)', fontSize: 10, maxWidth: 180, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.topic}</td>
                  <td style={{ padding: '4px 6px' }}>
                    <button onClick={() => setDetail(r)} style={{ fontSize: 9, padding: '2px 6px', border: '1px solid var(--accent)', borderRadius: 3, background: 'transparent', color: 'var(--accent)', cursor: 'pointer' }}>Detail</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      {/* Promotion Lanes — Clickable */}
      {!drill && (
        <Card title="Promotion Review Lanes">
          <div style={{ fontSize: 9, color: 'var(--amber)', marginBottom: 6 }}>Advisory Only — Click lane to drill down</div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {Object.entries(data.promotion_lanes).map(([lane, count]) => (
              <div key={lane} onClick={() => setDrill({ type: 'status', filter: 'staged' })} style={{ padding: '6px 12px', background: 'var(--bg2)', border: `1px solid ${laneColors[lane] || 'var(--border)'}`, borderRadius: 4, textAlign: 'center', cursor: 'pointer' }}>
                <div style={{ fontSize: 16, fontWeight: 700, color: laneColors[lane] || 'var(--text1)' }}>{count}</div>
                <div style={{ fontSize: 8, color: 'var(--text3)' }}>{lane.replace(/_/g, ' ')}</div>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* Queue Aging — Clickable */}
      {!drill && data.age_buckets.length > 0 && (
        <Card title="Queue Aging">
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
            {data.age_buckets.map((b, i) => (
              <div key={i} onClick={() => setDrill({ type: 'status', filter: 'staged' })} style={{ padding: '6px 12px', background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 4, textAlign: 'center', cursor: 'pointer' }}>
                <div style={{ fontSize: 16, fontWeight: 700, color: b.bucket === '8d+' ? 'var(--red)' : b.bucket === '4-7d' ? 'var(--amber)' : 'var(--text1)' }}>{b.c}</div>
                <div style={{ fontSize: 9, color: 'var(--text3)' }}>{b.bucket}</div>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* Agent Touch Map — Clickable */}
      {!drill && (
        <Card title="Agent Touch Map">
          <div style={{ fontSize: 11 }}>
            {data.agents.map((a, i) => (
              <div key={i} onClick={() => setDrill({ type: 'agent', filter: a.hermes_agent_name })} style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 0', borderBottom: '1px solid var(--border)', cursor: 'pointer' }}>
                <span style={{ color: 'var(--text1)' }}>{a.hermes_agent_name?.replace(/_/g, ' ')}</span>
                <span style={{ color: 'var(--text3)', fontSize: 10 }}>{a.c} rows | {a.last ? new Date(a.last).toLocaleDateString() : '?'}</span>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* Timeline */}
      {!drill && tlData && tlData.events.length > 0 && (
        <Card title="Timeline (Recent 20)">
          <div style={{ fontSize: 10 }}>
            {tlData.events.map((e, i) => (
              <div key={i} style={{ display: 'flex', gap: 8, padding: '3px 0', borderBottom: '1px solid var(--border)', alignItems: 'center' }}>
                <span style={{ fontSize: 9, padding: '1px 5px', borderRadius: 3, minWidth: 55, textAlign: 'center',
                  background: e.type === 'promoted' ? 'rgba(74,144,244,.1)' : e.type === 'embedded' ? 'rgba(14,203,129,.1)' : e.type === 'event' ? 'rgba(246,190,0,.1)' : 'rgba(100,100,100,.1)',
                  color: e.type === 'promoted' ? 'var(--accent)' : e.type === 'embedded' ? 'var(--green)' : e.type === 'event' ? 'var(--amber)' : 'var(--text3)',
                }}>{e.type}</span>
                <span style={{ color: 'var(--text2)' }}>id={e.id}</span>
                {e.symbol && <span style={{ color: 'var(--text1)', fontWeight: 600 }}>{e.symbol}</span>}
                {e.detail && <span style={{ color: 'var(--text3)' }}>{e.detail.replace(/_/g, ' ')}</span>}
                <span style={{ color: 'var(--text3)', marginLeft: 'auto', fontSize: 9 }}>{e.at ? new Date(e.at).toLocaleString() : ''}</span>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* Infrastructure */}
      {!drill && (
        <Card title="Infrastructure">
          <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', fontSize: 11 }}>
            <div><span style={{ color: 'var(--text3)' }}>LLM Queue:</span> {data.llm_queue.total} total, {data.llm_queue.completed} done, {data.llm_queue.failed} failed</div>
            <div><span style={{ color: 'var(--text3)' }}>Feed:</span> {data.feed_health.status} ({data.feed_health.symbols} symbols)</div>
            <div><span style={{ color: 'var(--text3)' }}>Last Observation:</span> {data.last_observation ? new Date(data.last_observation).toLocaleString() : 'N/A'}</div>
          </div>
        </Card>
      )}

      {/* Detail Drawer */}
      {detail && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.6)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center' }} onClick={() => setDetail(null)}>
          <div onClick={e => e.stopPropagation()} style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 8, padding: 20, maxWidth: 600, width: '90%', maxHeight: '80vh', overflowY: 'auto' }}>
            <div style={{ fontSize: 9, color: 'var(--amber)', marginBottom: 8, padding: '3px 6px', background: 'rgba(246,190,0,.08)', borderRadius: 3 }}>Advisory Only — Not Execution — Read-Only Detail</div>
            <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text0)', marginBottom: 4 }}>{detail.symbol || 'SYSTEM'} — {detail.research_type?.replace(/_/g, ' ')}</div>
            <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 8 }}>ID: {detail.id} | Agent: {detail.hermes_agent_name} | Confidence: {detail.confidence_score}</div>
            <div style={{ fontSize: 12, color: 'var(--text0)', marginBottom: 8, lineHeight: 1.5 }}><strong>Topic:</strong> {detail.topic}</div>
            <div style={{ fontSize: 11, color: 'var(--text1)', marginBottom: 8, lineHeight: 1.5 }}><strong>Summary:</strong> {detail.summary}</div>
            <div style={{ display: 'flex', gap: 6, marginBottom: 8, flexWrap: 'wrap' }}>
              <span style={{ fontSize: 9, padding: '2px 6px', borderRadius: 3, background: detail.status === 'promoted' ? 'rgba(74,144,244,.15)' : 'rgba(246,190,0,.1)', color: detail.status === 'promoted' ? 'var(--accent)' : 'var(--amber)' }}>{detail.status}</span>
              {detail.embedded && <span style={{ fontSize: 9, padding: '2px 6px', borderRadius: 3, background: 'rgba(14,203,129,.15)', color: 'var(--green)' }}>Embedded</span>}
              {detail.promoted_audit && <span style={{ fontSize: 9, padding: '2px 6px', borderRadius: 3, background: 'rgba(74,144,244,.1)', color: 'var(--accent)' }}>Audit ✓</span>}
            </div>
            <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 4 }}>Created: {detail.created_at ? new Date(detail.created_at).toLocaleString() : '?'}</div>
            <button onClick={() => setDetail(null)} style={{ marginTop: 12, fontSize: 11, padding: '6px 16px', border: '1px solid var(--border)', borderRadius: 4, background: 'var(--bg2)', color: 'var(--text1)', cursor: 'pointer' }}>Close</button>
          </div>
        </div>
      )}
    </>
  )
}
