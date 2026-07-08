import { useState, useMemo, useEffect } from 'react'
import { useApi } from '../hooks/useApi'
import { fmt$ } from '../lib/format'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, AreaChart, Area, PieChart, Pie, Cell } from 'recharts'
import type { DrillContext } from '../components/DetailDrawer'
import TradeReplayChart from '../components/TradeReplayChart'
import { buildReplayTrade } from '../lib/replayTrade'
import ProtectionOutcomesPanel from '../components/ProtectionOutcomesPanel'
import BacktestPanel from '../components/BacktestPanel'
import ExecutionHypothesesPanel from '../components/ExecutionHypothesesPanel'
import SchwabJournal from '../components/SchwabJournal'
import ExecutionCoachPanel from '../components/ExecutionCoachPanel'
import DrawdownChart from '../components/risk/DrawdownChart'
import ZellaScoreCard from '../components/tradeinview/ZellaScoreCard'
import ExitIntelligencePanel from '../components/tradeinview/ExitIntelligencePanel'
import BehavioralPanel from '../components/tradeinview/BehavioralPanel'
import SavedFilterBar, { type FilterPayload } from '../components/tradeinview/SavedFilterBar'
import TradeLogTable from '../components/tradeinview/TradeLogTable'
import TradeInViewDetail from '../components/tradeinview/TradeInViewDetail'
import CsvImportPanel from '../components/tradeinview/CsvImportPanel'
import ManualEntryPanel from '../components/tradeinview/ManualEntryPanel'
import OptionsJournalPanel from '../components/tradeinview/OptionsJournalPanel'
import SessionRecapPanel from '../components/tradeinview/SessionRecapPanel'
import AdvancedReportsPanel from '../components/tradeinview/AdvancedReportsPanel'
import MonteCarloPanel from '../components/tradeinview/MonteCarloPanel'
import TradeCompareReplay from '../components/tradeinview/TradeCompareReplay'
import TaggingQueuePanel from '../components/tradeinview/TaggingQueuePanel'
import ByTickerPanel from '../components/tradeinview/ByTickerPanel'
import { runJournalAsk } from '../lib/cloudLlmRun'
import { useOAuthLanes, laneReady } from '../hooks/useOAuthLanes'

interface Props { onDrill: (ctx: DrillContext) => void }
const TABS = ['Trades', 'By Ticker', 'Tagging Queue', 'Analytics', 'Exit Intel', 'Behavioral', 'Session', 'Advanced', 'Lessons', 'Protection', 'Backtesting', 'Real Accounts', 'Import'] as const
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
  eg: string | null; xg: string | null; entryTimeFull: string | null; r: number | null
}
const EXEC_C: Record<string, string> = { good: '#22c55e', ok: '#84cc16', weak: '#f59e0b', poor: '#ef4444' }

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

// Explain the entry/exit letter grades (A best → F worst, from backtest-replay grading) using the
// execution-quality signals when available, so the operator sees WHICH is entry/exit and WHY.
function gradeExplain(t: any, eq: any): string {
  const lines = ['Letter grades A (best) → F (worst), from backtest-replay grading.', '']
  const entryWhy: string[] = []
  if (eq) {
    if (eq.entry_timing_grade) entryWhy.push(`${eq.entry_timing_grade} timing`)
    if (eq.entry_volume_ratio != null) entryWhy.push(`RVOL ${eq.entry_volume_ratio}${eq.entry_volume_ratio < 1 ? ' (below avg)' : ''}`)
    if (eq.entry_above_vwap === false) entryWhy.push('below VWAP')
    else if (eq.entry_above_vwap === true) entryWhy.push('above VWAP')
  }
  lines.push(`ENTRY grade ${t.eg ?? '—'}${entryWhy.length ? ' — ' + entryWhy.join(', ') : ''}`)
  const exitWhy: string[] = []
  if (eq) {
    if (eq.exit_timing_grade) exitWhy.push(`${eq.exit_timing_grade} timing`)
    if (eq.capture_ratio != null) exitWhy.push(`captured ${Math.round((eq.capture_ratio ?? 0) * 100)}% of the in-hold move`)
    if (eq.missed_opportunity_grade === 'severe') exitWhy.push('severe missed runner')
  }
  lines.push(`EXIT grade ${t.xg ?? '—'}${exitWhy.length ? ' — ' + exitWhy.join(', ') : ''}`)
  if (eq?.grok_what_to_do_next_time) lines.push('', `Coach: ${eq.grok_what_to_do_next_time}`)
  return lines.join('\n')
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

// ── Inline emotion/psychology tagging form (writes journal_trade_reviews; feeds the by-emotion analytics) ──
const _PRE = ['calm', 'confident', 'impatient', 'fomo', 'distracted', 'overconfident', 'anxious']
const _DURING = ['calm', 'hesitation', 'tilt', 'greed', 'fear', 'moved stop', 'added to loser']
const _POST = ['satisfied', 'relieved', 'regret', 'frustrated', 'indifferent']
const _MISTAKES = ['FOMO', 'Revenge', 'Oversize', 'Chased', 'Moved Stop', 'Early Exit (fear)', 'No Stop', 'Overtrading']
const _STRENGTHS = ['Patient Entry', 'Good Size', 'Let Winner Run', 'Cut Loss Fast', 'Followed Plan', 'Waited for Setup']

function TradeReviewForm({ tradeKey, symbol, account, closedDate, onClose }: any) {
  const [eb, setEb] = useState(''); const [ed, setEd] = useState(''); const [ea, setEa] = useState('')
  const [conf, setConf] = useState(0); const [stress, setStress] = useState(0); const [fp, setFp] = useState<boolean | null>(null)
  const [mis, setMis] = useState<string[]>([]); const [str, setStr] = useState<string[]>([])
  const [notes, setNotes] = useState(''); const [saving, setSaving] = useState(false); const [msg, setMsg] = useState('')
  const tog = (arr: string[], set: any, v: string) => set(arr.includes(v) ? arr.filter(x => x !== v) : [...arr, v])
  const Chip = ({ label, active, onClick, color }: any) => (
    <button onClick={onClick} style={{ fontSize: 8.5, padding: '2px 7px', borderRadius: 11, cursor: 'pointer', border: `1px solid ${active ? color : 'var(--border)'}`, background: active ? color + '22' : 'var(--bg1)', color: active ? color : 'var(--text3)' }}>{label}</button>
  )
  const Row = ({ label, opts, val, set, color }: any) => (
    <div style={{ marginTop: 6 }}>
      <div style={{ fontSize: 8, color: 'var(--text3)', textTransform: 'uppercase', marginBottom: 3 }}>{label}</div>
      <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>{opts.map((o: string) => <Chip key={o} label={o} active={val === o} color={color} onClick={() => set(val === o ? '' : o)} />)}</div>
    </div>
  )
  const Scale = ({ label, val, set, color }: any) => (
    <div style={{ marginTop: 6 }}>
      <div style={{ fontSize: 8, color: 'var(--text3)', textTransform: 'uppercase', marginBottom: 3 }}>{label} (1–5)</div>
      <div style={{ display: 'flex', gap: 4 }}>{[1, 2, 3, 4, 5].map(n => <button key={n} onClick={() => set(val === n ? 0 : n)} style={{ width: 24, height: 22, fontSize: 10, borderRadius: 4, cursor: 'pointer', border: `1px solid ${val === n ? color : 'var(--border)'}`, background: val === n ? color + '22' : 'var(--bg1)', color: val === n ? color : 'var(--text3)' }}>{n}</button>)}</div>
    </div>
  )
  const save = async () => {
    setSaving(true); setMsg('')
    try {
      const body: any = { trade_key: tradeKey, symbol, account, closed_date: closedDate, mistake_tags: mis, strength_tags: str }
      if (eb) body.emotion_before = eb; if (ed) body.emotion_during = ed; if (ea) body.emotion_after = ea
      if (conf) body.confidence_before = conf; if (stress) body.stress_level = stress
      if (fp !== null) body.followed_plan = fp; if (notes.trim()) body.review_notes = notes.trim()
      const r = await fetch('/api/v2/journal/review', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }).then(x => x.json())
      if (r.ok) { setMsg('✓ saved'); setTimeout(onClose, 700) } else setMsg('⛔ ' + (r.error || 'failed'))
    } catch (e: any) { setMsg('⛔ ' + e.message) } finally { setSaving(false) }
  }
  return (
    <div style={{ marginTop: 8, padding: 9, background: 'var(--bg1)', border: '1px solid rgba(168,85,247,.3)', borderRadius: 7 }}>
      <div style={{ fontSize: 9, fontWeight: 700, color: '#c084fc', marginBottom: 2 }}>📝 Tag this trade — emotions & execution</div>
      <Row label="Pre-trade mood" opts={_PRE} val={eb} set={setEb} color="#60a5fa" />
      <div style={{ display: 'flex', gap: 14 }}><Scale label="Confidence" val={conf} set={setConf} color="#60a5fa" /><Scale label="Stress" val={stress} set={setStress} color="#f59e0b" /></div>
      <Row label="During trade" opts={_DURING} val={ed} set={setEd} color="#f59e0b" />
      <Row label="Post-trade" opts={_POST} val={ea} set={setEa} color="#22c55e" />
      <div style={{ marginTop: 6 }}>
        <div style={{ fontSize: 8, color: 'var(--text3)', textTransform: 'uppercase', marginBottom: 3 }}>Followed plan?</div>
        <div style={{ display: 'flex', gap: 4 }}>
          <Chip label="✓ yes" active={fp === true} color="#22c55e" onClick={() => setFp(fp === true ? null : true)} />
          <Chip label="✗ no" active={fp === false} color="#ef4444" onClick={() => setFp(fp === false ? null : false)} />
        </div>
      </div>
      <div style={{ marginTop: 6 }}>
        <div style={{ fontSize: 8, color: '#ef4444', textTransform: 'uppercase', marginBottom: 3 }}>Mistakes (one-tap)</div>
        <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>{_MISTAKES.map(m => <Chip key={m} label={m} active={mis.includes(m)} color="#ef4444" onClick={() => tog(mis, setMis, m)} />)}</div>
      </div>
      <div style={{ marginTop: 6 }}>
        <div style={{ fontSize: 8, color: '#22c55e', textTransform: 'uppercase', marginBottom: 3 }}>Strengths (one-tap)</div>
        <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>{_STRENGTHS.map(s => <Chip key={s} label={s} active={str.includes(s)} color="#22c55e" onClick={() => tog(str, setStr, s)} />)}</div>
      </div>
      <input value={notes} onChange={e => setNotes(e.target.value)} placeholder="note (optional)" style={{ width: '100%', marginTop: 7, fontSize: 10, padding: '5px 7px', borderRadius: 4, border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text0)' }} />
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 8 }}>
        <button disabled={saving} onClick={save} style={{ fontSize: 10, fontWeight: 700, padding: '5px 14px', borderRadius: 5, border: 'none', cursor: 'pointer', background: '#a855f7', color: '#fff' }}>{saving ? 'saving…' : 'Save tags'}</button>
        <button onClick={onClose} style={{ fontSize: 10, padding: '5px 10px', borderRadius: 5, border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text3)', cursor: 'pointer' }}>cancel</button>
        {msg && <span style={{ fontSize: 9, color: msg.startsWith('✓') ? '#22c55e' : '#ef4444' }}>{msg}</span>}
      </div>
    </div>
  )
}

export default function JournalHub({ onDrill }: Props) {
  const [chartTrade, setChartTrade] = useState<any>(null)
  const [tab, setTab] = useState<typeof TABS[number]>('Trades')
  const [critiqueQuery, setCritiqueQuery] = useState('')
  useEffect(() => {
    try {
      const storedTab = sessionStorage.getItem('journal_tab') as typeof TABS[number] | null
      const storedQ = sessionStorage.getItem('journal_critique_q') || ''
      if (storedTab && (TABS as readonly string[]).includes(storedTab)) setTab(storedTab)
      if (storedQ) setCritiqueQuery(storedQ)
      sessionStorage.removeItem('journal_tab')
      sessionStorage.removeItem('journal_critique_q')
    } catch { /* */ }
  }, [])
  // Trade Log: search + quick filter + pagination
  const [logSearch, setLogSearch] = useState('')
  const [logQuick, setLogQuick] = useState('all')
  const [logPage, setLogPage] = useState(0)
  const LOG_PAGE_SIZE = 12
  const [acctFilter, setAcctFilter] = useState('')
  const [timeRange, setTimeRange] = useState<typeof TIME_RANGES[number]>('6M')
  const { data: journal } = useApi<any>('/api/v2/automated-trade-journal', 60_000)
  const { data: outcomesData } = useApi<any>('/api/v2/rec-intel/outcomes', 300_000)   // discovery origin per symbol
  const { data: schwabJournal } = useApi<any>('/api/v2/journal', 120_000)
  const { data: readiness } = useApi<any>('/api/v2/paper-trade-readiness', 120_000)
  const { data: rawLessonsResp } = useApi<any>('/api/v2/journal/closed-trades/lessons', 120_000)
  const { data: eqResp } = useApi<any>('/api/v2/journal/execution-quality?limit=500', 120_000)
  // edge analytics (time-of-day / session / equity-drawdown / R / strategy) — follows account + range
  const _edgeDays: Record<string, number> = { '1M': 30, '3M': 90, '6M': 180, '1Y': 365, 'YTD': 365, 'ALL': 1095 }
  const { data: edgeResp } = useApi<any>(
    `/api/v2/journal/edge-analytics?days=${_edgeDays[timeRange] ?? 365}${acctFilter ? '&account=' + acctFilter : ''}`, 120_000)
  const { data: tagQueueResp } = useApi<any>(
    `/api/v2/journal/tagging-queue?days=${_edgeDays[timeRange] ?? 365}&limit=1${acctFilter ? '&account=' + encodeURIComponent(acctFilter) : ''}`, 120_000)
  const critiqueSummariesUrl = `/api/v2/journal/ai-critique/summaries?days=${_edgeDays[timeRange] ?? 365}&limit=500${acctFilter ? `&account=${encodeURIComponent(acctFilter)}` : ''}`
  const { data: critiqueSummariesResp, refetch: refetchCritiqueSummaries } = useApi<any>(critiqueSummariesUrl, 120_000)
  const critiqueByKey: Record<string, any> = (critiqueSummariesResp?.data ?? critiqueSummariesResp)?.by_trade_key ?? {}
  const [batchCritBusy, setBatchCritBusy] = useState(false)
  const [batchCritMsg, setBatchCritMsg] = useState('')
  const edge = ((edgeResp as any)?.data ?? edgeResp) || {}
  const tagQueueNeed = ((tagQueueResp as any)?.data ?? tagQueueResp)?.need_tagging ?? 0
  const [jq, setJq] = useState('')          // journal Ask box
  const [jAns, setJAns] = useState<any>(null)
  const [jBusy, setJBusy] = useState<'grok' | 'chatgpt' | null>(null)
  const oauth = useOAuthLanes(0)

  const jAsk = async (lane: 'grok' | 'chatgpt') => {
    const question = jq.trim()
    if (!question) return
    if (!laneReady(lane === 'grok' ? oauth.grok : oauth.chatgpt)) {
      setJAns({ ok: false, error: `${lane} OAuth not ready — Ops → Consumption` })
      return
    }
    setJBusy(lane); setJAns(null)
    try {
      setJAns(await runJournalAsk({
        question, lane, account: acctFilter || undefined, days: _edgeDays[timeRange] ?? 365,
      }))
    } catch (e: any) { setJAns({ ok: false, error: String(e?.message || e) }) }
    finally { setJBusy(null) }
  }

  const [reviewOpen, setReviewOpen] = useState<string | null>(null)  // trade_key whose emotion form is open
  const [logView, setLogView] = useState<'cards' | 'table'>('cards')
  const [sortCol, setSortCol] = useState('exitDate')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')
  const [detailTrade, setDetailTrade] = useState<any>(null)
  const [compareOpen, setCompareOpen] = useState(false)
  const tk = (sym: string, t: any) => `${sym}|${String(t ?? '').slice(0, 19).replace('T', ' ')}`
  const eqMap = useMemo(() => { const m: Record<string, any> = {}; for (const e of (eqResp?.trades ?? [])) m[tk(e.symbol, e.entry_time)] = e; return m }, [eqResp])
  // R-multiple: paper = real (planned stop); schwab = PROXY (reward / max adverse excursion), flagged ~
  const getR = (t: UT): { r: number | null; proxy: boolean } => {
    if (t.r != null) return { r: t.r, proxy: false }
    const e = t.entryTimeFull ? eqMap[tk(t.symbol, t.entryTimeFull)] : null
    const ep = Number(e?.entry_price), xp = Number(e?.exit_price), mae = Number(e?.mae_after_entry)
    if (e && mae > 0 && isFinite(ep) && isFinite(xp)) return { r: (xp - ep) / mae, proxy: true }
    return { r: null, proxy: false }
  }
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
        eg: t.entry_grade ?? null, xg: t.exit_grade ?? null, entryTimeFull: t.entry_time ?? null,
        r: t.r_multiple != null ? Number(t.r_multiple) : null,   // paper: real planned-R
      })
    }
    for (const t of (schwabJournal?.trades ?? [])) {
      result.push({
        id: `sw-${t.trade_key ?? t.symbol}-${t.open_date}`, symbol: t.symbol,
        account: t.account, na: normalizeAcct(t.account),
        trade_key: t.trade_key,
        ep: t.buy_price, xp: t.sell_price, shares: t.shares ?? 0,
        pnl: t.pnl ?? 0, pnlPct: t.pnl_pct, holdDays: t.hold_days,
        holdMin: null, exitReason: null, strat: (t.strategy_tag || t.classification) ? `manual_${t.strategy_tag ?? t.classification}` : null,
        status: 'closed', entryDate: t.open_date, exitDate: t.close_date, source: 'schwab',
        eg: t.entry_grade ?? null, xg: t.exit_grade ?? null,
        entryTimeFull: t.entry_time ?? null,
        exitTimeFull: t.exit_time ?? null,
        r: null,
      } as any)
    }
    return result.sort((a, b) => (b.exitDate ?? b.entryDate ?? '').localeCompare(a.exitDate ?? a.entryDate ?? ''))
  }, [journal, schwabJournal])

  const runBatchCritiques = async (useLlm = false) => {
    setBatchCritBusy(true)
    setBatchCritMsg('')
    try {
      const from = getTimeRangeCutoff(timeRange)
      const r = await fetch('/api/v2/journal/ai-critique/batch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          days: _edgeDays[timeRange] ?? 365,
          date_from: from,
          account: acctFilter || undefined,
          limit: 200,
          skip_existing: true,
          use_llm: useLlm,
        }),
      }).then(x => x.json())
      const d = r?.data ?? r
      setBatchCritMsg(`Critiques: ${d.generated ?? 0} new · ${d.cached ?? 0} existing · ${d.errors ?? 0} errors (${d.total ?? 0} scanned)`)
      refetchCritiqueSummaries()
    } catch (e: any) {
      setBatchCritMsg(`Batch failed: ${e?.message || e}`)
    } finally {
      setBatchCritBusy(false)
    }
  }

  // ── Apply BOTH filters (account + time range) — shared across all tabs ──
  const cutoff = getTimeRangeCutoff(timeRange)
  const filtered = useMemo(() => {
    let f = allTrades
    // 'All accounts' = REAL accounts only (operator 2026-06-18: paper trades must not count toward the
    // portfolio's performance). Alpaca Paper is opt-in — pick its chip to see paper.
    if (acctFilter) f = f.filter(t => t.na === acctFilter)
    else f = f.filter(t => t.source !== 'paper')
    f = f.filter(t => (t.exitDate ?? t.entryDate ?? '9999') >= cutoff || t.status === 'open')
    return f
  }, [allTrades, acctFilter, cutoff])
  const realTradeCount = useMemo(() => allTrades.filter(t => t.source !== 'paper').length, [allTrades])

  const closed = filtered.filter(t => t.status === 'closed')
  const open = filtered.filter(t => t.status === 'open')

  // Trade Log: search + quick filter + pagination (computed from the already tab-filtered set)
  const logFiltered = useMemo(() => {
    let v = filtered
    if (logSearch) v = v.filter(t => t.symbol?.toLowerCase().includes(logSearch.toLowerCase()))
    const eqOf = (t: any) => t.entryTimeFull ? eqMap[tk(t.symbol, t.entryTimeFull)] : null
    switch (logQuick) {
      case 'winners': v = v.filter(t => t.pnl > 0); break
      case 'losers': v = v.filter(t => t.pnl < 0); break
      case 'open': v = v.filter(t => t.status === 'open'); break
      case 'poor_exec': v = v.filter(t => eqOf(t)?.execution_grade === 'poor'); break
      case 'top_grade': v = v.filter(t => t.eg === 'A' || t.xg === 'A'); break
      case 'missed_runner': v = v.filter(t => eqOf(t)?.missed_opportunity_grade === 'severe'); break
    }
    return v
  }, [filtered, logSearch, logQuick, eqMap])
  const logPages = Math.max(1, Math.ceil(logFiltered.length / LOG_PAGE_SIZE))
  const logPageSafe = Math.min(logPage, logPages - 1)
  const logSorted = useMemo(() => {
    const rows = [...logFiltered]
    rows.sort((a, b) => {
      let av: any = (a as any)[sortCol], bv: any = (b as any)[sortCol]
      if (av == null) av = ''; if (bv == null) bv = ''
      if (typeof av === 'number' && typeof bv === 'number') return sortDir === 'asc' ? av - bv : bv - av
      return sortDir === 'asc' ? String(av).localeCompare(String(bv)) : String(bv).localeCompare(String(av))
    })
    return rows
  }, [logFiltered, sortCol, sortDir])
  const logPaged = logSorted.slice(logPageSafe * LOG_PAGE_SIZE, (logPageSafe + 1) * LOG_PAGE_SIZE)
  const onSortCol = (col: string) => { if (sortCol === col) setSortDir(d => d === 'asc' ? 'desc' : 'asc'); else { setSortCol(col); setSortDir('desc') } }
  const exportCsv = async () => {
    const q = `/api/v2/journal/export?days=${_edgeDays[timeRange] ?? 365}${acctFilter ? `&account=${acctFilter}` : ''}`
    const r = await fetch(q).then(x => x.json())
    if (r?.csv) {
      const blob = new Blob([r.csv], { type: 'text/csv' })
      const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = 'trade_in_view_export.csv'; a.click()
    }
  }
  const applySavedFilter = (p: FilterPayload) => {
    if (p.account !== undefined) setAcctFilter(p.account)
    if (p.timeRange) setTimeRange(p.timeRange as typeof TIME_RANGES[number])
    if (p.logQuick) setLogQuick(p.logQuick)
    if (p.logSearch !== undefined) setLogSearch(p.logSearch)
  }

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
        <button onClick={() => setAcctFilter('')} title="Real accounts only — paper trades are opt-in (pick the Alpaca Paper chip)" style={{ fontSize: 10, padding: '3px 10px', borderRadius: 6, border: 'none', cursor: 'pointer', background: !acctFilter ? 'rgba(96,165,250,.2)' : 'var(--bg2)', color: !acctFilter ? '#60a5fa' : 'var(--text3)' }}>
          All real ({realTradeCount})
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
      <div className="hub-title-row">
        <div>
          <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--text0)' }}>TradeInView</div>
          <div style={{ fontSize: 11, color: 'var(--text3)' }}>Trading journal & performance analytics · {realTradeCount} real trades · {Math.max(0, accountCounts.length - 1)} accounts <span style={{ color: 'var(--text4)' }}>· +{allTrades.length - realTradeCount} paper (opt-in)</span></div>
        </div>
        <div className="hub-tabs">
          {TABS.map(t => (
            <button key={t} onClick={() => setTab(t)} style={{
              padding: '4px 12px', fontSize: 11, borderRadius: 5, border: 'none', cursor: 'pointer',
              background: tab === t ? 'rgba(96,165,250,.15)' : 'var(--bg2)',
              color: tab === t ? '#60a5fa' : 'var(--text3)', fontWeight: tab === t ? 700 : 400,
              position: 'relative',
            }}>
              {t}
              {t === 'Tagging Queue' && tagQueueNeed > 0 && (
                <span style={{ marginLeft: 5, fontSize: 8, padding: '1px 5px', borderRadius: 8, background: '#ef4444', color: '#fff', fontWeight: 700 }}>{tagQueueNeed}</span>
              )}
            </button>
          ))}
        </div>
      </div>

      {/* Shared filters — persists across ALL tabs */}
      <SavedFilterBar current={{ account: acctFilter, timeRange, logQuick, logSearch }} onApply={applySavedFilter} />
      {filterBar}
      <div style={{ display: 'flex', gap: 8, marginBottom: 10 }}>
        <button onClick={exportCsv} style={{ fontSize: 9, padding: '3px 10px', borderRadius: 4, border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text2)', cursor: 'pointer' }}>⬇ Export CSV</button>
        <button onClick={() => fetch('/api/v2/journal/bulk-suggest', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })} style={{ fontSize: 9, padding: '3px 10px', borderRadius: 4, border: '1px solid var(--border)', background: 'var(--bg2)', color: '#f59e0b', cursor: 'pointer' }}>⚡ Auto-classify unannotated</button>
        <button onClick={() => fetch('/api/v2/journal/reminder', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })} style={{ fontSize: 9, padding: '3px 10px', borderRadius: 4, border: '1px solid var(--border)', background: 'var(--bg2)', color: '#c084fc', cursor: 'pointer' }}>📲 Review reminder</button>
        <button onClick={() => setCompareOpen(true)} disabled={closed.length < 2} style={{ fontSize: 9, padding: '3px 10px', borderRadius: 4, border: '1px solid var(--border)', background: 'var(--bg2)', color: '#86efac', cursor: closed.length < 2 ? 'default' : 'pointer', opacity: closed.length < 2 ? 0.5 : 1 }}>⇄ Compare win/loss</button>
        <button disabled={batchCritBusy || closed.length === 0} onClick={() => runBatchCritiques(false)}
          title="Generate deterministic AI critiques for closed trades in range (skips existing)"
          style={{ fontSize: 9, padding: '3px 10px', borderRadius: 4, border: '1px solid rgba(167,139,250,.4)', background: 'rgba(167,139,250,.12)', color: '#c4b5fd', cursor: batchCritBusy ? 'wait' : 'pointer', opacity: batchCritBusy ? 0.6 : 1 }}>
          {batchCritBusy ? '… generating critiques' : '🤖 Generate AI critiques'}
        </button>
        <button disabled={batchCritBusy} onClick={() => runBatchCritiques(true)}
          title="Regenerate with Grok narrative (slower)"
          style={{ fontSize: 9, padding: '3px 10px', borderRadius: 4, border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text3)', cursor: batchCritBusy ? 'wait' : 'pointer' }}>
          Grok batch
        </button>
      </div>
      {batchCritMsg && <div style={{ fontSize: 10, color: '#c4b5fd', marginBottom: 8 }}>{batchCritMsg}</div>}

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
              { l: 'Journal win rate', v: `${kpis.wr}%`, c: kpis.wr >= 55 ? '#22c55e' : '#f59e0b', tip: 'Wins ÷ resolved trades (excludes $0 scratches). 55%+ is the target.' },
              { l: 'P. Factor', v: kpis.pf.toFixed(2), c: 'var(--text0)', tip: 'Profit factor = gross wins ÷ gross losses. >1 profitable, >2 strong.' },
              { l: 'Expectancy', v: fmt$(kpis.expectancy, 0), c: kpis.expectancy >= 0 ? '#22c55e' : '#ef4444', tip: 'Average realized $ per closed trade — your edge per trade (total P&L ÷ closed count).' },
              (() => { const rs = closed.map(getR).filter(x => x.r != null).map(x => x.r as number); const a = rs.length ? rs.reduce((s, r) => s + r, 0) / rs.length : null; return { l: 'Avg R', v: a != null ? `${a.toFixed(2)}R` : '—', c: a == null ? 'var(--text3)' : a >= 0 ? '#22c55e' : '#ef4444', tip: `Average R-multiple over ${rs.length} closed trades with risk data. Paper = real planned-stop R; Schwab = ~proxy (reward ÷ max adverse excursion). Risk-adjusted edge.` } })(),
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
                      <span style={{ color: 'var(--text2)', width: 40, textAlign: 'right' }} title="Avg R-multiple (paper = real, ~ = Schwab proxy)">{(() => { const rs = closed.filter(t => (t.strat ?? '(unclassified)') === s.strategy).map(getR).filter(x => x.r != null).map(x => x.r as number); return rs.length ? `${(rs.reduce((a, b) => a + b, 0) / rs.length).toFixed(1)}R` : '—' })()}</span>
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

          {/* Daily Execution Coaching Queue (advisory) */}
          <ExecutionCoachPanel onDrill={onDrill} onReplay={(sym) => { const t = closed.find(x => x.symbol === sym); if (t) setChartTrade(buildReplayTrade({ ...t, exec: eqMap[tk(t.symbol, t.entryTimeFull ?? '')] })) }} />

          {/* Trade Log — actionable cards, filterable + paginated */}
          <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8, marginBottom: 8 }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)' }}>Trade Log ({logFiltered.length})</div>
              <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                <button onClick={() => setLogView('cards')} style={{ fontSize: 9, padding: '3px 8px', borderRadius: 4, border: '1px solid var(--border)', background: logView === 'cards' ? 'rgba(96,165,250,.2)' : 'var(--bg2)', color: logView === 'cards' ? '#60a5fa' : 'var(--text3)', cursor: 'pointer' }}>Cards</button>
                <button onClick={() => setLogView('table')} style={{ fontSize: 9, padding: '3px 8px', borderRadius: 4, border: '1px solid var(--border)', background: logView === 'table' ? 'rgba(96,165,250,.2)' : 'var(--bg2)', color: logView === 'table' ? '#60a5fa' : 'var(--text3)', cursor: 'pointer' }}>Table</button>
                <input value={logSearch} onChange={e => { setLogSearch(e.target.value); setLogPage(0) }} placeholder="search symbol…"
                  style={{ fontSize: 11, padding: '4px 8px', background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 5, color: 'var(--text0)', width: 140 }} />
              </div>
            </div>
            {/* quick filters */}
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 10 }}>
              {[['all', 'All'], ['winners', 'Winners'], ['losers', 'Losers'], ['open', 'Open'], ['top_grade', 'A-grade'], ['poor_exec', 'Poor execution'], ['missed_runner', 'Missed runner']].map(([k, lbl]) => (
                <button key={k} onClick={() => { setLogQuick(k); setLogPage(0) }}
                  style={{ fontSize: 10, padding: '3px 9px', borderRadius: 5, cursor: 'pointer', border: '1px solid var(--border)', background: logQuick === k ? 'rgba(96,165,250,.18)' : 'var(--bg2)', color: logQuick === k ? '#60a5fa' : 'var(--text3)', fontWeight: logQuick === k ? 700 : 400 }}>{lbl}</button>
              ))}
            </div>
            {logView === 'table' ? (
              <TradeLogTable trades={logPaged} sortCol={sortCol} sortDir={sortDir} onSort={onSortCol}
                critiqueByKey={critiqueByKey}
                onRow={t => setDetailTrade({ ...t, trade_key: `${t.symbol}:${t.account ?? t.na}:${t.exitDate}` })} />
            ) : (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(310px,1fr))', gap: 10 }}>
              {logPaged.map((t, i) => {
                const trk = `${t.symbol}:${t.account ?? t.na}:${t.exitDate}`
                const crit = critiqueByKey[trk]
                const eq = t.entryTimeFull ? eqMap[tk(t.symbol, t.entryTimeFull)] : null
                const { r, proxy } = getR(t)
                const won = t.status !== 'open' && t.pnl > 0, lost = t.status !== 'open' && t.pnl < 0
                const hold = t.holdMin != null ? (t.holdMin < 60 ? `${Math.round(t.holdMin)}m` : t.holdMin < 1440 ? `${Math.round(t.holdMin / 60)}h` : `${Math.round(t.holdMin / 1440)}d`) : t.holdDays != null ? `${t.holdDays}d` : '—'
                return (
                  <div key={`${t.id}-${i}`} style={{ background: 'var(--bg2)', border: '1px solid var(--border)', borderLeft: `4px solid ${acctColor(t.na)}`, borderRadius: 9, padding: 11 }}>
                    {/* header: symbol + pills */}
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 6 }}>
                      <div>
                        <span style={{ fontSize: 16, fontWeight: 700, color: 'var(--text0)', fontFamily: 'monospace' }}>{t.symbol}</span>
                        <span style={{ fontSize: 9, color: 'var(--text3)', marginLeft: 6 }}>{t.shares} sh · {hold}</span>
                        {(() => { const o = outcomesData?.outcomes?.[String(t.symbol).toUpperCase()]; return o?.origin
                          ? <span title="auto-detected discovery origin — where this trade was first surfaced" style={{ fontSize: 8, fontWeight: 700, padding: '2px 6px', borderRadius: 4, marginLeft: 6, background: 'rgba(96,165,250,.14)', color: '#60a5fa' }}>via {o.origin}</span>
                          : null })()}
                      </div>
                      <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
                        <span style={{ fontSize: 8, fontWeight: 700, padding: '2px 7px', borderRadius: 4, background: `${acctColor(t.na)}22`, color: acctColor(t.na) }}>{ACCT_LABEL[t.na] ?? t.na}</span>
                        {t.status === 'open'
                          ? <span style={{ fontSize: 8, fontWeight: 700, padding: '2px 7px', borderRadius: 4, background: 'rgba(96,165,250,.18)', color: '#60a5fa' }}>OPEN</span>
                          : <span style={{ fontSize: 8, fontWeight: 700, padding: '2px 7px', borderRadius: 4, background: won ? 'rgba(34,197,94,.18)' : lost ? 'rgba(239,68,68,.18)' : 'var(--bg1)', color: won ? '#22c55e' : lost ? '#ef4444' : 'var(--text3)' }}>{won ? 'WIN' : lost ? 'LOSS' : 'SCRATCH'}</span>}
                        {t.status === 'open' && (() => { const o = outcomesData?.outcomes?.[String(t.symbol).toUpperCase()]; if (!o?.held || o.unrealized_pnl_pct == null) return null
                          const up = o.unrealized_pnl_pct >= 0
                          return <span title={`currently held${o.held_since ? ` since ${String(o.held_since).slice(0, 10)}` : ''}${o.origin ? ` · origin: ${o.origin}` : ''} · unrealized $${o.unrealized_pnl ?? '?'} (monitoring till sale)`}
                            style={{ fontSize: 8, fontWeight: 800, padding: '2px 7px', borderRadius: 4, background: up ? 'rgba(96,165,250,.18)' : 'rgba(245,158,11,.18)', color: up ? '#60a5fa' : '#f59e0b' }}>● held {up ? '+' : ''}{o.unrealized_pnl_pct}% unrl</span> })()}
                      </div>
                    </div>
                    {/* P&L + R */}
                    <div style={{ display: 'flex', gap: 10, alignItems: 'baseline', marginTop: 7 }}>
                      <span style={{ fontSize: 20, fontWeight: 700, color: t.status === 'open' ? '#60a5fa' : t.pnl >= 0 ? '#22c55e' : '#ef4444' }}>{t.status === 'open' ? 'OPEN' : fmt$(t.pnl, 0)}</span>
                      {r != null && <span style={{ fontSize: 12, fontWeight: 700, color: r >= 0 ? '#86efac' : '#fca5a5' }} title={proxy ? 'Proxy R (reward ÷ MAE)' : 'R-multiple'}>{proxy ? '~' : ''}{r.toFixed(1)}R</span>}
                      <span style={{ fontSize: 9, color: 'var(--text3)' }}>{t.entryDate ?? '—'} → {t.exitDate ?? '—'}</span>
                    </div>
                    {/* pills: strategy, grades, execution */}
                    <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginTop: 8 }}>
                      <span style={{ fontSize: 8, fontWeight: 600, padding: '2px 7px', borderRadius: 4, background: 'var(--bg1)', color: 'var(--text2)' }}>{t.strat ?? 'unclassified'}</span>
                      {(t.eg || t.xg) && <span title={gradeExplain(t, eq)} style={{ fontSize: 8, fontWeight: 700, padding: '2px 7px', borderRadius: 4, background: 'var(--bg1)', cursor: 'help' }}><span style={{ color: 'var(--text3)' }}>E</span><span style={{ color: gradeColor(t.eg) }}>{t.eg ?? '·'}</span> <span style={{ color: 'var(--text3)' }}>X</span><span style={{ color: gradeColor(t.xg) }}>{t.xg ?? '·'}</span> ⓘ</span>}
                      {eq && <span title={eq.grok_what_to_do_next_time || eq.computed_summary || ''} style={{ fontSize: 8, fontWeight: 700, padding: '2px 7px', borderRadius: 4, background: (EXEC_C[eq.execution_grade] || 'var(--text3)') + '22', color: EXEC_C[eq.execution_grade] || 'var(--text3)' }}>{eq.execution_grade} cap{Math.round((eq.capture_ratio ?? 0) * 100)}%{eq.missed_opportunity_grade === 'severe' ? ' ⚠' : ''}</span>}
                      {crit?.has_critique && (
                        <span title={crit.summary || crit.takeaway} style={{ fontSize: 8, fontWeight: 600, padding: '2px 7px', borderRadius: 4, background: crit.stale ? 'rgba(245,158,11,.15)' : 'rgba(167,139,250,.15)', color: crit.stale ? '#f59e0b' : '#c4b5fd', maxWidth: 160, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' as const }}>
                          🤖 {crit.stale ? 'stale' : (crit.takeaway?.slice(0, 36) || 'critique')}
                        </span>
                      )}
                    </div>
                    {/* grok lesson */}
                    {eq?.grok_what_to_do_next_time && <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 6, fontStyle: 'italic', overflow: 'hidden', textOverflow: 'ellipsis', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical' as const }}>{eq.grok_what_to_do_next_time}</div>}
                    {/* action buttons */}
                    <div style={{ display: 'flex', gap: 6, marginTop: 9 }}>
                      <button onClick={() => setChartTrade(buildReplayTrade({ ...t, exec: eq }))}
                        style={{ fontSize: 9, padding: '3px 9px', borderRadius: 4, border: '1px solid var(--border)', background: 'var(--bg1)', color: 'var(--text2)', cursor: 'pointer' }}>📈 Replay</button>
                      <button onClick={() => setDetailTrade({ ...t, trade_key: `${t.symbol}:${t.account ?? t.na}:${t.exitDate}` })}
                        style={{ fontSize: 9, padding: '3px 9px', borderRadius: 4, border: '1px solid var(--border)', background: 'var(--bg1)', color: 'var(--text2)', cursor: 'pointer' }}>Details</button>
                      {t.status !== 'open' && (() => { const trk = `${t.symbol}:${t.account ?? t.na}:${t.exitDate}`; return (
                        <button onClick={() => setReviewOpen(reviewOpen === trk ? null : trk)}
                          style={{ fontSize: 9, padding: '3px 9px', borderRadius: 4, border: '1px solid var(--border)', background: reviewOpen === `${t.symbol}:${t.account ?? t.na}:${t.exitDate}` ? 'rgba(168,85,247,.2)' : 'var(--bg1)', color: '#c084fc', cursor: 'pointer' }}>📝 Tag</button>
                      ) })()}
                    </div>
                    {t.status !== 'open' && reviewOpen === `${t.symbol}:${t.account ?? t.na}:${t.exitDate}` && (
                      <TradeReviewForm tradeKey={`${t.symbol}:${t.account ?? t.na}:${t.exitDate}`} symbol={t.symbol}
                        account={t.account ?? t.na} closedDate={t.exitDate} onClose={() => setReviewOpen(null)} />
                    )}
                  </div>
                )
              })}
            </div>
            )}
            {logFiltered.length === 0 && <div style={{ fontSize: 11, color: 'var(--text3)', textAlign: 'center', padding: 20 }}>No trades match this filter.</div>}
            {/* pagination */}
            {logPages > 1 && (
              <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', gap: 10, marginTop: 12 }}>
                <button disabled={logPageSafe === 0} onClick={() => setLogPage(logPageSafe - 1)} style={{ fontSize: 11, padding: '4px 12px', borderRadius: 5, border: '1px solid var(--border)', background: 'var(--bg2)', color: logPageSafe === 0 ? 'var(--text3)' : 'var(--text1)', cursor: logPageSafe === 0 ? 'default' : 'pointer' }}>‹ Prev</button>
                <span style={{ fontSize: 10, color: 'var(--text3)' }}>Page {logPageSafe + 1} of {logPages} · {logFiltered.length} trades</span>
                <button disabled={logPageSafe >= logPages - 1} onClick={() => setLogPage(logPageSafe + 1)} style={{ fontSize: 11, padding: '4px 12px', borderRadius: 5, border: '1px solid var(--border)', background: 'var(--bg2)', color: logPageSafe >= logPages - 1 ? 'var(--text3)' : 'var(--text1)', cursor: logPageSafe >= logPages - 1 ? 'default' : 'pointer' }}>Next ›</button>
              </div>
            )}
          </div>
          <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 4 }}>
            Sources: paper ATM + Schwab trade_closed (up to 2000 rows). Grades from backtest replay where available.
          </div>
        </>
      )}
      {chartTrade && <TradeReplayChart trade={chartTrade} onClose={() => setChartTrade(null)} />}
      {detailTrade && (
        <TradeInViewDetail trade={detailTrade} onClose={() => setDetailTrade(null)}
          onReplay={() => { setChartTrade(buildReplayTrade(detailTrade)); setDetailTrade(null) }} />
      )}

      {/* ════════ ANALYTICS TAB ════════ */}
      {tab === 'Analytics' && (
        <>
          <div style={{ marginBottom: 14 }}><ZellaScoreCard account={acctFilter || undefined} days={_edgeDays[timeRange] ?? 365} /></div>
          <div style={{ marginBottom: 14 }}>
            <MonteCarloPanel account={acctFilter || undefined} days={_edgeDays[timeRange] ?? 365} />
          </div>
          {/* Performance KPIs — computed from filtered trades */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 8, marginBottom: 14 }}>
            {[
              { l: 'Journal win rate', v: `${kpis.wr}%`, c: kpis.wr >= 55 ? '#22c55e' : '#f59e0b' },
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

          {/* ═══ Edge analytics (real round-trips: time/session/equity/R/strategy) ═══ */}
          {edge.ok && edge.overall?.trades > 0 && (() => {
            const ta = edge.time_analysis || {}; const ec = edge.equity_curve || {}; const sb = edge.setup_breakdown || {}
            const barColor = (v: number) => (v >= 0 ? '#22c55e' : '#ef4444')
            const Bars = ({ title, rows, xk }: any) => (
              <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14 }}>
                <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>{title}</div>
                <ResponsiveContainer width="100%" height={150}>
                  <BarChart data={rows}><XAxis dataKey={xk} tick={{ fontSize: 9, fill: 'var(--text3)' }} />
                    <YAxis tick={{ fontSize: 9, fill: 'var(--text3)' }} width={42} />
                    <Tooltip contentStyle={{ background: 'var(--bg1)', border: '1px solid var(--border)', fontSize: 10 }}
                      formatter={(v: any, n: any) => [n === 'net_pnl' ? fmt$(v, 0) : v, n]} />
                    <Bar dataKey="net_pnl">{rows.map((r: any, i: number) => <Cell key={i} fill={barColor(r.net_pnl)} />)}</Bar>
                  </BarChart></ResponsiveContainer>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 4 }}>
                  {rows.map((r: any) => <span key={r.label} style={{ fontSize: 8.5, color: 'var(--text3)' }}>{r.label}: <b style={{ color: r.win_rate >= 50 ? '#22c55e' : '#f59e0b' }}>{r.win_rate}%</b> ({r.trades}t)</span>)}
                </div>
              </div>
            )
            return (
              <>
                {(ec.underwater?.length > 1 || ec.drawdown_series?.length > 1) && (
                  <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14, marginBottom: 14 }}>
                    <DrawdownChart
                      title="Underwater / drawdown"
                      data={(ec.drawdown_series || ec.underwater || []).map((p: any, i: number) => ({
                        date: p.date?.slice?.(5) || p.label || String(i),
                        drawdown: Number(p.drawdown ?? p.value ?? 0),
                        value: Number(p.equity ?? p.cumulative ?? 0),
                      }))}
                      valueKey="drawdown"
                    />
                  </div>
                )}
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8, margin: '14px 0' }}>
                  {[
                    { l: 'Net P&L (round-trips)', v: fmt$(ec.net_pnl ?? 0, 0), c: (ec.net_pnl ?? 0) >= 0 ? '#22c55e' : '#ef4444' },
                    { l: 'Max Drawdown', v: fmt$(-(ec.max_drawdown ?? 0), 0), c: '#ef4444' },
                    { l: 'Recovery Factor', v: ec.recovery_factor != null ? ec.recovery_factor.toFixed(1) : '—', c: (ec.recovery_factor ?? 0) >= 3 ? '#22c55e' : '#f59e0b' },
                    { l: 'Sharpe (per-trade)', v: (ec.sharpe_per_trade ?? 0).toFixed(2), c: (ec.sharpe_per_trade ?? 0) >= 0.2 ? '#22c55e' : '#f59e0b' },
                  ].map(k => (
                    <div key={k.l} style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 8, padding: '10px 12px', textAlign: 'center' }}>
                      <div style={{ fontSize: 18, fontWeight: 700, color: k.c, fontFamily: 'monospace' }}>{k.v}</div>
                      <div style={{ fontSize: 9, color: 'var(--text3)' }}>{k.l}</div>
                    </div>
                  ))}
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14, marginBottom: 14 }}>
                  {(ta.by_day_of_week?.length > 0) && <Bars title="P&L by Day of Week" rows={ta.by_day_of_week} xk="label" />}
                  {(ta.by_session?.length > 0) && <Bars title="P&L by Session (ET)" rows={ta.by_session} xk="label" />}
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14, marginBottom: 14 }}>
                  {/* By strategy */}
                  <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14 }}>
                    <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Edge by Strategy</div>
                    {(sb.by_strategy || []).map((s: any) => (
                      <div key={s.strategy} style={{ display: 'flex', justifyContent: 'space-between', padding: '3px 6px', borderBottom: '1px solid var(--border)', fontSize: 10 }}>
                        <span style={{ color: 'var(--text2)' }}>{s.strategy}</span>
                        <div style={{ display: 'flex', gap: 10 }}>
                          <span style={{ color: 'var(--text3)' }}>{s.trades}t</span>
                          <span style={{ color: s.win_rate >= 50 ? '#22c55e' : '#f59e0b' }}>{s.win_rate}%</span>
                          <span style={{ color: s.net_pnl >= 0 ? '#22c55e' : '#ef4444', fontWeight: 600, width: 64, textAlign: 'right' }}>{fmt$(s.net_pnl, 0)}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                  {/* R distribution */}
                  <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14 }}>
                    <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Realized-R Distribution
                      <span style={{ fontSize: 9, fontWeight: 400, color: 'var(--text3)', marginLeft: 6 }}>avg {edge.r_distribution?.avg_realized_r ?? '—'}R · n={edge.r_distribution?.sample ?? 0}</span></div>
                    {(edge.r_distribution?.sample ?? 0) === 0 ? <div style={{ fontSize: 10, color: 'var(--text3)' }}>No R data yet — reviewed trades with planned/realized R will populate this.</div> : (
                      <ResponsiveContainer width="100%" height={150}>
                        <BarChart data={edge.r_distribution.histogram}><XAxis dataKey="bucket" tick={{ fontSize: 8, fill: 'var(--text3)' }} />
                          <YAxis tick={{ fontSize: 9, fill: 'var(--text3)' }} width={28} allowDecimals={false} />
                          <Tooltip contentStyle={{ background: 'var(--bg1)', border: '1px solid var(--border)', fontSize: 10 }} />
                          <Bar dataKey="count">{edge.r_distribution.histogram.map((b: any, i: number) => <Cell key={i} fill={b.bucket.includes('-') && !b.bucket.includes('..') ? '#ef4444' : b.bucket.startsWith('-') || b.bucket.startsWith('<') ? '#ef4444' : '#22c55e'} />)}</Bar>
                        </BarChart></ResponsiveContainer>
                    )}
                  </div>
                </div>
              </>
            )
          })()}

          {/* ═══ Ask the journal (AI Q&A) ═══ */}
          <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14, marginBottom: 14 }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', marginBottom: 6 }}>💬 Ask your journal</div>
            <div style={{ fontSize: 9, color: 'var(--text3)', marginBottom: 8 }}>Natural-language Q&A over your real trade analytics — pick Grok or ChatGPT</div>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              <input value={jq} onChange={e => setJq(e.target.value)} placeholder="ask about your trading…"
                onKeyDown={e => { if (e.key === 'Enter' && jq.trim() && !jBusy) { void jAsk('grok') } }}
                style={{ flex: 1, minWidth: 180, fontSize: 12, padding: '8px 10px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text0)' }} />
              {(['grok', 'chatgpt'] as const).map(lane => {
                const color = lane === 'grok' ? '#1d9bf0' : '#10a37f'
                return (
                  <button key={lane} type="button" disabled={!!jBusy || !jq.trim()}
                    onClick={() => void jAsk(lane)}
                    style={{ padding: '8px 14px', borderRadius: 6, fontWeight: 800, fontSize: 12, cursor: jBusy ? 'wait' : 'pointer',
                      border: `1px solid ${color}66`, background: `${color}14`, color, opacity: jBusy && jBusy !== lane ? 0.5 : 1 }}>
                    {jBusy === lane ? '…' : lane === 'grok' ? '▶ Grok' : '▶ ChatGPT'}
                  </button>
                )
              })}
            </div>
            {jAns && (
              <div style={{ marginTop: 10, padding: 10, background: 'var(--bg2)', borderRadius: 6, fontSize: 11.5, color: 'var(--text1)', lineHeight: 1.6, whiteSpace: 'pre-wrap' }}>
                {jAns.ok === false || jAns.manual_required
                  ? <span style={{ color: '#ef4444' }}>⚠ {jAns.error || 'blocked — pick ▶ Grok or ▶ ChatGPT'}</span>
                  : jAns.answer}
                {jAns.model && jAns.ok !== false && !jAns.manual_required && (
                  <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 6 }}>via {jAns.model}{jAns.lane ? ` · ${jAns.lane}` : ''} · over your {acctFilter ? (ACCT_LABEL[acctFilter] ?? acctFilter) : 'all-account'} journal ({timeRange})</div>
                )}
              </div>
            )}
          </div>
        </>
      )}

      {tab === 'Tagging Queue' && (
        <TaggingQueuePanel account={acctFilter || undefined} days={_edgeDays[timeRange] ?? 365} acctLabel={ACCT_LABEL} />
      )}

      {tab === 'By Ticker' && <ByTickerPanel account={acctFilter || undefined} from={cutoff || undefined} />}

      {tab === 'Exit Intel' && <ExitIntelligencePanel account={acctFilter || undefined} days={_edgeDays[timeRange] ?? 365} />}

      {tab === 'Behavioral' && <BehavioralPanel account={acctFilter || undefined} days={_edgeDays[timeRange] ?? 365} />}

      {tab === 'Session' && <SessionRecapPanel />}

      {tab === 'Advanced' && (
        <AdvancedReportsPanel
          account={acctFilter || undefined}
          days={_edgeDays[timeRange] ?? 365}
          initialCritiqueQuery={critiqueQuery}
          onOpenTrade={(tk) => {
            const hit = allTrades.find((t: any) => t.trade_key === tk || `${t.symbol}:${t.account}:${t.exitDate}` === tk)
            if (hit) setDetailTrade(hit)
          }}
        />
      )}

      {compareOpen && <TradeCompareReplay trades={closed} onClose={() => setCompareOpen(false)} />}

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
      {tab === 'Backtesting' && <><ExecutionHypothesesPanel /><BacktestPanel onDrill={onDrill} sharedAccount={acctFilter} sharedDateFrom={cutoff} /></>}

      {/* ════════ REAL ACCOUNTS (Schwab) — API-authoritative round-trips, separate from paper ════════ */}
      {tab === 'Real Accounts' && <SchwabJournal />}

      {tab === 'Import' && (
        <div style={{ display: 'grid', gap: 14 }}>
          <CsvImportPanel />
          <ManualEntryPanel />
          <OptionsJournalPanel account={acctFilter || undefined} days={_edgeDays[timeRange] ?? 365} />
        </div>
      )}
    </div>
  )
}
