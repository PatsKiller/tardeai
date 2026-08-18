import { useApi } from '../hooks/useApi'
import { useNavigate } from 'react-router-dom'
import { fmt$ } from '../lib/format'
import { pricingStampLine } from '../lib/pricingStamp'
import { isScanStale, runLabel } from '../lib/homeLabels'
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
  const scanStale = isScanStale(tradeAi?.run_date)
  const setupsRun = runLabel(tradeAi?.run_label ?? tradeAi?.latest_run_label, tradeAi?.run_date)
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
  const journalStaleDays = (() => {
    if (!journalLastClose) return null
    const ms = Date.now() - new Date(String(journalLastClose)).getTime()
    return isFinite(ms) && ms > 0 ? Math.floor(ms / 86_400_000) : null
  })()
  const journalStale = journalStaleDays != null && journalStaleDays > 7
  const journalAgeMark = journalStale ? ` · ${journalStaleDays}d old` : ''
  const vix = tradeAi?.vix
  const approvals = overview?.pending_approvals ?? overview?.approvals_count
  const priceStamp = pricingStampLine(overview?.pricing ?? { last_repriced: overview?.last_repriced, reprice_source: overview?.reprice_source })

  const setupsValue = (() => {
    if (scanStale) return `STALE · ${setupsRun}`
    if (tradeAi?.latest_run_label || tradeAi?.run_label) {
      return `${goCount} GO · ${waitCount} WAIT · ${avoidCount} NOGO`
    }
    return '— before first run'
  })()

  const tiles = [
    {
      label: 'PORTFOLIO', value: portfolioVal != null ? fmt$(portfolioVal, 0) : '—',
      color: 'var(--text0)',
      tip: `Total portfolio equity across all linked broker accounts (Schwab, Fidelity, Alpaca, Moomoo). Refreshes every 2 min via /api/v2/overview.`,
      drill: { title: 'Portfolio', subtitle: 'From /api/v2/overview', endpoint: '/api/v2/overview',
        rows: overview ? [{ portfolio_value: overview.portfolio_value, total_cash: overview.total_cash, position_count: overview.position_count, today_change: overview.today_change, today_pct: overview.today_pct, as_of: overview.as_of }] : [] },
    },
    {
      label: 'TODAY', value: todayChange != null ? `${todayChange >= 0 ? '+' : ''}${fmt$(todayChange, 0)}${todayPct != null ? ` ${todayPct >= 0 ? '+' : ''}${todayPct}%` : ''}` : '—',
      color: todayChange == null ? 'var(--text3)' : todayChange >= 0 ? BB.green : BB.red,
      drill: { title: "Today's Move", subtitle: 'By account · from /api/v2/overview', endpoint: '/api/v2/overview',
        rows: overview ? [
          { today_change: overview.today_change, today_pct: overview.today_pct, portfolio_value: overview.portfolio_value, as_of: overview.as_of },
          ...Object.entries(overview.today_by_account ?? {})
            .sort((a: any, b: any) => Math.abs(b[1].change) - Math.abs(a[1].change))
            .map(([acct, d]: any) => ({
              account: acct, today_change: d.change,
              today_pct: d.pct != null ? `${d.pct >= 0 ? '+' : ''}${d.pct}%` : null,
              account_value: d.value, top_movers: d.top_movers || null,
            })),
        ] : [] },
      tip: `Today's net change ($ and %) across all linked accounts. Click to see per-account breakdown. Refreshes every 2 min.`,
    },
    {
      label: 'TRADING', value: winRate != null ? `${winRate}%${winTrades ? ` · ${winTrades}` : ''}${journalPnl != null ? ` · ${fmt$(journalPnl, 0)}` : ''}` : '—',
      stale: journalStale ? journalAgeMark : null,
      color: winRate != null && winRate >= 50 ? BB.green : winRate != null ? BB.amber : 'var(--text3)',
      tip: `Active trading only (day + swing), broker round-trips${journalLastClose ? ` · through ${journalLastClose}` : ''}. Excludes long-term trims of old holds — those are in REALIZED. Win rate excludes $0 scratches.${journalStale ? ` STALE because trade_closed last close is ${journalLastClose} — refresh via schwab journal ingest (broker history → local journal), not a dead UI.` : ''}`,
      drill: { title: 'Trading (active)', subtitle: `Day + swing round-trips, excludes long-term position trims${journalLastClose ? ` · through ${journalLastClose}` : ''} · REALIZED tile shows all closed incl. trims`, endpoint: '/api/v2/overview',
        rows: [{ trading_win_rate: overview?.journal?.win_rate, trading_trades: overview?.journal?.trade_count, trading_pnl: overview?.journal?.total_pnl, realized_win_rate: overview?.journal?.realized_win_rate, realized_trades: realizedCount, realized_pnl: realizedPnl, long_term_trim_pnl: longTermTrimPnl, basis: overview?.journal?.basis, last_close_date: overview?.journal?.last_close_date, paper_readiness_win_rate: readiness?.win_rate, paper_usable_trades: readiness?.closed_usable }] },
    },
    {
      label: 'REALIZED', value: realizedPnl != null ? fmt$(realizedPnl, 0) : '—',
      stale: journalStale ? journalAgeMark : null,
      color: realizedPnl == null ? 'var(--text3)' : realizedPnl >= 0 ? BB.green : BB.red,
      tip: `All closed P&L incl. long-term trims of old buy-and-hold lots${longTermTrimPnl ? ` (${fmt$(longTermTrimPnl, 0)} of it is long-term trims)` : ''}${journalLastClose ? ` · through ${journalLastClose}` : ''}. Trading-only P&L is ${journalPnl != null ? fmt$(journalPnl, 0) : '—'}.${journalStale ? ` Not a crashed page — last broker-verified close is ${journalLastClose}.` : ''}`,
      drill: { title: 'Realized P&L (all closed)', subtitle: `Includes long-term position trims — not just trading${journalLastClose ? ` · through ${journalLastClose}` : ''}`, endpoint: '/api/v2/overview',
        rows: [{ realized_pnl: realizedPnl, realized_trades: realizedCount, long_term_trim_pnl: longTermTrimPnl, trading_pnl: overview?.journal?.total_pnl, trading_trades: overview?.journal?.trade_count, basis: overview?.journal?.basis, last_close_date: overview?.journal?.last_close_date }] },
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
      stale: scanStale ? ' · prior session' : null,
      color: scanStale ? BB.amber : goCount > 0 ? BB.green : 'var(--text3)',
      tip: scanStale
        ? `Latest scan is from a prior session (${setupsRun}). Counts may be zero because the scanner has not run today — not because the universe is empty. Trading → Trade AI shows the full scan history.`
        : 'Latest scanner run only — Trading → Trade AI shows the full scan universe (today + yesterday, all runs)',
      drill: { title: 'Trade Setups', subtitle: scanStale ? `STALE — last ${setupsRun}` : 'Latest scanner run only — Trading → Trade AI shows the full scan universe (today + yesterday, all runs)', endpoint: '/api/v2/trade-ai',
        rows: tradeAi ? [{ scope: scanStale ? 'stale prior session' : 'latest run only', go_count: tradeAi.go_count, wait_count: tradeAi.wait_count, avoid_count: tradeAi.avoid_count, universe_go: tradeAi.universe_go, universe_wait: tradeAi.universe_wait, universe_nogo: tradeAi.universe_nogo, run_label: tradeAi.run_label, run_date: tradeAi.run_date, vix: tradeAi.vix, market_regime: tradeAi.market_regime, run_health_status: tradeAi.run_health_status }] : [] },
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
            {t.label}{(t as any).stale && <span style={{ color: BB.amber, fontWeight: 800 }}>{' '}⚠ STALE</span>}
          </div>
          <div style={{ fontSize: TYPE.lg, fontWeight: 700, color: t.color, fontFamily: 'monospace' }}>
            {t.value}{(t as any).stale && !String(t.value).includes('STALE') && <span style={{ fontSize: TYPE.xs, color: BB.amber }}>{(t as any).stale}</span>}
          </div>
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
