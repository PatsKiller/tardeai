import { useApi } from '../hooks/useApi'
import { useNavigate } from 'react-router-dom'
import { fmt$ } from '../lib/format'
import { pricingStampLine } from '../lib/pricingStamp'
import type { DrillContext } from './DetailDrawer'

interface Props {
  onDrill: (ctx: DrillContext) => void
}

export default function MetricStrip({ onDrill }: Props) {
  const navigate = useNavigate()
  const { data: overview } = useApi<any>('/api/v2/overview', 60_000)
  const { data: readiness } = useApi<any>('/api/v2/paper-trade-readiness', 120_000)
  const { data: regime } = useApi<any>('/api/v2/risk-regime/latest', 120_000)
  const { data: tradeAi } = useApi<any>('/api/v2/trade-ai', 60_000)
  const { data: gate } = useApi<any>('/api/v2/live-trading-gate', 120_000)

  const portfolioVal = overview?.portfolio_value
  // Headline win rate = the overall journal win rate (matches the Home card). The paper-readiness
  // win rate (gate-specific, ~24 paper trades) is a different metric and stays in the readiness/Trading context.
  const winRate = overview?.journal?.win_rate ?? readiness?.win_rate
  const winTrades = overview?.journal?.trade_count
  const regimeLabel = regime?.regime_label ?? '—'
  const regimeConf = regime?.confidence
  const goCount = tradeAi?.go_count ?? 0
  const waitCount = tradeAi?.wait_count ?? 0
  const avoidCount = tradeAi?.avoid_count ?? 0
  const operatorLive = !!gate?.operator_live_via_2fa_allowed
  const autoLive = gate?.status === 'AUTHORIZED'
  const liveBadge = operatorLive ? '2FA LIVE' : autoLive ? 'AUTO LIVE' : 'AUTO BLOCKED'
  const liveBadgeBlocked = !operatorLive && !autoLive
  // v2-parity header fields
  const todayChange = overview?.today_change
  const todayPct = overview?.today_pct
  const journalPnl = overview?.journal?.total_pnl
  const vix = tradeAi?.vix
  const runLabel = tradeAi?.run_label
  const approvals = overview?.pending_approvals ?? overview?.approvals_count
  const priceStamp = pricingStampLine(overview?.pricing ?? { last_repriced: overview?.last_repriced, reprice_source: overview?.reprice_source })

  const tiles = [
    {
      label: 'PORTFOLIO', value: portfolioVal != null ? fmt$(portfolioVal, 0) : '—',
      color: 'var(--text0)',
      drill: { title: 'Portfolio', subtitle: 'From /api/v2/overview', endpoint: '/api/v2/overview',
        rows: overview ? [{ portfolio_value: overview.portfolio_value, total_cash: overview.total_cash, position_count: overview.position_count, today_change: overview.today_change, today_pct: overview.today_pct, as_of: overview.as_of }] : [] },
    },
    {
      label: 'TODAY', value: todayChange != null ? `${todayChange >= 0 ? '+' : ''}${fmt$(todayChange, 0)}${todayPct != null ? ` ${todayPct >= 0 ? '+' : ''}${todayPct}%` : ''}` : '—',
      color: todayChange == null ? 'var(--text3)' : todayChange >= 0 ? '#22c55e' : '#ef4444',
      drill: { title: "Today's Move", subtitle: 'By account · from /api/v2/overview', endpoint: '/api/v2/overview',
        rows: overview ? [
          { today_change: overview.today_change, today_pct: overview.today_pct, portfolio_value: overview.portfolio_value, as_of: overview.as_of },
          // per-account breakdown (operator 2026-06-12), biggest mover first
          ...Object.entries(overview.today_by_account ?? {})
            .sort((a: any, b: any) => Math.abs(b[1].change) - Math.abs(a[1].change))
            .map(([acct, d]: any) => ({
              account: acct, today_change: d.change,
              today_pct: d.pct != null ? `${d.pct >= 0 ? '+' : ''}${d.pct}%` : null,
              account_value: d.value, top_movers: d.top_movers || null,
            })),
        ] : [] },
    },
    {
      label: 'WIN RATE', value: winRate != null ? `${winRate}%${winTrades ? ` · ${winTrades}` : ''}` : '—',
      color: winRate != null && winRate >= 50 ? '#22c55e' : winRate != null ? '#f59e0b' : 'var(--text3)',
      drill: { title: 'Win Rate', subtitle: 'Journal (all closed) · paper-readiness shown separately', endpoint: '/api/v2/overview',
        rows: [{ journal_win_rate: overview?.journal?.win_rate, journal_trades: overview?.journal?.trade_count, journal_pnl: overview?.journal?.total_pnl, paper_readiness_win_rate: readiness?.win_rate, paper_usable_trades: readiness?.closed_usable, paper_level: readiness?.level }] },
    },
    {
      label: 'JOURNAL P&L', value: journalPnl != null ? fmt$(journalPnl, 0) : '—',
      color: journalPnl == null ? 'var(--text3)' : journalPnl >= 0 ? '#22c55e' : '#ef4444',
      drill: { title: 'Journal P&L', subtitle: 'Realized P&L across closed journal trades', endpoint: '/api/v2/overview',
        rows: [{ journal_total_pnl: overview?.journal?.total_pnl, journal_trades: overview?.journal?.trade_count, journal_win_rate: overview?.journal?.win_rate }] },
    },
    {
      label: 'REGIME', value: regimeLabel ? `${regimeLabel.replace(/_/g, ' ')}${regimeConf ? ` ${Math.round(regimeConf * 100)}%` : ''}` : '—',
      color: regimeLabel === 'risk_off' ? '#ef4444' : regimeLabel === 'risk_on' ? '#22c55e' : '#f59e0b',
      drill: { title: 'Market Regime', subtitle: 'From /api/v2/risk-regime/latest', endpoint: '/api/v2/risk-regime/latest',
        rows: regime ? [{ regime_label: regime.regime_label, confidence: regime.confidence, volatility_state: regime.volatility_state, trend_state: regime.trend_state, breadth_state: regime.breadth_state, summary: regime.summary }] : [] },
    },
    {
      label: 'VIX', value: vix != null ? Number(vix).toFixed(1) : '—',
      color: vix == null ? 'var(--text3)' : vix >= 25 ? '#ef4444' : vix >= 18 ? '#f59e0b' : '#22c55e',
      drill: { title: 'VIX', subtitle: 'Volatility index (from latest Trade AI run)', endpoint: '/api/v2/trade-ai',
        rows: tradeAi ? [{ vix: tradeAi.vix, market_regime: tradeAi.market_regime, run_label: tradeAi.run_label }] : [] },
    },
    {
      label: 'SETUPS', value: `${goCount} GO · ${waitCount} WAIT · ${avoidCount} NOGO`,
      color: goCount > 0 ? '#22c55e' : 'var(--text3)',
      drill: { title: 'Trade Setups', subtitle: 'From /api/v2/trade-ai', endpoint: '/api/v2/trade-ai',
        rows: tradeAi ? [{ go_count: tradeAi.go_count, wait_count: tradeAi.wait_count, avoid_count: tradeAi.avoid_count, run_label: tradeAi.run_label, vix: tradeAi.vix, market_regime: tradeAi.market_regime, run_health_status: tradeAi.run_health_status }] : [] },
    },
    {
      label: 'LAST RUN', value: runLabel ? `${runLabel}` : '—',
      color: 'var(--text2)',
      drill: { title: 'Last Trade AI Run', subtitle: 'Latest orchestrator scan', endpoint: '/api/v2/trade-ai',
        rows: tradeAi ? [{ run_label: tradeAi.run_label, run_health_status: tradeAi.run_health_status, go_count: tradeAi.go_count, wait_count: tradeAi.wait_count }] : [] },
    },
  ]

  return (
    <div className="metric-strip" style={{ display: 'flex', flexDirection: 'column', background: 'var(--bg0)', borderBottom: '1px solid var(--border)', flexShrink: 0 }}>
    <div style={{ display: 'flex', alignItems: 'center', gap: 0, padding: '8px 16px 4px' }}>
      <div style={{ marginRight: 24, whiteSpace: 'nowrap' }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: '#60a5fa' }}>Command Center v3</div>
        {priceStamp && (
          <div
            title={`Holdings repriced via ${overview?.pricing?.reprice_source ?? overview?.reprice_source ?? 'finviz'} · /api/v2/overview`}
            onClick={() => onDrill({ title: 'Price Freshness', subtitle: priceStamp, endpoint: '/api/v2/overview',
              rows: overview?.pricing ? [overview.pricing] : [{ last_repriced: overview?.last_repriced, reprice_source: overview?.reprice_source }] })}
            style={{ fontSize: 8, color: 'var(--text3)', marginTop: 2, cursor: 'pointer', maxWidth: 280 }}
          >{priceStamp}</div>
        )}
      </div>
      {tiles.map(t => (
        <div key={t.label}
          onClick={() => onDrill(t.drill)}
          style={{ padding: '4px 20px', cursor: 'pointer', textAlign: 'center', borderRight: '1px solid var(--border)' }}
        >
          <div style={{ fontSize: 8, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '.5px' }}>{t.label}</div>
          <div style={{ fontSize: 16, fontWeight: 700, color: t.color, fontFamily: 'monospace' }}>{t.value}</div>
        </div>
      ))}
      {approvals != null && approvals > 0 && (
        <div onClick={() => navigate('/')}
          title={`${approvals} pending approvals (stop-triggered + governance) — go to Home → Action Inbox to review (read-only drill to source)`}
          style={{ marginLeft: 'auto', padding: '4px 12px', borderRadius: 6, fontSize: 10, fontWeight: 700, cursor: 'pointer',
            background: 'rgba(245,158,11,.15)', color: '#f59e0b', marginRight: 8 }}>
          ⚑ {approvals} APPROVALS →
        </div>
      )}
      <div
        title={gate?.operator_status_label || (operatorLive ? 'Schwab operator live via standing unlock + per-order 2FA' : 'Autonomous Alpaca live gate not passed')}
        style={{
        marginLeft: approvals != null && approvals > 0 ? 0 : 'auto', padding: '4px 14px', borderRadius: 6, fontSize: 10, fontWeight: 700,
        background: operatorLive ? 'rgba(34,197,94,.15)' : liveBadgeBlocked ? 'rgba(245,158,11,.15)' : 'rgba(34,197,94,.15)',
        color: operatorLive ? '#22c55e' : liveBadgeBlocked ? '#f59e0b' : '#22c55e',
      }}>
        {liveBadge}
      </div>
    </div>
    </div>
  )
}
