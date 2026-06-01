import { useState } from 'react'
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

const laneColors: Record<string, string> = {
  BATCH_APPROVE_ELIGIBLE: 'var(--green)', READY_FOR_OPERATOR_REVIEW: 'var(--accent)',
  NEEDS_RESEARCH: 'var(--amber)', AUTO_REJECT: 'var(--red)', DEFER_OBSERVE: 'var(--text3)',
}

export default function SelfLearningOverview() {
  const [rk, setRk] = useState(0)
  const { data, loading, error } = useApi<OverviewData>(`/api/v2/hermes/self-learning-overview?_r=${rk}`)

  if (loading && !data) return <div style={{ padding: 24, color: 'var(--text2)' }}>Loading...</div>
  if (error) return <div style={{ padding: 24, color: 'var(--red)' }}>Error: {error}</div>
  if (!data) return null

  return (
    <>
      <PageHeader title="Self-Learning Overview" subtitle="Hermes advisory automation cockpit" actions={
        <button onClick={() => setRk(k => k + 1)} style={{ fontSize: 11, padding: '4px 12px', border: '1px solid var(--border)', borderRadius: 4, background: 'var(--bg2)', color: 'var(--text1)', cursor: 'pointer' }}>Refresh</button>
      } />

      {/* Executive Status Strip */}
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 12 }}>
        <span style={{ fontSize: 10, padding: '3px 8px', borderRadius: 4, background: 'rgba(14,203,129,.15)', color: 'var(--green)', fontWeight: 700 }}>{data.maturity}</span>
        <span style={{ fontSize: 10, padding: '3px 8px', borderRadius: 4, background: 'rgba(234,57,67,.1)', color: 'var(--red)', fontWeight: 600 }}>Level 7: {data.level7}</span>
        <span style={{ fontSize: 10, padding: '3px 8px', borderRadius: 4, background: data.feed_health.status === 'RUN_HEALTHY' ? 'rgba(14,203,129,.1)' : 'rgba(246,190,0,.15)', color: data.feed_health.status === 'RUN_HEALTHY' ? 'var(--green)' : 'var(--amber)' }}>Feed: {data.feed_health.status}</span>
      </div>

      {/* Summary Cards */}
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 12 }}>
        {[
          { label: 'Hermes Rows', value: data.hermes.total, color: 'var(--text0)' },
          { label: 'Staged', value: data.hermes.staged, color: 'var(--text3)' },
          { label: 'Promoted', value: data.hermes.promoted, color: 'var(--accent)' },
          { label: 'Backlog', value: data.hermes.backlog, color: 'var(--amber)' },
          { label: 'Embeddings', value: data.embeddings, color: 'var(--green)' },
          { label: 'Cache', value: data.cache_sections, color: 'var(--text1)' },
          { label: 'LLM Queue', value: data.llm_queue.total, color: 'var(--accent)' },
          { label: 'Events', value: data.events.total, color: 'var(--text2)' },
        ].map((m, i) => (
          <div key={i} style={{ padding: '8px 14px', background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 6, textAlign: 'center', minWidth: 70 }}>
            <div style={{ fontSize: 18, fontWeight: 700, color: m.color }}>{m.value}</div>
            <div style={{ fontSize: 9, color: 'var(--text3)' }}>{m.label}</div>
          </div>
        ))}
      </div>

      {/* Promotion Lanes */}
      <Card title="Promotion Review Lanes">
        <div style={{ fontSize: 9, color: 'var(--amber)', marginBottom: 6 }}>Advisory Only — No Auto-Promotion — Operator Review Required</div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          {Object.entries(data.promotion_lanes).map(([lane, count]) => (
            <div key={lane} style={{ padding: '6px 12px', background: 'var(--bg2)', border: `1px solid ${laneColors[lane] || 'var(--border)'}`, borderRadius: 4, textAlign: 'center' }}>
              <div style={{ fontSize: 16, fontWeight: 700, color: laneColors[lane] || 'var(--text1)' }}>{count}</div>
              <div style={{ fontSize: 8, color: 'var(--text3)' }}>{lane.replace(/_/g, ' ')}</div>
            </div>
          ))}
        </div>
      </Card>

      {/* Queue Aging */}
      {data.age_buckets.length > 0 && (
        <Card title="Queue Aging">
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
            {data.age_buckets.map((b, i) => (
              <div key={i} style={{ padding: '6px 12px', background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 4, textAlign: 'center' }}>
                <div style={{ fontSize: 16, fontWeight: 700, color: b.bucket === '8d+' ? 'var(--red)' : b.bucket === '4-7d' ? 'var(--amber)' : 'var(--text1)' }}>{b.c}</div>
                <div style={{ fontSize: 9, color: 'var(--text3)' }}>{b.bucket}</div>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* Agent Touch Map */}
      <Card title="Agent Touch Map">
        <div style={{ fontSize: 11 }}>
          {data.agents.map((a, i) => (
            <div key={i} style={{ display: 'flex', justifyContent: 'space-between', padding: '3px 0', borderBottom: '1px solid var(--border)' }}>
              <span style={{ color: 'var(--text1)' }}>{a.hermes_agent_name?.replace(/_/g, ' ')}</span>
              <span style={{ color: 'var(--text3)', fontSize: 10 }}>{a.c} rows | {a.last ? new Date(a.last).toLocaleDateString() : '?'}</span>
            </div>
          ))}
        </div>
      </Card>

      {/* LLM Queue + Feed */}
      <Card title="Infrastructure">
        <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', fontSize: 11 }}>
          <div><span style={{ color: 'var(--text3)' }}>LLM Queue:</span> {data.llm_queue.total} total, {data.llm_queue.completed} done, {data.llm_queue.failed} failed</div>
          <div><span style={{ color: 'var(--text3)' }}>Feed:</span> {data.feed_health.status} ({data.feed_health.symbols} symbols)</div>
          <div><span style={{ color: 'var(--text3)' }}>Last Observation:</span> {data.last_observation ? new Date(data.last_observation).toLocaleString() : 'N/A'}</div>
        </div>
      </Card>
    </>
  )
}
