import { useState, useCallback, useEffect } from 'react'
import { useSearchParams } from 'react-router-dom'
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
  display_category?: string
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
        <div style={{ width: `${pct}%`, height: '100%', background: color, borderRadius: 4, transition: 'width .3s' }} />
      </div>
      <span style={{ width: 28, textAlign: 'right', color, fontSize: 9, fontWeight: 600 }}>{pct.toFixed(0)}%</span>
    </div>
  )
}

function Clickable({ children, onClick, active, style }: { children: React.ReactNode; onClick: () => void; active?: boolean; style?: React.CSSProperties }) {
  return (
    <div onClick={onClick} style={{
      cursor: 'pointer', transition: 'all .15s',
      border: active ? '2px solid var(--accent)' : '1px solid var(--border)',
      borderRadius: 10, ...style,
    }}
    onMouseEnter={e => { (e.currentTarget as HTMLDivElement).style.transform = 'translateY(-1px)'; (e.currentTarget as HTMLDivElement).style.boxShadow = '0 2px 8px rgba(0,0,0,.15)' }}
    onMouseLeave={e => { (e.currentTarget as HTMLDivElement).style.transform = ''; (e.currentTarget as HTMLDivElement).style.boxShadow = '' }}
    >{children}</div>
  )
}

export default function SelfLearningOverview() {
  const [sp, setSp] = useSearchParams()
  const [rk, setRk] = useState(0)

  const view = sp.get('view') || 'overview'
  const filterKey = sp.get('filter') || ''
  const selectedId = sp.get('item') ? parseInt(sp.get('item')!) : null

  const navigate = useCallback((v: string, f?: string, item?: number) => {
    const p: Record<string, string> = { view: v }
    if (f) p.filter = f
    if (item) p.item = String(item)
    setSp(p, { replace: false })
  }, [setSp])

  const goOverview = useCallback(() => navigate('overview'), [navigate])
  const goDrill = useCallback((f: string) => navigate('drilldown', f), [navigate])
  const goItem = useCallback((id: number) => {
    const p = new URLSearchParams(sp)
    p.set('item', String(id))
    if (!p.get('view') || p.get('view') === 'overview') p.set('view', 'drilldown')
    setSp(p, { replace: false })
  }, [sp, setSp])
  const closeItem = useCallback(() => {
    const p = new URLSearchParams(sp)
    p.delete('item')
    setSp(p, { replace: false })
  }, [sp, setSp])

  const { data } = useApi<OverviewData>(`/api/v2/hermes/self-learning-overview?_r=${rk}`)
  const { data: drillData } = useApi<{ items: DrillItem[] }>(view === 'drilldown' && filterKey ? `/api/v2/hermes/self-learning/drilldown?_r=${rk}&${filterKey}` : null)
  const { data: tlData } = useApi<{ events: TLEvent[] }>(`/api/v2/hermes/self-learning/timeline?_r=${rk}`)

  const selected = drillData?.items.find(i => i.id === selectedId) || null

  if (!data) return <div style={{ padding: 24, color: 'var(--text2)' }}>Loading...</div>

  const h = data.hermes
  const needsAttention = (data.promotion_lanes.READY_FOR_OPERATOR_REVIEW || 0) + (data.promotion_lanes.NEEDS_RESEARCH || 0)
  const blocked = (data.promotion_lanes.AUTO_REJECT || 0) + (h.ops_backlog || 0)
  const newToday = tlData?.events.filter(e => { const d = new Date(e.at); const n = new Date(); return d.toDateString() === n.toDateString() }).length || 0

  return (
    <div style={{ display: 'flex', gap: 14, minHeight: '80vh' }}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <PageHeader title="Self-Learning Overview" subtitle="What needs your attention?" actions={
          <button onClick={() => setRk(k => k + 1)} style={{ fontSize: 10, padding: '3px 10px', border: '1px solid var(--border)', borderRadius: 6, background: 'var(--bg2)', color: 'var(--text1)', cursor: 'pointer' }}>↻ Refresh</button>
        } />

        {/* ── Breadcrumb ── */}
        <div style={{ display: 'flex', gap: 4, alignItems: 'center', marginBottom: 10, fontSize: 10 }}>
          <span onClick={goOverview} style={{ cursor: 'pointer', color: view === 'overview' ? 'var(--text0)' : 'var(--accent)', fontWeight: view === 'overview' ? 700 : 400, textDecoration: view !== 'overview' ? 'underline' : 'none' }}>Overview</span>
          {view === 'drilldown' && <>
            <span style={{ color: 'var(--text3)' }}>›</span>
            <span style={{ color: 'var(--text0)', fontWeight: 700 }}>Drilldown{filterKey ? `: ${filterKey.split('=')[1]}` : ''}</span>
          </>}
          {selectedId && <>
            <span style={{ color: 'var(--text3)' }}>›</span>
            <span style={{ color: 'var(--text0)', fontWeight: 700 }}>Item #{selectedId}</span>
          </>}
        </div>

        {/* ── Status Strip ── */}
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 12 }}>
          <span style={{ fontSize: 9, padding: '2px 10px', borderRadius: 12, background: 'rgba(14,203,129,.12)', color: '#0ecb81', fontWeight: 700 }}>{data.maturity}</span>
          <span style={{ fontSize: 9, padding: '2px 10px', borderRadius: 12, background: 'rgba(234,57,67,.08)', color: '#ea3943' }}>Level 7: {data.level7}</span>
          <span style={{ fontSize: 9, padding: '2px 10px', borderRadius: 12, background: data.feed_health.status === 'RUN_HEALTHY' ? 'rgba(14,203,129,.08)' : 'rgba(246,190,0,.12)', color: data.feed_health.status === 'RUN_HEALTHY' ? '#0ecb81' : '#f6be00' }}>Feed {data.feed_health.symbols} sym</span>
          <span style={{ fontSize: 9, padding: '2px 10px', borderRadius: 12, background: 'rgba(74,144,244,.08)', color: '#4a90f4' }}>LLM {data.llm_queue.completed}/{data.llm_queue.total}</span>
        </div>

        {/* ══════ OVERVIEW VIEW ══════ */}
        {view === 'overview' && <>
          {/* Attention Row */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: 10, marginBottom: 14 }}>
            {[
              { label: '⚡ Needs Attention', value: needsAttention, color: '#f6be00', f: 'status=staged' },
              { label: '🆕 New Today', value: newToday, color: '#4a90f4', f: '' },
              { label: '🚫 Blocked / Stale', value: blocked, color: '#ea3943', f: 'type=ops_backlog' },
              { label: '✓ Auto-Promoted', value: 3, color: '#0ecb81', f: 'status=promoted' },
            ].map((c, i) => (
              <Clickable key={i} onClick={() => c.f && goDrill(c.f)} active={false} style={{ padding: '12px 14px', background: `${c.color}08` }}>
                <div style={{ fontSize: 24, fontWeight: 800, color: c.color }}>{c.value}</div>
                <div style={{ fontSize: 10, color: 'var(--text2)', marginTop: 2 }}>{c.label}</div>
              </Clickable>
            ))}
          </div>

          {/* Workflow Lanes */}
          <Card title="Workflow Lanes — click to drill">
            <div style={{ display: 'flex', gap: 8, overflowX: 'auto', paddingBottom: 4 }}>
              {Object.entries(data.promotion_lanes).filter(([, v]) => v > 0).map(([lane, count]) => {
                const cfg = laneConfig[lane] || { color: '#888', icon: '?', label: lane }
                return (
                  <Clickable key={lane} onClick={() => goDrill('status=staged')} style={{ minWidth: 110, padding: '10px 12px', background: `${cfg.color}08` }}>
                    <div style={{ fontSize: 12, marginBottom: 4 }}>{cfg.icon}</div>
                    <div style={{ fontSize: 22, fontWeight: 800, color: cfg.color }}>{count}</div>
                    <div style={{ fontSize: 9, color: 'var(--text3)' }}>{cfg.label}</div>
                  </Clickable>
                )
              })}
            </div>
          </Card>

          {/* Pipeline Flow */}
          <Card title="Research Pipeline — click any stage">
            <div style={{ display: 'flex', alignItems: 'center', gap: 3, flexWrap: 'wrap' }}>
              {[
                { name: 'Discovery', count: 8, color: '#4a90f4', f: 'type=source_discovery' },
                { name: 'Backlog', count: h.backlog, color: '#f6be00', f: 'type=research_backlog' },
                { name: 'Staged', count: h.staged - h.backlog, color: '#888', f: 'status=staged' },
                { name: 'Cache', count: data.cache_sections, color: '#0ecb81', f: 'status=promoted' },
                { name: 'Embedded', count: data.embeddings, color: '#4a90f4', f: 'status=staged' },
                { name: 'Promoted', count: h.promoted, color: '#0ecb81', f: 'status=promoted' },
              ].map((s, i) => (
                <div key={s.name} style={{ display: 'flex', alignItems: 'center', gap: 3 }}>
                  <Clickable onClick={() => goDrill(s.f)} style={{ padding: '8px 10px', background: `${s.color}0a`, textAlign: 'center', minWidth: 55 }}>
                    <div style={{ fontSize: 16, fontWeight: 700, color: s.color }}>{s.count}</div>
                    <div style={{ fontSize: 8, color: 'var(--text3)' }}>{s.name}</div>
                  </Clickable>
                  {i < 5 && <span style={{ color: 'var(--text3)', fontSize: 11 }}>→</span>}
                </div>
              ))}
            </div>
          </Card>

          {/* Queue Aging */}
          {data.age_buckets.length > 0 && (
            <Card title="Queue Aging — click bar to drill">
              <ResponsiveContainer width="100%" height={100}>
                <BarChart data={data.age_buckets} margin={{ top: 5, right: 5, left: 0, bottom: 0 }}>
                  <XAxis dataKey="bucket" tick={{ fontSize: 10, fill: '#888' }} axisLine={false} tickLine={false} />
                  <YAxis hide />
                  <Tooltip contentStyle={{ fontSize: 11, background: '#1a1a2e', border: '1px solid #333', borderRadius: 6 }} />
                  <Bar dataKey="c" radius={[6, 6, 0, 0]} cursor="pointer" onClick={() => goDrill('status=staged')}>
                    {data.age_buckets.map((b, i) => (
                      <Cell key={i} fill={b.bucket === '8d+' ? '#ea3943' : b.bucket === '4-7d' ? '#f6be00' : '#4a90f4'} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </Card>
          )}

          {/* Agent Activity */}
          {data.agents.length > 0 && (
            <Card title="Agent Activity — click bar to drill">
              <ResponsiveContainer width="100%" height={Math.min(160, data.agents.length * 28)}>
                <BarChart data={data.agents.slice(0, 6).map(a => ({ name: (a.hermes_agent_name || '').replace(/_/g, ' ').substring(0, 18), rows: a.c, raw: a.hermes_agent_name }))} layout="vertical" margin={{ top: 0, right: 10, left: 0, bottom: 0 }}>
                  <XAxis type="number" hide />
                  <YAxis type="category" dataKey="name" tick={{ fontSize: 9, fill: '#888' }} axisLine={false} tickLine={false} width={120} />
                  <Tooltip contentStyle={{ fontSize: 10, background: '#1a1a2e', border: '1px solid #333' }} />
                  <Bar dataKey="rows" fill="#4a90f4" radius={[0, 6, 6, 0]} barSize={14} cursor="pointer" onClick={(_: any, idx: number) => { const a = data.agents[idx]; if (a) goDrill(`agent=${a.hermes_agent_name}`) }} />
                </BarChart>
              </ResponsiveContainer>
            </Card>
          )}

          {/* Timeline */}
          {tlData && (
            <Card title="Timeline — click event to see detail">
              {tlData.events.slice(0, 10).map((e, i) => {
                const c: Record<string, string> = { staged: '#888', promoted: '#4a90f4', embedded: '#0ecb81', event: '#f6be00' }
                return (
                  <div key={i} onClick={() => { goDrill('status=staged'); goItem(e.id) }} style={{ display: 'flex', gap: 8, padding: '4px 0', borderBottom: '1px solid var(--border)', alignItems: 'center', fontSize: 10, cursor: 'pointer' }}
                    onMouseEnter={ev => (ev.currentTarget.style.background = 'var(--bg2)')}
                    onMouseLeave={ev => (ev.currentTarget.style.background = '')}>
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

          {/* Footer */}
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginTop: 8, fontSize: 9, color: 'var(--text3)' }}>
            <span>Total: {h.total}</span><span>·</span><span>Events: {data.events.total}</span><span>·</span>
            <span>Obs: {data.last_observation ? new Date(data.last_observation).toLocaleString() : 'N/A'}</span>
          </div>
        </>}

        {/* ══════ DRILLDOWN VIEW ══════ */}
        {view === 'drilldown' && drillData && (
          <Card title={`Results: ${filterKey.split('=')[1] || 'all'} (${drillData.items.length} items)`}>
            <div style={{ display: 'grid', gap: 8, gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))' }}>
              {drillData.items.slice(0, 20).map(r => (
                <Clickable key={r.id} onClick={() => goItem(r.id)} active={selectedId === r.id} style={{ padding: '10px 12px', background: selectedId === r.id ? 'var(--bg2)' : 'var(--bg1)' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                    <span style={{ fontWeight: 700, color: 'var(--text0)', fontSize: 12 }}>{r.display_category || r.symbol || 'SYS'}</span>
                    <span style={{ fontSize: 8, padding: '1px 5px', borderRadius: 4, background: r.status === 'promoted' ? 'rgba(74,144,244,.1)' : 'rgba(246,190,0,.08)', color: r.status === 'promoted' ? '#4a90f4' : '#f6be00' }}>{r.status}{r.embedded ? ' + RAG' : ''}</span>
                  </div>
                  <div style={{ fontSize: 10, color: 'var(--text2)', marginBottom: 4, lineHeight: 1.3, height: 26, overflow: 'hidden' }}>{r.topic}</div>
                  <div style={{ display: 'flex', gap: 4, fontSize: 9, color: 'var(--text3)' }}>
                    <span>{r.research_type?.replace(/_/g, ' ')}</span><span>·</span><span>conf {r.confidence_score}</span>
                  </div>
                </Clickable>
              ))}
            </div>
          </Card>
        )}
      </div>

      {/* ══════ PERSISTENT DETAIL DRAWER ══════ */}
      {selected && (
        <div style={{ width: 300, flexShrink: 0, background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16, position: 'sticky', top: 12, maxHeight: '88vh', overflowY: 'auto' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
            <span style={{ fontSize: 14, fontWeight: 800, color: 'var(--text0)' }}>{selected.display_category || selected.symbol || 'SYSTEM'}</span>
            <button onClick={closeItem} style={{ fontSize: 11, width: 24, height: 24, border: '1px solid var(--border)', borderRadius: 6, background: 'var(--bg2)', color: 'var(--text3)', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>✕</button>
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
          <div style={{ fontSize: 10, color: 'var(--text3)', lineHeight: 1.7 }}>
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
