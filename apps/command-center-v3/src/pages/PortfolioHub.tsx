import W7Lookthrough, { W7Allocation } from '../components/W7Lookthrough'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import RotationPublicationNotice from '../components/RotationPublicationNotice'
import { useRotationAvailability } from '../hooks/useRotationAvailability'
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip } from 'recharts'
import { fmt$ } from '../lib/format'
import { pricingStampLine } from '../lib/pricingStamp'
import type { DrillContext } from '../components/DetailDrawer'
import AskAgents from '../components/AskAgents'
import { mergeLiveStop } from '../lib/stopReviewTooltip'
import { storedStopFor, storedStopsAsOf } from '../lib/storedStops'
import { useAnalystReportMap } from '../hooks/useAnalystReportMap'
import StopManagement from '../components/StopManagement'
import RedeployPanel from '../components/RedeployPanel'
import AllocationPanel from '../components/AllocationPanel'
import ReturnsPanel from '../components/ReturnsPanel'
import DividendsPanel from '../components/DividendsPanel'
import HoldingsTableView, { type HoldingsTableRowContext } from '../components/HoldingsTableView'
import HoldingsSideDrawer from '../components/HoldingsSideDrawer'
import ShareReconciliationModal, { type ShareDriftItem } from '../components/ShareReconciliationModal'
import type { HoldingsDetailContext } from '../components/HoldingsDetailPanel'
import type { HoldingsCvdMode } from '../lib/holdingsTerminalTokens'
import { accountFullName, buildHoldingsRowModel, isCashHolding } from '../lib/holdingsRowModel'
import { useTerminalUi } from '../lib/terminalUi'
import { hubTitle, hubSubtitle, hubTab, hubPanel } from '../lib/terminalHubChrome'
import PortfolioDeskHealth from '../components/PortfolioDeskHealth'
import ForecastPanel from '../components/ForecastPanel'
import TaxPanel from '../components/TaxPanel'
import {
  parsePortfolioDeepLink,
  pickHoldingForDeepLink,
  resolvePortfolioSig,
  type PortfolioSignalTab,
} from '../lib/portfolioDeepLink'
import { downloadHoldingsCsv } from '../lib/exportHoldingsCsv'
import { BB, T, DASH } from '../lib/watchTokens'

interface Props { onDrill: (ctx: DrillContext) => void }
const TABS = ['Holdings', 'Allocation', 'Look-through', 'Returns', 'Dividends', 'Forecast', 'Tax', 'Redeploy', 'Stop Management'] as const
const COLORS = ['#60a5fa', '#22c55e', '#f59e0b', '#a855f7', '#ef4444', '#06b6d4', '#e879f9', '#fb923c']

const ACCT_COLORS = ['#60a5fa', '#22c55e', '#f59e0b', '#a855f7', '#ef4444', '#06b6d4', '#e879f9']

// Row at-a-glance helpers
const rsiZoneColor = (s?: string) => s === 'oversold' ? '#22c55e' : s === 'overbought' ? '#f59e0b' : 'var(--text3)'
const signalColor = (s?: string) => {
  const t = (s || '').toUpperCase()
  if (['ADD', 'BUY', 'STRONG_BUY', 'ACCUMULATE'].includes(t)) return '#22c55e'
  if (['TRIM', 'SELL', 'REDUCE', 'EXIT'].includes(t)) return '#ef4444'
  if (['MONITOR', 'WATCH', 'CAUTION'].includes(t)) return '#f59e0b'
  return 'var(--text3)'   // HOLD / NEUTRAL
}
// Unrealized P/L ($ and %) where real cost basis exists (401k funds have none → null → "—")
const plMetrics = (h: any): { dollars: number | null; pct: number | null } => {
  const cb = h.cost_basis
  if (cb == null || cb <= 0) return { dollars: null, pct: null }
  const dollars = h.gain_loss != null
    ? Number(h.gain_loss)
    : (h.market_value != null ? Number(h.market_value) - Number(cb) : null)
  const pct = h.gain_loss_pct != null
    ? Number(h.gain_loss_pct)
    : (dollars != null ? (dollars / Number(cb)) * 100 : null)
  return { dollars, pct }
}

// ── signal sub-tab buckets (operator request 2026-06-12) ──
const SIGNAL_TABS: [string, string[]][] = [
  ['All', []],
  ['Buy/Add', ['ADD', 'BUY', 'STRONG_BUY', 'ACCUMULATE']],
  ['Hold', ['HOLD', 'NEUTRAL']],
  ['Watch', ['WATCH', 'MONITOR', 'CAUTION']],
  ['Trim/Sell', ['TRIM', 'SELL', 'REDUCE', 'EXIT']],
]
// LLM provenance badge styling — which model lane reviewed this symbol (advisory research only)
const LLM_LANE: Record<string, { label: string; c: string }> = {
  local: { label: 'GEMMA', c: '#2dd4bf' },
  grok: { label: 'GROK', c: '#f59e0b' },
  chatgpt: { label: 'GPT', c: '#a3e635' },
  claude: { label: 'CLAUDE', c: '#d97757' },
}
const LLM_HEALTH_COLOR: Record<string, string> = {
  HEALTHY: '#22c55e', WATCH: '#f59e0b', CONCERN: '#ef4444', TRIM: '#fb923c', HOLD: '#60a5fa',
}
function LlmHealthChip({ health, action }: { health?: string; action?: string }) {
  if (!health) return null
  const c = LLM_HEALTH_COLOR[String(health).toUpperCase()] || 'var(--text3)'
  return (
    <span title={action ? `LLM action: ${action}` : 'Holdings LLM health assessment'}
      style={{ fontSize: 7.5, fontWeight: 800, padding: '1px 6px', borderRadius: 3,
        background: `${c}1f`, color: c, border: `1px solid ${c}44`, cursor: 'help' }}>
      🩺 {health}
    </span>
  )
}

function LlmBadges({ cov }: { cov?: any[] }) {
  if (!cov?.length) return <span title="no LLM research touched this symbol in 30d" style={{ fontSize: 8, color: 'var(--text3)' }}>no LLM review</span>
  const byLane: Record<string, any> = {}
  for (const c of cov) {
    const k = LLM_LANE[c.lane] ? c.lane : 'local'
    if (!byLane[k] || c.last_at > byLane[k].last_at) byLane[k] = c
  }
  return (
    <span style={{ display: 'inline-flex', gap: 3, flexWrap: 'wrap' }}>
      {Object.entries(byLane).map(([lane, c]: any) => {
        const m = LLM_LANE[lane]
        return <span key={lane} title={`${c.model} · ${String(c.last_at).slice(0, 10)} · ${c.n} review${c.n > 1 ? 's' : ''} (advisory research)`}
          style={{ fontSize: 7.5, fontWeight: 800, padding: '1px 5px', borderRadius: 3, letterSpacing: 0.4,
            background: m.c + '1f', color: m.c, border: `1px solid ${m.c}44`, cursor: 'help' }}>
          🤖 {m.label}</span>
      })}
    </span>
  )
}

export default function PortfolioHub({ onDrill }: Props) {
  const [searchParams, setSearchParams] = useSearchParams()
  const resolveTab = (t: string | null): typeof TABS[number] => {
    if (!t) return 'Holdings'
    return (TABS as readonly string[]).includes(t) ? t as typeof TABS[number] : 'Holdings'
  }
  const [tab, setTab] = useState<typeof TABS[number]>(resolveTab(searchParams.get('tab')))
  useEffect(() => {
    try { localStorage.removeItem('cc-v3-holdings-view') } catch { /* private mode */ }
  }, [])
  useEffect(() => {
    const t = resolveTab(searchParams.get('tab'))
    if (t !== tab) setTab(t)
  }, [searchParams, tab])
  const [terminalUi] = useTerminalUi()
  const tabPanel = terminalUi ? hubPanel(terminalUi) : { background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }
  const selectTab = (t: typeof TABS[number]) => {
    setTab(t)
    const next = new URLSearchParams(searchParams)
    if (t === 'Holdings') next.delete('tab')
    else next.set('tab', t)
    setSearchParams(next, { replace: true })
  }
  const [holdingsDrawer, setHoldingsDrawer] = useState<HoldingsDetailContext | null>(null)
  const [drawerTitle, setDrawerTitle] = useState('')
  const [drawerSubtitle, setDrawerSubtitle] = useState('')
  const holdingsCvd: HoldingsCvdMode = 'cvd'
  // ── Account filter (URL-synced, same pattern as tab) ──
  const resolveAcct = (a: string | null): string | null => {
    if (!a || a === 'all' || a === 'null') return null
    return a
  }
  const [acctFilter, setAcctFilter] = useState<string | null>(resolveAcct(searchParams.get('acct')))
  useEffect(() => {
    const a = resolveAcct(searchParams.get('acct'))
    if (a !== acctFilter) setAcctFilter(a)
  }, [searchParams]) // eslint-disable-line react-hooks/exhaustive-deps
  const selectAcct = (a: string | null) => {
    setAcctFilter(a)
    const next = new URLSearchParams(searchParams)
    if (!a) next.delete('acct')
    else next.set('acct', a)
    setSearchParams(next, { replace: true })
  }
  const [sigTab, setSigTab] = useState<PortfolioSignalTab>(resolvePortfolioSig(searchParams.get('sig')))
  useEffect(() => {
    const s = resolvePortfolioSig(searchParams.get('sig'))
    if (s !== sigTab) setSigTab(s)
  }, [searchParams]) // eslint-disable-line react-hooks/exhaustive-deps
  const selectSig = (s: PortfolioSignalTab) => {
    setSigTab(s)
    const next = new URLSearchParams(searchParams)
    if (s === 'All') next.delete('sig')
    else next.set('sig', s)
    setSearchParams(next, { replace: true })
  }
  const [focusKey, setFocusKey] = useState<string | null>(null)
  const deepLinkConsumed = useRef(false)
  // From the Stop Management Adjust modal: jump to a holding's card (its inline gated 2FA / manual-ticket panel).
  const focusHolding = (symbol: string, account: string) => {
    selectTab('Holdings'); selectAcct(account); selectSig('All')
    const key = `${symbol}-${account}`; setFocusKey(key)
    const tryScroll = (n: number) => {
      const el = document.getElementById(`hold-${key}`)
      if (el) { el.scrollIntoView({ behavior: 'smooth', block: 'center' }) }
      else if (n < 12) setTimeout(() => tryScroll(n + 1), 120)
    }
    setTimeout(() => tryScroll(0), 60)
    setTimeout(() => setFocusKey(null), 4000)
  }
  // Diversification gap-fill: LLM design-for-approval + per-ETF propose state
  const [gapDesign, setGapDesign] = useState<any>(null)
  const [gapBusy, setGapBusy] = useState(false)
  const [gapPropose, setGapPropose] = useState<Record<string, string>>({})
  const [holdingPatches, setHoldingPatches] = useState<Record<string, Record<string, unknown>>>({})
  const [protectionPatches, setProtectionPatches] = useState<Record<string, Record<string, unknown>>>({})
  const mergeHolding = (h: any) => {
    const key = `${(h.symbol || '').toUpperCase()}:${h.account}`
    const patch = holdingPatches[key]
    return patch ? { ...h, ...patch } : h
  }
  const mergeProtection = (sym: string, base?: any) => {
    const patch = protectionPatches[sym.toUpperCase()]
    return patch ? { ...(base ?? {}), ...patch } : base
  }
  // Manual broker sync (SnapTrade / Schwab) — operator-triggered, read-only holdings/position pull.
  const [syncState, setSyncState] = useState<{ busy: 'snaptrade' | 'schwab' | 'fidelity_stops' | null; msg: string }>({ busy: null, msg: '' })
  const syncBtn = (active: boolean): React.CSSProperties => ({
    fontSize: 10, fontWeight: 700, padding: '4px 10px', borderRadius: 6, cursor: active ? 'default' : 'pointer',
    border: '1px solid var(--border)', background: active ? 'rgba(96,165,250,.15)' : 'var(--bg2)',
    color: active ? '#60a5fa' : 'var(--text2)', whiteSpace: 'nowrap',
  })
  async function runSync(which: 'snaptrade' | 'schwab') {
    if (syncState.busy) return
    setSyncState({ busy: which, msg: '' })
    try {
      const r = await fetch(`/api/v2/portfolio/sync/${which}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
      const j = await r.json()
      setSyncState({ busy: null, msg: j?.ok ? (j.note || 'sync started ✓') : `error: ${j?.error || 'failed'}` })
    } catch {
      setSyncState({ busy: null, msg: 'request failed' })
    }
  }
  async function runFidelityStopSync() {
    if (syncState.busy) return
    setSyncState({ busy: 'fidelity_stops', msg: '' })
    try {
      const r = await fetch('/api/v2/fidelity-stops/sync', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
      const j = await r.json()
      const d = j?.data ?? j
      const n = Array.isArray(d?.upserted) ? d.upserted.length : 0
      setSyncState({
        busy: null,
        msg: j?.ok !== false && !(d?.errors?.length) ? `Fidelity GTC stops synced (${n}) ✓` : `error: ${j?.error || d?.errors?.[0]?.error || 'failed'}`,
      })
      refetchMonitored()
    } catch {
      setSyncState({ busy: null, msg: 'fidelity stop sync failed' })
    }
  }
  async function designFill() {
    setGapBusy(true); setGapDesign(null)
    try {
      const r = await fetch('/api/v2/lookthrough/design-fill', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
      setGapDesign(await r.json())
    } catch { setGapDesign({ ok: false, error: 'request failed' }) }
    setGapBusy(false)
  }
  async function proposeGapEtf(symbol: string, sleeve: string, rationale: string) {
    setGapPropose(p => ({ ...p, [symbol]: '…' }))
    try {
      const r = await fetch('/api/v2/rotation/propose-etf', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ symbol, direction: 'long', instrument_type: 'etf', sleeve, rationale }) })
      const j = await r.json()
      setGapPropose(p => ({ ...p, [symbol]: j?.ok ? (j.already_exists ? 'exists' : 'proposed ✓') : 'error' }))
    } catch { setGapPropose(p => ({ ...p, [symbol]: 'error' })) }
  }
  // WP-D: tab-scoped fetches — Holdings default stays rich; secondary tabs load on demand.
  const needHoldingsDesk = tab === 'Holdings' || tab === 'Stop Management'
  const needAllocation = tab === 'Allocation'
  const needLookthrough = tab === 'Look-through'
  const needReturns = tab === 'Returns'
  const needDividends = tab === 'Dividends'
  const needForecast = tab === 'Forecast'
  const needTax = tab === 'Tax'
  // These panels render holdings or account choices; other tabs use their own projection.
  const needHoldingsData = needHoldingsDesk || needAllocation || needDividends || needReturns

  const { data: overview } = useApi<any>('/api/v2/overview', 60_000, { enabled: needAllocation || needHoldingsDesk })
  const { data: holdings, loading: holdingsLoading, error: holdingsError, stale: holdingsStale } = useApi<any>('/api/v2/portfolio/holdings', 60_000, { enabled: needHoldingsData })
  const { data: shareDriftRaw, refetch: refetchShareDrift } = useApi<any>('/api/v2/holdings/share-drift', 60_000, { enabled: needHoldingsDesk })
  const shareDriftItems: ShareDriftItem[] = (shareDriftRaw?.items || shareDriftRaw?.data?.items || []) as ShareDriftItem[]
  const [shareDriftModal, setShareDriftModal] = useState<ShareDriftItem | null>(null)
  // Page views never trigger a broker read (page audit 2026-10-25): no live-stops poll, and llm-coverage is
  // asked for its stored stop model. Resting stops come from the holdings rows (cio_truth stop_last_known).
  const { data: llmCov } = useApi<any>('/api/v2/portfolio/llm-coverage?stops=stored', 120_000, { enabled: needHoldingsDesk })
  const { data: monitoredStops, refetch: refetchMonitored } = useApi<any>('/api/v2/holdings/monitored-stops', 60_000, { enabled: needHoldingsDesk })
  // Cards + Finviz strips only for the symbols this desk shows (perf 2026-10-25): the universe maps are ~3.3 MB +
  // 1.7 MB (~1.3 MB gzipped) and the desk reads cardMap[SYM] / fvMap[SYM] for holdings rows only. Both endpoints
  // filter server-side on ?symbols=; the request waits for holdings so the list is known.
  const holdingSymbols = useMemo(() => [...new Set(((holdings?.holdings ?? []) as any[])
    .map(h => String(h?.symbol || '').toUpperCase()).filter(Boolean))].sort().join(','), [holdings])
  const symbolsQs = `symbols=${encodeURIComponent(holdingSymbols)}`
  const { data: scards } = useApi<any>(`/api/v2/symbol-cards?${symbolsQs}`, 300_000, { enabled: needHoldingsDesk && !!holdingSymbols })
  // Closed-session resistance, same cache the Re-Entry desk reads, so the level shown
  // beside a holding is the level the rotation gates use — not a second opinion.
  const { data: resistancePref } = useApi<any>('/api/v2/ui/prefs/get?key=portfolio.reentry.resistance.v1', 300_000, { enabled: needHoldingsDesk })
  const cardMap: Record<string, any> = (scards as any)?.cards ?? {}
  const { data: fvStrip } = useApi<any>(`/api/v2/finviz-strip-map?${symbolsQs}`, 300_000, { enabled: needHoldingsDesk && !!holdingSymbols })
  const fvMap: Record<string, any> = fvStrip?.map ?? {}
  const { data: divs } = useApi<any>('/api/v2/dividends', 120_000, { enabled: needDividends })
  const { data: taxLots, loading: taxLoading, error: taxError } = useApi<any>('/api/v2/tax-lots', 120_000, { enabled: needTax })
  const { data: perfData } = useApi<any>('/api/v2/portfolio/performance', 120_000, { enabled: needReturns })
  const { data: riskData } = useApi<any>('/api/v2/risk', 120_000, { enabled: needReturns })
  const { data: forecast, loading: forecastLoading, error: forecastError } = useApi<any>('/api/v2/forecast', 300_000, { enabled: needForecast })
  const { data: rotation, error: rotationError } = useApi<any>('/api/v2/rotation/summary', 300_000, { enabled: needHoldingsDesk })
  const rotationPublication = useRotationAvailability(rotation, rotationError)
  const reportMap = useAnalystReportMap()

  // Allocation follows the account filter: per-account look-through when an account is selected, else global.
  const sectorsByAccount = overview?.sectors_by_account ?? {}
  const sectors = (acctFilter && sectorsByAccount[acctFilter]) ? sectorsByAccount[acctFilter] : (overview?.sectors ?? [])
  const allHoldings = holdings?.holdings ?? []
  const holdingsPending = !holdings && holdingsLoading
  const holdingsUnavailable = !holdings && !!holdingsError

  // ── Account filter: chips derived from holdings, with per-account counts + value ──
  const acctMap: Record<string, { n: number; value: number }> = {}
  for (const h of allHoldings) {
    const a = h.account ?? 'unknown'
    acctMap[a] ??= { n: 0, value: 0 }
    acctMap[a].n++; acctMap[a].value += (h.market_value ?? 0)
  }
  const accounts = Object.entries(acctMap).sort((a, b) => b[1].value - a[1].value)
  const acctColor = (a: string) => ACCT_COLORS[Math.max(0, accounts.findIndex(([k]) => k === a)) % ACCT_COLORS.length]
  // SoT Phase 6 — per-account STATE from /api/v2/overview portfolio_aggregate.accounts[].
  // A non-LIVE account shows its label and its last known value with a date; the total
  // names what it left out (excluded_accounts). Absent is not zero.
  const aggAccounts: any[] = Array.isArray((overview as any)?.portfolio_aggregate?.accounts)
    ? (overview as any).portfolio_aggregate.accounts : []
  const acctState = (a: string): { state?: string; reason?: string; lastValue?: number | null; asOf?: string | null } => {
    const row = aggAccounts.find(r => r?.account === a)
    return row ? { state: row.state, reason: row.state_reason, lastValue: row.last_known_value, asOf: row.last_known_value_as_of ?? row.state_as_of } : {}
  }
  const excludedAccounts: any[] = Array.isArray((overview as any)?.portfolio_aggregate?.excluded_accounts)
    ? (overview as any).portfolio_aggregate.excluded_accounts : []
  // Account-state rail: favorable / attention / breach from the house tokens; the manual
  // (no-API) state borrows the muted external-intel tint, badges only. No raw hex here.
  const STATE_COLOR: Record<string, string> = { LIVE: BB.green, STALE: BB.amber, SERVICE_DOWN: BB.red, NO_API_MANUAL: T.extIntel.hermes, UNCLASSIFIED: BB.text3 }
  const acctFiltered = acctFilter ? allHoldings.filter((h: any) => (h.account ?? 'unknown') === acctFilter) : allHoldings
  // signal sub-tab filter + per-bucket counts
  const sigCount = (sigs: string[]) => sigs.length === 0 ? acctFiltered.length
    : acctFiltered.filter((h: any) => sigs.includes(String(h.signal || '').toUpperCase())).length
  const sigSet = SIGNAL_TABS.find(([k]) => k === sigTab)?.[1] ?? []
  const holdingsList = (sigSet.length === 0 ? acctFiltered
    : acctFiltered.filter((h: any) => sigSet.includes(String(h.signal || '').toUpperCase())))
    .slice().sort((a: any, b: any) => (b.market_value ?? 0) - (a.market_value ?? 0))
  const coverage: Record<string, any[]> = (llmCov as any)?.coverage ?? {}
  const protection: Record<string, any> = (llmCov as any)?.protection ?? {}
  const stopCuration: Record<string, any> = (llmCov as any)?.stop_curation ?? {}
  const monitoredByKey: Record<string, any> = monitoredStops?.by_key ?? {}
  const confirmedByKey: Record<string, any> = (llmCov as any)?.confirmed_stops ?? {}
  // Stored stop model: the age is the oldest stored observation shown. No live read happened on this page view,
  // so no account counts as verified by one: a position without a stored resting stop is UNVERIFIABLE, never
  // a false NO_STOP.
  const brokerStopsFetchedAt = storedStopsAsOf(allHoldings)
  const liveStopsDegraded = false
  const brokerStopReadOk: string[] = []
  // Header total + day P/L follow the active filter (account + signal). Unfiltered → equals the global
  // portfolio figures; filtered → that account's own value + day change (fixes "10 holdings · $1.25M").
  const viewTotal = holdingsList.reduce((s: number, h: any) => s + (h.market_value ?? 0), 0)
  const viewDay = holdingsList.reduce((s: number, h: any) =>
    s + (h.day_change ?? (h.market_value ?? 0) * (h.day_change_pct ?? 0) / 100), 0)
  const viewDayPct = (viewTotal - viewDay) ? viewDay / (viewTotal - viewDay) * 100 : 0
  const priceStamp = pricingStampLine(holdings?.pricing ?? holdings, { includeTechnicals: true })

  const buildRowContext = (rawH: any): HoldingsTableRowContext => {
    const h = mergeHolding(rawH)
    const symU = (h.symbol || '').toUpperCase()
    const stopKey = `${symU}:${h.account}`
    const cash = isCashHolding(h)
    return {
      h,
      pr: cash ? undefined : mergeProtection(symU, protection[symU]),
      monitored: cash ? undefined : monitoredByKey[stopKey],
      confirmedStop: cash ? undefined : mergeLiveStop(confirmedByKey[stopKey], storedStopFor(rawH)),
      brokerStopReadOk,
      reportEntry: cash ? undefined : reportMap[symU],
      coverage: cash ? undefined : coverage[symU],
      // Cash never inherits Finviz strip / symbol-card news (CASH ticker contamination).
      fv: cash ? undefined : fvMap[symU],
      card: cash ? undefined : cardMap[symU],
    }
  }
  const openHoldingsDrawer = (rowCtx: HoldingsTableRowContext, opts?: { focus?: 'stops' | 'overview' }) => {
    const h = rowCtx.h
    const symU = (h.symbol || '').toUpperCase()
    const focusStops = opts?.focus === 'stops'
    const acctLabel = accountFullName(String(h.account ?? ''))
    setDrawerTitle(String(h.symbol || '').toUpperCase())
    setDrawerSubtitle(
      `${acctLabel}${h.name ? ` · ${h.name}` : ''}${focusStops ? ' · Stop Management' : ' · Ticker detail'}`,
    )
    setHoldingsDrawer({
      h,
      protection: rowCtx.pr,
      stopCuration: stopCuration[symU],
      monitored: rowCtx.monitored,
      confirmedStop: rowCtx.confirmedStop,
      brokerStopsFetchedAt,
      brokerStopReadOk,
      cardMap,
      fvMap,
      reportEntry: rowCtx.reportEntry,
      coverage: rowCtx.coverage,
      onRefreshMonitored: () => refetchMonitored?.(),
      cvdMode: holdingsCvd,
      drawerFocus: focusStops ? 'stops' : null,
      initialTab: focusStops ? 'stops' : 'overview',
      onPreflightUpdate: (symbol, account, patch) => {
        const hk = `${symbol}:${account}`
        if (patch.holding) setHoldingPatches(p => ({ ...p, [hk]: { ...(p[hk] ?? {}), ...patch.holding } }))
        if (patch.protection) setProtectionPatches(p => ({ ...p, [symbol]: { ...(p[symbol] ?? {}), ...patch.protection } }))
      },
    })
  }
  const openHoldingsStops = (rowCtx: HoldingsTableRowContext) => openHoldingsDrawer(rowCtx, { focus: 'stops' })
  const terminalRows = holdingsList.map(buildRowContext)

  // Desk health: placement vs verification from the same row model the table uses.
  const deskCounts = useMemo(() => {
    let placement = 0
    let verification = 0
    for (const r of terminalRows) {
      const m = buildHoldingsRowModel({
        h: r.h, pr: r.pr, confirmedStop: r.confirmedStop, monitored: r.monitored,
        brokerStopReadOk: r.brokerStopReadOk, fv: r.fv, card: r.card,
      })
      if (m.needsVerification || m.protectionState === 'UNVERIFIABLE') verification += 1
      else if (m.needsAction && m.protectionState === 'NO_STOP') placement += 1
    }
    return { placement, verification }
  }, [terminalRows])

  const unverifiedAccounts: string[] = []

  // Deep-link: ?symbol= / ?account= / ?drawer= / ?drawerTab=stops (Home + Research Intel)
  useEffect(() => {
    if (deepLinkConsumed.current) return
    if (!allHoldings.length) return
    const dl = parsePortfolioDeepLink(searchParams)
    if (!dl.symbol && !dl.drawer) return
    deepLinkConsumed.current = true
    const target = pickHoldingForDeepLink(allHoldings, dl.symbol, dl.account)
      || (dl.drawer ? (() => {
        const [sym, ...rest] = dl.drawer!.split(':')
        return pickHoldingForDeepLink(allHoldings, sym, rest.join(':') || null)
      })() : null)
    if (!target) return
    const sym = String(target.symbol || '').toUpperCase()
    const acct = String(target.account || '')
    if (dl.tab === 'Stop Management') {
      selectTab('Stop Management')
      if (acct) selectAcct(acct)
      return
    }
    selectTab('Holdings')
    if (acct) selectAcct(acct)
    selectSig('All')
    const key = `${sym}-${acct}`
    setFocusKey(key)
    const rowCtx = buildRowContext(target)
    const focusStops = dl.drawerTab === 'stops' || String(searchParams.get('tab') || '').toLowerCase().includes('stop')
    // Open drawer after paint so row exists for scroll
    setTimeout(() => {
      openHoldingsDrawer(rowCtx, { focus: focusStops ? 'stops' : 'overview' })
      const el = document.getElementById(`hold-${sym}-${acct}`)
      el?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }, 80)
    setTimeout(() => setFocusKey(null), 5000)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [allHoldings.length, searchParams])

  return (
    <div>
      <div className="hub-title-row" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 10 }}>
        <div>
          <div style={hubTitle()}>Portfolio</div>
          <div style={hubSubtitle(terminalUi)}>
            {(needLookthrough || needAllocation) ? 'Current holdings opened into their underlying exposures' : !needHoldingsData ? 'Select Holdings for position totals and stop coverage' : holdingsPending ? 'Loading holdings…' : holdingsUnavailable ? 'Holdings temporarily unavailable' : `${holdingsList.length} holdings · ${fmt$(viewTotal, 0)}`}
            {needHoldingsData && !needLookthrough && !needAllocation && !holdingsPending && !holdingsUnavailable && <>
              {' · '}<span style={{ color: viewDay >= 0 ? '#22c55e' : '#ef4444' }}>today {viewDay >= 0 ? '+' : ''}{fmt$(viewDay, 0)} ({viewDay >= 0 ? '+' : ''}{viewDayPct.toFixed(2)}%)</span>
              {acctFilter && <span style={{ color: 'var(--text4)' }}> · {acctFilter.replace(/_/g, ' ')}</span>}
              {holdingsStale && <span style={{ color: '#f59e0b' }}> · refreshing</span>}
            </>}
          </div>
          {needHoldingsData && priceStamp && (
            <div
              title={holdings?.pricing?.note ?? 'Live price overlay per account: Schwab broker sync; Fidelity Finviz/market_quotes'}
              onClick={() => onDrill({ title: 'Pricing sources', subtitle: priceStamp, endpoint: '/api/v2/portfolio/holdings',
                rows: holdings?.pricing ? [holdings.pricing] : [{ last_repriced: holdings?.last_repriced, reprice_source: holdings?.reprice_source }] })}
              style={{ fontSize: 9, color: 'var(--text3)', marginTop: 4, cursor: 'pointer' }}
            >{priceStamp}</div>
          )}
          {/* Manual broker sync buttons — read-only holdings/position pull (no trading) */}
          {needHoldingsDesk && <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 6, flexWrap: 'wrap' }}>
            <button onClick={() => runSync('snaptrade')} disabled={!!syncState.busy} style={syncBtn(syncState.busy === 'snaptrade')}
              title="Full Fidelity refresh: holdings + trade ledger + journal round-trips (read-only; no trading). Note: Fidelity posts trades overnight, so intraday fills appear next morning. Stops not pulled.">
              {syncState.busy === 'snaptrade' ? '⟳ Syncing SnapTrade…' : '⟳ Sync SnapTrade'}
            </button>
            <button onClick={() => runSync('schwab')} disabled={!!syncState.busy} style={syncBtn(syncState.busy === 'schwab')}
              title="Full Schwab refresh: positions + trade ledger + journal round-trips (read-only; no trading; stops not pulled).">
              {syncState.busy === 'schwab' ? '⟳ Syncing Schwab…' : '⟳ Sync Schwab'}
            </button>
            <details style={{ fontSize: 10, color: 'var(--text3)' }}>
              <summary style={{ cursor: 'pointer', fontWeight: 700, color: 'var(--text3)' }}>Advanced / legacy</summary>
              <button onClick={() => void runFidelityStopSync()} disabled={!!syncState.busy}
                style={{ ...syncBtn(syncState.busy === 'fidelity_stops'), opacity: 0.7, marginTop: 4 }}
                title="LEGACY — Fidelity Rollover IRA is CLOSED (rolled to Schwab 2026-07-16). Historical GTC stop map only.">
                {syncState.busy === 'fidelity_stops' ? '⟳ Fidelity stops…' : '⟳ Sync Fidelity GTC stops (legacy)'}
              </button>
            </details>
            {syncState.msg && (
              <span style={{ fontSize: 10, color: /error|failed/.test(syncState.msg) ? '#ef4444' : '#22c55e' }}>{syncState.msg}</span>
            )}
          </div>}
        </div>
        <div className="hub-tabs" style={{ display: 'flex', gap: terminalUi ? 4 : 6, flexWrap: 'wrap' }}>
          {TABS.map(t => (
            <button key={t} onClick={() => selectTab(t)} style={{ ...hubTab(tab === t, terminalUi), minHeight: 44 }}>{t}</button>
          ))}
        </div>
      </div>

      {needHoldingsDesk && <PortfolioDeskHealth
        holdingsCount={holdingsList.length}
        viewTotalLabel={fmt$(viewTotal, 0)}
        brokerStopReadOk={brokerStopReadOk}
        unverifiedAccounts={unverifiedAccounts}
        liveStopsDegraded={liveStopsDegraded}
        brokerStopsFetchedAt={brokerStopsFetchedAt}
        storedOnly
        placementCount={deskCounts.placement}
        verificationCount={deskCounts.verification}
        priceStamp={priceStamp}
        onExportCsv={() => downloadHoldingsCsv(holdingsList)}
        onOpenStopAudit={() => selectTab('Stop Management')}
      />}

      {tab === 'Redeploy' && <RedeployPanel />}

      {tab === 'Stop Management' && (
        <StopManagement
          onFocusHolding={focusHolding}
          accountFilter={acctFilter}
          onAccountFilter={selectAcct}
        />
      )}

      {tab === 'Holdings' && (() => {
        if (!rotationPublication.ready) return <RotationPublicationNotice summary={rotation} error={rotationError} />
        const rs = rotation?.summary ?? {}
        const noAction = (rs.rotation_ideas ?? 0) === 0 && (rs.trim_review ?? 0) === 0 && (rs.add_review ?? 0) === 0
        return (
          <div style={{
            display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap', marginBottom: 12, padding: '10px 14px',
            background: 'var(--bg1)', border: '1px solid var(--border)', borderLeft: '4px solid #60a5fa', borderRadius: 10,
          }}>
            <div style={{ flex: 1, minWidth: 220 }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)' }}>Rotation Advisor
                <span style={{ fontSize: 8.5, color: '#f59e0b', fontWeight: 600, marginLeft: 8 }}>advisory only · no broker action</span>
              </div>
              <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 2 }}>
                Account-aware rotation review with a local + Grok OAuth second opinion.
                {rotation && noAction
                  ? <span style={{ color: '#f59e0b' }}> No model-supported action — WATCH / RESEARCH_MORE.</span>
                  : rotation
                    ? <span> {rs.trim_review ?? 0} trim · {rs.add_review ?? 0} add · {rs.rotation_ideas ?? 0} rotation to review.</span>
                    : null}
              </div>
            </div>
            <Link to="/rotation" style={{
              padding: '6px 14px', fontSize: 11, fontWeight: 700, borderRadius: 6, textDecoration: 'none',
              background: 'rgba(96,165,250,.15)', color: '#60a5fa', border: '1px solid #60a5fa55', whiteSpace: 'nowrap',
            }}>Open Rotation Review →</Link>
          </div>
        )
      })()}

      {tab === 'Holdings' && accounts.length > 1 && (
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 12, alignItems: 'center' }}>
          <button onClick={() => selectAcct(null)} style={{
            padding: '3px 10px', fontSize: 10, borderRadius: 12, cursor: 'pointer',
            border: `1px solid ${acctFilter === null ? '#60a5fa' : 'var(--border)'}`,
            background: acctFilter === null ? 'rgba(96,165,250,.15)' : 'var(--bg2)',
            color: acctFilter === null ? '#60a5fa' : 'var(--text3)', fontWeight: acctFilter === null ? 700 : 400,
          }}>All ({allHoldings.length})</button>
          {accounts.map(([a, info]) => (
            <button key={a} onClick={() => selectAcct(a === acctFilter ? null : a)} style={{
              padding: '3px 10px', fontSize: 10, borderRadius: 12, cursor: 'pointer',
              border: `1px solid ${acctFilter === a ? acctColor(a) : 'var(--border)'}`,
              background: acctFilter === a ? `${acctColor(a)}22` : 'var(--bg2)',
              color: acctFilter === a ? acctColor(a) : 'var(--text3)', fontWeight: acctFilter === a ? 700 : 400,
            }}>
              <span style={{ display: 'inline-block', width: 7, height: 7, borderRadius: '50%', background: acctColor(a), marginRight: 5 }} />
              {accountFullName(a)} ({info.n})
              {(() => { const st = acctState(a); return st.state && st.state !== 'LIVE' ? (
                <span title={st.reason ?? st.state} style={{ marginLeft: 5, padding: '0 5px', borderRadius: 8, fontSize: DASH.chip, fontWeight: 700, letterSpacing: .3, border: `1px solid ${STATE_COLOR[st.state] ?? BB.border}`, color: STATE_COLOR[st.state] ?? BB.text3 }}>
                  {st.state.replace('_', ' ')}{st.lastValue != null ? ` · last ${fmt$(st.lastValue)}${st.asOf ? ` @ ${String(st.asOf).slice(0, 10)}` : ''}` : ''}
                </span>
              ) : null })()}
            </button>
          ))}
          {excludedAccounts.length > 0 && (
            <span title={excludedAccounts.map(e => `${e.account}: ${e.state} — ${e.reason ?? ''}`).join('\n')} style={{ fontSize: 10, color: 'var(--text3)', marginLeft: 4 }}>
              · total leaves out {excludedAccounts.map(e => `${accountFullName(e.account)} (${String(e.state).replace('_', ' ')}${e.last_value != null ? `, last ${fmt$(e.last_value)}${e.as_of ? ` @ ${String(e.as_of).slice(0, 10)}` : ''}` : ''})`).join(', ')}
            </span>
          )}
        </div>
      )}

      {tab === 'Allocation' && <W7Allocation account={acctFilter} selectAccount={selectAcct} />}

      {tab === 'Holdings' && (
        <div data-testid="holdings-panel">
          {/* Compact nav chips — allocation / stop desk live on their own tabs */}
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 10, alignItems: 'center' }}>
            <button
              type="button"
              data-testid="holdings-open-allocation"
              onClick={() => selectTab('Allocation')}
              style={{
                fontSize: 10.5, fontWeight: 700, padding: '5px 11px', borderRadius: 6, cursor: 'pointer',
                border: '1px solid #60a5fa44', background: 'rgba(96,165,250,.1)', color: '#60a5fa',
              }}
            >
              Allocation → sectors & accounts
            </button>
            <button
              type="button"
              data-testid="holdings-open-stops"
              onClick={() => selectTab('Stop Management')}
              style={{
                fontSize: 10.5, fontWeight: 700, padding: '5px 11px', borderRadius: 6, cursor: 'pointer',
                border: '1px solid #f59e0b44', background: 'rgba(245,158,11,.1)', color: '#f59e0b',
              }}
            >
              Stop Management desk →
            </button>
            {priceStamp && <div style={{ fontSize: 8, color: 'var(--text3)', marginLeft: 'auto' }} title={holdings?.pricing?.note}>{priceStamp}</div>}
          </div>

          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8, flexWrap: 'wrap', gap: 8 }}>
            <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
              {SIGNAL_TABS.map(([k, sigs]) => {
                const n = sigCount(sigs)
                const c = k === 'Buy/Add' ? '#22c55e' : k === 'Trim/Sell' ? '#ef4444' : k === 'Watch' ? '#f59e0b' : '#60a5fa'
                return (
                  <button key={k} onClick={() => selectSig(k as PortfolioSignalTab)} style={{
                    padding: '4px 12px', fontSize: 10.5, borderRadius: 6, cursor: 'pointer',
                    border: `1px solid ${sigTab === k ? c : 'var(--border)'}`,
                    background: sigTab === k ? `${c}1f` : 'var(--bg2)',
                    color: sigTab === k ? c : 'var(--text3)', fontWeight: sigTab === k ? 800 : 400,
                  }}>{k} ({n})</button>
                )
              })}
            </div>
          </div>

          {shareDriftItems.length > 0 && (
            <div
              data-testid="share-drift-banner"
              style={{
                marginBottom: 10, padding: '10px 14px', borderRadius: 8,
                background: 'rgba(245,158,11,.1)', border: '1px solid rgba(245,158,11,.4)',
                display: 'flex', flexWrap: 'wrap', gap: 10, alignItems: 'center',
              }}
            >
              <span style={{ fontSize: 12, fontWeight: 800, color: '#f59e0b' }}>
                Share drift · {shareDriftItems.length} position{shareDriftItems.length === 1 ? '' : 's'} need update
              </span>
              <span style={{ fontSize: 11, color: 'var(--text3)' }}>
                Likely dividend reinvestment — system shares lag broker actual.
              </span>
              <span style={{ flex: 1 }} />
              {shareDriftItems.slice(0, 4).map(it => (
                <button
                  key={it.id}
                  type="button"
                  onClick={() => setShareDriftModal(it)}
                  style={{
                    fontSize: 11, fontWeight: 700, padding: '4px 10px', borderRadius: 6, cursor: 'pointer',
                    border: '1px solid #f59e0b66', background: 'rgba(245,158,11,.15)', color: '#fbbf24',
                  }}
                >
                  {it.symbol} ({it.drift_amount >= 0 ? '+' : ''}{it.drift_amount})
                </button>
              ))}
            </div>
          )}

          <HoldingsTableView
            rows={terminalRows}
            resistanceMap={(resistancePref as any)?.value?.symbols ?? (resistancePref as any)?.data?.value?.symbols ?? {}}
            acctColor={acctColor}
            focusKey={focusKey}
            cvdMode={holdingsCvd}
            onOpenDetail={openHoldingsDrawer}
            onOpenStops={openHoldingsStops}
            onPrimaryAction={openHoldingsStops}
            onShareDrift={(ctx) => {
              const match = shareDriftItems.find(
                d => d.symbol === String(ctx.h.symbol || '').toUpperCase()
                  && d.account_key === String(ctx.h.account || ''),
              )
              if (match) setShareDriftModal(match)
              else {
                // synthesize from holding dual fields when task list lags
                const h = ctx.h
                const sys = Number(h.system_shares ?? h.shares ?? 0)
                const brk = Number(h.broker_actual_shares ?? h.shares ?? 0)
                setShareDriftModal({
                  id: 0,
                  account_key: String(h.account || ''),
                  symbol: String(h.symbol || '').toUpperCase(),
                  system_shares: sys,
                  broker_shares: brk,
                  drift_amount: brk - sys,
                  source: h.share_drift_source || 'dividend_reinvestment',
                  status: 'open',
                  message: `${String(h.symbol).toUpperCase()} share drift: system ${sys} vs broker ${brk}.`,
                })
              }
            }}
          />
          {holdingsPending && <div style={{ padding: 20, color: 'var(--text3)', fontSize: 12, textAlign: 'center', background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10 }}>Loading holdings from /api/v2/portfolio/holdings…</div>}
          {holdingsUnavailable && <div style={{ padding: 20, color: '#f59e0b', fontSize: 12, textAlign: 'center', background: 'var(--bg1)', border: '1px solid rgba(245,158,11,.35)', borderRadius: 10 }}>Holdings request is still retrying: {holdingsError}</div>}
          {!holdingsPending && !holdingsUnavailable && holdingsList.length === 0 && <div style={{ padding: 20, color: 'var(--text3)', fontSize: 11, textAlign: 'center', background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10 }}>No holdings match this filter.</div>}

          <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 8, lineHeight: 1.45 }}>
            Row click / Enter → full ticker drawer. <b>S</b> on focused row → Stop Management panel.
            Symbol / Stop / Action cells also open stops. Export CSV from desk strip (filtered lots).
          </div>
        </div>
      )}

      <HoldingsSideDrawer
        open={!!holdingsDrawer}
        title={drawerTitle}
        subtitle={drawerSubtitle}
        ctx={holdingsDrawer}
        onClose={() => setHoldingsDrawer(null)}
      />

      <ShareReconciliationModal
        open={!!shareDriftModal}
        item={shareDriftModal}
        onClose={() => setShareDriftModal(null)}
        onApplied={() => {
          refetchShareDrift?.()
          // force holdings refresh by soft-reloading page data
          try { window.dispatchEvent(new Event('focus')) } catch { /* */ }
        }}
      />

      {tab === 'Look-through' && <W7Lookthrough account={acctFilter} selectAccount={selectAcct} />}

      {tab === 'Dividends' && (
        <DividendsPanel
          divs={divs}
          holdings={allHoldings}
          accounts={accounts}
          acctFilter={acctFilter}
          selectAcct={selectAcct}
          acctColor={acctColor}
          panelStyle={tabPanel}
          terminalUi={terminalUi}
        />
      )}

      {tab === 'Returns' && perfData && (
        <ReturnsPanel
          perfData={perfData}
          holdings={allHoldings}
          riskPositions={riskData?.positions ?? []}
          acctColor={acctColor}
          initialAccount={acctFilter}
          onOpenHolding={(symbol, account) => {
            selectTab('Holdings')
            selectAcct(account)
            selectSig('All')
            const key = `${symbol}-${account}`
            setFocusKey(key)
            setTimeout(() => {
              document.getElementById(`hold-${symbol}-${account}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
            }, 120)
            setTimeout(() => setFocusKey(null), 4000)
          }}
        />
      )}
      {tab === 'Returns' && !perfData && <div style={{ color: 'var(--text3)', fontSize: 11, padding: 20 }}>Loading performance data...</div>}
      {tab === 'Forecast' && (
        <ForecastPanel forecast={forecast} loading={forecastLoading} error={forecastError} terminalUi={terminalUi} />
      )}

      {tab === 'Tax' && (
        <TaxPanel taxLots={taxLots} loading={taxLoading} error={taxError} terminalUi={terminalUi} panelStyle={tabPanel} />
      )}
    </div>
  )
}
