import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip } from 'recharts'
import { fmt$ } from '../lib/format'
import { pricingStampLine } from '../lib/pricingStamp'
import type { DrillContext } from '../components/DetailDrawer'
import ProAnalystPill, { useProAnalystMap } from '../components/ProAnalystPill'
import AnalystReviews, { useAnalystMap } from '../components/AnalystReviews'
import { laneLabel } from '../lib/laneLabels'
import AskAgents from '../components/AskAgents'
import HoldingProtectionActions from '../components/HoldingProtectionActions'
import { mergeLiveStop, stopReviewTooltip } from '../lib/stopReviewTooltip'
import HoldingReportLinks from '../components/HoldingReportLinks'
import { useAnalystReportMap } from '../hooks/useAnalystReportMap'
import { holdingReportEligible } from '../lib/reportLinks'
import StopManagement from '../components/StopManagement'
import RedeployPanel from '../components/RedeployPanel'
import AllocationPanel from '../components/AllocationPanel'
import ReturnsPanel from '../components/ReturnsPanel'
import DividendsPanel from '../components/DividendsPanel'
import { EvidenceBlock } from '../components/EvidenceBlock'
import HoldingsTableView, { type HoldingsTableRowContext } from '../components/HoldingsTableView'
import HoldingsSideDrawer from '../components/HoldingsSideDrawer'
import ShareReconciliationModal, { type ShareDriftItem } from '../components/ShareReconciliationModal'
import type { HoldingsDetailContext } from '../components/HoldingsDetailPanel'
import type { HoldingsCvdMode } from '../lib/holdingsTerminalTokens'
import { accountFullName } from '../lib/holdingsRowModel'
import { useTerminalUi } from '../lib/terminalUi'
import { hubTitle, hubSubtitle, hubTab, hubPanel } from '../lib/terminalHubChrome'

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
  const [sigTab, setSigTab] = useState('All')
  const [focusKey, setFocusKey] = useState<string | null>(null)
  // From the Stop Management Adjust modal: jump to a holding's card (its inline gated 2FA / manual-ticket panel).
  const focusHolding = (symbol: string, account: string) => {
    selectTab('Holdings'); selectAcct(account); setSigTab('All')
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
  const { data: overview } = useApi<any>('/api/v2/overview', 60_000)
  const { data: holdings, loading: holdingsLoading, error: holdingsError, stale: holdingsStale } = useApi<any>('/api/v2/portfolio/holdings', 60_000)
  const { data: shareDriftRaw, refetch: refetchShareDrift } = useApi<any>('/api/v2/holdings/share-drift', 60_000)
  const shareDriftItems: ShareDriftItem[] = (shareDriftRaw?.items || shareDriftRaw?.data?.items || []) as ShareDriftItem[]
  const [shareDriftModal, setShareDriftModal] = useState<ShareDriftItem | null>(null)
  const { data: llmCov } = useApi<any>('/api/v2/portfolio/llm-coverage', 120_000)
  const { data: liveStops } = useApi<any>('/api/v2/holdings/live-stops', 60_000)
  const { data: monitoredStops, refetch: refetchMonitored } = useApi<any>('/api/v2/holdings/monitored-stops', 60_000)
  const { data: scards } = useApi<any>('/api/v2/symbol-cards', 300_000)
  // Closed-session resistance, same cache the Re-Entry desk reads, so the level shown
  // beside a holding is the level the rotation gates use — not a second opinion.
  const { data: resistancePref } = useApi<any>('/api/v2/ui/prefs/get?key=portfolio.reentry.resistance.v1', 300_000)
  const cardMap: Record<string, any> = (scards as any)?.cards ?? {}
  const paMap = useProAnalystMap()
  const aMap = useAnalystMap()
  const { data: fvStrip } = useApi<any>('/api/v2/finviz-strip-map', 300_000)
  const fvMap: Record<string, any> = fvStrip?.map ?? {}
  const { data: divs } = useApi<any>('/api/v2/dividends', 120_000)
  const { data: taxLots } = useApi<any>('/api/v2/tax-lots', 120_000)
  const { data: perfData } = useApi<any>('/api/v2/portfolio/performance', 120_000)
  const { data: riskData } = useApi<any>('/api/v2/risk', 120_000)
  const { data: forecast } = useApi<any>('/api/v2/forecast', 300_000)
  const { data: lookthrough } = useApi<any>('/api/v2/portfolio/lookthrough', 300_000)
  const { data: rotation } = useApi<any>('/api/v2/rotation/summary', 300_000)
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
  const liveStopsByKey: Record<string, any> = (liveStops as any)?.by_key ?? {}
  const brokerStopsFetchedAt = (liveStops as any)?.fetched_at ?? (llmCov as any)?.broker_stops_fetched_at ?? null
  // accounts whose live broker-stop read succeeded — anything else is UNVERIFIABLE, not 'none'
  const brokerStopReadOk: string[] = (llmCov as any)?.broker_stop_read_ok_accounts ?? []
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
    return {
      h,
      pr: mergeProtection(symU, protection[symU]),
      monitored: monitoredByKey[stopKey],
      confirmedStop: mergeLiveStop(confirmedByKey[stopKey], liveStopsByKey[stopKey]),
      reportEntry: reportMap[symU],
      coverage: coverage[symU],
      // Existing enrichment only — Finviz strip + symbol cards (news / earnings)
      fv: fvMap[symU],
      card: cardMap[symU],
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

  return (
    <div>
      <div className="hub-title-row" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 10 }}>
        <div>
          <div style={hubTitle()}>Portfolio</div>
          <div style={hubSubtitle(terminalUi)}>
            {holdingsPending ? 'Loading holdings…' : holdingsUnavailable ? 'Holdings temporarily unavailable' : `${holdingsList.length} holdings · ${fmt$(viewTotal, 0)}`}
            {!holdingsPending && !holdingsUnavailable && <>
              {' · '}<span style={{ color: viewDay >= 0 ? '#22c55e' : '#ef4444' }}>today {viewDay >= 0 ? '+' : ''}{fmt$(viewDay, 0)} ({viewDay >= 0 ? '+' : ''}{viewDayPct.toFixed(2)}%)</span>
              {acctFilter && <span style={{ color: 'var(--text4)' }}> · {acctFilter.replace(/_/g, ' ')}</span>}
              {holdingsStale && <span style={{ color: '#f59e0b' }}> · refreshing</span>}
            </>}
          </div>
          {priceStamp && (
            <div
              title={holdings?.pricing?.note ?? 'Live price overlay per account: Schwab broker sync; Fidelity Finviz/market_quotes'}
              onClick={() => onDrill({ title: 'Pricing sources', subtitle: priceStamp, endpoint: '/api/v2/portfolio/holdings',
                rows: holdings?.pricing ? [holdings.pricing] : [{ last_repriced: holdings?.last_repriced, reprice_source: holdings?.reprice_source }] })}
              style={{ fontSize: 9, color: 'var(--text3)', marginTop: 4, cursor: 'pointer' }}
            >{priceStamp}</div>
          )}
          {/* Manual broker sync buttons — read-only holdings/position pull (no trading) */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 6, flexWrap: 'wrap' }}>
            <button onClick={() => runSync('snaptrade')} disabled={!!syncState.busy} style={syncBtn(syncState.busy === 'snaptrade')}
              title="Full Fidelity refresh: holdings + trade ledger + journal round-trips (read-only; no trading). Note: Fidelity posts trades overnight, so intraday fills appear next morning. Stops not pulled.">
              {syncState.busy === 'snaptrade' ? '⟳ Syncing SnapTrade…' : '⟳ Sync SnapTrade'}
            </button>
            <button onClick={() => runSync('schwab')} disabled={!!syncState.busy} style={syncBtn(syncState.busy === 'schwab')}
              title="Full Schwab refresh: positions + trade ledger + journal round-trips (read-only; no trading; stops not pulled).">
              {syncState.busy === 'schwab' ? '⟳ Syncing Schwab…' : '⟳ Sync Schwab'}
            </button>
            {/* Fidelity Rollover IRA closed 2026-07-16 (ACATS → Schwab). Keep button but mark legacy so operators don't think Fidelity is still an active book. */}
            <button onClick={() => void runFidelityStopSync()} disabled={!!syncState.busy} style={{ ...syncBtn(syncState.busy === 'fidelity_stops'), opacity: 0.55 }}
              title="LEGACY — Fidelity Rollover IRA is CLOSED (rolled to Schwab 2026-07-16). Historical GTC stop map only (config/fidelity_rollover_stops.json). Re-arm protective stops on Schwab Rollover IRA instead.">
              {syncState.busy === 'fidelity_stops' ? '⟳ Fidelity stops…' : '⟳ Sync Fidelity GTC stops (legacy)'}
            </button>
            {syncState.msg && (
              <span style={{ fontSize: 10, color: /error|failed/.test(syncState.msg) ? '#ef4444' : '#22c55e' }}>{syncState.msg}</span>
            )}
          </div>
        </div>
        <div className="hub-tabs" style={{ display: 'flex', gap: terminalUi ? 4 : 6, flexWrap: 'wrap' }}>
          {TABS.map(t => (
            <button key={t} onClick={() => selectTab(t)} style={hubTab(tab === t, terminalUi)}>{t}</button>
          ))}
        </div>
      </div>

      {tab === 'Redeploy' && <RedeployPanel />}

      {tab === 'Stop Management' && (
        <StopManagement
          onFocusHolding={focusHolding}
          accountFilter={acctFilter}
          onAccountFilter={selectAcct}
        />
      )}

      {tab === 'Holdings' && (() => {
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
                Account-aware rotation review with a local + cloud second opinion.
                {rotation && noAction
                  ? <span style={{ color: '#f59e0b' }}> No model-supported action — WATCH / RESEARCH_MORE.</span>
                  : rotation
                    ? <span> {rs.trim_review ?? 0} trim · {rs.add_review ?? 0} add · {rs.rotation_ideas ?? 0} rotation to review.</span>
                    : null}
              </div>
            </div>
            <a href="/v3/rotation" style={{
              padding: '6px 14px', fontSize: 11, fontWeight: 700, borderRadius: 6, textDecoration: 'none',
              background: 'rgba(96,165,250,.15)', color: '#60a5fa', border: '1px solid #60a5fa55', whiteSpace: 'nowrap',
            }}>Open Rotation Review →</a>
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
              {a} ({info.n})
            </button>
          ))}
        </div>
      )}

      {tab === 'Allocation' && (
        <AllocationPanel
          sectors={overview?.sectors ?? sectors}
          sectorsByAccount={sectorsByAccount}
          sectorContributors={(overview as any)?.sector_contributors ?? {}}
          sectorUnderlyings={(overview as any)?.sector_underlyings ?? {}}
          lookthroughAsOf={(overview as any)?.lookthrough_as_of ?? null}
          holdings={allHoldings}
          acctColor={acctColor}
          onGoHoldings={() => selectTab('Holdings')}
          onOpenHolding={(symbol, account) => {
            selectTab('Holdings')
            selectAcct(account)
            setSigTab('All')
            const key = `${symbol}-${account}`
            setFocusKey(key)
            setTimeout(() => {
              document.getElementById(`hold-${symbol}-${account}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
            }, 120)
            setTimeout(() => setFocusKey(null), 4000)
          }}
        />
      )}

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
                  <button key={k} onClick={() => setSigTab(k)} style={{
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

          <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 8, lineHeight: 1.45 }}>
            Row click → full ticker drawer (75%, tabbed). Symbol / Stop / Action → Stop Management tab.
            Allocation & portfolio Stop Management desk: separate tabs.
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

      {tab === 'Look-through' && (() => {
        const lt = (lookthrough as any)?.data ?? lookthrough ?? {}
        const acctDetail = lt.accounts_detail ?? {}
        // account filter: per-account look-through when selected, else portfolio-wide
        const view = (acctFilter && acctDetail[acctFilter]) ? acctDetail[acctFilter] : lt
        const themes = Object.entries(view.themes ?? {}).map(([name, t]: any) => ({ name, ...t })).sort((a: any, b: any) => b.pct - a.pct)
        const top = view.top_underlying ?? []
        const advs = view.advisories ?? []
        const maxThemePct = Math.max(1, ...themes.map((t: any) => t.pct))
        const maxStockPct = Math.max(1, ...top.map((s: any) => s.pct))
        const sevColor = (s: string) => s === 'high' ? '#ef4444' : s === 'medium' ? '#f59e0b' : '#22c55e'
        if (!themes.length) return <div style={{ color: 'var(--text3)', fontSize: 12, padding: 20 }}>No look-through computed yet — run <code>scripts/portfolio_lookthrough_themes.py --grok</code>.</div>
        const ltAccts = Object.keys(acctDetail)
        return (
          <div>
            <AskAgents />
            {ltAccts.length > 1 && (
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 9 }}>
                <button onClick={() => selectAcct(null)} style={{ fontSize: 10, padding: '3px 11px', borderRadius: 12, cursor: 'pointer', border: `1px solid ${acctFilter === null ? '#60a5fa' : 'var(--border)'}`, background: acctFilter === null ? 'rgba(96,165,250,.15)' : 'var(--bg2)', color: acctFilter === null ? '#60a5fa' : 'var(--text3)', fontWeight: acctFilter === null ? 700 : 400 }}>All accounts</button>
                {ltAccts.map(a => (
                  <button key={a} onClick={() => selectAcct(a === acctFilter ? null : a)} style={{ fontSize: 10, padding: '3px 11px', borderRadius: 12, cursor: 'pointer', border: `1px solid ${acctFilter === a ? acctColor(a) : 'var(--border)'}`, background: acctFilter === a ? `${acctColor(a)}22` : 'var(--bg2)', color: acctFilter === a ? acctColor(a) : 'var(--text3)', fontWeight: acctFilter === a ? 700 : 400 }}>{a.replace(/_/g, ' ')}</button>
                ))}
              </div>
            )}
            <div style={{ fontSize: 11, color: 'var(--text3)', marginBottom: 10 }}>
              True stock-level look-through{acctFilter ? <b style={{ color: 'var(--text1)' }}> · {acctFilter.replace(/_/g, ' ')} (${Math.round(view.portfolio_total ?? 0).toLocaleString()})</b> : ' — funds resolved to their underlying holdings'}. Coverage <b style={{ color: 'var(--text1)' }}>{view.coverage_pct}%</b> (top-10 fund holdings; theme %s are lower bounds). Hover a stock to see which funds hold it.
            </div>
            {lt.grok_narrative && (
              <div style={{ background: 'rgba(168,85,247,.08)', border: '1px solid rgba(168,85,247,.3)', borderRadius: 10, padding: '10px 13px', marginBottom: 10 }}>
                <div style={{ fontSize: 10, fontWeight: 800, color: '#c084fc', marginBottom: 4 }}>{`🧠 AI ADVISORY (${laneLabel('grok')})`}</div>
                <div style={{ fontSize: 11.5, color: 'var(--text1)', lineHeight: 1.55 }}>{lt.grok_narrative}</div>
              </div>
            )}
            {(view.theme_gaps ?? lt.theme_gaps ?? []).length > 0 && (() => {
              const gaps = view.theme_gaps ?? lt.theme_gaps ?? []
              const ds = gapDesign?.design
              return (
                <div style={{ background: 'rgba(34,197,94,.06)', border: '1px solid rgba(34,197,94,.3)', borderRadius: 10, padding: '11px 13px', marginBottom: 12 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8, flexWrap: 'wrap' }}>
                    <div style={{ fontSize: 12, fontWeight: 800, color: '#34d399' }}>🎯 Diversification gaps — fill suggestions</div>
                    <span style={{ fontSize: 9.5, color: 'var(--text3)' }}>{gaps.length} underweight/0% sleeve{gaps.length === 1 ? '' : 's'} with a long-ETF candidate · advisory only</span>
                    <span style={{ flex: 1 }} />
                    <button disabled={gapBusy} onClick={designFill} style={{ fontSize: 10.5, fontWeight: 700, padding: '5px 12px', borderRadius: 7, border: '1px solid #a855f7', background: gapBusy ? 'var(--bg2)' : 'rgba(168,85,247,.18)', color: '#c084fc', cursor: gapBusy ? 'wait' : 'pointer' }}>{gapBusy ? 'designing…' : '🤖 Design fill plan (AI)'}</button>
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))', gap: 8 }}>
                    {gaps.map((g: any, i: number) => (
                      <div key={i} style={{ background: 'var(--bg2)', border: `1px solid ${g.severity === 'high' ? '#ef4444' : '#f59e0b'}44`, borderRadius: 8, padding: '8px 10px' }}>
                        <div style={{ fontSize: 11.5, fontWeight: 700, color: 'var(--text0)' }}>{g.theme} <span style={{ color: g.severity === 'high' ? '#ef4444' : '#f59e0b' }}>{g.current_pct}%</span> <span style={{ color: 'var(--text3)' }}>→ {g.target_pct}%</span></div>
                        <div style={{ fontSize: 9.5, color: 'var(--text3)', marginBottom: 6 }}>gap ≈ ${Math.round(g.gap_dollars).toLocaleString()}</div>
                        <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap' }}>
                          {(g.suggested_etfs ?? []).map((e: any) => (
                            <button key={e.symbol} onClick={() => proposeGapEtf(e.symbol, g.theme, `Fill ${g.theme} gap (${g.current_pct}%→${g.target_pct}%) — advisory ETF candidate`)} title={`${e.name} — propose a PENDING review (no execution)`} style={{ fontSize: 10, fontWeight: 700, padding: '3px 8px', borderRadius: 6, border: '1px solid #22c55e66', background: 'rgba(34,197,94,.12)', color: '#86efac', cursor: 'pointer' }}>{e.symbol}{gapPropose[e.symbol] ? ` · ${gapPropose[e.symbol]}` : ' + propose'}</button>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                  {gapDesign && (
                    <div style={{ marginTop: 10, borderTop: '1px solid rgba(148,163,184,.18)', paddingTop: 8 }}>
                      {ds?.summary && <div style={{ fontSize: 11, color: 'var(--text1)', lineHeight: 1.5, marginBottom: 6 }}><b style={{ color: '#c084fc' }}>AI design ({gapDesign.lane}):</b> {ds.summary}</div>}
                      {(ds?.steps ?? []).map((s: any, i: number) => (
                        <div key={i} style={{ fontSize: 10.5, color: 'var(--text2)', display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', marginBottom: 3 }}>
                          <span style={{ fontFamily: 'monospace', fontWeight: 700, color: '#34d399' }}>{s.action} {s.symbol}</span>
                          <span>${Number(s.dollars || 0).toLocaleString()}</span>
                          <span style={{ color: 'var(--text3)' }}>· {s.funded_by}</span>
                          <span style={{ color: 'var(--text3)' }}>— {s.rationale}</span>
                          {s.symbol && <button onClick={() => proposeGapEtf(s.symbol, s.theme || '', s.rationale || 'AI fill design')} style={{ fontSize: 9, fontWeight: 700, padding: '2px 7px', borderRadius: 5, border: '1px solid #22c55e66', background: 'rgba(34,197,94,.12)', color: '#86efac', cursor: 'pointer' }}>{gapPropose[s.symbol] || '+ propose'}</button>}
                        </div>
                      ))}
                      {ds?.parse_error && <div style={{ fontSize: 10, color: '#f59e0b' }}>AI returned unstructured text: {ds.raw}</div>}
                      {gapDesign.ok === false && <div style={{ fontSize: 10, color: '#ef4444' }}>{gapDesign.error}</div>}
                      <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 5 }}>Proposing creates a PENDING review item — manual approval + all gates still required. Nothing is executed.</div>
                    </div>
                  )}
                </div>
              )
            })()}
            {(lt.agent_advisories ?? []).length > 0 && (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 8, marginBottom: 12 }}>
                {lt.agent_advisories.map((a: any, i: number) => {
                  const c = a.agent.startsWith('CIO') ? '#60a5fa' : a.agent.startsWith('Risk') ? '#ef4444' : '#22c55e'
                  return (
                    <div key={i} style={{ background: 'var(--bg2)', border: `1px solid ${c}44`, borderTop: `2px solid ${c}`, borderRadius: 8, padding: '9px 11px' }}>
                      <div style={{ fontSize: 10, fontWeight: 800, color: c, marginBottom: 4 }}>{a.agent} <span style={{ color: 'var(--text4)', fontWeight: 500 }}>· {a.model}</span></div>
                      <div style={{ fontSize: 11, color: 'var(--text1)', lineHeight: 1.5, whiteSpace: 'pre-wrap' }}>{a.text}</div>
                    </div>
                  )
                })}
              </div>
            )}
            {advs.length > 0 && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 14 }}>
                {advs.map((a: any, i: number) => (
                  <div key={i} style={{ display: 'flex', gap: 9, alignItems: 'baseline', padding: '7px 11px', borderRadius: 8, background: 'var(--bg2)', borderLeft: `3px solid ${sevColor(a.severity)}` }}>
                    <span style={{ fontSize: 8.5, fontWeight: 900, color: sevColor(a.severity), textTransform: 'uppercase' }}>{a.severity}</span>
                    <span style={{ fontSize: 11.5, fontWeight: 700, color: 'var(--text0)' }}>{a.title}</span>
                    <span style={{ fontSize: 10.5, color: 'var(--text2)' }}>{a.detail}</span>
                  </div>
                ))}
              </div>
            )}
            {top.length > 0 && (() => {
              const donut = top.slice(0, 10).map((s: any) => ({ name: s.symbol, value: s.value }))
              return (
                <div style={{ display: 'flex', gap: 16, alignItems: 'center', marginBottom: 14, background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 12 }}>
                  <div style={{ width: 190, height: 170, flexShrink: 0 }}>
                    <ResponsiveContainer width="100%" height="100%">
                      <PieChart>
                        <Pie data={donut} dataKey="value" nameKey="name" cx="50%" cy="50%" innerRadius={42} outerRadius={78} stroke="var(--bg0)" strokeWidth={2}>
                          {donut.map((_: any, i: number) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
                        </Pie>
                        <Tooltip formatter={(v: any) => `$${Math.round(v).toLocaleString()}`} />
                      </PieChart>
                    </ResponsiveContainer>
                  </div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', marginBottom: 6 }}>Top-10 underlying concentration (look-through)</div>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px 14px' }}>
                      {donut.map((d: any, i: number) => (
                        <span key={d.name} style={{ fontSize: 10.5, color: 'var(--text2)' }}>
                          <span style={{ color: COLORS[i % COLORS.length] }}>●</span> <b style={{ color: 'var(--text1)' }}>{d.name}</b> ${(d.value / 1000).toFixed(0)}k
                        </span>
                      ))}
                    </div>
                  </div>
                </div>
              )
            })()}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 18 }}>
              <div>
                <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Theme exposure</div>
                {themes.map((t: any) => (
                  <div key={t.name} title={(t.by_stock ?? []).map((s: any) => `${s.symbol} $${Math.round(s.value).toLocaleString()}`).join(' · ')} style={{ marginBottom: 7, cursor: 'help' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11 }}>
                      <span style={{ color: 'var(--text1)' }}>{t.name}</span>
                      <span style={{ color: 'var(--text2)' }}>${Math.round(t.value).toLocaleString()} · <b style={{ color: '#60a5fa' }}>{t.pct}%</b></span>
                    </div>
                    <div style={{ height: 6, background: 'var(--bg2)', borderRadius: 3, marginTop: 2 }}>
                      <div style={{ height: '100%', width: `${t.pct / maxThemePct * 100}%`, background: '#60a5fa', borderRadius: 3 }} />
                    </div>
                  </div>
                ))}
              </div>
              <div>
                <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Top underlying stocks (look-through)</div>
                {top.slice(0, 15).map((s: any) => (
                  <div key={s.symbol} title={'Held via:\n' + (s.in ?? []).map((x: any) => `  ${x.src} — $${Math.round(x.value).toLocaleString()}`).join('\n')} style={{ marginBottom: 6, cursor: 'help' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11 }}>
                      <span style={{ fontFamily: 'monospace', color: 'var(--text1)' }}>{s.symbol} <span style={{ fontSize: 8.5, color: 'var(--text4)' }}>ⓘ</span></span>
                      <span style={{ color: 'var(--text2)' }}>${Math.round(s.value).toLocaleString()} · <b style={{ color: s.pct >= 8 ? '#ef4444' : s.pct >= 5 ? '#f59e0b' : '#22c55e' }}>{s.pct}%</b></span>
                    </div>
                    <div style={{ height: 6, background: 'var(--bg2)', borderRadius: 3, marginTop: 2 }}>
                      <div style={{ height: '100%', width: `${s.pct / maxStockPct * 100}%`, background: s.pct >= 8 ? '#ef4444' : s.pct >= 5 ? '#f59e0b' : '#22c55e', borderRadius: 3 }} />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )
      })()}

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
            setSigTab('All')
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
      {tab === 'Forecast' && (() => {
        const f = forecast?.data ?? forecast ?? {}
        const proj = f.projections ?? {}
        const payers = f.top_dividend_payers ?? []
        return (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 10 }}>
              {[
                { k: 'Annual dividend income', v: fmt$(f.annual_dividend_income ?? 0, 0), c: '#22c55e' },
                { k: 'Monthly avg', v: fmt$(f.monthly_dividend_avg ?? 0, 0), c: 'var(--text0)' },
                { k: 'Portfolio yield', v: `${(f.portfolio_yield_pct ?? 0).toFixed(2)}%`, c: '#60a5fa' },
                { k: 'Retirement age', v: f.retirement_age ?? '—', c: '#a855f7' },
              ].map(s => (
                <div key={s.k} style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 8, padding: '10px 8px', textAlign: 'center' }}>
                  <div style={{ fontSize: 17, fontWeight: 700, color: s.c }}>{s.v}</div>
                  <div style={{ fontSize: 8, color: 'var(--text3)', textTransform: 'uppercase' }}>{s.k}</div>
                </div>
              ))}
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
              <div className={terminalUi ? 'cc-panel' : undefined} style={terminalUi ? hubPanel(terminalUi) : { background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14 }}>
                <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Projections (10y)</div>
                {Object.entries(proj).map(([k, v]: any) => (
                  <div key={k} style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 0', borderBottom: '1px solid var(--border)', fontSize: 11 }}>
                    <span style={{ color: 'var(--text3)', textTransform: 'capitalize' }}>{k}</span>
                    <span style={{ color: 'var(--text0)', fontWeight: 600 }}>{typeof v === 'object' ? fmt$(v.value ?? v.projected_value ?? v.total ?? 0, 0) : (typeof v === 'number' ? fmt$(v, 0) : String(v))}</span>
                  </div>
                ))}
              </div>
              <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14, maxHeight: 240, overflowY: 'auto' }}>
                <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Top Dividend Payers</div>
                {payers.slice(0, 10).map((p: any, i: number) => (
                  <div key={i} style={{ display: 'grid', gridTemplateColumns: '1fr auto auto', gap: 8, padding: '3px 0', borderBottom: '1px solid var(--border)', fontSize: 10, alignItems: 'center' }}>
                    <span style={{ fontFamily: 'monospace', color: 'var(--text1)' }}>{p.symbol} <ProAnalystPill symbol={p.symbol} map={paMap} compact /></span>
                    <span style={{ color: '#22c55e' }}>{Number(p.yield_pct ?? 0).toFixed(1)}%</span>
                    <span style={{ color: 'var(--text2)' }}>{fmt$(p.annual_income ?? 0, 0)}/y</span>
                  </div>
                ))}
              </div>
            </div>
            <div style={{ fontSize: 8, color: 'var(--text3)' }}>Source: /api/v2/forecast — {f.assumptions?.basis ?? 'dividend-income projection'}. {f.assumptions?.limitations ?? ''}</div>
          </div>
        )
      })()}

      {tab === 'Tax' && (
        <div className={terminalUi ? 'cc-panel' : undefined} style={tabPanel}>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 8, display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap' }}>
            <span>Tax Lots ({taxLots?.count ?? 0})</span>
            {taxLots?.total_unrealized_gain != null && (
              <span style={{ fontSize: 12, fontWeight: 800, color: taxLots.total_unrealized_gain >= 0 ? 'var(--green)' : 'var(--red)' }}>
                {taxLots.total_unrealized_gain >= 0 ? '+' : ''}{fmt$(taxLots.total_unrealized_gain, 0)} unrealized
              </span>
            )}
            {taxLots?.reconciled_to_holdings === false && (
              <span style={{ fontSize: 10, fontWeight: 700, color: 'var(--amber)' }}>⚠ not reconciled</span>
            )}
          </div>
          {(taxLots?.harvest_candidates ?? 0) > 0 && (
            <div style={{ marginBottom: 10, padding: '6px 10px', background: 'rgba(245,158,11,.06)', border: '1px solid rgba(245,158,11,.15)', borderRadius: 6, fontSize: 11, color: 'var(--amber)' }}>
              {taxLots.harvest_candidates} taxable-loss harvest candidate{taxLots.harvest_candidates === 1 ? '' : 's'}
              {taxLots?.worthless_security_loss ? ` · incl. ${fmt$(taxLots.worthless_security_loss, 0)} worthless-security losses` : ''}
            </div>
          )}
          {Array.isArray(taxLots?.lots) && taxLots.lots.length > 0 && (
            <div style={{ overflowX: 'auto', marginBottom: 10 }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
                <thead>
                  <tr style={{ color: 'var(--text3)' }}>
                    <th style={{ textAlign: 'left', padding: '4px 8px' }}>Symbol</th>
                    <th style={{ textAlign: 'left', padding: '4px 8px' }}>Account</th>
                    <th style={{ textAlign: 'right', padding: '4px 8px' }}>Shares</th>
                    <th style={{ textAlign: 'right', padding: '4px 8px' }}>Cost basis</th>
                    <th style={{ textAlign: 'right', padding: '4px 8px' }}>Value</th>
                    <th style={{ textAlign: 'right', padding: '4px 8px' }}>Unrealized</th>
                    <th style={{ textAlign: 'right', padding: '4px 8px' }}>%</th>
                    <th style={{ textAlign: 'left', padding: '4px 8px' }}>Term</th>
                  </tr>
                </thead>
                <tbody>
                  {taxLots.lots.map((l: any, i: number) => (
                    <tr key={i} style={{ borderTop: '1px solid rgba(148,163,184,.12)', color: 'var(--text1)' }}>
                      <td style={{ textAlign: 'left', padding: '4px 8px', fontWeight: 700, color: 'var(--text0)' }}>{l.symbol}{l.worthless ? ' ⚠' : ''}</td>
                      <td style={{ textAlign: 'left', padding: '4px 8px', color: 'var(--text3)' }}>{String(l.account || '').replace('schwab_', '')}</td>
                      <td style={{ textAlign: 'right', padding: '4px 8px', fontFamily: 'monospace' }}>{l.shares}</td>
                      <td style={{ textAlign: 'right', padding: '4px 8px', fontFamily: 'monospace' }}>{fmt$(l.cost_basis, 0)}</td>
                      <td style={{ textAlign: 'right', padding: '4px 8px', fontFamily: 'monospace' }}>{fmt$(l.current_value, 0)}</td>
                      <td style={{ textAlign: 'right', padding: '4px 8px', fontFamily: 'monospace', fontWeight: 700, color: (l.unrealized_gain ?? 0) >= 0 ? 'var(--green)' : 'var(--red)' }}>{(l.unrealized_gain ?? 0) >= 0 ? '+' : ''}{fmt$(l.unrealized_gain, 0)}</td>
                      <td style={{ textAlign: 'right', padding: '4px 8px', fontFamily: 'monospace', color: (l.gain_pct ?? 0) >= 0 ? 'var(--green)' : 'var(--red)' }}>{l.gain_pct}%</td>
                      <td style={{ textAlign: 'left', padding: '4px 8px', color: 'var(--text3)' }}>{l.holding_period}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <div style={{ fontSize: 10, color: 'var(--text3)' }}>{taxLots?.data_note ?? 'Source: /api/v2/tax-lots'}</div>
        </div>
      )}
    </div>
  )
}
