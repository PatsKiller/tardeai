import { useApi } from '../hooks/useApi'
import { fmt$ } from '../lib/format'
import type { DrillContext } from './DetailDrawer'

interface Props {
  onDrill: (ctx: DrillContext) => void
}

export default function MetricStrip({ onDrill }: Props) {
  const { data: overview } = useApi<any>('/api/v2/overview', 60_000)
  const { data: readiness } = useApi<any>('/api/v2/paper-trade-readiness', 120_000)
  const { data: regime } = useApi<any>('/api/v2/risk-regime/latest', 120_000)
  const { data: tradeAi } = useApi<any>('/api/v2/trade-ai', 60_000)
  const { data: gate } = useApi<any>('/api/v2/live-trading-gate', 120_000)

  const portfolioVal = overview?.portfolio_value
  const winRate = readiness?.win_rate
  const regimeLabel = regime?.regime_label ?? '—'
  const regimeConf = regime?.confidence
  const goCount = tradeAi?.go_count ?? 0
  const waitCount = tradeAi?.wait_count ?? 0
  const avoidCount = tradeAi?.avoid_count ?? 0
  const liveStatus = gate?.status ?? 'PAPER_ONLY'
  const isBlocked = liveStatus !== 'LIVE'

  const tiles = [
    {
      label: 'PORTFOLIO', value: portfolioVal != null ? fmt$(portfolioVal, 0) : '—',
      color: 'var(--text0)',
      drill: { title: 'Portfolio', subtitle: 'From /api/v2/overview', endpoint: '/api/v2/overview',
        rows: overview ? [{ portfolio_value: overview.portfolio_value, total_cash: overview.total_cash, position_count: overview.position_count, today_change: overview.today_change, today_pct: overview.today_pct, as_of: overview.as_of }] : [] },
    },
    {
      label: 'WIN RATE', value: winRate != null ? `${winRate}%` : '—',
      color: winRate != null && winRate >= 50 ? '#22c55e' : winRate != null ? '#f59e0b' : 'var(--text3)',
      drill: { title: 'Win Rate', subtitle: 'From /api/v2/paper-trade-readiness', endpoint: '/api/v2/paper-trade-readiness',
        rows: readiness ? [{ win_rate: readiness.win_rate, profit_factor: readiness.profit_factor, expectancy: readiness.expectancy, closed_usable: readiness.closed_usable, level: readiness.level }] : [] },
    },
    {
      label: 'REGIME', value: regimeLabel ? `${regimeLabel.replace(/_/g, ' ')}${regimeConf ? ` ${Math.round(regimeConf * 100)}%` : ''}` : '—',
      color: regimeLabel === 'risk_off' ? '#ef4444' : regimeLabel === 'risk_on' ? '#22c55e' : '#f59e0b',
      drill: { title: 'Market Regime', subtitle: 'From /api/v2/risk-regime/latest', endpoint: '/api/v2/risk-regime/latest',
        rows: regime ? [{ regime_label: regime.regime_label, confidence: regime.confidence, volatility_state: regime.volatility_state, trend_state: regime.trend_state, breadth_state: regime.breadth_state, summary: regime.summary }] : [] },
    },
    {
      label: 'SETUPS', value: `${goCount}/${waitCount}/${avoidCount}`,
      color: goCount > 0 ? '#22c55e' : 'var(--text3)',
      drill: { title: 'Trade Setups', subtitle: 'From /api/v2/trade-ai', endpoint: '/api/v2/trade-ai',
        rows: tradeAi ? [{ go_count: tradeAi.go_count, wait_count: tradeAi.wait_count, avoid_count: tradeAi.avoid_count, run_label: tradeAi.run_label, vix: tradeAi.vix, market_regime: tradeAi.market_regime, run_health_status: tradeAi.run_health_status }] : [] },
    },
  ]

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 0, padding: '8px 16px', background: 'var(--bg0)', borderBottom: '1px solid var(--border)', flexShrink: 0 }}>
      <div style={{ fontSize: 14, fontWeight: 700, color: '#60a5fa', marginRight: 24, whiteSpace: 'nowrap' }}>Command Center v3</div>
      {tiles.map(t => (
        <div key={t.label}
          onClick={() => onDrill(t.drill)}
          style={{ padding: '4px 20px', cursor: 'pointer', textAlign: 'center', borderRight: '1px solid var(--border)' }}
        >
          <div style={{ fontSize: 8, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '.5px' }}>{t.label}</div>
          <div style={{ fontSize: 16, fontWeight: 700, color: t.color, fontFamily: 'monospace' }}>{t.value}</div>
        </div>
      ))}
      <div style={{
        marginLeft: 'auto', padding: '4px 14px', borderRadius: 6, fontSize: 10, fontWeight: 700,
        background: isBlocked ? 'rgba(239,68,68,.15)' : 'rgba(34,197,94,.15)',
        color: isBlocked ? '#ef4444' : '#22c55e',
      }}>
        {isBlocked ? 'LIVE BLOCKED' : 'LIVE ENABLED'}
      </div>
    </div>
  )
}
