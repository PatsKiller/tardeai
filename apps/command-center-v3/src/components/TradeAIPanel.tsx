import { useState } from 'react'
import { useApi } from '../hooks/useApi'
import AgentSoulEditor from './AgentSoulEditor'
import { openClawCollisionNote } from '../lib/agentSubsystem'

// Command Center → System → TradeAI. Read-only TradeAI agent fleet (roles/model/calibration).
// Advisory personas expose an editable SOUL (shared with OpenClaw); algorithmic agents are read-only —
// their operational config (config/agents.yaml thresholds/routing) is safety-locked, never edited here.
export default function TradeAIPanel() {
  const { data: fl } = useApi<any>('/api/v2/tradeai/fleet', 60_000)
  const [editAgent, setEditAgent] = useState<{ id: string; title: string } | null>(null)

  const card: React.CSSProperties = { background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 8, padding: 14, marginBottom: 14 }
  const agents = fl?.agents || []
  const advisory = agents.filter((a: any) => a.type === 'advisory')
  const algo = agents.filter((a: any) => a.type === 'algorithmic')

  const row = (a: any) => (
    <tr key={a.agent} style={{ borderBottom: '1px solid var(--border)' }}>
      <td style={{ padding: '6px 8px', fontWeight: 600 }}>{a.agent}{openClawCollisionNote(a.soul_agent || a.agent) ? ' (Advisory)' : ''}</td>
      <td style={{ padding: '6px 8px', color: 'var(--text3)' }}>{a.role}</td>
      <td style={{ padding: '6px 8px' }}><code>{a.runtime_model}</code></td>
      <td style={{ padding: '6px 8px', color: a.type === 'advisory' ? '#60a5fa' : '#f59e0b' }}>{a.type}</td>
      <td style={{ padding: '6px 8px', color: 'var(--text3)' }}>{a.calibration || '—'}</td>
      <td style={{ padding: '6px 8px' }}>
        {a.soul_editable
          ? <button onClick={() => setEditAgent({ id: a.soul_agent, title: a.agent })} style={{ fontSize: 11, padding: '2px 8px', border: '1px solid var(--border)', borderRadius: 4, background: 'var(--bg1)', color: '#60a5fa', cursor: 'pointer' }}>Edit Identity</button>
          : <span style={{ fontSize: 10, color: 'var(--text3)' }}>config-locked</span>}
      </td>
    </tr>
  )

  return (
    <div>
      {editAgent && <AgentSoulEditor agent={editAgent.id} title={editAgent.title} onClose={() => setEditAgent(null)} />}

      <div style={card}>
        <div style={{ fontWeight: 700, marginBottom: 8 }}>TradeAI Agent Fleet</div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(230px,1fr))', gap: 6 }}>
          <div style={{ fontSize: 12, color: 'var(--text3)' }}>Runtime model: <b style={{ color: 'var(--text1)' }}>{fl?.runtime_model || '…'}</b></div>
          <div style={{ fontSize: 12, color: 'var(--text3)' }}>Agents: <b style={{ color: 'var(--text1)' }}>{agents.length}</b> ({advisory.length} advisory · {algo.length} algorithmic)</div>
        </div>
        <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 6 }}>ℹ {fl?.note}</div>
        <div style={{ fontSize: 10, color: '#f59e0b', marginTop: 6, lineHeight: 1.45 }}>
          Names like Aegis, Alex, Steph, and Maria also exist as governed FLEET critics on Agents → Runtime. Those are separate roles with no shared SOUL, dispatch, or memory.
        </div>
      </div>

      <div style={card}>
        <div style={{ fontWeight: 700, marginBottom: 8 }}>Advisory Personas <span style={{ fontSize: 10, color: 'var(--text3)', fontWeight: 400 }}>— editable SOUL (shared with OpenClaw)</span></div>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
          <thead><tr style={{ color: 'var(--text3)', textAlign: 'left' }}>
            {['Agent', 'Role', 'Model', 'Type', 'Calibration', 'Actions'].map(h => <th key={h} style={{ padding: '4px 8px', borderBottom: '1px solid var(--border)' }}>{h}</th>)}
          </tr></thead>
          <tbody>{advisory.map(row)}</tbody>
        </table>
      </div>

      <div style={card}>
        <div style={{ fontWeight: 700, marginBottom: 8 }}>Algorithmic Agents <span style={{ fontSize: 10, color: '#f59e0b', fontWeight: 400 }}>— config-locked (no SOUL; thresholds/routing not editable here)</span></div>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
          <thead><tr style={{ color: 'var(--text3)', textAlign: 'left' }}>
            {['Agent', 'Role', 'Model', 'Type', 'Calibration', 'Actions'].map(h => <th key={h} style={{ padding: '4px 8px', borderBottom: '1px solid var(--border)' }}>{h}</th>)}
          </tr></thead>
          <tbody>{algo.map(row)}</tbody>
        </table>
      </div>
      <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 4 }}>Source: /api/v2/tradeai/fleet · roles from config/agents.yaml · advisory SOULs editable (backup-first, validated) · operational config never edited here.</div>
    </div>
  )
}
