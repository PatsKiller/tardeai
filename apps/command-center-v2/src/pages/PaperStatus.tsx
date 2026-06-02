import React from 'react'
import OpenTradesCard from '../components/OpenTradesCard'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import SectionHeader from '../components/SectionHeader'
import MetricTile from '../components/MetricTile'
import { useApi } from '../hooks/useApi'
import { fmt$ } from '../lib/format'

const dot = (ok: boolean): React.CSSProperties => ({
  display: 'inline-block', width: 8, height: 8, borderRadius: '50%',
  background: ok ? 'var(--green)' : 'var(--red)', marginRight: 6, flexShrink: 0
})
const mono: React.CSSProperties = { fontFamily: 'monospace' }
const lbl: React.CSSProperties = { fontSize: 9, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '0.3px' }
const val: React.CSSProperties = { fontSize: 12, color: 'var(--text0)', fontWeight: 600, ...mono }
const row: React.CSSProperties = { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '4px 0', borderBottom: '1px solid var(--border)' }

export default function PaperStatus() {
  const { data, loading, refetch } = useApi<any>('/api/v2/paper-status', 30000)
  const { data: monData } = useApi<any>('/api/v2/open-trade-monitor', 30000)
  const { data: llmData } = useApi<any>('/api/v2/local-llm-status', 60000)
  const { data: curationData } = useApi<any>('/api/v2/agent-curation-events', 60000)
  const { data: readiness } = useApi<any>('/api/v2/paper-trade-readiness', 120000)

  if (loading) return <div style={{ padding: 24, color: 'var(--text3)' }}>Loading...</div>

  const a = data?.alpaca || {}
  const pt = data?.paper_trading || {}
  const risk = data?.risk || {}
  const pending = data?.pending_proposals ?? 0
  const mon = monData || {}
  const monSum = mon.summary || {}
  const llm = llmData || {}
  const curation = curationData || {}

  const kv = (label: string, value: any, isBool?: boolean) => (
    <div style={row} key={label}>
      <span style={lbl}>{label}</span>
      <span style={{ ...val, color: isBool ? (value ? 'var(--green)' : 'var(--red)') : 'var(--text0)' }}>
        {isBool ? (value ? 'Yes' : 'No') : (value ?? '--')}
      </span>
    </div>
  )

  const currency = (label: string, v: number | null | undefined) => (
    <div style={row} key={label}>
      <span style={lbl}>{label}</span>
      <span style={val}>{v != null ? fmt$(v, 2) : '--'}</span>
    </div>
  )

  return (
    <>
      <PageHeader title="Paper Trading Status" subtitle="Alpaca paper account health and today's activity" actions={
        <button onClick={refetch} style={{ padding: '4px 10px', fontSize: 10, background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 6, color: 'var(--text2)', cursor: 'pointer' }}>Refresh</button>
      } />

      {/* Statistical Readiness */}
      {readiness && (
        <div style={{ marginBottom: 14, padding: '12px 16px', background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
            <div>
              <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)' }}>Statistical Readiness</span>
              <span style={{ marginLeft: 8, fontSize: 10, padding: '2px 8px', borderRadius: 4, fontWeight: 600,
                background: readiness.level?.startsWith('P0') ? 'rgba(239,68,68,.1)' : readiness.level?.startsWith('P1') ? 'rgba(245,158,11,.1)' : 'rgba(34,197,94,.1)',
                color: readiness.level?.startsWith('P0') ? '#ef4444' : readiness.level?.startsWith('P1') ? '#f59e0b' : '#22c55e',
              }}>{readiness.level?.replace(/_/g, ' ')}</span>
            </div>
            <div style={{ fontSize: 9, color: '#ef4444', fontWeight: 700 }}>LIVE TRADING PROHIBITED</div>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)', gap: 8, marginBottom: 8 }}>
            {[
              { label: 'Usable Trades', value: readiness.closed_usable, color: 'var(--text0)' },
              { label: 'To 2,000', value: readiness.distance_to_2000, color: '#f59e0b' },
              { label: 'To 4,000', value: readiness.distance_to_4000, color: '#ef4444' },
              { label: 'Win Rate', value: readiness.win_rate != null ? `${readiness.win_rate}%` : '—', color: 'var(--text0)' },
              { label: 'Profit Factor', value: readiness.profit_factor ?? '—', color: 'var(--text0)' },
              { label: 'Net PnL', value: readiness.net_pnl != null ? `$${readiness.net_pnl.toFixed(0)}` : '—', color: readiness.net_pnl > 0 ? '#22c55e' : '#ef4444' },
            ].map(k => (
              <div key={k.label} style={{ textAlign: 'center' }}>
                <div style={{ fontSize: 18, fontWeight: 700, color: k.color, fontFamily: 'monospace' }}>{k.value}</div>
                <div style={{ fontSize: 9, color: 'var(--text3)' }}>{k.label}</div>
              </div>
            ))}
          </div>
          {/* Progress bars */}
          <div style={{ display: 'flex', gap: 12 }}>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 9, color: 'var(--text3)', marginBottom: 2 }}>Progress to 2,000 ({readiness.pct_to_2000}%)</div>
              <div style={{ height: 6, background: 'var(--bg2)', borderRadius: 3, overflow: 'hidden' }}>
                <div style={{ width: `${Math.min(100, readiness.pct_to_2000 || 0)}%`, height: '100%', background: '#f59e0b', borderRadius: 3, minWidth: 2 }} />
              </div>
            </div>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 9, color: 'var(--text3)', marginBottom: 2 }}>Progress to 4,000 ({readiness.pct_to_4000}%)</div>
              <div style={{ height: 6, background: 'var(--bg2)', borderRadius: 3, overflow: 'hidden' }}>
                <div style={{ width: `${Math.min(100, readiness.pct_to_4000 || 0)}%`, height: '100%', background: '#ef4444', borderRadius: 3, minWidth: 2 }} />
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Open trades intelligence */}
      <OpenTradesCard />

      {/* Alpaca API Card */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 14 }}>
        <Card>
          <SectionHeader title="Alpaca API" />
          <div style={{ padding: '8px 12px' }}>
            <div style={row}>
              <span style={lbl}>Status</span>
              <span style={{ display: 'flex', alignItems: 'center', ...val }}>
                <span style={dot(a.connected)} />
                {a.connected ? 'Connected' : 'Disconnected'}
              </span>
            </div>
            {kv('Configured', a.configured, true)}
            {kv('Account Status', a.account_status)}
            {kv('Paper Endpoint', a.paper_endpoint)}
            {kv('API Key', a.api_key_masked)}
            {currency('Equity', a.equity)}
            {currency('Buying Power', a.buying_power)}
            {currency('Cash', a.cash)}
            {kv('Open Positions', a.open_positions)}
            {kv('Open Orders', a.open_orders)}
            {a.last_error && (
              <div style={{ ...row, borderBottom: 'none' }}>
                <span style={lbl}>Last Error</span>
                <span style={{ ...val, color: 'var(--red)', fontSize: 10, maxWidth: 200, textAlign: 'right' }}>{a.last_error}</span>
              </div>
            )}
          </div>
        </Card>

        <Card>
          <SectionHeader title="Adapter Health" />
          <div style={{ padding: '8px 12px' }}>
            <div style={row}>
              <span style={lbl}>Enabled</span>
              <span style={{ display: 'flex', alignItems: 'center', ...val }}>
                <span style={dot(pt.enabled)} />
                {pt.enabled ? 'Yes' : 'No'}
              </span>
            </div>
            <div style={row}>
              <span style={lbl}>Trading Blocked</span>
              <span style={{ display: 'flex', alignItems: 'center', ...val }}>
                <span style={dot(!pt.trading_blocked)} />
                {pt.trading_blocked ? 'BLOCKED' : 'Clear'}
              </span>
            </div>
          </div>

          <SectionHeader title="Halt Flags" />
          <div style={{ padding: '8px 12px' }}>
            {risk && typeof risk === 'object' && Object.keys(risk).length > 0 ? (
              Object.entries(risk).map(([k, v]) => (
                <div style={row} key={k}>
                  <span style={lbl}>{k.replace(/_/g, ' ')}</span>
                  <span style={{ display: 'flex', alignItems: 'center', ...val }}>
                    <span style={dot(v === false || v === 0 || v === 'ok')} />
                    {String(v)}
                  </span>
                </div>
              ))
            ) : (
              <div style={{ fontSize: 10, color: 'var(--text3)', padding: 4 }}>No halt flags reported</div>
            )}
          </div>
        </Card>
      </div>

      {/* Today Summary */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)', gap: 10, marginBottom: 14 }}>
        <MetricTile label="Open Trades" value={pt.open_trades ?? 0} />
        <MetricTile label="Pending Proposals" value={pending} deltaColor={pending > 0 ? 'var(--amber)' : 'var(--text3)'} delta={pending > 0 ? 'needs review' : 'none'} />
        <MetricTile label="Today Opened" value={pt.today_opened ?? 0} />
        <MetricTile label="Today Closed" value={pt.today_closed ?? 0} />
        <MetricTile label="Realized P&L" value={pt.today_realized != null ? fmt$(pt.today_realized, 2) : '--'}
          deltaColor={pt.today_realized > 0 ? 'var(--green)' : pt.today_realized < 0 ? 'var(--red)' : 'var(--text3)'} />
        <MetricTile label="Unrealized P&L" value={pt.today_unrealized != null ? fmt$(pt.today_unrealized, 2) : '--'}
          deltaColor={pt.today_unrealized > 0 ? 'var(--green)' : pt.today_unrealized < 0 ? 'var(--red)' : 'var(--text3)'} />
      </div>

      {/* Session 15: Monitor + LLM + Curation tiles */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12, marginBottom: 14 }}>
        {/* Open Trade Monitor */}
        <Card>
          <SectionHeader title="Open Trade Monitor" />
          <div style={{ padding: '8px 12px' }}>
            {kv('Open Trades', monSum.open_count ?? 0)}
            {kv('Critical Alerts', monSum.critical_alerts ?? 0)}
            {kv('Warnings', monSum.warn_alerts ?? 0)}
            {kv('Stale Trades', monSum.stale_trades ?? 0)}
            {currency('Unrealized P&L', monSum.total_unrealized_pnl)}
            {currency('Open Risk', monSum.total_open_risk)}
          </div>
        </Card>

        {/* Local LLM Status */}
        <Card>
          <SectionHeader title="Local LLM" />
          <div style={{ padding: '8px 12px' }}>
            <div style={row}>
              <span style={lbl}>Status</span>
              <span style={{ display: 'flex', alignItems: 'center', ...val }}>
                <span style={dot(!!llm.available)} />
                {llm.available ? 'Available' : 'Unavailable'}
              </span>
            </div>
            {kv('Model', llm.model || '--')}
            {kv('Last Run', llm.last_status || '--')}
            {kv('Items Processed', llm.items_processed_last_run ?? 0)}
            {kv('Trades Awaiting', llm.trades_awaiting_analysis ?? 0)}
            {kv('Proposals Awaiting', llm.proposals_awaiting_analysis ?? 0)}
          </div>
        </Card>

        {/* Agent Curation */}
        <Card>
          <SectionHeader title="Agent Curation" />
          <div style={{ padding: '8px 12px' }}>
            {kv('Total Events', curation.count ?? 0)}
            {(curation.events || []).slice(0, 4).map((e: any, i: number) => (
              <div style={{ ...row, flexDirection: 'column', alignItems: 'flex-start', gap: 2 }} key={i}>
                <span style={{ fontSize: 10, color: 'var(--text2)' }}>
                  <span style={{ fontWeight: 600 }}>{e.agent_name}</span> · {e.event_type}
                </span>
                <span style={{ fontSize: 10, color: 'var(--text3)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '100%' }}>
                  {e.event_summary?.slice(0, 80) || '--'}
                </span>
              </div>
            ))}
            {(curation.events || []).length === 0 && (
              <div style={{ fontSize: 10, color: 'var(--text3)', padding: 4 }}>No curation events yet</div>
            )}
          </div>
        </Card>
      </div>

      {/* Recent Alerts */}
      {(mon.alerts || []).length > 0 && (
        <Card>
          <SectionHeader title={`Recent Alerts (${(mon.alerts || []).length})`} />
          <div style={{ padding: '8px 12px' }}>
            {(mon.alerts || []).slice(0, 8).map((a: any) => (
              <div style={row} key={a.id}>
                <span style={{
                  fontSize: 10, fontWeight: 700, minWidth: 60,
                  color: a.severity === 'CRITICAL' ? 'var(--red)' : a.severity === 'WARN' ? 'var(--amber)' : 'var(--text2)',
                }}>{a.severity}</span>
                <span style={{ ...val, flex: 1 }}>{a.symbol} — {a.alert_type}</span>
                <span style={{ fontSize: 9, color: 'var(--text3)' }}>
                  {a.created_at ? new Date(a.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : ''}
                </span>
              </div>
            ))}
          </div>
        </Card>
      )}
    </>
  )
}
