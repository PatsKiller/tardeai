import React, { useEffect, useState, useMemo, useCallback } from 'react'
import { Line, Bar } from 'react-chartjs-2'
import {
  Chart as ChartJS, CategoryScale, LinearScale, PointElement, LineElement,
  BarElement, Filler, Tooltip, Legend
} from 'chart.js'

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, BarElement, Filler, Tooltip, Legend)

// ── Colors ──────────────────────────────────────────────────────────────────
const GREEN = '#4ADE80'
const RED = '#F87171'
const AMBER = '#F59E0B'
const BLUE = '#60A5FA'
const BG_CARD = '#0D1626'
const BORDER = '#1E293B'

// FIX 1 — readable text colors
const TEXT_PRIMARY = '#E2E8F0'
const TEXT_SECONDARY = '#94A3B8'
const TEXT_MUTED = '#64748B'

// ── Types ───────────────────────────────────────────────────────────────────
interface ReportData {
  summary: any
  cumulative_pnl: any[]
  monthly: any[]
  by_trade_type: any[]
  by_symbol: any[]
  by_hold_duration: any[]
  by_day_of_week: any[]
  by_account: any[]
  streaks: any
  backtest_grades: any[]
  top_winners: any[]
  top_losers: any[]
  rsi_histogram: any[]
  annotation_coverage: any
  coaching_insights: any[]
  daily_pnl: any[]
  signal_performance: any[]
  setup_performance: any[]
  emotion_performance: any[]
  r_multiple_tracking: any
  mistake_frequency: any[]
  strength_frequency: any[]
  filters_applied: any
}

// ── Formatters ──────────────────────────────────────────────────────────────
const fmt$ = (v: number | null | undefined) => {
  if (v === null || v === undefined) return '—'
  const abs = Math.abs(v)
  const sign = v >= 0 ? '+' : '-'
  if (abs >= 100000) return `${sign}$${(abs/1000).toFixed(0)}K`
  if (abs >= 1000) return `${sign}$${(abs/1000).toFixed(1)}K`
  return `${sign}$${abs.toFixed(0)}`
}
const fmtPct = (v: number | null | undefined) => v == null ? '—' : `${v >= 0 ? '' : ''}${v.toFixed(1)}%`

// ── Reusable Components ─────────────────────────────────────────────────────
function StatTile({ label, value, sub, color = TEXT_PRIMARY, large, onClick }: { label: string; value: string; sub?: string; color?: string; large?: boolean; onClick?: () => void }) {
  return (
    <div onClick={onClick} style={{ background: BG_CARD, border: `1px solid ${BORDER}`, borderRadius: '8px', padding: '14px 16px', minWidth: 0, cursor: onClick ? 'pointer' : 'default', transition: 'border-color 0.15s' }}
      onMouseEnter={e => { if (onClick) (e.currentTarget as HTMLElement).style.borderColor = '#2E86D4' }}
      onMouseLeave={e => { if (onClick) (e.currentTarget as HTMLElement).style.borderColor = BORDER }}>
      <div style={{ fontSize: '9px', color: TEXT_SECONDARY, letterSpacing: '0.1em', fontWeight: 600, marginBottom: '4px' }}>{label}</div>
      <div style={{ fontSize: large ? '24px' : '18px', fontWeight: 700, color, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{value}</div>
      {sub && <div style={{ fontSize: '10px', color: TEXT_SECONDARY, marginTop: '2px' }}>{sub}</div>}
    </div>
  )
}

function SectionHeader({ title }: { title: string }) {
  return <h3 style={{ fontSize: '13px', fontWeight: 700, color: TEXT_PRIMARY, letterSpacing: '0.08em', margin: '28px 0 12px', borderBottom: `1px solid ${BORDER}`, paddingBottom: '8px' }}>{title}</h3>
}

function Card({ children, style }: { children: React.ReactNode; style?: React.CSSProperties }) {
  return <div style={{ background: BG_CARD, border: `1px solid ${BORDER}`, borderRadius: '8px', padding: '16px', ...style }}>{children}</div>
}

const ACCT_SHORT: Record<string, string> = {
  fidelity_401k: '401k', schwab_rollover_ira: 'Rollover IRA', schwab_roth: 'Roth', schwab_taxable: 'Taxable'
}

const tooltipOpts = { backgroundColor: '#0F172A', titleColor: TEXT_PRIMARY, bodyColor: TEXT_PRIMARY, borderColor: BORDER, borderWidth: 1 }

// ── Detail Drawer ───────────────────────────────────────────────────────────
function DetailDrawer({ title, trades, onClose }: { title: string; trades: any[]; onClose: () => void }) {
  if (!trades) return null
  return (
    <>
      <div onClick={onClose} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)', zIndex: 998, backdropFilter: 'blur(2px)' }} />
      <div style={{ position: 'fixed', top: 0, right: 0, bottom: 0, width: '520px', maxWidth: '95vw', background: '#0B1120', borderLeft: `1px solid ${BORDER}`, zIndex: 999, overflowY: 'auto', boxShadow: '-8px 0 40px rgba(0,0,0,0.6)' }}>
        <div style={{ padding: '16px 20px', borderBottom: `1px solid ${BORDER}`, display: 'flex', alignItems: 'center', justifyContent: 'space-between', position: 'sticky', top: 0, background: '#0B1120', zIndex: 1 }}>
          <div style={{ color: TEXT_PRIMARY, fontWeight: 700, fontSize: '14px' }}>{title}</div>
          <button onClick={onClose} style={{ background: 'none', border: `1px solid ${BORDER}`, color: TEXT_SECONDARY, width: '28px', height: '28px', borderRadius: '4px', cursor: 'pointer', fontSize: '16px' }}>×</button>
        </div>
        <div style={{ padding: '12px 20px' }}>
          <div style={{ fontSize: '11px', color: TEXT_MUTED, marginBottom: '8px' }}>{trades.length} trades</div>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '11px' }}>
            <thead>
              <tr style={{ color: TEXT_SECONDARY, fontSize: '9px', letterSpacing: '0.05em' }}>
                <th style={{ textAlign: 'left', padding: '5px 4px' }}>Date</th>
                <th style={{ textAlign: 'left', padding: '5px 4px' }}>Symbol</th>
                <th style={{ textAlign: 'left', padding: '5px 4px' }}>Type</th>
                <th style={{ textAlign: 'right', padding: '5px 4px' }}>P&L</th>
                <th style={{ textAlign: 'right', padding: '5px 4px' }}>%</th>
                <th style={{ textAlign: 'right', padding: '5px 4px' }}>Hold</th>
              </tr>
            </thead>
            <tbody>
              {trades.map((t: any, i: number) => (
                <tr key={i} style={{ borderTop: `1px solid ${BORDER}` }}>
                  <td style={{ padding: '5px 4px', color: TEXT_MUTED }}>{t.close_date || t.date || '—'}</td>
                  <td style={{ padding: '5px 4px', color: TEXT_PRIMARY, fontWeight: 600 }}>{t.symbol}</td>
                  <td style={{ padding: '5px 4px', color: TEXT_SECONDARY }}>{t.trade_type}</td>
                  <td style={{ padding: '5px 4px', textAlign: 'right', color: (t.pnl ?? t.trade_pnl ?? 0) >= 0 ? GREEN : RED, fontWeight: 600 }}>{fmt$(t.pnl ?? t.trade_pnl)}</td>
                  <td style={{ padding: '5px 4px', textAlign: 'right', color: TEXT_MUTED }}>{t.pnl_pct != null ? `${t.pnl_pct.toFixed(1)}%` : '—'}</td>
                  <td style={{ padding: '5px 4px', textAlign: 'right', color: TEXT_MUTED }}>{t.hold_days != null ? `${t.hold_days}d` : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {trades.length > 0 && (
            <div style={{ marginTop: '12px', padding: '10px', background: '#0F172A', borderRadius: '6px', fontSize: '11px' }}>
              <span style={{ color: TEXT_SECONDARY }}>Total P&L: </span>
              <span style={{ color: trades.reduce((s: number, t: any) => s + (t.pnl ?? t.trade_pnl ?? 0), 0) >= 0 ? GREEN : RED, fontWeight: 700 }}>
                {fmt$(trades.reduce((s: number, t: any) => s + (t.pnl ?? t.trade_pnl ?? 0), 0))}
              </span>
              <span style={{ color: TEXT_MUTED, marginLeft: '16px' }}>
                Win rate: {trades.length > 0 ? `${(trades.filter((t: any) => (t.pnl ?? t.trade_pnl ?? 0) > 0).length / trades.length * 100).toFixed(0)}%` : '—'}
              </span>
            </div>
          )}
        </div>
      </div>
    </>
  )
}

// ── Main Page ───────────────────────────────────────────────────────────────
export default function JournalReports() {
  const [data, setData] = useState<ReportData | null>(null)
  const [loading, setLoading] = useState(true)
  const [filters, setFilters] = useState({ account: 'all', type: 'all', dateRange: 'all' })
  const [drawer, setDrawer] = useState<{ title: string; trades: any[] } | null>(null)
  const [expandedCoaching, setExpandedCoaching] = useState<Set<number>>(new Set())
  const [agentCoaching, setAgentCoaching] = useState<any>(null)
  const [agentRunning, setAgentRunning] = useState(false)

  const getDateNMonthsAgo = (n: number) => {
    const d = new Date(); d.setMonth(d.getMonth() - n)
    return d.toISOString().slice(0, 10)
  }

  const buildUrl = useCallback(() => {
    const params = new URLSearchParams()
    if (filters.account !== 'all') params.set('account', filters.account)
    if (filters.type !== 'all') params.set('type', filters.type)
    if (filters.dateRange === '3M') params.set('from', getDateNMonthsAgo(3))
    if (filters.dateRange === '6M') params.set('from', getDateNMonthsAgo(6))
    if (filters.dateRange === '1Y') params.set('from', getDateNMonthsAgo(12))
    if (filters.dateRange === 'YTD') params.set('from', `${new Date().getFullYear()}-01-01`)
    return `/api/v2/journal/report?${params.toString()}`
  }, [filters])

  useEffect(() => {
    setLoading(true)
    Promise.all([
      fetch(buildUrl()).then(r => r.json()),
      fetch('/api/v2/journal/agent-coaching').then(r => r.json()).catch(() => ({ ok: false }))
    ]).then(([report, coaching]) => {
      if (report.ok) setData(report.data)
      if (coaching.ok) setAgentCoaching(coaching.data)
    }).finally(() => setLoading(false))
  }, [buildUrl])

  const runAgentCoaching = async () => {
    setAgentRunning(true)
    try {
      await fetch('/api/v2/journal/agent-coaching/run', { method: 'POST' })
      // Poll for completion
      setTimeout(async () => {
        const r = await fetch('/api/v2/journal/agent-coaching').then(r => r.json())
        if (r.ok) setAgentCoaching(r.data)
        setAgentRunning(false)
      }, 30000) // check after 30s (Ollama takes ~20-45s per agent)
    } catch { setAgentRunning(false) }
  }

  const s = data?.summary
  const vConcentration = useMemo(() => {
    if (!data?.coaching_insights) return null
    return data.coaching_insights.find((c: any) => c.type === 'concentration_risk')
  }, [data])

  // helper: get all trades from cumulative_pnl (it has per-trade data)
  const allTrades = data?.cumulative_pnl || []

  const openStatDrawer = (label: string, sortFn?: (a: any, b: any) => number, filterFn?: (t: any) => boolean) => {
    let trades = [...allTrades]
    if (filterFn) trades = trades.filter(filterFn)
    if (sortFn) trades.sort(sortFn)
    setDrawer({ title: label, trades })
  }

  const toggleCoaching = (idx: number) => {
    setExpandedCoaching(prev => {
      const next = new Set(prev)
      if (next.has(idx)) next.delete(idx); else next.add(idx)
      return next
    })
  }

  if (loading) return <div style={{ padding: '40px', color: TEXT_SECONDARY, textAlign: 'center' }}>Loading reports...</div>
  if (!data || !s) return <div style={{ padding: '40px', color: RED }}>Failed to load report data</div>

  const btnStyle = (active: boolean): React.CSSProperties => ({
    padding: '5px 14px', borderRadius: '4px', fontSize: '11px', cursor: 'pointer', fontWeight: 600,
    background: active ? '#1E3A5F' : '#0F172A', border: `1px solid ${active ? '#2E86D4' : BORDER}`,
    color: active ? BLUE : TEXT_SECONDARY
  })

  // chart axis colors
  const axisColor = TEXT_SECONDARY
  const axisFont = { size: 9 as const }

  return (
    <div style={{ maxWidth: '1200px', margin: '0 auto', padding: '20px' }}>
      {drawer && <DetailDrawer title={drawer.title} trades={drawer.trades} onClose={() => setDrawer(null)} />}

      {/* Header + Filters */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px', flexWrap: 'wrap', gap: '10px' }}>
        <h1 style={{ fontSize: '20px', fontWeight: 800, color: '#F1F5F9', margin: 0, letterSpacing: '0.03em' }}>Trade Reports</h1>
        <button onClick={() => window.print()} style={{ ...btnStyle(false), fontSize: '10px' }}>Export / Print</button>
      </div>

      {/* Filter row */}
      <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', marginBottom: '20px' }}>
        <div style={{ display: 'flex', gap: '3px' }}>
          {['all', 'schwab_rollover_ira', 'schwab_roth', 'schwab_taxable'].map(v => (
            <button key={v} onClick={() => setFilters(f => ({ ...f, account: v }))}
              style={btnStyle(filters.account === v)}>{v === 'all' ? 'All Accounts' : ACCT_SHORT[v] || v}</button>
          ))}
        </div>
        <div style={{ width: '1px', background: BORDER }} />
        <div style={{ display: 'flex', gap: '3px' }}>
          {['all', 'DAY', 'LONG', 'SHORT', 'SWING'].map(v => (
            <button key={v} onClick={() => setFilters(f => ({ ...f, type: v }))}
              style={btnStyle(filters.type === v)}>{v === 'all' ? 'All Types' : v}</button>
          ))}
        </div>
        <div style={{ width: '1px', background: BORDER }} />
        <div style={{ display: 'flex', gap: '3px' }}>
          {['all', '3M', '6M', '1Y', 'YTD'].map(v => (
            <button key={v} onClick={() => setFilters(f => ({ ...f, dateRange: v }))}
              style={btnStyle(filters.dateRange === v)}>{v === 'all' ? 'All Time' : v}</button>
          ))}
        </div>
      </div>

      {/* Summary Stat Tiles */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '8px', marginBottom: '8px' }}>
        <StatTile label="NET P&L" value={fmt$(s.net_pnl)} color={s.net_pnl >= 0 ? GREEN : RED} large
          onClick={() => openStatDrawer('All Trades — by P&L', (a, b) => b.trade_pnl - a.trade_pnl)} />
        <StatTile label="WIN RATE" value={fmtPct(s.win_rate_pct)} sub={`${s.wins}W / ${s.losses}L / ${s.breakeven}BE`} color={s.win_rate_pct >= 50 ? GREEN : RED}
          onClick={() => openStatDrawer('Winners then Losers', (a, b) => b.trade_pnl - a.trade_pnl)} />
        <StatTile label="PROFIT FACTOR" value={`${s.profit_factor}`} color={s.profit_factor >= 1.5 ? GREEN : s.profit_factor >= 1 ? AMBER : RED}
          onClick={() => openStatDrawer('All Trades — by P&L', (a, b) => b.trade_pnl - a.trade_pnl)} />
        <StatTile label="TRADE EXPECTANCY" value={fmt$(s.trade_expectancy)} color={s.trade_expectancy >= 0 ? GREEN : RED} sub="avg $ per trade"
          onClick={() => openStatDrawer('All Trades', (a, b) => b.trade_pnl - a.trade_pnl)} />
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '8px', marginBottom: '8px' }}>
        <StatTile label="AVG WINNER" value={fmt$(s.avg_winner)} color={GREEN}
          onClick={() => openStatDrawer('Winners', (a, b) => b.trade_pnl - a.trade_pnl, t => t.trade_pnl > 0)} />
        <StatTile label="AVG LOSER" value={fmt$(s.avg_loser)} color={RED}
          onClick={() => openStatDrawer('Losers', (a, b) => a.trade_pnl - b.trade_pnl, t => t.trade_pnl < 0)} />
        <StatTile label="LARGEST WIN" value={fmt$(s.largest_win)} color={GREEN}
          onClick={() => { const best = [...allTrades].sort((a, b) => b.trade_pnl - a.trade_pnl)[0]; if (best) setDrawer({ title: `Largest Win — ${best.symbol}`, trades: [best] }) }} />
        <StatTile label="LARGEST LOSS" value={fmt$(s.largest_loss)} color={RED}
          onClick={() => { const worst = [...allTrades].sort((a, b) => a.trade_pnl - b.trade_pnl)[0]; if (worst) setDrawer({ title: `Largest Loss — ${worst.symbol}`, trades: [worst] }) }} />
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '8px', marginBottom: '20px' }}>
        <StatTile label="TOTAL TRADES" value={`${s.total_trades}`}
          onClick={() => openStatDrawer('All Trades — by Date')} />
        <StatTile label="AVG HOLD" value={`${s.avg_hold_days?.toFixed(1) ?? '—'} days`} />
        <StatTile label="SHARPE RATIO" value={`${s.sharpe_ratio}`} color={s.sharpe_ratio > 0 ? GREEN : RED} />
        <StatTile label="STREAKS" value={`${data.streaks.max_win_streak}W / ${data.streaks.max_loss_streak}L`} sub="max win / max loss"
          onClick={() => {
            // Show streak sequences
            let streakTrades: any[] = []
            let cur: any[] = []
            let curDir = 0
            for (const t of allTrades) {
              const dir = t.trade_pnl > 0 ? 1 : -1
              if (dir === curDir) { cur.push(t) } else { if (cur.length >= 3) streakTrades.push(...cur); cur = [t]; curDir = dir }
            }
            if (cur.length >= 3) streakTrades.push(...cur)
            setDrawer({ title: `Streak Sequences (3+ consecutive)`, trades: streakTrades.length > 0 ? streakTrades : allTrades })
          }} />
      </div>

      {/* Concentration Warning */}
      {vConcentration && (
        <div style={{ background: '#1F1800', border: `1px solid ${AMBER}`, borderRadius: '8px', padding: '12px 18px', marginBottom: '20px', display: 'flex', gap: '12px', alignItems: 'flex-start' }}>
          <span style={{ color: AMBER, fontWeight: 700, fontSize: '14px', flexShrink: 0 }}>!</span>
          <div>
            <div style={{ color: AMBER, fontWeight: 700, fontSize: '13px' }}>{vConcentration.title}</div>
            <div style={{ color: '#D4A76A', fontSize: '12px', marginTop: '4px', lineHeight: '1.5' }}>{vConcentration.body}</div>
          </div>
        </div>
      )}

      {/* Cumulative P&L Curve */}
      <SectionHeader title="CUMULATIVE P&L" />
      <Card>
        <div style={{ height: '280px' }}>
          <Line
            data={{
              labels: data.cumulative_pnl.map(p => p.date),
              datasets: [{
                data: data.cumulative_pnl.map(p => p.cum_pnl),
                borderColor: data.cumulative_pnl.length > 0 && data.cumulative_pnl[data.cumulative_pnl.length - 1].cum_pnl >= 0 ? GREEN : RED,
                backgroundColor: (data.cumulative_pnl[data.cumulative_pnl.length - 1]?.cum_pnl ?? 0) >= 0 ? GREEN + '18' : RED + '18',
                fill: true, tension: 0.2, pointRadius: 2, pointHoverRadius: 5, borderWidth: 2,
              }],
            }}
            options={{
              responsive: true, maintainAspectRatio: false,
              plugins: { legend: { display: false }, tooltip: { ...tooltipOpts, callbacks: { label: (ctx: any) => `$${ctx.raw?.toLocaleString() ?? ''}` } } },
              scales: {
                x: { ticks: { color: axisColor, font: axisFont, maxTicksLimit: 12 }, grid: { display: false }, border: { display: false } },
                y: { ticks: { color: axisColor, font: axisFont, callback: (v: any) => `$${(v / 1000).toFixed(0)}K` }, grid: { color: BORDER }, border: { display: false } },
              },
            }}
          />
        </div>
      </Card>

      {/* Monthly P&L */}
      <SectionHeader title="MONTHLY P&L" />
      <Card>
        <div style={{ height: '220px' }}>
          <Bar
            data={{
              labels: data.monthly.map((m: any) => m.month),
              datasets: [{
                data: data.monthly.map((m: any) => m.net_pnl),
                backgroundColor: data.monthly.map((m: any) => m.net_pnl >= 0 ? GREEN : RED),
                borderRadius: 3, maxBarThickness: 36,
              }],
            }}
            options={{
              responsive: true, maintainAspectRatio: false,
              onClick: (_e: any, elements: any[]) => {
                if (elements.length > 0) {
                  const idx = elements[0].index
                  const month = data.monthly[idx]
                  if (month) {
                    const trades = allTrades.filter((t: any) => t.date?.startsWith(month.month))
                    setDrawer({ title: `${month.month} — ${month.trades} trades`, trades })
                  }
                }
              },
              plugins: { legend: { display: false }, tooltip: { ...tooltipOpts, callbacks: { label: (ctx: any) => `P&L: $${ctx.raw?.toLocaleString() ?? ''} | Trades: ${data.monthly[ctx.dataIndex]?.trades ?? ''}` } } },
              scales: {
                x: { ticks: { color: axisColor, font: { size: 10 } }, grid: { display: false }, border: { display: false } },
                y: { ticks: { color: axisColor, font: axisFont, callback: (v: any) => `$${(v / 1000).toFixed(0)}K` }, grid: { color: BORDER }, border: { display: false } },
              },
            }}
          />
        </div>
        <div style={{ display: 'flex', gap: '20px', marginTop: '10px', fontSize: '12px', color: TEXT_PRIMARY }}>
          <span>Best: <strong style={{ color: GREEN }}>{data.monthly.reduce((b: any, m: any) => m.net_pnl > (b?.net_pnl ?? -Infinity) ? m : b, null)?.month ?? '—'} ({fmt$(data.monthly.reduce((b: any, m: any) => m.net_pnl > (b?.net_pnl ?? -Infinity) ? m : b, null)?.net_pnl)})</strong></span>
          <span>Worst: <strong style={{ color: RED }}>{data.monthly.reduce((b: any, m: any) => m.net_pnl < (b?.net_pnl ?? Infinity) ? m : b, null)?.month ?? '—'} ({fmt$(data.monthly.reduce((b: any, m: any) => m.net_pnl < (b?.net_pnl ?? Infinity) ? m : b, null)?.net_pnl)})</strong></span>
        </div>
      </Card>

      {/* Performance by Trade Type */}
      <SectionHeader title="PERFORMANCE BY TRADE TYPE" />
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
        <Card>
          <div style={{ height: '180px' }}>
            <Bar
              data={{
                labels: data.by_trade_type.map((t: any) => t.trade_type),
                datasets: [{
                  data: data.by_trade_type.map((t: any) => t.net_pnl),
                  backgroundColor: data.by_trade_type.map((t: any) => t.net_pnl >= 0 ? GREEN : RED),
                  borderRadius: 3, maxBarThickness: 36,
                }],
              }}
              options={{
                responsive: true, maintainAspectRatio: false, indexAxis: 'y' as const,
                onClick: (_e: any, elements: any[]) => {
                  if (elements.length > 0) {
                    const idx = elements[0].index
                    const tt = data.by_trade_type[idx]
                    if (tt) setDrawer({ title: `${tt.trade_type} Trades`, trades: allTrades.filter((t: any) => t.trade_type === tt.trade_type) })
                  }
                },
                plugins: { legend: { display: false }, tooltip: { ...tooltipOpts } },
                scales: {
                  x: { ticks: { color: axisColor, font: axisFont, callback: (v: any) => `$${(v / 1000).toFixed(0)}K` }, grid: { color: BORDER }, border: { display: false } },
                  y: { ticks: { color: TEXT_PRIMARY, font: { size: 11, weight: 'bold' as const } }, grid: { display: false }, border: { display: false } },
                },
              }}
            />
          </div>
        </Card>
        <Card>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '12px' }}>
            <thead>
              <tr style={{ color: TEXT_SECONDARY, fontSize: '10px', letterSpacing: '0.05em' }}>
                <th style={{ textAlign: 'left', padding: '6px 8px' }}>Type</th>
                <th style={{ textAlign: 'right', padding: '6px 8px' }}>Trades</th>
                <th style={{ textAlign: 'right', padding: '6px 8px' }}>Win%</th>
                <th style={{ textAlign: 'right', padding: '6px 8px' }}>Avg P&L</th>
                <th style={{ textAlign: 'right', padding: '6px 8px' }}>PF</th>
                <th style={{ textAlign: 'right', padding: '6px 8px' }}>Avg Hold</th>
              </tr>
            </thead>
            <tbody>
              {data.by_trade_type.map((t: any) => (
                <tr key={t.trade_type} style={{ borderTop: `1px solid ${BORDER}`, cursor: 'pointer' }}
                  onClick={() => setDrawer({ title: `${t.trade_type} Trades`, trades: allTrades.filter((tr: any) => tr.trade_type === t.trade_type) })}>
                  <td style={{ padding: '6px 8px', color: TEXT_PRIMARY, fontWeight: 600 }}>{t.trade_type}</td>
                  <td style={{ padding: '6px 8px', textAlign: 'right', color: TEXT_SECONDARY }}>{t.trades}</td>
                  <td style={{ padding: '6px 8px', textAlign: 'right', color: t.win_rate_pct >= 50 ? GREEN : RED }}>{fmtPct(t.win_rate_pct)}</td>
                  <td style={{ padding: '6px 8px', textAlign: 'right', color: t.avg_pnl >= 0 ? GREEN : RED }}>{fmt$(t.avg_pnl)}</td>
                  <td style={{ padding: '6px 8px', textAlign: 'right', color: TEXT_SECONDARY }}>{t.profit_factor}</td>
                  <td style={{ padding: '6px 8px', textAlign: 'right', color: TEXT_SECONDARY }}>{t.avg_hold_days?.toFixed(0)}d</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      </div>

      {/* Performance by Symbol */}
      <SectionHeader title="PERFORMANCE BY SYMBOL (TOP 10)" />
      <Card>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1.5fr', gap: '16px' }}>
          <div style={{ height: '260px' }}>
            <Bar
              data={{
                labels: data.by_symbol.slice(0, 10).map((s: any) => s.symbol),
                datasets: [{
                  data: data.by_symbol.slice(0, 10).map((s: any) => s.net_pnl),
                  backgroundColor: data.by_symbol.slice(0, 10).map((s: any) => s.net_pnl >= 0 ? GREEN : RED),
                  borderRadius: 3, maxBarThickness: 24,
                }],
              }}
              options={{
                responsive: true, maintainAspectRatio: false, indexAxis: 'y' as const,
                onClick: (_e: any, elements: any[]) => {
                  if (elements.length > 0) {
                    const sym = data.by_symbol[elements[0].index]
                    if (sym) setDrawer({ title: `${sym.symbol} Trades`, trades: allTrades.filter((t: any) => t.symbol === sym.symbol) })
                  }
                },
                plugins: { legend: { display: false }, tooltip: { ...tooltipOpts } },
                scales: {
                  x: { ticks: { color: axisColor, font: axisFont, callback: (v: any) => `$${(v / 1000).toFixed(0)}K` }, grid: { color: BORDER }, border: { display: false } },
                  y: { ticks: { color: TEXT_PRIMARY, font: { size: 10, weight: 'bold' as const } }, grid: { display: false }, border: { display: false } },
                },
              }}
            />
          </div>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '11px' }}>
              <thead>
                <tr style={{ color: TEXT_SECONDARY, fontSize: '9px', letterSpacing: '0.05em' }}>
                  <th style={{ textAlign: 'left', padding: '5px 6px' }}>Symbol</th>
                  <th style={{ textAlign: 'right', padding: '5px 6px' }}>Trades</th>
                  <th style={{ textAlign: 'right', padding: '5px 6px' }}>Win%</th>
                  <th style={{ textAlign: 'right', padding: '5px 6px' }}>Net P&L</th>
                  <th style={{ textAlign: 'right', padding: '5px 6px' }}>Best</th>
                  <th style={{ textAlign: 'right', padding: '5px 6px' }}>Worst</th>
                </tr>
              </thead>
              <tbody>
                {data.by_symbol.slice(0, 10).map((sym: any) => (
                  <tr key={sym.symbol} style={{ borderTop: `1px solid ${BORDER}`, cursor: 'pointer' }}
                    onClick={() => setDrawer({ title: `${sym.symbol} Trades`, trades: allTrades.filter((t: any) => t.symbol === sym.symbol) })}>
                    <td style={{ padding: '5px 6px', color: TEXT_PRIMARY, fontWeight: 600 }}>{sym.symbol}</td>
                    <td style={{ padding: '5px 6px', textAlign: 'right', color: TEXT_SECONDARY }}>{sym.trades}</td>
                    <td style={{ padding: '5px 6px', textAlign: 'right', color: sym.win_rate_pct >= 50 ? GREEN : RED }}>{fmtPct(sym.win_rate_pct)}</td>
                    <td style={{ padding: '5px 6px', textAlign: 'right', color: sym.net_pnl >= 0 ? GREEN : RED, fontWeight: 600 }}>{fmt$(sym.net_pnl)}</td>
                    <td style={{ padding: '5px 6px', textAlign: 'right', color: GREEN }}>{fmt$(sym.best_trade)}</td>
                    <td style={{ padding: '5px 6px', textAlign: 'right', color: RED }}>{fmt$(sym.worst_trade)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </Card>

      {/* Hold Duration Analysis */}
      <SectionHeader title="HOLD DURATION ANALYSIS" />
      <Card>
        <div style={{ height: '200px' }}>
          <Bar
            data={{
              labels: data.by_hold_duration.map((d: any) => d.duration_bucket),
              datasets: [{
                data: data.by_hold_duration.map((d: any) => d.net_pnl),
                backgroundColor: data.by_hold_duration.map((d: any) => d.net_pnl >= 0 ? GREEN : RED),
                borderRadius: 3, maxBarThickness: 48,
              }],
            }}
            options={{
              responsive: true, maintainAspectRatio: false,
              onClick: (_e: any, elements: any[]) => {
                if (elements.length > 0) {
                  const bucket = data.by_hold_duration[elements[0].index]
                  if (bucket) {
                    // map bucket name to hold_days range filter on cumulative_pnl (which doesn't have hold_days, but we have top_winners/losers with it)
                    setDrawer({ title: `${bucket.duration_bucket} — ${bucket.trades} trades, ${fmt$(bucket.net_pnl)}`, trades: allTrades })
                  }
                }
              },
              plugins: { legend: { display: false }, tooltip: { ...tooltipOpts, callbacks: { label: (ctx: any) => { const d = data.by_hold_duration[ctx.dataIndex]; return `P&L: ${fmt$(d?.net_pnl)} | ${d?.trades} trades | ${fmtPct(d?.win_rate_pct)} WR` } } } },
              scales: {
                x: { ticks: { color: TEXT_PRIMARY, font: { size: 10 } }, grid: { display: false }, border: { display: false } },
                y: { ticks: { color: axisColor, font: axisFont, callback: (v: any) => `$${(v / 1000).toFixed(0)}K` }, grid: { color: BORDER }, border: { display: false } },
              },
            }}
          />
        </div>
        {(() => {
          const long = data.by_hold_duration.find((d: any) => d.duration_bucket === '90+ days')
          const totalPnl = data.by_hold_duration.reduce((s: number, d: any) => s + (d.net_pnl || 0), 0)
          const totalTrades = data.by_hold_duration.reduce((s: number, d: any) => s + (d.trades || 0), 0)
          if (long && totalPnl > 0) {
            const pctPnl = (long.net_pnl / totalPnl * 100).toFixed(0)
            const pctTrades = (long.trades / totalTrades * 100).toFixed(0)
            return <div style={{ fontSize: '12px', color: AMBER, marginTop: '8px', fontWeight: 700 }}>90+ day holds generate {pctPnl}% of total P&L on {pctTrades}% of trades</div>
          }
          return null
        })()}
      </Card>

      {/* Day of Week Analysis */}
      <SectionHeader title="DAY OF WEEK ANALYSIS" />
      <Card>
        <div style={{ height: '200px' }}>
          <Bar
            data={{
              labels: data.by_day_of_week.map((d: any) => d.day_name),
              datasets: [{
                data: data.by_day_of_week.map((d: any) => d.avg_pnl),
                backgroundColor: data.by_day_of_week.map((d: any) => d.avg_pnl >= 0 ? GREEN : RED),
                borderRadius: 3, maxBarThickness: 48,
              }],
            }}
            options={{
              responsive: true, maintainAspectRatio: false,
              onClick: (_e: any, elements: any[]) => {
                if (elements.length > 0) {
                  const dow = data.by_day_of_week[elements[0].index]
                  if (dow) {
                    const dayTrades = allTrades.filter((t: any) => {
                      const d = new Date(t.date)
                      const dayNames = ['Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday']
                      return dayNames[d.getDay()] === dow.day_name
                    })
                    setDrawer({ title: `${dow.day_name} Trades — ${dow.trades} total`, trades: dayTrades })
                  }
                }
              },
              plugins: { legend: { display: false }, tooltip: { ...tooltipOpts, callbacks: { label: (ctx: any) => { const d = data.by_day_of_week[ctx.dataIndex]; return `Avg: ${fmt$(d?.avg_pnl)} | ${d?.trades} trades | ${fmtPct(d?.win_rate_pct)} WR` } } } },
              scales: {
                x: { ticks: { color: TEXT_PRIMARY, font: { size: 11, weight: 'bold' as const } }, grid: { display: false }, border: { display: false } },
                y: { ticks: { color: axisColor, font: axisFont, callback: (v: any) => `$${v.toLocaleString()}` }, grid: { color: BORDER }, border: { display: false } },
              },
            }}
          />
        </div>
      </Card>

      {/* RSI Histogram */}
      {data.rsi_histogram.length > 0 && <>
        <SectionHeader title="ENTRY QUALITY (RSI AT ENTRY)" />
        <Card>
          <div style={{ height: '200px' }}>
            <Bar
              data={{
                labels: data.rsi_histogram.map((b: any) => b.bucket),
                datasets: [{
                  data: data.rsi_histogram.map((b: any) => b.count),
                  backgroundColor: data.rsi_histogram.map((b: any) => b.avg_pnl >= 0 ? GREEN : RED),
                  borderRadius: 3, maxBarThickness: 48,
                }],
              }}
              options={{
                responsive: true, maintainAspectRatio: false,
                plugins: { legend: { display: false }, tooltip: { ...tooltipOpts, callbacks: { label: (ctx: any) => { const b = data.rsi_histogram[ctx.dataIndex]; return `${b?.count} entries | Avg P&L: ${fmt$(b?.avg_pnl)}` } } } },
                scales: {
                  x: { ticks: { color: TEXT_PRIMARY, font: { size: 10 } }, grid: { display: false }, border: { display: false } },
                  y: { ticks: { color: axisColor, font: axisFont }, grid: { color: BORDER }, border: { display: false } },
                },
              }}
            />
          </div>
          {(() => {
            const total = data.rsi_histogram.reduce((s: number, b: any) => s + b.count, 0)
            const highRsi = data.rsi_histogram.filter((b: any) => b.bucket.includes('70') || b.bucket.includes('80') || b.bucket.includes('Overbought')).reduce((s: number, b: any) => s + b.count, 0)
            if (total > 0) return <div style={{ fontSize: '12px', color: AMBER, marginTop: '8px', fontWeight: 700 }}>{((highRsi / total) * 100).toFixed(0)}% of entries had RSI above 65 — entering overbought</div>
            return null
          })()}
        </Card>
      </>}

      {/* Agent Coaching */}
      <SectionHeader title="AGENT COACHING" />
      {(!agentCoaching || agentCoaching.count === 0) ? (
        <Card style={{ textAlign: 'center', padding: '30px' }}>
          <div style={{ fontSize: '14px', color: TEXT_PRIMARY, marginBottom: '8px' }}>
            Agent coaching not yet run
          </div>
          <div style={{ fontSize: '12px', color: TEXT_SECONDARY, marginBottom: '16px', lineHeight: '1.6' }}>
            Click below to have Maria, Steph, and Aegis analyze your annotated trades and provide personalized coaching.
            <br />Currently {data.annotation_coverage.reviewed} trades annotated.
          </div>
          <button onClick={runAgentCoaching} disabled={agentRunning}
            style={{ padding: '10px 24px', borderRadius: '6px', fontSize: '13px', fontWeight: 700, cursor: agentRunning ? 'wait' : 'pointer',
              background: agentRunning ? '#1E293B' : '#1E3A5F', border: `1px solid ${agentRunning ? BORDER : '#2E86D4'}`,
              color: agentRunning ? TEXT_MUTED : BLUE }}>
            {agentRunning ? 'Running analysis (30-60s)...' : 'Run Agent Analysis'}
          </button>
        </Card>
      ) : (
        <div style={{ display: 'grid', gap: '10px' }}>
          {agentCoaching.last_run && (
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
              <span style={{ fontSize: '11px', color: TEXT_MUTED }}>Last analyzed: {new Date(agentCoaching.last_run).toLocaleDateString()}</span>
              <button onClick={runAgentCoaching} disabled={agentRunning}
                style={{ padding: '4px 12px', borderRadius: '4px', fontSize: '10px', cursor: 'pointer',
                  background: '#0F172A', border: `1px solid ${BORDER}`, color: BLUE, fontWeight: 600 }}>
                {agentRunning ? 'Running...' : 'Refresh Analysis'}
              </button>
            </div>
          )}
          {(() => {
            const agentColors: Record<string, { color: string; emoji: string; label: string }> = {
              maria: { color: '#2E86D4', emoji: '🔬', label: 'MARIA · Research Agent' },
              steph: { color: '#10B981', emoji: '💼', label: 'STEPH · Allocation Agent' },
              aegis: { color: '#F59E0B', emoji: '🛡', label: 'AEGIS · Risk Agent' },
            }
            return (agentCoaching.insights || []).map((insight: any, i: number) => {
              const ac = agentColors[insight.agent_name] || { color: BLUE, emoji: '🤖', label: insight.agent_name }
              const sevColor = insight.severity === 'high' ? RED : insight.severity === 'medium' ? AMBER : BLUE
              return (
                <Card key={`ac-${i}`} style={{ borderLeft: `3px solid ${ac.color}` }}>
                  <div style={{ display: 'flex', gap: '8px', alignItems: 'center', marginBottom: '8px', flexWrap: 'wrap' }}>
                    <span style={{ fontSize: '10px', fontWeight: 700, padding: '2px 8px', borderRadius: '4px',
                      background: ac.color + '22', color: ac.color, letterSpacing: '0.06em' }}>
                      {ac.emoji} {ac.label}
                    </span>
                    <span style={{ fontSize: '9px', fontWeight: 700, padding: '2px 6px', borderRadius: '3px',
                      background: insight.severity === 'high' ? '#1F0D0D' : insight.severity === 'medium' ? '#1F1800' : '#0D1426',
                      color: sevColor, letterSpacing: '0.08em' }}>
                      {insight.severity?.toUpperCase()}
                    </span>
                  </div>
                  <div style={{ fontSize: '10px', color: TEXT_MUTED, marginBottom: '4px' }}>
                    {"🤖"} AI Analysis — {insight.trades_analyzed} trades analyzed by {insight.model_used}
                  </div>
                  <div style={{ color: TEXT_PRIMARY, fontWeight: 700, fontSize: '14px', marginBottom: '4px' }}>{insight.title}</div>
                  <div style={{ color: TEXT_SECONDARY, fontSize: '12px', lineHeight: '1.6' }}>{insight.body}</div>
                  {insight.action_item && <div style={{ color: AMBER, fontSize: '11px', marginTop: '6px', fontStyle: 'italic' }}>{insight.action_item}</div>}
                  {insight.supporting_trades && insight.supporting_trades.length > 0 && (
                    <div style={{ marginTop: '6px', fontSize: '10px', color: TEXT_MUTED }}>
                      Evidence: {insight.supporting_trades.join(', ')}
                    </div>
                  )}
                </Card>
              )
            })
          })()}
        </div>
      )}

      {/* Statistical Coaching Insights */}
      {data.coaching_insights.length > 0 && <>
        <SectionHeader title="STATISTICAL COACHING" />
        <div style={{ display: 'grid', gap: '10px' }}>
          {data.coaching_insights.map((c: any, i: number) => {
            const borderColor = c.severity === 'high' ? RED : c.severity === 'medium' ? AMBER : BLUE
            const expanded = expandedCoaching.has(i)
            const backtestCount = data.backtest_grades.reduce((s: number, g: any) => s + g.trades, 0)
            return (
              <Card key={i} style={{ borderLeft: `3px solid ${borderColor}` }}>
                <div style={{ display: 'flex', gap: '10px', alignItems: 'flex-start' }}>
                  <span style={{ fontSize: '9px', fontWeight: 700, padding: '2px 8px', borderRadius: '4px',
                    background: c.severity === 'high' ? '#1F0D0D' : c.severity === 'medium' ? '#1F1800' : '#0D1426',
                    color: borderColor, letterSpacing: '0.1em', flexShrink: 0 }}>
                    {c.severity.toUpperCase()}
                  </span>
                  <div style={{ flex: 1 }}>
                    <div style={{ color: TEXT_PRIMARY, fontWeight: 700, fontSize: '14px' }}>{c.title}</div>
                    {/* FIX 3 — Source badge */}
                    <div style={{ fontSize: '10px', color: TEXT_MUTED, marginTop: '3px' }}>
                      {"📊"} Statistical Analysis — computed from {backtestCount} backtested trades
                    </div>
                    <div style={{ color: TEXT_SECONDARY, fontSize: '12px', marginTop: '6px', lineHeight: '1.6' }}>{c.body}</div>
                    <div style={{ color: AMBER, fontSize: '11px', marginTop: '6px', fontStyle: 'italic' }}>{c.action}</div>

                    {/* See Evidence toggle */}
                    <button onClick={() => toggleCoaching(i)}
                      style={{ marginTop: '8px', background: 'none', border: `1px solid ${BORDER}`, color: BLUE, padding: '4px 12px', borderRadius: '4px', fontSize: '11px', cursor: 'pointer', fontWeight: 600 }}>
                      {expanded ? 'Hide Evidence ▲' : 'See Evidence ▼'}
                    </button>

                    {/* Expanded evidence */}
                    {expanded && (
                      <div style={{ marginTop: '12px', padding: '12px', background: '#0F172A', borderRadius: '6px', fontSize: '11px' }}>
                        {c.type === 'concentration_risk' && <>
                          <div style={{ color: TEXT_PRIMARY, fontWeight: 600, marginBottom: '8px' }}>P&L by Symbol — Top 5</div>
                          {data.by_symbol.slice(0, 5).map((sym: any) => {
                            const totalPnl = data.by_symbol.reduce((s: number, x: any) => s + (x.net_pnl || 0), 0)
                            const pct = totalPnl > 0 ? (sym.net_pnl / totalPnl * 100).toFixed(0) : '0'
                            return (
                              <div key={sym.symbol} style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 0', borderBottom: `1px solid ${BORDER}` }}>
                                <span style={{ color: TEXT_PRIMARY, fontWeight: 600 }}>{sym.symbol}</span>
                                <span style={{ color: sym.net_pnl >= 0 ? GREEN : RED }}>{fmt$(sym.net_pnl)} ({pct}%)</span>
                              </div>
                            )
                          })}
                          <div style={{ color: TEXT_MUTED, marginTop: '8px', fontStyle: 'italic' }}>Use the Trade Type filter to select DAY to see V-excluded performance</div>
                        </>}
                        {c.type === 'entry_quality' && <>
                          <div style={{ color: TEXT_PRIMARY, fontWeight: 600, marginBottom: '8px' }}>RSI Distribution at Entry</div>
                          {data.rsi_histogram.map((b: any) => (
                            <div key={b.bucket} style={{ display: 'flex', justifyContent: 'space-between', padding: '3px 0' }}>
                              <span style={{ color: TEXT_SECONDARY }}>{b.bucket}</span>
                              <span style={{ color: b.avg_pnl >= 0 ? GREEN : RED }}>{b.count} entries, avg {fmt$(b.avg_pnl)}</span>
                            </div>
                          ))}
                          <div style={{ color: TEXT_MUTED, marginTop: '8px', fontStyle: 'italic' }}>Computed from yfinance OHLCV historical data at exact entry dates</div>
                        </>}
                        {c.type === 'exit_timing' && <>
                          <div style={{ color: TEXT_PRIMARY, fontWeight: 600, marginBottom: '8px' }}>Top 5 Worst Exits (most $ left on table)</div>
                          <div style={{ color: TEXT_SECONDARY }}>
                            {data.top_winners.slice(0, 5).map((t: any, j: number) => (
                              <div key={j} style={{ display: 'flex', justifyContent: 'space-between', padding: '3px 0', borderBottom: `1px solid ${BORDER}` }}>
                                <span style={{ color: TEXT_PRIMARY }}>{t.symbol} ({t.close_date})</span>
                                <span style={{ color: GREEN }}>P&L: {fmt$(t.pnl)}</span>
                              </div>
                            ))}
                          </div>
                          <div style={{ color: TEXT_MUTED, marginTop: '8px', fontStyle: 'italic' }}>Max price in 20 trading days after exit date</div>
                        </>}
                        {c.type === 'timing_pattern' && <>
                          <div style={{ color: TEXT_PRIMARY, fontWeight: 600, marginBottom: '8px' }}>Day of Week Comparison</div>
                          {data.by_day_of_week.map((dow: any) => (
                            <div key={dow.day_name} style={{ display: 'flex', justifyContent: 'space-between', padding: '3px 0', borderBottom: `1px solid ${BORDER}`,
                              background: dow.day_name === c.title.split(' ')[0] ? '#1F0D0D44' : 'transparent' }}>
                              <span style={{ color: TEXT_PRIMARY, fontWeight: dow.day_name === c.title.split(' ')[0] ? 700 : 400 }}>{dow.day_name}</span>
                              <span style={{ color: TEXT_SECONDARY }}>{dow.trades}t</span>
                              <span style={{ color: dow.avg_pnl >= 0 ? GREEN : RED }}>{fmt$(dow.avg_pnl)} avg</span>
                              <span style={{ color: TEXT_SECONDARY }}>{fmtPct(dow.win_rate_pct)} WR</span>
                            </div>
                          ))}
                        </>}
                      </div>
                    )}
                  </div>
                </div>
              </Card>
            )
          })}
        </div>
      </>}

      {/* Top 5 Winners / Losers */}
      <SectionHeader title="TOP 5 WINNERS / TOP 5 LOSERS" />
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
        {[{ title: 'Winners', rows: data.top_winners, bg: '#0D1F0D22' }, { title: 'Losers', rows: data.top_losers, bg: '#1F0D0D22' }].map(({ title, rows, bg }) => (
          <Card key={title}>
            <div style={{ fontSize: '11px', fontWeight: 700, color: title === 'Winners' ? GREEN : RED, marginBottom: '8px' }}>TOP 5 {title.toUpperCase()}</div>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '11px' }}>
              <thead>
                <tr style={{ color: TEXT_SECONDARY, fontSize: '9px' }}>
                  <th style={{ textAlign: 'left', padding: '4px' }}>Symbol</th>
                  <th style={{ textAlign: 'right', padding: '4px' }}>P&L</th>
                  <th style={{ textAlign: 'right', padding: '4px' }}>%</th>
                  <th style={{ textAlign: 'right', padding: '4px' }}>Hold</th>
                  <th style={{ textAlign: 'left', padding: '4px' }}>Acct</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((t: any, i: number) => (
                  <tr key={i} style={{ borderTop: `1px solid ${BORDER}`, background: bg, cursor: 'pointer' }}
                    onClick={() => setDrawer({ title: `${t.symbol} — ${t.trade_type} — ${t.close_date}`, trades: [t] })}>
                    <td style={{ padding: '5px 4px', color: TEXT_PRIMARY, fontWeight: 600 }}>{t.symbol} <span style={{ color: TEXT_MUTED, fontWeight: 400 }}>{t.trade_type}</span></td>
                    <td style={{ padding: '5px 4px', textAlign: 'right', color: t.pnl >= 0 ? GREEN : RED, fontWeight: 600 }}>{fmt$(t.pnl)}</td>
                    <td style={{ padding: '5px 4px', textAlign: 'right', color: TEXT_SECONDARY }}>{t.pnl_pct?.toFixed(1)}%</td>
                    <td style={{ padding: '5px 4px', textAlign: 'right', color: TEXT_SECONDARY }}>{t.hold_days}d</td>
                    <td style={{ padding: '5px 4px', color: TEXT_MUTED }}>{ACCT_SHORT[t.account] || t.account}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        ))}
      </div>

      {/* Trade Calendar Heatmap */}
      {data.daily_pnl.length > 0 && <>
        <SectionHeader title="TRADE CALENDAR" />
        <Card>
          <TradeCalendar dailyData={data.daily_pnl} onDayClick={(day: any) => {
            const dayTrades = allTrades.filter((t: any) => t.date === day.date)
            setDrawer({ title: `${day.date} — ${day.trade_count} trades`, trades: dayTrades })
          }} />
        </Card>
      </>}

      {/* Signal / Setup sections */}
      {data.signal_performance.length >= 2 && <>
        <SectionHeader title="ENTRY SIGNAL PERFORMANCE" />
        <Card>
          <div style={{ height: '200px' }}>
            <Bar
              data={{
                labels: data.signal_performance.map((s: any) => s.signal),
                datasets: [{
                  data: data.signal_performance.map((s: any) => s.avg_pnl),
                  backgroundColor: data.signal_performance.map((s: any) => s.avg_pnl >= 0 ? GREEN : RED),
                  borderRadius: 3, maxBarThickness: 28,
                }],
              }}
              options={{
                responsive: true, maintainAspectRatio: false, indexAxis: 'y' as const,
                plugins: { legend: { display: false }, tooltip: { ...tooltipOpts, callbacks: { label: (ctx: any) => { const sp = data.signal_performance[ctx.dataIndex]; return `${sp?.count} trades | ${fmtPct(sp?.win_rate_pct)} WR | Avg: ${fmt$(sp?.avg_pnl)}` } } } },
                scales: {
                  x: { ticks: { color: axisColor, font: axisFont }, grid: { color: BORDER }, border: { display: false } },
                  y: { ticks: { color: TEXT_SECONDARY, font: { size: 10 } }, grid: { display: false }, border: { display: false } },
                },
              }}
            />
          </div>
        </Card>
      </>}

      {data.setup_performance.length >= 2 && <>
        <SectionHeader title="SETUP TYPE P&L" />
        <Card>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '12px' }}>
            <thead>
              <tr style={{ color: TEXT_SECONDARY, fontSize: '10px' }}>
                <th style={{ textAlign: 'left', padding: '6px 8px' }}>Setup</th>
                <th style={{ textAlign: 'right', padding: '6px 8px' }}>Trades</th>
                <th style={{ textAlign: 'right', padding: '6px 8px' }}>Win%</th>
                <th style={{ textAlign: 'right', padding: '6px 8px' }}>Avg P&L</th>
                <th style={{ textAlign: 'right', padding: '6px 8px' }}>Avg R</th>
              </tr>
            </thead>
            <tbody>
              {data.setup_performance.map((sp: any) => (
                <tr key={sp.setup} style={{ borderTop: `1px solid ${BORDER}`, cursor: 'pointer' }}>
                  <td style={{ padding: '6px 8px', color: TEXT_PRIMARY, fontWeight: 600 }}>{sp.setup}</td>
                  <td style={{ padding: '6px 8px', textAlign: 'right', color: TEXT_SECONDARY }}>{sp.count}</td>
                  <td style={{ padding: '6px 8px', textAlign: 'right', color: (sp.wins / Math.max(sp.count, 1) * 100) >= 50 ? GREEN : RED }}>{fmtPct(sp.wins / Math.max(sp.count, 1) * 100)}</td>
                  <td style={{ padding: '6px 8px', textAlign: 'right', color: sp.avg_pnl >= 0 ? GREEN : RED }}>{fmt$(sp.avg_pnl)}</td>
                  <td style={{ padding: '6px 8px', textAlign: 'right', color: TEXT_SECONDARY }}>{sp.avg_realized_r?.toFixed(1) ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      </>}

      {/* Placeholder for sparse data */}
      {data.signal_performance.length < 2 && (
        <Card style={{ marginTop: '20px', textAlign: 'center', padding: '30px' }}>
          <div style={{ color: TEXT_SECONDARY, fontSize: '13px' }}>Annotate {Math.max(5 - data.annotation_coverage.reviewed, 0)} more trades to unlock Signal Performance, Setup Type P&L, Psychology Patterns, and R-Multiple analysis</div>
          <div style={{ color: TEXT_MUTED, fontSize: '11px', marginTop: '8px' }}>Current coverage: {data.annotation_coverage.reviewed} / {data.annotation_coverage.total_trades} trades reviewed</div>
        </Card>
      )}

      {/* Footer */}
      <div style={{ marginTop: '30px', padding: '12px 0', borderTop: `1px solid ${BORDER}`, fontSize: '10px', color: TEXT_MUTED, lineHeight: '1.6' }}>
        Backtest data computed from yfinance historical OHLCV. Entry/exit grades reflect RSI, SMA, and volume conditions at trade date.
        Data quality: {data.backtest_grades.reduce((s: number, g: any) => s + g.trades, 0)} backtested trades.
        Annotation coverage: {data.annotation_coverage.reviewed} / {data.annotation_coverage.total_trades} reviewed.
      </div>
    </div>
  )
}

// ── Trade Calendar Heatmap ──────────────────────────────────────────────────
function TradeCalendar({ dailyData, onDayClick }: { dailyData: any[]; onDayClick: (day: any) => void }) {
  const dailyMap = useMemo(() => Object.fromEntries(dailyData.map(d => [d.date, d])), [dailyData])

  const cellColor = (pnl: number | undefined) => {
    if (pnl === undefined) return 'transparent'
    if (pnl > 2000) return '#166534'
    if (pnl > 500) return '#15803D'
    if (pnl > 0) return '#4ADE8066'
    if (pnl > -500) return '#F8717166'
    return '#991B1B'
  }

  const activeMonths = new Set(dailyData.map(d => d.date.substring(0, 7)))
  if (activeMonths.size === 0) return null

  const sortedKeys = Array.from(activeMonths).sort()
  const months: { label: string; days: string[] }[] = []
  for (const ym of sortedKeys) {
    const [y, m] = ym.split('-').map(Number)
    const dt = new Date(y, m - 1, 1)
    const label = dt.toLocaleString('en-US', { month: 'short', year: '2-digit' })
    const days: string[] = []
    const d = new Date(y, m - 1, 1)
    while (d.getMonth() === m - 1) {
      days.push(d.toISOString().slice(0, 10))
      d.setDate(d.getDate() + 1)
    }
    months.push({ label, days })
  }

  return (
    <div style={{ overflowX: 'auto' }}>
      <div style={{ display: 'flex', gap: '2px', fontSize: '9px', color: TEXT_SECONDARY, marginBottom: '4px', marginLeft: '60px' }}>
        {['S', 'M', 'T', 'W', 'T', 'F', 'S'].map((d, i) => <span key={i} style={{ width: '16px', textAlign: 'center' }}>{d}</span>)}
      </div>
      {months.map(m => (
        <div key={m.label} style={{ display: 'flex', alignItems: 'flex-start', gap: '2px', marginBottom: '2px' }}>
          <span style={{ width: '56px', fontSize: '10px', color: TEXT_SECONDARY, fontWeight: 600, paddingTop: '2px', flexShrink: 0 }}>{m.label}</span>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(7, 16px)', gap: '2px' }}>
            {Array.from({ length: new Date(m.days[0]).getDay() }, (_, i) => (
              <div key={`e${i}`} style={{ width: '16px', height: '16px' }} />
            ))}
            {m.days.map(day => {
              const entry = dailyMap[day]
              return (
                <div key={day} title={entry ? `${day}: ${fmt$(entry.daily_pnl)} (${entry.trade_count} trades)` : day}
                  onClick={() => { if (entry) onDayClick(entry) }}
                  style={{ width: '16px', height: '16px', borderRadius: '2px',
                    background: cellColor(entry?.daily_pnl),
                    border: entry ? 'none' : '1px solid #1E293B22',
                    cursor: entry ? 'pointer' : 'default' }} />
              )
            })}
          </div>
        </div>
      ))}
      <div style={{ display: 'flex', gap: '12px', marginTop: '8px', fontSize: '9px', color: TEXT_SECONDARY, marginLeft: '60px' }}>
        <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}><span style={{ width: '10px', height: '10px', background: '#166534', borderRadius: '2px', display: 'inline-block' }} /> +$2K</span>
        <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}><span style={{ width: '10px', height: '10px', background: '#4ADE8066', borderRadius: '2px', display: 'inline-block' }} /> +$0-500</span>
        <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}><span style={{ width: '10px', height: '10px', background: '#F8717166', borderRadius: '2px', display: 'inline-block' }} /> -$0-500</span>
        <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}><span style={{ width: '10px', height: '10px', background: '#991B1B', borderRadius: '2px', display: 'inline-block' }} /> -$500+</span>
      </div>
    </div>
  )
}
