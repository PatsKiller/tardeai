import { useState, useMemo } from 'react'
import { useApi } from '../hooks/useApi'
import { fmt$ } from '../lib/format'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, AreaChart, Area, PieChart, Pie, Cell } from 'recharts'
import type { DrillContext } from '../components/DetailDrawer'
import ProtectionOutcomesPanel from '../components/ProtectionOutcomesPanel'
import BacktestPanel from '../components/BacktestPanel'

interface Props { onDrill: (ctx: DrillContext) => void }
const TABS = ['Trades', 'Analytics', 'Lessons', 'Protection', 'Backtesting'] as const
const TIME_RANGES = ['6M', '3M', '1M', 'YTD', '1Y', 'ALL'] as const

const ACCT_COLOR: Record<string, string> = {
  schwab_rollover_ira: '#60a5fa', schwab_taxable: '#a855f7', schwab_roth_ira: '#06b6d4',
  schwab_roth: '#06b6d4', alpaca_paper: '#22c55e', ALPACA_PAPER: '#22c55e', TOS_PAPER: '#22c55e',
}
const acctColor = (a: string) => ACCT_COLOR[a] ?? ACCT_COLOR[a?.toLowerCase()] ?? 'var(--text2)'
const normalizeAcct = (a: string) => {
  const l = (a ?? '').toLowerCase()
  if (l.includes('alpaca') || l.includes('tos')) return 'alpaca_paper'
  if (l === 'schwab_roth') return 'schwab_roth_ira'
  return l
}
const ACCT_LABEL: Record<string, string> = {
  schwab_rollover_ira: 'Schwab Rollover IRA', schwab_taxable: 'Schwab Taxable',
  schwab_roth_ira: 'Schwab Roth IRA', alpaca_paper: 'Alpaca Paper',
}
const DOW = ['S', 'M', 'T', 'W', 'T', 'F', 'S']
const PIE_COLORS = ['#60a5fa', '#22c55e', '#a855f7', '#06b6d4', '#f59e0b', '#ef4444']

interface UT {
  id: string | number; symbol: string; account: string; na: string
  ep: number | null; xp: number | null; shares: number
  pnl: number; pnlPct: number | null; holdDays: number | null; holdMin: number | null
  exitReason: string | null; strat: string | null; status: string
  entryDate: string | null; exitDate: string | null; source: 'paper' | 'schwab'
  eg: string | null; xg: string | null
}

// Entry/exit letter-grade → color
function gradeColor(g: string | null | undefined): string {
  switch (g) {
    case 'A': return '#22c55e'
    case 'B': return '#86efac'
    case 'C': return '#f59e0b'
    case 'D': return '#ef4444'
    case 'F': return '#dc2626'
    default: return 'var(--text3)'
  }
}

function getTimeRangeCutoff(range: string): string {
  const now = new Date()
  if (range === 'ALL') return '2000-01-01'
  if (range === 'YTD') return `${now.getFullYear()}-01-01`
  const months: Record<string, number> = { '1M': 1, '3M': 3, '6M': 6, '1Y': 12 }
  const m = months[range] ?? 6
  const d = new Date(now.getFullYear(), now.getMonth() - m, now.getDate())
  return d.toISOString().slice(0, 10)
}

export default function JournalHub({ onDrill }: Props) {
  const [tab, setTab] = useState<typeof TABS[number]>('Trades')
  const [acctFilter, setAcctFilter] = useState('')
  const [timeRange, setTimeRange] = useState<typeof TIME_RANGES[number]>('6M')
  const { data: journal } = useApi<any>('/api/v2/automated-trade-journal', 60_000)
  const { data: schwabJournal } = useApi<any>('/api/v2/journal', 120_000)
  const { data: readiness } = useApi<any>('/api/v2/paper-trade-readiness', 120_000)
  const { data: rawLessonsResp } = useApi<any>('/api/v2/journal/closed-trades/lessons', 120_000)
  // Handle double-wrapped { ok, data: { ok, lessons, count } }
  const lessonsData = rawLessonsResp?.data ?? rawLessonsResp

  const warnings = journal?.integrity_warnings ?? []
  const jc = readiness?.journal_completeness ?? {}

  // ── Unify all trades ──
  const allTrades: UT[] = useMemo(() => {
    const result: UT[] = []
    for (const t of (journal?.trades ?? [])) {
      result.push({
        id: t.id, symbol: t.symbol, account: t.account ?? 'alpaca_paper',
        na: normalizeAcct(t.account ?? 'alpaca_paper'),
        ep: t.entry_price, xp: t.exit_price, shares: t.shares ?? 0,
        pnl: t.pnl ?? 0, pnlPct: t.pnl_pct, holdDays: null,
        holdMin: t.hold_time_min, exitReason: t.exit_reason, strat: t.strategy_id,
        status: t.status ?? 'closed', entryDate: t.entry_time?.slice(0, 10) ?? t.created_at?.slice(0, 10),
        exitDate: t.closed_at?.slice(0, 10), source: 'paper',
        eg: t.entry_grade ?? null, xg: t.exit_grade ?? null,
      })
    }
    for (const t of (schwabJournal?.trades ?? [])) {
      result.push({
        id: `sw-${t.trade_key ?? t.symbol}-${t.open_date}`, symbol: t.symbol,
        account: t.account, na: normalizeAcct(t.account),
        ep: t.buy_price, xp: t.sell_price, shares: t.shares ?? 0,
        pnl: t.pnl ?? 0, pnlPct: t.pnl_pct, holdDays: t.hold_days,
        holdMin: null, exitReason: null, strat: null,
        status: 'closed', entryDate: t.open_date, exitDate: t.close_date, source: 'schwab',
        eg: t.entry_grade ?? null, xg: t.exit_grade ?? null,
      })
    }
    return result.sort((a, b) => (b.exitDate ?? b.entryDate ?? '').localeCompare(a.exitDate ?? a.entryDate ?? ''))
  }, [journal, schwabJournal])

  // ── Apply BOTH filters (account + time range) — shared across all tabs ──
  const cutoff = getTimeRangeCutoff(timeRange)
  const filtered = useMemo(() => {
    let f = allTrades
    if (acctFilter) f = f.filter(t => t.na === acctFilter)
    f = f.filter(t => (t.exitDate ?? t.entryDate ?? '9999') >= cutoff || t.status === 'open')
    return f
  }, [allTrades, acctFilter, cutoff])

  const closed = filtered.filter(t => t.status === 'closed')
  const open = filtered.filter(t => t.status === 'open')

  // ── Account chips ──
  const accountCounts = useMemo(() => {
    const m: Record<string, number> = {}
    for (const t of allTrades) m[t.na] = (m[t.na] ?? 0) + 1
    return Object.entries(m).sort((a, b) => b[1] - a[1])
  }, [allTrades])

  // ── KPIs ──
  const kpis = useMemo(() => {
    const wins = closed.filter(t => t.pnl > 0)
    const losses = closed.filter(t => t.pnl < 0)
    const gp = wins.reduce((s, t) => s + t.pnl, 0)
    const gl = Math.abs(losses.reduce((s, t) => s + t.pnl, 0))
    const avgWin = wins.length > 0 ? gp / wins.length : 0
    const avgLoss = losses.length > 0 ? gl / losses.length : 0
    return {
      open: open.length, closed: closed.length,
      wins: wins.length, losses: losses.length,
      wr: closed.length > 0 ? Math.round(wins.length / closed.length * 1000) / 10 : 0,
      pf: gl > 0 ? Math.round(gp / gl * 100) / 100 : 0,
      totalPnl: Math.round(closed.reduce((s, t) => s + t.pnl, 0) * 100) / 100,
      avgWin: Math.round(avgWin * 100) / 100,
      avgLoss: Math.round(avgLoss * 100) / 100,
      expectancy: closed.length > 0 ? Math.round(closed.reduce((s, t) => s + t.pnl, 0) / closed.length * 100) / 100 : 0,
    }
  }, [closed, open])

  // ── Equity curve ──
  const equityCurve = useMemo(() => {
    const sorted = [...closed].filter(t => t.exitDate).sort((a, b) => (a.exitDate!).localeCompare(b.exitDate!))
    let cum = 0
    return sorted.map(t => { cum += t.pnl; return { date: (t.exitDate ?? '').slice(5), symbol: t.symbol, pnl: t.pnl, cumulative: Math.round(cum * 100) / 100, account: t.na } })
  }, [closed])

  // ── Daily P&L ──
  const dailyPnl = useMemo(() => {
    const m: Record<string, { pnl: number; trades: number; wins: number; losses: number }> = {}
    for (const t of closed) {
      if (!t.exitDate) continue
      if (!m[t.exitDate]) m[t.exitDate] = { pnl: 0, trades: 0, wins: 0, losses: 0 }
      m[t.exitDate].pnl += t.pnl; m[t.exitDate].trades += 1
      if (t.pnl > 0) m[t.exitDate].wins += 1; else if (t.pnl < 0) m[t.exitDate].losses += 1
    }
    return Object.entries(m).sort(([a], [b]) => a.localeCompare(b))
      .map(([date, v]) => ({ date: date.slice(5), fullDate: date, ...v, pnl: Math.round(v.pnl * 100) / 100 }))
  }, [closed])

  // ── Calendar months ──
  const calendarData = useMemo(() => {
    const byDate: Record<string, { pnl: number; trades: number; wins: number; losses: number }> = {}
    for (const t of closed) {
      if (!t.exitDate) continue
      if (!byDate[t.exitDate]) byDate[t.exitDate] = { pnl: 0, trades: 0, wins: 0, losses: 0 }
      byDate[t.exitDate].pnl += t.pnl; byDate[t.exitDate].trades += 1
      if (t.pnl > 0) byDate[t.exitDate].wins += 1; else if (t.pnl < 0) byDate[t.exitDate].losses += 1
    }
    const months: Record<string, Record<number, typeof byDate[string]>> = {}
    for (const [date, data] of Object.entries(byDate)) {
      const mk = date.slice(0, 7)
      if (!months[mk]) months[mk] = {}
      months[mk][parseInt(date.slice(8))] = data
    }
    return { months, maxPnl: Math.max(1, ...Object.values(byDate).map(d => Math.abs(d.pnl))) }
  }, [closed])

  // ── Strategy breakdown ──
  const stratBreakdown = useMemo(() => {
    const m: Record<string, { trades: number; wins: number; pnl: number }> = {}
    for (const t of closed) {
      const s = t.strat ?? '(unclassified)'
      if (!m[s]) m[s] = { trades: 0, wins: 0, pnl: 0 }
      m[s].trades += 1; if (t.pnl > 0) m[s].wins += 1; m[s].pnl += t.pnl
    }
    return Object.entries(m).sort((a, b) => b[1].trades - a[1].trades)
      .map(([strat, v]) => ({ strategy: strat, ...v, wr: Math.round(v.wins / v.trades * 100), pnl: Math.round(v.pnl * 100) / 100 }))
  }, [closed])

  // ── Account breakdown for analytics ──
  const acctBreakdown = useMemo(() => {
    const m: Record<string, { trades: number; wins: number; pnl: number }> = {}
    for (const t of closed) {
      if (!m[t.na]) m[t.na] = { trades: 0, wins: 0, pnl: 0 }
      m[t.na].trades += 1; if (t.pnl > 0) m[t.na].wins += 1; m[t.na].pnl += t.pnl
    }
    return Object.entries(m).sort((a, b) => b[1].trades - a[1].trades)
      .map(([acct, v]) => ({ account: acct, label: ACCT_LABEL[acct] ?? acct, color: acctColor(acct), ...v, wr: Math.round(v.wins / v.trades * 100), pnl: Math.round(v.pnl * 100) / 100 }))
  }, [closed])

  // ── Shared filter bar (renders at top, applies to ALL tabs) ──
  const filterBar = (
    <div style={{ marginBottom: 12 }}>
      {/* Account chips */}
      <div style={{ display: 'flex', gap: 6, marginBottom: 8, flexWrap: 'wrap' }}>
        <button onClick={() => setAcctFilter('')} style={{ fontSize: 10, padding: '3px 10px', borderRadius: 6, border: 'none', cursor: 'pointer', background: !acctFilter ? 'rgba(96,165,250,.2)' : 'var(--bg2)', color: !acctFilter ? '#60a5fa' : 'var(--text3)' }}>
          All ({allTrades.length})
        </button>
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
      {/* Time range chips */}
      <div style={{ display: 'flex', gap: 4 }}>
        {TIME_RANGES.map(r => (
          <button key={r} onClick={() => setTimeRange(r)} style={{
            fontSize: 9, padding: '2px 8px', borderRadius: 4, border: 'none', cursor: 'pointer',
            background: timeRange === r ? 'rgba(245,158,11,.2)' : 'var(--bg2)',
            color: timeRange === r ? '#f59e0b' : 'var(--text3)',
          }}>{r}</button>
        ))}
        <span style={{ fontSize: 9, color: 'var(--text3)', marginLeft: 6, lineHeight: '22px' }}>
          {filtered.length} trades in range · {closed.length} closed
        </span>
      </div>
    </div>
  )

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

      {/* Shared filters — persists across ALL tabs */}
      {filterBar}

      {warnings.length > 0 && (
        <div style={{ marginBottom: 12, padding: '8px 12px', background: 'rgba(245,158,11,.06)', border: '1px solid rgba(245,158,11,.15)', borderRadius: 8 }}>
          <div style={{ fontSize: 10, fontWeight: 700, color: '#f59e0b', marginBottom: 4 }}>Integrity Warnings ({warnings.length})</div>
          {warnings.slice(0, 3).map((w: any, i: number) => (
            <div key={i} style={{ fontSize: 9, color: '#fbbf24', padding: '1px 0' }}>{typeof w === 'string' ? w : JSON.stringify(w)}</div>
          ))}
        </div>
      )}

      {/* ════════ TRADES TAB ════════ */}
      {tab === 'Trades' && (
        <>
          {/* KPIs — hover ⓘ for definitions; click count tiles to drill the matching trades */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(8, 1fr)', gap: 6, marginBottom: 14 }}>
            {[
              { l: 'Open', v: kpis.open, c: '#60a5fa', tip: 'Currently-open positions in this view (no exit yet).', rows: open },
              { l: 'Closed', v: kpis.closed, c: 'var(--text0)', tip: 'Trades closed within the selected time range.', rows: closed },
              { l: 'Wins', v: kpis.wins, c: '#22c55e', tip: 'Closed trades with positive realized P&L.', rows: closed.filter(t => t.pnl > 0) },
              { l: 'Losses', v: kpis.losses, c: '#ef4444', tip: 'Closed trades with negative realized P&L.', rows: closed.filter(t => t.pnl < 0) },
              { l: 'Win Rate', v: `${kpis.wr}%`, c: kpis.wr >= 55 ? '#22c55e' : '#f59e0b', tip: 'Wins ÷ resolved trades (excludes $0 scratches). 55%+ is the target.' },
              { l: 'P. Factor', v: kpis.pf.toFixed(2), c: 'var(--text0)', tip: 'Profit factor = gross wins ÷ gross losses. >1 profitable, >2 strong.' },
              { l: 'Expectancy', v: fmt$(kpis.expectancy, 0), c: kpis.expectancy >= 0 ? '#22c55e' : '#ef4444', tip: 'Average realized $ per closed trade — your edge per trade (total P&L ÷ closed count).' },
              { l: 'Total P&L', v: fmt$(kpis.totalPnl, 0), c: kpis.totalPnl >= 0 ? '#22c55e' : '#ef4444', tip: 'Sum of realized P&L across closed trades in range.', rows: closed },
            ].map(k => (
              <div key={k.l} title={k.tip}
                onClick={k.rows ? () => onDrill({ title: k.l, subtitle: `${k.rows.length} trade${k.rows.length === 1 ? '' : 's'}`, endpoint: 'derived', rows: k.rows }) : undefined}
                style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 8, padding: '6px 8px', textAlign: 'center', cursor: k.rows ? 'pointer' : 'help' }}>
                <div style={{ fontSize: 16, fontWeight: 700, color: k.c, fontFamily: 'monospace' }}>{k.v}</div>
                <div style={{ fontSize: 8, color: 'var(--text3)' }}>{k.l} ⓘ</div>
              </div>
            ))}
          </div>

          {/* Charts row */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14, marginBottom: 14 }}>
            <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14 }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', marginBottom: 6 }}>Equity Curve <span style={{ fontSize: 9, color: 'var(--text3)', fontWeight: 400 }}>cumulative · {equityCurve.length} trades</span></div>
              {equityCurve.length < 2 ? <div style={{ color: 'var(--text3)', fontSize: 11, padding: 20, textAlign: 'center' }}>Insufficient data</div> : (
                <ResponsiveContainer width="100%" height={150}>
                  <AreaChart data={equityCurve}>
                    <defs><linearGradient id="jEq" x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor="#22c55e" stopOpacity={0.3}/><stop offset="95%" stopColor="#22c55e" stopOpacity={0}/></linearGradient></defs>
                    <XAxis dataKey="date" tick={{ fontSize: 7, fill: 'var(--text3)' }} /><YAxis tick={{ fontSize: 7, fill: 'var(--text3)' }} tickFormatter={(v: number) => `$${v}`} />
                    <Tooltip contentStyle={{ background: 'var(--bg1)', border: '1px solid var(--border)', fontSize: 10 }} />
                    <Area type="monotone" dataKey="cumulative" stroke="#22c55e" fill="url(#jEq)" strokeWidth={2} />
                  </AreaChart>
                </ResponsiveContainer>
              )}
            </div>
            <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14 }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', marginBottom: 6 }}>Daily P&L <span style={{ fontSize: 9, color: 'var(--text3)', fontWeight: 400 }}>{dailyPnl.length} days</span></div>
              {dailyPnl.length === 0 ? <div style={{ color: 'var(--text3)', fontSize: 11, padding: 20, textAlign: 'center' }}>No data</div> : (
                <ResponsiveContainer width="100%" height={150}>
                  <BarChart data={dailyPnl}>
                    <XAxis dataKey="date" tick={{ fontSize: 7, fill: 'var(--text3)' }} /><YAxis tick={{ fontSize: 7, fill: 'var(--text3)' }} tickFormatter={(v: number) => `$${v}`} />
                    <Tooltip contentStyle={{ background: 'var(--bg1)', border: '1px solid var(--border)', fontSize: 10 }} />
                    <Bar dataKey="pnl" radius={[3, 3, 0, 0]} shape={(props: any) => {
                      const { x, y, width, height, payload } = props
                      return <rect x={x} y={y} width={width} height={Math.abs(height)} rx={3} fill={payload.pnl >= 0 ? '#22c55e' : '#ef4444'} />
                    }} />
                  </BarChart>
                </ResponsiveContainer>
              )}
            </div>
          </div>

          {/* Calendar */}
          <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14, marginBottom: 14 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
              <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)' }}>Calendar P&L</span>
              <span style={{ fontSize: 9, color: 'var(--text3)' }}>{dailyPnl.length} trading days</span>
            </div>
            {Object.keys(calendarData.months).length === 0 ? (
              <div style={{ color: 'var(--text3)', fontSize: 11, padding: 10, textAlign: 'center' }}>No closed trades in selected range</div>
            ) : (
              <div style={{ display: 'flex', gap: 16, overflowX: 'auto', paddingBottom: 8 }}>
              {Object.entries(calendarData.months).sort(([a], [b]) => a.localeCompare(b)).map(([mk, days]) => {
                const [yr, mo] = mk.split('-').map(Number)
                const dim = new Date(yr, mo, 0).getDate()
                const sdow = new Date(yr, mo - 1, 1).getDay()
                const ml = new Date(yr, mo - 1).toLocaleDateString('en-US', { month: 'long', year: 'numeric' })
                const cells = []
                for (let i = 0; i < sdow; i++) cells.push(<div key={`e${i}`} style={{ width: 26, height: 26 }} />)
                for (let day = 1; day <= dim; day++) {
                  const d = days[day]
                  const isWe = new Date(yr, mo - 1, day).getDay() % 6 === 0
                  let bg = 'var(--bg0)', color = 'var(--text3)'
                  if (d) {
                    const int = Math.min(1, Math.abs(d.pnl) / calendarData.maxPnl)
                    const a = 0.2 + int * 0.6
                    bg = d.pnl > 0 ? `rgba(34,197,94,${a})` : d.pnl < 0 ? `rgba(239,68,68,${a})` : 'rgba(148,163,184,0.3)'
                    color = 'var(--text0)'
                  }
                  cells.push(
                    <div key={day} onClick={d ? () => onDrill({ title: `${mk}-${String(day).padStart(2,'0')}`, subtitle: `${fmt$(d.pnl,2)} · ${d.trades} trades`, endpoint: 'derived', rows: closed.filter(t => t.exitDate === `${mk}-${String(day).padStart(2,'0')}`) }) : undefined}
                      title={d ? `${mk}-${String(day).padStart(2,'0')}: ${fmt$(d.pnl,2)} (${d.trades}t, ${d.wins}W ${d.losses}L)` : `${day}`}
                      style={{ width: 26, height: 26, borderRadius: 4, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 8, color, background: bg, opacity: isWe && !d ? 0.3 : 1, cursor: d ? 'pointer' : 'default', border: d ? '1px solid rgba(255,255,255,0.1)' : 'none' }}>{day}</div>
                  )
                }
                return (
                  <div key={mk} style={{ marginBottom: 10 }}>
                    <div style={{ fontSize: 10, color: 'var(--text2)', fontWeight: 600, marginBottom: 3 }}>{ml}</div>
                    <div style={{ display: 'flex', gap: 2, marginBottom: 2 }}>{DOW.map((d, i) => <div key={i} style={{ width: 26, textAlign: 'center', fontSize: 7, color: 'var(--text3)' }}>{d}</div>)}</div>
                    <div style={{ display: 'flex', gap: 2, flexWrap: 'wrap', maxWidth: 26 * 7 + 12 }}>{cells}</div>
                  </div>
                )
              })}
              </div>
            )}
            <div style={{ display: 'flex', gap: 10, fontSize: 8, marginTop: 4, color: 'var(--text3)' }}>
              <span><span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: 2, background: '#22c55e', marginRight: 3 }}/>profit</span>
              <span><span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: 2, background: '#ef4444', marginRight: 3 }}/>loss</span>
              <span><span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: 2, background: 'var(--bg0)', marginRight: 3 }}/>no trades</span>
            </div>
          </div>

          {/* Strategy + Monthly side by side */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14, marginBottom: 14 }}>
            {stratBreakdown.length > 0 && (
              <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14 }}>
                <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', marginBottom: 6 }}>By Strategy</div>
                {stratBreakdown.map(s => (
                  <div key={s.strategy} onClick={() => onDrill({ title: s.strategy, subtitle: `${s.trades} trades`, endpoint: 'derived', rows: closed.filter(t => (t.strat ?? '(unclassified)') === s.strategy) })}
                    style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 6px', borderBottom: '1px solid var(--border)', cursor: 'pointer', fontSize: 10 }}>
                    <span style={{ color: 'var(--text0)', fontFamily: 'monospace' }}>{s.strategy}</span>
                    <div style={{ display: 'flex', gap: 12 }}>
                      <span style={{ color: 'var(--text3)' }}>{s.trades}t</span>
                      <span style={{ color: s.wr >= 55 ? '#22c55e' : '#f59e0b', width: 35 }}>{s.wr}%</span>
                      <span style={{ color: s.pnl >= 0 ? '#22c55e' : '#ef4444', fontWeight: 600, width: 60, textAlign: 'right' }}>{fmt$(s.pnl, 0)}</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
            {/* Monthly */}
            {dailyPnl.length > 0 && (
              <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14 }}>
                <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', marginBottom: 6 }}>Monthly Summary</div>
                {(() => {
                  const byM: Record<string, { pnl: number; t: number; w: number; l: number }> = {}
                  for (const t of closed) { if (!t.exitDate) continue; const m = t.exitDate.slice(0,7); if (!byM[m]) byM[m]={pnl:0,t:0,w:0,l:0}; byM[m].pnl+=t.pnl; byM[m].t+=1; if(t.pnl>0)byM[m].w+=1; else if(t.pnl<0)byM[m].l+=1 }
                  return Object.entries(byM).sort(([a],[b])=>a.localeCompare(b)).map(([m,v])=>(
                    <div key={m} title={`${m}: ${v.t} trades · ${v.w}W ${v.l}L · ${fmt$(Math.round(v.pnl),0)} — click to view`}
                      onClick={() => onDrill({ title: `${m} — Monthly`, subtitle: `${v.t} trades · ${fmt$(Math.round(v.pnl),0)}`, endpoint: 'derived', rows: closed.filter(t => (t.exitDate ?? '').slice(0,7) === m) })}
                      style={{ display:'flex',justifyContent:'space-between',padding:'4px 6px',borderBottom:'1px solid var(--border)',fontSize:10, cursor:'pointer' }}>
                      <span style={{color:'var(--text0)',fontFamily:'monospace'}}>{m}</span>
                      <div style={{display:'flex',gap:10}}>
                        <span style={{color:'var(--text3)'}}>{v.t}t</span>
                        <span style={{color:v.t>0?((v.w/v.t*100)>=55?'#22c55e':'#f59e0b'):'var(--text3)'}}>{v.t>0?Math.round(v.w/v.t*100):0}%</span>
                        <span style={{color:v.pnl>=0?'#22c55e':'#ef4444',fontWeight:600,width:70,textAlign:'right'}}>{fmt$(Math.round(v.pnl),0)}</span>
                      </div>
                    </div>
                  ))
                })()}
              </div>
            )}
          </div>

          {/* Trade Log */}
          <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14, maxHeight: 400, overflowY: 'auto' }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', marginBottom: 6 }}>Trade Log ({filtered.length})</div>
            <div style={{ display: 'grid', gridTemplateColumns: '0.2fr 0.8fr 1.1fr 0.7fr 0.7fr 0.7fr 0.6fr 0.9fr 0.5fr', fontSize: 8, color: 'var(--text3)', padding: '3px 6px', borderBottom: '1px solid var(--border)' }}>
              <span title="Account color (dot matches the account legend).">●</span>
              <span title="Ticker symbol and share count. Click any row for full trade detail.">Symbol ⓘ</span>
              <span title="Brokerage account the trade was booked in.">Account</span>
              <span title="Entry date.">Entry</span>
              <span title="Exit date (— if still open).">Exit</span>
              <span title="Realized profit/loss. $0.00 = scratch/no-fill or open.">P&L</span>
              <span title="Entry grade / exit grade, from backtest-replay grading (A best → F). '/' separates entry and exit quality.">Grade ⓘ</span>
              <span title="Strategy that generated the trade.">Strategy</span>
              <span title="Hold duration (m=minutes, h=hours).">Hold</span>
            </div>
            {filtered.map((t, i) => (
              <div key={`${t.id}-${i}`} onClick={() => onDrill({ title: `${t.symbol}`, subtitle: `${ACCT_LABEL[t.na]??t.account} · ${t.strat??t.source}`, endpoint: t.source==='schwab'?'/api/v2/journal':'/api/v2/automated-trade-journal', rows: [{ ...t, entry_grade: t.eg, exit_grade: t.xg }], subjectType: 'closed_trade', subjectKey: t.symbol })}
                style={{ display: 'grid', gridTemplateColumns: '0.2fr 0.8fr 1.1fr 0.7fr 0.7fr 0.7fr 0.6fr 0.9fr 0.5fr', padding: '4px 6px', borderBottom: '1px solid var(--border)', borderLeft: `3px solid ${acctColor(t.na)}`, cursor: 'pointer', fontSize: 10, background: `${acctColor(t.na)}06` }}>
                <span style={{ display: 'inline-block', width: 7, height: 7, borderRadius: '50%', background: acctColor(t.na), marginTop: 4 }} />
                <div>
                  <span style={{ fontWeight: 700, color: 'var(--text0)', fontFamily: 'monospace' }}>{t.symbol}</span>
                  <span style={{ fontSize: 8, color: 'var(--text3)', marginLeft: 4 }}>{t.shares}sh</span>
                </div>
                <span style={{ color: acctColor(t.na), fontSize: 9 }}>{ACCT_LABEL[t.na] ?? t.na}</span>
                <span style={{ color: 'var(--text3)', fontSize: 9, fontFamily: 'monospace' }}>{t.entryDate ?? '—'}</span>
                <span style={{ color: 'var(--text3)', fontSize: 9, fontFamily: 'monospace' }}>{t.exitDate ?? (t.status==='open'?'—':'—')}</span>
                <span style={{ color: t.status==='open'?'#60a5fa':t.pnl>=0?'#22c55e':'#ef4444', fontWeight: 600 }}>{t.status==='open'?'OPEN':fmt$(t.pnl,2)}</span>
                <span style={{ fontSize: 9, fontFamily: 'monospace', display: 'flex', gap: 2, alignItems: 'center' }}>
                  {(t.eg || t.xg)
                    ? <><span title="Entry grade" style={{ color: gradeColor(t.eg), fontWeight: 700 }}>{t.eg ?? '·'}</span>
                        <span style={{ color: 'var(--text3)' }}>/</span>
                        <span title="Exit grade" style={{ color: gradeColor(t.xg), fontWeight: 700 }}>{t.xg ?? '·'}</span></>
                    : <span style={{ color: 'var(--text3)' }}>—</span>}
                </span>
                <span style={{ color: 'var(--text2)', fontSize: 9 }}>{t.strat ?? '—'}</span>
                <span style={{ color: 'var(--text3)', fontSize: 8 }}>{t.holdMin!=null?(t.holdMin<60?`${Math.round(t.holdMin)}m`:`${Math.round(t.holdMin/60)}h`):t.holdDays!=null?`${t.holdDays}d`:'—'}</span>
              </div>
            ))}
          </div>
          <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 4 }}>
            Sources: /api/v2/automated-trade-journal (paper) + /api/v2/journal (Schwab). Grade = entry/exit grade from backtest replay grading (trade_backtest_results), where available. /journal returns trades from 2024-11 onward; older Schwab history exists in DB (153 closed) but is not returned by this endpoint.
          </div>
        </>
      )}

      {/* ════════ ANALYTICS TAB ════════ */}
      {tab === 'Analytics' && (
        <>
          {/* Performance KPIs — computed from filtered trades */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 8, marginBottom: 14 }}>
            {[
              { l: 'Win Rate', v: `${kpis.wr}%`, c: kpis.wr >= 55 ? '#22c55e' : '#f59e0b' },
              { l: 'Profit Factor', v: kpis.pf.toFixed(2), c: kpis.pf >= 1.3 ? '#22c55e' : '#f59e0b' },
              { l: 'Avg Winner', v: fmt$(kpis.avgWin, 0), c: '#22c55e' },
              { l: 'Avg Loser', v: fmt$(-kpis.avgLoss, 0), c: '#ef4444' },
              { l: 'Expectancy', v: fmt$(kpis.expectancy, 0), c: kpis.expectancy >= 0 ? '#22c55e' : '#ef4444' },
            ].map(k => (
              <div key={k.l} style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 8, padding: '10px 12px', textAlign: 'center' }}>
                <div style={{ fontSize: 20, fontWeight: 700, color: k.c, fontFamily: 'monospace' }}>{k.v}</div>
                <div style={{ fontSize: 9, color: 'var(--text3)' }}>{k.l}</div>
              </div>
            ))}
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14, marginBottom: 14 }}>
            {/* Account breakdown with donut */}
            <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14 }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>P&L by Account</div>
              {acctBreakdown.length === 0 ? <div style={{ color: 'var(--text3)', fontSize: 11 }}>No data</div> : (
                <>
                  <ResponsiveContainer width="100%" height={140}>
                    <PieChart><Pie data={acctBreakdown.map(a => ({ name: a.label, value: Math.abs(a.pnl) }))} cx="50%" cy="50%" outerRadius={55} dataKey="value" stroke="var(--bg0)" strokeWidth={2}>
                      {acctBreakdown.map((a, i) => <Cell key={i} fill={a.color} />)}
                    </Pie><Tooltip contentStyle={{ background: 'var(--bg1)', border: '1px solid var(--border)', fontSize: 10 }} /></PieChart>
                  </ResponsiveContainer>
                  {acctBreakdown.map(a => (
                    <div key={a.account} style={{ display: 'flex', justifyContent: 'space-between', padding: '3px 6px', borderBottom: '1px solid var(--border)', fontSize: 10 }}>
                      <span style={{ color: a.color }}>{a.label}</span>
                      <div style={{ display: 'flex', gap: 10 }}>
                        <span style={{ color: 'var(--text3)' }}>{a.trades}t</span>
                        <span style={{ color: a.wr >= 55 ? '#22c55e' : '#f59e0b' }}>{a.wr}%</span>
                        <span style={{ color: a.pnl >= 0 ? '#22c55e' : '#ef4444', fontWeight: 600 }}>{fmt$(a.pnl, 0)}</span>
                      </div>
                    </div>
                  ))}
                </>
              )}
              <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 6 }}>Computed from {closed.length} closed trades in selected range</div>
            </div>

            {/* Journal completeness */}
            <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14 }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Data Quality (Paper Trades)</div>
              {Object.keys(jc).length === 0 ? <div style={{ color: 'var(--text3)', fontSize: 11 }}>No completeness data</div> :
              Object.entries(jc).sort(([, a]: [string, any], [, b]: [string, any]) => b - a).map(([field, pct]: [string, any]) => (
                <div key={field} style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 2 }}>
                  <span style={{ width: 90, fontSize: 9, color: 'var(--text2)' }}>{field}</span>
                  <div style={{ flex: 1, height: 10, background: 'var(--bg2)', borderRadius: 3, overflow: 'hidden' }}>
                    <div style={{ width: `${pct}%`, height: '100%', background: pct >= 95 ? '#22c55e' : pct >= 80 ? '#f59e0b' : '#ef4444', borderRadius: 3 }} />
                  </div>
                  <span style={{ fontSize: 9, color: pct >= 95 ? '#22c55e' : pct >= 80 ? '#f59e0b' : '#ef4444', width: 30, textAlign: 'right' }}>{pct}%</span>
                </div>
              ))}
              <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 6 }}>Source: /api/v2/paper-trade-readiness (paper trades only — Schwab has no field completeness tracking)</div>
            </div>
          </div>

          {/* Actionable insights */}
          <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14 }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Actionable Insights</div>
            {kpis.wr < 55 && <div style={{ padding: '4px 8px', fontSize: 10, color: '#f59e0b', borderBottom: '1px solid var(--border)' }}>Win rate {kpis.wr}% is below 55% gate — {Math.ceil(55 * kpis.closed / 100) - kpis.wins} more wins needed at current sample size</div>}
            {kpis.avgLoss > kpis.avgWin && <div style={{ padding: '4px 8px', fontSize: 10, color: '#ef4444', borderBottom: '1px solid var(--border)' }}>Average loser (${kpis.avgLoss}) exceeds average winner (${kpis.avgWin}) — review stop placement</div>}
            {kpis.pf >= 1.3 && <div style={{ padding: '4px 8px', fontSize: 10, color: '#22c55e', borderBottom: '1px solid var(--border)' }}>Profit factor {kpis.pf.toFixed(2)} clears the 1.3 gate requirement</div>}
            {stratBreakdown.filter(s => s.wr < 35 && s.trades >= 3).map(s => (
              <div key={s.strategy} style={{ padding: '4px 8px', fontSize: 10, color: '#ef4444', borderBottom: '1px solid var(--border)' }}>Strategy "{s.strategy}" has {s.wr}% WR on {s.trades} trades — review or pause</div>
            ))}
            {kpis.closed < 30 && <div style={{ padding: '4px 8px', fontSize: 10, color: 'var(--text3)', borderBottom: '1px solid var(--border)' }}>Sample size {kpis.closed} is below 30-trade gate minimum — need {30 - kpis.closed} more</div>}
            <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 6 }}>Insights derived from {closed.length} closed trades in the {timeRange} range across {acctFilter ? (ACCT_LABEL[acctFilter] ?? acctFilter) : 'all accounts'}</div>
          </div>
        </>
      )}

      {/* ════════ LESSONS TAB ════════ */}
      {tab === 'Lessons' && (() => {
        // Handle double-wrapped response: { ok, data: { lessons: [...] } }
        const rawLessons = lessonsData?.lessons ?? lessonsData?.data?.lessons ?? []
        const lessonCount = lessonsData?.count ?? lessonsData?.data?.count ?? rawLessons.length
        const catColor: Record<string, string> = {
          exit_discipline: '#22c55e', stop_quality: '#f59e0b', entry_timing: '#ef4444',
          data_quality: '#60a5fa', broker_sync: '#a855f7', manual_intervention: '#06b6d4', unknown: 'var(--text3)',
        }
        const confIcon: Record<string, string> = { positive: '+', negative: '-', neutral: '~' }
        return (
          <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 12 }}>
              <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)' }}>Trade Lessons ({lessonCount})</div>
              <span style={{ fontSize: 9, color: 'var(--text3)' }}>Source: /api/v2/journal/closed-trades/lessons</span>
            </div>
            {rawLessons.length === 0 ? <div style={{ color: 'var(--text3)', fontSize: 11 }}>No lessons recorded yet</div> :
            rawLessons.map((l: any, i: number) => {
              const cat = l.lesson_category ?? 'unknown'
              const cc = catColor[cat] ?? 'var(--text3)'
              const lesson = l.improved_lesson ?? l.lesson_text ?? l.summary ?? ''
              const rule = l.rule_feedback ?? ''
              const conf = l.confidence_delta ?? 'neutral'
              return (
                <div key={i} onClick={() => onDrill({ title: `${l.symbol} — ${cat}`, subtitle: `${l.strategy ?? ''} · confidence: ${conf}`, endpoint: '/api/v2/journal/closed-trades/lessons', rows: [l] })}
                  style={{ padding: '10px 12px', marginBottom: 6, background: 'var(--bg2)', borderRadius: 8, borderLeft: `3px solid ${cc}`, cursor: 'pointer' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                    <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                      <span style={{ fontWeight: 700, color: 'var(--text0)', fontFamily: 'monospace', fontSize: 12 }}>{l.symbol}</span>
                      <span style={{ fontSize: 9, padding: '1px 6px', borderRadius: 3, background: `${cc}20`, color: cc, fontWeight: 600 }}>{cat.replace(/_/g, ' ')}</span>
                      <span style={{ fontSize: 9, color: 'var(--text3)' }}>{l.strategy}</span>
                    </div>
                    <span style={{ fontSize: 10, fontWeight: 700, color: conf === 'positive' ? '#22c55e' : conf === 'negative' ? '#ef4444' : 'var(--text3)' }}>
                      {confIcon[conf] ?? '~'} {conf}
                    </span>
                  </div>
                  <div style={{ fontSize: 11, color: 'var(--text1)', lineHeight: 1.4, marginBottom: rule ? 4 : 0 }}>{lesson}</div>
                  {rule && <div style={{ fontSize: 10, color: '#f59e0b', fontStyle: 'italic', lineHeight: 1.3 }}>Rule: {rule}</div>}
                </div>
              )
            })}
          </div>
        )
      })()}

      {/* ════════ PROTECTION TAB ════════ */}
      {tab === 'Protection' && <ProtectionOutcomesPanel onDrill={onDrill} />}

      {/* ════════ BACKTESTING TAB (v2 port via shared v3 BacktestPanel) — driven by the shared account + time-range filters ════════ */}
      {tab === 'Backtesting' && <BacktestPanel onDrill={onDrill} sharedAccount={acctFilter} sharedDateFrom={cutoff} />}
    </div>
  )
}
