import { useState } from 'react'
import { useApi } from '../hooks/useApi'
import type { DrillContext } from '../components/DetailDrawer'

interface Props { onDrill: (ctx: DrillContext) => void }
const TABS = ['Roster', 'Performance', 'Calibration'] as const

export default function AgentsHub({ onDrill }: Props) {
  const [tab, setTab] = useState<typeof TABS[number]>('Roster')
  const { data: summary } = useApi<any>('/api/v2/agents/summary', 120_000)

  const { data: perfData } = useApi<any>('/api/v2/agent-performance', 120_000)
  const { data: calData } = useApi<any>('/api/v2/agent-calibration/status', 120_000)
  const agents = summary?.agents ?? []
  const handoffs = summary?.handoffs ?? []

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 16 }}>
        <div>
          <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--text0)' }}>Agents</div>
          <div style={{ fontSize: 11, color: 'var(--text3)' }}>{agents.length} agents · {handoffs.length} recent handoffs</div>
        </div>
        <div style={{ display: 'flex', gap: 4 }}>
          {TABS.map(t => (
            <button key={t} onClick={() => setTab(t)} style={{
              padding: '4px 12px', fontSize: 11, borderRadius: 5, border: 'none', cursor: 'pointer',
              background: tab === t ? 'rgba(96,165,250,.15)' : 'var(--bg2)',
              color: tab === t ? '#60a5fa' : 'var(--text3)', fontWeight: tab === t ? 700 : 400,
            }}>{t}</button>
          ))}
        </div>
      </div>

      {tab === 'Roster' && (
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
          {agents.length === 0 ? <div style={{ color: 'var(--text3)', fontSize: 11 }}>No agent data from /agents/summary</div> :
          agents.map((a: any, i: number) => (
            <div key={i} onClick={() => onDrill({ title: a.name ?? a.agent_name ?? `Agent ${i}`, subtitle: a.role ?? a.type ?? '', endpoint: '/api/v2/agents/summary', rows: [a] })}
              style={{ display: 'flex', justifyContent: 'space-between', padding: '10px 8px', borderBottom: '1px solid var(--border)', cursor: 'pointer' }}>
              <div>
                <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text0)' }}>{a.name ?? a.agent_name ?? `Agent ${i}`}</div>
                <div style={{ fontSize: 9, color: 'var(--text3)' }}>{a.role ?? a.type ?? '—'}</div>
              </div>
              <div style={{ textAlign: 'right' }}>
                <div style={{ fontSize: 10, color: a.status === 'active' ? '#22c55e' : 'var(--text3)' }}>{a.status ?? '—'}</div>
              </div>
            </div>
          ))}
          <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 8 }}>Source: /api/v2/agents/summary</div>
        </div>
      )}

      {tab === 'Performance' && perfData && (
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 10 }}>Agent Performance History</div>
          {(perfData.history ?? []).length === 0 ? <div style={{ color: 'var(--text3)', fontSize: 11 }}>No performance history recorded</div> :
          (perfData.history ?? []).slice(0, 15).map((h: any, i: number) => (
            <div key={i} onClick={() => onDrill({ title: h.agent_name ?? `Entry ${i}`, subtitle: 'Performance', endpoint: '/api/v2/agent-performance', rows: [h] })}
              style={{ padding: '6px 6px', borderBottom: '1px solid var(--border)', cursor: 'pointer', fontSize: 11, color: 'var(--text2)' }}>
              {h.agent_name ?? ''}: {h.metric ?? ''} = {h.value ?? JSON.stringify(h).slice(0, 80)}
            </div>
          ))}
          <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 8 }}>Source: /api/v2/agent-performance</div>
        </div>
      )}

      {tab === 'Calibration' && calData && (
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 10 }}>Agent Calibration</div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 10, marginBottom: 12 }}>
            {['recommendations_total', 'calibration_events_total', 'disagreements_total'].map(k => (
              <div key={k} style={{ background: 'var(--bg2)', borderRadius: 8, padding: '8px 10px', textAlign: 'center' }}>
                <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--text0)' }}>{calData[k] ?? 0}</div>
                <div style={{ fontSize: 9, color: 'var(--text3)' }}>{k.replace(/_/g, ' ')}</div>
              </div>
            ))}
          </div>
          <div style={{ fontSize: 8, color: 'var(--text3)' }}>Source: /api/v2/agent-calibration/status</div>
        </div>
      )}
    </div>
  )
}
