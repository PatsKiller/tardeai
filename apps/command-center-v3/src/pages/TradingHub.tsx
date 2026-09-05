import { useEffect, useState, type CSSProperties } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import {
  parseTradingDeepLink,
  tradingTabSearchParams,
  TRADING_TABS,
  type TradingTab,
} from '../lib/tradingDeepLink'
import { buildTradingTriage } from '../lib/tradingCommandTriage'
// One classifier, shared with MetricStrip. These four lived here unexported,
// which is why the header could not see the run health this panel renders.
import {
  classifyRunHealth,
  runHealthReasonCodes,
  reasonCodeOneLiner,
  hasReasonGloss,
  runHealthChipColor,
  type RunHealthTier,
} from '../lib/runHealth'
import TradingDeskHealth from '../components/TradingDeskHealth'
import TradingCommandTriage from '../components/TradingCommandTriage'
import { Link } from 'react-router-dom'
import {
  downloadExecutionQualityCsv,
  filterExecutionByDays,
} from '../lib/exportExecutionQualityCsv'
import { summarizeReconByBroker } from '../lib/brokerReconSummary'
import {
  pageSlice, toggleSelectedSymbol, selectSymbols, deselectSymbols, dedupeSymbols,
  formatThinkorswimSymbols, selectionStorageKey, getSocialScoutPill, getTopGainerPill,
  getSqueezePill, getRunnerPill, getMicroFloatPill, getLowPricePill,
  getSocialAwarenessPill, isSocialAwarenessRow,
  isSqueezeRow, isRunnerRow, isMicroFloatRow, isManualReviewRow,
  sortTickerList, type ScannerSortMode, type TosFormat,
} from '../lib/scannerSelection'
import SchwabAccountsMonitor from '../components/SchwabAccountsMonitor'
import ScalpSetupsPanel from '../components/ScalpSetupsPanel'
import ScalpStrategyModal, { type Setup } from '../components/ScalpStrategyModal'
import { fmt$, fmtVol } from '../lib/format'
import type { DrillContext } from '../components/DetailDrawer'
import ProtectionPanel from '../components/ProtectionPanel'
// ProposalsRich archived (_archive/20260702) — Proposals tab uses <BrokerProposals/> only.
import BrokerOrders from '../components/BrokerOrders'
import TimeExitProposals from '../components/TimeExitProposals'
import ATMControlPanel from '../components/ATMControlPanel'
import OpenTradesIntelligence from '../components/OpenTradesIntelligence'
import ProAnalystPill, { useProAnalystMap } from '../components/ProAnalystPill'
import CountryFlag from '../components/CountryFlag'
import ManualTosDesk from './ManualTosDesk'
import BrokerProposals from '../components/BrokerProposals'
import OptionsHub from './OptionsHub'
import { useTerminalUi } from '../lib/terminalUi'
import { hubTitle, hubSubtitle, hubTab, hubFilterSelect, hubKpiChip, hubPanel } from '../lib/terminalHubChrome'
import { runLabel } from '../lib/homeLabels'
import { tradeAiSurfaceFreshness } from '../lib/surfaceFreshness'
import { renderSetupCounts } from '../lib/setupRunSummary'
import { BB, TYPE } from '../lib/watchTokens'

interface Props { onDrill: (ctx: DrillContext) => void }
const TABS = TRADING_TABS

// GO / WAIT / MANUAL_REVIEW / NO-GO decision color
const decisionColor = (d?: string) => d === 'GO' ? '#22c55e' : d === 'WAIT' ? '#f59e0b' : d === 'MANUAL_REVIEW' ? 'var(--squeeze)' : '#ef4444'

const NY_TZ = 'America/New_York'

/**
 * STALE SESSION / empty-cache honesty for the Trade AI scanner surface.
 * Delegates to tradeAiSurfaceFreshness so session-normalized run_date cannot
 * hide a multi-day empty stale cache (bisect 2026-08-28). Display-only.
 */
function isTradeAiStaleSession(tradeAi: any): boolean {
  return tradeAiSurfaceFreshness(tradeAi).stale
}


/** Rank for scalp signal selection: GO > WAIT > others. */
function scalpDecisionRank(decision?: string): number {
  const d = String(decision || '').toUpperCase().replace(/_/g, '-')
  if (d === 'GO') return 3
  if (d === 'WAIT') return 2
  return 1
}

/** Grade rank: A > B > C > D > F > unknown. */
function scalpGradeRank(grade?: string): number {
  const g = String(grade || '').toUpperCase()
  if (g === 'A') return 5
  if (g === 'B') return 4
  if (g === 'C') return 3
  if (g === 'D') return 2
  if (g === 'F') return 1
  return 0
}

/** True when `a` is the better row for dedupe (decision → grade → score). */
function isBetterScalpSignal(a: any, b: any): boolean {
  const da = scalpDecisionRank(a?.decision)
  const db = scalpDecisionRank(b?.decision)
  if (da !== db) return da > db
  const ga = scalpGradeRank(a?.grade)
  const gb = scalpGradeRank(b?.grade)
  if (ga !== gb) return ga > gb
  return (Number(a?.score) || 0) > (Number(b?.score) || 0)
}

/**
 * Client-side dedupe of /api/v2/scalp/live signals by uppercase symbol.
 * Keeps the best-ranked row per symbol. Display-only — does not change backend contracts.
 */
function dedupeScalpSignalsBySymbol(sigs: any[]): { unique: any[]; rawCount: number } {
  const best = new Map<string, any>()
  for (const row of sigs) {
    const sym = String(row?.symbol || '').toUpperCase()
    if (!sym) continue
    const normalized = { ...row, symbol: sym }
    const prev = best.get(sym)
    if (!prev || isBetterScalpSignal(normalized, prev)) best.set(sym, normalized)
  }
  return { unique: [...best.values()], rawCount: sigs.length }
}


export default function TradingHub({ onDrill }: Props) {
  const [terminalUi] = useTerminalUi()
  // Deep-link support (WP-T1): /trading?tab=…&symbol=…&proposal=…&intent=…
  // Telegram /go/order and /go/proposal rewrite into these params (App.tsx).
  const [searchParams, setSearchParams] = useSearchParams()
  const deepLink = parseTradingDeepLink(searchParams)
  const urlTab = deepLink.tab
  const urlProposal = deepLink.proposal
  const [tab, setTabState] = useState<TradingTab>(urlTab)
  useEffect(() => { setTabState(urlTab) }, [urlTab])
  /** URL-synced tab change — shareable desk state (Portfolio parity). */
  const setTab = (next: TradingTab) => {
    setTabState(next)
    setSearchParams(tradingTabSearchParams(searchParams, next), { replace: true })
  }
  // C2 monitor → "edit as DRAFT" hands a seeded intent to the Broker Orders Active Trader panel
  const [draftSeed, setDraftSeed] = useState<any | null>(null)
  const [activeTraderStrategiesOpen, setActiveTraderStrategiesOpen] = useState(false)
  const [tradeFilter, setTradeFilter] = useState<'ACTIONABLE' | 'GO' | 'WAIT' | 'MANUAL' | 'SCOUT' | 'AWARENESS'>('ACTIONABLE')
  const [tradeSort, setTradeSort] = useState<ScannerSortMode>('awareness')
  const [copied, setCopied] = useState<string | null>(null)
  // Trade AI scanner: top-30 pagination + persistent cross-page symbol selection + Thinkorswim copy.
  // Selection persists in localStorage keyed by day so it survives refresh/pagination but does not
  // linger across scanner runs forever. Awareness/selection only — never executes or validates.
  const scanDay = new Date().toISOString().slice(0, 10)
  const selKey = selectionStorageKey(scanDay)
  const [selectedSyms, setSelectedSyms] = useState<string[]>(() => {
    try { return dedupeSymbols(JSON.parse(localStorage.getItem(selKey) || '[]')) } catch { return [] }
  })
  const persistSel = (next: string[]) => {
    const deduped = dedupeSymbols(next)
    setSelectedSyms(deduped)
    try { localStorage.setItem(selKey, JSON.stringify(deduped)) } catch { /* private mode */ }
  }
  const [scannerPage, setScannerPage] = useState(1)
  const [tosFormat, setTosFormat] = useState<TosFormat>('comma')
  const [tosCopied, setTosCopied] = useState(false)
  // WP-T6: TCA lookback window (client-side filter)
  const [execDays, setExecDays] = useState<number | 'all'>(90)
  // Broker desk tab: skip heavy hub polls so single-threaded API can serve broker-proposals first.
  const brokerDesk = tab === 'Proposals' || tab === 'Broker Orders' || tab === 'Schwab Accounts'
  // Pure Schwab program tabs — hub chrome is Schwab-specific (not paper vs Path B counts).
  const pureSchwabTabs = tab === 'Broker Orders' || tab === 'Schwab Accounts'
  // Slim scanner projection (~10% of the full /trade-ai payload) — full universe rows are
  // trimmed server-side; the multi-MB full endpoint 500-looped under load (2026-07-17).
  const { data: tradeAi, error: tradeAiError, loading: tradeAiLoading } = useApi<any>('/api/v2/trade-ai/scanner', 60_000, { enabled: tab === 'Trade AI' })
  const { data: warriorAudit } = useApi<any>('/api/v2/warrior-audit/latest', 300_000, { enabled: tab === 'Trade AI' })
  const paMap = useProAnalystMap()
  // Do not stampede the single-process API while the default Trade AI tab
  // is still painting the scanner (941-row payload + 8 sibling polls = empty desk).
  const scannerSettled = tab !== 'Trade AI' || !!tradeAi || !!tradeAiError
  const { data: openTrades } = useApi<any>('/api/v2/open-trades', 30_000, { enabled: (tab === 'Open Trades' || !brokerDesk) && scannerSettled })
  // WP-T3 triage: position intelligence summary (risk flags) — hub-wide, slower poll
  const { data: openIntel, loading: openIntelLoading } = useApi<any>('/api/v2/open-trades/intelligence', 120_000, {
    enabled: !pureSchwabTabs && scannerSettled,
  })
  // Paper PENDING+AFPT — validation/Alpaca pipeline only (NOT Path B broker queue).
  const { data: proposals } = useApi<any>('/api/v2/paper-proposals', 60_000, { enabled: !pureSchwabTabs && scannerSettled })
  // Path B truth for operator queue size — queue_summary.total (active broker entries).
  const { data: brokerQueueSummary } = useApi<any>('/api/v2/broker-proposals/summary', 120_000, { enabled: !pureSchwabTabs && scannerSettled })
  // Light list probe for pagination.total when summary is thin / unavailable (same active population).
  const { data: brokerQueueList } = useApi<any>('/api/v2/broker-proposals?page=1&page_size=1', 120_000, {
    enabled: !pureSchwabTabs && scannerSettled && brokerQueueSummary == null,
  })
  const { data: paperStatus } = useApi<any>('/api/v2/paper-status', 30_000, { enabled: scannerSettled })
  const { data: readiness } = useApi<any>('/api/v2/paper-trade-readiness', 120_000, { enabled: !brokerDesk && scannerSettled })
  const { data: execState } = useApi<any>('/api/v2/execution/current-state', 120_000, { enabled: !brokerDesk && scannerSettled })
  const { data: execQual, loading: execQualLoading, error: execQualError } = useApi<any>('/api/v2/execution-quality', 120_000, { enabled: tab === 'Execution' })
  const { data: scalpData } = useApi<any>('/api/v2/scalp/live', 120_000, { enabled: tab === 'Scalp' })
  const { data: scalpExt } = useApi<any>('/api/v2/hermes/subject-intel-map?type=scalp', 120_000, { enabled: tab === 'Scalp' })
  const scalpExtMap: Record<string, any[]> = scalpExt?.map ?? {}
  const { data: setupAdvisory } = useApi<any>('/api/v2/atm/setup-advisory', 120_000, { enabled: tab === 'Open Trades' || tab === 'ATM Controls' })
  // Recon for tab body + hub triage (unmatched breaks)
  const { data: recon } = useApi<any>('/api/v2/broker-reconciliation', 120_000, {
    enabled: (tab === 'Broker Recon' || !pureSchwabTabs) && scannerSettled,
  })
  // Pilot standing approvals for 2FA triage chip
  const { data: pilotStatus } = useApi<any>('/api/v2/broker-orders/pilot/status', 60_000, {
    enabled: (!pureSchwabTabs || tab === 'Broker Orders') && scannerSettled,
  })

  const advMap: Record<string, any> = {}
  const advBySym: Record<string, any> = {}
  for (const a of (setupAdvisory?.advisories ?? [])) {
    advMap[String(a.proposal_id)] = a
    // Map advisory to symbol for open-position enrichment; prefer non-expired / higher-confidence
    const prev = advBySym[a.symbol]
    if (!prev || (prev.status === 'EXPIRED' && a.status !== 'EXPIRED')) advBySym[a.symbol] = a
  }
  const advColor = (f?: string) => f === 'caution' ? '#ef4444' : f === 'favorable' ? '#22c55e' : 'var(--text3)'

  const trades = openTrades?.trades ?? []
  const execRaw: any[] = Array.isArray(execQual)
    ? execQual
    : Array.isArray((execQual as any)?.fills)
      ? (execQual as any).fills
      : Array.isArray((execQual as any)?.rows)
        ? (execQual as any).rows
        : []
  const execList: any[] = filterExecutionByDays(execRaw, execDays)
  const propList = proposals?.proposals ?? []
  const pending = propList.filter((p: any) => p.status === 'PENDING' || p.status === 'APPROVED_FOR_PAPER_TEST')
  // Paper pending = API whole-table PENDING+AFPT (not the LIMIT-50 list; not Path B broker queue).
  const paperPendingCount = proposals
    ? Number(proposals.pending_count ?? pending.length)
    : null
  // Path B broker queue size: prefer queue_summary.total, else pagination.total for active list.
  const brokerQueueCount = (() => {
    const fromSummary = brokerQueueSummary?.total
    if (fromSummary != null && Number.isFinite(Number(fromSummary))) return Number(fromSummary)
    const qs = brokerQueueList?.queue_summary
    if (qs?.total != null && Number.isFinite(Number(qs.total))) return Number(qs.total)
    const pag = brokerQueueList?.pagination?.total
    if (pag != null && Number.isFinite(Number(pag))) return Number(pag)
    return null
  })()
  const alpaca = paperStatus?.alpaca ?? {}
  const fmtCount = (n: number | null) => (n == null ? '—' : String(n))

  // WP-T3: command triage chips (pure, fail-closed)
  const queueForTriage = brokerQueueSummary ?? brokerQueueList?.queue_summary ?? null
  const triageChips = buildTradingTriage({
    intelSummary: openIntel?.summary ?? null,
    intelPositions: openIntel?.positions ?? null,
    queueSummary: queueForTriage,
    recon: recon ?? null,
    pilot: pilotStatus ?? null,
    paperPending: paperPendingCount,
  })
  const navigateTriage = (nextTab: TradingTab, params?: Record<string, string>) => {
    setTabState(nextTab)
    const next = tradingTabSearchParams(searchParams, nextTab)
    if (params) {
      for (const [k, v] of Object.entries(params)) {
        if (v) next.set(k, v)
      }
    }
    setSearchParams(next, { replace: true })
  }

  return (
    <div>
      <div className="hub-title-row" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 10 }}>
        <div>
          <div style={hubTitle()}>Trading</div>
          <div style={hubSubtitle(terminalUi)}>
            Path A Entry Desk · Path B Proposals + per-order 2FA · AUTO LIVE BLOCKED unless 2FA path · Stop Management on Portfolio
          </div>
        </div>
        <div className="hub-tabs" role="tablist" aria-label="Trading desk tabs" style={{ display: 'flex', gap: terminalUi ? 4 : 6, flexWrap: 'wrap' }}>
          {TABS.map(t => (
            <button
              key={t}
              type="button"
              role="tab"
              aria-selected={tab === t}
              onClick={() => setTab(t)}
              style={hubTab(tab === t, terminalUi)}
            >
              {t}
            </button>
          ))}
        </div>
      </div>

      <TradingDeskHealth
        openCount={trades.length}
        paperPending={paperPendingCount}
        brokerQueue={brokerQueueCount}
        readinessLevel={readiness?.level}
        readinessPct={readiness?.pct_to_2000}
        liveVia2faAllowed={execState?.operator_live_via_2fa_allowed}
        alpacaStatus={alpaca.account_status ?? null}
        pureSchwabTabs={pureSchwabTabs}
      />

      {!pureSchwabTabs && (
        <TradingCommandTriage
          chips={triageChips}
          loading={openIntelLoading && !openIntel}
          onNavigate={navigateTriage}
        />
      )}

      {/* Readiness bar */}
      {readiness && tab === 'Proposals' && (
        <div className={terminalUi ? 'cc-panel' : undefined} style={{ marginBottom: 14, ...(terminalUi ? hubPanel(terminalUi) : { padding: '8px 14px', background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 8 }), fontSize: terminalUi ? 9 : 10 }}>
          <span style={{ color: 'var(--text3)' }}>Validation Readiness:</span>
          <span style={{ fontWeight: 700, color: '#f59e0b', marginLeft: 8 }}>{readiness.level?.replace(/_/g, ' ')}</span>
          <span style={{ color: 'var(--text3)', marginLeft: 12 }}>
            {readiness.level === 'P0_NOT_ENOUGH_DATA'
              ? ' — empirical validation sample still thin; Path B caps are advisory until maturity gates pass.'
              : ' — live route gates reflect current validation tier.'}
          </span>
        </div>
      )}
      {readiness && tab !== 'Proposals' && tab !== 'Broker Orders' && (
        <div className={terminalUi ? 'cc-panel' : undefined} style={{ marginBottom: 14, ...(terminalUi ? hubPanel(terminalUi) : { padding: '8px 14px', background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 8 }), display: 'flex', gap: 20, alignItems: 'center', fontSize: terminalUi ? 9 : 10 }}>
          <span style={{ color: 'var(--text3)' }}>Validation Readiness:</span>
          <span style={{ fontWeight: 700, color: '#f59e0b' }}>{readiness.level?.replace(/_/g, ' ')}</span>
          <span style={{ color: 'var(--text3)' }}>{readiness.closed_usable}/{readiness.target_2000} trades</span>
          <div style={{ flex: 1, height: 4, background: 'var(--bg2)', borderRadius: 2 }}>
            <div style={{ width: `${Math.min(100, readiness.pct_to_2000 ?? 0)}%`, height: '100%', background: '#f59e0b', borderRadius: 2, minWidth: 2 }} />
          </div>
          <span
            title={execState?.operator_status_label || ''}
            style={{ color: execState?.operator_live_via_2fa_allowed ? '#22c55e' : '#f59e0b', fontWeight: 700, fontSize: 9 }}
          >
            {execState?.operator_live_via_2fa_allowed ? '2FA LIVE ON' : 'AUTO LIVE BLOCKED'}
          </span>
        </div>
      )}
      {tab === 'Proposals' && (
        <div className={terminalUi ? 'cc-panel' : undefined} style={{ marginBottom: 14, ...(terminalUi ? hubPanel(terminalUi) : { padding: '8px 14px', background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 8 }), fontSize: terminalUi ? 9 : 10, color: 'var(--text2)', lineHeight: 1.45 }}>
          Path B operator route — P0 validation caps are advisory. <span style={{ color: 'var(--text0)', fontWeight: 700 }}>Auto route (2FA)</span> opens trade review (edit size/risk) before Schwab approval.
        </div>
      )}
      {tab === 'Entry Desk' && (
        <div className={terminalUi ? 'cc-panel' : undefined} style={{ marginBottom: 14, ...(terminalUi ? hubPanel(terminalUi) : { padding: '8px 14px', background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 8 }), fontSize: terminalUi ? 9 : 10, color: 'var(--text2)', lineHeight: 1.45 }}>
          Path A — manual Thinkorswim. Rating, R:R, and exit ladder are <b>deterministic</b> on this tab; watchlist agent maturity shows when DB has it. <b>Stage 2b + Auto route (2FA)</b> are on{' '}
          <button type="button" onClick={() => setTab('Proposals')} style={{ background: 'none', border: 'none', padding: 0, color: '#60a5fa', fontWeight: 700, cursor: 'pointer', fontSize: 10 }}>Proposals</button>.
        </div>
      )}

      {tab === 'Trade AI' && (() => {
        // Phase 203: do NOT render the KPI grid as 0/0/0/no-run when the API fetch is loading or
        // errored — that silently masks a transient backend issue (e.g. DB contention) as an empty
        // scanner. Show an explicit state instead. Genuine empty data still renders below.
        if (!tradeAi) {
          const errored = !!tradeAiError
          const pending = tradeAiLoading || !errored
          return (
            <div className={terminalUi ? 'cc-panel' : undefined} style={{ ...(terminalUi ? hubPanel(terminalUi) : { background: 'var(--bg1)', border: `1px solid ${errored ? '#ef4444' : 'var(--border)'}`, borderRadius: 10, padding: 16 }) }}>
              <div style={{ fontSize: terminalUi ? 11 : 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 6 }}>Market Opportunities Scanner</div>
              <div style={{ fontSize: 12, color: errored ? '#ef4444' : 'var(--text3)' }}>
                {errored ? '⚠ Scanner data temporarily unavailable — /api/v2/trade-ai/scanner did not respond (auto-retrying every 60s). This is an API/data-availability issue, not necessarily an empty scan. Check backend load (e.g. a long-running backup) if it persists.'
                  : pending ? 'Loading latest scanner run…'
                  : 'Scanner returned an empty payload — not a missing file. Recheck /api/v2/trade-ai/scanner.'}
              </div>
              <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 8 }}>Source: /api/v2/trade-ai/scanner{tradeAiError ? ` · error: ${String(tradeAiError).slice(0, 80)}` : ''}</div>
            </div>
          )
        }
        const tickers: any[] = sortTickerList(tradeAi?.tickers ?? [], tradeSort)
        const isScoutRow = (t: any) => t.scout_status === 'SOCIAL_SCOUT'
        const isAwarenessRow = (t: any) => isSocialAwarenessRow(t)
        const isScreenerWaitRow = (t: any) => (t.decision || '').toUpperCase() === 'WAIT' && !isAwarenessRow(t)
        const isActionableRow = (t: any) => {
          const d = (t.decision || '').toUpperCase()
          return d === 'GO' || d === 'WAIT' || d === 'MANUAL_REVIEW' || isManualReviewRow(t)
        }
        const filtered = tradeFilter === 'ACTIONABLE' ? tickers.filter(isActionableRow)
          : tradeFilter === 'SCOUT' ? tickers.filter(isScoutRow)
          : tradeFilter === 'AWARENESS' ? tickers.filter(isAwarenessRow)
          : tradeFilter === 'MANUAL' ? tickers.filter(isManualReviewRow)
          : tradeFilter === 'WAIT' ? tickers.filter(isScreenerWaitRow)
          : tickers.filter((t: any) => t.decision === tradeFilter)
        const actionableCount = tickers.filter(isActionableRow).length
        const scoutCount = tickers.filter(isScoutRow).length
        const awarenessCount = tickers.filter(isAwarenessRow).length
        const manualCount = tickers.filter(isManualReviewRow).length
        const sortLabels: Record<ScannerSortMode, string> = {
          awareness: 'Awareness rank', score: 'Score', rvol: 'RVOL', change: 'Change %', symbol: 'Symbol A–Z',
        }
        // Top-30, 10 per page. Page count is based on the top-30 window, not the whole universe.
        const pv = pageSlice(filtered, scannerPage, 30, 10)
        const pageRows = pv.items
        // Selection helpers operate on the WHOLE selection (cross-page), independent of the page.
        const pageSymbols = pageRows.map((t: any) => t.symbol)
        const tosText = formatThinkorswimSymbols(selectedSyms, tosFormat)
        const copyBoxes = (['GO', 'WAIT', 'ALL'] as const).map(type => {
          const subset = type === 'ALL' ? tickers
            : type === 'WAIT' ? tickers.filter(isScreenerWaitRow)
            : tickers.filter((t: any) => t.decision === type && !isAwarenessRow(t))
          const syms = sortTickerList(subset, tradeSort).map((t: any) => t.symbol)
          return { type, label: type === 'ALL' ? 'Universe' : type, syms, text: syms.join(','), color: type === 'GO' ? '#22c55e' : type === 'WAIT' ? '#f59e0b' : 'var(--text2)' }
        })
        const doCopy = (type: string, text: string) => {
          const done = () => { setCopied(type); setTimeout(() => setCopied(null), 1500) }
          if (navigator.clipboard?.writeText) navigator.clipboard.writeText(text).then(done).catch(done)
          else { const ta = document.createElement('textarea'); ta.value = text; document.body.appendChild(ta); ta.select(); document.execCommand('copy'); document.body.removeChild(ta); done() }
        }
        // Source badge config (parity with v2 Source column)
        const srcCfg: Record<string, { icon: string; color: string; label: string }> = {
          social: { icon: '💬', color: '#d97706', label: 'Social' },
          portfolio: { icon: '💼', color: '#6366f1', label: 'Portfolio' },
          personal_watchlist: { icon: '👤', color: '#6366f1', label: 'Personal' },
          ai_discovered: { icon: '🤖', color: '#059669', label: 'AI' },
          ai_watchlist: { icon: '🔍', color: '#059669', label: 'AI Watch' },
          screener: { icon: '📊', color: '#0891b2', label: 'Finviz' },
        }
        const srcBadge = (t: any) => {
          const c = srcCfg[t.source || 'screener'] || srcCfg.screener
          return { ...c, label: t.source === 'social' && t.source_detail ? `Social ${t.source_detail}` : c.label }
        }
        const pctColor = (v: any) => { const n = parseFloat(v); return isNaN(n) ? 'var(--text3)' : n >= 0 ? '#22c55e' : '#ef4444' }
        const pctText = (v: any) => (v === '' || v == null) ? '—' : `${v}%`
        const pgBtn = (disabled: boolean): CSSProperties => ({
          padding: '3px 9px', fontSize: 10, borderRadius: 5, fontFamily: 'monospace',
          border: '1px solid var(--border)', background: 'var(--bg1)', color: 'var(--text2)',
          cursor: disabled ? 'not-allowed' : 'pointer', opacity: disabled ? 0.4 : 1,
        })
        // Richer ticker table layout
        // checkbox · Decision · Source · Country(flag) · Symbol · Score · Grd · RVOL · Price · Chg% · Gap% · Float · Sector · Social · Catalyst
        const gridCols = '26px 52px 72px 30px 1fr 60px 30px 48px 52px 64px 58px 58px 50px 1.3fr 1fr 1.6fr'
        const runHistory: any[] = tradeAi?.run_history ?? []
        const sectors: Record<string, number> = tradeAi?.sectors ?? {}
        const sectorEntries = Object.entries(sectors).sort((a, b) => (b[1] as number) - (a[1] as number))
        const sectorMax = sectorEntries.length ? Math.max(...sectorEntries.map(e => e[1] as number)) : 1
        const runGoMax = runHistory.length ? Math.max(1, ...runHistory.map((r: any) => r.go ?? 0)) : 1
        // KPI counts reflect the displayed universe (matching copy lists / filter / table),
        // NOT the current-run-only go_count/wait_count which read 0 on an underfilled run.
        const goN = tradeAi?.universe_go ?? tickers.filter((t: any) => t.decision === 'GO').length
        const waitN = tradeAi?.universe_wait ?? tickers.filter((t: any) => t.decision === 'WAIT').length
        const universeN = tradeAi?.universe_count ?? tickers.length
        const noGoN = tradeAi?.universe_nogo ?? Math.max(0, universeN - goN - waitN)
        const scannedN = tradeAi?.current_run_scanned ?? tradeAi?.latest_run_symbols_scanned ?? tradeAi?.ticker_count
        // Scope labels (P0 2026-07-14): these chips count the FULL SCAN UNIVERSE (latest scan
        // per symbol, today + yesterday, all runs) — intentionally wider than the header
        // SETUPS strip, which counts the LATEST RUN only (go_count/wait_count/avoid_count).
        // Both scopes come from /api/v2/trade-ai; label them so identical-looking numbers
        // can't silently disagree.
        const universeScope = 'Full scan universe — latest scan per symbol, today + yesterday, all runs (wider than the header SETUPS strip, which counts the latest run only)'
        const staleSession = isTradeAiStaleSession(tradeAi)
        const setupsFresh = tradeAiSurfaceFreshness(tradeAi)
        const healthTier = classifyRunHealth(tradeAi?.run_health_status)
        const healthCodes = runHealthReasonCodes(tradeAi)
        const healthFloor = Number(tradeAi?.expected_min_symbols)
        const healthFloorLabel = Number.isFinite(healthFloor) && healthFloor > 0 ? String(healthFloor) : 'min 40'
        const setupsRunLabel = runLabel(tradeAi?.latest_run_label || tradeAi?.run_label, tradeAi?.run_date)
        const runTsDisplay = tradeAi?.latest_run_timestamp
          ? new Date(tradeAi.latest_run_timestamp).toLocaleString('en-US', {
              timeZone: NY_TZ,
              month: 'short',
              day: 'numeric',
              year: 'numeric',
              hour: '2-digit',
              minute: '2-digit',
              timeZoneName: 'short',
            })
          : (tradeAi?.run_date ? String(tradeAi.run_date) : 'timestamp unavailable')
        const healthStatusLabel = String(tradeAi?.run_health_status || 'UNKNOWN')
        const kpis = [
          { label: 'GO', value: goN, color: '#22c55e', title: universeScope },
          { label: 'WAIT', value: waitN, color: '#f59e0b', title: universeScope },
          { label: 'NO-GO', value: noGoN, color: '#ef4444', title: universeScope },
          { label: 'Universe', value: universeN, color: 'var(--text0)', title: universeScope },
          { label: 'VIX', value: tradeAi?.vix != null ? Number(tradeAi.vix).toFixed(1) : '—', color: '#60a5fa', title: undefined as string | undefined },
          { label: 'Regime', value: tradeAi?.market_regime ?? '—', color: '#a855f7', title: undefined as string | undefined },
        ]
        return (
          <div className={terminalUi ? 'cc-panel' : undefined} style={terminalUi ? hubPanel(terminalUi) : { background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 4 }}>
              <div style={{ fontSize: terminalUi ? 11 : 13, fontWeight: 700, color: 'var(--text0)' }}>Market Opportunities Scanner</div>
              <div style={{ fontSize: 10, color: 'var(--text3)' }}>
                {tradeAi?.latest_run_label || tradeAi?.run_label || 'no run'}
                {tradeAi?.latest_run_timestamp && ` · ${new Date(tradeAi.latest_run_timestamp).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}`}
                {scannedN != null && ` · ${scannedN} scanned this run`}
                {tradeAi?.run_health_status && (
                  <span
                    style={{ marginLeft: 6, color: runHealthChipColor(healthTier), fontWeight: 800 }}
                    data-testid="trade-ai-run-health-chip"
                    title={healthCodes.length ? healthCodes.join(', ') : healthStatusLabel}
                  >
                    · {healthStatusLabel}
                  </span>
                )}
                {staleSession && <span style={{ marginLeft: 6, color: BB.amber, fontWeight: 800 }}>· STALE SESSION</span>}
              </div>
            </div>
            {staleSession && (
              <div
                role="status"
                data-testid="trade-ai-stale-session-banner"
                style={{
                  marginTop: 8,
                  marginBottom: 4,
                  padding: '10px 12px',
                  borderRadius: 8,
                  border: `1px solid ${BB.amber}`,
                  background: BB.amberDim,
                  color: 'var(--text0)',
                  fontSize: TYPE.sm,
                  lineHeight: 1.45,
                }}
              >
                <div style={{ fontWeight: 800, color: BB.amber, fontSize: TYPE.md, marginBottom: 4 }}>
                  {setupsFresh.surfaceLabel || 'STALE SESSION'} — not a live scan claim (HTTP 200 ≠ live)
                </div>
                <div style={{ color: 'var(--text1)', fontSize: TYPE.sm }}>
                  Last run: <b>{setupsRunLabel}</b>
                  {' · '}
                  <b>{runTsDisplay}</b>
                  {setupsFresh.asOf && <> · cache as_of <b>{String(setupsFresh.asOf).slice(0, 19).replace('T', ' ')}</b></>}
                  {setupsFresh.reason && <> · {setupsFresh.reason}</>}
                  {' · '}
                  universe <b>{goN}</b> GO / <b>{waitN}</b> WAIT
                  {universeN != null && <> · {universeN} symbols in panel</>}
                  {scannedN != null && <> · current-run scanned {scannedN}</>}
                </div>
                <div style={{ marginTop: 4, color: 'var(--text2)', fontSize: TYPE.sm }}>
                  Empty or prior-day rows here are upstream data (or an empty stale cache), not a missing route.
                  Header SETUPS shows the same STALE surface. No new scan is started from this page.
                </div>
              </div>
            )}
            {healthTier === 'underfilled' && (
              <div
                role="status"
                data-testid="trade-ai-run-underfilled-banner"
                style={{
                  marginTop: 8,
                  marginBottom: 4,
                  padding: '10px 12px',
                  borderRadius: 8,
                  border: `1px solid ${BB.amber}`,
                  background: BB.amberDim,
                  color: 'var(--text0)',
                  fontSize: TYPE.sm,
                  lineHeight: 1.45,
                }}
              >
                <div style={{ fontWeight: 800, color: BB.amber, fontSize: TYPE.md, marginBottom: 4 }}>
                  RUN UNDERFILLED — latest run scanned fewer symbols than the health floor
                </div>
                <div style={{ color: 'var(--text1)', fontSize: TYPE.sm }}>
                  Status <b>{healthStatusLabel}</b>
                  {' · '}
                  current-run scanned <b>{scannedN != null ? scannedN : '—'}</b>
                  {' · '}
                  health floor <b>{healthFloorLabel}</b>
                  {universeN != null && <> · panel universe {universeN}</>}
                </div>
                {healthCodes.length > 0 && (
                  <div style={{ marginTop: 4, color: 'var(--text1)', fontSize: TYPE.sm }}>
                    Reasons:{' '}
                    {healthCodes.map((code, i) => (
                      <span key={code}>
                        {i > 0 ? ' · ' : ''}
                        {/* A code with no gloss returns itself, which rendered
                            "UNIVERSE_TOO_SMALL — UNIVERSE_TOO_SMALL" live. */}
                        <b>{code}</b>{hasReasonGloss(code) ? <> — {reasonCodeOneLiner(code)}</> : null}
                      </span>
                    ))}
                  </div>
                )}
                <div style={{ marginTop: 4, color: 'var(--text2)', fontSize: TYPE.sm }}>
                  Panel universe may still include social/prior-day overlay; <b>current-run scanned</b> is the health numerator.
                  Underfill is not the same as STALE SESSION or RUN FAILED. No scan is started from this page.
                </div>
              </div>
            )}
            {healthTier === 'failed' && (
              <div
                role="status"
                data-testid="trade-ai-run-failed-banner"
                style={{
                  marginTop: 8,
                  marginBottom: 4,
                  padding: '10px 12px',
                  borderRadius: 8,
                  border: `1px solid ${BB.red}`,
                  background: BB.redDim,
                  color: 'var(--text0)',
                  fontSize: TYPE.sm,
                  lineHeight: 1.45,
                }}
              >
                <div style={{ fontWeight: 800, color: BB.red, fontSize: TYPE.md, marginBottom: 4 }}>
                  RUN FAILED — latest screener run did not complete a usable ingest
                </div>
                <div style={{ color: 'var(--text1)', fontSize: TYPE.sm }}>
                  Status <b>{healthStatusLabel}</b>
                  {' · '}
                  current-run scanned <b>{scannedN != null ? scannedN : '—'}</b>
                  {universeN != null && <> · panel universe {universeN}</>}
                </div>
                {healthCodes.length > 0 && (
                  <div style={{ marginTop: 4, color: 'var(--text1)', fontSize: TYPE.sm }}>
                    Reasons:{' '}
                    {healthCodes.map((code, i) => (
                      <span key={code}>
                        {i > 0 ? ' · ' : ''}
                        {/* A code with no gloss returns itself, which rendered
                            "UNIVERSE_TOO_SMALL — UNIVERSE_TOO_SMALL" live. */}
                        <b>{code}</b>{hasReasonGloss(code) ? <> — {reasonCodeOneLiner(code)}</> : null}
                      </span>
                    ))}
                  </div>
                )}
                <div style={{ marginTop: 4, color: 'var(--text2)', fontSize: TYPE.sm }}>
                  This is ingest/auth failure — not underfill and not merely a prior session. No scan is started from this page.
                </div>
              </div>
            )}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6,1fr)', gap: terminalUi ? 4 : 8, margin: '10px 0 6px' }}>
              {kpis.map(k => (
                <div key={k.label} title={k.title} style={{ ...(terminalUi ? hubKpiChip(false, true) : { background: 'var(--bg2)', borderRadius: 8, padding: '8px 6px' }), textAlign: 'center', cursor: k.title ? 'help' : 'default' }}>
                  <div style={{ fontSize: terminalUi ? 14 : 17, fontWeight: 700, color: k.color }}>{k.value}</div>
                  <div style={{ fontSize: terminalUi ? 7 : 8, color: 'var(--text3)', textTransform: 'uppercase' }}>{k.label}</div>
                </div>
              ))}
            </div>
            <div style={{ fontSize: 10, color: 'var(--text3)', margin: '0 0 12px' }}>
              Scope: full scan universe (latest scan per symbol · today + yesterday · all runs).
              Header SETUPS = latest run only: {(() => {
                const run = renderSetupCounts(tradeAi?.setup_run_summary, {})
                if (!run.population) return run.counts
                const integrity = run.degraded ? ` · ${run.integrity}` : ''
                return `${run.counts} · ${run.population}${integrity} · run ${run.runId ?? tradeAi?.run_id ?? ''}`
              })()}.
              {healthTier === 'underfilled' && (
                <> Current-run health: <b style={{ color: BB.amber }}>UNDERFILLED</b> ({scannedN != null ? scannedN : '—'} scanned).</>
              )}
              {healthTier === 'failed' && (
                <> Current-run health: <b style={{ color: BB.red }}>FAILED</b>.</>
              )}
            </div>

            {/* Copy lists (GO / WAIT / Universe) — paste into broker watchlist / ToS */}
            <div style={{ display: 'flex', gap: 8, marginBottom: 10 }}>
              {copyBoxes.map(b => (
                <div key={b.type} style={{ flex: 1, padding: '6px 10px', background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 8 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 3 }}>
                    <span style={{ fontSize: 8, color: b.color, fontWeight: 700 }}>{b.label} ({b.syms.length})</span>
                    {b.syms.length > 0 && (
                      <button onClick={() => doCopy(b.type, b.text)} style={{
                        fontSize: 8, padding: '2px 8px', borderRadius: 4, cursor: 'pointer', fontWeight: 600,
                        border: `1px solid ${copied === b.type ? '#22c55e' : 'var(--border)'}`,
                        background: copied === b.type ? 'rgba(34,197,94,.12)' : 'var(--bg1)',
                        color: copied === b.type ? '#22c55e' : 'var(--text2)',
                      }}>{copied === b.type ? '✓ Copied' : 'Copy'}</button>
                    )}
                  </div>
                  <div style={{ fontSize: 11, color: 'var(--text0)', fontFamily: 'monospace', wordBreak: 'break-all', userSelect: 'all', cursor: 'text', minHeight: 16, maxHeight: 54, overflowY: 'auto' }}>
                    {b.text || '—'}
                  </div>
                </div>
              ))}
            </div>

            {/* Decision filter — default Actionable (GO+WAIT+Manual); Ross lanes collapsed under Manual */}
            <div style={{ display: 'flex', gap: 4, marginBottom: 8, flexWrap: 'wrap', alignItems: 'center' }}>
              {(['ACTIONABLE', 'GO', 'WAIT', 'AWARENESS', 'MANUAL', 'SCOUT'] as const).map(f => {
                const active = tradeFilter === f
                const fc = f === 'GO' ? '#22c55e' : f === 'WAIT' ? '#f59e0b' : f === 'AWARENESS' ? 'var(--social-awareness)' : f === 'SCOUT' ? 'var(--social-scout)' : f === 'MANUAL' ? 'var(--squeeze)' : '#60a5fa'
                const count = f === 'ACTIONABLE' ? actionableCount : f === 'SCOUT' ? scoutCount : f === 'AWARENESS' ? awarenessCount : f === 'MANUAL' ? manualCount : f === 'WAIT' ? tickers.filter(isScreenerWaitRow).length : tickers.filter((t: any) => t.decision === f).length
                const label = f === 'ACTIONABLE' ? 'Actionable' : f === 'SCOUT' ? 'Social Scouts' : f === 'AWARENESS' ? 'Social Awareness' : f === 'MANUAL' ? 'Manual' : f
                return (
                  <button key={f} onClick={() => { setTradeFilter(f); setScannerPage(1) }} title={f === 'ACTIONABLE' ? 'GO + WAIT + MANUAL_REVIEW — what matters today; hides 1500+ NO-GO universe noise' : f === 'SCOUT' ? 'Partial social setups (≥2/5 pillars) — awareness only, never GO/validation/tradeable' : f === 'AWARENESS' ? 'Pre-market StockTwits — Finviz overlay when available; awareness only, not tradeable' : f === 'MANUAL' ? 'Squeeze · Runner · Micro-float · Low-price — Entry Desk only; never auto GO' : undefined}
                    style={{ ...hubKpiChip(active, terminalUi), fontFamily: 'monospace', color: active ? fc : (terminalUi ? undefined : 'var(--text3)') }}>{label} ({count})</button>
                )
              })}
              <div style={{ flex: 1, minWidth: 8 }} />
              <label style={{ fontSize: 9, color: 'var(--text3)', display: 'flex', alignItems: 'center', gap: 4 }}>
                Sort
                <select value={tradeSort} onChange={e => { setTradeSort(e.target.value as ScannerSortMode); setScannerPage(1) }} style={{
                  ...hubFilterSelect(terminalUi), fontFamily: 'monospace', cursor: 'pointer',
                }}>
                  {(Object.keys(sortLabels) as ScannerSortMode[]).map(k => (
                    <option key={k} value={k}>{sortLabels[k]}</option>
                  ))}
                </select>
              </label>
            </div>

            <div style={{ overflowX: 'auto' }}>
            <div style={{ minWidth: 1112 }}>
            <div style={{ display: 'grid', gridTemplateColumns: gridCols, gap: 6, fontSize: 8, color: 'var(--text3)', padding: '3px 6px', borderBottom: '1px solid var(--border)', textTransform: 'uppercase', alignItems: 'center' }}>
              <span title="Select/clear all rows on this page">
                <input type="checkbox" aria-label="Select visible page"
                  checked={pageSymbols.length > 0 && pageSymbols.every((s: string) => selectedSyms.includes(String(s).toUpperCase()))}
                  onChange={e => persistSel(e.target.checked ? selectSymbols(selectedSyms, pageSymbols) : deselectSymbols(selectedSyms, pageSymbols))}
                  style={{ cursor: 'pointer' }} />
              </span>
              <span>Decision</span><span>Source</span><span title="Headquarters country of the underlying company (ADRs show the home country, not the US listing)" style={{ cursor: 'help' }}>Ctry</span><span>Symbol</span><span>Score</span><span>Grd</span><span>RVOL</span><span title="Today's share volume from the same Finviz scan as RVOL">Vol</span><span>Price</span><span>Chg%</span><span>Gap%</span><span>Float</span><span>Sector</span><span>Social</span><span>Catalyst</span>
            </div>
            {filtered.length === 0 ? <div style={{ color: 'var(--text3)', fontSize: 11, padding: 12 }}>No {tradeFilter === 'ACTIONABLE' ? 'actionable ' : tradeFilter === 'SCOUT' ? 'Social Scout ' : tradeFilter === 'MANUAL' ? 'manual review ' : tradeFilter + ' '}rows in the latest run.</div> :
            pageRows.map((t: any, i: number) => {
              const sb = srcBadge(t)
              const social = t.social_sentiment || ''
              const socialColor = social.includes('Very Bullish') ? '#4ade80' : social.includes('Bullish') ? '#86efac' : social.includes('Bearish') ? '#f87171' : 'var(--text3)'
              const score = t.score ?? 0
              const scout = getSocialScoutPill(t)
              const socialAware = getSocialAwarenessPill(t)
              const topGainer = getTopGainerPill(t)
              const squeeze = getSqueezePill(t)
              const runner = getRunnerPill(t)
              const micro = getMicroFloatPill(t)
              const lowPrice = getLowPricePill(t)
              const sym = String(t.symbol || '').toUpperCase()
              const checked = selectedSyms.includes(sym)
              const isManualLane = squeeze.isSqueeze || runner.isRunner || micro.isMicroFloat || lowPrice.isLowPrice
              const rowAccent = socialAware.isAwareness ? 'var(--social-awareness)' : scout.isScout ? 'var(--social-scout)' : squeeze.isSqueeze ? 'var(--squeeze)' : lowPrice.isLowPrice ? 'var(--low-price)' : micro.isMicroFloat ? 'var(--micro-float)' : runner.isRunner ? 'var(--runner)' : topGainer.isTopGainer ? 'var(--top-gainer)' : decisionColor(t.decision)
              return (
              <div key={`${t.symbol}-${i}`} onClick={() => onDrill({ title: t.symbol, subtitle: `${t.decision ?? ''} · score ${t.score ?? '—'} · ${t.sector ?? ''}`, endpoint: '/api/v2/trade-ai/scanner', rows: [t] })}
                style={{ display: 'grid', gridTemplateColumns: gridCols, gap: 6, padding: '5px 6px', borderBottom: '1px solid var(--border)', cursor: 'pointer', fontSize: 10, alignItems: 'center', borderLeft: `3px solid ${rowAccent}` }}>
                <span onClick={e => e.stopPropagation()} style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                  <input type="checkbox" aria-label={`Select ${sym}`} checked={checked}
                    onChange={() => persistSel(toggleSelectedSymbol(selectedSyms, sym))} style={{ cursor: 'pointer' }} />
                </span>
                <span style={{ fontWeight: 700, fontSize: 9, color: socialAware.isAwareness ? 'var(--social-awareness)' : scout.isScout ? 'var(--social-scout)' : isManualLane ? (lowPrice.isLowPrice ? 'var(--low-price)' : squeeze.isSqueeze ? 'var(--squeeze)' : micro.isMicroFloat ? 'var(--micro-float)' : 'var(--runner)') : decisionColor(t.decision) }}>{socialAware.isAwareness ? 'AWARE' : scout.isScout ? 'SCOUT' : isManualLane ? 'MANUAL' : (t.decision || 'NO-GO')}</span>
                <span title={sb.label} style={{ fontSize: 8, fontWeight: 600, padding: '1px 4px', borderRadius: 3, border: `1px solid ${sb.color}40`, color: sb.color, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{sb.icon} {sb.label}</span>
                <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                  <CountryFlag symbol={t.symbol} country={t.country} countryName={t.country_name} size={20} />
                </span>
                <div style={{ overflow: 'hidden' }}>
                  <span style={{ fontWeight: 700, color: 'var(--text0)', fontFamily: 'monospace' }}>{t.symbol}</span>
                  {t.decision_changed && <span title={`critic changed from ${t.original_decision}`} style={{ fontSize: 8, color: '#f59e0b', marginLeft: 4 }}>⟳</span>}
                  {socialAware.isAwareness && (
                    <span title={socialAware.tooltip}
                      style={{ marginLeft: 4, fontSize: 7.5, fontWeight: 700, padding: '1px 5px', borderRadius: 3, background: 'var(--social-awareness-dim)', color: 'var(--social-awareness)', border: '1px solid var(--social-awareness)', whiteSpace: 'nowrap', cursor: 'help' }}>{socialAware.text}</span>
                  )}
                  {scout.isScout && !socialAware.isAwareness && (
                    <span title={scout.tooltip}
                      style={{ marginLeft: 4, fontSize: 7.5, fontWeight: 700, padding: '1px 5px', borderRadius: 3, background: 'var(--social-scout-dim)', color: 'var(--social-scout)', border: '1px solid var(--social-scout)', whiteSpace: 'nowrap', cursor: 'help' }}>{scout.text}</span>
                  )}
                  {squeeze.isSqueeze && (
                    <span title={squeeze.tooltip}
                      style={{ marginLeft: 4, fontSize: 7.5, fontWeight: 700, padding: '1px 5px', borderRadius: 3, background: 'var(--squeeze-dim)', color: 'var(--squeeze)', border: '1px solid var(--squeeze)', whiteSpace: 'nowrap', cursor: 'help' }}>{squeeze.text}</span>
                  )}
                  {runner.isRunner && !squeeze.isSqueeze && !micro.isMicroFloat && !lowPrice.isLowPrice && (
                    <span title={runner.tooltip}
                      style={{ marginLeft: 4, fontSize: 7.5, fontWeight: 700, padding: '1px 5px', borderRadius: 3, background: 'var(--runner-dim)', color: 'var(--runner)', border: '1px solid var(--runner)', whiteSpace: 'nowrap', cursor: 'help' }}>{runner.text}</span>
                  )}
                  {micro.isMicroFloat && !squeeze.isSqueeze && !lowPrice.isLowPrice && (
                    <span title={micro.tooltip}
                      style={{ marginLeft: 4, fontSize: 7.5, fontWeight: 700, padding: '1px 5px', borderRadius: 3, background: 'var(--micro-float-dim)', color: 'var(--micro-float)', border: '1px solid var(--micro-float)', whiteSpace: 'nowrap', cursor: 'help' }}>{micro.text}</span>
                  )}
                  {lowPrice.isLowPrice && !squeeze.isSqueeze && (
                    <span title={lowPrice.tooltip}
                      style={{ marginLeft: 4, fontSize: 7.5, fontWeight: 700, padding: '1px 5px', borderRadius: 3, background: 'var(--low-price-dim)', color: 'var(--low-price)', border: '1px solid var(--low-price)', whiteSpace: 'nowrap', cursor: 'help' }}>{lowPrice.text}</span>
                  )}
                  {/* Co-renders with the manual-lane pill: a squeeze that is also a top
                      gainer must show both, otherwise the gainer fact disappears. */}
                  {topGainer.isTopGainer && (
                    <span title={topGainer.tooltip}
                      style={{ marginLeft: 4, fontSize: 7.5, fontWeight: 700, padding: '1px 5px', borderRadius: 3, background: 'var(--top-gainer-dim)', color: 'var(--top-gainer)', border: `1px solid var(--top-gainer)`, whiteSpace: 'nowrap', cursor: 'help', opacity: t.top_gainer_stale ? 0.7 : 1 }}>{topGainer.text}</span>
                  )}
                  {' '}<ProAnalystPill symbol={t.symbol} map={paMap} compact />
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                  <div style={{ width: 24, height: 4, background: 'var(--bg3)', borderRadius: 2, overflow: 'hidden', flexShrink: 0 }}>
                    <div style={{ width: `${Math.min(score, 50) * 2}%`, height: '100%', background: score >= 40 ? '#22c55e' : score >= 30 ? '#f59e0b' : 'var(--text3)' }} />
                  </div>
                  <span style={{ fontWeight: 600, color: score >= 40 ? '#22c55e' : score >= 30 ? '#f59e0b' : 'var(--text2)' }}>{t.score ?? '—'}</span>
                </div>
                <span style={{ fontWeight: 600, color: t.grade === 'A' ? '#22c55e' : 'var(--text2)' }}>{t.grade || '—'}</span>
                <span style={{ color: (t.rvol ?? 0) >= 5 ? '#22c55e' : 'var(--text2)' }}>{t.rvol ? Number(t.rvol).toFixed(1) + 'x' : '—'}</span>
                <span style={{ color: (t.volume ?? 0) >= 1_000_000 ? '#22c55e' : 'var(--text2)', fontFamily: 'monospace', fontSize: 9 }} title={t.volume ? `${Number(t.volume).toLocaleString()} shares` : undefined}>{fmtVol(t.volume)}</span>
                <span style={{ color: 'var(--text2)' }}>{t.price ? `$${Number(t.price).toFixed(2)}` : '—'}</span>
                <span style={{ color: pctColor(t.change_pct), fontWeight: 600 }}>{pctText(t.change_pct)}</span>
                <span style={{ color: pctColor(t.gap_pct) }}>{pctText(t.gap_pct)}</span>
                <span style={{ color: 'var(--text2)' }}>{t.float_m != null && t.float_m !== '' ? `${t.float_m}M` : '—'}</span>
                <span style={{ fontSize: 9, display: 'flex', flexDirection: 'column', gap: 1, overflow: 'hidden' }}>
                  <span style={{ fontWeight: 600, color: 'var(--text1)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{t.sector || '—'}</span>
                  {t.vs_sector_pct != null && <span style={{ fontSize: 8, color: t.vs_sector_pct >= 0 ? '#4ade80' : '#f87171' }}>vs {t.sector_etf || 'sector'}: {t.vs_sector_pct >= 0 ? '+' : ''}{t.vs_sector_pct}%</span>}
                </span>
                {social ? (
                  <span style={{ fontSize: 9, display: 'flex', flexDirection: 'column', gap: 1 }}>
                    <span style={{ fontWeight: 600, color: socialColor }}>{social}</span>
                    {(t.social_reddit || t.social_stocktwits) ? <span style={{ fontSize: 8, color: 'var(--text3)' }}>R:{t.social_reddit || 0} ST:{t.social_stocktwits || 0}{t.social_bullish_pct != null ? ` (${Math.round(t.social_bullish_pct)}% bull)` : ''}</span> : null}
                  </span>
                ) : <span style={{ fontSize: 9, color: 'var(--text3)' }}>—</span>}
                <span style={{ fontSize: 9, color: t.disqualified ? '#fca5a5' : socialAware.isAwareness ? 'var(--social-awareness)' : t.catalyst_verified === false ? '#f59e0b' : 'var(--text3)', display: 'flex', alignItems: 'center', gap: 4, overflow: 'hidden' }} title={t.catalyst}>
                  {t.disqualified && <span style={{ fontSize: 7, background: '#7f1d1d', color: '#fca5a5', padding: '1px 4px', borderRadius: 2, fontWeight: 700, flexShrink: 0 }}>DQ</span>}
                  {socialAware.isAwareness && !t.disqualified && <span style={{ fontSize: 7, background: 'var(--social-awareness-dim)', color: 'var(--social-awareness)', padding: '1px 4px', borderRadius: 2, fontWeight: 700, flexShrink: 0 }}>ST</span>}
                  {!t.disqualified && !socialAware.isAwareness && t.catalyst_verified === false && <span style={{ fontSize: 7, background: '#78350f', color: '#fcd34d', padding: '1px 4px', borderRadius: 2, fontWeight: 700, flexShrink: 0 }}>?</span>}
                  {!t.disqualified && !socialAware.isAwareness && t.catalyst_verified === true && <span style={{ fontSize: 7, background: '#052e16', color: '#86efac', padding: '1px 4px', borderRadius: 2, fontWeight: 700, flexShrink: 0 }}>V</span>}
                  <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{t.catalyst || (socialAware.isAwareness ? 'StockTwits pre-market mention' : '—')}</span>
                </span>
              </div>
            )})}
            </div>
            </div>

            {/* Pagination — top 30, 10 per page */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 10, flexWrap: 'wrap' }}>
              <span style={{ fontSize: 9, color: 'var(--text3)' }}>
                {pv.total === 0 ? 'No rows' : `Showing ${pv.from}–${pv.to} of ${pv.total}`} (top 30 · sorted by {sortLabels[tradeSort].toLowerCase()}{tradeFilter !== 'ACTIONABLE' ? ` · ${tradeFilter === 'SCOUT' ? 'Social Scouts' : tradeFilter === 'MANUAL' ? 'Manual' : tradeFilter} filter` : ''})
              </span>
              <div style={{ flex: 1 }} />
              <button onClick={() => setScannerPage(p => Math.max(1, Math.min(p, pv.pageCount) - 1))} disabled={pv.page <= 1} style={pgBtn(pv.page <= 1)}>‹ Previous</button>
              {Array.from({ length: pv.pageCount }, (_, i) => i + 1).map(p => (
                <button key={p} onClick={() => setScannerPage(p)} style={{ ...pgBtn(false), ...(p === pv.page ? { background: 'rgba(96,165,250,.18)', color: '#60a5fa', borderColor: '#60a5fa', fontWeight: 700 } : {}) }}>{p}</button>
              ))}
              <button onClick={() => setScannerPage(p => Math.min(pv.pageCount, Math.min(p, pv.pageCount) + 1))} disabled={pv.page >= pv.pageCount} style={pgBtn(pv.page >= pv.pageCount)}>Next ›</button>
            </div>

            {/* Thinkorswim copy list — persists symbols selected across pages/filters */}
            <div style={{ marginTop: 10, padding: '8px 12px', background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 8 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6, flexWrap: 'wrap' }}>
                <span style={{ fontSize: 10, fontWeight: 700, color: 'var(--text1)' }}>Thinkorswim copy list</span>
                <span style={{ fontSize: 9, color: 'var(--text3)' }}>{selectedSyms.length} selected</span>
                <div style={{ flex: 1 }} />
                {(['comma', 'newline', 'space'] as const).map(fmt => (
                  <button key={fmt} onClick={() => setTosFormat(fmt)} style={{ ...pgBtn(false), ...(tosFormat === fmt ? { background: 'rgba(96,165,250,.18)', color: '#60a5fa', borderColor: '#60a5fa' } : {}) }}>{fmt}</button>
                ))}
                <button onClick={() => persistSel(selectSymbols(selectedSyms, pageSymbols))} style={pgBtn(false)}>Select page</button>
                <button onClick={() => persistSel(deselectSymbols(selectedSyms, pageSymbols))} style={pgBtn(false)}>Clear page</button>
                <button onClick={() => persistSel([])} disabled={selectedSyms.length === 0} style={pgBtn(selectedSyms.length === 0)}>Clear all</button>
                <button onClick={() => {
                  const done = () => { setTosCopied(true); setTimeout(() => setTosCopied(false), 1500) }
                  if (navigator.clipboard?.writeText) navigator.clipboard.writeText(tosText).then(done).catch(done)
                  else done()
                }} disabled={selectedSyms.length === 0} style={{ ...pgBtn(selectedSyms.length === 0), background: tosCopied ? 'rgba(34,197,94,.15)' : 'var(--bg1)', color: tosCopied ? '#22c55e' : 'var(--text1)', borderColor: tosCopied ? '#22c55e' : 'var(--border)', fontWeight: 700 }}>
                  {tosCopied ? `✓ Copied ${selectedSyms.length} symbol${selectedSyms.length === 1 ? '' : 's'}` : 'Copy'}
                </button>
              </div>
              {/* selectable textarea fallback — operator can manually copy if clipboard API is blocked */}
              <textarea readOnly value={tosText} aria-label="Selected symbols for Thinkorswim"
                placeholder="Check rows above to build a Thinkorswim symbol list (selection persists across pages)…"
                style={{ width: '100%', minHeight: 38, resize: 'vertical', boxSizing: 'border-box', fontSize: 11, fontFamily: 'monospace', color: 'var(--text0)', background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 6, padding: '6px 8px' }} />
              <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 4 }}>Awareness/selection only — copying symbols never places, validates, or queues a trade. Social Scout, Top Gainer, and Squeeze (MANUAL_REVIEW) symbols can be copied but remain non-auto-tradeable.</div>
            </div>

            <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 8 }}>Source: /api/v2/trade-ai/scanner (orchestrator scan: screener → enrichment → scalp critic → GO/WAIT/MANUAL_REVIEW). Teal AWARE = pre-market StockTwits with Finviz overlay when cached (still awareness-only, not in WAIT copy). Click a row for full scan detail. Default: Actionable. Cyan SQUEEZE · orange RUNNER · purple MICRO · yellow LOW — Entry Desk only.</div>

            {warriorAudit?.ok && (
              <div style={{ marginTop: 12, padding: '10px 12px', background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 8 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8, flexWrap: 'wrap' }}>
                  <span style={{ fontSize: 11, fontWeight: 700, color: 'var(--squeeze)' }}>Ross Alignment Audit</span>
                  <span style={{ fontSize: 9, color: 'var(--text3)' }}>{warriorAudit.since} → {warriorAudit.until}</span>
                  {warriorAudit.generated_at && <span style={{ fontSize: 8, color: 'var(--text3)' }}>updated {String(warriorAudit.generated_at).slice(0, 16).replace('T', ' ')}</span>}
                </div>
                <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', fontSize: 10, marginBottom: 8 }}>
                  <span><strong style={{ color: '#60a5fa' }}>{warriorAudit.symbol_recall_pct ?? '—'}%</strong> <span style={{ color: 'var(--text3)' }}>recall</span></span>
                  <span><strong style={{ color: '#f59e0b' }}>{warriorAudit.go_recall_pct ?? '—'}%</strong> <span style={{ color: 'var(--text3)' }}>GO</span></span>
                  <span><strong style={{ color: 'var(--text1)' }}>{warriorAudit.symbol_days ?? '—'}</strong> <span style={{ color: 'var(--text3)' }}>sym-days</span></span>
                </div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                  {(warriorAudit.top_gaps ?? []).map(([k, v]: [string, number]) => (
                    <span key={k} style={{ fontSize: 8, padding: '2px 6px', borderRadius: 4, background: 'var(--bg1)', border: '1px solid var(--border)', color: 'var(--text2)' }}>{k.replace(/_MANUAL.*/, '')}: <strong>{v}</strong></span>
                  ))}
                </div>
                <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 6 }}>Weekly Mon AM · awareness goal (not auto-GO Ross names) · /api/v2/warrior-audit/latest</div>
              </div>
            )}

            {/* Run History + Sector Distribution */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginTop: 14 }}>
              <div style={{ background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 8, padding: 12 }}>
                <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Run History <span style={{ color: 'var(--text3)', fontWeight: 400 }}>({runHistory.length})</span></div>
                {runHistory.length <= 1 ? <div style={{ color: 'var(--text3)', fontSize: 10 }}>Single run only</div> : (
                  <>
                    <div style={{ display: 'flex', alignItems: 'flex-end', gap: 4, height: 60 }}>
                      {runHistory.slice().reverse().map((r: any, i: number) => (
                        <div key={i} title={`${r.label} · GO ${r.go} · WAIT ${r.wait}`} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'flex-end', height: '100%' }}>
                          <div style={{ width: '100%', height: `${((r.go ?? 0) / runGoMax) * 100}%`, minHeight: (r.go ?? 0) > 0 ? 3 : 0, background: (r.go ?? 0) > 0 ? '#22c55e' : 'var(--border)', borderRadius: '2px 2px 0 0' }} />
                          <span style={{ fontSize: 7, color: 'var(--text3)', marginTop: 2, whiteSpace: 'nowrap' }}>{r.label}</span>
                        </div>
                      ))}
                    </div>
                    <div style={{ display: 'flex', gap: 8, marginTop: 8, flexWrap: 'wrap' }}>
                      {runHistory.map((r: any, i: number) => (
                        <div key={i} style={{ fontSize: 9, color: 'var(--text3)' }}><span style={{ fontWeight: 600, color: 'var(--text2)' }}>{r.label}</span> GO:{r.go} W:{r.wait}</div>
                      ))}
                    </div>
                  </>
                )}
              </div>
              <div style={{ background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 8, padding: 12 }}>
                <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Sector Distribution <span style={{ color: 'var(--text3)', fontWeight: 400 }}>({sectorEntries.length})</span></div>
                {sectorEntries.length === 0 ? <div style={{ color: 'var(--text3)', fontSize: 10 }}>No sector data available</div> : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 4, maxHeight: 200, overflowY: 'auto' }}>
                    {sectorEntries.map(([sec, count]) => (
                      <div key={sec} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <span style={{ width: 110, fontSize: 9, color: 'var(--text2)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{sec}</span>
                        <div style={{ flex: 1, height: 8, background: 'var(--bg3)', borderRadius: 3, overflow: 'hidden' }}>
                          <div style={{ width: `${((count as number) / sectorMax) * 100}%`, height: '100%', background: '#60a5fa', opacity: 0.7, borderRadius: 3 }} />
                        </div>
                        <span style={{ width: 28, fontSize: 9, color: 'var(--text1)', textAlign: 'right', fontWeight: 600 }}>{count}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>
        )
      })()}

      {tab === 'Options' && <OptionsHub onDrill={onDrill} />}

      {tab === 'Open Trades' && (
        <>
          <TimeExitProposals />
          <OpenTradesIntelligence onDrill={onDrill} focusSymbol={deepLink.symbol || undefined} />
          <details style={{ marginTop: 14 }}>
            <summary style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', cursor: 'pointer' }}>Protection Advisory (all proposals)</summary>
            <div style={{ marginTop: 10 }}><ProtectionPanel onDrill={onDrill} /></div>
          </details>
        </>
      )}

      {tab === 'Proposals' && (
        <BrokerProposals
          focusSymbol={deepLink.symbol || undefined}
          focusProposalId={urlProposal ? Number(urlProposal) : undefined}
        />
      )}
      {tab === 'Broker Orders' && <BrokerOrders draftSeed={draftSeed} />}
      {tab === 'Schwab Accounts' && (
        <SchwabAccountsMonitor onEditDraft={(intent: any) => { setDraftSeed(intent); setTab('Broker Orders') }} />
      )}

      {tab === 'Execution' && execQualLoading && (
        <div className={terminalUi ? 'cc-panel' : undefined} style={{ ...(terminalUi ? hubPanel(terminalUi) : { background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 24 }), textAlign: 'center' }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 6 }}>Execution Quality</div>
          <div style={{ fontSize: 11, color: 'var(--text3)' }}>Loading transaction cost analysis from /api/v2/execution-quality…</div>
        </div>
      )}
      {tab === 'Execution' && !execQualLoading && execQualError && (
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 20 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 6 }}>Execution data unavailable</div>
          <div style={{ fontSize: 11, color: 'var(--text2)', marginBottom: 10 }}>{execQualError}</div>
          <Link to="/journal" style={{ fontSize: 11, fontWeight: 700, color: 'var(--text1)' }}>Journal closed trades →</Link>
        </div>
      )}
      {tab === 'Execution' && !execQualLoading && !execQualError && execQual == null && (
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 20 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 6 }}>No execution quality data yet</div>
          <div style={{ fontSize: 11, color: 'var(--text3)', marginBottom: 10, lineHeight: 1.5 }}>TCA fills appear after broker orders execute. Check Journal closed trades or Broker Orders.</div>
          <Link to="/journal" style={{ fontSize: 11, fontWeight: 700, color: 'var(--text1)', marginRight: 14 }}>Journal →</Link>
          <Link to="/trading?tab=Broker+Orders" style={{ fontSize: 11, fontWeight: 700, color: 'var(--text1)' }}>Broker Orders →</Link>
        </div>
      )}
      {tab === 'Execution' && !execQualLoading && !execQualError && execQual != null && (() => {
        // ── Transaction Cost Analysis: aggregate the rich per-fill data into a clear, actionable view ──
        const QC = (q?: string) => { const u = (q || '').toUpperCase(); return u === 'EXCELLENT' ? 'var(--text1)' : u === 'GOOD' ? 'var(--text1)' : u === 'ACCEPTABLE' ? 'var(--text2)' : u === 'POOR' ? 'var(--text0)' : 'var(--text3)' }
        const ex = execList
        const n = ex.length
        const q = { EXCELLENT: 0, GOOD: 0, ACCEPTABLE: 0, POOR: 0, OTHER: 0 } as Record<string, number>
        ex.forEach((e: any) => { const u = (e.fill_quality || '').toUpperCase(); if (q[u] != null) q[u]++; else q.OTHER++ })
        const slips = ex.map((e: any) => e.slippage_pct).filter((v: any) => v != null)
        const avgSlip = slips.length ? slips.reduce((a: number, b: number) => a + Math.abs(b), 0) / slips.length : null
        const totSlipD = ex.reduce((a: number, e: any) => a + (e.slippage_dollars || 0), 0)
        const ttf = ex.map((e: any) => e.time_to_fill_seconds).filter((v: any) => v != null)
        const avgTtf = ttf.length ? ttf.reduce((a: number, b: number) => a + b, 0) / ttf.length : null
        const partials = ex.filter((e: any) => e.partial_fill).length
        const improved = ex.filter((e: any) => (e.price_improvement_pct || 0) > 0).length
        const poor = ex.filter((e: any) => (e.fill_quality || '').toUpperCase() === 'POOR')
          .sort((a: any, b: any) => Math.abs(b.slippage_pct || 0) - Math.abs(a.slippage_pct || 0))
        const ordered = [...ex].sort((a: any, b: any) => {
          const pa = (a.fill_quality || '').toUpperCase() === 'POOR' ? 1 : 0, pb = (b.fill_quality || '').toUpperCase() === 'POOR' ? 1 : 0
          if (pa !== pb) return pb - pa
          return Math.abs(b.slippage_pct || 0) - Math.abs(a.slippage_pct || 0)
        })
        const Tip = ({ t, children }: { t: string; children: any }) => (
          <span title={t} style={{ cursor: 'help', borderBottom: '1px dotted var(--text3)' }}>{children}</span>
        )
        const Metric = ({ label, value, color, tip }: { label: string; value: any; color?: string; tip: string }) => (
          <div title={tip} style={{ background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 8, padding: '8px 10px', cursor: 'help', minWidth: 110, flex: '1 1 110px' }}>
            <div style={{ fontSize: 10, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: 0.4 }}>{label} ⓘ</div>
            <div style={{ fontSize: 17, fontWeight: 700, color: color || 'var(--text0)', marginTop: 2 }}>{value}</div>
          </div>
        )
        return (
        <div className={terminalUi ? 'cc-panel' : undefined} style={terminalUi ? hubPanel(terminalUi) : { background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, alignItems: 'center', marginBottom: 8 }}>
            <div style={{ fontSize: terminalUi ? 11 : 13, fontWeight: 700, color: 'var(--text0)' }}>Execution Quality — Transaction Cost Analysis</div>
            <span style={{ flex: 1 }} />
            <label style={{ fontSize: 10, color: 'var(--text3)', display: 'flex', alignItems: 'center', gap: 6 }}>
              Lookback
              <select
                aria-label="TCA lookback days"
                value={String(execDays)}
                onChange={e => setExecDays(e.target.value === 'all' ? 'all' : Number(e.target.value))}
                style={{ fontSize: 10, padding: '4px 8px', borderRadius: 5, border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text0)' }}
              >
                <option value="7">7d</option>
                <option value="30">30d</option>
                <option value="90">90d</option>
                <option value="180">180d</option>
                <option value="365">1y</option>
                <option value="all">All</option>
              </select>
            </label>
            <button
              type="button"
              data-testid="execution-export-csv"
              disabled={!execList.length}
              title="Download filtered TCA fills as CSV (client-side; no broker write)."
              onClick={() => downloadExecutionQualityCsv(execList)}
              style={{
                fontSize: 10, fontWeight: 800, padding: '4px 10px', borderRadius: 5, cursor: execList.length ? 'pointer' : 'not-allowed',
                opacity: execList.length ? 1 : 0.45, border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text1)',
              }}
            >
              Export CSV ({execList.length})
            </button>
            <Link to="/journal" style={{ fontSize: 10, fontWeight: 800, color: 'var(--text1)' }}>Journal →</Link>
          </div>
          <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 12 }}>
            How well orders filled vs. intended. Window: {execDays === 'all' ? 'all available' : `last ${execDays} days`} · {execRaw.length} raw · {n} shown.
            Clean execution is part of live-readiness — not auto-trade authority.
          </div>

          {n === 0 ? <div style={{ color: 'var(--text3)', fontSize: 11 }}>No execution quality data in this lookback.</div> : (<>
          {/* POOR-fill alert */}
          {poor.length > 0 && (
            <div style={{ background: 'rgba(239,68,68,.1)', border: '1px solid rgba(239,68,68,.4)', borderRadius: 8, padding: '8px 12px', marginBottom: 12 }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: '#ef4444' }}>⚠ {poor.length} POOR fill{poor.length > 1 ? 's' : ''} — investigate</div>
              <div style={{ fontSize: 10, color: 'var(--text2)', marginTop: 4, display: 'flex', flexWrap: 'wrap', gap: 10 }}>
                {poor.slice(0, 6).map((e: any) => (
                  <span key={e.id} onClick={() => onDrill({ title: `${e.symbol} TCA`, subtitle: `POOR · slip ${e.slippage_pct?.toFixed(2)}%`, endpoint: '/api/v2/execution-quality', rows: [e] })} style={{ cursor: 'pointer', textDecoration: 'underline dotted' }}>
                    <b style={{ fontFamily: 'monospace' }}>{e.symbol}</b> {e.slippage_pct != null ? `${e.slippage_pct.toFixed(2)}%` : ''} {e.market_session ? `(${e.market_session})` : ''}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Summary band */}
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 12 }}>
            <Metric label="Fills" value={n} tip="Total recorded fills in this window." />
            <Metric label="Avg Slippage" value={avgSlip != null ? `${avgSlip.toFixed(3)}%` : '—'} color={avgSlip == null ? undefined : avgSlip < 0.1 ? '#22c55e' : avgSlip < 0.3 ? '#f59e0b' : '#ef4444'} tip="Average absolute difference between intended and actual fill price, as % of price. Lower is better; under ~0.1% is excellent." />
            <Metric label="Total Slip $" value={fmt$(totSlipD)} color={totSlipD <= 0 ? '#22c55e' : '#ef4444'} tip="Net dollar cost (or gain) from slippage across all fills. Negative/zero = you paid no cost; positive = slippage ate into returns." />
            <Metric label="Avg Time-to-Fill" value={avgTtf != null ? `${avgTtf.toFixed(1)}s` : '—'} tip="Average seconds from order submit to fill. Faster reduces adverse price drift." />
            <Metric label="Partial Fills" value={`${partials}/${n}`} color={partials === 0 ? '#22c55e' : '#f59e0b'} tip="Orders that filled only partially. Frequent partials suggest thin liquidity or sizing too large." />
            <Metric label="Price Improved" value={`${improved}/${n}`} color={improved > 0 ? '#22c55e' : undefined} tip="Fills that executed BETTER than intended (positive price improvement)." />
          </div>

          {/* Graphical quality distribution bar */}
          <div style={{ marginBottom: 14 }}>
            <div style={{ fontSize: 9, color: 'var(--text3)', marginBottom: 4 }}><Tip t="Distribution of fill-quality grades. Aim for mostly EXCELLENT/GOOD; any POOR is worth a look.">FILL QUALITY DISTRIBUTION ⓘ</Tip></div>
            <div style={{ display: 'flex', height: 22, borderRadius: 5, overflow: 'hidden', border: '1px solid var(--border)' }}>
              {(['EXCELLENT', 'GOOD', 'ACCEPTABLE', 'POOR', 'OTHER'] as const).map(k => q[k] > 0 && (
                <div key={k} title={`${k}: ${q[k]} (${((q[k] / n) * 100).toFixed(0)}%)`} style={{ width: `${(q[k] / n) * 100}%`, background: QC(k), display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 9, fontWeight: 700, color: '#0a0a0a' }}>
                  {(q[k] / n) > 0.08 ? q[k] : ''}
                </div>
              ))}
            </div>
            <div style={{ display: 'flex', gap: 12, marginTop: 4, fontSize: 9, color: 'var(--text2)', flexWrap: 'wrap' }}>
              {(['EXCELLENT', 'GOOD', 'ACCEPTABLE', 'POOR'] as const).map(k => q[k] > 0 && (
                <span key={k}><span style={{ color: QC(k) }}>■</span> {k} {q[k]}</span>
              ))}
            </div>
          </div>

          {/* Fills table — poor first, color-coded */}
          <div style={{ display: 'flex', fontSize: 9, color: 'var(--text3)', padding: '0 6px 4px', textTransform: 'uppercase', letterSpacing: 0.3 }}>
            <span style={{ flex: '0 0 64px' }}>Symbol</span>
            <span style={{ flex: '0 0 90px' }}><Tip t="Fill-quality grade for this order.">Quality</Tip></span>
            <span style={{ flex: '0 0 80px' }}><Tip t="Slippage: intended vs actual fill price as %.">Slip %</Tip></span>
            <span style={{ flex: '0 0 80px' }}><Tip t="Bid-ask spread at submit, as %. Wider spreads make good fills harder.">Spread</Tip></span>
            <span style={{ flex: '0 0 70px' }}><Tip t="Seconds from submit to fill.">Fill (s)</Tip></span>
            <span style={{ flex: '1 1 auto' }}>Session · Strategy</span>
          </div>
          {ordered.slice(0, 30).map((e: any) => {
            const isPoor = (e.fill_quality || '').toUpperCase() === 'POOR'
            return (
            <div key={e.id} onClick={() => onDrill({ title: `${e.symbol} — Transaction Cost Analysis`, subtitle: `${e.fill_quality ?? '—'} · slip ${e.slippage_pct != null ? e.slippage_pct.toFixed(2) + '%' : '—'} · intended ${e.intended_entry ?? '—'} → fill ${e.fill_price ?? '—'}`, endpoint: '/api/v2/execution-quality', rows: [e] })}
              style={{ display: 'flex', alignItems: 'center', padding: '6px 6px', borderBottom: '1px solid var(--border)', cursor: 'pointer', fontSize: 11, background: isPoor ? 'rgba(239,68,68,.06)' : undefined }}>
              <span style={{ flex: '0 0 64px', fontWeight: 600, color: 'var(--text0)', fontFamily: 'monospace' }}>{e.symbol}</span>
              <span style={{ flex: '0 0 90px' }}><span style={{ fontSize: 9, fontWeight: 700, padding: '1px 6px', borderRadius: 4, background: QC(e.fill_quality), color: '#0a0a0a' }}>{e.fill_quality ?? '—'}</span></span>
              <span style={{ flex: '0 0 80px', color: e.slippage_pct == null ? 'var(--text3)' : Math.abs(e.slippage_pct) < 0.1 ? '#22c55e' : Math.abs(e.slippage_pct) < 0.5 ? '#f59e0b' : '#ef4444' }}>{e.slippage_pct != null ? `${e.slippage_pct.toFixed(2)}%` : '—'}</span>
              <span style={{ flex: '0 0 80px', color: 'var(--text2)' }}>{e.spread_pct != null ? `${e.spread_pct.toFixed(2)}%` : '—'}</span>
              <span style={{ flex: '0 0 70px', color: 'var(--text2)' }}>{e.time_to_fill_seconds != null ? `${e.time_to_fill_seconds.toFixed(0)}s` : '—'}</span>
              <span style={{ flex: '1 1 auto', fontSize: 9, color: 'var(--text3)' }}>{e.market_session ?? '—'}{e.strategy_id ? ` · ${e.strategy_id}` : ''}</span>
            </div>
          )})}
          <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 8 }}>Source: /api/v2/execution-quality · click any row for full TCA. Export is client-side only.</div>
          </>)}
        </div>
        )
      })()}

      {tab === 'Broker Recon' && (() => {
        const r = recon?.data ?? recon ?? {}
        const runs = r.runs ?? []
        const items = r.items ?? []
        const latest = runs[0] ?? {}
        const venues = summarizeReconByBroker(runs, items)
        const stClr = (s: string) => /ok|matched|clean/i.test(s || '') ? 'var(--text1)' : /unmatched|mismatch|orphan|issue|break/i.test(s || '') ? 'var(--text0)' : 'var(--text3)'
        return (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,minmax(100px,1fr))', gap: 10 }}>
              {[
                { k: 'Orders seen', v: latest.orders_seen ?? '—', c: 'var(--text0)' },
                { k: 'Trades matched', v: latest.trades_matched ?? '—', c: 'var(--text1)' },
                { k: 'Unmatched broker', v: latest.unmatched_broker_orders ?? 0, c: (latest.unmatched_broker_orders ?? 0) > 0 ? 'var(--text0)' : 'var(--text3)' },
                { k: 'Unmatched local', v: latest.unmatched_local_trades ?? 0, c: (latest.unmatched_local_trades ?? 0) > 0 ? 'var(--text0)' : 'var(--text3)' },
              ].map(s => (
                <div key={s.k} style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 8, padding: '10px 8px', textAlign: 'center' }}>
                  <div style={{ fontSize: 17, fontWeight: 700, color: s.c }}>{s.v}</div>
                  <div style={{ fontSize: 10, color: 'var(--text3)', textTransform: 'uppercase' }}>{s.k}</div>
                </div>
              ))}
            </div>

            <div className={terminalUi ? 'cc-panel' : undefined} style={terminalUi ? hubPanel(terminalUi) : { background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14 }}>
              <div style={{ fontSize: 12, fontWeight: 800, color: 'var(--text0)', marginBottom: 8 }}>Venues · next action</div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {venues.map(v => (
                  <div key={v.broker} style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center', padding: '8px 10px', border: '1px solid var(--border)', borderRadius: 6, background: 'var(--bg2)' }}>
                    <b style={{ fontSize: 11, color: 'var(--text0)', minWidth: 140 }}>{v.broker}</b>
                    <span style={{ fontSize: 10, color: stClr(v.status), fontWeight: 800 }}>{v.status.toUpperCase()}</span>
                    <span style={{ fontSize: 10, color: 'var(--text3)' }}>brokerΔ {v.unmatched_broker} · localΔ {v.unmatched_local}</span>
                    <span style={{ fontSize: 10, color: 'var(--text2)', flex: 1 }}>{v.next_action}</span>
                  </div>
                ))}
              </div>
              <div style={{ marginTop: 10, display: 'flex', flexWrap: 'wrap', gap: 10 }}>
                <Link to="/journal" style={{ fontSize: 10, fontWeight: 800, color: 'var(--text1)' }}>Journal →</Link>
                <Link to="/trading?tab=Broker+Orders" style={{ fontSize: 10, fontWeight: 800, color: 'var(--text1)' }}>Broker Orders →</Link>
                <Link to="/trading?tab=Open+Trades" style={{ fontSize: 10, fontWeight: 800, color: 'var(--text1)' }}>Open Trades →</Link>
              </div>
            </div>

            <div className={terminalUi ? 'cc-panel' : undefined} style={terminalUi ? hubPanel(terminalUi) : { background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14 }}>
              <div style={{ fontSize: terminalUi ? 10 : 12, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Reconciliation items ({items.length})</div>
              {items.length === 0 ? <div style={{ color: 'var(--text1)', fontSize: 11 }}>No unmatched items — broker and local in sync for latest run.</div> :
              items.slice(0, 20).map((it: any, i: number) => (
                <div key={i} onClick={() => onDrill({ title: it.symbol ?? it.broker_order_id, subtitle: it.reconciliation_state, endpoint: '/api/v2/broker-reconciliation', rows: [it] })}
                  style={{ display: 'grid', gridTemplateColumns: '1fr 1.2fr 1fr', gap: 8, padding: '5px 6px', borderBottom: '1px solid var(--border)', cursor: 'pointer', fontSize: 10, alignItems: 'center' }}>
                  <span style={{ fontFamily: 'monospace', fontWeight: 600, color: 'var(--text0)' }}>{it.symbol ?? '—'}</span>
                  <span style={{ color: stClr(it.reconciliation_state), fontSize: 10 }}>{it.reconciliation_state ?? ''}</span>
                  <span style={{ color: 'var(--text3)', fontSize: 10 }}>{it.issue_code ?? it.broker ?? ''}</span>
                </div>
              ))}
              <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 8 }}>Source: /api/v2/broker-reconciliation — multi-venue runs + items. Latest: {latest.broker ?? ''} {latest.run_status ?? ''} {latest.started_at ? new Date(latest.started_at).toLocaleString() : ''}</div>
            </div>
          </div>
        )
      })()}

      {/* ActiveTrader moved to its own top-level section: /v3/active-trader */}
      {tab === 'Scalp' && <ScalpSetupsPanel />}
      {tab === 'Scalp' && scalpData && (() => {
        // ── Live scalp signals: unwrap {timestamp,data:{...}} and present clearly + actionably ──
        const GC = (g?: string) => { const u = (g || '').toUpperCase(); return u === 'A' ? '#22c55e' : u === 'B' ? '#84cc16' : u === 'C' ? '#f59e0b' : u === 'D' || u === 'F' ? '#ef4444' : 'var(--text3)' }
        // Social Scout pill — operator-awareness ONLY. Distinct violet (var(--social-scout)), never
        // green/GO. No execution/validate/buy affordance: it is a watch/surface state, never tradeable.
        const SCOUT_COLOR = 'var(--social-scout)'
        const ScoutPill = ({ d }: { d: any }) => {
          if (d.scout_status !== 'SOCIAL_SCOUT' || !d.operator_pill) return null
          const hints = (d.operator_tooltip_hints || []).join(' · ')
          const tip = `${d.operator_subtitle || 'Not quite there yet'}${hints ? ' — ' + hints : ''}\n`
            + 'Awareness only — not a GO, not validation-fast-path eligible, not a standard momentum_scalp trade.'
          return (
            <span title={tip} style={{ fontSize: 8.5, fontWeight: 700, padding: '1px 6px', borderRadius: 4,
              background: 'var(--social-scout-dim)', color: SCOUT_COLOR, border: `1px solid ${SCOUT_COLOR}`,
              whiteSpace: 'nowrap', cursor: 'help', marginRight: 6 }}>{d.operator_pill}</span>
          )
        }
        const raw: any[] = scalpData.signals ?? []
        const expanded = raw.map((s: any) => ({ ...(s.data || s), _ts: s.timestamp })).filter((d: any) => d.symbol)
        // API can emit the same symbol twice; dedupe by symbol keeping best rank (GO>WAIT>others, grade, score).
        const { unique: sigs, rawCount: rawSignalCount } = dedupeScalpSignalsBySymbol(expanded)
        const n = sigs.length
        const byG: Record<string, number> = {}; sigs.forEach((d: any) => { const g = (d.grade || '?').toUpperCase(); byG[g] = (byG[g] || 0) + 1 })
        const byD = { GO: 0, WAIT: 0, 'NO-GO': 0 } as Record<string, number>
        sigs.forEach((d: any) => { const k = (d.decision || '').toUpperCase().replace('_', '-'); if (byD[k] != null) byD[k]++ })
        const catalyst = sigs.filter((d: any) => d.catalyst_verified).length
        const scouts = sigs.filter((d: any) => d.scout_status === 'SOCIAL_SCOUT').length
        const avgScore = n ? Math.round(sigs.reduce((a: number, d: any) => a + (d.score || 0), 0) / n) : 0
        // "prime" actionable scalp = GO + grade A + catalyst verified (the criteria that actually matter)
        const prime = sigs.filter((d: any) => (d.decision || '').toUpperCase() === 'GO' && (d.grade || '').toUpperCase() === 'A' && d.catalyst_verified)
        const ordered = [...sigs].sort((a: any, b: any) => {
          const da = scalpDecisionRank(a.decision), db = scalpDecisionRank(b.decision)
          if (da !== db) return db - da
          const ga = scalpGradeRank(a.grade), gb = scalpGradeRank(b.grade)
          if (ga !== gb) return gb - ga
          return (Number(b.score) || 0) - (Number(a.score) || 0)
        })
        const Tip = ({ t, children }: { t: string; children: any }) => (
          <span title={t} style={{ cursor: 'help', borderBottom: '1px dotted var(--text3)' }}>{children}</span>
        )
        const Metric = ({ label, value, color, tip }: { label: string; value: any; color?: string; tip: string }) => (
          <div title={tip} style={{ background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 8, padding: '8px 10px', cursor: 'help', minWidth: 100, flex: '1 1 100px' }}>
            <div style={{ fontSize: 9, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: 0.4 }}>{label} ⓘ</div>
            <div style={{ fontSize: 17, fontWeight: 700, color: color || 'var(--text0)', marginTop: 2 }}>{value}</div>
          </div>
        )
        return (
        <div className={terminalUi ? 'cc-panel' : undefined} style={terminalUi ? hubPanel(terminalUi) : { background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
          <div style={{ fontSize: terminalUi ? 11 : 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 4 }}>Scalp Live — Signal Screen</div>
          <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 12 }}>Live scalp candidates, graded. Prime setups = GO · grade A · catalyst-verified (with high RVOL). These are advisory — execution is gated.</div>

          {n === 0 ? <div style={{ color: 'var(--text3)', fontSize: 11 }}>No live scalp signals.</div> : (<>

          {/* Prime-setup alert */}
          <div style={{ background: prime.length ? 'rgba(34,197,94,.1)' : 'var(--bg2)', border: `1px solid ${prime.length ? 'rgba(34,197,94,.4)' : 'var(--border)'}`, borderRadius: 8, padding: '8px 12px', marginBottom: 12 }}>
            {prime.length ? (<>
              <div style={{ fontSize: 12, fontWeight: 700, color: '#22c55e' }}>✦ {prime.length} prime setup{prime.length > 1 ? 's' : ''} — GO · A · catalyst</div>
              <div style={{ fontSize: 10, color: 'var(--text2)', marginTop: 4, display: 'flex', flexWrap: 'wrap', gap: 10 }}>
                {prime.slice(0, 8).map((d: any, i: number) => (
                  <span key={i} onClick={() => onDrill({ title: `${d.symbol} — Scalp Signal`, subtitle: `GO · A · score ${d.score} · RVOL ${d.rvol}`, endpoint: '/api/v2/scalp/live', rows: [d], subjectType: 'scalp', subjectKey: d.symbol })} style={{ cursor: 'pointer', textDecoration: 'underline dotted' }}>
                    <b style={{ fontFamily: 'monospace' }}>{d.symbol}</b> {d.change_percent ? `${d.change_percent}` : ''} {d.rvol ? `RVOL ${d.rvol}` : ''}
                  </span>
                ))}
              </div>
            </>) : <div style={{ fontSize: 11, color: 'var(--text3)' }}>No prime setups right now (need GO + grade A + verified catalyst). Watching {n} candidates.</div>}
          </div>

          {/* Summary band */}
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 12 }}>
            <Metric label="Signals" value={n} tip="Live scalp candidates on the screen." />
            <Metric label="GO" value={byD.GO} color={byD.GO > 0 ? '#22c55e' : undefined} tip="Candidates graded GO — passed the scalp decision gate." />
            <Metric label="Grade A" value={byG['A'] || 0} color={(byG['A'] || 0) > 0 ? '#22c55e' : undefined} tip="Top-grade setups. Grade reflects setup quality (float/RVOL/catalyst/structure)." />
            <Metric label="Catalyst ✓" value={`${catalyst}/${n}`} tip="Signals with a verified catalyst. A real catalyst is required for a prime scalp." />
            <Metric label="Social Scouts" value={scouts} color={scouts > 0 ? 'var(--social-scout)' : undefined} tip="Partial social setups meeting ≥2 of 5 scout pillars — interesting, not there yet. Awareness only: never GO, never validation-eligible, never a standard momentum_scalp." />
            <Metric label="Avg Score" value={avgScore} tip="Mean composite score across candidates (higher = stronger setup)." />
          </div>

          {/* Decision + grade distribution bars */}
          <div style={{ marginBottom: 14, display: 'flex', gap: 18, flexWrap: 'wrap' }}>
            <div style={{ flex: '1 1 240px' }}>
              <div style={{ fontSize: 9, color: 'var(--text3)', marginBottom: 4 }}><Tip t="GO = actionable, WAIT = watch, NO-GO = rejected.">DECISION ⓘ</Tip></div>
              <div style={{ display: 'flex', height: 20, borderRadius: 5, overflow: 'hidden', border: '1px solid var(--border)' }}>
                {(['GO', 'WAIT', 'NO-GO'] as const).map(k => byD[k] > 0 && (
                  <div key={k} title={`${k}: ${byD[k]}`} style={{ width: `${(byD[k] / n) * 100}%`, background: decisionColor(k === 'NO-GO' ? 'NO' : k), display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 9, fontWeight: 700, color: '#0a0a0a' }}>{(byD[k] / n) > 0.08 ? byD[k] : ''}</div>
                ))}
              </div>
            </div>
            <div style={{ flex: '1 1 240px' }}>
              <div style={{ fontSize: 9, color: 'var(--text3)', marginBottom: 4 }}><Tip t="Setup-quality grade distribution. A is best.">GRADE ⓘ</Tip></div>
              <div style={{ display: 'flex', height: 20, borderRadius: 5, overflow: 'hidden', border: '1px solid var(--border)' }}>
                {['A', 'B', 'C', 'D', 'F', '?'].map(k => (byG[k] || 0) > 0 && (
                  <div key={k} title={`${k}: ${byG[k]}`} style={{ width: `${(byG[k] / n) * 100}%`, background: GC(k), display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 9, fontWeight: 700, color: '#0a0a0a' }}>{(byG[k] / n) > 0.08 ? `${k}:${byG[k]}` : ''}</div>
                ))}
              </div>
            </div>
          </div>

          {/* Signals table — GO + best grade first */}
          <div style={{ display: 'flex', fontSize: 9, color: 'var(--text3)', padding: '0 6px 4px', textTransform: 'uppercase', letterSpacing: 0.3 }}>
            <span style={{ flex: '0 0 66px' }}>Symbol</span>
            <span style={{ flex: '0 0 48px' }}>Grade</span>
            <span style={{ flex: '0 0 56px' }}>Decision</span>
            <span style={{ flex: '0 0 50px' }}>Score</span>
            <span style={{ flex: '0 0 60px' }}><Tip t="Relative volume vs average. Scalps want high RVOL (5x+).">RVOL</Tip></span>
            <span style={{ flex: '0 0 60px' }}>Chg %</span>
            <span style={{ flex: '0 0 54px' }}><Tip t="Catalyst verified?">Catalyst</Tip></span>
            <span style={{ flex: '1 1 auto' }}>Source</span>
          </div>
          {ordered.slice(0, 30).map((d: any) => {
            const isGo = (d.decision || '').toUpperCase() === 'GO'
            return (
            <div key={d.symbol} onClick={() => onDrill({ title: `${d.symbol} — Scalp Signal`, subtitle: `${d.decision ?? '—'} · grade ${d.grade ?? '—'} · score ${d.score ?? '—'} · RVOL ${d.rvol ?? '—'}${d.critic_verdict ? ' · ' + d.critic_verdict : ''}`, endpoint: '/api/v2/scalp/live', rows: [d], subjectType: 'scalp', subjectKey: d.symbol })}
              style={{ display: 'flex', alignItems: 'center', padding: '6px 6px', borderBottom: '1px solid var(--border)', cursor: 'pointer', fontSize: 11, background: isGo ? 'rgba(34,197,94,.05)' : undefined }}>
              <span style={{ flex: '0 0 66px', fontWeight: 600, color: 'var(--text0)', fontFamily: 'monospace' }}>{d.symbol}
                {(scalpExtMap[d.symbol] || []).map((e: any, j: number) => <span key={j} title={`${e.lane === 'grok' ? 'Grok' : e.lane === 'chatgpt' ? 'ChatGPT' : e.lane}: ${e.recommendation || ''}\n${e.at ? new Date(e.at).toLocaleString() : ''}`} style={{ marginLeft: 4, fontSize: 8, fontWeight: 700, color: e.lane === 'grok' ? '#1d9bf0' : '#10a37f', cursor: 'help' }}>✦</span>)}</span>
              <span style={{ flex: '0 0 48px' }}><span style={{ fontSize: 9, fontWeight: 700, padding: '1px 6px', borderRadius: 4, background: GC(d.grade), color: '#0a0a0a' }}>{d.grade ?? '—'}</span></span>
              <span style={{ flex: '0 0 56px', fontWeight: 600, color: decisionColor((d.decision || '').toUpperCase().startsWith('NO') ? 'NO' : (d.decision || '').toUpperCase()), fontSize: 10 }}>{d.decision ?? '—'}</span>
              <span style={{ flex: '0 0 50px', color: 'var(--text2)' }}>{d.score ?? '—'}</span>
              <span style={{ flex: '0 0 60px', color: (d.rvol || 0) >= 5 ? '#22c55e' : (d.rvol || 0) >= 2 ? '#f59e0b' : 'var(--text3)' }}>{d.rvol != null ? `${d.rvol}x` : '—'}</span>
              <span style={{ flex: '0 0 60px', color: 'var(--text2)' }}>{d.change_percent || '—'}</span>
              <span style={{ flex: '0 0 54px', textAlign: 'center' }}>{d.catalyst_verified ? <span style={{ color: '#22c55e' }}>✓</span> : <span style={{ color: 'var(--text3)' }}>—</span>}</span>
              <span style={{ flex: '1 1 auto', fontSize: 9, color: 'var(--text3)', display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 4 }}><ScoutPill d={d} />{d.source ?? '—'}</span>
            </div>
          )})}
          <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 8 }} data-testid="scalp-dedupe-footer">
            Deduped {rawSignalCount} → {n} unique symbols.
            {' · '}Source: /api/v2/scalp/live · click any row for the full signal. Hover ⓘ for definitions. Advisory only — scalp execution is gated.
          </div>
          </>)}
        </div>
        )
      })()}
      {tab === 'Entry Desk' && <ManualTosDesk focusSymbol={deepLink.symbol || undefined} />}
      {tab === 'ATM Controls' && <ATMControlPanel />}
    </div>
  )
}
