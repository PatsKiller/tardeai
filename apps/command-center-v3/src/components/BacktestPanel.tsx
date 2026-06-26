import { useState, useEffect, useMemo, useCallback, useRef } from 'react'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Cell,
  ReferenceLine, ResponsiveContainer, LineChart, Line, AreaChart, Area,
} from 'recharts'
import type { DrillContext } from './DetailDrawer'

/* ------------------------------------------------------------------ *
 * v2 Backtesting page ported into the v3 Strategy → Backtest tab.
 * Read-only: no write/POST controls. v3 tokens + Recharts + drill→Drawer.
 * Default run-type = replay_trades (the real, differentiated data;
 * champion rows are seeded/uniform simulations).
 * ------------------------------------------------------------------ */

interface Props {
  onDrill: (ctx: DrillContext) => void
  /** Account + time-range filters owned by JournalHub, applied across all tabs.
   *  sharedAccount is a normalized account key (e.g. 'alpaca_paper', 'schwab_rollover_ira'),
   *  matching strategy_backtest_trades.account exactly; '' = all accounts.
   *  sharedDateFrom is the time-range cutoff (YYYY-MM-DD), fed to the backend start_date. */
  sharedAccount?: string
  sharedDateFrom?: string
}

interface BtStatus {
  datasets_total: number; runs_total: number; trades_total: number
  trades_filtered?: number; runs_filtered?: number; filters_active?: boolean
  classification_classified?: number; classification_total?: number; classification_unclassified?: number
  last_runs?: { strategy_backtester?: string | null; trade_backtest_engine?: string | null; llm_review?: string | null; edge_comparison?: string | null }
  last_run_overall?: string | null
}
interface BtRun { run_id: string; run_type: string; strategy_id: string; status: string; start_date: string; end_date: string }
interface BtResult {
  result_id: number; run_id: string; strategy_id: string; run_type: string
  simulated_trades: number; wins: number; losses: number; win_rate: number
  profit_factor: number; expectancy_r: number; total_pnl: number; avg_pnl: number
  avg_r_multiple: number; max_drawdown_pct: number; equity_curve_json: string | null
  equity_curve?: Array<{ date: string; value: number }>
}
interface BtTrade {
  simulated_trade_id: string; run_id: string; strategy_id: string; symbol: string
  trade_date?: string; entry_price: number; exit_price: number; pnl: number
  pnl_pct?: number; r_multiple: number; exit_reason: string; run_type?: string
}
interface MissedOpp {
  missed_opportunity_key: string; proposal_id: number; signal_id?: string | null; candidate_id?: string | null
  symbol: string; strategy: string; status: string; proposal_time: string
  entry: number | null; target: number | null; stop: number | null
  sim_pnl: number | null; sim_r: number | null; sim_exit_reason?: string | null
  sim_outcome_verdict: 'WIN' | 'LOSS' | 'BREAKEVEN' | 'MIXED' | 'NO_DATA'
  sim_verdict_source: string; duplicate_count: number
  win_count: number; loss_count: number; breakeven_count: number; dedupe_confidence: string
}
interface MissedSummary {
  raw_rows: number; deduped_rows: number; duplicates_removed: number
  would_win: number; would_lose: number; breakeven: number; mixed: number; no_data: number; pnl_left_on_table: number
}
interface MissedData {
  summary?: MissedSummary; rows?: MissedOpp[]
  // legacy (deduped-based) compat
  total_missed: number; would_win: number; would_lose: number
  pnl_left_on_table: number; opportunities: MissedOpp[]
}
interface TrailData { trades: any[]; strategy_recommendations: any[]; summary: { total_analyzed: number; strategies_analyzed: number; avg_improvement: number } }
interface BrokerAccount { broker: string; account_label: string }
interface FilterOptions { strategies: string[]; run_ids: string[]; run_types: string[]; brokers: string[]; accounts: string[]; broker_accounts: BrokerAccount[]; minDate: string; maxDate: string; data_quality_gaps: string[] }

const G = '#22c55e', R = '#ef4444', A = '#f59e0b', B = '#60a5fa', P = '#a855f7', C = '#06b6d4'

function wrColor(wr: number) { return wr >= 55 ? G : wr >= 35 ? A : R }
function scoreColor(s: number | null | undefined) { const v = Number(s ?? 0); return s == null ? 'var(--text3)' : v >= 70 ? G : v >= 45 ? A : R }
// trailing-optimization config is an object like {breakeven: 1.5} — never render it raw.
function cfgBE(c: any) { return c && typeof c === 'object' ? (c.breakeven ?? c.value ?? '') : (c ?? '') }
function cfgLabel(c: any) { const b = cfgBE(c); return b === '' || b == null ? '—' : `BE ${b}R` }
function verdictColor(v?: string) {
  const s = (v || '').toLowerCase()
  if (s.includes('high-quality') || s.includes('good entry')) return G
  if (s.includes('valid setup') || s.includes('salvage')) return '#86efac'
  if (s.includes('weak') || s.includes('invalid') || s.includes('chase')) return R
  return A
}
function fmt$(n: number | null | undefined) { const v = Number(n ?? 0); return (v >= 0 ? '+' : '-') + '$' + Math.abs(v).toFixed(2) }
function fmtR(n: number | null | undefined) { const v = Number(n ?? 0); return (v >= 0 ? '+' : '') + v.toFixed(2) + 'R' }
function safeStr(s: string | null | undefined, fallback = 'unknown') { return (s ?? fallback).replace(/_/g, ' ') }
function num(n: number | null | undefined) { return Number(n ?? 0) }
// Advisory data-trust tier → color (does NOT affect GO/WAIT; base-data quality only)
function trustColor(tier?: string) {
  return tier === 'excellent' ? '#22c55e' : tier === 'usable' ? '#60a5fa' : tier === 'advisory' ? '#f59e0b' : tier === 'untrusted' ? '#ef4444' : 'var(--text3)'
}
// map tab id -> data-quality scorecard key
const TRUST_TAB_KEY: Record<string, string> = { entry_quality: 'entry_quality', trade_eval: 'trade_eval', missed: 'missed', llm_reviews: 'llm_review_coverage' }
// Outcome supplied by backend `sim_outcome_verdict` (deduped by canonical proposal_id) — NOT derived
// from P&L sign in the UI. MIXED = the proposal's sim runs disagree (shown, not hidden).
function missedVerdictColor(v?: string) {
  if (v === 'WIN') return G
  if (v === 'LOSS') return R
  if (v === 'MIXED') return P
  if (v === 'BREAKEVEN') return A
  return 'var(--text3)'
}

function buildQS(params: Record<string, string>) {
  const parts = Object.entries(params).filter(([, v]) => v).map(([k, v]) => `${k}=${encodeURIComponent(v)}`)
  return parts.length ? '?' + parts.join('&') : ''
}

const card: React.CSSProperties = { background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }
const secTitle: React.CSSProperties = { fontSize: 11, fontWeight: 700, letterSpacing: '.06em', textTransform: 'uppercase', color: 'var(--text3)', marginBottom: 12 }
const selStyle: React.CSSProperties = { padding: '4px 8px', fontSize: 11, background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 5, color: 'var(--text1)', fontFamily: 'var(--mono)' }

const WrTooltip = ({ active, payload, label }: any) => {
  if (!active || !payload?.length) return null
  const d = payload[0]?.payload
  return (
    <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 8, padding: '10px 14px', fontSize: 12 }}>
      <div style={{ fontWeight: 600, marginBottom: 6, color: 'var(--text0)' }}>{safeStr(label)}</div>
      {d && <>
        <div style={{ color: wrColor(num(d.win_rate || d.wr)), fontWeight: 600 }}>{num(d.win_rate || d.wr).toFixed(1)}% win rate</div>
        {d.trades != null && <div style={{ color: 'var(--text2)' }}>n = {d.trades} trades</div>}
        {d.avg_r != null && <div style={{ color: 'var(--text2)' }}>avg R {fmtR(d.avg_r)}</div>}
        {d.total_pnl != null && <div style={{ color: num(d.total_pnl) >= 0 ? G : R }}>{fmt$(d.total_pnl)}</div>}
        <div style={{ color: 'var(--text3)', fontSize: 11, marginTop: 6 }}>Click to filter trades</div>
      </>}
    </div>
  )
}

type TabId = 'overview' | 'strategy' | 'trades' | 'missed' | 'results' | 'runs' | 'trailing' | 'mfe' | 'optimization' | 'llm_reviews' | 'entry_quality' | 'capture' | 'potential' | 'trade_eval'

export default function BacktestPanel({ onDrill, sharedAccount = '', sharedDateFrom = '' }: Props) {
  const [status, setStatus] = useState<BtStatus | null>(null)
  const [runs, setRuns] = useState<BtRun[]>([])
  const [results, setResults] = useState<BtResult[]>([])
  const [trades, setTrades] = useState<BtTrade[]>([])
  const [missed, setMissed] = useState<MissedData | null>(null)
  const [trailData, setTrailData] = useState<TrailData | null>(null)
  const [mfeData, setMfeData] = useState<any>(null)
  const [optData, setOptData] = useState<any>(null)
  const [llmReviewData, setLlmReviewData] = useState<any>(null)
  const [dataQuality, setDataQuality] = useState<any>(null)
  const [eqSummary, setEqSummary] = useState<any>(null)       // entry/exit grading summary
  const [eqAnalytics, setEqAnalytics] = useState<any>(null)   // rsi/coaching/best-worst
  const [liveReadiness, setLiveReadiness] = useState<any>(null) // live paper win-rates (edge decay)
  const [resultHistory, setResultHistory] = useState<any[]>([]) // potential-over-time (④)
  const [tradeEval, setTradeEval] = useState<any>(null)         // structured LLM evaluations
  const [setupAdvisory, setSetupAdvisory] = useState<any>(null) // setup-quality prior + advisories
  const [loading, setLoading] = useState(true)
  const [tab, setTab] = useState<TabId>('overview')
  const [selectedStrategy, setSelectedStrategy] = useState<string | null>(null)
  const [selectedResult, setSelectedResult] = useState<BtResult | null>(null)
  const [runFilter, setRunFilter] = useState('all')
  // Filters — account + dateFrom seed from JournalHub's shared filters so the
  // Backtesting tab honors the same account/time-range selection as every other tab.
  const [dateFrom, setDateFrom] = useState(sharedDateFrom)
  const [dateTo, setDateTo] = useState('')
  const [strategyFilter, setStrategyFilter] = useState('')
  const [runTypeFilter, setRunTypeFilter] = useState('replay_trades')  // default = real data
  const [brokerFilter, setBrokerFilter] = useState('')
  const [accountFilter, setAccountFilter] = useState(sharedAccount)
  const [filterOptions, setFilterOptions] = useState<FilterOptions>({ strategies: [], run_ids: [], run_types: [], brokers: [], accounts: [], broker_accounts: [], minDate: '', maxDate: '', data_quality_gaps: [] })

  const filtersActive = Boolean(dateFrom || dateTo || strategyFilter || runTypeFilter || brokerFilter || accountFilter)
  const mountedRef = useRef(false)

  const loadData = useCallback(async (f: { dateFrom: string; dateTo: string; strategy: string; runType: string; broker: string; account: string }) => {
    setLoading(true)
    const qs = buildQS({ start_date: f.dateFrom, end_date: f.dateTo, strategy: f.strategy, run_type: f.runType, broker: f.broker, account: f.account })
    const [st, ru, re, tr, mi, trail, fo] = await Promise.allSettled([
      fetch('/api/v2/backtesting/status' + qs).then(r => r.json()),
      fetch('/api/v2/backtesting/runs' + qs).then(r => r.json()),
      fetch('/api/v2/backtesting/results' + qs).then(r => r.json()),
      fetch('/api/v2/backtesting/trades' + qs).then(r => r.json()),
      fetch('/api/v2/backtesting/missed-opportunities' + qs).then(r => r.json()),
      fetch('/api/v2/backtesting/trailing-stop-analysis' + qs).then(r => r.json()).catch(() => ({ ok: false })),
      fetch('/api/v2/backtesting/filter-options').then(r => r.json()),
    ])
    if (st.status === 'fulfilled') setStatus(st.value.data ?? st.value)
    if (ru.status === 'fulfilled') setRuns(ru.value.data ?? [])
    if (re.status === 'fulfilled') {
      const raw: BtResult[] = re.value.data ?? []
      setResults(raw.map(r => ({
        ...r,
        equity_curve: (() => {
          if (!r.equity_curve_json) return []
          try { const p = typeof r.equity_curve_json === 'string' ? JSON.parse(r.equity_curve_json) : r.equity_curve_json; return Array.isArray(p) ? p : [] } catch { return [] }
        })(),
      })))
    }
    if (tr.status === 'fulfilled') setTrades(tr.value.data ?? [])
    if (mi.status === 'fulfilled' && mi.value.ok) setMissed(mi.value.data)
    if (trail.status === 'fulfilled' && (trail.value as any)?.ok) setTrailData((trail.value as any).data)
    if (fo.status === 'fulfilled' && fo.value?.ok && fo.value.data) {
      const fd = fo.value.data
      setFilterOptions({
        strategies: fd.strategies || [], run_ids: fd.run_ids || [], run_types: fd.run_types || [],
        brokers: fd.brokers || [], accounts: fd.accounts || [], broker_accounts: fd.broker_accounts || [],
        minDate: fd.minDate || '', maxDate: fd.maxDate || '', data_quality_gaps: fd.data_quality_gaps || [],
      })
    }
    try {
      const [mfe, opt, llm, eqs, eqa, live, hist, tev, adv, dq] = await Promise.allSettled([
        fetch('/api/v2/backtesting/mfe-analysis' + qs).then(r => r.json()),
        fetch('/api/v2/backtesting/trailing-optimization' + qs).then(r => r.json()),
        fetch('/api/v2/lifecycle/llm-review-status' + qs).then(r => r.json()),
        fetch('/api/v2/journal/backtest-summary' + qs).then(r => r.json()),
        fetch('/api/v2/journal/backtest-analytics' + qs).then(r => r.json()),
        fetch('/api/v2/paper-trade-readiness').then(r => r.json()),
        fetch('/api/v2/backtesting/result-history' + (f.runType ? `?run_type=${encodeURIComponent(f.runType)}` : '')).then(r => r.json()).catch(() => ({ ok: false })),
        fetch('/api/v2/backtesting/trade-evaluations' + qs).then(r => r.json()).catch(() => ({ ok: false })),
        fetch('/api/v2/atm/setup-advisory').then(r => r.json()).catch(() => ({ ok: false })),
        fetch('/api/v2/backtesting/data-quality').then(r => r.json()).catch(() => ({ ok: false })),
      ])
      if (dq.status === 'fulfilled' && dq.value?.ok) setDataQuality(dq.value.data)
      if (mfe.status === 'fulfilled' && mfe.value?.ok) setMfeData(mfe.value.data)
      if (opt.status === 'fulfilled' && opt.value?.ok) setOptData(opt.value.data)
      if (llm.status === 'fulfilled' && llm.value?.ok) setLlmReviewData(llm.value.data)
      if (eqs.status === 'fulfilled' && eqs.value?.ok) setEqSummary(eqs.value.data)
      if (eqa.status === 'fulfilled' && eqa.value?.ok) setEqAnalytics(eqa.value.data)
      if (live.status === 'fulfilled') setLiveReadiness(live.value?.data ?? live.value)
      if (hist.status === 'fulfilled' && (hist.value as any)?.ok) setResultHistory((hist.value as any).data ?? [])
      if (tev.status === 'fulfilled' && (tev.value as any)?.ok) setTradeEval((tev.value as any).data)
      if (adv.status === 'fulfilled' && (adv.value as any)?.ok) setSetupAdvisory((adv.value as any).data)
    } catch { /* lazy loads optional */ }
    setLoading(false)
  }, [])

  // Initial load honors the shared account + time-range seeded into state above.
  useEffect(() => { loadData({ dateFrom, dateTo: '', strategy: '', runType: 'replay_trades', broker: '', account: accountFilter }) }, [loadData])  // eslint-disable-line react-hooks/exhaustive-deps
  // Propagate JournalHub's shared filters → internal state (triggers the reload effect below).
  // Setting state to the same value (e.g. on mount) is a no-op, so no duplicate fetch.
  useEffect(() => { setAccountFilter(sharedAccount) }, [sharedAccount])
  useEffect(() => { setDateFrom(sharedDateFrom) }, [sharedDateFrom])
  useEffect(() => {
    if (!mountedRef.current) { mountedRef.current = true; return }
    loadData({ dateFrom, dateTo, strategy: strategyFilter, runType: runTypeFilter, broker: brokerFilter, account: accountFilter })
  }, [dateFrom, dateTo, strategyFilter, runTypeFilter, brokerFilter, accountFilter, loadData])

  const strategyStats = useMemo(() => {
    const m: Record<string, { n: number; wins: number; pnl: number; rs: number[] }> = {}
    trades.forEach(t => {
      const s = t.strategy_id
      if (!s || s === 'unknown') return
      if (!m[s]) m[s] = { n: 0, wins: 0, pnl: 0, rs: [] }
      m[s].n++
      if (num(t.pnl) > 0) m[s].wins++
      m[s].pnl += num(t.pnl)
      if (t.r_multiple != null) m[s].rs.push(num(t.r_multiple))
    })
    return Object.entries(m).map(([strategy, v]) => {
      const best = results.find(r => r.strategy_id === strategy)
      return {
        strategy, strategy_id: strategy, trades: v.n,
        win_rate: v.n > 0 ? Math.round(100 * v.wins / v.n) : 0,
        total_pnl: Math.round(v.pnl * 100) / 100,
        avg_r: v.rs.length > 0 ? Math.round(v.rs.reduce((a, b) => a + b, 0) / v.rs.length * 100) / 100 : 0,
        profit_factor: best?.profit_factor ?? null,
        expectancy_r: best?.expectancy_r ?? null,
        max_drawdown: best?.max_drawdown_pct ?? null,
      }
    }).sort((a, b) => b.win_rate - a.win_rate)
  }, [trades, results])

  const filteredTrades = useMemo(() => selectedStrategy ? trades.filter(t => t.strategy_id === selectedStrategy) : trades, [trades, selectedStrategy])

  const rBuckets = useMemo(() => {
    const src = selectedStrategy ? trades.filter(t => t.strategy_id === selectedStrategy) : trades
    return [
      { label: '<-2R', min: -99, max: -2 }, { label: '-2 to -1', min: -2, max: -1 },
      { label: '-1 to 0', min: -1, max: 0 }, { label: '0 to 1', min: 0, max: 1 },
      { label: '1 to 2', min: 1, max: 2 }, { label: '>2R', min: 2, max: 99 },
    ].map(b => ({ ...b, count: src.filter(t => t.r_multiple != null && num(t.r_multiple) > b.min && num(t.r_multiple) <= b.max).length }))
  }, [trades, selectedStrategy])

  const flagged = strategyStats.filter(s => s.win_rate < 35 && s.trades >= 3)

  const avgEvalScore = useMemo(() => {
    const xs = (tradeEval?.evaluations ?? []).map((e: any) => e.eval_overall_score).filter((n: any) => typeof n === 'number')
    return xs.length ? xs.reduce((a: number, b: number) => a + b, 0) / xs.length : null
  }, [tradeEval])

  // ① Cadence — derive run frequency from runs created_at (last 14 distinct days)
  const cadence = useMemo(() => {
    const days: Record<string, number> = {}
    let last = ''
    runs.forEach(r => {
      const ca = String((r as any).created_at || '').slice(0, 10)
      if (ca) { days[ca] = (days[ca] || 0) + 1; if (ca > last) last = ca }
    })
    const sorted = Object.entries(days).sort((a, b) => a[0] < b[0] ? -1 : 1).slice(-14)
    return { perDay: sorted.map(([d, n]) => ({ d: d.slice(5), n })), last }
  }, [runs])

  // Edge Decay — backtest WR (from trades) vs live paper WR (from readiness)
  const edgeDecay = useMemo(() => {
    const live: Record<string, number> = {}
    const liveN: Record<string, number> = {}
    for (const s of (liveReadiness?.top_strategies ?? [])) {
      if (s.closed > 0) { live[s.strategy] = s.win_rate; liveN[s.strategy] = s.closed }
    }
    return strategyStats
      .filter(s => live[s.strategy_id] != null)
      .map(s => ({ strategy: s.strategy_id, backtest_wr: s.win_rate, live_wr: live[s.strategy_id], live_n: liveN[s.strategy_id], gap: Math.round((live[s.strategy_id] - s.win_rate)) }))
      .sort((a, b) => a.gap - b.gap)
  }, [strategyStats, liveReadiness])

  // ② Left-on-table cumulative over time (from MFE trades, which carry trade context)
  const captureSeries = useMemo(() => {
    const ts = (mfeData?.trades ?? [])
      .filter((t: any) => t.money_left != null && (t.mfe_time || t.created_at))
      .map((t: any) => ({ date: String(t.mfe_time || t.created_at).slice(0, 10), left: num(t.money_left), symbol: t.symbol }))
      .sort((a: any, b: any) => a.date < b.date ? -1 : 1)
    let cum = 0
    return ts.map((p: any) => { cum += p.left; return { date: p.date.slice(5), cum: Math.round(cum), left: Math.round(p.left), symbol: p.symbol } })
  }, [mfeData])

  const handleStrategyClick = useCallback((data: any) => {
    const name = data?.activePayload?.[0]?.payload?.strategy_id ?? data?.strategy_id
    if (!name) return
    setSelectedStrategy(prev => prev === name ? null : name)
    setTab('trades')
  }, [])

  if (loading) return <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: 240, color: 'var(--text3)', fontSize: 12 }}>Loading backtest data…</div>

  const TABS: { id: TabId; label: string }[] = [
    { id: 'overview', label: 'Overview' },
    { id: 'entry_quality', label: `Entry Quality${eqSummary?.summary?.total ? ` (${eqSummary.summary.total})` : ''}` },
    { id: 'trade_eval', label: `AI Trade Eval${tradeEval?.evaluations?.length ? ` (${tradeEval.evaluations.length})` : ''}` },
    { id: 'capture', label: 'Capture' },
    { id: 'potential', label: 'Potential Over Time' },
    { id: 'strategy', label: `Strategy (${strategyStats.length})` },
    { id: 'trades', label: `Trades (${selectedStrategy ? filteredTrades.length : trades.length})` },
    { id: 'missed', label: `Missed (${missed?.total_missed ?? 0})` },
    { id: 'results', label: `Results (${results.length})` },
    { id: 'runs', label: `Runs (${runs.length})` },
    { id: 'trailing', label: `Trail Analysis (${trailData?.summary?.total_analyzed ?? 0})` },
    { id: 'mfe', label: `MFE/MAE (${mfeData?.trades?.length ?? 0})` },
    { id: 'optimization', label: `Optimization (${optData?.results?.length ?? 0})` },
    { id: 'llm_reviews', label: `LLM Review Coverage (${llmReviewData?.total_reviews ?? 0})` },
  ]

  const runTypeNote = runTypeFilter === 'replay_trades' ? 'Showing real trade replays.'
    : runTypeFilter === 'replay_proposals' ? 'Showing rejected/expired proposal replays.'
    : runTypeFilter === 'champion' ? 'Showing hypothetical champion simulations (seeded/uniform).'
    : runTypeFilter ? `Filtered to ${runTypeFilter}.` : 'Showing all sources (replay + champion).'

  return (
    <div>
      {/* ① Cadence & coverage strip */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginBottom: 12, padding: '8px 14px', background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 8 }}>
        <div style={{ flexShrink: 0 }}>
          <div style={{ fontSize: 9, color: 'var(--text3)', textTransform: 'uppercase', fontWeight: 700 }}>Backtest cadence</div>
          <div style={{ fontSize: 12, color: 'var(--text1)' }}>Daily 6 AM ET (active) · full sweep Sun 10 PM ET</div>
        </div>
        <div style={{ flexShrink: 0, borderLeft: '1px solid var(--border)', paddingLeft: 16 }}>
          <div style={{ fontSize: 9, color: 'var(--text3)', textTransform: 'uppercase', fontWeight: 700 }}>Last run (any pipeline)</div>
          <div style={{ fontSize: 12, color: G }} title={status?.last_runs ? Object.entries(status.last_runs).map(([k, v]) => `${k}: ${v ? String(v).slice(0, 16) : '—'}`).join('\n') : ''}>
            {(status?.last_run_overall ? String(status.last_run_overall).slice(0, 16) : (cadence.last || '—'))}
          </div>
          {status?.last_runs && (
            <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 1 }}>
              strat {status.last_runs.strategy_backtester ? String(status.last_runs.strategy_backtester).slice(5, 10) : '—'} · eng {status.last_runs.trade_backtest_engine ? String(status.last_runs.trade_backtest_engine).slice(5, 10) : '—'} · llm {status.last_runs.llm_review ? String(status.last_runs.llm_review).slice(5, 10) : '—'} · edge {status.last_runs.edge_comparison ? String(status.last_runs.edge_comparison).slice(5, 10) : '—'}
            </div>
          )}
        </div>
        <div style={{ flex: 1, minWidth: 120, height: 34 }}>
          <div style={{ fontSize: 9, color: 'var(--text3)', textTransform: 'uppercase', fontWeight: 700, marginBottom: -2 }}>Runs / day (14d)</div>
          <ResponsiveContainer width="100%" height={26}>
            <BarChart data={cadence.perDay} margin={{ top: 2, right: 0, bottom: 0, left: 0 }}>
              <Tooltip contentStyle={{ background: 'var(--bg1)', border: '1px solid var(--border)', fontSize: 10 }} cursor={{ fill: 'rgba(255,255,255,.04)' }} />
              <Bar dataKey="n" radius={[2, 2, 0, 0]} fill={B} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Context banner */}
      <div style={{ fontSize: 11, color: B, marginBottom: 12, padding: '8px 12px', background: 'rgba(96,165,250,.06)', border: '1px solid rgba(96,165,250,.15)', borderRadius: 6 }}>
        Backtesting rows are historical replays and champion simulations — not live broker orders. {runTypeNote}
      </div>

      {/* KPI tiles */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(7,1fr)', gap: 10, marginBottom: 14 }}>
        {[
          { label: 'Datasets', value: status?.datasets_total ?? 0 },
          { label: 'Runs', value: filtersActive ? `${status?.runs_filtered ?? 0} / ${status?.runs_total ?? 0}` : (status?.runs_total ?? 0) },
          { label: 'Backtest Rows', value: filtersActive ? `${trades.length.toLocaleString()} / ${(status?.trades_total ?? 0).toLocaleString()}` : (status?.trades_total ?? 0).toLocaleString() },
          { label: 'Results', value: results.length },
          { label: 'Strategy Coverage', value: `${(status?.classification_classified ?? 0).toLocaleString()} / ${(status?.classification_total ?? 0).toLocaleString()}`, accent: (status?.classification_unclassified ?? 0) > 0 },
          { label: 'Flagged', value: flagged.length, accent: flagged.length > 0 },
          { label: 'Missed', value: missed?.total_missed ?? 0 },
        ].map(k => (
          <div key={k.label} style={{ background: 'var(--bg1)', border: `1px solid ${(k as any).accent ? 'rgba(239,68,68,.4)' : 'var(--border)'}`, borderRadius: 8, padding: '12px 14px', textAlign: 'center' }}>
            <div style={{ fontSize: 22, fontWeight: 700, color: (k as any).accent ? R : 'var(--text0)' }}>{k.value}</div>
            <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 4 }}>{k.label}</div>
          </div>
        ))}
      </div>

      {/* Low-win-rate warning */}
      {flagged.length > 0 && (
        <div style={{ display: 'flex', gap: 10, padding: '10px 14px', marginBottom: 14, background: 'rgba(239,68,68,.08)', border: '1px solid rgba(239,68,68,.25)', borderRadius: 8, fontSize: 12, color: '#fca5a5' }}>
          <span style={{ color: R, fontWeight: 700 }}>⚠ Low backtest win rate</span>
          <span>{flagged.map(s => `${safeStr(s.strategy)} ${s.win_rate}%`).join('  ·  ')}</span>
        </div>
      )}

      {/* Selected-strategy chip */}
      {selectedStrategy && (
        <div style={{ display: 'inline-flex', alignItems: 'center', gap: 8, padding: '5px 12px', marginBottom: 12, background: 'rgba(168,85,247,.12)', border: '1px solid rgba(168,85,247,.35)', borderRadius: 20, fontSize: 12, color: '#d8b4fe' }}>
          <span>Drill-down: <strong>{safeStr(selectedStrategy)}</strong></span>
          <button onClick={() => setSelectedStrategy(null)} style={{ background: 'none', border: 'none', color: '#d8b4fe', cursor: 'pointer', fontSize: 14, padding: 0 }}>×</button>
        </div>
      )}

      {/* Filter bar */}
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 12, flexWrap: 'wrap' }}>
        <span style={{ fontSize: 9, color: 'var(--text3)', textTransform: 'uppercase', fontWeight: 700 }}>Filters</span>
        <input type="date" value={dateFrom} onChange={e => setDateFrom(e.target.value)} min={filterOptions.minDate} max={filterOptions.maxDate} style={selStyle} title="Start date" />
        <span style={{ fontSize: 10, color: 'var(--text3)' }}>to</span>
        <input type="date" value={dateTo} onChange={e => setDateTo(e.target.value)} min={filterOptions.minDate} max={filterOptions.maxDate} style={selStyle} title="End date" />
        <select value={brokerFilter} onChange={e => { setBrokerFilter(e.target.value); setAccountFilter('') }} style={selStyle}>
          <option value="">All Brokers</option>
          {filterOptions.brokers.map(b => <option key={b} value={b}>{b.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())}</option>)}
        </select>
        <select value={accountFilter} onChange={e => setAccountFilter(e.target.value)} style={selStyle}>
          <option value="">All Accounts</option>
          {(brokerFilter ? filterOptions.broker_accounts.filter(ba => ba.broker === brokerFilter).map(ba => ba.account_label) : filterOptions.accounts)
            .map(a => <option key={a} value={a}>{a.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())}</option>)}
        </select>
        <select value={strategyFilter} onChange={e => setStrategyFilter(e.target.value)} style={selStyle}>
          <option value="">All Strategies</option>
          {filterOptions.strategies.map(s => <option key={s} value={s}>{safeStr(s)}</option>)}
        </select>
        <select value={runTypeFilter} onChange={e => setRunTypeFilter(e.target.value)} style={selStyle}>
          <option value="">All Run Types</option>
          {filterOptions.run_types.map(t => <option key={t} value={t}>{safeStr(t)}</option>)}
        </select>
        {filtersActive && (
          <button onClick={() => { setDateFrom(''); setDateTo(''); setStrategyFilter(''); setRunTypeFilter(''); setBrokerFilter(''); setAccountFilter('') }}
            style={{ padding: '3px 8px', fontSize: 9, background: 'rgba(239,68,68,.1)', border: '1px solid rgba(239,68,68,.3)', borderRadius: 4, color: '#fca5a5', cursor: 'pointer' }}>Clear</button>
        )}
        {filtersActive && (
          <span style={{ fontSize: 10, color: 'var(--text3)' }}>
            Showing {trades.length.toLocaleString()} {runTypeFilter === 'replay_trades' ? 'replay-trade' : runTypeFilter === 'replay_proposals' ? 'replay-proposal' : runTypeFilter === 'champion' ? 'champion-sim' : 'backtest'} rows (of {(status?.trades_total ?? 0).toLocaleString()} total)
          </span>
        )}
      </div>

      {/* Data quality gaps */}
      {filterOptions.data_quality_gaps.length > 0 && filtersActive && (
        <div style={{ fontSize: 10, color: A, marginBottom: 12, padding: '6px 10px', background: 'rgba(245,158,11,.05)', border: '1px solid rgba(245,158,11,.15)', borderRadius: 4 }}>
          {filterOptions.data_quality_gaps.map((g, i) => <div key={i}>{g}</div>)}
        </div>
      )}

      {/* Sub-tabs */}
      <div style={{ display: 'flex', borderBottom: '1px solid var(--border)', marginBottom: 18, overflowX: 'auto' }}>
        {TABS.map(t => {
          const tk = TRUST_TAB_KEY[t.id]; const tier = tk && dataQuality?.tabs?.[tk]?.tier
          return (
          <button key={t.id} onClick={() => setTab(t.id)} title={tier ? `Data trust: ${tier}${dataQuality?.tabs?.[tk]?.pct != null ? ` (${Math.round(dataQuality.tabs[tk].pct * 100)}% linked/clean)` : ''} — ${dataQuality?.tabs?.[tk]?.basis || ''}` : undefined} style={{
            padding: '8px 14px', fontSize: 12, fontWeight: 500, background: 'none', border: 'none', cursor: 'pointer',
            borderBottom: tab === t.id ? `2px solid ${B}` : '2px solid transparent',
            color: tab === t.id ? B : 'var(--text3)', whiteSpace: 'nowrap', marginBottom: -1,
          }}>{tier && <span style={{ display: 'inline-block', width: 7, height: 7, borderRadius: '50%', background: trustColor(tier), marginRight: 6, verticalAlign: 'middle' }} />}{t.label}</button>
          )
        })}
      </div>
      {dataQuality?.tabs && (
        <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: -10, marginBottom: 14, display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
          <span style={{ fontWeight: 700, textTransform: 'uppercase' }}>Data trust</span>
          {[['excellent', 'Excellent'], ['usable', 'Usable'], ['advisory', 'Advisory'], ['untrusted', 'Untrusted']].map(([k, lbl]) => (
            <span key={k}><span style={{ display: 'inline-block', width: 7, height: 7, borderRadius: '50%', background: trustColor(k), marginRight: 4 }} />{lbl}</span>
          ))}
          <span style={{ color: 'var(--text3)', fontStyle: 'italic' }}>advisory only — base-data quality per tab; does not affect GO/WAIT</span>
        </div>
      )}

      {/* ===== OVERVIEW ===== */}
      {tab === 'overview' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
          <div style={card}>
            <div style={secTitle}>Win rate by strategy</div>
            <p style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 8, marginTop: -6 }}>Click any bar to filter trades</p>
            {strategyStats.length === 0 ? <Empty label="No strategy data matches current filters." /> : (
              <ResponsiveContainer width="100%" height={Math.max(220, strategyStats.length * 30 + 20)}>
                <BarChart data={strategyStats} layout="vertical" margin={{ top: 0, right: 50, bottom: 0, left: 140 }} onClick={handleStrategyClick} style={{ cursor: 'pointer' }}>
                  <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="var(--border-subtle)" />
                  <XAxis type="number" domain={[0, 100]} tickFormatter={v => `${v}%`} tick={{ fontSize: 10, fill: 'var(--text3)' }} axisLine={{ stroke: 'var(--border)' }} tickLine={false} />
                  <YAxis dataKey="strategy" type="category" tick={{ fontSize: 10, fill: 'var(--text2)' }} width={138} tickFormatter={s => safeStr(s)} axisLine={false} tickLine={false} />
                  <Tooltip content={<WrTooltip />} cursor={{ fill: 'rgba(255,255,255,.03)' }} />
                  <ReferenceLine x={50} stroke="rgba(245,158,11,.4)" strokeDasharray="4 2" />
                  <Bar dataKey="win_rate" radius={[0, 4, 4, 0]}>
                    {strategyStats.map((s, i) => <Cell key={i} fill={s.strategy === selectedStrategy ? P : wrColor(s.win_rate)} opacity={selectedStrategy && s.strategy !== selectedStrategy ? 0.35 : 1} />)}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            )}
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            <div style={card}>
              <div style={secTitle}>R-multiple distribution</div>
              <ResponsiveContainer width="100%" height={140}>
                <BarChart data={rBuckets} margin={{ top: 4, right: 4, bottom: 20, left: 4 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--border-subtle)" />
                  <XAxis dataKey="label" tick={{ fontSize: 10, fill: 'var(--text3)' }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fontSize: 10, fill: 'var(--text3)' }} allowDecimals={false} axisLine={false} tickLine={false} />
                  <Bar dataKey="count" radius={[4, 4, 0, 0]}>{rBuckets.map((b, i) => <Cell key={i} fill={b.min >= 0 ? G : R} fillOpacity={0.8} />)}</Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
            <div style={{ ...card, cursor: 'pointer' }} onClick={() => setTab('missed')}>
              <div style={secTitle}>Missed proposals impact</div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 10 }}>
                {[
                  { label: 'Would win', value: missed?.would_win ?? 0, color: G },
                  { label: 'Would lose', value: missed?.would_lose ?? 0, color: R },
                  { label: 'Left on table', value: `$${num(missed?.pnl_left_on_table).toFixed(2)}`, color: A },
                ].map(k => (
                  <div key={k.label} style={{ textAlign: 'center', padding: '10px 8px', background: 'var(--bg2)', borderRadius: 8 }}>
                    <div style={{ fontSize: 20, fontWeight: 700, color: k.color }}>{k.value}</div>
                    <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 3 }}>{k.label}</div>
                  </div>
                ))}
              </div>
              <p style={{ fontSize: 10, color: 'var(--text3)', marginTop: 10, marginBottom: 0 }}>Click to view table →</p>
            </div>
          </div>
        </div>
        {/* Edge Decay — backtest vs live divergence */}
        <div style={card}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
            <div style={secTitle}>Edge decay — backtest vs live win rate</div>
            <span style={{ fontSize: 9, color: 'var(--text3)' }}>negative gap = live underperforming backtest (overfit risk)</span>
          </div>
          {edgeDecay.length === 0 ? <Empty label="No strategy has both backtest and live paper trades yet." /> : (
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead><tr style={{ borderBottom: '1px solid var(--border)' }}>
                {['Strategy', 'Backtest WR', 'Live WR', 'Live n', 'Gap'].map(h => <th key={h} style={{ textAlign: h === 'Strategy' ? 'left' : 'right', padding: '7px 10px', fontSize: 9, fontWeight: 700, color: 'var(--text3)', textTransform: 'uppercase' }}>{h}</th>)}
              </tr></thead>
              <tbody>{edgeDecay.map(e => (
                <tr key={e.strategy} onClick={() => onDrill({ title: e.strategy, subtitle: 'Backtest vs live divergence', endpoint: '/api/v2/paper-trade-readiness + /api/v2/backtesting/trades', rows: [{ strategy: e.strategy, backtest_win_rate: `${e.backtest_wr}%`, live_win_rate: `${e.live_wr}%`, live_trades: e.live_n, gap_pts: e.gap }] })}
                  style={{ borderBottom: '1px solid var(--border-subtle)', cursor: 'pointer' }}>
                  <td style={{ padding: '7px 10px', color: 'var(--text0)', fontSize: 12 }}>{safeStr(e.strategy)}</td>
                  <td style={{ padding: '7px 10px', textAlign: 'right', fontSize: 12, color: wrColor(e.backtest_wr) }}>{e.backtest_wr}%</td>
                  <td style={{ padding: '7px 10px', textAlign: 'right', fontSize: 12, color: wrColor(e.live_wr) }}>{e.live_wr}%</td>
                  <td style={{ padding: '7px 10px', textAlign: 'right', fontSize: 11, color: 'var(--text3)' }}>{e.live_n}{e.live_n < 5 && <span style={{ marginLeft: 4, fontSize: 8, color: '#fca5a5' }}>low</span>}</td>
                  <td style={{ padding: '7px 10px', textAlign: 'right', fontSize: 12, fontWeight: 700, color: e.gap <= -15 ? R : e.gap < 0 ? A : G }}>{e.gap > 0 ? '+' : ''}{e.gap}pt</td>
                </tr>
              ))}</tbody>
            </table>
          )}
          <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 6 }}>Source: /api/v2/paper-trade-readiness (live) vs replay-trade win rate (backtest)</div>
        </div>
        </div>
      )}

      {/* ===== ENTRY QUALITY (③) ===== */}
      {tab === 'entry_quality' && (
        !eqSummary?.summary ? <Empty card label="Entry-grade data not available. Run scripts/trade_backtest_engine.py to grade closed-trade entries." /> : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 12 }}>
              {[
                { label: 'Trades graded', value: eqSummary.summary.total, color: 'var(--text0)' },
                { label: 'Avg entry RSI', value: num(eqSummary.summary.avg_entry_rsi).toFixed(0), color: num(eqSummary.summary.avg_entry_rsi) >= 70 ? R : num(eqSummary.summary.avg_entry_rsi) >= 60 ? A : G },
                { label: 'Early exits', value: eqSummary.summary.early_exits, color: A },
                { label: 'Left on table', value: `$${(num(eqSummary.summary.total_left_on_table) / 1000).toFixed(0)}k`, color: A },
              ].map(k => (
                <div key={k.label} style={{ ...card, textAlign: 'center' }}>
                  <div style={{ fontSize: 24, fontWeight: 700, color: k.color }}>{k.value}</div>
                  <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 4 }}>{k.label}</div>
                </div>
              ))}
            </div>
            {(eqAnalytics?.coaching_bullets ?? []).length > 0 && (
              <div style={{ ...card, background: 'rgba(96,165,250,.05)', border: '1px solid rgba(96,165,250,.2)' }}>
                <div style={secTitle}>How was our entry — coaching</div>
                {eqAnalytics.coaching_bullets.map((b: string, i: number) => (
                  <div key={i} style={{ fontSize: 12, color: 'var(--text1)', padding: '3px 0', display: 'flex', gap: 8 }}><span style={{ color: B }}>▸</span>{b}</div>
                ))}
              </div>
            )}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
              <div style={card}>
                <div style={secTitle}>Entry grade distribution</div>
                <ResponsiveContainer width="100%" height={180}>
                  <BarChart data={eqSummary.by_entry_grade ?? []} margin={{ top: 4, right: 8, bottom: 4, left: 4 }}>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--border-subtle)" />
                    <XAxis dataKey="entry_grade" tick={{ fontSize: 11, fill: 'var(--text2)' }} axisLine={false} tickLine={false} />
                    <YAxis tick={{ fontSize: 10, fill: 'var(--text3)' }} allowDecimals={false} axisLine={false} tickLine={false} />
                    <Tooltip contentStyle={{ background: 'var(--bg1)', border: '1px solid var(--border)', fontSize: 11 }} cursor={{ fill: 'rgba(255,255,255,.04)' }} />
                    <Bar dataKey="count" radius={[4, 4, 0, 0]}>
                      {(eqSummary.by_entry_grade ?? []).map((g: any, i: number) => <Cell key={i} fill={g.entry_grade === 'A' ? G : g.entry_grade === 'B' ? '#86efac' : g.entry_grade === 'C' ? A : R} />)}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
                <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 4 }}>Most entries grade C/D — entries are timed late (high RSI).</div>
              </div>
              <div style={card}>
                <div style={secTitle}>Entry RSI vs outcome</div>
                <ResponsiveContainer width="100%" height={180}>
                  <BarChart data={eqAnalytics?.rsi_histogram ?? []} margin={{ top: 4, right: 8, bottom: 4, left: 4 }}>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--border-subtle)" />
                    <XAxis dataKey="bucket" tick={{ fontSize: 8, fill: 'var(--text3)' }} axisLine={false} tickLine={false} />
                    <YAxis tick={{ fontSize: 10, fill: 'var(--text3)' }} allowDecimals={false} axisLine={false} tickLine={false} />
                    <Tooltip contentStyle={{ background: 'var(--bg1)', border: '1px solid var(--border)', fontSize: 11 }} cursor={{ fill: 'rgba(255,255,255,.04)' }}
                      formatter={(v: any, _n: any, p: any) => [`${v} trades · avg ${fmt$(p.payload.avg_pnl)} · ${p.payload.wins}W`, p.payload.bucket]} />
                    <Bar dataKey="count" radius={[4, 4, 0, 0]}>
                      {(eqAnalytics?.rsi_histogram ?? []).map((d: any, i: number) => <Cell key={i} fill={num(d.avg_pnl) >= 0 ? G : R} fillOpacity={0.8} />)}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
                <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 4 }}>Green = profitable RSI band. Source: /api/v2/journal/backtest-analytics</div>
              </div>
            </div>
            <div style={card}>
              <div style={secTitle}>Best entries</div>
              <GradeTable rows={eqAnalytics?.best_entries ?? []} onDrill={onDrill} kind="entry" />
            </div>
          </div>
        )
      )}

      {/* ===== AI TRADE EVAL (structured LLM) ===== */}
      {tab === 'trade_eval' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div style={{ fontSize: 11, color: A, padding: '8px 12px', background: 'rgba(245,158,11,.06)', border: '1px solid rgba(245,158,11,.2)', borderRadius: 6 }}>
            ⚠ {tradeEval?.disclaimer ?? 'Post-trade research / journaling and model evaluation. Not live trading advice.'} Each trade is graded by a local LLM (gemma3:12b) on the captured technicals (RSI, MACD, ADX, Bollinger, Fibonacci, structure, candlestick). VWAP/intraday are not captured and are excluded from judgment.
          </div>

          {/* Setup-Quality Prior — feeds the ATM proposal advisory */}
          {setupAdvisory?.prior?.length > 0 && (
            <div style={card}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
                <div style={secTitle}>Setup-quality prior — what entries have worked (by RSI band)</div>
                <span style={{ fontSize: 9, color: 'var(--text3)' }}>feeds ATM proposal advisory · advisory-only, never gates</span>
              </div>
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead><tr style={{ borderBottom: '1px solid var(--border)' }}>
                  {['Entry RSI', 'n', 'Backtest win rate', 'Avg left', 'LLM score', 'Dominant verdict', 'Confidence'].map(h => <th key={h} style={{ textAlign: h === 'Entry RSI' || h === 'Dominant verdict' ? 'left' : 'right', padding: '6px 10px', fontSize: 9, fontWeight: 700, color: 'var(--text3)', textTransform: 'uppercase' }}>{h}</th>)}
                </tr></thead>
                <tbody>{setupAdvisory.prior.map((p: any) => {
                  const sc = p.llm_score ?? p.grade_score
                  return (
                    <tr key={p.band} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                      <td style={{ padding: '6px 10px', fontWeight: 600, color: 'var(--text0)', fontFamily: 'var(--mono)' }}>{p.band}</td>
                      <td style={{ padding: '6px 10px', textAlign: 'right', color: 'var(--text3)' }}>{p.n}</td>
                      <td style={{ padding: '6px 10px', textAlign: 'right', color: wrColor(num(p.win_rate)) }}>{num(p.win_rate).toFixed(0)}%</td>
                      <td style={{ padding: '6px 10px', textAlign: 'right', color: A }}>${num(p.avg_left).toLocaleString()}</td>
                      <td style={{ padding: '6px 10px', textAlign: 'right', fontWeight: 700, color: scoreColor(sc) }}>{sc != null ? num(sc).toFixed(0) : '—'}</td>
                      <td style={{ padding: '6px 10px', fontSize: 11, color: verdictColor(p.dominant_verdict) }}>{p.dominant_verdict ?? '—'}</td>
                      <td style={{ padding: '6px 10px', textAlign: 'right', fontSize: 10, color: p.confidence === 'high' ? G : p.confidence === 'medium' ? A : 'var(--text3)' }}>{p.confidence}</td>
                    </tr>
                  )
                })}</tbody>
              </table>
              {setupAdvisory.advisories?.length > 0 && (
                <div style={{ fontSize: 10, color: 'var(--text2)', marginTop: 8 }}>
                  {setupAdvisory.advisories.filter((a: any) => a.advisory_flag === 'caution').length} of {setupAdvisory.advisories.length} recent proposals fall in a caution band → see ATM advisory on the Trading hub.
                </div>
              )}
            </div>
          )}
          {(!tradeEval?.evaluations || tradeEval.evaluations.length === 0) ? (
            <Empty card label="No structured trade evaluations yet. The batch evaluator (trade_close_llm_analyzer.py --structured) populates these; it runs nightly and grades the largest left-on-table trades first." />
          ) : (
            <>
              {/* Verdict distribution + avg */}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 2fr', gap: 16 }}>
                <div style={{ ...card, textAlign: 'center' }}>
                  <div style={{ fontSize: 36, fontWeight: 800, color: scoreColor(avgEvalScore) }}>{avgEvalScore != null ? Math.round(avgEvalScore) : '—'}</div>
                  <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 4 }}>Avg overall score ({tradeEval.evaluations.length} trades)</div>
                </div>
                <div style={card}>
                  <div style={secTitle}>Verdict distribution</div>
                  {(tradeEval.verdict_distribution ?? []).map((v: any) => (
                    <div key={v.eval_verdict} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 5 }}>
                      <div style={{ width: 200, fontSize: 11, color: 'var(--text1)', textTransform: 'capitalize', flexShrink: 0 }}>{v.eval_verdict}</div>
                      <div style={{ flex: 1, height: 14, background: 'var(--bg2)', borderRadius: 3, overflow: 'hidden' }}>
                        <div style={{ height: '100%', width: `${Math.min(100, v.n / Math.max(...tradeEval.verdict_distribution.map((x: any) => x.n)) * 100)}%`, background: verdictColor(v.eval_verdict) }} />
                      </div>
                      <div style={{ width: 70, fontSize: 11, color: 'var(--text3)', textAlign: 'right' }}>{v.n} · {v.avg_score}avg</div>
                    </div>
                  ))}
                </div>
              </div>
              {/* Evaluated trades list */}
              <div style={card}>
                <div style={secTitle}>Evaluated trades — click for full reasoning</div>
                <div style={{ overflowX: 'auto' }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                    <thead><tr style={{ borderBottom: '1px solid var(--border)' }}>
                      {['Symbol', 'Date', 'Overall', 'Verdict', 'Summary', 'Model'].map(h => <th key={h} style={{ textAlign: ['Overall'].includes(h) ? 'right' : 'left', padding: '7px 10px', fontSize: 9, fontWeight: 700, color: 'var(--text3)', textTransform: 'uppercase' }}>{h}</th>)}
                    </tr></thead>
                    <tbody>{tradeEval.evaluations.map((e: any) => {
                      const sc = e.output_payload?.scores ?? {}
                      return (
                        <tr key={e.id} onClick={() => onDrill({
                          title: `${e.symbol} — AI eval`, subtitle: `${e.eval_verdict ?? '—'} · ${e.close_date ?? ''} · ${e.model_name}`,
                          endpoint: '/api/v2/backtesting/trade-evaluations',
                          rows: [{
                            verdict: e.eval_verdict, overall_score: e.eval_overall_score,
                            confluence: sc.confluence_score, entry_timing: sc.entry_timing_score, exit_quality: sc.exit_quality_score,
                            risk_reward: sc.risk_reward_score, management: sc.management_score,
                            summary: e.summary,
                            entry_assessment: e.output_payload?.entry_assessment,
                            exit_assessment: e.output_payload?.exit_assessment,
                            improvements: e.improvements, data_gaps: e.output_payload?.data_gaps,
                            model: e.model_name, prompt_version: e.prompt_version,
                          }],
                        })}
                          style={{ borderBottom: '1px solid var(--border-subtle)', cursor: 'pointer' }}>
                          <td style={{ padding: '8px 10px', fontWeight: 600, color: 'var(--text0)', fontFamily: 'var(--mono)' }}>{e.symbol}</td>
                          <td style={{ padding: '8px 10px', fontSize: 11, color: 'var(--text3)' }}>{e.close_date ?? '—'}</td>
                          <td style={{ padding: '8px 10px', textAlign: 'right', fontWeight: 700, color: scoreColor(e.eval_overall_score) }}>{e.eval_overall_score ?? '—'}</td>
                          <td style={{ padding: '8px 10px', fontSize: 11 }}><span style={{ padding: '2px 8px', borderRadius: 4, fontSize: 10, fontWeight: 600, background: 'var(--bg2)', color: verdictColor(e.eval_verdict) }}>{e.eval_verdict ?? '—'}</span></td>
                          <td style={{ padding: '8px 10px', fontSize: 11, color: 'var(--text2)', maxWidth: 360, whiteSpace: 'normal', lineHeight: 1.4 }}>{(e.summary || '').slice(0, 140)}{(e.summary || '').length > 140 ? '…' : ''}</td>
                          <td style={{ padding: '8px 10px', fontSize: 9, color: 'var(--text3)' }}>{e.model_name}</td>
                        </tr>
                      )
                    })}</tbody>
                  </table>
                </div>
                <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 8 }}>Source: /api/v2/backtesting/trade-evaluations · local gemma3:12b · structured_eval_v1 · outcome and quality scored separately</div>
              </div>
            </>
          )}
        </div>
      )}

      {/* ===== CAPTURE / LEFT ON TABLE (②) ===== */}
      {tab === 'capture' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 12 }}>
            {[
              { label: 'Left on table (exit, 20d)', value: `$${(num(eqSummary?.summary?.total_left_on_table) / 1000).toFixed(1)}k`, color: A },
              { label: 'Money left (MFE intratrade)', value: `$${num(mfeData?.summary?.total_money_left).toFixed(0)}`, color: A },
              { label: 'Missed proposals', value: `$${num(missed?.pnl_left_on_table).toFixed(2)}`, color: A },
            ].map(k => (
              <div key={k.label} style={{ ...card, textAlign: 'center' }}>
                <div style={{ fontSize: 22, fontWeight: 700, color: k.color }}>{k.value}</div>
                <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 4 }}>{k.label}</div>
              </div>
            ))}
          </div>
          <div style={card}>
            <div style={secTitle}>Cumulative money left on table (MFE, by trade date)</div>
            {captureSeries.length === 0 ? <Empty label="No MFE excursion data for current filters." /> : (
              <ResponsiveContainer width="100%" height={200}>
                <AreaChart data={captureSeries} margin={{ top: 4, right: 8, bottom: 4, left: 4 }}>
                  <defs><linearGradient id="capGrad" x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor={A} stopOpacity={0.35} /><stop offset="95%" stopColor={A} stopOpacity={0} /></linearGradient></defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border-subtle)" />
                  <XAxis dataKey="date" tick={{ fontSize: 9, fill: 'var(--text3)' }} axisLine={false} tickLine={false} />
                  <YAxis tickFormatter={v => `$${v}`} tick={{ fontSize: 9, fill: 'var(--text3)' }} axisLine={false} tickLine={false} />
                  <Tooltip contentStyle={{ background: 'var(--bg1)', border: '1px solid var(--border)', fontSize: 11 }} formatter={(v: any, n: any) => [`$${v}`, n === 'cum' ? 'cumulative' : n]} />
                  <Area type="monotone" dataKey="cum" stroke={A} fill="url(#capGrad)" strokeWidth={2} dot={false} />
                </AreaChart>
              </ResponsiveContainer>
            )}
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
            <div style={card}>
              <div style={secTitle}>Left on table by trade type</div>
              {(eqAnalytics?.left_on_table_by_type ?? []).length === 0 ? <Empty label="No data." /> : (
                <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                  <thead><tr style={{ borderBottom: '1px solid var(--border)' }}>{['Type', 'Total left', 'Avg', 'n'].map(h => <th key={h} style={{ textAlign: h === 'Type' ? 'left' : 'right', padding: '6px 8px', fontSize: 9, color: 'var(--text3)', fontWeight: 700, textTransform: 'uppercase' }}>{h}</th>)}</tr></thead>
                  <tbody>{eqAnalytics.left_on_table_by_type.map((t: any) => (
                    <tr key={t.trade_type} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                      <td style={{ padding: '6px 8px', color: 'var(--text1)', fontSize: 12 }}>{t.trade_type}</td>
                      <td style={{ padding: '6px 8px', textAlign: 'right', color: A, fontSize: 12 }}>${num(t.total_left).toLocaleString()}</td>
                      <td style={{ padding: '6px 8px', textAlign: 'right', color: 'var(--text2)', fontSize: 11 }}>${num(t.avg_left).toFixed(0)}</td>
                      <td style={{ padding: '6px 8px', textAlign: 'right', color: 'var(--text3)', fontSize: 11 }}>{t.count}</td>
                    </tr>
                  ))}</tbody>
                </table>
              )}
            </div>
            <div style={card}>
              <div style={secTitle}>Worst exits (most left behind)</div>
              <GradeTable rows={eqAnalytics?.worst_exits ?? eqSummary?.worst_exits ?? []} onDrill={onDrill} kind="exit" />
            </div>
          </div>
        </div>
      )}

      {/* ===== POTENTIAL OVER TIME (④) ===== */}
      {tab === 'potential' && (
        resultHistory.length === 0 ? (
          <Empty card label="Potential-over-time history is not yet recorded. The append-only backtest_result_history table + archiver need to be enabled (see /api/v2/backtesting/result-history). Once a few backtest runs are archived, this charts how our hypothetical edge trends run-over-run." />
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            <div style={card}>
              <div style={secTitle}>Hypothetical performance over time (per archived run)</div>
              <ResponsiveContainer width="100%" height={240}>
                <LineChart data={resultHistory} margin={{ top: 8, right: 12, bottom: 4, left: 4 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border-subtle)" />
                  <XAxis dataKey="snapshot_date" tick={{ fontSize: 9, fill: 'var(--text3)' }} axisLine={false} tickLine={false} />
                  <YAxis yAxisId="l" tick={{ fontSize: 9, fill: 'var(--text3)' }} axisLine={false} tickLine={false} />
                  <YAxis yAxisId="r" orientation="right" tickFormatter={v => `${v}%`} domain={[0, 100]} tick={{ fontSize: 9, fill: 'var(--text3)' }} axisLine={false} tickLine={false} />
                  <Tooltip contentStyle={{ background: 'var(--bg1)', border: '1px solid var(--border)', fontSize: 11 }} />
                  <Line yAxisId="l" type="monotone" dataKey="total_pnl" name="Total P&L" stroke={G} strokeWidth={2} dot={false} />
                  <Line yAxisId="r" type="monotone" dataKey="win_rate" name="Win rate %" stroke={B} strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>
        )
      )}

      {/* ===== STRATEGY ===== */}
      {tab === 'strategy' && (
        <div style={card}>
          <div style={secTitle}>Strategy performance — click row to filter trades</div>
          {strategyStats.length === 0 ? <Empty label="No strategy data matches current filters." /> : (
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead><tr style={{ borderBottom: '1px solid var(--border)' }}>
                {['Strategy', 'Trades', 'Win rate', 'Avg R', 'Total P&L', 'Profit Factor', 'Exp R', 'Max DD'].map(h => <th key={h} style={{ textAlign: h === 'Strategy' ? 'left' : 'right', padding: '8px 10px', fontSize: 10, fontWeight: 700, color: 'var(--text3)', textTransform: 'uppercase' }}>{h}</th>)}
              </tr></thead>
              <tbody>{strategyStats.map(s => (
                <tr key={s.strategy} onClick={() => { setSelectedStrategy(p => p === s.strategy ? null : s.strategy); setTab('trades') }}
                  style={{ borderBottom: '1px solid var(--border-subtle)', cursor: 'pointer', background: selectedStrategy === s.strategy ? 'rgba(168,85,247,.08)' : 'transparent' }}>
                  <td style={{ padding: '9px 10px', fontWeight: 500, color: 'var(--text0)' }}>{safeStr(s.strategy)}</td>
                  <td style={{ padding: '9px 10px', textAlign: 'right', fontSize: 12 }}>
                    <span style={{ color: 'var(--text3)' }}>{s.trades}</span>
                    {s.trades < 5 && <span style={{ marginLeft: 6, fontSize: 8, padding: '1px 5px', borderRadius: 3, background: 'rgba(239,68,68,.15)', color: '#fca5a5' }}>very small</span>}
                    {s.trades >= 5 && s.trades < 20 && <span style={{ marginLeft: 6, fontSize: 8, padding: '1px 5px', borderRadius: 3, background: 'rgba(245,158,11,.15)', color: '#fde68a' }}>small</span>}
                  </td>
                  <td style={{ padding: '9px 10px', textAlign: 'right' }}>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 8 }}>
                      <div style={{ width: 56, height: 4, borderRadius: 2, background: 'var(--bg2)', overflow: 'hidden' }}>
                        <div style={{ height: '100%', width: `${s.win_rate}%`, borderRadius: 2, background: wrColor(s.win_rate) }} />
                      </div>
                      <span style={{ fontSize: 12, fontWeight: 700, color: wrColor(s.win_rate) }}>{s.win_rate}%</span>
                    </div>
                  </td>
                  <td style={{ padding: '9px 10px', textAlign: 'right', fontSize: 12, fontWeight: 500, color: s.avg_r >= 0 ? G : R }}>{fmtR(s.avg_r)}</td>
                  <td style={{ padding: '9px 10px', textAlign: 'right', fontSize: 12, fontWeight: 500, color: s.total_pnl >= 0 ? G : R }}>{fmt$(s.total_pnl)}</td>
                  <td style={{ padding: '9px 10px', textAlign: 'right', fontSize: 12, color: s.profit_factor != null ? (num(s.profit_factor) >= 1.5 ? G : num(s.profit_factor) >= 1 ? A : R) : 'var(--text3)' }}>{s.profit_factor != null ? num(s.profit_factor).toFixed(2) : '—'}</td>
                  <td style={{ padding: '9px 10px', textAlign: 'right', fontSize: 12, color: s.expectancy_r != null ? (num(s.expectancy_r) >= 0 ? '#86efac' : '#fca5a5') : 'var(--text3)' }}>{s.expectancy_r != null ? fmtR(s.expectancy_r) : '—'}</td>
                  <td style={{ padding: '9px 10px', textAlign: 'right', fontSize: 12, color: s.max_drawdown != null ? R : 'var(--text3)' }}>{s.max_drawdown != null ? `${num(s.max_drawdown).toFixed(1)}%` : '—'}</td>
                </tr>
              ))}</tbody>
            </table>
          )}
        </div>
      )}

      {/* ===== TRADES ===== */}
      {tab === 'trades' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div style={card}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
              <div style={secTitle}>R-multiple distribution{selectedStrategy ? ` — ${safeStr(selectedStrategy)}` : ''}</div>
              {selectedStrategy && <button onClick={() => setSelectedStrategy(null)} style={{ fontSize: 11, color: P, background: 'none', border: '1px solid rgba(168,85,247,.3)', borderRadius: 6, padding: '3px 10px', cursor: 'pointer' }}>Clear filter</button>}
            </div>
            <ResponsiveContainer width="100%" height={160}>
              <BarChart data={rBuckets} margin={{ top: 4, right: 4, bottom: 20, left: 4 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--border-subtle)" />
                <XAxis dataKey="label" tick={{ fontSize: 11, fill: 'var(--text3)' }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fontSize: 11, fill: 'var(--text3)' }} allowDecimals={false} axisLine={false} tickLine={false} />
                <Bar dataKey="count" radius={[4, 4, 0, 0]}>{rBuckets.map((b, i) => <Cell key={i} fill={b.min >= 0 ? G : R} fillOpacity={0.8} />)}</Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
          <div style={card}>
            <div style={secTitle}>{filteredTrades.length} sim trades{filtersActive ? ' (filtered)' : ''}</div>
            {filteredTrades.length === 0 ? <Empty label="No trades match current filters." /> : (
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                  <thead><tr style={{ borderBottom: '1px solid var(--border)' }}>
                    {['Symbol', 'Strategy', 'Source', 'Date', 'Entry', 'Exit', 'P&L', 'R', 'Exit reason'].map(h => <th key={h} style={{ textAlign: ['Symbol', 'Strategy', 'Source', 'Date', 'Exit reason'].includes(h) ? 'left' : 'right', padding: '8px 10px', fontSize: 10, fontWeight: 700, color: 'var(--text3)', textTransform: 'uppercase' }}>{h}</th>)}
                  </tr></thead>
                  <tbody>{filteredTrades.slice(0, 200).map(t => (
                    <tr key={t.simulated_trade_id} onClick={() => onDrill({ title: `${t.symbol} — ${safeStr(t.strategy_id)}`, subtitle: `${t.run_type ?? 'backtest'} · ${t.trade_date ? String(t.trade_date).slice(0, 10) : '—'}`, endpoint: '/api/v2/backtesting/trades', rows: [t as any] })}
                      style={{ borderBottom: '1px solid var(--border-subtle)', cursor: 'pointer' }}>
                      <td style={{ padding: '8px 10px', fontWeight: 600, color: 'var(--text0)', fontFamily: 'var(--mono)' }}>{t.symbol ?? '—'}</td>
                      <td style={{ padding: '8px 10px', fontSize: 11, color: 'var(--text3)' }}>{safeStr(t.strategy_id)}</td>
                      <td style={{ padding: '8px 10px', fontSize: 11 }}><SourceBadge rt={t.run_type} /></td>
                      <td style={{ padding: '8px 10px', fontSize: 11, color: 'var(--text3)' }}>{t.trade_date ? String(t.trade_date).slice(0, 10) : '—'}</td>
                      <td style={{ padding: '8px 10px', textAlign: 'right', color: 'var(--text2)' }}>${num(t.entry_price).toFixed(2)}</td>
                      <td style={{ padding: '8px 10px', textAlign: 'right', color: 'var(--text2)' }}>${num(t.exit_price).toFixed(2)}</td>
                      <td style={{ padding: '8px 10px', textAlign: 'right', fontWeight: 600, color: num(t.pnl) >= 0 ? G : R }}>{fmt$(t.pnl)}</td>
                      <td style={{ padding: '8px 10px', textAlign: 'right', color: num(t.r_multiple) >= 0 ? '#86efac' : '#fca5a5' }}>{fmtR(t.r_multiple)}</td>
                      <td style={{ padding: '8px 10px', fontSize: 11, color: 'var(--text3)' }}>{t.exit_reason || '—'}</td>
                    </tr>
                  ))}</tbody>
                </table>
                {filteredTrades.length > 200 && <div style={{ padding: 10, textAlign: 'center', fontSize: 11, color: 'var(--text3)' }}>Showing 200 of {filteredTrades.length} trades</div>}
              </div>
            )}
          </div>
        </div>
      )}

      {/* ===== MISSED ===== */}
      {tab === 'missed' && (
        !missed ? <Empty label="No missed-opportunity data available." card /> : (() => {
          const sm = missed.summary
          const rows = missed.rows ?? missed.opportunities ?? []
          return (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5,1fr)', gap: 12 }}>
              {[
                { label: 'Would win', value: sm?.would_win ?? missed.would_win, color: G, bg: 'rgba(34,197,94,.1)', bd: 'rgba(34,197,94,.25)' },
                { label: 'Would lose', value: sm?.would_lose ?? missed.would_lose, color: R, bg: 'rgba(239,68,68,.1)', bd: 'rgba(239,68,68,.25)' },
                { label: 'Mixed / review', value: sm?.mixed ?? 0, color: P, bg: 'rgba(168,85,247,.1)', bd: 'rgba(168,85,247,.25)' },
                { label: 'No sim data', value: sm?.no_data ?? 0, color: 'var(--text3)', bg: 'rgba(120,120,120,.08)', bd: 'var(--border)' },
                { label: 'P&L left on table', value: `$${num(sm?.pnl_left_on_table ?? missed.pnl_left_on_table).toFixed(2)}`, color: A, bg: 'rgba(245,158,11,.1)', bd: 'rgba(245,158,11,.25)' },
              ].map(k => (
                <div key={k.label} style={{ background: k.bg, border: `1px solid ${k.bd}`, borderRadius: 12, padding: 16, textAlign: 'center' }}>
                  <div style={{ fontSize: 26, fontWeight: 700, color: k.color }}>{k.value}</div>
                  <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 6 }}>{k.label}</div>
                </div>
              ))}
            </div>
            <div style={card}>
              <div style={secTitle}>{rows.length} distinct missed opportunities</div>
              <div style={{ fontSize: 9, color: 'var(--text3)', marginBottom: 8, marginTop: -8 }}>
                {sm ? `Showing ${sm.deduped_rows} distinct missed opportunities from ${sm.raw_rows} raw simulations; ${sm.duplicates_removed} duplicates collapsed (dedupe key: proposal_id). ` : ''}
                Outcome supplied by backend sim_outcome_verdict; source shown per row. MIXED = sim runs disagree.
              </div>
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                  <thead><tr style={{ borderBottom: '1px solid var(--border)' }}>
                    {['Date', 'Symbol', 'Strategy', 'Status', 'Entry', 'Target', 'Stop', 'Sim P&L', 'Sim R', 'Verdict', 'Source', 'Dupes'].map(h => <th key={h} style={{ textAlign: ['Date', 'Symbol', 'Strategy', 'Status', 'Verdict', 'Source'].includes(h) ? 'left' : 'right', padding: '8px 10px', fontSize: 9, fontWeight: 700, color: 'var(--text3)', textTransform: 'uppercase' }}>{h}</th>)}
                  </tr></thead>
                  <tbody>{rows.map(o => {
                    const v = o.sim_outcome_verdict
                    return (
                      <tr key={o.missed_opportunity_key ?? o.proposal_id} onClick={() => onDrill({ title: `${o.symbol} — missed`, subtitle: `${safeStr(o.strategy)} · ${o.status} · ${v}`, endpoint: '/api/v2/backtesting/missed-opportunities', rows: [o as any] })}
                        style={{ borderBottom: '1px solid var(--border-subtle)', cursor: 'pointer', background: v === 'WIN' ? 'rgba(34,197,94,.03)' : v === 'MIXED' ? 'rgba(168,85,247,.03)' : 'transparent' }}>
                        <td style={{ padding: '7px 10px', fontSize: 11, color: 'var(--text3)' }}>{o.proposal_time ? String(o.proposal_time).slice(0, 10) : '—'}</td>
                        <td style={{ padding: '7px 10px', fontWeight: 600, color: 'var(--text0)', fontFamily: 'var(--mono)' }}>{o.symbol ?? '—'}</td>
                        <td style={{ padding: '7px 10px', fontSize: 11, color: 'var(--text3)' }}>{safeStr(o.strategy)}</td>
                        <td style={{ padding: '7px 10px' }}><span style={{ fontSize: 9, padding: '2px 7px', borderRadius: 4, fontWeight: 600, background: (o.status ?? '').toLowerCase().includes('exp') ? 'rgba(245,158,11,.15)' : 'rgba(239,68,68,.15)', color: (o.status ?? '').toLowerCase().includes('exp') ? A : R }}>{o.status ?? '—'}</span></td>
                        <td style={{ padding: '7px 10px', textAlign: 'right', fontSize: 12, color: 'var(--text2)' }}>{o.entry == null ? '—' : `$${num(o.entry).toFixed(2)}`}</td>
                        <td style={{ padding: '7px 10px', textAlign: 'right', fontSize: 12, color: 'var(--text2)' }}>{o.target == null ? '—' : `$${num(o.target).toFixed(2)}`}</td>
                        <td style={{ padding: '7px 10px', textAlign: 'right', fontSize: 12, color: 'var(--text2)' }}>{o.stop == null ? '—' : `$${num(o.stop).toFixed(2)}`}</td>
                        <td style={{ padding: '7px 10px', textAlign: 'right', fontWeight: 600, color: o.sim_pnl == null ? 'var(--text3)' : num(o.sim_pnl) >= 0 ? G : R }}>{o.sim_pnl == null ? '—' : fmt$(o.sim_pnl)}</td>
                        <td style={{ padding: '7px 10px', textAlign: 'right', color: o.sim_r == null ? 'var(--text3)' : num(o.sim_r) >= 0 ? '#86efac' : '#fca5a5' }}>{o.sim_r == null ? '—' : fmtR(o.sim_r)}</td>
                        <td style={{ padding: '7px 10px' }}><span style={{ color: missedVerdictColor(v), fontWeight: 600, fontSize: 11 }}>{v === 'MIXED' ? `MIXED (${o.win_count}W/${o.loss_count}L)` : v}</span></td>
                        <td style={{ padding: '7px 10px', fontSize: 9, color: 'var(--text3)' }}>{o.sim_verdict_source ?? '—'}</td>
                        <td style={{ padding: '7px 10px', textAlign: 'right' }}>{o.duplicate_count > 1 ? <span style={{ fontSize: 9, padding: '2px 6px', borderRadius: 4, background: 'rgba(96,165,250,.15)', color: B, fontWeight: 600 }}>deduped ×{o.duplicate_count}</span> : <span style={{ fontSize: 11, color: 'var(--text3)' }}>{o.duplicate_count}</span>}</td>
                      </tr>
                    )
                  })}</tbody>
                </table>
              </div>
            </div>
          </div>
          )
        })()
      )}

      {/* ===== RESULTS ===== */}
      {tab === 'results' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          {selectedResult?.equity_curve && selectedResult.equity_curve.length > 1 && (
            <div style={card}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
                <div>
                  <div style={secTitle}>Equity curve — {safeStr(selectedResult.strategy_id)}</div>
                  <div style={{ display: 'flex', gap: 16, marginTop: -8 }}>
                    {[
                      { l: 'Win rate', v: `${num(selectedResult.win_rate).toFixed(1)}%`, c: wrColor(num(selectedResult.win_rate)) },
                      { l: 'PF', v: selectedResult.profit_factor != null ? num(selectedResult.profit_factor).toFixed(2) : '—', c: 'var(--text0)' },
                      { l: 'P&L', v: fmt$(selectedResult.total_pnl), c: num(selectedResult.total_pnl) >= 0 ? G : R },
                      { l: 'Max DD', v: selectedResult.max_drawdown_pct != null ? `${num(selectedResult.max_drawdown_pct).toFixed(1)}%` : '—', c: R },
                      { l: 'Exp R', v: fmtR(selectedResult.expectancy_r), c: num(selectedResult.expectancy_r) >= 0 ? '#86efac' : '#fca5a5' },
                    ].map(k => <div key={k.l} style={{ textAlign: 'center' }}><div style={{ fontSize: 16, fontWeight: 600, color: k.c }}>{k.v}</div><div style={{ fontSize: 9, color: 'var(--text3)' }}>{k.l}</div></div>)}
                  </div>
                </div>
                <button onClick={() => setSelectedResult(null)} style={{ fontSize: 11, color: P, background: 'none', border: '1px solid rgba(168,85,247,.3)', borderRadius: 6, padding: '3px 10px', cursor: 'pointer' }}>Deselect</button>
              </div>
              <ResponsiveContainer width="100%" height={180}>
                <AreaChart data={selectedResult.equity_curve} margin={{ top: 4, right: 4, bottom: 4, left: 4 }}>
                  <defs><linearGradient id="curveGrad" x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor={num(selectedResult.total_pnl) >= 0 ? G : R} stopOpacity={0.3} /><stop offset="95%" stopColor={num(selectedResult.total_pnl) >= 0 ? G : R} stopOpacity={0} /></linearGradient></defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border-subtle)" />
                  <XAxis dataKey="date" tick={{ fontSize: 9, fill: 'var(--text3)' }} tickFormatter={d => d?.slice(5) || d} interval="preserveStartEnd" axisLine={false} tickLine={false} />
                  <YAxis tickFormatter={v => `$${num(v).toFixed(0)}`} tick={{ fontSize: 9, fill: 'var(--text3)' }} axisLine={false} tickLine={false} />
                  <ReferenceLine y={0} stroke="var(--border)" strokeDasharray="3 3" />
                  <Area type="monotone" dataKey="value" dot={false} stroke={num(selectedResult.total_pnl) >= 0 ? G : R} fill="url(#curveGrad)" strokeWidth={2} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          )}
          {results.length === 0 ? <Empty label="No results match current filters." card /> : (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(200px,1fr))', gap: 12 }}>
              {results.map(r => {
                const winPct = r.simulated_trades > 0 ? Math.round(r.wins / r.simulated_trades * 100) : 0
                const sel = selectedResult?.result_id === r.result_id
                return (
                  <div key={r.result_id} onClick={() => setSelectedResult(p => p?.result_id === r.result_id ? null : r)}
                    style={{ ...card, cursor: 'pointer', border: sel ? '1px solid rgba(168,85,247,.6)' : '1px solid var(--border)', background: sel ? 'rgba(168,85,247,.08)' : 'var(--bg1)', padding: '14px 16px' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 10 }}>
                      <div>
                        <div style={{ fontSize: 22, fontWeight: 700, color: wrColor(num(r.win_rate)), lineHeight: 1 }}>{num(r.win_rate).toFixed(1)}%</div>
                        <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 3 }}>{safeStr(r.strategy_id)?.slice(0, 22)}</div>
                      </div>
                      <span style={{ fontSize: 8, padding: '2px 7px', borderRadius: 4, fontWeight: 600, height: 'fit-content', background: 'rgba(34,197,94,.12)', color: '#86efac' }}>{safeStr(r.run_type)}</span>
                    </div>
                    <div style={{ height: 4, borderRadius: 2, overflow: 'hidden', background: 'rgba(239,68,68,.3)', marginBottom: 8 }}>
                      <div style={{ height: '100%', width: `${winPct}%`, borderRadius: 2, background: G }} />
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: 'var(--text3)' }}>
                      <span>{r.wins}W / {r.losses}L</span>
                      <span style={{ color: num(r.total_pnl) >= 0 ? G : R }}>{fmt$(r.total_pnl)}</span>
                    </div>
                    {r.equity_curve && r.equity_curve.length > 2 && (
                      <div style={{ marginTop: 8, height: 36 }}>
                        <ResponsiveContainer width="100%" height="100%">
                          <LineChart data={r.equity_curve}>
                            <ReferenceLine y={0} stroke="var(--border)" />
                            <Line type="monotone" dataKey="value" dot={false} stroke={num(r.total_pnl) >= 0 ? G : R} strokeWidth={1.5} />
                          </LineChart>
                        </ResponsiveContainer>
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          )}
        </div>
      )}

      {/* ===== RUNS ===== */}
      {tab === 'runs' && (
        <div style={card}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
            <div style={secTitle}>All {runs.length} backtest runs{filtersActive ? ' (filtered)' : ''}</div>
            <div style={{ display: 'flex', gap: 6 }}>
              {['all', 'replay_trades', 'replay_proposals', 'champion'].map(f => (
                <button key={f} onClick={() => setRunFilter(f)} style={{
                  fontSize: 10, padding: '3px 10px', borderRadius: 6, cursor: 'pointer',
                  background: runFilter === f ? 'rgba(168,85,247,.18)' : 'transparent',
                  border: runFilter === f ? '1px solid rgba(168,85,247,.5)' : '1px solid var(--border)',
                  color: runFilter === f ? '#d8b4fe' : 'var(--text3)',
                }}>{f === 'all' ? 'All' : safeStr(f)}</button>
              ))}
            </div>
          </div>
          {runs.filter(r => runFilter === 'all' || r.run_type === runFilter).length === 0 ? <Empty label="No runs match current filters." /> : (
            runs.filter(r => runFilter === 'all' || r.run_type === runFilter).map(r => (
              <div key={r.run_id} onClick={() => onDrill({ title: safeStr(r.strategy_id).slice(0, 40), subtitle: `${r.run_type} · ${r.run_id}`, endpoint: '/api/v2/backtesting/runs', rows: [r as any] })}
                style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 12px', marginBottom: 4, background: 'var(--bg2)', border: '1px solid var(--border-subtle)', borderRadius: 8, cursor: 'pointer' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, minWidth: 0 }}>
                  <span style={{ fontSize: 9, padding: '2px 8px', borderRadius: 4, fontWeight: 600, flexShrink: 0, background: r.run_type === 'replay_trades' ? 'rgba(34,197,94,.15)' : 'rgba(168,85,247,.15)', color: r.run_type === 'replay_trades' ? '#86efac' : '#d8b4fe' }}>{safeStr(r.run_type)}</span>
                  <span style={{ fontSize: 12, color: 'var(--text1)', fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{safeStr(r.strategy_id)}</span>
                </div>
                <div style={{ textAlign: 'right', flexShrink: 0, marginLeft: 12 }}>
                  <div style={{ fontSize: 10, color: 'var(--text3)' }}>{r.start_date ?? '—'} → {r.end_date ?? '—'}</div>
                  <div style={{ fontSize: 10, color: G, marginTop: 2 }}>{r.status ?? '—'}</div>
                </div>
              </div>
            ))
          )}
        </div>
      )}

      {/* ===== TRAIL ANALYSIS ===== */}
      {tab === 'trailing' && (
        (!trailData || (trailData.trades?.length ?? 0) === 0) ? (
          <Empty card label="Trailing stop analysis has not been run for the current filters. It simulates replacing fixed stops with trailing stops on each closed trade." />
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            <div style={card}>
              <div style={secTitle}>Strategy trailing stop recommendations</div>
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                  <thead><tr style={{ borderBottom: '1px solid var(--border)' }}>
                    {['Strategy', 'Trades', 'Avg fixed P&L', 'Max potential', '5% trail', '8% trail', 'Optimal %', 'Improvement', 'Recommendation'].map(h => <th key={h} style={{ textAlign: h === 'Strategy' || h === 'Recommendation' ? 'left' : 'right', padding: '8px 10px', fontSize: 9, fontWeight: 700, color: 'var(--text3)', textTransform: 'uppercase' }}>{h}</th>)}
                  </tr></thead>
                  <tbody>{(trailData.strategy_recommendations || []).map((rec: any) => (
                    <tr key={rec.strategy_id} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                      <td style={{ padding: '9px 10px', fontWeight: 500, color: 'var(--text0)' }}>{safeStr(rec.strategy_id)}</td>
                      <td style={{ padding: '9px 10px', textAlign: 'right', fontSize: 12, color: 'var(--text3)' }}>{rec.trades}</td>
                      <td style={{ padding: '9px 10px', textAlign: 'right', fontSize: 12, color: num(rec.avg_fixed_pnl) >= 0 ? G : R }}>{num(rec.avg_fixed_pnl).toFixed(1)}%</td>
                      <td style={{ padding: '9px 10px', textAlign: 'right', fontSize: 12, color: A }}>{num(rec.avg_max_potential).toFixed(1)}%</td>
                      <td style={{ padding: '9px 10px', textAlign: 'right', fontSize: 12, color: num(rec.avg_5pct) > num(rec.avg_fixed_pnl) ? G : 'var(--text3)' }}>{rec.avg_5pct != null ? `${num(rec.avg_5pct).toFixed(1)}%` : '—'}</td>
                      <td style={{ padding: '9px 10px', textAlign: 'right', fontSize: 12, color: num(rec.avg_8pct) > num(rec.avg_fixed_pnl) ? G : 'var(--text3)' }}>{rec.avg_8pct != null ? `${num(rec.avg_8pct).toFixed(1)}%` : '—'}</td>
                      <td style={{ padding: '9px 10px', textAlign: 'right', fontSize: 12, fontWeight: 600, color: P }}>{rec.avg_optimal_pct != null ? `${num(rec.avg_optimal_pct).toFixed(0)}%` : '—'}</td>
                      <td style={{ padding: '9px 10px', textAlign: 'right', fontWeight: 600, fontSize: 13, color: num(rec.avg_improvement) > 0 ? G : R }}>{num(rec.avg_improvement) > 0 ? '+' : ''}{num(rec.avg_improvement).toFixed(1)}%</td>
                      <td style={{ padding: '9px 10px' }}><span style={{ fontSize: 10, padding: '2px 8px', borderRadius: 4, fontWeight: 600, background: (rec.recommended_trail ?? '') === 'keep_fixed' ? 'rgba(144,152,176,.15)' : 'rgba(168,85,247,.18)', color: (rec.recommended_trail ?? '') === 'keep_fixed' ? 'var(--text2)' : '#d8b4fe' }}>{safeStr(rec.recommended_trail, '—')}</span></td>
                    </tr>
                  ))}</tbody>
                </table>
              </div>
            </div>
            <div style={card}>
              <div style={secTitle}>Trade-by-trade trailing stop analysis</div>
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                  <thead><tr style={{ borderBottom: '1px solid var(--border)' }}>
                    {['Symbol', 'Strategy', 'Fixed P&L', 'Max potential', '5% trail', '8% trail', '10% trail', 'Optimal', 'Lesson'].map(h => <th key={h} style={{ textAlign: ['Symbol', 'Strategy', 'Lesson'].includes(h) ? 'left' : 'right', padding: '7px 8px', fontSize: 9, fontWeight: 700, color: 'var(--text3)', textTransform: 'uppercase' }}>{h}</th>)}
                  </tr></thead>
                  <tbody>{(trailData.trades || []).map((t: any) => (
                    <tr key={t.trade_id} onClick={() => onDrill({ title: `${t.symbol} — trailing`, subtitle: safeStr(t.strategy_id), endpoint: '/api/v2/backtesting/trailing-stop-analysis', rows: [t] })} style={{ borderBottom: '1px solid var(--border-subtle)', cursor: 'pointer' }}>
                      <td style={{ padding: '7px 8px', fontWeight: 600, color: 'var(--text0)', fontFamily: 'var(--mono)' }}>{t.symbol ?? '—'}</td>
                      <td style={{ padding: '7px 8px', fontSize: 11, color: 'var(--text3)' }}>{safeStr(t.strategy_id)}</td>
                      <td style={{ padding: '7px 8px', textAlign: 'right', fontSize: 12, color: num(t.fixed_pnl_pct) >= 0 ? G : R, fontWeight: 600 }}>{num(t.fixed_pnl_pct).toFixed(1)}%</td>
                      <td style={{ padding: '7px 8px', textAlign: 'right', fontSize: 12, color: A }}>+{num(t.high_water_pct_gain).toFixed(1)}%</td>
                      <td style={{ padding: '7px 8px', textAlign: 'right', fontSize: 12, color: t.trail_5pct_pnl != null ? (num(t.trail_5pct_pnl) > num(t.fixed_pnl_pct) ? G : R) : 'var(--text3)' }}>{t.trail_5pct_pnl != null ? `${num(t.trail_5pct_pnl).toFixed(1)}%` : '—'}</td>
                      <td style={{ padding: '7px 8px', textAlign: 'right', fontSize: 12, color: t.trail_8pct_pnl != null ? (num(t.trail_8pct_pnl) > num(t.fixed_pnl_pct) ? G : R) : 'var(--text3)' }}>{t.trail_8pct_pnl != null ? `${num(t.trail_8pct_pnl).toFixed(1)}%` : '—'}</td>
                      <td style={{ padding: '7px 8px', textAlign: 'right', fontSize: 12, color: t.trail_10pct_pnl != null ? (num(t.trail_10pct_pnl) > num(t.fixed_pnl_pct) ? G : R) : 'var(--text3)' }}>{t.trail_10pct_pnl != null ? `${num(t.trail_10pct_pnl).toFixed(1)}%` : '—'}</td>
                      <td style={{ padding: '7px 8px', textAlign: 'right', fontWeight: 600, color: P, fontSize: 12 }}>{t.optimal_trail_pct != null ? `${num(t.optimal_trail_pct).toFixed(0)}% → ${num(t.optimal_trail_pnl).toFixed(1)}%` : 'Fixed best'}</td>
                      <td style={{ padding: '7px 8px', maxWidth: 200, fontSize: 11, color: 'var(--text3)', whiteSpace: 'normal', lineHeight: 1.4 }}>{t.lesson_text ? (String(t.lesson_text).slice(0, 120) + (String(t.lesson_text).length > 120 ? '…' : '')) : '—'}</td>
                    </tr>
                  ))}</tbody>
                </table>
              </div>
            </div>
          </div>
        )
      )}

      {/* ===== MFE / MAE ===== */}
      {tab === 'mfe' && (
        <div>
          <div style={{ fontSize: 11, color: 'var(--text2)', marginBottom: 12 }}>Max Favorable / Adverse Excursion — how much of each trade's potential was captured.</div>
          {mfeData?.summary && (
            <div style={{ display: 'flex', gap: 12, marginBottom: 16, flexWrap: 'wrap' }}>
              {[
                { label: 'Analyzed', value: mfeData.summary.total_trades },
                { label: 'Avg Capture', value: `${(num(mfeData.summary.avg_capture_ratio) * 100).toFixed(0)}%`, color: num(mfeData.summary.avg_capture_ratio) >= 0.6 ? G : A },
                { label: 'Avg MFE', value: `${num(mfeData.summary.avg_mfe_r).toFixed(2)}R`, color: G },
                { label: 'Avg MAE', value: `${num(mfeData.summary.avg_mae_r).toFixed(2)}R`, color: R },
                { label: 'Money Left', value: `$${num(mfeData.summary.total_money_left).toFixed(0)}`, color: A },
                { label: 'Entry Quality', value: `${num(mfeData.summary.avg_entry_quality).toFixed(0)}/100` },
              ].map(m => (
                <div key={m.label} style={{ padding: '8px 12px', background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 6, flex: 1, minWidth: 110 }}>
                  <div style={{ fontSize: 9, color: 'var(--text3)', textTransform: 'uppercase', marginBottom: 2 }}>{m.label}</div>
                  <div style={{ fontSize: 16, fontWeight: 700, color: (m as any).color || 'var(--text0)' }}>{m.value}</div>
                </div>
              ))}
            </div>
          )}
          <div style={card}>
            {(!mfeData?.trades?.length) ? <Empty label="No MFE/MAE data for current filters." /> : (
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', fontSize: 11, borderCollapse: 'collapse' }}>
                  <thead><tr style={{ borderBottom: '1px solid var(--border)' }}>
                    {['Symbol', 'Strategy', 'Entry', 'Exit', 'MFE', 'MAE', 'Actual R', 'Capture', 'Left $', 'Entry Q', 'Stop Near'].map(h => <th key={h} style={{ padding: '6px 8px', textAlign: 'left', color: 'var(--text3)', fontSize: 9, fontWeight: 700, textTransform: 'uppercase' }}>{h}</th>)}
                  </tr></thead>
                  <tbody>{(mfeData?.trades || []).map((t: any, i: number) => (
                    <tr key={i} onClick={() => onDrill({ title: `${t.symbol} — MFE/MAE`, subtitle: safeStr(t.strategy_id), endpoint: '/api/v2/backtesting/mfe-analysis', rows: [t] })} style={{ borderBottom: '1px solid var(--border-subtle)', cursor: 'pointer' }}>
                      <td style={{ padding: '6px 8px', fontWeight: 600, color: 'var(--text0)', fontFamily: 'var(--mono)' }}>{t.symbol}</td>
                      <td style={{ padding: '6px 8px', color: 'var(--text3)', fontSize: 9 }}>{safeStr(t.strategy_id)}</td>
                      <td style={{ padding: '6px 8px', color: 'var(--text2)' }}>${num(t.entry_price).toFixed(2)}</td>
                      <td style={{ padding: '6px 8px', color: 'var(--text2)' }}>${num(t.exit_price).toFixed(2)}</td>
                      <td style={{ padding: '6px 8px', color: G, fontWeight: 600 }}>{num(t.mfe_r).toFixed(2)}R</td>
                      <td style={{ padding: '6px 8px', color: R }}>{num(t.mae_r).toFixed(2)}R</td>
                      <td style={{ padding: '6px 8px', color: num(t.actual_r) >= 0 ? G : R }}>{fmtR(t.actual_r)}</td>
                      <td style={{ padding: '6px 8px', color: num(t.capture_ratio) >= 0.6 ? G : A, fontWeight: 600 }}>{(num(t.capture_ratio) * 100).toFixed(0)}%</td>
                      <td style={{ padding: '6px 8px', color: num(t.money_left) > 0 ? A : 'var(--text3)' }}>{fmt$(t.money_left)}</td>
                      <td style={{ padding: '6px 8px', color: 'var(--text2)' }}>{num(t.entry_quality_score).toFixed(0)}</td>
                      <td style={{ padding: '6px 8px', color: t.stop_nearly_hit ? R : 'var(--text3)' }}>{t.stop_nearly_hit ? 'YES' : '—'}</td>
                    </tr>
                  ))}</tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      )}

      {/* ===== OPTIMIZATION ===== */}
      {tab === 'optimization' && (
        <div>
          <div style={{ fontSize: 11, color: 'var(--text2)', marginBottom: 4 }}>Simulates breakeven thresholds per strategy family to find the optimal trailing tier config.</div>
          {optData?.diagnostics && (
            <div style={{ fontSize: 9, color: 'var(--text3)', marginBottom: 12 }}>
              Showing latest optimization for {optData.diagnostics.distinct_families} strategy families (collapsed from {optData.diagnostics.raw_history_rows} historical run rows).
            </div>
          )}
          {(optData?.results || []).length === 0 ? <Empty label="No optimization data for current filters." card /> : (
            (optData.results).map((r: any, i: number) => {
              const optBE = String(cfgBE(r.optimized_config))
              return (
              <div key={i} style={{ ...card, marginBottom: 8 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                  <span style={{ fontSize: 14, fontWeight: 700, color: 'var(--text0)', textTransform: 'capitalize' }}>{safeStr(r.strategy_family)}</span>
                  <span style={{ fontSize: 12, fontWeight: 700, color: num(r.improvement_pct) > 0 ? G : 'var(--text3)' }}>{num(r.improvement_pct) > 0 ? '+' : ''}{num(r.improvement_pct).toFixed(1)}%</span>
                </div>
                <div style={{ display: 'flex', gap: 16, fontSize: 10, marginBottom: 8, flexWrap: 'wrap' }}>
                  <span><span style={{ color: 'var(--text3)' }}>Current: </span>{cfgLabel(r.current_config)} → {num(r.current_avg_r).toFixed(3)}R avg</span>
                  <span><span style={{ color: 'var(--text3)' }}>Optimal: </span><span style={{ color: G, fontWeight: 600 }}>{cfgLabel(r.optimized_config)} → {num(r.optimized_avg_r).toFixed(3)}R avg</span></span>
                  <span style={{ color: 'var(--text3)' }}>{r.sample_size} trades · {r.confidence}</span>
                </div>
                {r.detail && typeof r.detail === 'object' && <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                  {Object.entries(r.detail).map(([th, d]: [string, any]) => (
                    <span key={th} style={{ padding: '3px 8px', borderRadius: 4, fontSize: 9,
                      background: th === optBE ? 'rgba(34,197,94,.15)' : 'var(--bg2)',
                      border: `1px solid ${th === optBE ? 'rgba(34,197,94,.3)' : 'var(--border-subtle)'}`,
                      color: th === optBE ? G : 'var(--text2)' }}>
                      BE {th}R: {num(d?.avg_r).toFixed(3)}R{d?.win_rate != null ? ` win ${num(d.win_rate).toFixed(0)}%` : ''}
                    </span>
                  ))}
                </div>}
              </div>
            )})
          )}
        </div>
      )}

      {/* ===== LLM REVIEW COVERAGE ===== */}
      {tab === 'llm_reviews' && (() => {
        const eb = llmReviewData?.error_breakdown ?? {}
        const runs = llmReviewData?.runs ?? {}
        const oh = llmReviewData?.ollama_health ?? {}
        const healthy = oh.healthy
        const banner = healthy === true
          ? { c: G, bg: 'rgba(34,197,94,.08)', bd: 'rgba(34,197,94,.25)', t: `Ollama healthy${oh.latency_ms != null ? ` (${oh.latency_ms}ms)` : ''}` }
          : healthy === false
          ? { c: R, bg: 'rgba(239,68,68,.08)', bd: 'rgba(239,68,68,.25)', t: `Ollama currently unhealthy — ${oh.failure_class ?? 'unavailable'}` }
          : { c: A, bg: 'rgba(245,158,11,.08)', bd: 'rgba(245,158,11,.25)', t: 'Ollama health unknown' }
        const complete = (llmReviewData?.total_reviews ?? 0) - (llmReviewData?.error_count ?? 0) - (llmReviewData?.pending_count ?? 0) - (eb.invalidated_stale_basis ?? 0)
        return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div style={{ fontSize: 11, color: banner.c, padding: '8px 12px', background: banner.bg, border: `1px solid ${banner.bd}`, borderRadius: 6, fontWeight: 600 }}>
            ● {banner.t}
            {runs.last_skipped_at && <span style={{ color: A, fontWeight: 400 }}> · last review run skipped {String(runs.last_skipped_at).slice(0, 16)} ({runs.last_skipped_reason})</span>}
          </div>
          <div style={{ fontSize: 10, color: 'var(--text3)', padding: '6px 12px', background: 'rgba(96,165,250,.06)', border: '1px solid rgba(96,165,250,.15)', borderRadius: 6 }}>
            Infra errors are model/service availability failures (Ollama down/timeout), NOT failed trades or failed strategy logic. Parser errors are true review-generation issues. {runs.last_successful_at ? `Last successful run: ${String(runs.last_successful_at).slice(0, 16)}.` : 'No completed run recorded yet.'} Retryable backlog: {eb.retryable ?? 0} (manual/bounded).
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6,1fr)', gap: 10 }}>
            {[
              { label: 'Total Rows', value: llmReviewData?.total_reviews ?? 0, color: 'var(--text0)' },
              { label: 'Complete', value: complete, color: G },
              { label: 'Infra errors', value: eb.infrastructure_errors ?? 0, color: A },
              { label: 'Parser errors', value: eb.parser_errors ?? 0, color: R },
              { label: 'Empty/null', value: eb.empty_null_reviews ?? 0, color: 'var(--text3)' },
              { label: 'Retryable', value: eb.retryable ?? 0, color: B },
            ].map(k => (
              <div key={k.label} style={{ ...card, textAlign: 'center' }}>
                <div style={{ fontSize: 26, fontWeight: 700, color: k.color }}>{k.value}</div>
                <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 4 }}>{k.label}</div>
              </div>
            ))}
          </div>
          {llmReviewData?.coverage && (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
              {[
                { label: 'Real Paper Trades With LLM Review', ...llmReviewData.coverage.paper_trades },
                { label: 'Backtest Rows With LLM Review', ...llmReviewData.coverage.backtest_trades },
              ].map(c => {
                const total = (c as any).total ?? (c as any).closed_total ?? 0
                return (
                  <div key={c.label} style={card}>
                    <div style={secTitle}>{c.label}</div>
                    <div style={{ display: 'flex', gap: 16 }}>
                      <div><div style={{ fontSize: 20, fontWeight: 700, color: G }}>{(c as any).reviewed ?? 0}</div><div style={{ fontSize: 9, color: 'var(--text3)' }}>Reviewed</div></div>
                      <div><div style={{ fontSize: 20, fontWeight: 700, color: A }}>{(c as any).unreviewed ?? 0}</div><div style={{ fontSize: 9, color: 'var(--text3)' }}>Unreviewed</div></div>
                      <div><div style={{ fontSize: 20, fontWeight: 700, color: 'var(--text2)' }}>{total}</div><div style={{ fontSize: 9, color: 'var(--text3)' }}>Total</div></div>
                    </div>
                    <div style={{ height: 4, borderRadius: 2, background: 'var(--bg2)', marginTop: 10, overflow: 'hidden' }}>
                      <div style={{ height: '100%', width: `${Math.min(100, ((c as any).reviewed ?? 0) / Math.max(total, 1) * 100)}%`, background: G, borderRadius: 2 }} />
                    </div>
                  </div>
                )
              })}
            </div>
          )}
          <div style={card}>
            <div style={secTitle}>Latest LLM Reviews</div>
            {llmReviewData?.provenance && (
              <div style={{ fontSize: 9, color: 'var(--text3)', marginBottom: 8, marginTop: -8 }}>
                Provenance: {Object.entries(llmReviewData.provenance).map(([k, v]: any) => `${k} ${v.rows} (${v.trade_instance_linked} linked)`).join(' · ')}. Simulation rows are backtest sims (no real trade); paper/imported link to canonical trade_instance_id where an exact key exists.
              </div>
            )}
            {(llmReviewData?.latest_reviews || []).length === 0 ? <Empty label="No LLM reviews yet. Reviews run weekly on Sunday at 11 PM." /> : (
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead><tr style={{ borderBottom: '1px solid var(--border)' }}>
                  {['Symbol', 'Stage', 'Status', 'Model', 'Provenance', 'Lineage', 'Date'].map(h => <th key={h} style={{ textAlign: 'left', padding: '8px 10px', fontSize: 9, fontWeight: 700, color: 'var(--text3)', textTransform: 'uppercase' }}>{h}</th>)}
                </tr></thead>
                <tbody>{(llmReviewData?.latest_reviews || []).map((r: any) => {
                  const sc = r.status === 'complete' ? G : r.status === 'error' ? R : r.status === 'partial' ? A : 'var(--text3)'
                  const si = r.status === 'complete' ? '✓' : r.status === 'error' ? '✗' : '○'
                  return (
                    <tr key={r.id} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                      <td style={{ padding: '8px 10px', fontWeight: 600, color: 'var(--text0)', fontFamily: 'var(--mono)' }}>{r.symbol}</td>
                      <td style={{ padding: '8px 10px', fontSize: 11, color: 'var(--text2)' }}>{safeStr(r.review_stage)}</td>
                      <td style={{ padding: '8px 10px' }}><span style={{ fontSize: 12, color: sc, fontWeight: 600 }}>{si} {r.status}</span></td>
                      <td style={{ padding: '8px 10px', fontSize: 11, color: 'var(--text3)' }}>{r.model_name || '—'}</td>
                      <td style={{ padding: '8px 10px' }}>{(() => { const pk = r.provenance || (r.source_table === 'strategy_backtest_trades' ? 'simulation' : 'paper'); const col = pk === 'paper' ? G : pk === 'imported_backtest' ? B : pk === 'simulation' ? P : 'var(--text3)'; return <span style={{ fontSize: 9, padding: '2px 6px', borderRadius: 4, background: 'rgba(255,255,255,.05)', color: col, fontWeight: 600 }}>{pk}</span> })()}</td>
                      <td style={{ padding: '8px 10px', fontSize: 10 }}>{r.linked ? <span style={{ color: G }}>ti#{r.trade_instance_id}</span> : <span style={{ color: 'var(--text3)' }}>{r.provenance === 'simulation' ? 'sim (no trade)' : 'unlinked'}</span>}</td>
                      <td style={{ padding: '8px 10px', fontSize: 11, color: 'var(--text3)' }}>{r.generated_at ? String(r.generated_at).slice(0, 10) : '—'}</td>
                    </tr>
                  )
                })}</tbody>
              </table>
            )}
          </div>
        </div>
        )
      })()}

      <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 16, textAlign: 'center' }}>Read-only port of v2 /backtesting. Sources: /api/v2/backtesting/* + /api/v2/lifecycle/llm-review-status</div>
    </div>
  )
}

function SourceBadge({ rt }: { rt?: string }) {
  const m: Record<string, { bg: string; c: string; t: string }> = {
    replay_trades: { bg: 'rgba(34,197,94,.15)', c: '#86efac', t: 'replay' },
    replay_proposals: { bg: 'rgba(245,158,11,.15)', c: '#fde68a', t: 'proposal' },
  }
  const s = m[rt ?? ''] ?? { bg: 'rgba(168,85,247,.15)', c: '#d8b4fe', t: rt || 'champion' }
  return <span style={{ padding: '2px 7px', borderRadius: 6, fontSize: 9, fontWeight: 600, background: s.bg, color: s.c }}>{s.t}</span>
}

function gradeColor(g?: string) { return g === 'A' ? G : g === 'B' ? '#86efac' : g === 'C' ? A : g === 'D' ? R : 'var(--text3)' }

function GradeTable({ rows, onDrill, kind }: { rows: any[]; onDrill: (c: DrillContext) => void; kind: 'entry' | 'exit' }) {
  if (!rows?.length) return <Empty label="No data." />
  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead><tr style={{ borderBottom: '1px solid var(--border)' }}>
          {['Symbol', 'Entry G', 'Exit G', kind === 'entry' ? 'Entry RSI' : 'Left 20d', 'P&L'].map(h => <th key={h} style={{ textAlign: h === 'Symbol' ? 'left' : 'right', padding: '6px 8px', fontSize: 9, color: 'var(--text3)', fontWeight: 700, textTransform: 'uppercase' }}>{h}</th>)}
        </tr></thead>
        <tbody>{rows.slice(0, 10).map((r, i) => (
          <tr key={r.trade_key || i} onClick={() => onDrill({ title: `${r.symbol} — ${r.trade_key || ''}`, subtitle: `entry ${r.entry_grade ?? '—'} · exit ${r.exit_grade ?? '—'}`, endpoint: '/api/v2/journal/backtest-analytics', rows: [r] })}
            style={{ borderBottom: '1px solid var(--border-subtle)', cursor: 'pointer' }}>
            <td style={{ padding: '6px 8px', fontWeight: 600, color: 'var(--text0)', fontFamily: 'var(--mono)' }}>{r.symbol}</td>
            <td style={{ padding: '6px 8px', textAlign: 'right', fontWeight: 700, color: gradeColor(r.entry_grade) }}>{r.entry_grade ?? '—'}</td>
            <td style={{ padding: '6px 8px', textAlign: 'right', fontWeight: 700, color: gradeColor(r.exit_grade) }}>{r.exit_grade ?? '—'}</td>
            <td style={{ padding: '6px 8px', textAlign: 'right', color: 'var(--text2)', fontSize: 11 }}>{kind === 'entry' ? (r.entry_rsi != null ? num(r.entry_rsi).toFixed(0) : '—') : (r.left_on_table_20d != null ? `$${num(r.left_on_table_20d).toLocaleString()}` : '—')}</td>
            <td style={{ padding: '6px 8px', textAlign: 'right', color: num(r.actual_pnl) >= 0 ? G : R, fontSize: 11 }}>{r.actual_pnl != null ? fmt$(r.actual_pnl) : '—'}</td>
          </tr>
        ))}</tbody>
      </table>
    </div>
  )
}

function Empty({ label, card: asCard }: { label: string; card?: boolean }) {
  const inner = <div style={{ padding: '28px 20px', textAlign: 'center', color: 'var(--text3)', fontSize: 12, lineHeight: 1.5 }}>{label}</div>
  return asCard ? <div style={card}>{inner}</div> : inner
}
