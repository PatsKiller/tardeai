import { useParams, useNavigate } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import { timeAgo, fmt$ } from '../lib/format'

const card: React.CSSProperties = { background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)', borderRadius: 12, padding: '16px 20px' }
const secTitle: React.CSSProperties = { fontSize: 11, fontWeight: 600, letterSpacing: '.08em', textTransform: 'uppercase' as const, color: 'rgba(255,255,255,0.4)', marginBottom: 14 }

const recColor: Record<string, string> = {
  BUY: '#0ecb81', HOLD: '#f0b90b', SELL: '#f6465d', TRIM: '#f6465d',
  ADD: '#0ecb81', NEUTRAL: '#8b95a5', AVOID: '#f6465d', RESEARCH_MORE: '#4a90f4',
}

export default function AgentDashboard() {
  const { agentId } = useParams<{ agentId: string }>()
  const navigate = useNavigate()
  const { data: summary } = useApi<any>('/api/v2/agents/summary', 30000)
  const { data: detail } = useApi<any>('/api/v2/agent-detail', 30000)
  const { data: health } = useApi<any>('/api/v2/agent-health', 60000)
  const { data: calibration } = useApi<any>('/api/v2/agent-calibration', 60000)
  const { data: perfHistory } = useApi<any>('/api/v2/agents/performance-history', 60000)

  const agents = summary?.agents || []
  const agent = agents.find((a: any) => a.agent === agentId) || { agent: agentId }
  const agentDetail = detail?.[agentId] || detail?.data?.[agentId] || {}
  const latest = agentDetail?.latest || []
  const distribution = agentDetail?.distribution || []
  const topSymbols = agentDetail?.top_symbols || []

  const healthData = health || {}
  const agentHealth = (healthData.agents || healthData.data?.agents || []).find((a: any) => a.agent === agentId)
  const calibData = (calibration?.data || calibration || [])

  return (
    <div style={{ padding: '20px 24px', maxWidth: 1400, margin: '0 auto' }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 20, paddingBottom: 16, borderBottom: '1px solid rgba(255,255,255,0.08)' }}>
        <div>
          <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.3)', marginBottom: 4 }}>
            <span style={{ cursor: 'pointer' }} onClick={() => navigate('/v2/')}>Home</span>
            {' > '}
            <span style={{ cursor: 'pointer' }} onClick={() => navigate('/ai-analyst')}>AI Analyst</span>
            {' > '}
            <span>{agentId}</span>
          </div>
          <h1 style={{ fontSize: 20, fontWeight: 600, margin: 0, color: 'rgba(255,255,255,0.9)' }}>{agentId}</h1>
          <p style={{ fontSize: 12, color: 'rgba(255,255,255,0.4)', margin: '4px 0 0' }}>{agent.description || agent.role || 'Agent dashboard'}</p>
        </div>
        <button onClick={() => navigate('/ai-analyst')} style={{ padding: '7px 16px', borderRadius: 8, fontSize: 12, background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.1)', color: 'rgba(255,255,255,0.5)', cursor: 'pointer' }}>Back</button>
      </div>

      {/* Stats tiles */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5,1fr)', gap: 10, marginBottom: 20 }}>
        {[
          { label: 'Total Actions', value: agent.actions_taken || agent.total || 0 },
          { label: 'Avg Confidence', value: agent.avg_confidence ? `${Number(agent.avg_confidence).toFixed(0)}%` : '—' },
          { label: 'Last Run', value: agent.last_run ? timeAgo(agent.last_run) : 'never' },
          { label: 'Status', value: agent.status || 'unknown', color: agent.status === 'active' ? '#4ade80' : '#f59e0b' },
          { label: 'Symbols Covered', value: topSymbols.length || '—' },
        ].map(k => (
          <div key={k.label} style={{ ...card, textAlign: 'center', padding: '14px 16px' }}>
            <div style={{ fontSize: 20, fontWeight: 600, color: (k as any).color || 'rgba(255,255,255,0.9)' }}>{k.value}</div>
            <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.35)', marginTop: 4 }}>{k.label}</div>
          </div>
        ))}
      </div>

      {/* Recommendation Distribution */}
      {distribution.length > 0 && (
        <div style={{ ...card, marginBottom: 20 }}>
          <div style={secTitle}>Recommendation Distribution</div>
          <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
            {distribution.map((d: any) => (
              <div key={d.recommendation} style={{ padding: '8px 16px', borderRadius: 8, background: `${recColor[d.recommendation] || '#8b95a5'}15`, border: `1px solid ${recColor[d.recommendation] || '#8b95a5'}40` }}>
                <div style={{ fontSize: 18, fontWeight: 700, color: recColor[d.recommendation] || '#8b95a5' }}>{d.cnt}</div>
                <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.4)' }}>{d.recommendation}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Top Symbols */}
      {topSymbols.length > 0 && (
        <div style={{ ...card, marginBottom: 20 }}>
          <div style={secTitle}>Top Symbols Analyzed</div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {topSymbols.map((s: any) => (
              <span key={s.symbol} style={{ padding: '4px 10px', borderRadius: 6, fontSize: 11, fontWeight: 600, background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.1)', color: 'rgba(255,255,255,0.7)' }}>
                {s.symbol} ({s.cnt})
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Recent Activity */}
      <div style={{ ...card, marginBottom: 20 }}>
        <div style={secTitle}>Recent Activity (last 20)</div>
        {latest.length === 0 ? (
          <div style={{ color: 'rgba(255,255,255,0.3)', fontSize: 12, padding: 16 }}>No recent activity for this agent.</div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead><tr style={{ borderBottom: '1px solid rgba(255,255,255,0.1)' }}>
                {['Time', 'Symbol', 'Recommendation', 'Confidence', 'Summary'].map(h => (
                  <th key={h} style={{ textAlign: 'left', padding: '6px 8px', fontSize: 10, fontWeight: 600, color: 'rgba(255,255,255,0.35)', textTransform: 'uppercase' }}>{h}</th>
                ))}
              </tr></thead>
              <tbody>
                {latest.slice(0, 20).map((r: any, i: number) => {
                  const rc = recColor[r.recommendation] || '#8b95a5'
                  return (
                    <tr key={i} style={{ borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                      <td style={{ padding: '6px 8px', fontSize: 10, color: 'rgba(255,255,255,0.4)' }}>{r.created_at ? timeAgo(r.created_at) : '—'}</td>
                      <td style={{ padding: '6px 8px', fontWeight: 600, color: 'rgba(255,255,255,0.85)' }}>{r.symbol}</td>
                      <td style={{ padding: '6px 8px' }}><span style={{ fontSize: 10, padding: '2px 7px', borderRadius: 4, fontWeight: 600, background: `${rc}20`, color: rc }}>{r.recommendation}</span></td>
                      <td style={{ padding: '6px 8px', fontSize: 11, color: 'rgba(255,255,255,0.5)' }}>{r.confidence ? `${r.confidence}%` : '—'}</td>
                      <td style={{ padding: '6px 8px', fontSize: 10, color: 'rgba(255,255,255,0.4)', maxWidth: 300, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.summary || r.narrative || '—'}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Calibration / Performance */}
      {agentHealth && (
        <div style={{ ...card, marginBottom: 20 }}>
          <div style={secTitle}>Health & Calibration</div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 12 }}>
            <div><div style={{ fontSize: 9, color: 'rgba(255,255,255,0.3)' }}>Avg Confidence</div><div style={{ fontSize: 16, fontWeight: 600, color: 'rgba(255,255,255,0.8)' }}>{agentHealth.avg_confidence ? `${Number(agentHealth.avg_confidence).toFixed(0)}%` : '—'}</div></div>
            <div><div style={{ fontSize: 9, color: 'rgba(255,255,255,0.3)' }}>Escalation Rate</div><div style={{ fontSize: 16, fontWeight: 600, color: 'rgba(255,255,255,0.8)' }}>{agentHealth.escalation_rate ? `${Number(agentHealth.escalation_rate).toFixed(1)}%` : '—'}</div></div>
            <div><div style={{ fontSize: 9, color: 'rgba(255,255,255,0.3)' }}>Unique Symbols</div><div style={{ fontSize: 16, fontWeight: 600, color: 'rgba(255,255,255,0.8)' }}>{agentHealth.unique_symbols || '—'}</div></div>
          </div>
        </div>
      )}

      {/* Performance History */}
      {(perfHistory?.history || []).length > 0 && (
        <div style={card}>
          <div style={secTitle}>Performance History</div>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead><tr style={{ borderBottom: '1px solid rgba(255,255,255,0.1)' }}>
                {['Period', 'Accuracy', 'Confidence', 'Actions'].map(h => (
                  <th key={h} style={{ textAlign: 'left', padding: '6px 8px', fontSize: 10, fontWeight: 600, color: 'rgba(255,255,255,0.35)', textTransform: 'uppercase' }}>{h}</th>
                ))}
              </tr></thead>
              <tbody>
                {(perfHistory.history || []).slice(0, 10).map((p: any, i: number) => (
                  <tr key={i} style={{ borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                    <td style={{ padding: '6px 8px', fontSize: 11, color: 'rgba(255,255,255,0.5)' }}>{p.period || p.created_at?.slice(0, 10) || '—'}</td>
                    <td style={{ padding: '6px 8px', fontSize: 11, color: 'rgba(255,255,255,0.5)' }}>{p.accuracy_pct ? `${p.accuracy_pct}%` : '—'}</td>
                    <td style={{ padding: '6px 8px', fontSize: 11, color: 'rgba(255,255,255,0.5)' }}>{p.avg_confidence ? `${Number(p.avg_confidence).toFixed(0)}%` : '—'}</td>
                    <td style={{ padding: '6px 8px', fontSize: 11, color: 'rgba(255,255,255,0.5)' }}>{p.total_actions || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
