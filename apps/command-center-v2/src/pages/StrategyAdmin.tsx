import React, { useState } from 'react'
import PageHeader from '../components/PageHeader'
import { useApi } from '../hooks/useApi'

const mono: React.CSSProperties = { fontFamily: 'monospace' }
const pill = (color: string): React.CSSProperties => ({
  fontSize: 9, padding: '2px 6px', borderRadius: 4, fontWeight: 600,
  background: color === 'green' ? 'rgba(34,197,94,0.15)' : color === 'red' ? 'rgba(239,68,68,0.15)' : color === 'blue' ? 'rgba(59,130,246,0.15)' : 'rgba(251,191,36,0.15)',
  color: color === 'green' ? 'var(--green)' : color === 'red' ? 'var(--red)' : color === 'blue' ? '#60A5FA' : 'var(--amber)',
})
const btn = (bg: string, fg: string): React.CSSProperties => ({
  padding: '5px 12px', fontSize: 10, fontWeight: 600, border: 'none', borderRadius: 5, cursor: 'pointer', color: fg, background: bg,
})

const statusColor = (s: string) => s === 'VALIDATED' ? 'green' : s === 'TESTING' ? 'blue' : s === 'PAUSED' || s === 'KILLED' ? 'red' : 'amber'
const tcColor = (tc: string) => tc === 'INTRADAY' ? '#60A5FA' : tc === 'SHORT_SWING' ? '#34D399' : tc === 'MEDIUM_SWING' ? '#FBBF24' : tc === 'POSITION' ? '#A78BFA' : '#94A3B8'

function StrategyDetail({ sid, onClose }: { sid: string; onClose: () => void }) {
  const { data, loading } = useApi<any>(`/api/v2/strategy-configs/${sid}`, 0)
  if (loading) return <div style={{ padding: 20, color: 'var(--text3)' }}>Loading...</div>
  const cfg = data?.config || {}
  const ctx = data?.prompt_context || ''
  const risk = cfg.risk || {}
  const lifecycle = cfg.lifecycle || {}
  const co = cfg.co_enables || {}
  const vg = cfg.validation_gate || {}
  const entry = cfg.entry_criteria || []
  const disq = cfg.auto_disqualifiers || []
  const agents = cfg.agent_responsibilities || {}
  const pc = cfg.prompt_context || {}

  return (
    <div style={{ background: 'var(--bg1)', borderRadius: 8, border: '1px solid var(--border)', padding: 16, marginBottom: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <div>
          <span style={{ fontSize: 16, fontWeight: 700, ...mono }}>{cfg.display_name || sid}</span>
          <span style={{ marginLeft: 8, fontSize: 10, color: 'var(--text3)' }}>v{cfg.version} | {data?.config_hash?.slice(0, 8)}</span>
        </div>
        <button onClick={onClose} style={btn('var(--bg0)', 'var(--text2)')}>Close</button>
      </div>
      <div style={{ fontSize: 11, color: 'var(--text2)', marginBottom: 12 }}>{cfg.purpose}</div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8, marginBottom: 12 }}>
        <div><div style={{ fontSize: 8, color: 'var(--text3)', textTransform: 'uppercase' }}>Status</div><span style={pill(statusColor(cfg.status))}>{cfg.status}</span></div>
        <div><div style={{ fontSize: 8, color: 'var(--text3)', textTransform: 'uppercase' }}>Timeframe</div><div style={{ fontSize: 11, ...mono, color: tcColor(cfg.timeframe_class) }}>{cfg.timeframe} ({cfg.timeframe_class})</div></div>
        <div><div style={{ fontSize: 8, color: 'var(--text3)', textTransform: 'uppercase' }}>Accounts</div><div style={{ fontSize: 10, ...mono }}>{(cfg.eligible_accounts || []).join(', ')}</div></div>
        <div><div style={{ fontSize: 8, color: 'var(--text3)', textTransform: 'uppercase' }}>Live Allowed</div><span style={pill(cfg.execution?.live_allowed ? 'green' : 'red')}>{cfg.execution?.live_allowed ? 'YES' : 'NO'}</span></div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8, marginBottom: 12 }}>
        <div><div style={{ fontSize: 8, color: 'var(--text3)', textTransform: 'uppercase' }}>Risk/Trade</div><div style={{ fontSize: 11, ...mono }}>{risk.risk_per_trade_pct || '?'}</div></div>
        <div><div style={{ fontSize: 8, color: 'var(--text3)', textTransform: 'uppercase' }}>Max Position</div><div style={{ fontSize: 11, ...mono }}>${risk.max_position_size || '?'}</div></div>
        <div><div style={{ fontSize: 8, color: 'var(--text3)', textTransform: 'uppercase' }}>Target R:R</div><div style={{ fontSize: 11, ...mono }}>{risk.target_rr || '?'}</div></div>
        <div><div style={{ fontSize: 8, color: 'var(--text3)', textTransform: 'uppercase' }}>Expiry</div><div style={{ fontSize: 11, ...mono }}>{lifecycle.proposal_expiry_hours || '?'}h</div></div>
      </div>

      {entry.length > 0 && (
        <div style={{ marginBottom: 12 }}>
          <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text1)', marginBottom: 4 }}>Entry Criteria ({entry.length})</div>
          {entry.map((c: any, i: number) => (
            <div key={i} style={{ fontSize: 10, color: 'var(--text2)', padding: '2px 0', ...mono }}>
              {c.id || c.description}: {c.metric} {c.operator} {JSON.stringify(c.value)}
            </div>
          ))}
        </div>
      )}

      {disq.length > 0 && (
        <div style={{ marginBottom: 12 }}>
          <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--red)', marginBottom: 4 }}>Auto-Disqualifiers ({disq.length})</div>
          {disq.map((d: any, i: number) => (
            <div key={i} style={{ fontSize: 10, color: '#F87171', padding: '2px 0', ...mono }}>
              {d.id}: {d.condition || d.description}
            </div>
          ))}
        </div>
      )}

      {Object.keys(agents).length > 0 && (
        <div style={{ marginBottom: 12 }}>
          <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text1)', marginBottom: 4 }}>Agent Roles</div>
          {Object.entries(agents).map(([agent, role]) => (
            <div key={agent} style={{ fontSize: 10, color: 'var(--text2)', padding: '2px 0' }}>
              <span style={{ fontWeight: 600, ...mono }}>{agent}:</span> {String(role).slice(0, 150)}
            </div>
          ))}
        </div>
      )}

      <div style={{ marginBottom: 12 }}>
        <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text1)', marginBottom: 4 }}>Validation Gate</div>
        <div style={{ fontSize: 10, color: 'var(--text3)', ...mono }}>
          {vg.min_closed_paper_trades || 30} trades | {((vg.min_win_rate || 0.55) * 100).toFixed(0)}% win | PF {vg.min_profit_factor || 1.3} | {vg.min_calendar_months || 6} months | Human: {vg.human_approval_required ? 'Required' : 'Not required'}
        </div>
      </div>

      {co && (co.promotes_to?.length > 0 || co.strengthens?.length > 0) && (
        <div style={{ marginBottom: 12 }}>
          <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text1)', marginBottom: 4 }}>Co-Enablement</div>
          {co.promotes_to?.length > 0 && <div style={{ fontSize: 10, color: 'var(--text2)' }}>Promotes to: {co.promotes_to.join(', ')}</div>}
          {co.strengthens?.length > 0 && <div style={{ fontSize: 10, color: 'var(--text2)' }}>Strengthens: {co.strengthens.join(', ')}</div>}
        </div>
      )}

      <details style={{ marginTop: 8 }}>
        <summary style={{ fontSize: 10, fontWeight: 600, color: 'var(--text3)', cursor: 'pointer' }}>LLM Prompt Context</summary>
        <pre style={{ fontSize: 9, padding: 8, background: 'var(--bg0)', borderRadius: 4, overflow: 'auto', maxHeight: 200, margin: '4px 0', color: 'var(--text2)' }}>{ctx}</pre>
      </details>
    </div>
  )
}

export default function StrategyAdmin() {
  const { data, loading } = useApi<any>('/api/v2/strategy-configs', 60000)
  const { data: govData } = useApi<any>('/api/v2/paper-performance-governance', 60000)
  const { data: matchData } = useApi<any>('/api/v2/strategy-setup-matches', 30000)
  const [selectedStrategy, setSelectedStrategy] = useState<string | null>(null)
  const [running, setRunning] = useState<string | null>(null)

  const runAction = async (action: string, endpoint: string) => {
    setRunning(action)
    try {
      await fetch(endpoint, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
      window.location.reload()
    } catch { alert('Failed') }
    setRunning(null)
  }

  const strategies = data?.strategies ? Object.values(data.strategies) as any[] : []
  const gov = govData?.data || []
  const matches = matchData?.matches || []
  const govMap: Record<string, any> = {}
  gov.forEach((g: any) => { govMap[g.strategy_id] = g })

  const grouped = {
    INTRADAY: strategies.filter((s: any) => s.timeframe_class === 'INTRADAY'),
    SHORT_SWING: strategies.filter((s: any) => s.timeframe_class === 'SHORT_SWING'),
    MEDIUM_SWING: strategies.filter((s: any) => s.timeframe_class === 'MEDIUM_SWING'),
    POSITION: strategies.filter((s: any) => s.timeframe_class === 'POSITION'),
    CASH: strategies.filter((s: any) => s.timeframe_class === 'CASH'),
  }

  return (
    <div style={{ minHeight: '100vh' }}>
      <PageHeader title="Strategy Admin" subtitle={`${strategies.length} strategies loaded`} actions={
        <div style={{ display: 'flex', gap: 8 }}>
          <button onClick={() => runAction('validate', '/api/v2/strategy-configs/validate')} disabled={!!running}
            style={btn('rgba(59,130,246,0.15)', '#60A5FA')}>{running === 'validate' ? '...' : 'Validate All'}</button>
          <button onClick={() => runAction('sync', '/api/v2/strategy-configs/sync-db')} disabled={!!running}
            style={btn('rgba(34,197,94,0.15)', 'var(--green)')}>{running === 'sync' ? '...' : 'Sync to DB'}</button>
        </div>
      } />

      {loading && <div style={{ padding: 24, color: 'var(--text3)' }}>Loading...</div>}

      {selectedStrategy && <StrategyDetail sid={selectedStrategy} onClose={() => setSelectedStrategy(null)} />}

      {Object.entries(grouped).map(([group, strats]) => strats.length > 0 && (
        <div key={group} style={{ marginBottom: 20 }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: tcColor(group), marginBottom: 8, textTransform: 'uppercase', letterSpacing: '0.5px' }}>{group.replace('_', ' ')} ({strats.length})</div>
          <div style={{ background: 'var(--bg1)', borderRadius: 8, border: '1px solid var(--border)', overflow: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11, ...mono }}>
              <thead>
                <tr style={{ borderBottom: '2px solid var(--border)' }}>
                  {['Strategy', 'Status', 'Version', 'Hash', 'Accounts', 'Risk/Trade', 'Expiry', 'Live', 'Governance', 'Trades', ''].map(h => (
                    <th key={h} style={{ padding: '8px 10px', textAlign: 'left', fontSize: 9, color: 'var(--text3)', fontWeight: 600, textTransform: 'uppercase' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {strats.map((s: any) => {
                  const g = govMap[s.strategy_id]
                  return (
                    <tr key={s.strategy_id} style={{ borderBottom: '1px solid var(--border)', cursor: 'pointer' }}
                      onClick={() => setSelectedStrategy(s.strategy_id)}>
                      <td style={{ padding: '6px 10px', fontWeight: 700 }}>{s.display_name}</td>
                      <td style={{ padding: '6px 10px' }}><span style={pill(statusColor(s.status))}>{s.status}</span></td>
                      <td style={{ padding: '6px 10px', color: 'var(--text3)' }}>v{s.version}</td>
                      <td style={{ padding: '6px 10px', color: 'var(--text3)', fontSize: 9 }}>{s.config_hash?.slice(0, 8)}</td>
                      <td style={{ padding: '6px 10px', color: 'var(--text2)', fontSize: 9 }}>{(s.eligible_accounts || []).join(', ')}</td>
                      <td style={{ padding: '6px 10px' }}>{s.risk?.risk_per_trade_pct || '?'}</td>
                      <td style={{ padding: '6px 10px' }}>{s.lifecycle?.proposal_expiry_hours || '?'}h</td>
                      <td style={{ padding: '6px 10px' }}><span style={pill(s.risk?.live_allowed ? 'green' : 'red')}>{s.execution?.live_allowed ? 'YES' : 'NO'}</span></td>
                      <td style={{ padding: '6px 10px' }}>{g ? <span style={pill(g.governance_state === 'PAPER_ONLY' ? 'amber' : g.governance_state === 'WATCHLIST' ? 'blue' : 'green')}>{g.governance_state}</span> : <span style={{ color: 'var(--text3)', fontSize: 9 }}>--</span>}</td>
                      <td style={{ padding: '6px 10px', color: 'var(--text2)' }}>{g ? `${g.paper_trades || 0}/${g.closed_trades || 0}` : '--'}</td>
                      <td style={{ padding: '6px 10px' }}><span style={{ color: '#60A5FA', fontSize: 9 }}>Details</span></td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      ))}

      {/* Recent setup matches */}
      {matches.length > 0 && (
        <div style={{ marginTop: 20 }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text1)', marginBottom: 8 }}>Recent Setup Matches</div>
          <div style={{ background: 'var(--bg1)', borderRadius: 8, border: '1px solid var(--border)', overflow: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 10, ...mono }}>
              <thead>
                <tr style={{ borderBottom: '2px solid var(--border)' }}>
                  {['Symbol', 'Strategy', 'Score', 'Status', 'Primary', 'Reason', 'Date'].map(h => (
                    <th key={h} style={{ padding: '6px 8px', textAlign: 'left', fontSize: 8, color: 'var(--text3)', fontWeight: 600, textTransform: 'uppercase' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {matches.slice(0, 30).map((m: any) => (
                  <tr key={m.id} style={{ borderBottom: '1px solid var(--border)' }}>
                    <td style={{ padding: '4px 8px', fontWeight: 700 }}>{m.symbol}</td>
                    <td style={{ padding: '4px 8px' }}>{m.strategy_id}</td>
                    <td style={{ padding: '4px 8px' }}>{m.match_score}</td>
                    <td style={{ padding: '4px 8px' }}><span style={pill(m.match_status === 'STRONG_MATCH' ? 'green' : m.match_status === 'BLOCKED' ? 'red' : 'amber')}>{m.match_status}</span></td>
                    <td style={{ padding: '4px 8px', color: m.is_primary ? 'var(--green)' : 'var(--text3)' }}>{m.is_primary ? 'YES' : '--'}</td>
                    <td style={{ padding: '4px 8px', color: 'var(--text3)', fontSize: 9 }}>{(m.reason || '').slice(0, 40)}</td>
                    <td style={{ padding: '4px 8px', color: 'var(--text3)', fontSize: 9 }}>{m.created_at ? new Date(m.created_at).toLocaleDateString() : '--'}</td>
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
