import { useEffect, useRef, useState, type CSSProperties } from 'react'
// Trade AI = Opportunities page (Gate 3 Main.dc.html, 2026-10-22); Shared Momentum is its collapsed drawer.
import TradeAiOpportunities from '../components/tradeai/TradeAiOpportunities'
import { Navigate, useLocation, useSearchParams } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import {
  canonicalTradingSearch,
  legacyTradingRedirect,
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
  pageSlice, toggleSelectedSymbol, selectSymbols, deselectSymbols, dedupeSymbols,
  formatThinkorswimSymbols, selectionStorageKey, getSocialScoutPill, getTopGainerPill,
  getSqueezePill, getRunnerPill, getMicroFloatPill, getLowPricePill,
  getSocialAwarenessPill, isSocialAwarenessRow,
  isSqueezeRow, isRunnerRow, isMicroFloatRow, isManualReviewRow,
  sortTickerList, type ScannerSortMode, type TosFormat,
} from '../lib/scannerSelection'
import SchwabAccountsMonitor from '../components/SchwabAccountsMonitor'
import ActiveTraderFiresStrip from '../components/tradeai/ActiveTraderFiresStrip'
import { fmtVol } from '../lib/format'
import type { DrillContext } from '../components/DetailDrawer'
// ProposalsRich archived (_archive/20260702) — Proposals tab uses <BrokerProposals/> only.
import BrokerOrders from '../components/BrokerOrders'
// Open Trades = the protect-first desk (Gate 3, 2026-10-22). It renders PositionDecisionCardV4 unchanged for
// the Stage 2c protective-stop ARM + per-order 2FA flow. The dead time-exit widget is no longer shown.
import OpenTradesDesk from '../components/OpenTradesDesk'
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

/** Scanner KPI tiles that filter the table below; null = informational only. */
type TileFilter = 'GO' | 'WAIT' | null

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




/**
 * Retired tabs (Scalp → Active Trader, ATM Controls → System → Broker Access, Execution → Journal)
 * redirect before the hub mounts, so an old Telegram or bookmark link never starts the hub polls.
 */
export default function TradingHub(props: Props) {
  const [searchParams] = useSearchParams()
  const { hash } = useLocation()
  const redirect = legacyTradingRedirect(searchParams)
  if (redirect) return <Navigate to={redirect} replace />
  // Retired in-hub names (Entry Desk, Broker Recon, Schwab Accounts, Broker Proposals …) are rewritten
  // to the canonical URL with a history replace before the desk mounts (P3 2026-10-23).
  const canonical = canonicalTradingSearch(searchParams)
  if (canonical) return <Navigate to={{ search: `?${canonical.toString()}`, hash }} replace />
  return <TradingHubDesk {...props} />
}

function TradingHubDesk({ onDrill }: Props) {
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
  const [tradeFilter, setTradeFilter] = useState<'ACTIONABLE' | 'GO' | 'WAIT' | 'MANUAL' | 'SCOUT' | 'AWARENESS'>('ACTIONABLE')
  const scannerFilterRef = useRef<HTMLDivElement | null>(null)
  const applyTileFilter = (f: 'GO' | 'WAIT') => {
    setTradeFilter(f)
    setScannerPage(1)
    scannerFilterRef.current?.scrollIntoView?.({ behavior: 'smooth', block: 'start' })
  }
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
  // Broker desk tab: skip heavy hub polls so single-threaded API can serve broker-proposals first.
  const brokerDesk = tab === 'Proposals' || tab === 'Broker Orders'
  // Broker Orders desk (approval links only) — hub chrome is Schwab-specific (not paper vs Path B counts).
  const pureSchwabTabs = tab === 'Broker Orders'
  // Proposals: Path B queue (default) or Path A Entry Desk (merged 2026-10-22). Broker Orders: the
  // Schwab account monitor section (was the Schwab Accounts tab).
  const section = deepLink.section
  const setSection = (next: string | null) => {
    const sp = new URLSearchParams(searchParams)
    if (next) sp.set('section', next)
    else sp.delete('section')
    setSearchParams(sp, { replace: true })
  }
  // Slim scanner projection (~10% of the full /trade-ai payload) — full universe rows are
  // trimmed server-side; the multi-MB full endpoint 500-looped under load (2026-07-17).
  const { data: tradeAi, error: tradeAiError, loading: tradeAiLoading } = useApi<any>('/api/v2/trade-ai/scanner', 60_000, { enabled: tab === 'Trade AI' })
  const { data: warriorAudit } = useApi<any>('/api/v2/warrior-audit/latest', 300_000, { enabled: tab === 'Trade AI' })
  const paMap = useProAnalystMap()
  // Do not stampede the single-process API while the default Trade AI tab
  // is still painting the scanner (941-row payload + 8 sibling polls = empty desk).
  const scannerSettled = tab !== 'Trade AI' || !!tradeAi || !!tradeAiError
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
  // Recon for hub triage (unmatched breaks); the reconciliation detail is a drawer on Open Trades.
  const { data: recon } = useApi<any>('/api/v2/broker-reconciliation', 120_000, {
    enabled: !pureSchwabTabs && scannerSettled,
  })
  // Pilot standing approvals for 2FA triage chip
  const { data: pilotStatus } = useApi<any>('/api/v2/broker-orders/pilot/status', 60_000, {
    enabled: (!pureSchwabTabs || tab === 'Broker Orders') && scannerSettled,
  })


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
  // Open count from the position intelligence (holdings + paper, write-offs excluded) — not paper_trades.
  const openCount: number | null = openIntel?.summary
    ? Number(openIntel.summary.active_positions ?? openIntel.summary.total_positions ?? 0)
    : null

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
            Proposals (Path B queue + Path A Entry Desk) · per-order 2FA · AUTO LIVE BLOCKED unless 2FA path · Stop Management on Portfolio
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
              {t === 'Proposals' && brokerQueueCount != null && brokerQueueCount > 0 && (
                <span data-testid="proposals-tab-count" title="Path B broker queue (active entries)" style={{ marginLeft: 6, fontFamily: 'monospace', color: 'var(--warning-color)' }}>{brokerQueueCount}</span>
              )}
            </button>
          ))}
          {tab === 'Broker Orders' && (
            <span role="tab" aria-selected="true" data-testid="trading-desk-broker-orders" style={hubTab(true, terminalUi)} title="Broker Orders opens from its Telegram approval links (/v3/go/order/…); it is not a tab.">
              Broker Orders
            </span>
          )}
        </div>
      </div>
      <div style={{ fontSize: 11, color: 'var(--text3)', margin: '-4px 0 10px' }} data-testid="trading-moved-note">
        Broker Orders opens from its approval links · ATM controls moved to{' '}
        <Link to="/system/broker-access#automation-controls" style={{ color: 'var(--text2)' }}>System → Broker Access</Link>
        {' '}· Scalp list moved to <Link to="/active-trader?tab=Scalp" style={{ color: 'var(--text2)' }}>Active Trader → Scalp</Link>
      </div>

      <TradingDeskHealth
        openCount={openCount}
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
        <div role="tablist" aria-label="Proposals sections" data-testid="proposals-sections" style={{ display: 'flex', gap: 6, marginBottom: 10, flexWrap: 'wrap' }}>
          <button type="button" role="tab" aria-selected={section !== 'path-a'} data-testid="proposals-section-path-b" onClick={() => setSection(null)} style={hubTab(section !== 'path-a', terminalUi)}>Path B queue</button>
          <button type="button" role="tab" aria-selected={section === 'path-a'} data-testid="proposals-section-path-a" onClick={() => setSection('path-a')} style={hubTab(section === 'path-a', terminalUi)}>Path A · Entry Desk</button>
        </div>
      )}
      {tab === 'Proposals' && section !== 'path-a' && (
        <div className={terminalUi ? 'cc-panel' : undefined} style={{ marginBottom: 14, ...(terminalUi ? hubPanel(terminalUi) : { padding: '8px 14px', background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 8 }), fontSize: terminalUi ? 9 : 10, color: 'var(--text2)', lineHeight: 1.45 }}>
          Path B operator route — P0 validation caps are advisory. <span style={{ color: 'var(--text0)', fontWeight: 700 }}>Auto route (2FA)</span> opens trade review (edit size/risk) before Schwab approval.
        </div>
      )}
      {tab === 'Proposals' && section === 'path-a' && (
        <div className={terminalUi ? 'cc-panel' : undefined} style={{ marginBottom: 14, ...(terminalUi ? hubPanel(terminalUi) : { padding: '8px 14px', background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 8 }), fontSize: terminalUi ? 9 : 10, color: 'var(--text2)', lineHeight: 1.45 }}>
          Path A — manual Thinkorswim. Rating, R:R, and exit ladder are <b>deterministic</b> on this tab; watchlist agent maturity shows when DB has it. <b>Stage 2b + Auto route (2FA)</b> are on{' '}
          <button type="button" onClick={() => setSection(null)} style={{ background: 'none', border: 'none', padding: 0, color: '#60a5fa', fontWeight: 700, cursor: 'pointer', fontSize: 10 }}>Path B queue</button>.
        </div>
      )}

      {/* The previous scanner view stays reachable as the page's "Scanner tools" drawer (run health,
          run history, sector mix, Thinkorswim copy, Warrior audit). */}
      {tab === 'Trade AI' && <TradeAiOpportunities tradeAi={tradeAi} error={tradeAiError} loading={tradeAiLoading} classic={tradeAi ? (() => {
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
          return {
            type,
            label: type === 'ALL' ? 'Universe' : type === 'WAIT' ? 'WAIT (screener)' : type,
            syms,
            text: syms.join(','),
            color: type === 'GO' ? '#22c55e' : type === 'WAIT' ? '#f59e0b' : 'var(--text2)',
          }
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
        const universeScope = 'UNIVERSE scope — latest scan per symbol, today + yesterday, all runs (wider than header SETUPS · LATEST RUN)'
        const setupRunUi = renderSetupCounts(tradeAi?.setup_run_summary, {})
        const latestRunScope = `LATEST RUN only — same contract as header SETUPS${setupRunUi.runId ? ` · ${setupRunUi.runId}` : ''}`
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
        const integrity = tradeAi?.setup_run_summary?.count_integrity
        const integrityReason = tradeAi?.setup_run_summary?.count_integrity_reason
        const underfillNote = setupRunUi.healthDegraded
          ? ` · ${setupRunUi.runHealthStatus || 'UNDERFILLED'}${scannedN != null ? ` ${scannedN}/${healthFloorLabel}` : ''}`
          : ''
        const integrityNote = integrity && integrity !== 'RECONCILED'
          ? ` · integrity ${integrity}${integrityReason ? `: ${integrityReason}` : ''}`
          : ''
        const kpis = [
          { label: 'UNIVERSE GO', value: goN, color: '#22c55e', title: universeScope, filter: 'GO' as TileFilter },
          { label: 'UNIVERSE WAIT', value: waitN, color: '#f59e0b', title: `${universeScope} · includes social-awareness WAIT (higher than WAIT screener copy)`, filter: 'WAIT' as TileFilter },
          { label: 'UNIVERSE NO-GO', value: noGoN, color: '#ef4444', title: universeScope, filter: null as TileFilter },
          { label: 'Universe', value: universeN, color: 'var(--text0)', title: universeScope, filter: null as TileFilter },
          { label: 'VIX', value: tradeAi?.vix != null ? Number(tradeAi.vix).toFixed(1) : '—', color: '#60a5fa', title: undefined as string | undefined, filter: null as TileFilter },
          { label: 'Regime', value: tradeAi?.market_regime ?? '—', color: '#a855f7', title: undefined as string | undefined, filter: null as TileFilter },
        ]
        const latestRunKpis = [
          { label: 'LATEST RUN GO', value: tradeAi?.setup_run_summary?.go_count ?? '—', color: BB.green, title: `${latestRunScope}${underfillNote}${integrityNote}`, filter: 'GO' as TileFilter },
          { label: 'LATEST RUN WAIT', value: tradeAi?.setup_run_summary?.wait_count ?? '—', color: BB.amber, title: `${latestRunScope}${underfillNote}${integrityNote}`, filter: 'WAIT' as TileFilter },
          { label: 'LATEST RUN NOGO', value: tradeAi?.setup_run_summary?.nogo_count ?? '—', color: BB.red, title: `${latestRunScope}${underfillNote}${integrityNote}`, filter: null as TileFilter },
          {
            label: 'LATEST RUN SCANNED',
            value: tradeAi?.setup_run_summary?.scanned_count ?? scannedN ?? '—',
            color: 'var(--text0)',
            title: `${latestRunScope}${underfillNote}${integrityNote}`,
            filter: null as TileFilter,
          },
        ]
        // GO / WAIT tiles filter the table below (operator 2026-10-22: "I can't click on go or wait"). The table
        // rows are the universe scope (today + yesterday), so a LATEST RUN tile can show more rows than its count.
        const tileFilterProps = (k: { label: string; filter: TileFilter; title?: string }) => k.filter ? {
          role: 'button' as const,
          tabIndex: 0,
          'data-testid': `scanner-tile-filter-${k.filter.toLowerCase()}`,
          'aria-pressed': tradeFilter === k.filter,
          onClick: () => applyTileFilter(k.filter as 'GO' | 'WAIT'),
          onKeyDown: (e: any) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); applyTileFilter(k.filter as 'GO' | 'WAIT') } },
          title: `${k.title ? `${k.title} · ` : ''}click to show ${k.filter} rows in the table`,
        } : { title: k.title }
        return (
          <div className={terminalUi ? 'cc-panel' : undefined} style={terminalUi ? hubPanel(terminalUi) : { background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
            <ActiveTraderFiresStrip tradeAiTickers={tickers} />
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 4 }}>
              <div style={{ fontSize: terminalUi ? 11 : 13, fontWeight: 700, color: 'var(--text0)' }}>Market Opportunities Scanner</div>
              <div style={{ fontSize: 10, color: 'var(--text3)' }}>
                {tradeAi?.latest_run_label || tradeAi?.run_label || 'no run'}
                {tradeAi?.latest_run_timestamp && ` · ${new Date(tradeAi.latest_run_timestamp).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}`}
                {scannedN != null && ` · ${scannedN} scanned this run`}
                {tradeAi?.run_health_status && (
                  <span
                    style={{ marginLeft: 6, color: runHealthChipColor(healthTier), fontWeight: 800 }}
                    data-testid="trade-ai-run-health-chip-classic"
                    data-run-id={tradeAi?.run_id ?? ''}
                    data-run-scanned={scannedN != null ? String(scannedN) : ''}
                    data-run-floor={healthFloor && isFinite(healthFloor) ? String(healthFloor) : ''}
                    data-run-health={healthTier}
                    data-run-integrity={tradeAi?.setup_run_summary?.count_integrity ?? ''}
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
                  {' '}Header SETUPS / RUN chips below answer the latest-run question ({setupRunUi.counts}); UNIVERSE chips answer today+yesterday.
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
            {(healthTier === 'underfilled' || healthTier === 'failed') && (
              <div
                data-testid="trade-ai-latest-run-kpis"
                style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: terminalUi ? 4 : 8, margin: '10px 0 4px' }}
              >
                {latestRunKpis.map(k => (
                  <div key={k.label} {...tileFilterProps(k)} style={{ ...(terminalUi ? hubKpiChip(k.filter != null && tradeFilter === k.filter, true) : { background: 'var(--bg2)', borderRadius: 8, padding: '8px 6px' }), textAlign: 'center', cursor: k.filter ? 'pointer' : 'help', border: `1px solid ${k.filter && tradeFilter === k.filter ? k.color : BB.amber}` }}>
                    <div style={{ fontSize: TYPE.md, fontWeight: 700, color: k.color }}>{k.value}</div>
                    <div style={{ fontSize: TYPE.xs, color: 'var(--text3)', textTransform: 'uppercase' }}>{k.label}</div>
                  </div>
                ))}
              </div>
            )}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6,1fr)', gap: terminalUi ? 4 : 8, margin: '10px 0 6px' }}>
              {kpis.map(k => (
                <div key={k.label} {...tileFilterProps(k)} style={{ ...(terminalUi ? hubKpiChip(k.filter != null && tradeFilter === k.filter, true) : { background: 'var(--bg2)', borderRadius: 8, padding: '8px 6px' }), textAlign: 'center', cursor: k.filter ? 'pointer' : k.title ? 'help' : 'default', ...(k.filter && tradeFilter === k.filter ? { outline: `1px solid ${k.color}` } : {}) }}>
                  <div style={{ fontSize: terminalUi ? 14 : 17, fontWeight: 700, color: k.color }}>{k.value}</div>
                  <div style={{ fontSize: terminalUi ? 7 : 8, color: 'var(--text3)', textTransform: 'uppercase' }}>{k.label}</div>
                </div>
              ))}
            </div>
            <div style={{ fontSize: 10, color: 'var(--text3)', margin: '0 0 12px' }}>
              Scope: <b>UNIVERSE</b> chips = latest scan per symbol · today + yesterday · all runs.
              Header <b>SETUPS · LATEST RUN</b> = {(() => {
                if (!setupRunUi.population) return setupRunUi.counts
                const integrity = setupRunUi.degraded ? ` · ${setupRunUi.integrity}` : ''
                return `${setupRunUi.counts} · ${setupRunUi.population}${integrity} · run ${setupRunUi.runId ?? tradeAi?.run_id ?? ''}`
              })()}.
              WAIT copy list is screener WAIT only (excludes awareness) — may be lower than UNIVERSE WAIT.
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
            <div ref={scannerFilterRef} style={{ display: 'flex', gap: 4, marginBottom: 8, flexWrap: 'wrap', alignItems: 'center' }}>
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
                        <div key={i} data-run-id={r.run_id ?? ''} title={`${r.run_id ?? 'run unknown'} · ${renderSetupCounts(r.setup_run_summary, {}).counts} · ${r.count_integrity}`} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'flex-end', height: '100%' }}>
                          <div style={{ width: '100%', height: `${((r.go ?? 0) / runGoMax) * 100}%`, minHeight: (r.go ?? 0) > 0 ? 3 : 0, background: (r.go ?? 0) > 0 ? '#22c55e' : 'var(--border)', borderRadius: '2px 2px 0 0' }} />
                          <span style={{ fontSize: 7, color: 'var(--text3)', marginTop: 2, whiteSpace: 'nowrap' }}>{r.label}</span>
                        </div>
                      ))}
                    </div>
                    <div style={{ display: 'flex', gap: 8, marginTop: 8, flexWrap: 'wrap' }}>
                      {runHistory.map((r: any, i: number) => (
                        <div key={i} data-run-id={r.run_id ?? ''} style={{ fontSize: 9, color: 'var(--text3)' }}><span style={{ fontWeight: 600, color: 'var(--text2)' }}>{r.run_id ?? r.label}</span> {renderSetupCounts(r.setup_run_summary, {}).counts} · {r.count_integrity}</div>
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
      })() : null} />}

      {tab === 'Options' && <OptionsHub onDrill={onDrill} />}

      {tab === 'Open Trades' && (
        <OpenTradesDesk onDrill={onDrill} focusSymbol={deepLink.symbol || undefined} initialDrawer={deepLink.drawer} />
      )}

      {tab === 'Proposals' && section !== 'path-a' && (
        <BrokerProposals
          focusSymbol={deepLink.symbol || undefined}
          focusProposalId={urlProposal ? Number(urlProposal) : undefined}
        />
      )}
      {tab === 'Proposals' && section === 'path-a' && <ManualTosDesk focusSymbol={deepLink.symbol || undefined} />}
      {tab === 'Broker Orders' && (
        <div className={terminalUi ? 'cc-panel' : undefined} data-testid="broker-orders-desk-note" style={{ marginBottom: 10, ...(terminalUi ? hubPanel(terminalUi) : { padding: '8px 14px', background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 8 }), fontSize: 11, color: 'var(--text2)', display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
          <span>Broker Orders desk — opened from an approval link. Every live order still needs its per-order 2FA.</span>
          <button type="button" onClick={() => setSection(section === 'schwab-accounts' ? null : 'schwab-accounts')} style={hubTab(section === 'schwab-accounts', terminalUi)}>
            {section === 'schwab-accounts' ? 'Hide Schwab account monitor' : 'Schwab account monitor'}
          </button>
        </div>
      )}
      {tab === 'Broker Orders' && section === 'schwab-accounts' && (
        <SchwabAccountsMonitor onEditDraft={(intent: any) => { setDraftSeed(intent); setSection(null) }} />
      )}
      {tab === 'Broker Orders' && <BrokerOrders draftSeed={draftSeed} />}

    </div>
  )
}
