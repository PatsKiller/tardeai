import { useState } from 'react'
import { useApi } from '../hooks/useApi'
import type { DrillContext } from '../components/DetailDrawer'

interface Props { onDrill: (ctx: DrillContext) => void }
const TABS = ['Roster', 'Performance', 'Calibration'] as const

export default function AgentsHub({ onDrill }: Props) {
  const [tab, setTab] = useState<typeof TABS[number]>('Roster')
  const { data: summary } = useApi<any>('/api/v2/agents/summary', 120_000)

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

      {tab === 'Performance' && <div style={{ color: 'var(--text3)', fontSize: 12, padding: 20 }}>Agent performance — awaiting data integration</div>}
      {tab === 'Calibration' && <div style={{ color: 'var(--text3)', fontSize: 12, padding: 20 }}>Agent calibration — awaiting data integration</div>}
    </div>
  )
}
