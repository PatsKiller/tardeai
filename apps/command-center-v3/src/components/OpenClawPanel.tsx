import { useState } from 'react'
import { useApi } from '../hooks/useApi'
import AgentSoulEditor from './AgentSoulEditor'

// Command Center → System → OpenClaw. Read-only inventory of the OpenClaw ecosystem
// (agents + skills + channels + gateway), with safe editable agent SOULs. Mirrors the Hermes tab.
export default function OpenClawPanel() {
  const { data: st } = useApi<any>('/api/v2/openclaw/status', 60_000)
  const [editAgent, setEditAgent] = useState<{ id: string; title: string } | null>(null)

  const card: React.CSSProperties = { background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 8, padding: 14, marginBottom: 14 }
  const kv: React.CSSProperties = { fontSize: 12, color: 'var(--text3)' }
  const gwOk = (st?.gateway_active || '') === 'active'

  return (
    <div>
      {editAgent && <AgentSoulEditor agent={editAgent.id} title={editAgent.title} onClose={() => setEditAgent(null)} />}

      {/* Status card */}
      <div style={card}>
        <div style={{ fontWeight: 700, marginBottom: 8 }}>OpenClaw Ecosystem</div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(230px,1fr))', gap: 6 }}>
          <div style={kv}>Home: <code>{st?.home}</code></div>
          <div style={kv}>Primary model: <b style={{ color: 'var(--text1)' }}>{st?.model_primary || '…'}</b></div>
          <div style={kv}>Gateway: <b style={{ color: gwOk ? '#22c55e' : '#ef4444' }}>{st?.gateway_active} / {st?.gateway_enabled}</b></div>
          <div style={kv}>Agents: <b style={{ color: 'var(--text1)' }}>{st?.agents?.length ?? '…'}</b></div>
          <div style={kv}>Skills: <b style={{ color: 'var(--text1)' }}>{st?.skills_catalog?.length ?? '…'}</b></div>
        </div>
        {st?.model_fallbacks?.length > 0 && <div style={{ ...kv, marginTop: 6 }}>Fallbacks: {st.model_fallbacks.join(' → ')}</div>}
        <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 6 }}>ℹ {st?.warning}</div>
      </div>

      {/* Agents */}
      <div style={card}>
        <div style={{ fontWeight: 700, marginBottom: 8 }}>Agents</div>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
          <thead><tr style={{ color: 'var(--text3)', textAlign: 'left' }}>
            {['Agent', 'Identity', 'Model', 'Registration', 'SOUL', 'Actions'].map(h => <th key={h} style={{ padding: '4px 8px', borderBottom: '1px solid var(--border)' }}>{h}</th>)}
          </tr></thead>
          <tbody>
            {(st?.agents || []).map((a: any) => (
              <tr key={a.id} style={{ borderBottom: '1px solid var(--border)', opacity: a.registered === false ? 0.85 : 1 }}>
                <td style={{ padding: '6px 8px', fontWeight: 600 }}>{a.emoji ? a.emoji + ' ' : ''}{a.name}</td>
                <td style={{ padding: '6px 8px', color: 'var(--text3)' }}>{a.identity_name || (a.registered === false ? `unregistered · ${(a.skills || []).length} skill(s)` : '—')}</td>
                <td style={{ padding: '6px 8px' }}>{a.model ? <code>{a.model}</code> : '—'}</td>
                <td style={{ padding: '6px 8px', color: a.registered === false ? '#f59e0b' : '#22c55e' }}>{a.registered === false ? 'unregistered' : 'registered'}</td>
                <td style={{ padding: '6px 8px', color: a.soul_exists ? '#22c55e' : 'var(--text3)' }}>{a.soul_exists ? 'present' : '—'}</td>
                <td style={{ padding: '6px 8px' }}>
                  {a.registered !== false && a.soul_exists
                    ? <button onClick={() => setEditAgent({ id: a.id, title: a.identity_name || a.name })} style={{ fontSize: 11, padding: '2px 8px', border: '1px solid var(--border)', borderRadius: 4, background: 'var(--bg1)', color: '#60a5fa', cursor: 'pointer' }}>Edit Identity</button>
                    : <span style={{ fontSize: 10, color: 'var(--text3)' }}>{a.registered === false ? 'read-only' : 'no SOUL'}</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Skills + Channels */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(280px,1fr))', gap: 14 }}>
        <div style={card}>
          <div style={{ fontWeight: 700, marginBottom: 8 }}>Skills Catalog</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            {(st?.skills_catalog || []).map((s: string) => (
              <span key={s} style={{ fontSize: 11, padding: '2px 8px', border: '1px solid var(--border)', borderRadius: 4, background: 'var(--bg1)', color: 'var(--text2)' }}>{s}</span>
            ))}
          </div>
        </div>
        <div style={card}>
          <div style={{ fontWeight: 700, marginBottom: 8 }}>Channels</div>
          {(st?.channels || []).map((c: any) => (
            <div key={c.name} style={{ fontSize: 12, marginBottom: 3 }}>
              <span style={{ color: c.enabled ? '#22c55e' : 'var(--text3)' }}>{c.enabled ? '● ' : '○ '}</span>{c.name}
            </div>
          ))}
        </div>
      </div>
      <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 4 }}>Source: /api/v2/openclaw/status · read-only inventory · agent SOULs editable (backup-first, validated) · gateway shown not controlled.</div>
    </div>
  )
}
