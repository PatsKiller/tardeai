import { useState } from 'react'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import { useApi } from '../hooks/useApi'

interface SiemEvent {
  id: string; timestamp: string; source: string; event_type: string; severity: string
  symbol: string | null; component: string | null; message: string
  dedupe_key: string; repeat_count: number; suppressed: boolean
}

interface DedupeGroup {
  key: string; count: number; severity: string; event_type: string
  component: string | null; first: string; last: string
}

interface TypeCount { type: string; count: number }

interface SiemData {
  total_events: number; suppressed: number; noise_reduction_pct: number; immediate_alerts: number
  severity: Record<string, number>
  type_counts: TypeCount[]
  top_dedupe_groups: DedupeGroup[]
  recent_events: SiemEvent[]
  period_days: number
}

const sevColor: Record<string, string> = { P0: '#ef4444', P1: '#f59e0b', P2: '#3b82f6', P3: '#6b7280' }
const sevBg: Record<string, string> = { P0: 'rgba(239,68,68,.1)', P1: 'rgba(245,158,11,.1)', P2: 'rgba(59,130,246,.08)', P3: 'rgba(107,114,128,.08)' }

function timeAgo(iso: string) {
  if (!iso) return '—'
  const ms = Date.now() - new Date(iso).getTime()
  const h = Math.floor(ms / 3600000)
  if (h < 1) return `${Math.floor(ms / 60000)}m ago`
  if (h < 24) return `${h}h ago`
  return `${Math.floor(h / 24)}d ago`
}

export default function SiemDashboard() {
  const { data } = useApi<SiemData>('/api/v2/system/siem', 60_000)
  const [filter, setFilter] = useState<string>('')
  const [showSuppressed, setShowSuppressed] = useState(true)
  const [expandedId, setExpandedId] = useState<string | null>(null)

  if (!data) return <div style={{ padding: 24, color: 'var(--text2)' }}>Loading SIEM data...</div>

  const filtered = data.recent_events.filter(e => {
    if (!showSuppressed && e.suppressed) return false
    if (filter && e.event_type !== filter && e.severity !== filter) return false
    return true
  })

  return (
    <div style={{ padding: '20px 24px', maxWidth: 1400, margin: '0 auto' }}>
      <PageHeader title="Alert SIEM" subtitle={`${data.total_events} raw events · ${data.period_days}-day retention · ${data.noise_reduction_pct}% noise reduction`} />

      {/* KPI Row — clickable */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)', gap: 10, marginBottom: 16 }}>
        {[
          { label: 'Total Events', value: data.total_events, color: 'var(--text0)', click: '' },
          { label: 'Immediate (P0/P1)', value: data.immediate_alerts, color: data.immediate_alerts > 0 ? '#f59e0b' : '#22c55e', click: 'P1' },
          { label: 'Suppressed', value: data.suppressed, color: '#6b7280', click: '' },
          { label: 'Noise Reduction', value: `${data.noise_reduction_pct}%`, color: '#22c55e', click: '' },
          { label: 'P1 Active', value: data.severity.P1 || 0, color: '#f59e0b', click: 'P1' },
          { label: 'P2 Monitor', value: data.severity.P2 || 0, color: '#3b82f6', click: 'P2' },
        ].map(k => (
          <div key={k.label} onClick={() => { if (k.click !== undefined) setFilter(k.click) }}
            style={{ background: 'var(--bg1)', border: `1px solid ${filter === k.click && k.click ? 'var(--accent)' : 'var(--border)'}`, borderRadius: 10, padding: '14px 16px', textAlign: 'center', cursor: 'pointer', transition: 'border-color .15s' }}>
            <div style={{ fontSize: 24, fontWeight: 700, color: k.color }}>{k.value}</div>
            <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 4 }}>{k.label}</div>
          </div>
        ))}
      </div>

      {/* Severity bar — clickable */}
      <div style={{ display: 'flex', gap: 4, marginBottom: 16, height: 10, borderRadius: 5, overflow: 'hidden' }}>
        {['P0', 'P1', 'P2', 'P3'].map(s => {
          const pct = data.total_events > 0 ? ((data.severity[s] || 0) / data.total_events * 100) : 0
          return pct > 0 ? <div key={s} onClick={() => setFilter(s)} style={{ width: `${pct}%`, background: sevColor[s], minWidth: 4, cursor: 'pointer', opacity: filter === s ? 1 : 0.7, transition: 'opacity .15s' }} title={`${s}: ${data.severity[s]} — click to filter`} /> : null
        })}
        {data.suppressed > 0 && <div onClick={() => { setFilter(''); setShowSuppressed(true) }} style={{ width: `${data.noise_reduction_pct}%`, background: 'rgba(107,114,128,0.3)', minWidth: 4, cursor: 'pointer' }} title={`Suppressed: ${data.suppressed}`} />}
      </div>

      <div style={{ display: 'flex', gap: 16 }}>
        {/* Left: Event stream */}
        <div style={{ flex: 1, minWidth: 0 }}>
          {/* Filters */}
          <div style={{ display: 'flex', gap: 6, marginBottom: 12, flexWrap: 'wrap', alignItems: 'center' }}>
            <span style={{ fontSize: 9, color: 'var(--text3)', textTransform: 'uppercase', fontWeight: 600 }}>Filter</span>
            {['', 'P1', 'P2', 'STOP_TRIGGERED', 'PIPELINE_FAILURE', 'AGENT_STALENESS', 'FEED_HEALTH', 'DATA_QUALITY'].map(f => (
              <button key={f} onClick={() => setFilter(f)} style={{
                fontSize: 10, padding: '3px 10px', borderRadius: 6, cursor: 'pointer', border: 'none',
                background: filter === f ? 'rgba(59,130,246,.2)' : 'var(--bg2)',
                color: filter === f ? '#60a5fa' : 'var(--text3)',
              }}>{f || 'All'}</button>
            ))}
            <label style={{ fontSize: 10, color: 'var(--text3)', display: 'flex', alignItems: 'center', gap: 4, marginLeft: 8 }}>
              <input type="checkbox" checked={showSuppressed} onChange={e => setShowSuppressed(e.target.checked)} />
              Show suppressed
            </label>
          </div>

          {/* Event list */}
          <Card title={`Events (${filtered.length} groups${showSuppressed ? '' : ' — active only'})`}>
            <div style={{ maxHeight: 600, overflowY: 'auto' }}>
              {filtered.map(e => (
                <div key={e.id}>
                  <div onClick={() => setExpandedId(expandedId === e.id ? null : e.id)} style={{
                    display: 'flex', gap: 8, padding: '8px 10px', borderBottom: expandedId === e.id ? 'none' : '1px solid var(--border)',
                    opacity: e.suppressed ? 0.5 : 1, cursor: 'pointer',
                    background: expandedId === e.id ? 'var(--bg2)' : e.severity === 'P1' && !e.suppressed ? 'rgba(245,158,11,.04)' : 'transparent',
                  }}>
                    {/* Severity badge */}
                    <span style={{ fontSize: 9, fontWeight: 700, padding: '2px 6px', borderRadius: 4, background: sevBg[e.severity], color: sevColor[e.severity], minWidth: 22, textAlign: 'center', flexShrink: 0 }}>
                      {e.severity}
                    </span>
                    {/* Type badge */}
                    <span style={{ fontSize: 8, padding: '2px 6px', borderRadius: 4, background: 'var(--bg2)', color: 'var(--text2)', minWidth: 80, textAlign: 'center', flexShrink: 0, whiteSpace: 'nowrap' }}>
                      {e.event_type.replace(/_/g, ' ')}
                    </span>
                    {/* Symbol */}
                    {e.symbol && <span style={{ fontSize: 11, fontWeight: 700, color: 'var(--text0)', minWidth: 40, flexShrink: 0 }}>{e.symbol}</span>}
                    {/* Message */}
                    <span style={{ fontSize: 10, color: 'var(--text2)', flex: 1, lineHeight: 1.4, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{e.message}</span>
                    {/* Repeat count */}
                    {e.repeat_count > 1 && <span style={{ fontSize: 9, color: '#f59e0b', fontWeight: 600, flexShrink: 0 }}>×{e.repeat_count}</span>}
                    {/* Time */}
                    <span style={{ fontSize: 9, color: 'var(--text3)', minWidth: 50, textAlign: 'right', flexShrink: 0 }}>{timeAgo(e.timestamp)}</span>
                  </div>
                  {/* Expanded detail */}
                  {expandedId === e.id && (
                    <div style={{ padding: '10px 14px 12px', background: 'var(--bg2)', borderBottom: '1px solid var(--border)', fontSize: 10, lineHeight: 1.6 }}>
                      <div style={{ color: 'var(--text1)', marginBottom: 6, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>{e.message}</div>
                      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8, color: 'var(--text3)' }}>
                        <div><strong>Type:</strong> {e.event_type}</div>
                        <div><strong>Source:</strong> {e.source}</div>
                        <div><strong>Component:</strong> {e.component || '—'}</div>
                        <div><strong>Symbol:</strong> {e.symbol || '—'}</div>
                        <div><strong>Severity:</strong> <span style={{ color: sevColor[e.severity] }}>{e.severity}</span></div>
                        <div><strong>Repeats:</strong> {e.repeat_count}×</div>
                        <div><strong>Timestamp:</strong> {e.timestamp ? new Date(e.timestamp).toLocaleString() : '—'}</div>
                        <div><strong>Dedupe Key:</strong> <span style={{ fontFamily: 'monospace', fontSize: 9 }}>{e.dedupe_key}</span></div>
                        <div><strong>Status:</strong> {e.suppressed ? 'Suppressed (noise)' : 'Active'}</div>
                      </div>
                    </div>
                  )}
                </div>
              ))}
              {filtered.length === 0 && <div style={{ padding: 20, textAlign: 'center', color: 'var(--text3)', fontSize: 12 }}>No events match current filter.</div>}
            </div>
          </Card>
        </div>

        {/* Right: Dedupe groups */}
        <div style={{ width: 320, flexShrink: 0 }}>
          <Card title="Top Repeat Groups">
            {data.top_dedupe_groups.map((g, i) => {
              const parts = g.key.split(':')
              return (
                <div key={i} style={{ padding: '8px 10px', borderBottom: '1px solid var(--border)', cursor: 'pointer' }}
                     onClick={() => setFilter(g.event_type)}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 2 }}>
                    <span style={{ fontSize: 10, fontWeight: 600, color: 'var(--text1)' }}>{g.event_type.replace(/_/g, ' ')}</span>
                    <span style={{ fontSize: 14, fontWeight: 800, color: g.count > 10 ? '#f59e0b' : 'var(--text2)' }}>{g.count}×</span>
                  </div>
                  <div style={{ fontSize: 9, color: 'var(--text3)' }}>
                    {g.component || parts[2] || '—'} · <span style={{ color: sevColor[g.severity] }}>{g.severity}</span>
                  </div>
                  <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 2 }}>
                    {timeAgo(g.first)} → {timeAgo(g.last)}
                  </div>
                </div>
              )
            })}
          </Card>

          <div style={{ marginTop: 12 }}>
            <Card title="Event Types">
              {data.type_counts.map(tc => (
                <div key={tc.type} onClick={() => setFilter(tc.type)} style={{
                  display: 'flex', justifyContent: 'space-between', padding: '4px 10px', fontSize: 10,
                  color: 'var(--text2)', cursor: 'pointer', borderBottom: '1px solid var(--border)',
                }}>
                  <span>{tc.type.replace(/_/g, ' ')}</span>
                  <span style={{ fontWeight: 600 }}>{tc.count}</span>
                </div>
              ))}
            </Card>
          </div>
        </div>
      </div>
    </div>
  )
}
