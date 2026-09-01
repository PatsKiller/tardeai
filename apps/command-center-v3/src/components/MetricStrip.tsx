import { useApi } from '../hooks/useApi'
import { useNavigate } from 'react-router-dom'
import { fmt$ } from '../lib/format'
import { pricingStampLine } from '../lib/pricingStamp'
import { runLabel } from '../lib/homeLabels'
import { overviewSurfaceFreshness, tradeAiSurfaceFreshness } from '../lib/surfaceFreshness'
import { BB, T, TYPE } from '../lib/watchTokens'
import type { DrillContext } from './DetailDrawer'


interface Props {
  onDrill: (ctx: DrillContext) => void
}

export default function MetricStrip({ onDrill }: Props) {
  const navigate = useNavigate()

  const { data: overview } = useApi<any>('/api/v2/overview', 120_000)
  const { data: readiness } = useApi<any>('/api/v2/paper-trade-readiness', 120_000)
  const { data: regime } = useApi<any>('/api/v2/risk-regime/latest', 120_000)
  const { data: tradeAi } = useApi<any>('/api/v2/trade-ai/summary', 120_000)
  const { data: gate } = useApi<any>('/api/v2/live-trading-gate', 120_000)
  const { data: health } = useApi<any>('/api/v2/health', 120_000)
  const healthWarn = (health?.findings ?? []).filter((f: any) => f.severity === 'critical' || f.severity === 'warning').length

  const portfolioVal = overview?.portfolio_value
  const winRate = overview?.journal?.win_rate ?? readiness?.win_rate
  const winTrades = overview?.journal?.trade_count
  const regimeLabel = regime?.regime_label ?? '—'
  const regimeConf = regime?.confidence
  const goCount = tradeAi?.go_count ?? 0
  const waitCount = tradeAi?.wait_count ?? 0
  const avoidCount = tradeAi?.avoid_count ?? 0
  // Prefer API stale + cached_at over session-normalized run_date (heal can label "today"
  // while the cache stays empty for days — census/bisect 2026-08-28).
  const setupsFresh = tradeAiSurfaceFreshness(tradeAi)
  const overviewFresh = overviewSurfaceFreshness(overview)
  const scanStale = setupsFresh.stale
  const setupsRun = runLabel(tradeAi?.run_label ?? tradeAi?.latest_run_label, tradeAi?.run_date)
  const setupsAsOfMark = setupsFresh.asOf
    ? ` · as_of ${String(setupsFresh.asOf).slice(0, 19).replace('T', ' ')}`
    : ''
  // GAP 2. This said "as_of" while the value is the DATA clock, so the chip
  // named the one field it is specifically not reporting. It also went blank
  // when the money had no date -- and after the UNDATED fix that silence would
  // be the whole rendering. Silence must never be indistinguishable from a
  // healthy block (AGENTS.md 9.1), so UNDATED is stated.
  const overviewAcct = overviewFresh.dataAsOfAccount
  const overviewAcctMark = overviewAcct ? ` (${overviewAcct})` : ''
  const overviewAsOfMark = overviewFresh.dataAsOf
    ? ` · data_as_of ${String(overviewFresh.dataAsOf).slice(0, 19).replace('T', ' ')}${overviewAcctMark}`
    : ` · data_as_of UNDATED${overviewAcctMark}`
  const operatorLive = !!gate?.operator_live_via_2fa_allowed
  const autoLive = gate?.status === 'AUTHORIZED'
  const liveBadge = operatorLive ? '2FA LIVE' : autoLive ? 'AUTO LIVE' : 'AUTO BLOCKED'
  const liveBadgeBlocked = !operatorLive && !autoLive
  const todayChange = overview?.today_change
  const todayPct = overview?.today_pct
  const journalPnl = overview?.journal?.total_pnl
  const realizedPnl = overview?.journal?.realized_pnl
  const realizedCount = overview?.journal?.realized_count
  const longTermTrimPnl = overview?.journal?.long_term_trim_pnl
  const journalLastClose = overview?.journal?.last_close_date
  const journalLastIngested = overview?.journal?.last_ingested_at
  const journalIngestedHours = (() => {
    if (!journalLastIngested) return null
    const ms = Date.now() - new Date(String(journalLastIngested)).getTime()
    return isFinite(ms) && ms > 0 ? ms / 3_600_000 : null
  })()
  // STALE now means "journal pipeline hasn't rebuilt recently" (72h spans weekends), not
  // "haven't closed a trade recently" — a quiet market is not stale data.
  const journalStale = journalIngestedHours != null && journalIngestedHours > 72
  const journalAgeMark = journalStale ? ` · not refreshed ${Math.round(journalIngestedHours)}h` : ''
  const journalRefreshedMark = journalLastIngested ? ` · journal rebuilt ${new Date(String(journalLastIngested)).toLocaleString(undefined, { month: 'numeric', day: 'numeric', hour: 'numeric', minute: '2-digit' })}` : ''
  const vix = tradeAi?.vix
  const approvals = overview?.pending_approvals ?? overview?.approvals_count
  const priceStamp = pricingStampLine(overview?.pricing ?? { last_repriced: overview?.last_repriced, reprice_source: overview?.reprice_source })

  const setupsValue = (() => {
    if (scanStale) {
      // Visible STALE on the value itself — not only a tooltip (Wave 3 census finding).
      return setupsFresh.surfaceLabel || `STALE · ${setupsRun}`
    }
    if (tradeAi?.latest_run_label || tradeAi?.run_label) {
      return `${goCount} GO · ${waitCount} WAIT · ${avoidCount} NOGO`
    }
    return '— before first run'
  })()

  const tiles = [
    {
      label: 'PORTFOLIO', value: portfolioVal != null ? fmt$(portfolioVal, 0) : '—',
      stale: overviewFresh.stale ? (overviewFresh.surfaceLabel?.replace(/^STALE · /, ' · ') || overviewAsOfMark) : null,
      asOf: overviewFresh.asOf,
      asOfLabel: 'data_as_of',
      asOfNote: overviewAcct,
      undated: !overviewFresh.dataAsOf,
      color: overviewFresh.stale ? BB.amber : 'var(--text0)',
      tip: `Total portfolio equity across all linked broker accounts (Schwab, Fidelity, Alpaca, Moomoo). Refreshes every 2 min via /api/v2/overview.${overviewAsOfMark}${overviewFresh.stale ? ` · ${overviewFresh.reason}` : ''}`,
      drill: { title: 'Portfolio', subtitle: overviewFresh.stale ? `STALE${overviewAsOfMark}` : 'From /api/v2/overview', endpoint: '/api/v2/overview',
        rows: overview ? [{ portfolio_value: overview.portfolio_value, total_cash: overview.total_cash, position_count: overview.position_count, today_change: overview.today_change, today_pct: overview.today_pct, as_of: overview.as_of, surface_stale: overviewFresh.stale, surface_reason: overviewFresh.reason }] : [] },
    },
    {
      label: 'TODAY', value: todayChange != null ? `${todayChange >= 0 ? '+' : ''}${fmt$(todayChange, 0)}${todayPct != null ? ` ${todayPct >= 0 ? '+' : ''}${todayPct}%` : ''}` : '—',
      stale: overviewFresh.stale ? (overviewFresh.surfaceLabel?.replace(/^STALE · /, ' · ') || overviewAsOfMark) : null,
      asOf: overviewFresh.asOf,
      asOfLabel: 'data_as_of',
      asOfNote: overviewAcct,
      undated: !overviewFresh.dataAsOf,
      color: overviewFresh.stale ? BB.amber : todayChange == null ? 'var(--text3)' : todayChange >= 0 ? BB.green : BB.red,
      drill: { title: "Today's Move", subtitle: overviewFresh.stale ? `STALE${overviewAsOfMark}` : 'By account · from /api/v2/overview', endpoint: '/api/v2/overview',
        rows: overview ? [
          { today_change: overview.today_change, today_pct: overview.today_pct, portfolio_value: overview.portfolio_value, as_of: overview.as_of, surface_stale: overviewFresh.stale },
          ...Object.entries(overview.today_by_account ?? {})
            .sort((a: any, b: any) => Math.abs(b[1].change) - Math.abs(a[1].change))
            .map(([acct, d]: any) => ({
              account: acct, today_change: d.change,
              today_pct: d.pct != null ? `${d.pct >= 0 ? '+' : ''}${d.pct}%` : null,
              account_value: d.value, top_movers: d.top_movers || null,
            })),
        ] : [] },
      tip: `Today's net change ($ and %) across all linked accounts. Click to see per-account breakdown. Refreshes every 2 min.${overviewAsOfMark}`,
    },
    {
      label: 'TRADING', value: winRate != null ? `${winRate}%${winTrades ? ` · ${winTrades}` : ''}${journalPnl != null ? ` · ${fmt$(journalPnl, 0)}` : ''}` : '—',
      stale: journalStale ? journalAgeMark : null,
      color: winRate != null && winRate >= 50 ? BB.green : winRate != null ? BB.amber : 'var(--text3)',
      tip: `Active trading only (day + swing), broker round-trips${journalLastClose ? ` · last close ${journalLastClose}` : ''}${journalRefreshedMark}. Excludes long-term trims of old holds — those are in REALIZED. Win rate excludes $0 scratches.`,
      drill: { title: 'Trading (active)', subtitle: `Day + swing round-trips, excludes long-term position trims${journalLastClose ? ` · through ${journalLastClose}` : ''} · REALIZED tile shows all closed incl. trims`, endpoint: '/api/v2/overview',
        rows: [{ trading_win_rate: overview?.journal?.win_rate, trading_trades: overview?.journal?.trade_count, trading_pnl: overview?.journal?.total_pnl, realized_win_rate: overview?.journal?.realized_win_rate, realized_trades: realizedCount, realized_pnl: realizedPnl, long_term_trim_pnl: longTermTrimPnl, basis: overview?.journal?.basis, last_close_date: overview?.journal?.last_close_date, last_ingested_at: overview?.journal?.last_ingested_at, ledger_last_trade_time: overview?.journal?.ledger_last_trade_time, paper_readiness_win_rate: readiness?.win_rate, paper_usable_trades: readiness?.closed_usable }] },
    },
    {
      label: 'REALIZED', value: realizedPnl != null ? fmt$(realizedPnl, 0) : '—',
      stale: journalStale ? journalAgeMark : null,
      color: realizedPnl == null ? 'var(--text3)' : realizedPnl >= 0 ? BB.green : BB.red,
      tip: `All closed P&L incl. long-term trims of old buy-and-hold lots${longTermTrimPnl ? ` (${fmt$(longTermTrimPnl, 0)} of it is long-term trims)` : ''}${journalLastClose ? ` · last close ${journalLastClose}` : ''}${journalRefreshedMark}. Trading-only P&L is ${journalPnl != null ? fmt$(journalPnl, 0) : '—'}.`,
      drill: { title: 'Realized P&L (all closed)', subtitle: `Includes long-term position trims — not just trading${journalLastClose ? ` · through ${journalLastClose}` : ''}`, endpoint: '/api/v2/overview',
        rows: [{ realized_pnl: realizedPnl, realized_trades: realizedCount, long_term_trim_pnl: longTermTrimPnl, trading_pnl: overview?.journal?.total_pnl, trading_trades: overview?.journal?.trade_count, basis: overview?.journal?.basis, last_close_date: overview?.journal?.last_close_date, last_ingested_at: overview?.journal?.last_ingested_at }] },
    },
    {
      label: 'REGIME', value: regimeLabel ? `${regimeLabel.replace(/_/g, ' ')}${regimeConf ? ` ${Math.round(regimeConf * 100)}%` : ''}` : '—',
      color: regimeLabel === 'risk_off' ? BB.red : regimeLabel === 'risk_on' ? BB.green : BB.amber,
      tip: `Market regime from /api/v2/risk-regime/latest — weighs trend, breadth, and volatility signals into a risk-on/risk-off label with confidence.`,
      drill: { title: 'Market Regime', subtitle: 'From /api/v2/risk-regime/latest', endpoint: '/api/v2/risk-regime/latest',
        rows: regime ? [{ regime_label: regime.regime_label, confidence: regime.confidence, volatility_state: regime.volatility_state, trend_state: regime.trend_state, breadth_state: regime.breadth_state, summary: regime.summary }] : [] },
    },
    {
      label: 'VIX', value: vix != null ? Number(vix).toFixed(1) : '—',
      color: vix == null ? 'var(--text3)' : vix >= 25 ? BB.red : vix >= 18 ? BB.amber : BB.green,
      tip: `CBOE Volatility Index. Green <18 (low fear), amber 18-25 (elevated), red ≥25 (high fear). Sourced from latest Trade AI scan.`,
      drill: { title: 'VIX', subtitle: 'Volatility index (from latest Trade AI run)', endpoint: '/api/v2/trade-ai',
        rows: tradeAi ? [{ vix: tradeAi.vix, market_regime: tradeAi.market_regime, run_label: tradeAi.run_label }] : [] },
    },
    {
      label: 'SETUPS · LATEST RUN',
      value: setupsValue,
      // Extra amber mark when value already contains STALE (keeps label chip + as_of visible).
      stale: scanStale ? `${setupsAsOfMark || ' · stale'}` : null,
      asOf: setupsFresh.asOf,
      color: scanStale ? BB.amber : goCount > 0 ? BB.green : 'var(--text3)',
      tip: scanStale
        ? `Scanner surface is STALE (${setupsFresh.reason || 'prior/empty cache'}). ${setupsRun}${setupsAsOfMark}. HTTP 200 is not a live claim — Trading → Trade AI shows the same payload.`
        : 'Latest scanner run only — Trading → Trade AI shows the full scan universe (today + yesterday, all runs)',
      drill: { title: 'Trade Setups', subtitle: scanStale ? (setupsFresh.surfaceLabel || `STALE — last ${setupsRun}`) : 'Latest scanner run only — Trading → Trade AI shows the full scan universe (today + yesterday, all runs)', endpoint: '/api/v2/trade-ai',
        rows: tradeAi ? [{ scope: scanStale ? 'stale' : 'latest run only', go_count: tradeAi.go_count, wait_count: tradeAi.wait_count, avoid_count: tradeAi.avoid_count, universe_go: tradeAi.universe_go, universe_wait: tradeAi.universe_wait, universe_nogo: tradeAi.universe_nogo, run_label: tradeAi.run_label, run_date: tradeAi.run_date, cached_at: tradeAi.cached_at, cache_age_sec: tradeAi.cache_age_sec, stale: tradeAi.stale, surface_stale: setupsFresh.stale, surface_reason: setupsFresh.reason, vix: tradeAi.vix, market_regime: tradeAi.market_regime, run_health_status: tradeAi.run_health_status }] : [] },
    },
  ]

  return (
    <div className="metric-strip" style={{ display: 'flex', flexDirection: 'column', background: 'var(--bg0)', borderBottom: '1px solid var(--border)', flexShrink: 0 }}>
    <div style={{ display: 'flex', alignItems: 'center', gap: 0, padding: '8px 16px 4px' }}>
      <div style={{ marginRight: 24, whiteSpace: 'nowrap' }}>
        <div style={{ fontSize: TYPE.md, fontWeight: 700, color: T.link }}>Command Center v3</div>
        {priceStamp && (
          <div
            title={`Holdings repriced via ${overview?.pricing?.reprice_source ?? overview?.reprice_source ?? 'finviz'} · /api/v2/overview`}
            onClick={() => onDrill({ title: 'Price Freshness', subtitle: priceStamp, endpoint: '/api/v2/overview',
              rows: overview?.pricing ? [overview.pricing] : [{ last_repriced: overview?.last_repriced, reprice_source: overview?.reprice_source }] })}
            style={{ fontSize: TYPE.xs, color: 'var(--text3)', marginTop: 2, cursor: 'pointer', maxWidth: 280 }}
          >{priceStamp}</div>
        )}
      </div>
      {tiles.map(t => (
        <div key={t.label}
          className="metric-strip-tile"
          title={(t as any).tip}
          onClick={() => onDrill(t.drill)}
          style={{ padding: '4px 20px', cursor: 'pointer', textAlign: 'center', borderRight: '1px solid var(--border)' }}
        >
          <div style={{ fontSize: TYPE.xs, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '.5px' }}>
            {t.label}{(t as any).stale && <span style={{ color: BB.amber, fontWeight: 800 }} data-surface-stale>{' '}⚠ STALE</span>}
          </div>
          <div style={{ fontSize: TYPE.lg, fontWeight: 700, color: t.color, fontFamily: 'monospace' }}>
            {t.value}{(t as any).stale && !String(t.value).includes('STALE') && <span style={{ fontSize: TYPE.xs, color: BB.amber }}>{(t as any).stale}</span>}
          </div>
          {(t as any).asOf && (
            <div style={{ fontSize: TYPE.xs, color: (t as any).stale ? BB.amber : 'var(--text3)', marginTop: 1 }} data-surface-as-of>
              {(t as any).asOfLabel || 'as_of'} {String((t as any).asOf).slice(0, 16).replace('T', ' ')}
              {(t as any).asOfNote ? ` · ${(t as any).asOfNote}` : ''}
            </div>
          )}
          {!(t as any).asOf && (t as any).undated && (
            <div style={{ fontSize: TYPE.xs, color: BB.amber, marginTop: 1 }} data-surface-as-of data-surface-undated>
              {(t as any).asOfLabel || 'as_of'} UNDATED
            </div>
          )}
        </div>
      ))}
      {approvals != null && approvals > 0 && (
        <div onClick={() => navigate('/')}
          title={`${approvals} pending approvals — Home → Action Inbox has CTAs to Risk and Trading`}
          style={{ marginLeft: 'auto', padding: '4px 12px', borderRadius: 6, fontSize: TYPE.xs, fontWeight: 700, cursor: 'pointer',
            background: BB.amberDim, color: BB.amber, marginRight: 8 }}>
          ⚑ {approvals} APPROVALS →
        </div>
      )}
      {healthWarn > 0 && (
        <div onClick={() => navigate('/health')}
          title={`${healthWarn} health finding(s) — open Health for remediate + coder dispatch`}
          style={{ padding: '4px 12px', borderRadius: 6, fontSize: TYPE.xs, fontWeight: 700, cursor: 'pointer',
            background: BB.redDim, color: BB.red, marginRight: 8 }}>
          ♥ {healthWarn} HEALTH →
        </div>
      )}
      <div
        title={gate?.operator_status_label || (operatorLive ? 'Schwab operator live via standing unlock + per-order 2FA' : 'Autonomous Alpaca live gate not passed')}
        style={{
        marginLeft: approvals != null && approvals > 0 ? 0 : 'auto', padding: '4px 14px', borderRadius: 6, fontSize: TYPE.xs, fontWeight: 700,
        background: operatorLive ? BB.greenDim : liveBadgeBlocked ? BB.amberDim : BB.greenDim,
        color: operatorLive ? BB.green : liveBadgeBlocked ? BB.amber : BB.green,
      }}>
        {liveBadge}
      </div>
    </div>
    </div>
  )
}
