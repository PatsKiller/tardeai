import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import SectionHeader from '../components/SectionHeader'
import MetricTile from '../components/MetricTile'
import StatusBadge from '../components/StatusBadge'
import ActionButton from '../components/ActionButton'
import { useApi } from '../hooks/useApi'

export default function SystemHealth() {
  const navigate = useNavigate()
  const [rk, setRk] = useState(0)
  const [healthTab, setHealthTab] = useState<'checks'|'events'>('checks')
  const { data } = useApi<any>(`/api/v2/system-health?_r=${rk}`)
  const { data: screeners } = useApi<any>(`/api/v2/finviz-screeners?_r=${rk}`)
  const { data: agentHealth } = useApi<any>(`/api/v2/execution-integrity?_r=${rk}`, 15000)

  const llm = data?.llm || {}
  const db = data?.db_tables || {}
  const cio = data?.cio_decisions || []

  // Agent health data
  const ahSummary = agentHealth?.summary || {}
  const ahChecks = agentHealth?.checks || []
  const ahEvents = agentHealth?.recent_events || []
  const critDown = ahChecks.filter((c: any) => c.severity === 'CRITICAL' && c.status !== 'OK' && c.status !== 'RECOVERED')
  const healthPct = ahSummary.total > 0 ? Math.round(((ahSummary.ok || 0) / ahSummary.total) * 100) : 0

  const sPill = (s: string) => {
    const color = (s === 'OK' || s === 'RECOVERED') ? 'var(--green)' : (s === 'STALE' || s === 'MISSING' || s === 'OUTPUT_INVALID') ? 'var(--red)' : 'var(--amber)'
    return { fontSize: 9, padding: '2px 6px', borderRadius: 4, fontWeight: 600,
      background: `color-mix(in srgb, ${color} 15%, transparent)`, color } as React.CSSProperties
  }
  const sevPill = (s: string) => {
    const color = s === 'CRITICAL' ? 'var(--red)' : s === 'WARN' ? 'var(--amber)' : 'var(--accent)'
    return { fontSize: 9, padding: '2px 6px', borderRadius: 4, fontWeight: 600,
      background: `color-mix(in srgb, ${color} 15%, transparent)`, color } as React.CSSProperties
  }

  return (
    <>
      <PageHeader title="System Health & Services" subtitle="Execution integrity, data products, services, LLM router" actions={
        <div style={{ display: 'flex', gap: 6 }}>
          <ActionButton onClick={() => navigate('/orchestration')} variant="secondary">Orchestration</ActionButton>
          <ActionButton onClick={() => setRk(k => k + 1)} variant="secondary">Refresh</ActionButton>
        </div>
      } />

      {/* ── Execution Integrity Agent ── */}
      <Card style={{ marginBottom: 14 }}>
        <SectionHeader title="Execution Integrity Agent" count={ahSummary.total} />
        {critDown.length > 0 && (
          <div style={{ padding: '8px 12px', margin: '0 12px 12px', background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.25)', borderRadius: 6, color: 'var(--red)', fontSize: 11, fontWeight: 600 }}>
            {critDown.length} CRITICAL down: {critDown.map((c: any) => c.component).join(', ')}
          </div>
        )}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(7, 1fr)', gap: 8, padding: '0 12px 12px' }}>
          <MetricTile label="Health" value={`${healthPct}%`} deltaColor={healthPct >= 80 ? 'var(--green)' : healthPct >= 50 ? 'var(--amber)' : 'var(--red)'} />
          <MetricTile label="Total" value={ahSummary.total || 0} />
          <MetricTile label="OK" value={ahSummary.ok || 0} deltaColor="var(--green)" />
          <MetricTile label="Stale" value={ahSummary.stale || 0} deltaColor={(ahSummary.stale || 0) > 0 ? 'var(--red)' : 'var(--text3)'} />
          <MetricTile label="Missing" value={ahSummary.missing || 0} deltaColor={(ahSummary.missing || 0) > 0 ? 'var(--red)' : 'var(--text3)'} />
          <MetricTile label="Failed" value={ahSummary.failed || 0} deltaColor={(ahSummary.failed || 0) > 0 ? 'var(--red)' : 'var(--text3)'} />
          <MetricTile label="Recovered" value={ahSummary.recovered || 0} deltaColor="var(--green)" />
        </div>
        <div style={{ display: 'flex', gap: 6, padding: '0 12px 8px' }}>
          {(['checks', 'events'] as const).map(t => (
            <button key={t} onClick={() => setHealthTab(t)}
              style={{ padding: '4px 10px', fontSize: 10, fontWeight: 600, border: 'none', borderRadius: 4, cursor: 'pointer',
                background: healthTab === t ? 'rgba(74,144,244,0.15)' : 'transparent', color: healthTab === t ? 'var(--accent)' : 'var(--text3)' }}>
              {t === 'checks' ? `Components (${ahChecks.length})` : `Events (${ahEvents.length})`}
            </button>
          ))}
        </div>
        <div style={{ maxHeight: 400, overflowY: 'auto' }}>
          {healthTab === 'checks' && (
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 10, fontFamily: 'monospace' }}>
              <thead>
                <tr style={{ borderBottom: '2px solid var(--border)' }}>
                  {['Component', 'Status', 'Severity', 'Schedule', 'Last OK', 'Action', 'Downstream', 'Error'].map(h => (
                    <th key={h} style={{ padding: '6px 8px', textAlign: 'left', fontSize: 8, color: 'var(--text3)', fontWeight: 600, textTransform: 'uppercase' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {ahChecks.length === 0 && <tr><td colSpan={8} style={{ padding: 16, textAlign: 'center', color: 'var(--text3)', fontStyle: 'italic' }}>No health data yet. Agent runs every 5 min.</td></tr>}
                {ahChecks.map((c: any) => (
                  <tr key={c.component} style={{ borderBottom: '1px solid var(--border-subtle)', background: c.severity === 'CRITICAL' && c.status !== 'OK' ? 'rgba(239,68,68,0.03)' : undefined }}>
                    <td style={{ padding: '5px 8px', fontWeight: 700, fontSize: 10 }}>{c.component}</td>
                    <td style={{ padding: '5px 8px' }}><span style={sPill(c.status)}>{c.status}</span></td>
                    <td style={{ padding: '5px 8px' }}><span style={sevPill(c.severity)}>{c.severity}</span></td>
                    <td style={{ padding: '5px 8px', color: 'var(--text3)', fontSize: 8 }}>{c.expected_schedule || '--'}</td>
                    <td style={{ padding: '5px 8px', color: 'var(--text3)', fontSize: 8 }}>{c.last_success_at ? new Date(c.last_success_at).toLocaleTimeString() : '--'}</td>
                    <td style={{ padding: '5px 8px', fontSize: 8 }}>{c.last_action || '--'}</td>
                    <td style={{ padding: '5px 8px', color: 'var(--text2)', fontSize: 8, maxWidth: 160, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{c.downstream_impact || '--'}</td>
                    <td style={{ padding: '5px 8px', color: 'var(--red)', fontSize: 8, maxWidth: 160, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{c.last_error || '--'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {healthTab === 'events' && (
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 10, fontFamily: 'monospace' }}>
              <thead>
                <tr style={{ borderBottom: '2px solid var(--border)' }}>
                  {['Time', 'Component', 'Event', 'Severity', 'Message', 'Result'].map(h => (
                    <th key={h} style={{ padding: '6px 8px', textAlign: 'left', fontSize: 8, color: 'var(--text3)', fontWeight: 600, textTransform: 'uppercase' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {ahEvents.length === 0 && <tr><td colSpan={6} style={{ padding: 16, textAlign: 'center', color: 'var(--text3)', fontStyle: 'italic' }}>No events yet.</td></tr>}
                {ahEvents.map((e: any, i: number) => (
                  <tr key={i} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                    <td style={{ padding: '5px 8px', color: 'var(--text3)', fontSize: 8, whiteSpace: 'nowrap' }}>{e.created_at ? new Date(e.created_at).toLocaleTimeString() : '--'}</td>
                    <td style={{ padding: '5px 8px', fontWeight: 600 }}>{e.component}</td>
                    <td style={{ padding: '5px 8px' }}>{e.event_type}</td>
                    <td style={{ padding: '5px 8px' }}><span style={sevPill(e.severity)}>{e.severity}</span></td>
                    <td style={{ padding: '5px 8px', color: 'var(--text2)', fontSize: 8, maxWidth: 250, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{e.message || '--'}</td>
                    <td style={{ padding: '5px 8px' }}>{e.success === true ? 'OK' : e.success === false ? 'FAIL' : '--'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </Card>

      {/* P0.5B: Control Plane Trust Panel */}
      <Card style={{ marginBottom: 14 }}>
        <SectionHeader title="Control Plane Trust" />
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 8, padding: '0 12px 12px' }}>
          <MetricTile label="safe_flock skips" value={agentHealth?.safe_flock?.lock_skips ?? 'N/A'}
            deltaColor={(agentHealth?.safe_flock?.lock_skips || 0) > 0 ? 'var(--amber)' : 'var(--green)'}
            delta={`${agentHealth?.safe_flock?.events_seen ?? 0} events (1h)`} />
          <MetricTile label="Repeated skips" value={agentHealth?.safe_flock?.repeated_lock_skips ?? 'N/A'}
            deltaColor={(agentHealth?.safe_flock?.repeated_lock_skips || 0) > 0 ? 'var(--red)' : 'var(--green)'} />
          <MetricTile label="Stale locks" value={agentHealth?.safe_flock?.stale_locks_cleared ?? 'N/A'}
            deltaColor={(agentHealth?.safe_flock?.stale_locks_cleared || 0) > 0 ? 'var(--amber)' : 'var(--green)'} />
          <MetricTile label="Time-stop overdue" value={agentHealth?.time_stop_summary?.overdue_count ?? 'N/A'}
            deltaColor={(agentHealth?.time_stop_summary?.overdue_count || 0) > 0 ? 'var(--red)' : 'var(--green)'}
            delta={`${agentHealth?.time_stop_summary?.review_due_count ?? 0} review due`} />
          <MetricTile label="Telegram bypass" value={agentHealth?.alert_routing?.bypass_router_files ?? 'N/A'}
            delta={`${agentHealth?.alert_routing?.direct_telegram_senders ?? 0} direct senders`}
            deltaColor="var(--amber)" />
        </div>
        {(agentHealth?.time_stop_summary?.overdue_positions || []).length > 0 && (
          <div style={{ padding: '6px 12px 12px', fontSize: 10, color: 'var(--text2)' }}>
            <span style={{ fontWeight: 600, color: 'var(--red)' }}>Overdue: </span>
            {(agentHealth?.time_stop_summary?.overdue_positions || []).map((p: any, i: number) => (
              <span key={i} style={{ marginRight: 10 }}>
                <span style={{ fontWeight: 600 }}>{p.symbol}</span>
                <span style={{ color: 'var(--text3)', marginLeft: 4 }}>{p.strategy} · {p.hold_days}d ({p.type}{p.max ? ` max ${p.max}d` : ''})</span>
              </span>
            ))}
          </div>
        )}
      </Card>

      {/* LLM Router */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 10, marginBottom: 14 }}>
        <MetricTile label="Local Ollama" value={llm?.local?.available ? 'Online' : 'Offline'}
          deltaColor={llm?.local?.available ? 'var(--green)' : 'var(--red)'}
          delta={llm?.local?.available ? `${llm.local.model || 'qwen3'}` : 'fallback to cloud APIs'}
          tooltip="Local LLM for fast/cheap analysis. When offline, falls back to Claude API (higher cost). Restart: systemctl --user start ollama" />
        <MetricTile label="Claude" value={llm?.claude?.configured ? 'Ready' : 'No Key'}
          deltaColor={llm?.claude?.configured ? 'var(--green)' : 'var(--text3)'}
          delta={llm?.claude?.configured ? 'ANTHROPIC_API_KEY set' : 'check .env file'}
          tooltip="API keys loaded from .env file. 'No Key' = ANTHROPIC_API_KEY not found." />
        <MetricTile label="Grok" value={llm?.grok?.configured ? 'Ready' : 'No Key'}
          deltaColor={llm?.grok?.configured ? 'var(--green)' : 'var(--amber)'}
          delta={llm?.grok?.configured ? 'XAI_API_KEY set' : 'optional — Claude is primary'}
          tooltip="xAI Grok API. Optional fallback when Claude is unavailable." />
        <MetricTile label="Daily Spend" value={`$${(llm?.daily_spend || 0).toFixed(4)}`}
          delta={`of $${(llm?.daily_budget || 2).toFixed(2)} budget`}
          deltaColor={(llm?.daily_spend || 0) > (llm?.daily_budget || 2) ? 'var(--red)' : 'var(--green)'}
          tooltip="LLM API spend today. Budget: $2/day. Local calls are free. Tracked in logs/llm_router.log." />
        <MetricTile label="Budget Left" value={`$${(llm?.budget_remaining || 0).toFixed(2)}`}
          deltaColor={(llm?.budget_remaining || 0) > 0.5 ? 'var(--green)' : (llm?.budget_remaining || 0) > 0 ? 'var(--amber)' : 'var(--red)'}
          delta={(llm?.budget_remaining || 0) <= 0 ? 'EXCEEDED — local only' : 'remaining today'} />
      </div>

      {!llm?.local?.available && (
        <div style={{ padding: '8px 12px', marginBottom: 12, background: 'var(--amber-dim)', border: '1px solid var(--amber)', borderRadius: 8, fontSize: 10, color: 'var(--amber)' }}>
          Ollama is offline — all LLM calls route to cloud APIs (higher cost). To restart: SSH to server and run <code style={{ background: 'var(--bg3)', padding: '1px 4px', borderRadius: 3 }}>systemctl --user start ollama</code>
        </div>
      )}

      {/* DB State */}
      <Card>
        <SectionHeader title="Database State" />
        {Object.keys(db).length > 0 ? (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8, padding: 12 }}>
            {Object.entries(db).map(([t, c]) => (
              <div key={t} style={{ fontSize: 10 }}>
                <div style={{ color: 'var(--text3)', fontSize: 8 }}>{t.replace('watchlist_', 'wl_').replace('ticker_', 'tk_')}</div>
                <div style={{ fontWeight: 700, color: Number(c) > 0 ? 'var(--text1)' : 'var(--text3)' }}>{Number(c).toLocaleString()}</div>
              </div>
            ))}
          </div>
        ) : (
          <div style={{ padding: 14, color: 'var(--text3)', fontSize: 11 }}>Database state unavailable — check Ops page for table inventory or verify DB connection.</div>
        )}
      </Card>

      {/* CIO Decisions */}
      <Card>
        <SectionHeader title="CIO Decision Distribution" />
        <div style={{ padding: 12 }}>
          {cio.map((d: any, i: number) => (
            <div key={i} style={{ display: 'flex', gap: 8, fontSize: 10, padding: '3px 0', borderBottom: '1px solid var(--border-subtle)' }}>
              <span style={{ fontWeight: 700, color: 'var(--accent)', minWidth: 120 }}>{d.action}</span>
              <span style={{ color: 'var(--text2)' }}>{d.cnt}</span>
            </div>
          ))}
        </div>
      </Card>

      {/* Finviz Screeners */}
      <Card>
        <SectionHeader title="Finviz Screeners" count={screeners?.screeners?.length} />
        <div style={{ maxHeight: 300, overflowY: 'auto' }}>
          {(screeners?.screeners || []).map((s: any) => (
            <div key={s.screener_id} style={{ display: 'flex', gap: 8, alignItems: 'center', padding: '8px 12px', borderBottom: '1px solid var(--border-subtle)' }}>
              <span style={{ fontWeight: 700, color: 'var(--accent)', fontSize: 11, minWidth: 180 }}>{s.display_name}</span>
              <span style={{ fontSize: 9, padding: '1px 6px', borderRadius: 99, background: 'rgba(74,144,244,0.1)', color: 'var(--accent)' }}>{s.strategy_type?.replace(/_/g, ' ')}</span>
              <span style={{ fontSize: 9, color: 'var(--text3)', flex: 1 }}>{s.description?.slice(0, 60)}</span>
              <a href={s.finviz_url} target="_blank" rel="noreferrer" style={{ fontSize: 9, color: 'var(--accent)' }}>Open</a>
            </div>
          ))}
        </div>
      </Card>

      {/* Data Product Freshness */}
      <Card title={data?.data_freshness ? `Data Product Health — ${data.data_freshness.summary}` : 'Data Product Health'} style={{ marginTop: 14 }}>
        {data?.data_freshness ? (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))', gap: 8 }}>
            {(data.data_freshness.products || []).map((p: any) => {
              const isWeekendStale = p.stale_reason === 'weekend_market_closed'
              const statusKey = p.status === 'fresh' ? 'green' : isWeekendStale ? 'info' : p.status === 'stale' ? 'red' : 'muted'
              const statusLabel = p.status === 'fresh' ? 'Fresh' : isWeekendStale ? 'Weekend Paused' : p.status === 'stale' ? 'Stale — Action Needed' : 'Unknown'
              const color = p.status === 'fresh' ? 'var(--green)' : isWeekendStale ? 'var(--accent)' : p.status === 'stale' ? 'var(--red)' : 'var(--text3)'
              return (
                <div key={p.product} title={p.remediation || ''} style={{ padding: '8px 12px', borderRadius: 6, border: `1px solid color-mix(in srgb, ${color} 20%, transparent)`, background: `color-mix(in srgb, ${color} 5%, transparent)`, cursor: p.remediation ? 'help' : 'default' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span style={{ fontSize: 11, fontWeight: 600, color }}>{p.product}</span>
                    <StatusBadge status={statusKey} label={statusLabel} />
                  </div>
                  <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 3 }}>
                    {p.age_hours != null ? `${Math.round(p.age_hours)}h old` : 'unknown'} / max {p.max_stale_hours}h
                  </div>
                  {p.owner && (
                    <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 2 }}>
                      Owner: {p.owner} · {p.schedule || 'manual'}
                    </div>
                  )}
                  {p.stale_reason && p.stale_reason !== 'weekend_market_closed' && p.remediation && (
                    <div style={{ fontSize: 9, color: 'var(--red)', marginTop: 2 }}>
                      Fix: <code style={{ fontSize: 8 }}>{p.remediation}</code>
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        ) : (
          <div style={{ padding: 14, color: 'var(--text3)', fontSize: 11 }}>
            Data product freshness not yet loaded. Refresh to check status.
          </div>
        )}
      </Card>

      {/* System Info */}
      <div style={{ marginTop: 14, padding: '10px 14px', background: 'rgba(16,20,28,0.92)', border: '1px solid rgba(255,255,255,0.07)', borderRadius: 10, fontSize: 10, color: 'var(--text3)' }}>
        Cron jobs: {data?.cron_jobs || 0} | Finviz screeners: {data?.finviz_screeners || screeners?.screeners?.length || 0} active | Validation suites: {data?.validation_suites || 0}
        {data?.finviz_screeners === 0 && screeners?.screeners?.length > 0 && (
          <span style={{ color: 'var(--amber)', marginLeft: 8 }}>Note: DB shows {screeners.screeners.length} screeners — health check may query different source</span>
        )}
      </div>
    </>
  )
}
