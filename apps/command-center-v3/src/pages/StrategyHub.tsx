import { useState } from 'react'
import { useApi } from '../hooks/useApi'
import { BarChart, Bar, XAxis, YAxis, ReferenceLine, ResponsiveContainer, LineChart, Line, Tooltip, Legend } from 'recharts'
import type { DrillContext } from '../components/DetailDrawer'
import BacktestPanel from '../components/BacktestPanel'

interface Props { onDrill: (ctx: DrillContext) => void }

const TABS = ['Analytics', 'Desk', 'Incubator', 'Backtest'] as const

export default function StrategyHub({ onDrill }: Props) {
  const [tab, setTab] = useState<typeof TABS[number]>('Analytics')
  const { data: intel } = useApi<any>('/api/v2/strategy-intelligence', 120_000)
  const { data: configs } = useApi<any>('/api/v2/strategy-configs', 120_000)
  const { data: desk } = useApi<any>('/api/v2/strategy-desk', 120_000)
  const { data: readiness } = useApi<any>('/api/v2/paper-trade-readiness', 120_000)
  const { data: btResults } = useApi<any>('/api/v2/backtesting/results', 120_000)
  const { data: incubator } = useApi<any>('/api/v2/incubator', 120_000)
  const { data: incAdv } = useApi<any>('/api/v2/setup-advisory/candidates?entity=incubator', 120_000)
  const incAdvMap: Record<string, any> = {}
  for (const a of (incAdv?.advisories ?? [])) incAdvMap[a.symbol] = a
  const advColor = (f?: string) => f === 'caution' ? '#ef4444' : f === 'favorable' ? '#22c55e' : 'var(--text3)'

  const strategies = intel?.strategies ?? []
  const configMap = configs?.strategies ?? {}
  const topStrats = readiness?.top_strategies ?? []
  const btData = btResults ?? []

  // Merge real paper trade win rates with strategy intelligence
  const paperWrMap: Record<string, { win_rate: number; closed: number; pnl: number; profit_factor?: number }> = {}
  for (const s of topStrats) {
    if (s.closed > 0) {
      const losses = s.closed - (s.wins ?? 0)
      const grossProfit = s.net_pnl > 0 ? s.net_pnl : Math.max(0, (s.wins ?? 0) * Math.abs(s.avg_pnl ?? 0))
      paperWrMap[s.strategy] = { win_rate: s.win_rate, closed: s.closed, pnl: s.net_pnl }
    }
  }

  // Win rate bar chart data — only strategies with closed trades
  const wrBars = topStrats
    .filter((s: any) => s.closed > 0)
    .map((s: any) => ({
      strategy: s.strategy.replace(/_/g, ' '),
      strategy_id: s.strategy,
      win_rate: s.win_rate ?? 0,
      closed: s.closed,
      pnl: s.net_pnl,
      fill: (s.win_rate ?? 0) >= 55 ? '#22c55e' : (s.win_rate ?? 0) >= 45 ? '#f59e0b' : '#ef4444',
    }))
    .sort((a: any, b: any) => b.win_rate - a.win_rate)

  // Equity curve from backtesting — top 4 by trade count
  const topBt = [...btData]
    .sort((a: any, b: any) => (b.simulated_trades ?? 0) - (a.simulated_trades ?? 0))
    .slice(0, 4)
  let equityCurves: any[] = []
  try {
    // Build unified data points from equity_curve_json
    const curvesByStrat: Record<string, number[]> = {}
    for (const bt of topBt) {
      const curve = typeof bt.equity_curve_json === 'string' ? JSON.parse(bt.equity_curve_json) : bt.equity_curve_json
      if (Array.isArray(curve) && curve.length > 0) {
        curvesByStrat[bt.strategy_id] = curve.map((p: any) => typeof p === 'number' ? p : p.cumulative_r ?? p.value ?? 0)
      }
    }
    const maxLen = Math.max(...Object.values(curvesByStrat).map(c => c.length), 0)
    for (let i = 0; i < maxLen; i++) {
      const point: any = { trade: i + 1 }
      for (const [sid, curve] of Object.entries(curvesByStrat)) {
        point[sid] = curve[i] ?? curve[curve.length - 1] ?? 0
      }
      equityCurves.push(point)
    }
  } catch { /* empty state */ }

  const COLORS = ['#22c55e', '#60a5fa', '#f59e0b', '#a855f7']

  // Scoreboard: merge intel + paper performance
  const scoreboard = strategies
    .map((s: any) => {
      const paper = paperWrMap[s.strategy_id]
      const cfg = configMap[s.strategy_id]
      return {
        ...s,
        win_rate: paper?.win_rate ?? s.win_rate,
        closed: paper?.closed ?? s.trade_count ?? 0,
        pnl: paper?.pnl ?? 0,
        timeframe_class: cfg?.timeframe_class ?? '—',
        eligible: s.governance_state === 'VALIDATED' || (paper?.win_rate ?? 0) >= 55,
      }
    })
    .sort((a: any, b: any) => (b.closed ?? 0) - (a.closed ?? 0))

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 16 }}>
        <div>
          <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--text0)' }}>Strategy Hub</div>
          <div style={{ fontSize: 11, color: 'var(--text3)' }}>{strategies.length} strategies · {topStrats.reduce((a: number, s: any) => a + (s.closed ?? 0), 0)} closed paper trades</div>
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

      {tab === 'Analytics' && (
        <>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 16 }}>
            {/* Win rate bar chart */}
            <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 12 }}>
                <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)' }}>Win Rate by Strategy</span>
                <span style={{ fontSize: 9, color: 'var(--text3)' }}>dashed = 55% gate</span>
              </div>
              {wrBars.length === 0 ? (
                <div style={{ color: 'var(--text3)', fontSize: 11, padding: 20, textAlign: 'center' }}>No closed paper trades yet</div>
              ) : (
                <ResponsiveContainer width="100%" height={wrBars.length * 36 + 20}>
                  <BarChart data={wrBars} layout="vertical" margin={{ left: 10, right: 40 }}>
                    <XAxis type="number" domain={[0, 100]} tick={{ fontSize: 9, fill: 'var(--text3)' }} />
                    <YAxis dataKey="strategy" type="category" width={130} tick={{ fontSize: 10, fill: 'var(--text2)' }} />
                    <ReferenceLine x={55} stroke="#60a5fa" strokeDasharray="4 4" strokeWidth={1.5} />
                    <Tooltip contentStyle={{ background: 'var(--bg1)', border: '1px solid var(--border)', fontSize: 11 }}
                      formatter={(v: number) => [`${v}%`, 'Win Rate']} />
                    <Bar dataKey="win_rate" radius={[0, 4, 4, 0]} barSize={20}
                      fill="#22c55e"
                      onClick={(d: any) => onDrill({
                        title: `${d.strategy_id} Performance`, subtitle: 'Paper trade win rate',
                        endpoint: '/api/v2/paper-trade-readiness',
                        rows: [{ strategy: d.strategy_id, win_rate: `${d.win_rate}%`, closed: d.closed, pnl: `$${d.pnl?.toFixed(2)}` }],
                      })}
                    />
                  </BarChart>
                </ResponsiveContainer>
              )}
              <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 6 }}>Source: /api/v2/paper-trade-readiness (real paper trades)</div>
            </div>

            {/* Equity curve overlay */}
            <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 12 }}>
                <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)' }}>Equity Curve Overlay</span>
                <span style={{ fontSize: 9, color: 'var(--text3)' }}>cumulative R, top 4</span>
              </div>
              {equityCurves.length === 0 ? (
                <div style={{ color: 'var(--text3)', fontSize: 11, padding: 20, textAlign: 'center' }}>Insufficient backtest data for equity curves</div>
              ) : (
                <ResponsiveContainer width="100%" height={240}>
                  <LineChart data={equityCurves}>
                    <XAxis dataKey="trade" tick={{ fontSize: 9, fill: 'var(--text3)' }} />
                    <YAxis tick={{ fontSize: 9, fill: 'var(--text3)' }} />
                    <Tooltip contentStyle={{ background: 'var(--bg1)', border: '1px solid var(--border)', fontSize: 10 }} />
                    <Legend wrapperStyle={{ fontSize: 9 }} />
                    {topBt.map((bt: any, i: number) => (
                      <Line key={bt.strategy_id} dataKey={bt.strategy_id} stroke={COLORS[i]} strokeWidth={2} dot={false}
                        name={bt.strategy_id.replace(/_/g, ' ')} />
                    ))}
                  </LineChart>
                </ResponsiveContainer>
              )}
              <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 6 }}>Source: /api/v2/backtesting/results (equity_curve_json)</div>
            </div>
          </div>

          {/* Scoreboard */}
          <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 10 }}>Scoreboard</div>
            <div style={{ fontSize: 9, color: 'var(--text3)', marginBottom: 8 }}>Click a row to drill into strategy detail</div>
            <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr 1fr 1fr 1fr', gap: 0, fontSize: 9, color: 'var(--text3)', padding: '4px 8px', borderBottom: '1px solid var(--border)' }}>
              <span>Strategy</span><span>Win Rate</span><span>Profit Factor</span><span>Trades</span><span>Status</span>
            </div>
            {scoreboard.map((s: any) => (
              <div key={s.strategy_id}
                onClick={() => onDrill({
                  title: s.display_name || s.strategy_id, subtitle: `${s.governance_state} · ${s.closed} trades`,
                  endpoint: '/api/v2/strategy-intelligence',
                  rows: [{
                    strategy_id: s.strategy_id, governance_state: s.governance_state,
                    win_rate: s.win_rate != null ? `${s.win_rate}%` : '—',
                    profit_factor: s.profit_factor ?? '—', avg_r: s.avg_r ?? '—',
                    trade_count: s.closed, timeframe: s.timeframe_class,
                    pnl: s.pnl != null ? `$${s.pnl.toFixed(2)}` : '—',
                  }],
                })}
                style={{
                  display: 'grid', gridTemplateColumns: '2fr 1fr 1fr 1fr 1fr', gap: 0,
                  padding: '8px 8px', borderBottom: '1px solid var(--border)', cursor: 'pointer',
                  opacity: s.closed === 0 ? 0.4 : 1,
                }}
              >
                <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--text0)', fontFamily: 'monospace' }}>{s.strategy_id}</span>
                <span style={{ fontSize: 11, color: s.win_rate != null ? ((s.win_rate ?? 0) >= 55 ? '#22c55e' : (s.win_rate ?? 0) >= 45 ? '#f59e0b' : '#ef4444') : 'var(--text3)' }}>
                  {s.win_rate != null ? `${s.win_rate}%` : '—'}
                </span>
                <span style={{ fontSize: 11, color: 'var(--text2)' }}>{s.profit_factor != null ? s.profit_factor.toFixed(2) : '—'}</span>
                <span style={{ fontSize: 11, color: s.closed === 0 ? 'var(--text3)' : 'var(--text0)' }}>{s.closed || 'no trades'}</span>
                <span style={{
                  fontSize: 10, fontWeight: 600,
                  color: s.eligible ? '#22c55e' : s.closed === 0 ? 'var(--text3)' : '#f59e0b',
                }}>{s.closed === 0 ? 'no data' : s.eligible ? 'eligible' : 'below gate'}</span>
              </div>
            ))}
          </div>
        </>
      )}

      {tab === 'Desk' && desk && (
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 10 }}>Strategy Desk</div>
          {(desk.strategies ?? []).map((s: any) => (
            <div key={s.strategy_id}
              onClick={() => onDrill({
                title: s.display_name, subtitle: s.strategy_id,
                endpoint: '/api/v2/strategy-desk',
                rows: [{ ...s }],
              })}
              style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 8px', borderBottom: '1px solid var(--border)', cursor: 'pointer' }}
            >
              <div>
                <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text0)' }}>{s.display_name}</div>
                <div style={{ fontSize: 9, color: 'var(--text3)' }}>{s.timeframe} · risk ${s.risk_per_trade}/trade</div>
              </div>
              <div style={{ textAlign: 'right' }}>
                <div style={{ fontSize: 10, color: s.signals_today > 0 ? '#22c55e' : 'var(--text3)' }}>{s.signals_today} signals today</div>
                <div style={{ fontSize: 9, color: 'var(--text3)' }}>{s.status}</div>
              </div>
            </div>
          ))}
        </div>
      )}

      {tab === 'Incubator' && incubator && (
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 12 }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)' }}>Incubator ({incubator.total ?? 0} symbols)</div>
            <span style={{ fontSize: 10, color: '#22c55e' }}>{incubator.promoted ?? 0} promoted · {incubator.active ?? 0} active</span>
          </div>
          <div style={{ maxHeight: 400, overflowY: 'auto' }}>
            {(incubator.universe ?? []).slice(0, 30).map((item: any, i: number) => {
              const adv = incAdvMap[item.symbol]
              return (
              <div key={i}
                onClick={() => onDrill({ title: item.symbol, subtitle: `${item.strategy_id} · ${item.status}`, endpoint: '/api/v2/incubator', rows: [adv ? { ...item, setup_advisory: adv.note, setup_advisory_flag: adv.advisory_flag, setup_prior_score: adv.prior_score } : item] })}
                style={{ display: 'grid', gridTemplateColumns: '1fr 1.6fr 1fr 0.7fr 1fr', padding: '5px 6px', borderBottom: '1px solid var(--border)', cursor: 'pointer', fontSize: 11, alignItems: 'center' }}>
                <span style={{ fontWeight: 600, color: 'var(--text0)', fontFamily: 'monospace' }}>{item.symbol}</span>
                <span style={{ color: 'var(--text3)', fontSize: 9 }}>{item.strategy_id}</span>
                <span style={{ color: item.status === 'PROMOTED' ? '#22c55e' : item.lifecycle_state === 'graduated' ? '#06b6d4' : 'var(--text2)', fontSize: 10 }}>{item.status}</span>
                <span style={{ color: 'var(--text3)', fontSize: 9 }}>{item.latest_score ?? '—'}</span>
                {adv ? <span title={adv.note} style={{ justifySelf: 'end', fontSize: 8, padding: '1px 6px', borderRadius: 3, background: 'var(--bg2)', color: advColor(adv.advisory_flag), border: `1px solid ${advColor(adv.advisory_flag)}33` }}>
                  {adv.advisory_flag === 'caution' ? '⚠ ' : ''}setup ~{adv.prior_score != null ? Number(adv.prior_score).toFixed(0) : '—'}
                </span> : <span />}
              </div>
            )})}
          </div>
          <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 8 }}>Source: /api/v2/incubator + /api/v2/setup-advisory/candidates (setup-quality prior, advisory-only). Showing first 30 of {incubator.total}.</div>
        </div>
      )}

      {tab === 'Backtest' && <BacktestPanel onDrill={onDrill} />}
    </div>
  )
}
