import { useState } from 'react'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import { useApi } from '../hooks/useApi'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts'

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

const laneConfig: Record<string, { color: string; icon: string; label: string }> = {
  BATCH_APPROVE_ELIGIBLE: { color: '#0ecb81', icon: '✓', label: 'Batch Eligible' },
  READY_FOR_OPERATOR_REVIEW: { color: '#4a90f4', icon: '👁', label: 'Ready for Review' },
  NEEDS_RESEARCH: { color: '#f6be00', icon: '🔍', label: 'Needs Research' },
  AUTO_REJECT: { color: '#ea3943', icon: '✕', label: 'Auto Reject' },
  DEFER_OBSERVE: { color: '#888', icon: '⏳', label: 'Defer' },
}

function ScoreBar({ label, value }: { label: string; value: number }) {
  const pct = Math.min(100, value * 100)
  const color = pct >= 75 ? '#0ecb81' : pct >= 50 ? '#f6be00' : '#ea3943'
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 10, marginBottom: 4 }}>
      <span style={{ width: 75, color: 'var(--text3)', flexShrink: 0 }}>{label}</span>
      <div style={{ flex: 1, height: 8, background: 'var(--bg2)', borderRadius: 4, overflow: 'hidden' }}>
        <div style={{ width: `${pct}%`, height: '100%', background: color, borderRadius: 4 }} />
      </div>
      <span style={{ width: 28, textAlign: 'right', color, fontSize: 9, fontWeight: 600 }}>{pct.toFixed(0)}%</span>
    </div>
  )
}

export default function SelfLearningOverview() {
  const [rk, setRk] = useState(0)
  const [filter, setFilter] = useState<string | null>(null)
  const [selected, setSelected] = useState<DrillItem | null>(null)
  const { data } = useApi<OverviewData>(`/api/v2/hermes/self-learning-overview?_r=${rk}`)
  const { data: drillData } = useApi<{ items: DrillItem[] }>(filter ? `/api/v2/hermes/self-learning/drilldown?_r=${rk}&${filter}` : null)
  const { data: tlData } = useApi<{ events: TLEvent[] }>(`/api/v2/hermes/self-learning/timeline?_r=${rk}`)

  if (!data) return <div style={{ padding: 24, color: 'var(--text2)' }}>Loading...</div>

  const h = data.hermes
  const needsAttention = (data.promotion_lanes.READY_FOR_OPERATOR_REVIEW || 0) + (data.promotion_lanes.NEEDS_RESEARCH || 0)
  const blocked = (data.promotion_lanes.AUTO_REJECT || 0) + (h.ops_backlog || 0)
  const newToday = tlData?.events.filter(e => { const d = new Date(e.at); const n = new Date(); return d.toDateString() === n.toDateString() }).length || 0
  const hc = { transition: 'all .15s', cursor: 'pointer' }

  return (
    <div style={{ display: 'flex', gap: 14, minHeight: '80vh' }}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <PageHeader title="Self-Learning Overview" subtitle="What needs your attention?" actions={
          <div style={{ display: 'flex', gap: 6 }}>
            {filter && <button onClick={() => { setFilter(null); setSelected(null) }} style={{ fontSize: 10, padding: '3px 10px', border: '1px solid var(--amber)', borderRadius: 6, background: 'transparent', color: 'var(--amber)', cursor: 'pointer' }}>← Overview</button>}
            <button onClick={() => setRk(k => k + 1)} style={{ fontSize: 10, padding: '3px 10px', border: '1px solid var(--border)', borderRadius: 6, background: 'var(--bg2)', color: 'var(--text1)', cursor: 'pointer' }}>↻</button>
          </div>
        } />

        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 12 }}>
          <span style={{ fontSize: 9, padding: '2px 10px', borderRadius: 12, background: 'rgba(14,203,129,.12)', color: '#0ecb81', fontWeight: 700 }}>{data.maturity}</span>
          <span style={{ fontSize: 9, padding: '2px 10px', borderRadius: 12, background: 'rgba(234,57,67,.08)', color: '#ea3943' }}>Level 7: {data.level7}</span>
          <span style={{ fontSize: 9, padding: '2px 10px', borderRadius: 12, background: data.feed_health.status === 'RUN_HEALTHY' ? 'rgba(14,203,129,.08)' : 'rgba(246,190,0,.12)', color: data.feed_health.status === 'RUN_HEALTHY' ? '#0ecb81' : '#f6be00' }}>Feed {data.feed_health.symbols} sym</span>
          <span style={{ fontSize: 9, padding: '2px 10px', borderRadius: 12, background: 'rgba(74,144,244,.08)', color: '#4a90f4' }}>LLM {data.llm_queue.completed}/{data.llm_queue.total}</span>
        </div>

        {!filter && (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: 10, marginBottom: 14 }}>
            {[
              { label: '⚡ Needs Attention', value: needsAttention, color: '#f6be00', q: 'status=staged', bg: 'rgba(246,190,0,.06)' },
              { label: '🆕 New Today', value: newToday, color: '#4a90f4', q: null, bg: 'rgba(74,144,244,.06)' },
              { label: '🚫 Blocked / Stale', value: blocked, color: '#ea3943', q: 'type=ops_backlog', bg: 'rgba(234,57,67,.06)' },
              { label: '✓ Auto-Promoted', value: 3, color: '#0ecb81', q: 'status=promoted', bg: 'rgba(14,203,129,.06)' },
            ].map((c, i) => (
              <div key={i} onClick={() => c.q && setFilter(c.q)} style={{ ...hc, padding: '12px 14px', background: c.bg, border: `1px solid ${filter === c.q ? 'var(--accent)' : 'var(--border)'}`, borderRadius: 10 }}>
                <div style={{ fontSize: 24, fontWeight: 800, color: c.color }}>{c.value}</div>
                <div style={{ fontSize: 10, color: 'var(--text2)', marginTop: 2 }}>{c.label}</div>
              </div>
            ))}
          </div>
        )}

        {!filter && (
          <Card title="Workflow Lanes">
            <div style={{ display: 'flex', gap: 8, overflowX: 'auto', paddingBottom: 4 }}>
              {Object.entries(data.promotion_lanes).filter(([, v]) => v > 0).map(([lane, count]) => {
                const cfg = laneConfig[lane] || { color: '#888', icon: '?', label: lane }
                return (
                  <div key={lane} onClick={() => setFilter('status=staged')} style={{ ...hc, minWidth: 110, padding: '10px 12px', background: `${cfg.color}08`, border: `1px solid ${cfg.color}30`, borderRadius: 10 }}>
                    <div style={{ fontSize: 12, marginBottom: 4 }}>{cfg.icon}</div>
                    <div style={{ fontSize: 22, fontWeight: 800, color: cfg.color }}>{count}</div>
                    <div style={{ fontSize: 9, color: 'var(--text3)' }}>{cfg.label}</div>
                  </div>
                )
              })}
            </div>
          </Card>
        )}

        {!filter && (
          <Card title="Research Pipeline">
            <div style={{ display: 'flex', alignItems: 'center', gap: 3, flexWrap: 'wrap' }}>
              {[
                { name: 'Discovery', count: 8, color: '#4a90f4' },
                { name: 'Backlog', count: h.backlog, color: '#f6be00' },
                { name: 'Staged', count: h.staged - h.backlog, color: '#888' },
                { name: 'Cache', count: data.cache_sections, color: '#0ecb81' },
                { name: 'Embedded', count: data.embeddings, color: '#4a90f4' },
                { name: 'Promoted', count: h.promoted, color: '#0ecb81' },
              ].map((s, i) => (
                <div key={s.name} style={{ display: 'flex', alignItems: 'center', gap: 3 }}>
                  <div onClick={() => setFilter(i <= 2 ? 'status=staged' : 'status=promoted')} style={{ ...hc, padding: '8px 10px', background: `${s.color}0a`, border: `1px solid ${s.color}25`, borderRadius: 8, textAlign: 'center', minWidth: 55 }}>
                    <div style={{ fontSize: 16, fontWeight: 700, color: s.color }}>{s.count}</div>
                    <div style={{ fontSize: 8, color: 'var(--text3)' }}>{s.name}</div>
                  </div>
                  {i < 5 && <span style={{ color: 'var(--text3)', fontSize: 11 }}>→</span>}
                </div>
              ))}
            </div>
          </Card>
        )}

        {!filter && data.age_buckets.length > 0 && (
          <Card title="Queue Aging">
            <ResponsiveContainer width="100%" height={100}>
              <BarChart data={data.age_buckets} margin={{ top: 5, right: 5, left: 0, bottom: 0 }}>
                <XAxis dataKey="bucket" tick={{ fontSize: 10, fill: '#888' }} axisLine={false} tickLine={false} />
                <YAxis hide />
                <Tooltip contentStyle={{ fontSize: 11, background: '#1a1a2e', border: '1px solid #333', borderRadius: 6 }} />
                <Bar dataKey="c" radius={[6, 6, 0, 0]}>
                  {data.age_buckets.map((b, i) => (
                    <Cell key={i} fill={b.bucket === '8d+' ? '#ea3943' : b.bucket === '4-7d' ? '#f6be00' : '#4a90f4'} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </Card>
        )}

        {!filter && data.agents.length > 0 && (
          <Card title="Agent Activity">
            <ResponsiveContainer width="100%" height={Math.min(160, data.agents.length * 28)}>
              <BarChart data={data.agents.slice(0, 6).map(a => ({ name: (a.hermes_agent_name || '').replace(/_/g, ' ').substring(0, 18), rows: a.c }))} layout="vertical" margin={{ top: 0, right: 10, left: 0, bottom: 0 }}>
                <XAxis type="number" hide />
                <YAxis type="category" dataKey="name" tick={{ fontSize: 9, fill: '#888' }} axisLine={false} tickLine={false} width={120} />
                <Tooltip contentStyle={{ fontSize: 10, background: '#1a1a2e', border: '1px solid #333' }} />
                <Bar dataKey="rows" fill="#4a90f4" radius={[0, 6, 6, 0]} barSize={14} cursor="pointer" />
              </BarChart>
            </ResponsiveContainer>
          </Card>
        )}

        {!filter && tlData && (
          <Card title="Timeline">
            {tlData.events.slice(0, 10).map((e, i) => {
              const c: Record<string, string> = { staged: '#888', promoted: '#4a90f4', embedded: '#0ecb81', event: '#f6be00' }
              return (
                <div key={i} style={{ display: 'flex', gap: 8, padding: '4px 0', borderBottom: '1px solid var(--border)', alignItems: 'center', fontSize: 10 }}>
                  <div style={{ width: 8, height: 8, borderRadius: '50%', background: c[e.type] || '#888', flexShrink: 0 }} />
                  <span style={{ color: c[e.type] || '#888', fontWeight: 600, minWidth: 55 }}>{e.type}</span>
                  {e.symbol && <span style={{ color: 'var(--text0)', fontWeight: 600 }}>{e.symbol}</span>}
                  <span style={{ color: 'var(--text3)', flex: 1 }}>{e.detail?.replace(/_/g, ' ') || ''}</span>
                  <span style={{ color: 'var(--text3)', fontSize: 9 }}>{e.at ? new Date(e.at).toLocaleTimeString() : ''}</span>
                </div>
              )
            })}
          </Card>
        )}

        {filter && drillData && (
          <Card title={`Results (${drillData.items.length})`}>
            <div style={{ display: 'grid', gap: 8, gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))' }}>
              {drillData.items.slice(0, 16).map(r => (
                <div key={r.id} onClick={() => setSelected(r)} style={{ ...hc, padding: '10px 12px', background: selected?.id === r.id ? 'var(--bg2)' : 'var(--bg1)', border: `1px solid ${selected?.id === r.id ? 'var(--accent)' : 'var(--border)'}`, borderRadius: 8 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                    <span style={{ fontWeight: 700, color: 'var(--text0)', fontSize: 12 }}>{r.symbol || 'SYS'}</span>
                    <span style={{ fontSize: 8, padding: '1px 5px', borderRadius: 4, background: r.status === 'promoted' ? 'rgba(74,144,244,.1)' : 'rgba(246,190,0,.08)', color: r.status === 'promoted' ? '#4a90f4' : '#f6be00' }}>{r.status}{r.embedded ? ' + RAG' : ''}</span>
                  </div>
                  <div style={{ fontSize: 10, color: 'var(--text2)', marginBottom: 4, lineHeight: 1.3, height: 26, overflow: 'hidden' }}>{r.topic}</div>
                  <div style={{ display: 'flex', gap: 4, fontSize: 9, color: 'var(--text3)' }}>
                    <span>{r.research_type?.replace(/_/g, ' ')}</span><span>·</span><span>conf {r.confidence_score}</span>
                  </div>
                </div>
              ))}
            </div>
          </Card>
        )}

        {!filter && (
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginTop: 8, fontSize: 9, color: 'var(--text3)' }}>
            <span>Total: {h.total}</span><span>·</span><span>Events: {data.events.total}</span><span>·</span>
            <span>Obs: {data.last_observation ? new Date(data.last_observation).toLocaleString() : 'N/A'}</span>
          </div>
        )}
      </div>

      {selected && (
        <div style={{ width: 300, flexShrink: 0, background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16, position: 'sticky', top: 12, maxHeight: '88vh', overflowY: 'auto' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
            <span style={{ fontSize: 14, fontWeight: 800, color: 'var(--text0)' }}>{selected.symbol || 'SYSTEM'}</span>
            <button onClick={() => setSelected(null)} style={{ fontSize: 11, width: 24, height: 24, border: '1px solid var(--border)', borderRadius: 6, background: 'var(--bg2)', color: 'var(--text3)', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>✕</button>
          </div>
          <div style={{ fontSize: 9, color: '#f6be00', marginBottom: 10, padding: '3px 8px', background: 'rgba(246,190,0,.06)', borderRadius: 6 }}>Advisory Only — Read-Only</div>
          <div style={{ fontSize: 11, color: 'var(--text1)', marginBottom: 8, lineHeight: 1.5 }}>{selected.topic}</div>
          <div style={{ fontSize: 10, color: 'var(--text2)', marginBottom: 12, lineHeight: 1.5 }}>{selected.summary}</div>
          <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginBottom: 12 }}>
            <span style={{ fontSize: 8, padding: '2px 6px', borderRadius: 4, background: selected.status === 'promoted' ? 'rgba(74,144,244,.12)' : 'rgba(246,190,0,.08)', color: selected.status === 'promoted' ? '#4a90f4' : '#f6be00' }}>{selected.status}</span>
            {selected.embedded && <span style={{ fontSize: 8, padding: '2px 6px', borderRadius: 4, background: 'rgba(14,203,129,.1)', color: '#0ecb81' }}>Embedded</span>}
            {selected.promoted_audit && <span style={{ fontSize: 8, padding: '2px 6px', borderRadius: 4, background: 'rgba(74,144,244,.08)', color: '#4a90f4' }}>Audit ✓</span>}
          </div>
          <div style={{ marginBottom: 12 }}>
            <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text2)', marginBottom: 6 }}>Quality</div>
            <ScoreBar label="Confidence" value={selected.confidence_score} />
            <ScoreBar label="Evidence" value={selected.source_urls_json && selected.source_urls_json !== '[]' ? 0.9 : 0.4} />
            <ScoreBar label="Freshness" value={0.9} />
            <ScoreBar label="Source" value={selected.source_urls_json && selected.source_urls_json !== '[]' ? 0.9 : 0.6} />
          </div>
          <div style={{ fontSize: 10, color: 'var(--text3)', lineHeight: 1.6 }}>
            <div><strong>ID:</strong> {selected.id}</div>
            <div><strong>Type:</strong> {selected.research_type?.replace(/_/g, ' ')}</div>
            <div><strong>Agent:</strong> {selected.hermes_agent_name?.replace(/_/g, ' ')}</div>
            <div><strong>Created:</strong> {selected.created_at ? new Date(selected.created_at).toLocaleString() : '?'}</div>
          </div>
        </div>
      )}
    </div>
  )
}
