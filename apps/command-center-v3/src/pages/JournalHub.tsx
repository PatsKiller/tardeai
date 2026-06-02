import { useState, useMemo } from 'react'
import { useApi } from '../hooks/useApi'
import { fmt$ } from '../lib/format'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, AreaChart, Area } from 'recharts'
import type { DrillContext } from '../components/DetailDrawer'
import ProtectionOutcomesPanel from '../components/ProtectionOutcomesPanel'

interface Props { onDrill: (ctx: DrillContext) => void }
const TABS = ['Trades', 'Analytics', 'Lessons', 'Protection'] as const

export default function JournalHub({ onDrill }: Props) {
  const [tab, setTab] = useState<typeof TABS[number]>('Trades')
  const { data: journal } = useApi<any>('/api/v2/automated-trade-journal', 60_000)
  const { data: analytics } = useApi<any>('/api/v2/automated-journal-analytics', 120_000)
  const { data: readiness } = useApi<any>('/api/v2/paper-trade-readiness', 120_000)
  const { data: lessonsData } = useApi<any>('/api/v2/journal/closed-trades/lessons', 120_000)

  const trades = journal?.trades ?? []
  const openTrades = trades.filter((t: any) => t.status === 'open')
  const closedTrades = trades.filter((t: any) => t.status === 'closed')
  const summary = journal?.summary ?? {}
  const warnings = journal?.integrity_warnings ?? []
  const jc = readiness?.journal_completeness ?? {}
  const overall = analytics?.overall ?? {}
  const byStrategy = analytics?.by_strategy ?? summary?.by_strategy ?? []

  // ── Derived: equity curve (cumulative PnL from closed trades sorted by close date) ──
  const equityCurve = useMemo(() => {
    const sorted = [...closedTrades]
      .filter((t: any) => t.closed_at && t.pnl != null)
      .sort((a: any, b: any) => (a.closed_at ?? '').localeCompare(b.closed_at ?? ''))
    let cum = 0
    return sorted.map((t: any) => {
      cum += (t.pnl ?? 0)
      return { date: (t.closed_at ?? '').slice(5, 10), symbol: t.symbol, pnl: t.pnl, cumulative: Math.round(cum * 100) / 100 }
    })
  }, [closedTrades])

  // ── Derived: daily P&L (aggregate by close date) ──
  const dailyPnl = useMemo(() => {
    const byDate: Record<string, { pnl: number; trades: number; wins: number; losses: number }> = {}
    for (const t of closedTrades) {
      if (!t.closed_at) continue
      const d = (t.closed_at ?? '').slice(0, 10)
      if (!byDate[d]) byDate[d] = { pnl: 0, trades: 0, wins: 0, losses: 0 }
      byDate[d].pnl += (t.pnl ?? 0)
      byDate[d].trades += 1
      if ((t.pnl ?? 0) > 0) byDate[d].wins += 1
      else if ((t.pnl ?? 0) < 0) byDate[d].losses += 1
    }
    return Object.entries(byDate)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([date, v]) => ({ date: date.slice(5), fullDate: date, ...v, pnl: Math.round(v.pnl * 100) / 100 }))
  }, [closedTrades])

  // ── Derived: calendar grid (sparse — only real trading days) ──
  const calendarData = useMemo(() => {
    const byDate: Record<string, { pnl: number; trades: number; wins: number; losses: number }> = {}
    for (const t of closedTrades) {
      if (!t.closed_at) continue
      const d = (t.closed_at ?? '').slice(0, 10)
      if (!byDate[d]) byDate[d] = { pnl: 0, trades: 0, wins: 0, losses: 0 }
      byDate[d].pnl += (t.pnl ?? 0)
      byDate[d].trades += 1
      if ((t.pnl ?? 0) > 0) byDate[d].wins += 1
      else if ((t.pnl ?? 0) < 0) byDate[d].losses += 1
    }
    // Group by month
    const months: Record<string, Record<number, typeof byDate[string]>> = {}
    for (const [date, data] of Object.entries(byDate)) {
      const [y, m, dStr] = date.split('-')
      const monthKey = `${y}-${m}`
      if (!months[monthKey]) months[monthKey] = {}
      months[monthKey][parseInt(dStr)] = data
    }
    return months
  }, [closedTrades])

  // ── Derived: monthly summary ──
  const monthlySummary = useMemo(() => {
    const byMonth: Record<string, { pnl: number; trades: number; wins: number; losses: number }> = {}
    for (const t of closedTrades) {
      if (!t.closed_at) continue
      const m = (t.closed_at ?? '').slice(0, 7)
      if (!byMonth[m]) byMonth[m] = { pnl: 0, trades: 0, wins: 0, losses: 0 }
      byMonth[m].pnl += (t.pnl ?? 0)
      byMonth[m].trades += 1
      if ((t.pnl ?? 0) > 0) byMonth[m].wins += 1
      else if ((t.pnl ?? 0) < 0) byMonth[m].losses += 1
    }
    return Object.entries(byMonth).sort(([a], [b]) => a.localeCompare(b)).map(([month, v]) => ({
      month, ...v, pnl: Math.round(v.pnl * 100) / 100,
      wr: v.trades > 0 ? Math.round(v.wins / v.trades * 100) : 0,
    }))
  }, [closedTrades])

  const maxAbsDailyPnl = Math.max(1, ...dailyPnl.map(d => Math.abs(d.pnl)))

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 16 }}>
        <div>
          <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--text0)' }}>Journal</div>
          <div style={{ fontSize: 11, color: 'var(--text3)' }}>{trades.length} trades · {openTrades.length} open · {closedTrades.length} closed</div>
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

      {/* Integrity warnings */}
      {warnings.length > 0 && (
        <div style={{ marginBottom: 12, padding: '8px 12px', background: 'rgba(245,158,11,.06)', border: '1px solid rgba(245,158,11,.15)', borderRadius: 8 }}>
          <div style={{ fontSize: 10, fontWeight: 700, color: '#f59e0b', marginBottom: 4 }}>Integrity Warnings ({warnings.length})</div>
          {warnings.slice(0, 5).map((w: any, i: number) => (
            <div key={i} style={{ fontSize: 9, color: '#fbbf24', padding: '1px 0' }}>{typeof w === 'string' ? w : JSON.stringify(w)}</div>
          ))}
        </div>
      )}

      {tab === 'Trades' && (
        <>
          {/* ── KPI Tiles ── */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(7, 1fr)', gap: 8, marginBottom: 14 }}>
            {[
              { label: 'Open', value: summary.open_count ?? openTrades.length, color: '#60a5fa' },
              { label: 'Closed', value: summary.closed_count ?? closedTrades.length, color: 'var(--text0)' },
              { label: 'Wins', value: summary.wins ?? 0, color: '#22c55e' },
              { label: 'Losses', value: summary.losses ?? 0, color: '#ef4444' },
              { label: 'Win Rate', value: summary.win_rate != null ? `${summary.win_rate}%` : '—', color: (summary.win_rate ?? 0) >= 55 ? '#22c55e' : '#f59e0b' },
              { label: 'Profit Factor', value: overall.profit_factor?.toFixed(2) ?? '—', color: 'var(--text0)' },
              { label: 'Avg R', value: summary.avg_r?.toFixed(2) ?? overall.avg_r?.toFixed(2) ?? '—', color: 'var(--text0)' },
            ].map(k => (
              <div key={k.label} style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 8, padding: '8px 10px', textAlign: 'center' }}>
                <div style={{ fontSize: 18, fontWeight: 700, color: k.color, fontFamily: 'monospace' }}>{k.value}</div>
                <div style={{ fontSize: 9, color: 'var(--text3)' }}>{k.label}</div>
              </div>
            ))}
          </div>

          {/* ── Equity Curve + Daily P&L ── */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14, marginBottom: 14 }}>
            {/* Equity curve */}
            <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)' }}>Equity Curve</span>
                <span style={{ fontSize: 9, color: 'var(--text3)' }}>cumulative realized P&L</span>
              </div>
              {equityCurve.length < 2 ? (
                <div style={{ color: 'var(--text3)', fontSize: 11, padding: 20, textAlign: 'center' }}>Insufficient closed trades for curve ({equityCurve.length})</div>
              ) : (
                <ResponsiveContainer width="100%" height={160}>
                  <AreaChart data={equityCurve}>
                    <defs><linearGradient id="jEqGrad" x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor="#22c55e" stopOpacity={0.3}/><stop offset="95%" stopColor="#22c55e" stopOpacity={0}/></linearGradient></defs>
                    <XAxis dataKey="date" tick={{ fontSize: 8, fill: 'var(--text3)' }} />
                    <YAxis tick={{ fontSize: 8, fill: 'var(--text3)' }} tickFormatter={(v: number) => `$${v}`} />
                    <Tooltip contentStyle={{ background: 'var(--bg1)', border: '1px solid var(--border)', fontSize: 10 }}
                      formatter={(v: number, name: string) => [fmt$(v, 2), name === 'cumulative' ? 'Cumulative' : 'Trade']} />
                    <Area type="monotone" dataKey="cumulative" stroke="#22c55e" fill="url(#jEqGrad)" strokeWidth={2} />
                  </AreaChart>
                </ResponsiveContainer>
              )}
              <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 4 }}>Derived from {closedTrades.length} closed trades</div>
            </div>

            {/* Daily P&L bars */}
            <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)' }}>Daily P&L</span>
                <span style={{ fontSize: 9, color: 'var(--text3)' }}>{dailyPnl.length} trading days</span>
              </div>
              {dailyPnl.length === 0 ? (
                <div style={{ color: 'var(--text3)', fontSize: 11, padding: 20, textAlign: 'center' }}>No closed trades with dates</div>
              ) : (
                <ResponsiveContainer width="100%" height={160}>
                  <BarChart data={dailyPnl}>
                    <XAxis dataKey="date" tick={{ fontSize: 8, fill: 'var(--text3)' }} />
                    <YAxis tick={{ fontSize: 8, fill: 'var(--text3)' }} tickFormatter={(v: number) => `$${v}`} />
                    <Tooltip contentStyle={{ background: 'var(--bg1)', border: '1px solid var(--border)', fontSize: 10 }}
                      formatter={(v: number) => [fmt$(v, 2), 'P&L']} />
                    <Bar dataKey="pnl" radius={[3, 3, 0, 0]}
                      fill="#22c55e"
                      shape={(props: any) => {
                        const { x, y, width, height, payload } = props
                        const fill = payload.pnl >= 0 ? '#22c55e' : '#ef4444'
                        return <rect x={x} y={y} width={width} height={Math.abs(height)} rx={3} fill={fill} />
                      }}
                    />
                  </BarChart>
                </ResponsiveContainer>
              )}
            </div>
          </div>

          {/* ── P&L Calendar Heatmap ── */}
          <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14, marginBottom: 14 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 10 }}>
              <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)' }}>Calendar P&L</span>
              <span style={{ fontSize: 9, color: 'var(--text3)' }}>Sparse: {Object.keys(calendarData).length === 0 ? 'no data' : `${dailyPnl.length} trading days across ${Object.keys(calendarData).length} months`}</span>
            </div>
            {Object.keys(calendarData).length === 0 ? (
              <div style={{ color: 'var(--text3)', fontSize: 11, padding: 10, textAlign: 'center' }}>No closed trades with dates for calendar</div>
            ) : (
              Object.entries(calendarData).sort(([a], [b]) => a.localeCompare(b)).map(([monthKey, days]) => {
                const [y, m] = monthKey.split('-')
                const daysInMonth = new Date(parseInt(y), parseInt(m), 0).getDate()
                const monthName = new Date(parseInt(y), parseInt(m) - 1).toLocaleDateString('en-US', { month: 'long', year: 'numeric' })
                return (
                  <div key={monthKey} style={{ marginBottom: 10 }}>
                    <div style={{ fontSize: 10, fontWeight: 600, color: 'var(--text2)', marginBottom: 4 }}>{monthName}</div>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(31, 1fr)', gap: 2 }}>
                      {Array.from({ length: daysInMonth }, (_, i) => i + 1).map(day => {
                        const d = days[day]
                        if (!d) return <div key={day} style={{ height: 20, borderRadius: 2, background: 'var(--bg2)', opacity: 0.3 }} title={`Day ${day}: no trades`} />
                        const intensity = Math.min(1, Math.abs(d.pnl) / maxAbsDailyPnl)
                        const alpha = 0.3 + intensity * 0.7
                        const bg = d.pnl > 0 ? `rgba(34,197,94,${alpha})` : d.pnl < 0 ? `rgba(239,68,68,${alpha})` : 'rgba(148,163,184,0.3)'
                        return (
                          <div key={day}
                            onClick={() => onDrill({
                              title: `${monthKey}-${String(day).padStart(2, '0')}`,
                              subtitle: `${fmt$(d.pnl, 2)} · ${d.trades} trades · ${d.wins}W ${d.losses}L`,
                              endpoint: '/api/v2/automated-trade-journal',
                              rows: closedTrades.filter((t: any) => t.closed_at?.startsWith(`${monthKey}-${String(day).padStart(2, '0')}`)),
                            })}
                            style={{ height: 20, borderRadius: 2, background: bg, cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center' }}
                            title={`${monthKey}-${String(day).padStart(2, '0')}: ${fmt$(d.pnl, 2)} (${d.trades} trades, ${d.wins}W ${d.losses}L)`}
                          >
                            <span style={{ fontSize: 7, color: 'rgba(255,255,255,0.8)' }}>{day}</span>
                          </div>
                        )
                      })}
                    </div>
                  </div>
                )
              })
            )}
            <div style={{ display: 'flex', gap: 12, fontSize: 9, marginTop: 6, color: 'var(--text3)' }}>
              <span><span style={{ display: 'inline-block', width: 10, height: 10, borderRadius: 2, background: '#22c55e', marginRight: 3 }}/>profit</span>
              <span><span style={{ display: 'inline-block', width: 10, height: 10, borderRadius: 2, background: '#ef4444', marginRight: 3 }}/>loss</span>
              <span><span style={{ display: 'inline-block', width: 10, height: 10, borderRadius: 2, background: 'var(--bg2)', opacity: 0.3, marginRight: 3 }}/>no trades</span>
            </div>
          </div>

          {/* ── Monthly Summary ── */}
          {monthlySummary.length > 0 && (
            <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14, marginBottom: 14 }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Monthly Summary</div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr 1fr 1fr', fontSize: 9, color: 'var(--text3)', padding: '4px 6px', borderBottom: '1px solid var(--border)' }}>
                <span>Month</span><span>Trades</span><span>Wins</span><span>Losses</span><span>Win Rate</span><span>P&L</span>
              </div>
              {monthlySummary.map(m => (
                <div key={m.month} onClick={() => onDrill({ title: m.month, subtitle: `${m.trades} trades, ${fmt$(m.pnl, 2)}`, endpoint: '/api/v2/automated-trade-journal', rows: closedTrades.filter((t: any) => t.closed_at?.startsWith(m.month)) })}
                  style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr 1fr 1fr', padding: '6px 6px', borderBottom: '1px solid var(--border)', cursor: 'pointer', fontSize: 11 }}>
                  <span style={{ color: 'var(--text0)', fontFamily: 'monospace' }}>{m.month}</span>
                  <span style={{ color: 'var(--text2)' }}>{m.trades}</span>
                  <span style={{ color: '#22c55e' }}>{m.wins}</span>
                  <span style={{ color: '#ef4444' }}>{m.losses}</span>
                  <span style={{ color: m.wr >= 55 ? '#22c55e' : m.wr >= 45 ? '#f59e0b' : '#ef4444' }}>{m.wr}%</span>
                  <span style={{ color: m.pnl >= 0 ? '#22c55e' : '#ef4444', fontWeight: 600 }}>{fmt$(m.pnl, 2)}</span>
                </div>
              ))}
            </div>
          )}

          {/* ── Strategy Breakdown ── */}
          {byStrategy.length > 0 && (
            <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14, marginBottom: 14 }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Strategy Breakdown</div>
              <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr 1fr 1fr 1fr', fontSize: 9, color: 'var(--text3)', padding: '4px 6px', borderBottom: '1px solid var(--border)' }}>
                <span>Strategy</span><span>Trades</span><span>Wins</span><span>Win Rate</span><span>P&L</span>
              </div>
              {byStrategy.filter((s: any) => (s.trades ?? s.count ?? 0) > 0).sort((a: any, b: any) => (b.trades ?? b.count ?? 0) - (a.trades ?? a.count ?? 0)).map((s: any) => {
                const trades_count = s.trades ?? s.count ?? 0
                const wr = s.win_rate ?? (trades_count > 0 ? Math.round((s.wins ?? 0) / trades_count * 100) : 0)
                return (
                  <div key={s.strategy_id ?? s.strategy} onClick={() => onDrill({ title: s.strategy_id ?? s.strategy, subtitle: `${trades_count} trades`, endpoint: '/api/v2/automated-journal-analytics', rows: [s] })}
                    style={{ display: 'grid', gridTemplateColumns: '2fr 1fr 1fr 1fr 1fr', padding: '6px 6px', borderBottom: '1px solid var(--border)', cursor: 'pointer', fontSize: 11 }}>
                    <span style={{ color: 'var(--text0)', fontFamily: 'monospace' }}>{s.strategy_id ?? s.strategy}</span>
                    <span style={{ color: 'var(--text2)' }}>{trades_count}</span>
                    <span style={{ color: '#22c55e' }}>{s.wins ?? 0}</span>
                    <span style={{ color: wr >= 55 ? '#22c55e' : wr >= 45 ? '#f59e0b' : '#ef4444' }}>{wr}%</span>
                    <span style={{ color: (s.pnl ?? 0) >= 0 ? '#22c55e' : '#ef4444', fontWeight: 600 }}>{fmt$(s.pnl ?? 0, 2)}</span>
                  </div>
                )
              })}
            </div>
          )}

          {/* ── Trade List ── */}
          <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14, maxHeight: 400, overflowY: 'auto' }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Trade Log ({trades.length})</div>
            <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 1fr 1fr 1.2fr 0.8fr', fontSize: 9, color: 'var(--text3)', padding: '4px 6px', borderBottom: '1px solid var(--border)' }}>
              <span>Symbol</span><span>Entry</span><span>P&L</span><span>Exit Reason</span><span>Hold</span>
            </div>
            {trades.map((t: any) => (
              <div key={t.id} onClick={() => onDrill({ title: `${t.symbol} #${t.id}`, subtitle: `${t.strategy_id} · ${t.status}`, endpoint: '/api/v2/automated-trade-journal', rows: [t] })}
                style={{ display: 'grid', gridTemplateColumns: '1.2fr 1fr 1fr 1.2fr 0.8fr', padding: '6px 6px', borderBottom: '1px solid var(--border)', cursor: 'pointer', fontSize: 11 }}>
                <div>
                  <div style={{ fontWeight: 700, color: 'var(--text0)', fontFamily: 'monospace' }}>{t.symbol}</div>
                  <div style={{ fontSize: 8, color: 'var(--text3)' }}>{t.strategy_id}</div>
                </div>
                <span style={{ color: 'var(--text2)' }}>{t.shares} @ {fmt$(t.entry_price, 2)}</span>
                <span style={{ color: t.status === 'open' ? '#60a5fa' : (t.pnl ?? 0) >= 0 ? '#22c55e' : '#ef4444', fontWeight: 600 }}>
                  {t.status === 'open' ? 'OPEN' : fmt$(t.pnl, 2)}
                </span>
                <span style={{ color: 'var(--text2)', fontSize: 10 }}>{t.exit_reason ?? '—'}</span>
                <span style={{ color: 'var(--text3)', fontSize: 9 }}>{t.hold_time_min ? (t.hold_time_min < 60 ? `${Math.round(t.hold_time_min)}m` : `${Math.round(t.hold_time_min / 60)}h`) : '—'}</span>
              </div>
            ))}
          </div>
          <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 6 }}>
            Source: /api/v2/automated-trade-journal (all {closedTrades.length} closed) + /automated-journal-analytics (KPIs).
            Win rate shown is journal's {summary.win_rate ?? '—'}% on {summary.real_trade_count ?? closedTrades.length} real trades.
            Gate figure is 45.8% on all 24 including phantoms — see gate for canonical number.
          </div>
        </>
      )}

      {tab === 'Analytics' && (
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 10 }}>Journal Field Completeness</div>
          {Object.keys(jc).length === 0 ? <div style={{ color: 'var(--text3)', fontSize: 11 }}>No completeness data — run paper_trade_statistics.py</div> :
          Object.entries(jc).sort(([, a]: [string, any], [, b]: [string, any]) => b - a).map(([field, pct]: [string, any]) => (
            <div key={field} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 3 }}>
              <span style={{ width: 120, fontSize: 10, color: 'var(--text2)' }}>{field}</span>
              <div style={{ flex: 1, height: 12, background: 'var(--bg2)', borderRadius: 3, overflow: 'hidden' }}>
                <div style={{ width: `${pct}%`, height: '100%', background: pct >= 95 ? '#22c55e' : pct >= 80 ? '#f59e0b' : '#ef4444', borderRadius: 3 }} />
              </div>
              <span style={{ fontSize: 10, color: pct >= 95 ? '#22c55e' : pct >= 80 ? '#f59e0b' : '#ef4444', width: 40, textAlign: 'right' }}>{pct}%</span>
            </div>
          ))}
          <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 8 }}>Source: /api/v2/paper-trade-readiness → journal_completeness</div>
        </div>
      )}

      {tab === 'Lessons' && lessonsData && (
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 10 }}>Trade Lessons ({lessonsData.count ?? 0})</div>
          {(lessonsData.lessons ?? []).length === 0 ? <div style={{ color: 'var(--text3)', fontSize: 11 }}>No lessons recorded yet</div> :
          (lessonsData.lessons ?? []).slice(0, 15).map((l: any, i: number) => (
            <div key={i} onClick={() => onDrill({ title: l.lesson_category ?? `Lesson ${i}`, subtitle: l.strategy_id ?? '', endpoint: '/api/v2/journal/closed-trades/lessons', rows: [l] })}
              style={{ padding: '8px 6px', borderBottom: '1px solid var(--border)', cursor: 'pointer' }}>
              <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text0)' }}>{l.lesson_category ?? l.lesson_type ?? '—'}</div>
              <div style={{ fontSize: 10, color: 'var(--text2)', marginTop: 2 }}>{(l.lesson_text ?? l.summary ?? JSON.stringify(l)).slice(0, 120)}</div>
              <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 2 }}>{l.strategy_id ?? ''} · {l.symbol ?? ''}</div>
            </div>
          ))}
          <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 8 }}>Source: /api/v2/journal/closed-trades/lessons</div>
        </div>
      )}

      {tab === 'Protection' && <ProtectionOutcomesPanel onDrill={onDrill} />}
    </div>
  )
}
