const ROLE_COLORS: Record<string, { bg: string; fg: string }> = {
  'R': { bg: '#3b82f6', fg: '#fff' }, 'A': { bg: '#10b981', fg: '#fff' },
  'C': { bg: '#f59e0b', fg: '#0f172a' }, 'I': { bg: '#64748b', fg: '#fff' },
  'R/A': { bg: '#3b82f6', fg: '#fff' },
}

function RolePill({ role }: { role: string }) {
  const s = ROLE_COLORS[role] || ROLE_COLORS['I']
  return <span style={{ background: s.bg, color: s.fg, padding: '2px 8px', borderRadius: 4, fontWeight: 700, fontSize: 10, fontFamily: 'monospace', display: 'inline-block', minWidth: 24, textAlign: 'center' }}>{role}</span>
}

interface Props {
  data: any
  onPeerClick: (peer: string) => void
}

export function RACIMatrix({ data, onPeerClick }: Props) {
  const processes = data?.data?.processes || data?.processes || []
  const peers = data?.data?.peer_summary || data?.peer_summary || []

  if (processes.length === 0) {
    return (
      <div style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)', borderRadius: 12, padding: '16px 20px', marginBottom: 16 }}>
        <div style={{ fontSize: 11, fontWeight: 600, letterSpacing: '.08em', textTransform: 'uppercase' as const, color: 'rgba(255,255,255,0.4)', marginBottom: 8 }}>RACI · Process Ownership</div>
        <div style={{ color: 'rgba(255,255,255,0.3)', fontSize: 11 }}>No processes mapped for this agent. Edit config/agent_raci.yaml to add.</div>
      </div>
    )
  }

  return (
    <div style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)', borderRadius: 12, padding: '16px 20px', marginBottom: 16 }}>
      <div style={{ fontSize: 11, fontWeight: 600, letterSpacing: '.08em', textTransform: 'uppercase' as const, color: 'rgba(255,255,255,0.4)', marginBottom: 14 }}>RACI · Process Ownership</div>

      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead><tr style={{ borderBottom: '1px solid rgba(255,255,255,0.1)' }}>
          {['Process', 'Role', 'Co-actors', 'Trigger', 'Frequency'].map(h => (
            <th key={h} style={{ textAlign: h === 'Role' ? 'center' : 'left', padding: '6px 8px', fontSize: 10, fontWeight: 600, color: 'rgba(255,255,255,0.35)', textTransform: 'uppercase' }}>{h}</th>
          ))}
        </tr></thead>
        <tbody>
          {processes.map((p: any) => (
            <tr key={p.id} style={{ borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
              <td style={{ padding: '8px 8px', fontWeight: 600, color: 'rgba(255,255,255,0.8)', fontSize: 12 }}>{p.name}</td>
              <td style={{ padding: '8px 8px', textAlign: 'center' }}><RolePill role={p.this_role} /></td>
              <td style={{ padding: '8px 8px' }}>
                {(p.co_actors || []).map((a: any) => (
                  <button key={a.agent} onClick={() => onPeerClick(a.agent)} style={{ background: 'transparent', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 4, padding: '2px 6px', display: 'inline-flex', gap: 4, alignItems: 'center', cursor: 'pointer', fontSize: 10, marginRight: 4, marginBottom: 2, color: 'rgba(255,255,255,0.6)' }}>
                    <RolePill role={a.role} /> {a.agent.replace(/_/g, ' ')}
                  </button>
                ))}
              </td>
              <td style={{ padding: '8px 8px', fontSize: 10, color: 'rgba(255,255,255,0.4)' }}>{p.trigger}</td>
              <td style={{ padding: '8px 8px', fontSize: 10, color: 'rgba(255,255,255,0.4)' }}>{p.frequency}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {peers.length > 0 && (
        <div style={{ marginTop: 16 }}>
          <div style={{ fontSize: 10, fontWeight: 600, letterSpacing: '.05em', textTransform: 'uppercase' as const, color: 'rgba(255,255,255,0.3)', marginBottom: 8 }}>Peer Relationships</div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {peers.map((p: any) => (
              <button key={p.peer} onClick={() => onPeerClick(p.peer)} style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 6, padding: '6px 10px', cursor: 'pointer', fontSize: 11, color: 'rgba(255,255,255,0.6)' }}>
                <span style={{ fontWeight: 600, color: 'rgba(255,255,255,0.8)' }}>{p.peer.replace(/_/g, ' ')}</span>
                <span style={{ marginLeft: 6, fontSize: 9 }}>({p.dominant_relationship}, {p.process_count} shared)</span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
