import { useState } from 'react'
import { useApi } from '../hooks/useApi'
import { fmt$ } from '../lib/format'
import { BarChart, Bar, XAxis, YAxis, ReferenceLine, ResponsiveContainer, LineChart, Line, Tooltip, Legend, Cell } from 'recharts'
import type { DrillContext } from '../components/DetailDrawer'
import BacktestPanel from '../components/BacktestPanel'
import StrategyPlanner from '../components/StrategyPlanner'

interface Props { onDrill: (ctx: DrillContext) => void }

const TABS = ['Leaderboard', 'Analytics', 'Planner', 'Desk', 'Incubator', 'Plan vs Perf', 'Backtest'] as const

export default function StrategyHub({ onDrill }: Props) {
  const [tab, setTab] = useState<typeof TABS[number]>('Leaderboard')
  const { data: leaderboard } = useApi<any>('/api/v2/strategy-leaderboard', 60_000)
  const { data: intel } = useApi<any>('/api/v2/strategy-intelligence', 120_000)
  const { data: configs } = useApi<any>('/api/v2/strategy-configs', 120_000)
  const { data: desk } = useApi<any>('/api/v2/strategy-desk', 120_000)
  const { data: readiness } = useApi<any>('/api/v2/paper-trade-readiness', 120_000)
  const { data: btResults } = useApi<any>('/api/v2/backtesting/results', 120_000)
  const { data: pvp } = useApi<any>('/api/v2/plan-vs-performance', 120_000)
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
  const paperWrMap: Record<string, any> = {}
  for (const s of topStrats) {
    if (s.closed > 0) {
      paperWrMap[s.strategy] = { win_rate: s.win_rate, closed: s.closed, pnl: s.net_pnl, rr: s.rr ?? null,
        avg_r: s.avg_r ?? null, expectancy: s.expectancy ?? null, no_losses: s.no_losses ?? false,
        wins: s.wins ?? 0, losses: s.losses ?? 0 }
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
        rr: paper?.rr ?? null,
        avg_r: paper?.avg_r ?? s.avg_r ?? null,
        expectancy: paper?.expectancy ?? null,
        no_losses: paper?.no_losses ?? false,
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

      {tab === 'Leaderboard' && <StrategyLeaderboard data={leaderboard} onDrill={onDrill} onTab={setTab} />}
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
            <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr 1fr 1fr 1fr 1fr 1.3fr', gap: 0, fontSize: 9, color: 'var(--text3)', padding: '4px 8px', borderBottom: '1px solid var(--border)' }}>
              <span>Strategy</span><span>Win Rate</span><span>Profit Factor</span><span>R:R</span><span>Expectancy</span><span>Trades</span><span>Status</span>
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
                  display: 'grid', gridTemplateColumns: '2fr 1fr 1fr 1fr 1fr 1fr 1.3fr', gap: 0,
                  padding: '8px 8px', borderBottom: '1px solid var(--border)', cursor: 'pointer',
                  opacity: s.closed === 0 ? 0.4 : 1,
                }}
              >
                <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--text0)', fontFamily: 'monospace' }}>{s.strategy_id}</span>
                <span style={{ fontSize: 11, color: s.win_rate != null ? ((s.win_rate ?? 0) >= 55 ? '#22c55e' : (s.win_rate ?? 0) >= 45 ? '#f59e0b' : '#ef4444') : 'var(--text3)' }}>
                  {s.win_rate != null ? `${s.win_rate}%` : '—'}
                </span>
                <span style={{ fontSize: 11, color: 'var(--text2)' }} title={s.no_losses ? 'no losing trades → undefined (∞)' : ''}>{s.profit_factor != null && s.profit_factor > 0 ? s.profit_factor.toFixed(2) : (s.no_losses ? '∞' : '—')}</span>
                <span style={{ fontSize: 11, color: s.rr != null ? (s.rr >= 2 ? '#22c55e' : s.rr >= 1 ? '#f59e0b' : '#ef4444') : (s.no_losses ? '#22c55e' : 'var(--text3)') }} title={s.no_losses ? 'no losing trades → R:R undefined (∞)' : 'realized payoff R:R = avg win / avg loss'}>{s.rr != null ? `${s.rr.toFixed(2)}:1` : (s.no_losses ? '∞' : '—')}</span>
                <span style={{ fontSize: 11, color: s.expectancy != null ? (s.expectancy > 0 ? '#22c55e' : '#ef4444') : 'var(--text3)' }} title="per-trade $ expectancy = net P&L / closed trades">{s.expectancy != null ? `${s.expectancy > 0 ? '+' : ''}$${s.expectancy.toFixed(0)}` : '—'}</span>
                <span style={{ fontSize: 11, color: s.closed === 0 ? 'var(--text3)' : 'var(--text0)' }}>{s.closed || 'no trades'}{s.closed > 0 && s.closed < 10 ? ' ⚠' : ''}</span>
                {(() => {
                  // display-only status (real governance_state untouched): reward profitable low-WR strategies
                  const profitable = (s.expectancy ?? 0) > 0 && ((s.rr ?? 0) >= 2 || (s.profit_factor ?? 0) >= 1.5 || s.no_losses)
                  const thin = s.closed > 0 && s.closed < 10
                  let label = 'no data', color = 'var(--text3)'
                  if (s.closed > 0) {
                    if (s.eligible) { label = 'eligible'; color = '#22c55e' }
                    else if (profitable) { label = `profitable · low WR${thin ? ' (thin)' : ''}`; color = '#14b8a6' }
                    else { label = 'below gate'; color = '#f59e0b' }
                  }
                  return <span style={{ fontSize: 10, fontWeight: 600, color }} title={profitable && !s.eligible ? 'win-rate below 55% gate but positive expectancy / strong R:R — display only; governance gate unchanged' : ''}>{label}</span>
                })()}
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

      {tab === 'Plan vs Perf' && (() => {
        const p = pvp?.data ?? pvp ?? {}
        const sm = p.summary ?? {}
        const snaps = p.strategy_snapshots ?? []
        const rg = p.regime_now ?? {}
        const adh = sm.plan_adherence_rate
        return (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5,1fr)', gap: 10 }}>
              {[
                { k: 'Plan adherence', v: adh != null ? `${(adh <= 1 ? adh * 100 : adh).toFixed(0)}%` : '—', c: '#60a5fa' },
                { k: 'Win rate', v: sm.win_rate != null ? `${(sm.win_rate <= 1 ? sm.win_rate * 100 : sm.win_rate).toFixed(0)}%` : '—', c: '#22c55e' },
                { k: 'Total P&L', v: fmt$(sm.total_pnl ?? 0, 0), c: (sm.total_pnl ?? 0) >= 0 ? '#22c55e' : '#ef4444' },
                { k: 'Closed', v: sm.closed_trades ?? '—', c: 'var(--text0)' },
                { k: 'Regime', v: rg.regime_label ?? '—', c: '#a855f7' },
              ].map(s => (
                <div key={s.k} style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 8, padding: '10px 6px', textAlign: 'center' }}>
                  <div style={{ fontSize: 15, fontWeight: 700, color: s.c }}>{s.v}</div>
                  <div style={{ fontSize: 8, color: 'var(--text3)', textTransform: 'uppercase' }}>{s.k}</div>
                </div>
              ))}
            </div>
            <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14, maxHeight: 420, overflowY: 'auto' }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Strategy performance snapshots ({snaps.length})</div>
              <div style={{ display: 'grid', gridTemplateColumns: '1.6fr 0.6fr 0.7fr 0.6fr 0.8fr 1fr', fontSize: 8, color: 'var(--text3)', padding: '3px 6px', borderBottom: '1px solid var(--border)', textTransform: 'uppercase' }}>
                <span>Strategy</span><span>Trades</span><span>Win%</span><span>Avg R</span><span>P&L</span><span>Assessment</span>
              </div>
              {snaps.map((s: any, i: number) => (
                <div key={i} onClick={() => onDrill({ title: s.strategy_id, subtitle: s.assessment ?? '', endpoint: '/api/v2/plan-vs-performance', rows: [s] })}
                  style={{ display: 'grid', gridTemplateColumns: '1.6fr 0.6fr 0.7fr 0.6fr 0.8fr 1fr', padding: '4px 6px', borderBottom: '1px solid var(--border)', cursor: 'pointer', fontSize: 10, alignItems: 'center' }}>
                  <span style={{ color: 'var(--text1)', fontWeight: 600 }}>{(s.strategy_id ?? '').replace(/_/g, ' ')}</span>
                  <span style={{ color: 'var(--text3)' }}>{s.trades_closed ?? 0}</span>
                  <span style={{ color: (s.win_rate ?? 0) >= 50 ? '#22c55e' : '#f59e0b' }}>{s.win_rate != null ? `${Math.round(s.win_rate <= 1 ? s.win_rate * 100 : s.win_rate)}` : '—'}</span>
                  <span style={{ color: (s.avg_r ?? 0) >= 0 ? '#22c55e' : '#ef4444' }}>{s.avg_r != null ? Number(s.avg_r).toFixed(2) : '—'}</span>
                  <span style={{ color: (s.total_pnl ?? 0) >= 0 ? '#22c55e' : '#ef4444' }}>{fmt$(s.total_pnl ?? 0, 0)}</span>
                  <span style={{ color: 'var(--text3)', fontSize: 8, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{s.assessment ?? ''}</span>
                </div>
              ))}
              <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 8 }}>Source: /api/v2/plan-vs-performance — planned vs actual execution, strategy snapshots, regime fit.</div>
            </div>
          </div>
        )
      })()}

      {tab === 'Planner' && <StrategyPlanner />}
      {tab === 'Backtest' && <BacktestPanel onDrill={onDrill} />}
    </div>
  )
}

// Live strategy leaderboard (operator 2026-06-19) — ranked by LIVE expectancy (avg R), with backtest +
// assessment as context. Chart + table. LOW confidence (<8 live trades) flagged as directional only.
function StrategyLeaderboard({ data, onDrill, onTab }: any) {
  const rows: any[] = data?.leaderboard ?? []
  const note: string = data?.note ?? ''
  const CONF: Record<string, string> = { high: '#22c55e', medium: '#f59e0b', low: '#94a3b8' }
  const chart = rows.map(r => ({ name: r.strategy_id.replace(/_/g, ' ').slice(0, 14), R: r.live?.avg_r ?? 0 }))
  const th = { fontSize: 9.5, color: 'var(--text3)', textTransform: 'uppercase' as const, fontWeight: 800, textAlign: 'right' as const, padding: '5px 8px' }
  const td = { fontSize: 12, padding: '6px 8px', textAlign: 'right' as const, color: 'var(--text1)' }
  const drillRow = (r: any) => onDrill?.({
    title: r.strategy_id, subtitle: `rank #${r.rank} · ${r.confidence} confidence · tilt ${r.tilt ?? '—'}×`,
    endpoint: '/api/v2/strategy-leaderboard',
    rows: [{ strategy_id: r.strategy_id, rank: r.rank, live_avg_r: r.live?.avg_r, live_win_rate: r.live?.win_rate,
      live_trades: `${r.live?.wins ?? 0}/${r.live?.n ?? 0}`, total_pnl: r.live?.total_pnl, confidence: r.confidence,
      tilt: r.tilt, backtest: r.backtest ? `${r.backtest.sample} · ${r.backtest.expectancy_r}R` : '—',
      assessment: r.snapshot?.recommendation || r.snapshot?.assessment || '—' }],
  })
  const actBtn: React.CSSProperties = { fontSize: 9.5, fontWeight: 700, padding: '3px 8px', borderRadius: 5, border: '1px solid var(--border)', background: 'var(--bg2)', color: '#60a5fa', cursor: 'pointer', whiteSpace: 'nowrap' }
  return <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
    <div style={{ fontSize: 10.5, color: 'var(--text3)' }}>{note}</div>
    {rows.length > 0 && <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14 }}>
      <div style={{ fontSize: 12, fontWeight: 800, color: 'var(--text0)', marginBottom: 8 }}>Live expectancy per trade (R)</div>
      <ResponsiveContainer width="100%" height={200}>
        <BarChart data={chart} margin={{ top: 4, right: 10, bottom: 4, left: 0 }}>
          <XAxis dataKey="name" tick={{ fontSize: 9, fill: '#94a3b8' }} interval={0} angle={-18} textAnchor="end" height={48} />
          <YAxis tick={{ fontSize: 10, fill: '#94a3b8' }} />
          <ReferenceLine y={0} stroke="#475569" />
          <Tooltip contentStyle={{ background: '#0f172a', border: '1px solid #334155', fontSize: 11 }} />
          <Bar dataKey="R">{chart.map((c, i) => <Cell key={i} fill={c.R >= 0 ? '#22c55e' : '#ef4444'} />)}</Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>}
    <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 4, overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead><tr>
          <th style={{ ...th, textAlign: 'left' }}>#  Strategy</th>
          <th style={th}>Live R</th><th style={th}>Win%</th><th style={th}>Trades</th><th style={th}>Total P&L</th>
          <th style={th}>Conf</th><th style={th}>Tilt</th><th style={th}>Backtest (n · expR)</th><th style={{ ...th, textAlign: 'left' }}>Assessment</th><th style={{ ...th, textAlign: 'left' }}>Actions</th>
        </tr></thead>
        <tbody>
          {rows.map(r => {
            const lv = r.live ?? {}, bt = r.backtest, sn = r.snapshot
            const rc = (lv.avg_r ?? 0) >= 0 ? '#22c55e' : '#ef4444'
            return <tr key={r.strategy_id} onClick={() => drillRow(r)} title="open strategy detail" style={{ borderTop: '1px solid var(--border)', cursor: 'pointer' }}>
              <td style={{ ...td, textAlign: 'left', fontWeight: 700, color: 'var(--text0)' }}>
                <span style={{ color: r.rank <= 2 ? '#fbbf24' : 'var(--text3)', marginRight: 7 }}>{r.rank <= 2 ? '★' : r.rank}</span>{r.strategy_id}
              </td>
              <td style={{ ...td, color: rc, fontWeight: 800 }}>{lv.avg_r ?? '—'}</td>
              <td style={td}>{lv.win_rate ?? '—'}%</td>
              <td style={td}>{lv.wins ?? 0}/{lv.n ?? 0}</td>
              <td style={{ ...td, color: (lv.total_pnl ?? 0) >= 0 ? '#22c55e' : '#ef4444' }}>{lv.total_pnl != null ? fmt$(lv.total_pnl) : '—'}</td>
              <td style={{ ...td, color: CONF[r.confidence] }}>{r.confidence}</td>
              <td style={{ ...td, fontWeight: 800, color: r.excluded ? 'var(--text3)' : (r.tilt > 1.02 ? '#22c55e' : r.tilt < 0.98 ? '#ef4444' : 'var(--text3)') }} title={r.excluded ? 'momentum_scalp — excluded from tilt (pinned 1.0)' : 'allocation tilt: boosts candidate ranking + risk budget'}>{r.tilt != null ? `${r.tilt}×` : '—'}{r.excluded ? ' 🔒' : ''}</td>
              <td style={td}>{bt ? <span title={bt.data_suspect ? 'backtest expectancy out of realistic range — data suspect, ignored in ranking' : ''}>{bt.sample ?? '—'} · {bt.expectancy_r ?? '—'}R {bt.data_suspect ? '⚠' : ''}</span> : '—'}</td>
              <td style={{ ...td, textAlign: 'left', fontSize: 10.5, color: 'var(--text3)' }}>{sn?.recommendation || sn?.assessment || '—'}</td>
              <td style={{ ...td, textAlign: 'left' }} onClick={e => e.stopPropagation()}>
                <span style={{ display: 'flex', gap: 5 }}>
                  <button style={actBtn} onClick={() => onTab?.('Backtest')} title={`Open the Backtest tab for ${r.strategy_id}`}>Backtest →</button>
                  <button style={actBtn} onClick={() => onTab?.('Plan vs Perf')} title="Open Plan vs Performance">Plan →</button>
                </span>
              </td>
            </tr>
          })}
          {rows.length === 0 && <tr><td colSpan={10} style={{ ...td, textAlign: 'center', color: 'var(--text3)', padding: 20 }}>No closed trades yet.</td></tr>}
        </tbody>
      </table>
    </div>
  </div>
}
