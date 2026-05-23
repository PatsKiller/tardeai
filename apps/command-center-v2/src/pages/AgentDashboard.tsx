import { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import { timeAgo } from '../lib/format'

const card: React.CSSProperties = { background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)', borderRadius: 12, padding: '16px 20px', marginBottom: 16 }
const secTitle: React.CSSProperties = { fontSize: 11, fontWeight: 600, letterSpacing: '.08em', textTransform: 'uppercase' as const, color: 'rgba(255,255,255,0.4)', marginBottom: 14 }
const recColor: Record<string, string> = { BUY: '#0ecb81', HOLD: '#f0b90b', SELL: '#f6465d', TRIM: '#f6465d', ADD: '#0ecb81', NEUTRAL: '#8b95a5', AVOID: '#f6465d', RESEARCH_MORE: '#4a90f4' }

const AGENTS = ['steph', 'maria', 'maria_research', 'risk_agent', 'tax_agent', 'alex', 'aegis', 'iris', 'social_scalp', 'scalp_critic']

export default function AgentDashboard() {
  const { agentId } = useParams<{ agentId: string }>()
  const navigate = useNavigate()
  const { data: resp } = useApi<any>(`/api/v2/agent-dashboard?agent=${agentId}`, 30000)
  const d = resp || {}
  const id = d.identity || {}
  const stats = d.stats || {}
  const [expandedRow, setExpandedRow] = useState<string | null>(null)
  const [mixPeriod, setMixPeriod] = useState('30d')

  const statusColor = stats.status === 'healthy' ? '#4ade80' : stats.status === 'stale' ? '#f59e0b' : '#f87171'

  return (
    <div style={{ padding: '20px 24px', maxWidth: 1400, margin: '0 auto' }}>
      {/* Agent Switcher */}
      <div style={{ display: 'flex', gap: 4, marginBottom: 16, overflowX: 'auto', paddingBottom: 4 }}>
        {AGENTS.map(a => (
          <button key={a} onClick={() => navigate(`/agent-dashboard/${a}`)}
            style={{ padding: '5px 12px', borderRadius: 8, fontSize: 11, fontWeight: a === agentId ? 700 : 500, cursor: 'pointer',
              background: a === agentId ? 'rgba(99,102,241,0.2)' : 'rgba(255,255,255,0.04)',
              border: a === agentId ? '1px solid rgba(99,102,241,0.5)' : '1px solid rgba(255,255,255,0.08)',
              color: a === agentId ? '#a5b4fc' : 'rgba(255,255,255,0.4)', whiteSpace: 'nowrap' }}>
            {a.replace(/_/g, ' ')}
          </button>
        ))}
      </div>

      {/* Section 1: Identity Card */}
      <div style={{ ...card, display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div>
          <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.3)', marginBottom: 4 }}>
            <span style={{ cursor: 'pointer' }} onClick={() => navigate('/')}>Home</span> › <span style={{ cursor: 'pointer' }} onClick={() => navigate('/ai-analyst')}>AI Analyst</span> › {id.display || agentId}
          </div>
          <h1 style={{ fontSize: 22, fontWeight: 700, margin: 0, color: 'rgba(255,255,255,0.95)' }}>{id.emoji || '🤖'} {id.display || agentId}</h1>
          <p style={{ fontSize: 12, color: 'rgba(255,255,255,0.4)', margin: '4px 0 0' }}>{id.role || 'Agent'}</p>
          <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.3)', marginTop: 6 }}>Model: {id.model || '—'}</div>
        </div>
        <div style={{ textAlign: 'right' }}>
          <div style={{ display: 'inline-block', padding: '3px 10px', borderRadius: 12, fontSize: 10, fontWeight: 700, background: `${statusColor}20`, color: statusColor }}>{stats.status || '?'}</div>
          <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.3)', marginTop: 6 }}>Last run: {stats.last_run_at ? timeAgo(stats.last_run_at) : 'never'}</div>
        </div>
      </div>

      {/* Stats Tiles */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5,1fr)', gap: 10, marginBottom: 16 }}>
        {[
          { label: 'Lifetime Analyses', value: stats.lifetime_analyses || 0 },
          { label: 'Avg Confidence (all)', value: stats.avg_confidence_all ? `${(stats.avg_confidence_all * 100).toFixed(0)}%` : '—' },
          { label: 'Avg Confidence (30d)', value: stats.avg_confidence_30d ? `${(stats.avg_confidence_30d * 100).toFixed(0)}%` : '—' },
          { label: 'Top Symbols', value: (d.top_symbols || []).length },
          { label: 'Active Debates', value: (d.debates || []).length },
        ].map(k => (
          <div key={k.label} style={{ ...card, textAlign: 'center', padding: '12px', marginBottom: 0 }}>
            <div style={{ fontSize: 20, fontWeight: 600, color: 'rgba(255,255,255,0.9)' }}>{k.value}</div>
            <div style={{ fontSize: 9, color: 'rgba(255,255,255,0.35)', marginTop: 4 }}>{k.label}</div>
          </div>
        ))}
      </div>

      {/* Section 3: Confidence Histogram + Section 4: Decision Mix — side by side */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 16 }}>
        {/* Confidence Histogram */}
        <div style={card}>
          <div style={secTitle}>Confidence Distribution (30d)</div>
          {(d.confidence_histogram || []).length === 0 ? (
            <div style={{ color: 'rgba(255,255,255,0.3)', fontSize: 11 }}>No confidence data in last 30 days</div>
          ) : (
            <div style={{ display: 'flex', alignItems: 'flex-end', gap: 4, height: 100 }}>
              {Array.from({ length: 10 }, (_, i) => {
                const bucket = (d.confidence_histogram || []).find((h: any) => h.bucket === i + 1)
                const cnt = bucket?.cnt || 0
                const maxCnt = Math.max(...(d.confidence_histogram || []).map((h: any) => h.cnt || 0), 1)
                const pct = (cnt / maxCnt) * 100
                const color = i >= 7 ? '#4ade80' : i >= 4 ? '#f59e0b' : '#f87171'
                return (
                  <div key={i} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
                    <div style={{ fontSize: 8, color: 'rgba(255,255,255,0.3)', marginBottom: 2 }}>{cnt || ''}</div>
                    <div style={{ width: '100%', height: `${Math.max(pct, 2)}%`, background: color, borderRadius: '3px 3px 0 0', minHeight: 2 }} />
                    <div style={{ fontSize: 7, color: 'rgba(255,255,255,0.2)', marginTop: 2 }}>{i * 10}%</div>
                  </div>
                )
              })}
            </div>
          )}
        </div>

        {/* Decision Mix */}
        <div style={card}>
          <div style={secTitle}>Decision Mix</div>
          {Object.keys(d.decision_mix || {}).length === 0 ? (
            <div style={{ color: 'rgba(255,255,255,0.3)', fontSize: 11 }}>No decisions in selected period</div>
          ) : (
            <div>
              {Object.entries(d.decision_mix || {}).map(([rec, cnt]) => {
                const total = Object.values(d.decision_mix || {}).reduce((a: number, b: unknown) => a + Number(b), 0) as number
                const pct = Number(total) > 0 ? (Number(cnt) / Number(total) * 100) : 0
                const color = recColor[rec] || '#8b95a5'
                return (
                  <div key={rec} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                    <span style={{ width: 60, fontSize: 10, fontWeight: 600, color }}>{rec}</span>
                    <div style={{ flex: 1, height: 16, background: 'rgba(255,255,255,0.04)', borderRadius: 4, overflow: 'hidden' }}>
                      <div style={{ height: '100%', width: `${pct}%`, background: `${color}40`, borderRadius: 4, minWidth: 2 }} />
                    </div>
                    <span style={{ fontSize: 11, fontWeight: 600, color: 'rgba(255,255,255,0.6)', width: 30, textAlign: 'right' }}>{Number(cnt)}</span>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </div>

      {/* Top Symbols */}
      {(d.top_symbols || []).length > 0 && (
        <div style={card}>
          <div style={secTitle}>Top Symbols (90d)</div>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {(d.top_symbols || []).map((s: any) => (
              <span key={s.symbol} onClick={() => navigate(`/watchlist/${s.symbol}`)}
                style={{ padding: '4px 10px', borderRadius: 6, fontSize: 11, fontWeight: 600, cursor: 'pointer',
                  background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.1)', color: 'rgba(255,255,255,0.7)' }}>
                {s.symbol} <span style={{ fontWeight: 400, color: 'rgba(255,255,255,0.3)' }}>({s.cnt})</span>
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Section 5: Recent Analyses */}
      <div style={card}>
        <div style={secTitle}>Recent Analyses</div>
        {(d.recent_results || []).length === 0 ? (
          <div style={{ color: 'rgba(255,255,255,0.3)', fontSize: 12, padding: 16 }}>No analyses found for this agent. This may mean the agent writes to a different table or hasn't run recently.</div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead><tr style={{ borderBottom: '1px solid rgba(255,255,255,0.1)' }}>
                {['Time', 'Symbol', 'Recommendation', 'Confidence', 'Trigger', 'Summary'].map(h => (
                  <th key={h} style={{ textAlign: 'left', padding: '6px 8px', fontSize: 10, fontWeight: 600, color: 'rgba(255,255,255,0.35)', textTransform: 'uppercase' }}>{h}</th>
                ))}
              </tr></thead>
              <tbody>
                {(d.recent_results || []).map((r: any) => {
                  const rc = recColor[r.recommendation] || '#8b95a5'
                  const expanded = expandedRow === r.id
                  return (
                    <>
                      <tr key={r.id} onClick={() => setExpandedRow(expanded ? null : r.id)} style={{ borderBottom: '1px solid rgba(255,255,255,0.05)', cursor: 'pointer' }}>
                        <td style={{ padding: '6px 8px', fontSize: 10, color: 'rgba(255,255,255,0.4)' }}>{r.created_at ? timeAgo(r.created_at) : '—'}</td>
                        <td style={{ padding: '6px 8px', fontWeight: 600, color: 'rgba(255,255,255,0.85)' }}>{r.symbol}</td>
                        <td style={{ padding: '6px 8px' }}><span style={{ fontSize: 10, padding: '2px 7px', borderRadius: 4, fontWeight: 600, background: `${rc}20`, color: rc }}>{r.recommendation}</span></td>
                        <td style={{ padding: '6px 8px', fontSize: 11 }}>
                          <div style={{ width: 60, height: 6, background: 'rgba(255,255,255,0.08)', borderRadius: 3, overflow: 'hidden', display: 'inline-block', verticalAlign: 'middle', marginRight: 4 }}>
                            <div style={{ height: '100%', width: `${(r.confidence || 0) * 100}%`, background: (r.confidence || 0) > 0.7 ? '#4ade80' : (r.confidence || 0) > 0.4 ? '#f59e0b' : '#f87171', borderRadius: 3 }} />
                          </div>
                          <span style={{ fontSize: 10, color: 'rgba(255,255,255,0.5)' }}>{r.confidence ? `${(r.confidence * 100).toFixed(0)}%` : '—'}</span>
                        </td>
                        <td style={{ padding: '6px 8px', fontSize: 10, color: 'rgba(255,255,255,0.4)' }}>{r.request_type || '—'}</td>
                        <td style={{ padding: '6px 8px', fontSize: 10, color: 'rgba(255,255,255,0.4)', maxWidth: 250, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.summary || '—'}</td>
                      </tr>
                      {expanded && (
                        <tr key={`${r.id}-exp`}><td colSpan={6} style={{ padding: '12px 16px', background: 'rgba(255,255,255,0.02)', fontSize: 11, color: 'rgba(255,255,255,0.5)', lineHeight: 1.6 }}>
                          {r.summary || 'No detailed summary available.'}
                          {r.reason_codes && <div style={{ marginTop: 8, fontSize: 10, color: 'rgba(255,255,255,0.3)' }}>Reasons: {typeof r.reason_codes === 'string' ? r.reason_codes : JSON.stringify(r.reason_codes)}</div>}
                          {r.model_used && <div style={{ fontSize: 9, color: 'rgba(255,255,255,0.2)', marginTop: 4 }}>Model: {r.model_used}</div>}
                        </td></tr>
                      )}
                    </>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Section 6: Calibration */}
      <div style={card}>
        <div style={secTitle}>Outcome Calibration</div>
        {(d.calibration?.ready) ? (
          <div style={{ color: 'rgba(255,255,255,0.5)', fontSize: 12 }}>Calibration data available — {d.calibration.samples} samples</div>
        ) : (
          <div>
            <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.4)', marginBottom: 8 }}>Needs {d.calibration?.samples_needed || 20}+ closed trade outcomes for calibration</div>
            <div style={{ width: '100%', height: 8, background: 'rgba(255,255,255,0.06)', borderRadius: 4, overflow: 'hidden' }}>
              <div style={{ height: '100%', width: `${Math.min(((d.calibration?.samples || 0) / (d.calibration?.samples_needed || 20)) * 100, 100)}%`, background: '#f59e0b', borderRadius: 4 }} />
            </div>
            <div style={{ fontSize: 9, color: 'rgba(255,255,255,0.3)', marginTop: 4 }}>Samples: {d.calibration?.samples || 0} / {d.calibration?.samples_needed || 20}</div>
          </div>
        )}
      </div>

      {/* Section 7: Debates + Section 8: Outcome Lessons — side by side */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 16 }}>
        <div style={card}>
          <div style={secTitle}>Active Debates ({(d.debates || []).length})</div>
          {(d.debates || []).length === 0 ? (
            <div style={{ color: 'rgba(255,255,255,0.3)', fontSize: 11 }}>No debates involving this agent</div>
          ) : (
            (d.debates || []).map((db: any) => (
              <div key={db.id} style={{ padding: '8px 10px', marginBottom: 6, borderRadius: 6, background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.06)' }}>
                <div style={{ fontSize: 12, fontWeight: 600, color: 'rgba(255,255,255,0.8)' }}>{db.symbol} — {db.debate_type}</div>
                <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.4)', marginTop: 2 }}>{db.outcome_summary || 'Pending resolution'}</div>
                <div style={{ fontSize: 9, color: 'rgba(255,255,255,0.25)', marginTop: 2 }}>{db.created_at ? timeAgo(db.created_at) : ''}</div>
              </div>
            ))
          )}
        </div>

        <div style={card}>
          <div style={secTitle}>Outcome Lessons ({(d.outcome_lessons || []).length})</div>
          {(d.outcome_lessons || []).length === 0 ? (
            <div style={{ color: 'rgba(255,255,255,0.3)', fontSize: 11 }}>No outcome lessons recorded for this agent</div>
          ) : (
            (d.outcome_lessons || []).slice(0, 5).map((l: any) => (
              <div key={l.id} style={{ padding: '8px 10px', marginBottom: 6, borderRadius: 6, background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.06)' }}>
                <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.7)' }}>{l.rule_text}</div>
                <div style={{ fontSize: 9, color: 'rgba(255,255,255,0.3)', marginTop: 2 }}>
                  {l.symbol && <span>{l.symbol} · </span>}
                  {l.confidence_adjustment && <span>Adj: {l.confidence_adjustment > 0 ? '+' : ''}{l.confidence_adjustment} · </span>}
                  {l.created_at ? timeAgo(l.created_at) : ''}
                </div>
              </div>
            ))
          )}
        </div>
      </div>

      {/* Section 9: Agent-Specific */}
      {d.agent_specific?.type === 'income_tracker' && (
        <div style={card}>
          <div style={secTitle}>Income Tracker (Steph)</div>
          <div style={{ display: 'flex', gap: 20, alignItems: 'center', marginBottom: 12 }}>
            <div>
              <div style={{ fontSize: 9, color: 'rgba(255,255,255,0.3)' }}>Annual Income</div>
              <div style={{ fontSize: 22, fontWeight: 700, color: '#4ade80' }}>${(d.agent_specific.current_income || 0).toLocaleString()}</div>
            </div>
            <div>
              <div style={{ fontSize: 9, color: 'rgba(255,255,255,0.3)' }}>Target</div>
              <div style={{ fontSize: 22, fontWeight: 700, color: 'rgba(255,255,255,0.5)' }}>${(d.agent_specific.income_target || 55000).toLocaleString()}</div>
            </div>
            <div style={{ flex: 1 }}>
              <div style={{ width: '100%', height: 10, background: 'rgba(255,255,255,0.06)', borderRadius: 5, overflow: 'hidden' }}>
                <div style={{ height: '100%', width: `${Math.min((d.agent_specific.current_income / d.agent_specific.income_target) * 100, 100)}%`, background: '#4ade80', borderRadius: 5 }} />
              </div>
              <div style={{ fontSize: 9, color: 'rgba(255,255,255,0.3)', marginTop: 2 }}>{((d.agent_specific.current_income / d.agent_specific.income_target) * 100).toFixed(1)}% of target</div>
            </div>
          </div>
          {(d.agent_specific.top_income_positions || []).length > 0 && (
            <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.4)' }}>
              Top: {(d.agent_specific.top_income_positions || []).slice(0, 5).map((p: any) => `${p.symbol} ($${p.income.toFixed(0)})`).join(', ')}
            </div>
          )}
        </div>
      )}

      {d.agent_specific?.type === 'overnight_findings' && (d.agent_specific.briefs || []).length > 0 && (
        <div style={card}>
          <div style={secTitle}>Overnight Findings (Aegis)</div>
          {(d.agent_specific.briefs || []).map((b: any) => (
            <div key={b.id} style={{ padding: '8px 10px', marginBottom: 6, borderRadius: 6, background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.06)' }}>
              <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.7)' }}>{b.key_findings || 'No findings recorded'}</div>
              <div style={{ fontSize: 9, color: 'rgba(255,255,255,0.25)' }}>{b.brief_date || (b.created_at ? timeAgo(b.created_at) : '')}</div>
            </div>
          ))}
        </div>
      )}

      {d.agent_specific?.type === 'coverage' && (d.agent_specific.runs || []).length > 0 && (
        <div style={card}>
          <div style={secTitle}>Recent Runs (Iris)</div>
          {(d.agent_specific.runs || []).map((r: any) => (
            <div key={r.id} style={{ padding: '4px 0', fontSize: 11, color: 'rgba(255,255,255,0.5)' }}>
              {r.run_type} — {r.symbols_processed} symbols — {r.created_at ? timeAgo(r.created_at) : ''}
            </div>
          ))}
        </div>
      )}

      {/* Section 10: Event Queue & Escalation Map */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 16 }}>
        <div style={card}>
          <div style={secTitle}>Incoming Events ({(d.event_queue || []).length})</div>
          {Object.keys(d.event_summary || {}).length === 0 ? (
            <div style={{ color: 'rgba(255,255,255,0.3)', fontSize: 11 }}>No events routed to this agent recently</div>
          ) : (
            Object.entries(d.event_summary || {}).map(([type, cnt]) => (
              <div key={type} style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 0', fontSize: 11 }}>
                <span style={{ color: 'rgba(255,255,255,0.6)' }}>{type.replace(/_/g, ' ')}</span>
                <span style={{ fontWeight: 600, color: type.includes('STOP') || type.includes('CRITICAL') ? '#f87171' : '#f59e0b' }}>{String(cnt)}</span>
              </div>
            ))
          )}
        </div>

        <div style={card}>
          <div style={secTitle}>Handoffs (out: {d.handoff_summary?.outgoing || 0} / in: {d.handoff_summary?.incoming || 0})</div>
          {(d.handoffs || []).length === 0 ? (
            <div style={{ color: 'rgba(255,255,255,0.3)', fontSize: 11 }}>No handoffs involving this agent</div>
          ) : (
            (d.handoffs || []).slice(0, 8).map((h: any) => (
              <div key={h.id} style={{ padding: '4px 0', fontSize: 10, color: 'rgba(255,255,255,0.5)', borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
                <span style={{ color: '#a5b4fc' }}>{h.from_agent}</span> → <span style={{ color: '#a5b4fc' }}>{h.to_agent}</span>
                {h.symbol && <span style={{ marginLeft: 6, fontWeight: 600, color: 'rgba(255,255,255,0.7)' }}>{h.symbol}</span>}
                <span style={{ marginLeft: 6, color: 'rgba(255,255,255,0.25)' }}>{h.created_at ? timeAgo(h.created_at) : ''}</span>
              </div>
            ))
          )}
        </div>
      </div>

      {/* Section 11: LLM Routing */}
      {Object.keys(d.llm_routing || {}).length > 0 && (
        <div style={card}>
          <div style={secTitle}>LLM Routing ({d.llm_total_calls || 0} calls)</div>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead><tr style={{ borderBottom: '1px solid rgba(255,255,255,0.1)' }}>
              {['Provider', 'Calls', 'Success Rate', 'Avg Latency', 'Fallbacks'].map(h => (
                <th key={h} style={{ textAlign: h === 'Provider' ? 'left' : 'right', padding: '6px 8px', fontSize: 10, fontWeight: 600, color: 'rgba(255,255,255,0.35)' }}>{h}</th>
              ))}
            </tr></thead>
            <tbody>
              {Object.entries(d.llm_routing || {}).map(([provider, stats]: [string, any]) => (
                <tr key={provider} style={{ borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                  <td style={{ padding: '6px 8px', fontWeight: 600, color: 'rgba(255,255,255,0.8)' }}>{provider}</td>
                  <td style={{ padding: '6px 8px', textAlign: 'right', fontSize: 11, color: 'rgba(255,255,255,0.5)' }}>{stats.calls}</td>
                  <td style={{ padding: '6px 8px', textAlign: 'right', fontSize: 11, color: stats.success_rate >= 95 ? '#4ade80' : '#f59e0b' }}>{stats.success_rate}%</td>
                  <td style={{ padding: '6px 8px', textAlign: 'right', fontSize: 11, color: 'rgba(255,255,255,0.5)' }}>{(stats.avg_latency_ms / 1000).toFixed(1)}s</td>
                  <td style={{ padding: '6px 8px', textAlign: 'right', fontSize: 11, color: stats.fallbacks > 0 ? '#f87171' : 'rgba(255,255,255,0.3)' }}>{stats.fallbacks}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* SLA Status Banner */}
      {d.sla && (
        <div style={{ padding: '8px 14px', marginBottom: 16, borderRadius: 8, fontSize: 10,
          background: d.sla.color === 'green' ? 'rgba(74,222,128,0.06)' : d.sla.color === 'amber' ? 'rgba(245,158,11,0.08)' : 'rgba(248,113,113,0.08)',
          border: `1px solid ${d.sla.color === 'green' ? 'rgba(74,222,128,0.2)' : d.sla.color === 'amber' ? 'rgba(245,158,11,0.25)' : 'rgba(248,113,113,0.25)'}`,
          color: d.sla.color === 'green' ? '#4ade80' : d.sla.color === 'amber' ? '#f59e0b' : '#f87171' }}>
          Data freshness: {d.sla.age_minutes != null ? `${Math.round(d.sla.age_minutes)}m ago` : 'unknown'} · SLA: ≤{d.sla.sla_minutes}m · {d.sla.color === 'green' ? '🟢' : d.sla.color === 'amber' ? '🟡' : '🔴'}
        </div>
      )}

      {/* Performance History */}
      {(d.performance_history || []).length > 0 && (
        <div style={card}>
          <div style={secTitle}>Performance History</div>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead><tr style={{ borderBottom: '1px solid rgba(255,255,255,0.1)' }}>
              {['Period', 'Accuracy', 'Confidence', 'Actions'].map(h => (
                <th key={h} style={{ textAlign: 'left', padding: '6px 8px', fontSize: 10, fontWeight: 600, color: 'rgba(255,255,255,0.35)' }}>{h}</th>
              ))}
            </tr></thead>
            <tbody>
              {(d.performance_history || []).slice(0, 10).map((p: any, i: number) => (
                <tr key={i} style={{ borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                  <td style={{ padding: '6px 8px', fontSize: 11, color: 'rgba(255,255,255,0.5)' }}>{p.period || String(p.created_at || '').slice(0, 10)}</td>
                  <td style={{ padding: '6px 8px', fontSize: 11, color: 'rgba(255,255,255,0.5)' }}>{p.accuracy_pct ? `${p.accuracy_pct}%` : '—'}</td>
                  <td style={{ padding: '6px 8px', fontSize: 11, color: 'rgba(255,255,255,0.5)' }}>{p.avg_confidence ? `${Number(p.avg_confidence).toFixed(0)}%` : '—'}</td>
                  <td style={{ padding: '6px 8px', fontSize: 11, color: 'rgba(255,255,255,0.5)' }}>{p.total_actions || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
