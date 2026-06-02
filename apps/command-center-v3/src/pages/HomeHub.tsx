import { useState } from 'react'
import { useApi } from '../hooks/useApi'
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'
import { fmt$, fmtPct } from '../lib/format'
import type { DrillContext } from '../components/DetailDrawer'

interface Props { onDrill: (ctx: DrillContext) => void }

const TABS = ['Snapshot', 'Morning Command', 'Brief'] as const

export default function HomeHub({ onDrill }: Props) {
  const [tab, setTab] = useState<typeof TABS[number]>('Snapshot')
  const { data: overview } = useApi<any>('/api/v2/overview', 60_000)
  const { data: readiness } = useApi<any>('/api/v2/paper-trade-readiness', 120_000)
  const { data: regime } = useApi<any>('/api/v2/risk-regime/latest', 120_000)
  const { data: tradeAi } = useApi<any>('/api/v2/trade-ai', 60_000)
  const { data: risk } = useApi<any>('/api/v2/risk', 60_000)
  const { data: metricsHist } = useApi<any>('/api/v2/system/metrics-history', 300_000)
  const { data: proposals } = useApi<any>('/api/v2/paper-proposals', 60_000)
  const { data: briefData } = useApi<any>('/api/v2/morning-brief', 300_000)

  const pv = overview?.portfolio_value
  const todayChg = overview?.today_change
  const journal = overview?.journal ?? {}
  const winRate = readiness?.win_rate
  const wrTrades = readiness?.closed_usable ?? journal?.trade_count
  const regimeLabel = regime?.regime_label ?? '—'
  const vix = tradeAi?.vix
  const goCount = tradeAi?.go_count ?? 0
  const waitCount = tradeAi?.wait_count ?? 0
  const avoidCount = tradeAi?.avoid_count ?? 0
  const journalPnl = journal?.total_pnl
  const positions = risk?.positions ?? []
  const triggered = positions.filter((p: any) => p.triggered)
  const heat = risk?.portfolio_heat_pct ?? 0
  const pendingCount = proposals?.pending_count ?? 0
  const pipelineStatus = overview?.pipeline_status

  // Equity curve from daily metrics
  const dailyMetrics = metricsHist?.metrics ?? []
  const equityCurve = [...dailyMetrics]
    .sort((a: any, b: any) => (a.metric_date ?? '').localeCompare(b.metric_date ?? ''))
    .map((m: any) => ({ date: m.metric_date?.slice(5), value: m.portfolio_value }))

  // Data freshness hours
  const lastRepriced = overview?.last_repriced
  let dataAgeHours = 0
  if (lastRepriced) {
    try {
      const parts = lastRepriced.replace(' ET', '').trim()
      // Approximate — show pipeline_status instead of computing exact hours
    } catch { /* */ }
  }

  const tiles = [
    { label: 'PORTFOLIO', value: pv != null ? fmt$(pv, 0) : '—', sub: todayChg != null ? `${todayChg >= 0 ? '+' : ''}${fmt$(todayChg, 0)} today` : '', color: 'var(--text0)',
      drill: { title: 'Portfolio', subtitle: '/api/v2/overview', endpoint: '/api/v2/overview', rows: overview ? [{ portfolio_value: pv, today_change: todayChg, position_count: overview.position_count, as_of: overview.as_of }] : [] } },
    { label: 'WIN RATE', value: winRate != null ? `${winRate}%` : (journal?.win_rate != null ? `${journal.win_rate}%` : '—'), sub: `${wrTrades ?? 0} trades`, color: (winRate ?? 0) >= 50 ? '#22c55e' : '#f59e0b',
      drill: { title: 'Win Rate', subtitle: '/api/v2/paper-trade-readiness', endpoint: '/api/v2/paper-trade-readiness', rows: readiness ? [{ win_rate: readiness.win_rate, profit_factor: readiness.profit_factor, closed_usable: readiness.closed_usable }] : [] } },
    { label: 'REGIME', value: regimeLabel.replace(/_/g, ' '), sub: vix != null ? `VIX ${vix}` : '', color: regimeLabel === 'risk_off' ? '#ef4444' : regimeLabel === 'risk_on' ? '#22c55e' : '#f59e0b',
      drill: { title: 'Market Regime', subtitle: '/api/v2/risk-regime/latest', endpoint: '/api/v2/risk-regime/latest', rows: regime ? [regime] : [] } },
    { label: 'SETUPS', value: `${goCount}/${waitCount}/${avoidCount}`, sub: 'GO/WAIT/NO', color: goCount > 0 ? '#22c55e' : 'var(--text3)',
      drill: { title: 'Trade Setups', subtitle: '/api/v2/trade-ai', endpoint: '/api/v2/trade-ai', rows: tradeAi ? [{ go_count: goCount, wait_count: waitCount, avoid_count: avoidCount, vix, run_label: tradeAi.run_label }] : [] } },
    { label: 'JOURNAL P&L', value: journalPnl != null ? fmt$(journalPnl, 0) : '—', sub: 'cumulative', color: (journalPnl ?? 0) >= 0 ? '#22c55e' : '#ef4444',
      drill: { title: 'Journal P&L', subtitle: '/api/v2/overview → journal', endpoint: '/api/v2/overview', rows: journal ? [journal] : [] } },
  ]

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 16 }}>
        <div>
          <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--text0)' }}>Home</div>
          <div style={{ fontSize: 11, color: 'var(--text3)' }}>{fmt$(pv ?? 0, 0)} · {overview?.position_count ?? 0} positions</div>
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

      {tab === 'Snapshot' && (
        <>
          {/* Metric tiles */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 10, marginBottom: 16 }}>
            {tiles.map(t => (
              <div key={t.label} onClick={() => onDrill(t.drill)}
                style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: '12px 14px', cursor: 'pointer' }}>
                <div style={{ fontSize: 8, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '.5px' }}>{t.label}</div>
                <div style={{ fontSize: 20, fontWeight: 700, color: t.color, fontFamily: 'monospace', marginTop: 2 }}>{t.value}</div>
                {t.sub && <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 2 }}>{t.sub}</div>}
              </div>
            ))}
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 280px', gap: 16, marginBottom: 16 }}>
            {/* Equity curve */}
            <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)' }}>Equity Curve</span>
                <span style={{ fontSize: 9, color: 'var(--text3)' }}>{equityCurve.length} days · /system/metrics-history</span>
              </div>
              {equityCurve.length < 2 ? (
                <div style={{ color: 'var(--text3)', fontSize: 11, padding: 30, textAlign: 'center' }}>Insufficient daily history ({equityCurve.length} days)</div>
              ) : (
                <ResponsiveContainer width="100%" height={200}>
                  <AreaChart data={equityCurve}>
                    <defs><linearGradient id="eqGrad" x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor="#60a5fa" stopOpacity={0.3} /><stop offset="95%" stopColor="#60a5fa" stopOpacity={0} /></linearGradient></defs>
                    <XAxis dataKey="date" tick={{ fontSize: 9, fill: 'var(--text3)' }} />
                    <YAxis domain={['auto', 'auto']} tick={{ fontSize: 9, fill: 'var(--text3)' }} tickFormatter={(v: number) => `$${(v / 1000).toFixed(0)}K`} />
                    <Tooltip contentStyle={{ background: 'var(--bg1)', border: '1px solid var(--border)', fontSize: 10 }} formatter={(v: number) => [fmt$(v, 0), 'Value']} />
                    <Area type="monotone" dataKey="value" stroke="#60a5fa" fill="url(#eqGrad)" strokeWidth={2} />
                  </AreaChart>
                </ResponsiveContainer>
              )}
            </div>

            {/* Alert rail */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {triggered.length > 0 && (
                <div onClick={() => onDrill({ title: `${triggered.length} Stops Triggered`, subtitle: 'Positions below stop', endpoint: '/api/v2/risk', rows: triggered })}
                  style={{ padding: '10px 12px', background: 'rgba(239,68,68,.12)', border: '1px solid rgba(239,68,68,.25)', borderRadius: 8, cursor: 'pointer' }}>
                  <div style={{ fontSize: 12, fontWeight: 700, color: '#ef4444' }}>{triggered.length} stops triggered</div>
                  <div style={{ fontSize: 10, color: '#fca5a5', marginTop: 2 }}>{triggered.map((p: any) => p.symbol).join(' ')}</div>
                </div>
              )}
              {heat > 5 && (
                <div onClick={() => onDrill({ title: 'Portfolio Heat', subtitle: `${heat}% over 5% threshold`, endpoint: '/api/v2/risk', rows: [{ portfolio_heat_pct: heat, total_risk: risk?.total_risk_dollars }] })}
                  style={{ padding: '10px 12px', background: 'rgba(245,158,11,.12)', border: '1px solid rgba(245,158,11,.25)', borderRadius: 8, cursor: 'pointer' }}>
                  <div style={{ fontSize: 12, fontWeight: 700, color: '#f59e0b' }}>Heat {heat}%</div>
                  <div style={{ fontSize: 10, color: '#fbbf24', marginTop: 2 }}>above 5% threshold</div>
                </div>
              )}
              <div onClick={() => onDrill({ title: 'Data Freshness', subtitle: pipelineStatus ?? '—', endpoint: '/api/v2/overview', rows: [{ pipeline_status: pipelineStatus, last_repriced: lastRepriced, as_of: overview?.as_of }] })}
                style={{ padding: '10px 12px', background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 8, cursor: 'pointer' }}>
                <div style={{ fontSize: 12, fontWeight: 600, color: pipelineStatus === 'fresh' ? 'var(--text2)' : '#f59e0b' }}>
                  Data: {pipelineStatus ?? '—'}
                </div>
                <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 2 }}>last: {lastRepriced ?? '—'}</div>
              </div>
            </div>
          </div>

          {/* Action inbox */}
          <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
            <div style={{ display: 'flex', gap: 8, alignItems: 'baseline', marginBottom: 10 }}>
              <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)' }}>Action Inbox</span>
              <span style={{ fontSize: 9, color: 'var(--text3)' }}>read-only — drill to source, no write controls</span>
            </div>
            {triggered.length > 0 && (
              <div onClick={() => onDrill({ title: 'Triggered Stops', subtitle: 'Verify broker executed', endpoint: '/api/v2/risk', rows: triggered })}
                style={{ padding: '8px 10px', borderBottom: '1px solid var(--border)', cursor: 'pointer', fontSize: 11, color: '#ef4444' }}>
                {triggered.length} triggered stops — verify broker executed
              </div>
            )}
            {pendingCount > 0 && (
              <div onClick={() => onDrill({ title: 'Pending Proposals', subtitle: `${pendingCount} awaiting review`, endpoint: '/api/v2/paper-proposals', rows: [{ pending_count: pendingCount }] })}
                style={{ padding: '8px 10px', borderBottom: '1px solid var(--border)', cursor: 'pointer', fontSize: 11, color: 'var(--text2)' }}>
                {pendingCount} proposals awaiting review
              </div>
            )}
            {triggered.length === 0 && pendingCount === 0 && (
              <div style={{ fontSize: 11, color: 'var(--text3)', padding: 8 }}>No pending actions</div>
            )}
            <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 8 }}>Source: /api/v2/risk + /api/v2/paper-proposals</div>
          </div>
        </>
      )}

      {tab === 'Morning Command' && briefData && (
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 10 }}>Morning Brief</div>
          <div style={{ fontSize: 9, color: 'var(--text3)', marginBottom: 12 }}>Generated: {briefData.generated_at ?? '—'}</div>
          {briefData.action_items && (
            <div style={{ marginBottom: 12 }}>
              <div style={{ fontSize: 11, fontWeight: 600, color: '#f59e0b', marginBottom: 6 }}>Action Items</div>
              {(Array.isArray(briefData.action_items) ? briefData.action_items : []).map((a: any, i: number) => (
                <div key={i} onClick={() => onDrill({ title: `Action ${i+1}`, subtitle: '', endpoint: '/api/v2/morning-brief', rows: [typeof a === 'object' ? a : {item: a}] })}
                  style={{ padding: '4px 6px', borderBottom: '1px solid var(--border)', cursor: 'pointer', fontSize: 11, color: 'var(--text2)' }}>
                  {typeof a === 'string' ? a : (a.title ?? a.action ?? JSON.stringify(a)).slice(0, 100)}
                </div>
              ))}
            </div>
          )}
          {briefData.strategy_health && (
            <div style={{ marginBottom: 12 }}>
              <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text2)', marginBottom: 6 }}>Strategy Health</div>
              <div style={{ fontSize: 10, color: 'var(--text2)' }}>{typeof briefData.strategy_health === 'string' ? briefData.strategy_health : JSON.stringify(briefData.strategy_health).slice(0, 200)}</div>
            </div>
          )}
          <div style={{ fontSize: 8, color: 'var(--text3)' }}>Source: /api/v2/morning-brief</div>
        </div>
      )}
      {tab === 'Morning Command' && !briefData && <div style={{ color: 'var(--text3)', fontSize: 11, padding: 20 }}>Loading morning brief...</div>}

      {tab === 'Brief' && briefData && (
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 10 }}>Overnight Activity</div>
          {briefData.overnight_activity ? (
            <div style={{ fontSize: 11, color: 'var(--text2)', lineHeight: 1.6 }}>
              {typeof briefData.overnight_activity === 'string' ? briefData.overnight_activity : JSON.stringify(briefData.overnight_activity, null, 2).slice(0, 500)}
            </div>
          ) : <div style={{ color: 'var(--text3)', fontSize: 11 }}>No overnight activity data</div>}
          <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 8 }}>Source: /api/v2/morning-brief → overnight_activity</div>
        </div>
      )}
      {tab === 'Brief' && !briefData && <div style={{ color: 'var(--text3)', fontSize: 11, padding: 20 }}>Loading brief...</div>}
    </div>
  )
}
