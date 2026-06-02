import { useState, useMemo } from 'react'
import { useApi } from '../hooks/useApi'
import { fmt$ } from '../lib/format'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, AreaChart, Area } from 'recharts'
import type { DrillContext } from '../components/DetailDrawer'
import ProtectionOutcomesPanel from '../components/ProtectionOutcomesPanel'

interface Props { onDrill: (ctx: DrillContext) => void }
const TABS = ['Trades', 'Analytics', 'Lessons', 'Protection'] as const

// Account color map
const ACCT_COLOR: Record<string, string> = {
  schwab_rollover_ira: '#60a5fa',   // blue
  schwab_taxable: '#a855f7',        // purple
  schwab_roth_ira: '#06b6d4',       // cyan
  schwab_roth: '#06b6d4',           // cyan (alias)
  alpaca_paper: '#22c55e',          // green
  ALPACA_PAPER: '#22c55e',          // green (alias)
  TOS_PAPER: '#22c55e',             // green (legacy alias)
}
const acctColor = (a: string) => ACCT_COLOR[a] ?? ACCT_COLOR[a?.toLowerCase()] ?? 'var(--text2)'
const normalizeAcct = (a: string) => {
  const lower = (a ?? '').toLowerCase()
  if (lower.includes('alpaca') || lower.includes('tos')) return 'alpaca_paper'
  return lower
}
const ACCT_LABEL: Record<string, string> = {
  schwab_rollover_ira: 'Schwab Rollover IRA',
  schwab_taxable: 'Schwab Taxable',
  schwab_roth_ira: 'Schwab Roth IRA',
  schwab_roth: 'Schwab Roth IRA',
  alpaca_paper: 'Alpaca Paper',
}

interface UnifiedTrade {
  id: string | number; symbol: string; account: string; normalizedAccount: string
  entryPrice: number | null; exitPrice: number | null; shares: number
  pnl: number; pnlPct: number | null; holdDays: number | null; holdMin: number | null
  exitReason: string | null; strategyId: string | null; status: string
  entryDate: string | null; exitDate: string | null; source: 'paper' | 'schwab'
}

const DOW = ['S', 'M', 'T', 'W', 'T', 'F', 'S']

export default function JournalHub({ onDrill }: Props) {
  const [tab, setTab] = useState<typeof TABS[number]>('Trades')
  const [acctFilter, setAcctFilter] = useState<string>('')
  const { data: journal } = useApi<any>('/api/v2/automated-trade-journal', 60_000)
  const { data: schwabJournal } = useApi<any>('/api/v2/journal', 120_000)
  const { data: analytics } = useApi<any>('/api/v2/automated-journal-analytics', 120_000)
  const { data: readiness } = useApi<any>('/api/v2/paper-trade-readiness', 120_000)
  const { data: lessonsData } = useApi<any>('/api/v2/journal/closed-trades/lessons', 120_000)

  const warnings = journal?.integrity_warnings ?? []
  const jc = readiness?.journal_completeness ?? {}
  const overall = analytics?.overall ?? {}

  // ── Unify trades from both sources ──
  const allTrades: UnifiedTrade[] = useMemo(() => {
    const result: UnifiedTrade[] = []
    // Paper trades
    for (const t of (journal?.trades ?? [])) {
      result.push({
        id: t.id, symbol: t.symbol, account: t.account ?? 'alpaca_paper',
        normalizedAccount: normalizeAcct(t.account ?? 'alpaca_paper'),
        entryPrice: t.entry_price, exitPrice: t.exit_price, shares: t.shares ?? 0,
        pnl: t.pnl ?? 0, pnlPct: t.pnl_pct, holdDays: null,
        holdMin: t.hold_time_min, exitReason: t.exit_reason, strategyId: t.strategy_id,
        status: t.status ?? 'closed', entryDate: t.entry_time?.slice(0, 10) ?? t.created_at?.slice(0, 10),
        exitDate: t.closed_at?.slice(0, 10), source: 'paper',
      })
    }
    // Schwab trades
    for (const t of (schwabJournal?.trades ?? [])) {
      result.push({
        id: `sw-${t.trade_key ?? t.symbol}`, symbol: t.symbol, account: t.account,
        normalizedAccount: normalizeAcct(t.account),
        entryPrice: t.buy_price, exitPrice: t.sell_price, shares: t.shares ?? 0,
        pnl: t.pnl ?? 0, pnlPct: t.pnl_pct, holdDays: t.hold_days,
        holdMin: null, exitReason: null, strategyId: null,
        status: 'closed', entryDate: t.open_date, exitDate: t.close_date, source: 'schwab',
      })
    }
    return result.sort((a, b) => (b.exitDate ?? b.entryDate ?? '').localeCompare(a.exitDate ?? a.entryDate ?? ''))
  }, [journal, schwabJournal])

  // ── Filter by account ──
  const filtered = acctFilter ? allTrades.filter(t => t.normalizedAccount === acctFilter) : allTrades
  const closedFiltered = filtered.filter(t => t.status === 'closed')
  const openFiltered = filtered.filter(t => t.status === 'open')

  // ── Account chips ──
  const accountCounts = useMemo(() => {
    const m: Record<string, number> = {}
    for (const t of allTrades) { m[t.normalizedAccount] = (m[t.normalizedAccount] ?? 0) + 1 }
    return Object.entries(m).sort((a, b) => b[1] - a[1])
  }, [allTrades])

  // ── KPIs from filtered closed ──
  const kpis = useMemo(() => {
    const closed = closedFiltered
    const wins = closed.filter(t => t.pnl > 0).length
    const losses = closed.filter(t => t.pnl < 0).length
    const grossProfit = closed.filter(t => t.pnl > 0).reduce((s, t) => s + t.pnl, 0)
    const grossLoss = Math.abs(closed.filter(t => t.pnl < 0).reduce((s, t) => s + t.pnl, 0))
    return {
      open: openFiltered.length, closed: closed.length, wins, losses,
      wr: closed.length > 0 ? Math.round(wins / closed.length * 100 * 10) / 10 : 0,
      pf: grossLoss > 0 ? Math.round(grossProfit / grossLoss * 100) / 100 : 0,
      totalPnl: Math.round(closed.reduce((s, t) => s + t.pnl, 0) * 100) / 100,
    }
  }, [closedFiltered, openFiltered])

  // ── Equity curve ──
  const equityCurve = useMemo(() => {
    const sorted = [...closedFiltered].filter(t => t.exitDate).sort((a, b) => (a.exitDate ?? '').localeCompare(b.exitDate ?? ''))
    let cum = 0
    return sorted.map(t => { cum += t.pnl; return { date: (t.exitDate ?? '').slice(5), symbol: t.symbol, pnl: t.pnl, cumulative: Math.round(cum * 100) / 100, account: t.normalizedAccount } })
  }, [closedFiltered])

  // ── Daily P&L ──
  const dailyPnl = useMemo(() => {
    const byDate: Record<string, { pnl: number; trades: number; wins: number; losses: number }> = {}
    for (const t of closedFiltered) {
      if (!t.exitDate) continue
      if (!byDate[t.exitDate]) byDate[t.exitDate] = { pnl: 0, trades: 0, wins: 0, losses: 0 }
      byDate[t.exitDate].pnl += t.pnl
      byDate[t.exitDate].trades += 1
      if (t.pnl > 0) byDate[t.exitDate].wins += 1
      else if (t.pnl < 0) byDate[t.exitDate].losses += 1
    }
    return Object.entries(byDate).sort(([a], [b]) => a.localeCompare(b))
      .map(([date, v]) => ({ date: date.slice(5), fullDate: date, ...v, pnl: Math.round(v.pnl * 100) / 100 }))
  }, [closedFiltered])

  // ── Calendar ──
  const calendarMonths = useMemo(() => {
    const byDate: Record<string, { pnl: number; trades: number; wins: number; losses: number }> = {}
    for (const t of closedFiltered) {
      if (!t.exitDate) continue
      if (!byDate[t.exitDate]) byDate[t.exitDate] = { pnl: 0, trades: 0, wins: 0, losses: 0 }
      byDate[t.exitDate].pnl += t.pnl
      byDate[t.exitDate].trades += 1
      if (t.pnl > 0) byDate[t.exitDate].wins += 1
      else if (t.pnl < 0) byDate[t.exitDate].losses += 1
    }
    const months: Record<string, Record<number, typeof byDate[string]>> = {}
    for (const [date, data] of Object.entries(byDate)) {
      const mk = date.slice(0, 7)
      if (!months[mk]) months[mk] = {}
      months[mk][parseInt(date.slice(8))] = data
    }
    return { months, maxPnl: Math.max(1, ...Object.values(byDate).map(d => Math.abs(d.pnl))) }
  }, [closedFiltered])

  // ── Strategy breakdown ──
  const stratBreakdown = useMemo(() => {
    const m: Record<string, { trades: number; wins: number; pnl: number }> = {}
    for (const t of closedFiltered) {
      const s = t.strategyId ?? '(no strategy)'
      if (!m[s]) m[s] = { trades: 0, wins: 0, pnl: 0 }
      m[s].trades += 1
      if (t.pnl > 0) m[s].wins += 1
      m[s].pnl += t.pnl
    }
    return Object.entries(m).sort((a, b) => b[1].trades - a[1].trades)
      .map(([strat, v]) => ({ strategy: strat, ...v, wr: Math.round(v.wins / v.trades * 100), pnl: Math.round(v.pnl * 100) / 100 }))
  }, [closedFiltered])

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 16 }}>
        <div>
          <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--text0)' }}>Journal</div>
          <div style={{ fontSize: 11, color: 'var(--text3)' }}>{allTrades.length} trades · {accountCounts.length} accounts</div>
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

      {/* Account filter chips */}
      <div style={{ display: 'flex', gap: 6, marginBottom: 12, flexWrap: 'wrap' }}>
        <button onClick={() => setAcctFilter('')} style={{
          fontSize: 10, padding: '3px 10px', borderRadius: 6, border: 'none', cursor: 'pointer',
          background: !acctFilter ? 'rgba(96,165,250,.2)' : 'var(--bg2)', color: !acctFilter ? '#60a5fa' : 'var(--text3)',
        }}>All ({allTrades.length})</button>
        {accountCounts.map(([acct, cnt]) => (
          <button key={acct} onClick={() => setAcctFilter(acctFilter === acct ? '' : acct)} style={{
            fontSize: 10, padding: '3px 10px', borderRadius: 6, border: 'none', cursor: 'pointer',
            background: acctFilter === acct ? `${acctColor(acct)}20` : 'var(--bg2)',
            color: acctFilter === acct ? acctColor(acct) : 'var(--text3)',
          }}>
            <span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: '50%', background: acctColor(acct), marginRight: 4 }} />
            {ACCT_LABEL[acct] ?? acct} ({cnt})
          </button>
        ))}
      </div>

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
          {/* KPI Tiles */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(7, 1fr)', gap: 8, marginBottom: 14 }}>
            {[
              { label: 'Open', value: kpis.open, color: '#60a5fa' },
              { label: 'Closed', value: kpis.closed, color: 'var(--text0)' },
              { label: 'Wins', value: kpis.wins, color: '#22c55e' },
              { label: 'Losses', value: kpis.losses, color: '#ef4444' },
              { label: 'Win Rate', value: `${kpis.wr}%`, color: kpis.wr >= 55 ? '#22c55e' : '#f59e0b' },
              { label: 'Profit Factor', value: kpis.pf.toFixed(2), color: 'var(--text0)' },
              { label: 'Total P&L', value: fmt$(kpis.totalPnl, 0), color: kpis.totalPnl >= 0 ? '#22c55e' : '#ef4444' },
            ].map(k => (
              <div key={k.label} style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 8, padding: '8px 10px', textAlign: 'center' }}>
                <div style={{ fontSize: 18, fontWeight: 700, color: k.color, fontFamily: 'monospace' }}>{k.value}</div>
                <div style={{ fontSize: 9, color: 'var(--text3)' }}>{k.label}</div>
              </div>
            ))}
          </div>

          {/* Equity Curve + Daily P&L */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14, marginBottom: 14 }}>
            <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)' }}>Equity Curve</span>
                <span style={{ fontSize: 9, color: 'var(--text3)' }}>cumulative P&L · {equityCurve.length} trades</span>
              </div>
              {equityCurve.length < 2 ? (
                <div style={{ color: 'var(--text3)', fontSize: 11, padding: 20, textAlign: 'center' }}>Insufficient data ({equityCurve.length} trades)</div>
              ) : (
                <ResponsiveContainer width="100%" height={160}>
                  <AreaChart data={equityCurve}>
                    <defs><linearGradient id="jEq" x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor="#22c55e" stopOpacity={0.3}/><stop offset="95%" stopColor="#22c55e" stopOpacity={0}/></linearGradient></defs>
                    <XAxis dataKey="date" tick={{ fontSize: 8, fill: 'var(--text3)' }} />
                    <YAxis tick={{ fontSize: 8, fill: 'var(--text3)' }} tickFormatter={(v: number) => `$${v}`} />
                    <Tooltip contentStyle={{ background: 'var(--bg1)', border: '1px solid var(--border)', fontSize: 10 }} />
                    <Area type="monotone" dataKey="cumulative" stroke="#22c55e" fill="url(#jEq)" strokeWidth={2} />
                  </AreaChart>
                </ResponsiveContainer>
              )}
            </div>
            <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)' }}>Daily P&L</span>
                <span style={{ fontSize: 9, color: 'var(--text3)' }}>{dailyPnl.length} days</span>
              </div>
              {dailyPnl.length === 0 ? (
                <div style={{ color: 'var(--text3)', fontSize: 11, padding: 20, textAlign: 'center' }}>No data</div>
              ) : (
                <ResponsiveContainer width="100%" height={160}>
                  <BarChart data={dailyPnl}>
                    <XAxis dataKey="date" tick={{ fontSize: 8, fill: 'var(--text3)' }} />
                    <YAxis tick={{ fontSize: 8, fill: 'var(--text3)' }} tickFormatter={(v: number) => `$${v}`} />
                    <Tooltip contentStyle={{ background: 'var(--bg1)', border: '1px solid var(--border)', fontSize: 10 }} />
                    <Bar dataKey="pnl" radius={[3, 3, 0, 0]}
                      shape={(props: any) => {
                        const { x, y, width, height, payload } = props
                        return <rect x={x} y={y} width={width} height={Math.abs(height)} rx={3} fill={payload.pnl >= 0 ? '#22c55e' : '#ef4444'} />
                      }} />
                  </BarChart>
                </ResponsiveContainer>
              )}
            </div>
          </div>

          {/* Calendar P&L — proper week grid with DOW headers */}
          <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14, marginBottom: 14 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 10 }}>
              <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)' }}>Calendar P&L</span>
              <span style={{ fontSize: 9, color: 'var(--text3)' }}>{dailyPnl.length} trading days</span>
            </div>
            {Object.keys(calendarMonths.months).length === 0 ? (
              <div style={{ color: 'var(--text3)', fontSize: 11, padding: 10, textAlign: 'center' }}>No closed trades with dates</div>
            ) : (
              Object.entries(calendarMonths.months).sort(([a], [b]) => a.localeCompare(b)).map(([monthKey, days]) => {
                const [yr, mo] = monthKey.split('-').map(Number)
                const daysInMonth = new Date(yr, mo, 0).getDate()
                const startDow = new Date(yr, mo - 1, 1).getDay()
                const monthLabel = new Date(yr, mo - 1).toLocaleDateString('en-US', { month: 'long', year: 'numeric' })
                const cells = []
                for (let i = 0; i < startDow; i++) cells.push(<div key={`e${i}`} style={{ width: 28, height: 28 }} />)
                for (let day = 1; day <= daysInMonth; day++) {
                  const d = days[day]
                  const isWeekend = new Date(yr, mo - 1, day).getDay() % 6 === 0
                  let bg = 'var(--bg0)'
                  let color = 'var(--text3)'
                  if (d) {
                    const intensity = Math.min(1, Math.abs(d.pnl) / calendarMonths.maxPnl)
                    const alpha = 0.2 + intensity * 0.6
                    bg = d.pnl > 0 ? `rgba(34,197,94,${alpha})` : d.pnl < 0 ? `rgba(239,68,68,${alpha})` : 'rgba(148,163,184,0.3)'
                    color = 'var(--text0)'
                  }
                  cells.push(
                    <div key={day}
                      onClick={d ? () => onDrill({
                        title: `${monthKey}-${String(day).padStart(2, '0')}`,
                        subtitle: `${fmt$(d.pnl, 2)} · ${d.trades} trades · ${d.wins}W ${d.losses}L`,
                        endpoint: 'derived from trades',
                        rows: closedFiltered.filter(t => t.exitDate === `${monthKey}-${String(day).padStart(2, '0')}`),
                      }) : undefined}
                      title={d ? `${monthKey}-${String(day).padStart(2, '0')}: ${fmt$(d.pnl, 2)} (${d.trades} trades, ${d.wins}W ${d.losses}L)` : `Day ${day}`}
                      style={{
                        width: 28, height: 28, borderRadius: 4, display: 'flex', alignItems: 'center',
                        justifyContent: 'center', fontSize: 9, color, background: bg,
                        opacity: isWeekend && !d ? 0.3 : 1, cursor: d ? 'pointer' : 'default',
                        border: d ? '1px solid rgba(255,255,255,0.1)' : 'none',
                      }}>{day}</div>
                  )
                }
                return (
                  <div key={monthKey} style={{ marginBottom: 12 }}>
                    <div style={{ fontSize: 11, color: 'var(--text2)', fontWeight: 600, marginBottom: 4 }}>{monthLabel}</div>
                    <div style={{ display: 'flex', gap: 2, marginBottom: 2 }}>
                      {DOW.map((d, i) => <div key={i} style={{ width: 28, textAlign: 'center', fontSize: 8, color: 'var(--text3)' }}>{d}</div>)}
                    </div>
                    <div style={{ display: 'flex', gap: 2, flexWrap: 'wrap', maxWidth: 28 * 7 + 12 }}>{cells}</div>
                  </div>
                )
              })
            )}
            <div style={{ display: 'flex', gap: 12, fontSize: 9, marginTop: 6, color: 'var(--text3)' }}>
              <span><span style={{ display: 'inline-block', width: 10, height: 10, borderRadius: 2, background: '#22c55e', marginRight: 3 }}/>profit</span>
              <span><span style={{ display: 'inline-block', width: 10, height: 10, borderRadius: 2, background: '#ef4444', marginRight: 3 }}/>loss</span>
              <span><span style={{ display: 'inline-block', width: 10, height: 10, borderRadius: 2, background: 'var(--bg0)', marginRight: 3 }}/>no trades</span>
            </div>
          </div>

          {/* Strategy Breakdown */}
          {stratBreakdown.length > 0 && (
            <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14, marginBottom: 14 }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Strategy Breakdown</div>
              <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr 1fr 1fr 1fr', fontSize: 9, color: 'var(--text3)', padding: '4px 6px', borderBottom: '1px solid var(--border)' }}>
                <span>Strategy</span><span>Trades</span><span>Wins</span><span>Win Rate</span><span>P&L</span>
              </div>
              {stratBreakdown.map(s => (
                <div key={s.strategy} onClick={() => onDrill({ title: s.strategy, subtitle: `${s.trades} trades`, endpoint: 'derived', rows: closedFiltered.filter(t => (t.strategyId ?? '(no strategy)') === s.strategy) })}
                  style={{ display: 'grid', gridTemplateColumns: '2fr 1fr 1fr 1fr 1fr', padding: '6px 6px', borderBottom: '1px solid var(--border)', cursor: 'pointer', fontSize: 11 }}>
                  <span style={{ color: 'var(--text0)', fontFamily: 'monospace' }}>{s.strategy}</span>
                  <span style={{ color: 'var(--text2)' }}>{s.trades}</span>
                  <span style={{ color: '#22c55e' }}>{s.wins}</span>
                  <span style={{ color: s.wr >= 55 ? '#22c55e' : s.wr >= 45 ? '#f59e0b' : '#ef4444' }}>{s.wr}%</span>
                  <span style={{ color: s.pnl >= 0 ? '#22c55e' : '#ef4444', fontWeight: 600 }}>{fmt$(s.pnl, 2)}</span>
                </div>
              ))}
            </div>
          )}

          {/* Trade Log */}
          <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14, maxHeight: 400, overflowY: 'auto' }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Trade Log ({filtered.length})</div>
            <div style={{ display: 'grid', gridTemplateColumns: '0.3fr 1fr 1.2fr 0.8fr 0.8fr 0.8fr 0.8fr 0.6fr', fontSize: 9, color: 'var(--text3)', padding: '4px 6px', borderBottom: '1px solid var(--border)' }}>
              <span></span><span>Symbol</span><span>Account</span><span>Entry Date</span><span>Exit Date</span><span>P&L</span><span>Strategy</span><span>Hold</span>
            </div>
            {filtered.map((t, i) => (
              <div key={`${t.id}-${i}`} onClick={() => onDrill({ title: `${t.symbol} #${t.id}`, subtitle: `${t.account} · ${t.strategyId ?? t.source}`, endpoint: t.source === 'schwab' ? '/api/v2/journal' : '/api/v2/automated-trade-journal', rows: [t] })}
                style={{ display: 'grid', gridTemplateColumns: '0.3fr 1fr 1.2fr 0.8fr 0.8fr 0.8fr 0.8fr 0.6fr', padding: '5px 6px', borderBottom: '1px solid var(--border)', cursor: 'pointer', fontSize: 10 }}>
                <span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: '50%', background: acctColor(t.normalizedAccount), marginTop: 3 }} title={ACCT_LABEL[t.normalizedAccount] ?? t.account} />
                <div>
                  <div style={{ fontWeight: 700, color: 'var(--text0)', fontFamily: 'monospace' }}>{t.symbol}</div>
                  <div style={{ fontSize: 8, color: 'var(--text3)' }}>{t.shares} @ {t.entryPrice != null ? fmt$(t.entryPrice, 2) : '—'}</div>
                </div>
                <span style={{ color: acctColor(t.normalizedAccount), fontSize: 9 }}>{ACCT_LABEL[t.normalizedAccount] ?? t.account}</span>
                <span style={{ color: 'var(--text3)', fontSize: 9, fontFamily: 'monospace' }}>{t.entryDate ?? '—'}</span>
                <span style={{ color: 'var(--text3)', fontSize: 9, fontFamily: 'monospace' }}>{t.exitDate ?? (t.status === 'open' ? 'OPEN' : '—')}</span>
                <span style={{ color: t.status === 'open' ? '#60a5fa' : t.pnl >= 0 ? '#22c55e' : '#ef4444', fontWeight: 600 }}>
                  {t.status === 'open' ? 'OPEN' : fmt$(t.pnl, 2)}
                </span>
                <span style={{ color: 'var(--text2)', fontSize: 9 }}>{t.strategyId ?? '—'}</span>
                <span style={{ color: 'var(--text3)', fontSize: 9 }}>
                  {t.holdMin != null ? (t.holdMin < 60 ? `${Math.round(t.holdMin)}m` : `${Math.round(t.holdMin / 60)}h`) : t.holdDays != null ? `${t.holdDays}d` : '—'}
                </span>
              </div>
            ))}
          </div>
          <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 6 }}>
            Sources: /api/v2/automated-trade-journal (paper) + /api/v2/journal (Schwab). Read-only.
          </div>
        </>
      )}

      {tab === 'Analytics' && (
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 10 }}>Journal Field Completeness</div>
          {Object.keys(jc).length === 0 ? <div style={{ color: 'var(--text3)', fontSize: 11 }}>No completeness data</div> :
          Object.entries(jc).sort(([, a]: [string, any], [, b]: [string, any]) => b - a).map(([field, pct]: [string, any]) => (
            <div key={field} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 3 }}>
              <span style={{ width: 120, fontSize: 10, color: 'var(--text2)' }}>{field}</span>
              <div style={{ flex: 1, height: 12, background: 'var(--bg2)', borderRadius: 3, overflow: 'hidden' }}>
                <div style={{ width: `${pct}%`, height: '100%', background: pct >= 95 ? '#22c55e' : pct >= 80 ? '#f59e0b' : '#ef4444', borderRadius: 3 }} />
              </div>
              <span style={{ fontSize: 10, color: pct >= 95 ? '#22c55e' : pct >= 80 ? '#f59e0b' : '#ef4444', width: 40, textAlign: 'right' }}>{pct}%</span>
            </div>
          ))}
          <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 8 }}>Source: /api/v2/paper-trade-readiness</div>
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
            </div>
          ))}
          <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 8 }}>Source: /api/v2/journal/closed-trades/lessons</div>
        </div>
      )}

      {tab === 'Protection' && <ProtectionOutcomesPanel onDrill={onDrill} />}
    </div>
  )
}
